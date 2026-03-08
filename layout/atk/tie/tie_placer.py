"""Tie cell placement engine for IHP SG13G2.

Strip-based per-device algorithm:
  - One ntap per PMOS device (above, in reserved tie strip)
  - One ptap per NMOS device (below, in reserved tie strip)
  - X-aligned to device source pin
  - M1 bridge connects tie M1 pad to device source via M1
  - NWell extension (ntap only) merges with device NWell

Data sources:
  - device_lib.json: pin positions, implant bounds, classification
  - netlist.json constraints.tie_config: src_pin, cont config (design choices)

All coordinates in nm (dbu=0.001µm).
"""

from ..pdk import (
    UM, VIA_CLEAR, VIA1_PAD_M1, M1_THIN, M1_MIN_S,
)
from ..device import (
    load_device_lib, get_device_pins_nm, get_nwell_tie_info, get_gate_info,
    is_mosfet,
)
from ..paths import DEVICE_LIB_JSON

# DRC constants (nm) — from IHP SG13G2 design manual
CNT_SZ = 160       # Cnt.a: contact size
CNT_SP = 180       # Cnt.b: contact spacing
ACT_ENC = 70       # Cnt.c: Activ enclosure of Cont
M1_ENC = 50        # M1.c1: M1 endcap enclosure of Cont
NW_E = 240         # NW.e: NWell enclosure of N+ Activ
PSD_CLR = 50       # pSD clearance margin
PSD_C1 = 30        # pSD.c1: pSD enclosure of P+Activ in PWell
ACT_B = 210        # Act.b: min Activ space or notch
PSD_D = 180        # pSD.d: min pSD space
GAT_D = 70         # Gat.d: min GatPoly space to Activ
CNT_F = 110        # Cnt.f: min Cont on Activ space to GatPoly
CNT_G1 = 90        # Cnt.g1: min pSD space to Cont on nSD-Activ
PSD_D1 = 30        # pSD.d1: min pSD space to N+Activ in NWell
LU_A_MAX = 20000   # LU.a: max P+Activ to ntap distance in NWell
NBULAY_THRESHOLD = 2990  # NWell width that triggers nBuLay generation

_device_lib = load_device_lib(DEVICE_LIB_JSON)


def _snap5(nm):
    """Snap nm value to 5nm grid."""
    return ((nm + 2) // 5) * 5


def _half_extents_2x2():
    """Half-extents for 2×2 contact array."""
    half_pitch = (CNT_SZ + CNT_SP) // 2  # 170
    act_hx = half_pitch + CNT_SZ // 2 + ACT_ENC   # 320
    m1_hx = half_pitch + CNT_SZ // 2 + M1_ENC     # 300
    return act_hx, m1_hx


def _half_extents_1x2():
    """Half-extents for 1×2 contact array (single column, 2 rows)."""
    act_hx = CNT_SZ // 2 + ACT_ENC   # 150
    m1_hx = CNT_SZ // 2 + M1_ENC     # 130
    return act_hx, m1_hx


def _half_extents_y():
    """Y half-extents (always 2 rows of contacts)."""
    half_pitch_y = (CNT_SZ + CNT_SP) // 2  # 170
    act_hy = half_pitch_y + CNT_SZ // 2 + ACT_ENC  # 320
    m1_hy = half_pitch_y + CNT_SZ // 2 + M1_ENC    # 300
    return act_hy, m1_hy


class TiePlacer:
    """Compute tie cell positions and geometry for all MOSFET devices."""

    def __init__(self, placement, device_lib, tie_templates, netlist):
        self.placement = placement
        self.device_lib = device_lib
        self.tie_templates = tie_templates
        self.netlist = netlist
        self.instances = placement['instances']
        self.tie_strips = placement['tie_strips']
        self.nwell_islands = placement['nwell_islands']
        self.constraints = netlist['constraints']

        self._nwell_nets = {}
        for d in netlist['devices']:
            if d['has_nwell']:
                self._nwell_nets[d['name']] = d['nwell_net']

        # Pin → net map for checking if source is on tie net (gnd)
        self._pin_net_map = {}
        for net_info in netlist.get('nets', []):
            net_name = net_info['name']
            for pin in net_info.get('pins', []):
                self._pin_net_map[pin] = net_name

        self._m1_obstacles = self._build_m1_obstacle_map()
        self._activ_obstacles = self._build_activ_obstacle_map()
        self._gatpoly_obstacles = self._build_gatpoly_obstacle_map()
        self._psd_obstacles = self._build_psd_obstacle_map()
        self.ties = []
        self.nwell_extensions = []

    def _inst_origin(self, inst_name):
        """PCell origin (absolute nm) for an instance.

        placement.json stores bbox left-bottom (µm).
        PCell origin = placement_pos - bbox_min.
        """
        inst = self.instances[inst_name]
        bbox = self.device_lib[inst['type']]['bbox']
        px = round(inst['x_um'] * UM)
        py = round(inst['y_um'] * UM)
        return px - bbox[0], py - bbox[1]

    def _build_m1_obstacle_map(self):
        """Build M1 shapes for all devices in absolute nm coordinates."""
        obstacles = {}
        for name, inst in self.instances.items():
            dev_type = inst['type']
            if not is_mosfet(_device_lib, dev_type):
                continue
            origin_x, origin_y = self._inst_origin(name)
            m1_shapes = self.device_lib[dev_type]['shapes_by_layer'].get('M1_8_0', [])
            obstacles[name] = [
                [origin_x + s[0], origin_y + s[1], origin_x + s[2], origin_y + s[3]]
                for s in m1_shapes
            ]
        return obstacles

    def _build_activ_obstacle_map(self):
        """Build Activ shapes for all devices in absolute nm coordinates.

        Used to prevent tie Activ+Contact from overlapping any device's
        Active region (which would cause Cnt.j / Gat.a1 DRC violations).
        """
        obstacles = {}
        for name, inst in self.instances.items():
            dev_type = inst['type']
            if not is_mosfet(_device_lib, dev_type):
                continue
            origin_x, origin_y = self._inst_origin(name)
            activ_shapes = self.device_lib[dev_type]['shapes_by_layer'].get('Activ_1_0', [])
            obstacles[name] = [
                [origin_x + s[0], origin_y + s[1], origin_x + s[2], origin_y + s[3]]
                for s in activ_shapes
            ]
        return obstacles

    def _build_gatpoly_obstacle_map(self):
        """Build GatPoly bounding boxes for all MOSFET devices (abs nm)."""
        obstacles = {}
        for name, inst in self.instances.items():
            dev_type = inst['type']
            if not is_mosfet(_device_lib, dev_type):
                continue
            origin_x, origin_y = self._inst_origin(name)
            gp_shapes = self.device_lib[dev_type]['shapes_by_layer'].get(
                'GatPoly_5_0', [])
            obstacles[name] = [
                [origin_x + s[0], origin_y + s[1],
                 origin_x + s[2], origin_y + s[3]]
                for s in gp_shapes
            ]
        return obstacles

    def _build_psd_obstacle_map(self):
        """Build pSD bounding boxes for all MOSFET devices (abs nm)."""
        obstacles = {}
        for name, inst in self.instances.items():
            dev_type = inst['type']
            if not is_mosfet(_device_lib, dev_type):
                continue
            origin_x, origin_y = self._inst_origin(name)
            psd_shapes = self.device_lib[dev_type]['shapes_by_layer'].get(
                'pSD_14_0', [])
            obstacles[name] = [
                [origin_x + s[0], origin_y + s[1],
                 origin_x + s[2], origin_y + s[3]]
                for s in psd_shapes
            ]
        return obstacles

    def _clamp_act_cy_for_clearance(self, act_cy, tie_cx, act_hx, act_hy,
                                     skip_device):
        """Clamp act_cy so tie Activ/contacts don't violate GatPoly/pSD DRC.

        Checks ALL devices (except skip_device) for:
          - Gat.d: tie Activ must be ≥70nm from any GatPoly
          - Cnt.f: tie Cont must be ≥110nm from any GatPoly on Activ
          - pSD.e/Cnt.g1: tie nSD-Activ/Cont must not overlap device pSD
        """
        half_pitch_y = (CNT_SZ + CNT_SP) // 2
        upper_cont_dy = half_pitch_y + CNT_SZ // 2  # 250nm

        for dev_name, gp_shapes in self._gatpoly_obstacles.items():
            if dev_name == skip_device:
                continue
            for gp in gp_shapes:
                # X overlap check (tie Activ vs GatPoly)
                if tie_cx + act_hx <= gp[0] or tie_cx - act_hx >= gp[2]:
                    continue
                # GatPoly below tie → cap act_cy from below (min)
                # GatPoly above tie → cap act_cy from above (max)
                if gp[3] <= act_cy:
                    # GatPoly is below: tie bottom must be above GatPoly top
                    min_cy = gp[3] + GAT_D + act_hy
                    min_cy_cnt = gp[3] + CNT_F + upper_cont_dy
                    lower = max(min_cy, min_cy_cnt)
                    if act_cy < lower:
                        act_cy = _snap5(lower)
                else:
                    # GatPoly is above: tie top must be below GatPoly bottom
                    max_cy = gp[1] - GAT_D - act_hy
                    max_cy_cnt = gp[1] - CNT_F - upper_cont_dy
                    upper = min(max_cy, max_cy_cnt)
                    if act_cy > upper:
                        act_cy = _snap5(upper)

        for dev_name, psd_shapes in self._psd_obstacles.items():
            if dev_name == skip_device:
                continue
            for psd in psd_shapes:
                # X overlap check
                if tie_cx + act_hx <= psd[0] or tie_cx - act_hx >= psd[2]:
                    continue
                # pSD below tie → tie bottom must clear pSD top
                if psd[3] <= act_cy:
                    lower = psd[3] + PSD_D1 + act_hy
                    lower_cnt = psd[3] + CNT_G1 + upper_cont_dy
                    lb = max(lower, lower_cnt)
                    if act_cy < lb:
                        act_cy = _snap5(lb)
                else:
                    # pSD above tie → tie top must clear pSD bottom
                    upper = psd[1] - PSD_D1 - act_hy
                    upper_cnt = psd[1] - CNT_G1 - upper_cont_dy
                    ub = min(upper, upper_cnt)
                    if act_cy > ub:
                        act_cy = _snap5(ub)

        return act_cy

    def _resolve_activ_clear_x(self, default_cx, act_rect, skip_device):
        """Shift tie X so its Activ does not overlap any device Activ.

        The margin must satisfy both Act.b (210nm Activ spacing) and
        pSD.d (180nm pSD spacing, with pSD extending PSD_C1=30nm beyond Activ).
        Required clearance = max(Act.b, pSD.d + PSD_C1) = max(210, 210) = 210nm.

        Args:
            default_cx: preferred tie center X (nm)
            act_rect: tie Activ rectangle [x1, y1, x2, y2] at default_cx
            skip_device: device whose Activ is same-net (skip)

        Returns: resolved center X (snapped to 5nm grid)
        """
        cx = default_cx
        act_hx = (act_rect[2] - act_rect[0]) // 2
        # Margin from tie Activ edge to device Activ edge:
        # Act.b = 210nm (Activ-to-Activ), pSD extends PSD_C1 beyond Activ
        # pSD.d = 180nm, so pSD needs 180 + 30 = 210nm from device Activ
        margin = max(ACT_B, PSD_D + PSD_C1)  # 210nm

        for dev_name, shapes in self._activ_obstacles.items():
            if dev_name == skip_device:
                continue
            for s in shapes:
                # Y overlap check
                if s[3] <= act_rect[1] or s[1] >= act_rect[3]:
                    continue
                # X overlap check (with margin)
                tie_left = cx - act_hx - margin
                tie_right = cx + act_hx + margin
                if tie_left < s[2] and tie_right > s[0]:
                    # Compute shift for both directions
                    shift_right = s[2] + margin + act_hx - cx
                    shift_left = cx - (s[0] - margin - act_hx)
                    if shift_right <= shift_left:
                        cx = _snap5(cx + shift_right)
                    else:
                        cx = _snap5(cx - shift_left)
        return cx

    def _check_m1_conflict(self, tie_m1_rect, skip_device=None):
        """Check if tie M1 rect (inflated by M1.b) conflicts with any device M1."""
        conflicts = []
        for name, shapes in self._m1_obstacles.items():
            if name == skip_device:
                continue
            for s in shapes:
                if (tie_m1_rect[0] < s[2] and tie_m1_rect[2] > s[0] and
                        tie_m1_rect[1] < s[3] and tie_m1_rect[3] > s[1]):
                    conflicts.append((name, s))
        return conflicts

    def _resolve_m1_clear_x(self, default_cx, m1_hx, m1_y_bot, m1_y_top, skip_device):
        """Find nearest X that clears all M1 obstacles for a tie.

        1D search: for each obstacle M1 shape that overlaps the tie in Y,
        compute the minimum X shift (left or right) to satisfy M1.b >= 180nm.
        Pick the direction with the smallest shift.

        Args:
            default_cx: preferred tie center X (nm)
            m1_hx: tie M1 pad half-width in X (nm)
            m1_y_bot: tie M1 pad bottom Y (nm)
            m1_y_top: tie M1 pad top Y (nm)
            skip_device: device whose M1 is same-net (skip)

        Returns: resolved center X (snapped to 5nm grid)
        """
        cx = default_cx
        for _name, shapes in self._m1_obstacles.items():
            if _name == skip_device:
                continue
            for s in shapes:
                # Y overlap check (exact, using tie M1 Y range)
                if s[3] <= m1_y_bot or s[1] >= m1_y_top:
                    continue
                # X conflict: tie M1 inflated by M1.b must not overlap obstacle
                tie_left = cx - m1_hx - M1_MIN_S
                tie_right = cx + m1_hx + M1_MIN_S
                if tie_left < s[2] and tie_right > s[0]:
                    # Compute shift for both directions
                    shift_right = s[2] + M1_MIN_S + m1_hx - cx
                    shift_left = cx - (s[0] - M1_MIN_S - m1_hx)
                    if shift_right <= shift_left:
                        cx = _snap5(cx + shift_right)
                    else:
                        cx = _snap5(cx - shift_left)
        return cx

    def _compute_ntap(self, inst_name):
        """Compute ntap tie for a PMOS device. All math in nm."""
        inst = self.instances[inst_name]
        dev_type = inst['type']
        origin_x, origin_y = self._inst_origin(inst_name)
        cfg = self.constraints['tie_config'][dev_type]
        info = get_nwell_tie_info(_device_lib, dev_type)

        # NWell and pSD absolute bounds (nm)
        nw_top = _snap5(origin_y + info['nw'][3])
        psd_top = _snap5(origin_y + info['psd'][3])
        nw_left = _snap5(origin_x + info['nw'][0])
        nw_right = _snap5(origin_x + info['nw'][2])

        # Net
        nwell_net = self._nwell_nets.get(inst_name, 'vdd')

        # Source pin absolute X (nm)
        src_abs_x = _snap5(origin_x + get_device_pins_nm(_device_lib, dev_type)[cfg['src_pin']][0])

        # Check if source pin is on the NWell net.
        # If source is a signal net, tie M1 must NOT touch source M1.
        src_pin_key = f'{inst_name}.{cfg["src_pin"]}'
        src_net = self._pin_net_map.get(src_pin_key, nwell_net)
        src_is_nwell_net = (src_net == nwell_net)

        # Half-extents
        if cfg['cont'] == '2x2':
            act_hx, m1_hx = _half_extents_2x2()
        else:
            act_hx, m1_hx = _half_extents_1x2()
        act_hy, m1_hy = _half_extents_y()

        # Clamp tie center X to NW.e valid range
        tie_cx = max(nw_left + NW_E + act_hx,
                     min(src_abs_x, nw_right - NW_E - act_hx))
        tie_cx = _snap5(tie_cx)

        # Source via M1 top (above device bbox)
        bbox_top = round(inst['y_um'] * UM) + round(inst['h_um'] * UM)
        src_via_y = bbox_top + VIA_CLEAR
        src_m1_top = src_via_y + VIA1_PAD_M1 // 2

        # Tie Activ center Y
        if src_is_nwell_net:
            # Source is NWell net — tie M1 top merges with source M1 top
            act_cy = max(src_m1_top + m1_hy, psd_top + PSD_CLR + act_hy)
        else:
            # Source is signal — add M1 spacing gap to prevent short
            act_cy = max(src_m1_top + m1_hy + M1_MIN_S, psd_top + PSD_CLR + act_hy)
        act_cy = _snap5(act_cy)

        # GatPoly + pSD clearance: clamp act_cy so tie Activ/contacts
        # don't violate Gat.d/Cnt.f/Cnt.g1/pSD.e with nearby devices.
        act_cy = self._clamp_act_cy_for_clearance(
            act_cy, tie_cx, act_hx, act_hy, skip_device=inst_name)

        # M1 conflict avoidance
        tie_cx = self._resolve_m1_clear_x(
            tie_cx, m1_hx, act_cy - m1_hy, act_cy + m1_hy, skip_device=inst_name)

        # Activ overlap avoidance: tie Activ must not overlap any device Activ
        trial_activ = [tie_cx - act_hx, act_cy - act_hy,
                       tie_cx + act_hx, act_cy + act_hy]
        tie_cx = self._resolve_activ_clear_x(
            tie_cx, trial_activ, skip_device=inst_name)

        # Re-run M1 check after Activ shift
        tie_cx = self._resolve_m1_clear_x(
            tie_cx, m1_hx, act_cy - m1_hy, act_cy + m1_hy, skip_device=inst_name)

        # Contact positions
        half_pitch = (CNT_SZ + CNT_SP) // 2   # 170
        half_pitch_y = half_pitch
        contacts = []
        if cfg['cont'] == '2x2':
            for dx in [-1, 1]:
                for dy in [-1, 1]:
                    contacts.append([tie_cx + dx * half_pitch - CNT_SZ // 2,
                                     act_cy + dy * half_pitch_y - CNT_SZ // 2,
                                     tie_cx + dx * half_pitch + CNT_SZ // 2,
                                     act_cy + dy * half_pitch_y + CNT_SZ // 2])
        else:
            for dy in [-1, 1]:
                contacts.append([tie_cx - CNT_SZ // 2,
                                 act_cy + dy * half_pitch_y - CNT_SZ // 2,
                                 tie_cx + CNT_SZ // 2,
                                 act_cy + dy * half_pitch_y + CNT_SZ // 2])

        activ = [tie_cx - act_hx, act_cy - act_hy, tie_cx + act_hx, act_cy + act_hy]
        m1_pad = [tie_cx - m1_hx, act_cy - m1_hy, tie_cx + m1_hx, act_cy + m1_hy]

        # NWell extension: narrow, enclose tie Activ + NW.e, merge with device NWell top
        nw_ext = [tie_cx - act_hx - NW_E, nw_top,
                  tie_cx + act_hx + NW_E, act_cy + act_hy + NW_E]

        # M1 bridge: from tie M1 pad bottom to source via M1 top
        # Only bridge when source is on the NWell net.
        bridge = None
        jog = None
        if src_is_nwell_net:
            bridge_top = m1_pad[1]     # tie M1 pad bottom
            bridge_bot = src_m1_top    # source M1 top (merge point)
            if bridge_top > bridge_bot:
                bridge = [src_abs_x - M1_THIN // 2, bridge_bot,
                          src_abs_x + M1_THIN // 2, bridge_top]

            # Horizontal jog if tie_cx != src_abs_x (1x2 variants)
            if abs(tie_cx - src_abs_x) > 10:
                jog = [min(tie_cx - m1_hx, src_abs_x - M1_THIN // 2),
                       m1_pad[1] - M1_THIN,
                       max(tie_cx + m1_hx, src_abs_x + M1_THIN // 2),
                       m1_pad[1]]

        # LU distance: device Activ center Y to tie Activ center Y
        dev_act_cy = origin_y + get_device_pins_nm(_device_lib, dev_type)[cfg['src_pin']][1]
        lu_distance = abs(act_cy - dev_act_cy)

        return {
            'id': f'tie_{inst_name}_ntap',
            'device': inst_name,
            'type': 'ntap',
            'net': nwell_net,
            'center_nm': [tie_cx, act_cy],
            'src_abs_x': src_abs_x,
            'cont_config': cfg['cont'],
            'activ': activ,
            'nwell': nw_ext,
            'm1_pad': m1_pad,
            'contacts': contacts,
            'bridge': bridge,
            'jog': jog,
            'lu_distance_nm': lu_distance,
            'nwell_ext_width': nw_ext[2] - nw_ext[0],
        }

    def _compute_ptap(self, inst_name):
        """Compute ptap tie for an NMOS device. All math in nm."""
        inst = self.instances[inst_name]
        dev_type = inst['type']
        origin_x, origin_y = self._inst_origin(inst_name)

        # Source pin absolute X (nm)
        src_abs_x = _snap5(origin_x + get_device_pins_nm(_device_lib, dev_type)['S'][0])

        # Half-extents: ptap always 1×2
        act_hx = CNT_SZ // 2 + ACT_ENC    # 150
        m1_hx = CNT_SZ // 2 + M1_ENC      # 130
        act_hy, m1_hy = _half_extents_y()  # 320, 300

        ptap_cx = _snap5(src_abs_x)

        # Source via below device bbox
        bbox_bot = round(inst['y_um'] * UM)
        src_via_y = bbox_bot - VIA_CLEAR
        src_m1_bot = src_via_y - VIA1_PAD_M1 // 2

        # Check if source pin is on the tie net (gnd).
        # If source is a signal net, tie M1 must NOT touch source M1.
        src_pin = f'{inst_name}.S'
        src_net = self._pin_net_map.get(src_pin, 'gnd')
        src_is_tie_net = (src_net == 'gnd')

        # ptap center Y: below source M1 bottom
        if src_is_tie_net:
            # Source is gnd — tie M1 top merges with source M1 bottom
            ptap_cy = _snap5(src_m1_bot - m1_hy)
        else:
            # Source is signal — add M1 spacing gap to prevent short
            ptap_cy = _snap5(src_m1_bot - m1_hy - M1_MIN_S)

        # M1 conflict avoidance: resolve X using actual tie M1 Y range
        ptap_cx = self._resolve_m1_clear_x(
            ptap_cx, m1_hx, ptap_cy - m1_hy, ptap_cy + m1_hy, skip_device=inst_name)

        # Activ overlap avoidance: tie Activ must not overlap any device Activ
        trial_activ = [ptap_cx - act_hx, ptap_cy - act_hy,
                       ptap_cx + act_hx, ptap_cy + act_hy]
        ptap_cx = self._resolve_activ_clear_x(
            ptap_cx, trial_activ, skip_device=inst_name)

        # Re-run M1 check after Activ shift (X may have changed)
        ptap_cx = self._resolve_m1_clear_x(
            ptap_cx, m1_hx, ptap_cy - m1_hy, ptap_cy + m1_hy, skip_device=inst_name)

        # Contacts (1×2)
        half_pitch_y = (CNT_SZ + CNT_SP) // 2
        contacts = []
        for dy in [-1, 1]:
            contacts.append([ptap_cx - CNT_SZ // 2,
                             ptap_cy + dy * half_pitch_y - CNT_SZ // 2,
                             ptap_cx + CNT_SZ // 2,
                             ptap_cy + dy * half_pitch_y + CNT_SZ // 2])

        activ = [ptap_cx - act_hx, ptap_cy - act_hy, ptap_cx + act_hx, ptap_cy + act_hy]
        psd = [ptap_cx - act_hx - PSD_C1, ptap_cy - act_hy - PSD_C1,
               ptap_cx + act_hx + PSD_C1, ptap_cy + act_hy + PSD_C1]
        m1_pad = [ptap_cx - m1_hx, ptap_cy - m1_hy, ptap_cx + m1_hx, ptap_cy + m1_hy]

        # M1 bridge: from tie M1 pad top to source M1 bottom
        # Only bridge when source is on the tie net (gnd).
        bridge = None
        jog = None
        if src_is_tie_net:
            bridge_bot_y = m1_pad[3]       # tie M1 pad top
            bridge_top_y = src_m1_bot      # source M1 bottom
            if bridge_bot_y < bridge_top_y:
                bridge = [src_abs_x - M1_THIN // 2, bridge_bot_y,
                          src_abs_x + M1_THIN // 2, bridge_top_y]

            # Horizontal jog if ptap_cx shifted away from src_abs_x
            if abs(ptap_cx - src_abs_x) > 10:
                jog = [min(ptap_cx - m1_hx, src_abs_x - M1_THIN // 2),
                       m1_pad[3],  # at tie M1 pad top
                       max(ptap_cx + m1_hx, src_abs_x + M1_THIN // 2),
                       m1_pad[3] + M1_THIN]

        # LU distance
        dev_act_cy = origin_y + get_device_pins_nm(_device_lib, dev_type)['S'][1]
        lu_distance = abs(ptap_cy - dev_act_cy)

        return {
            'id': f'tie_{inst_name}_ptap',
            'device': inst_name,
            'type': 'ptap',
            'net': 'gnd',
            'center_nm': [ptap_cx, ptap_cy],
            'src_abs_x': src_abs_x,
            'cont_config': '1x2',
            'activ': activ,
            'psd': psd,
            'm1_pad': m1_pad,
            'contacts': contacts,
            'bridge': bridge,
            'jog': jog,
            'lu_distance_nm': lu_distance,
        }

    def _compute_lu_extra_ties(self, primary_tie, inst_name):
        """Generate additional ntap ties along a wide PMOS device for LU.a.

        When device Activ is wider than LU_A_MAX, places 1x2 ntap ties
        at intervals ≤ LU_A_MAX along the device length.  Each extra tie
        has the same Y as the primary tie but different X.  M1 is
        connected via a horizontal bar to the primary tie's M1.
        """
        inst = self.instances[inst_name]
        dev_type = inst['type']
        dev = self.device_lib[dev_type]
        origin_x, origin_y = self._inst_origin(inst_name)

        # Device Activ X extent (absolute nm)
        activ_shapes = dev['shapes_by_layer'].get('Activ_1_0', [])
        if not activ_shapes:
            return []
        act_x_min = min(origin_x + s[0] for s in activ_shapes)
        act_x_max = max(origin_x + s[2] for s in activ_shapes)
        dev_act_width = act_x_max - act_x_min

        if dev_act_width <= LU_A_MAX:
            return []

        # Primary tie covers [primary_x - LU_A_MAX/2, primary_x + LU_A_MAX/2]
        primary_cx = primary_tie['center_nm'][0]
        act_cy = primary_tie['center_nm'][1]

        # 1x2 half-extents for extra ties
        act_hx, m1_hx = _half_extents_1x2()
        act_hy, m1_hy = _half_extents_y()

        # NWell bounds for clamping
        info = get_nwell_tie_info(_device_lib, dev_type)
        nw_top = _snap5(origin_y + info['nw'][3])
        nw_left = _snap5(origin_x + info['nw'][0])
        nw_right = _snap5(origin_x + info['nw'][2])

        # Net
        nwell_net = primary_tie['net']

        # Exclusion zones: device pin X positions have access-point m1_stubs
        # extending vertically through the tie strip.  Keep tie M1 away.
        pin_xs = get_device_pins_nm(_device_lib, dev_type)
        exclude_xs = []
        for pname, (px, _) in pin_xs.items():
            abs_px = _snap5(origin_x + px)
            exclude_xs.append(abs_px)

        # Place extra ties at LU_A_MAX intervals, covering the full device
        # Start from primary_cx, step by LU_A_MAX in both directions
        extra_ties = []
        half_pitch_y = (CNT_SZ + CNT_SP) // 2

        step = LU_A_MAX
        cx = _snap5(primary_cx + step)
        idx = 0

        while cx < act_x_max:
            # Clamp to NW.e valid range
            tie_cx = max(nw_left + NW_E + act_hx,
                         min(cx, nw_right - NW_E - act_hx))
            tie_cx = _snap5(tie_cx)

            # Skip if too close to a device pin m1_stub
            # m1_stub is M1_THIN (160nm) wide; need M1_MIN_S (180nm) clearance
            stub_margin = M1_THIN // 2 + M1_MIN_S + m1_hx  # 80+180+130=390nm
            skip = False
            for epx in exclude_xs:
                if abs(tie_cx - epx) < stub_margin:
                    skip = True
                    break
            if skip:
                cx = _snap5(cx + step)
                continue

            # M1 + Activ conflict avoidance
            tie_cx = self._resolve_m1_clear_x(
                tie_cx, m1_hx, act_cy - m1_hy, act_cy + m1_hy,
                skip_device=inst_name)
            trial_activ = [tie_cx - act_hx, act_cy - act_hy,
                           tie_cx + act_hx, act_cy + act_hy]
            tie_cx = self._resolve_activ_clear_x(
                tie_cx, trial_activ, skip_device=inst_name)
            tie_cx = self._resolve_m1_clear_x(
                tie_cx, m1_hx, act_cy - m1_hy, act_cy + m1_hy,
                skip_device=inst_name)

            # Contacts (1x2)
            contacts = []
            for dy in [-1, 1]:
                contacts.append([tie_cx - CNT_SZ // 2,
                                 act_cy + dy * half_pitch_y - CNT_SZ // 2,
                                 tie_cx + CNT_SZ // 2,
                                 act_cy + dy * half_pitch_y + CNT_SZ // 2])

            activ = [tie_cx - act_hx, act_cy - act_hy,
                     tie_cx + act_hx, act_cy + act_hy]
            m1_pad = [tie_cx - m1_hx, act_cy - m1_hy,
                      tie_cx + m1_hx, act_cy + m1_hy]

            # NWell extension
            nw_ext = [tie_cx - act_hx - NW_E, nw_top,
                      tie_cx + act_hx + NW_E, act_cy + act_hy + NW_E]

            idx += 1
            extra_ties.append({
                'id': f'tie_{inst_name}_ntap_lu{idx}',
                'device': inst_name,
                'type': 'ntap',
                'net': nwell_net,
                'center_nm': [tie_cx, act_cy],
                'cont_config': '1x2',
                'activ': activ,
                'nwell': nw_ext,
                'm1_pad': m1_pad,
                'contacts': contacts,
                'bridge': None,
                'jog': None,
                'lu_distance_nm': 0,
                'nwell_ext_width': nw_ext[2] - nw_ext[0],
            })

            cx = _snap5(cx + step)

        # M1 bus bar: connect all extra ties to primary via horizontal M1
        if extra_ties:
            hp_m1_thin = M1_THIN // 2
            bus_x1 = primary_tie['m1_pad'][0]
            bus_x2 = extra_ties[-1]['m1_pad'][2]
            bus_y1 = act_cy - m1_hy
            bus_y2 = act_cy - m1_hy + M1_THIN
            # Add bus bar as M1 rect on the primary tie
            primary_tie.setdefault('m1_bus', [bus_x1, bus_y1, bus_x2, bus_y2])

        return extra_ties

    def solve(self):
        """Compute all tie positions. Returns list of tie dicts."""
        self.ties = []
        self.nwell_extensions = []

        pmos_types = set(self.constraints['tie_reservation']['pmos_ntap']['applies_to'])
        nmos_types = set(self.constraints['tie_reservation']['nmos_ptap']['applies_to'])

        for name, inst in self.instances.items():
            dev_type = inst['type']
            if dev_type in pmos_types:
                tie = self._compute_ntap(name)
                self.ties.append(tie)
                self.nwell_extensions.append({
                    'tie_id': tie['id'],
                    'device': name,
                    'rect_nm': tie['nwell'],
                    'net': tie['net'],
                    'width_nm': tie['nwell_ext_width'],
                })
                # LU.a: extra ties along wide devices
                extras = self._compute_lu_extra_ties(tie, name)
                for et in extras:
                    self.ties.append(et)
                    self.nwell_extensions.append({
                        'tie_id': et['id'],
                        'device': name,
                        'rect_nm': et['nwell'],
                        'net': et['net'],
                        'width_nm': et['nwell_ext_width'],
                    })
            elif dev_type in nmos_types:
                tie = self._compute_ptap(name)
                self.ties.append(tie)

        return self.ties

    def _find_tie_strip(self, tie):
        """Find which tie strip a tie belongs to based on its device's row."""
        device = tie['device']
        row_groups = self.constraints['row_groups']
        for rn, rd in row_groups.items():
            if device in rd['devices']:
                # ntap → strip above (rn_ntap), ptap → strip below (rn_ptap)
                strip_key = f'{rn}_ntap' if tie['type'] == 'ntap' else f'{rn}_ptap'
                return self.tie_strips.get(strip_key)
        return None

    def verify(self):
        """Run all gate checks. Returns (n_pass, n_total, errors)."""
        errors = []
        n_total = 7
        n_pass = 0

        max_lu = self.constraints['tie_reservation']['pmos_ntap']['max_distance_nm']
        pmos_types = set(self.constraints['tie_reservation']['pmos_ntap']['applies_to'])
        nmos_types = set(self.constraints['tie_reservation']['nmos_ptap']['applies_to'])

        # Check 1: LU.a — every PMOS to its ntap ≤ 20µm
        c1_ok = True
        ntap_by_dev = {t['device']: t for t in self.ties if t['type'] == 'ntap'}
        for name, inst in self.instances.items():
            if inst['type'] not in pmos_types:
                continue
            t = ntap_by_dev.get(name)
            if not t:
                errors.append(f'LU.a FAIL: {name} has no ntap')
                c1_ok = False
            elif t['lu_distance_nm'] > max_lu:
                errors.append(f'LU.a FAIL: {name} lu={t["lu_distance_nm"]}nm > {max_lu}nm')
                c1_ok = False
        if c1_ok:
            n_pass += 1

        # Check 2: LU.b — every NMOS to its ptap ≤ 20µm
        c2_ok = True
        ptap_by_dev = {t['device']: t for t in self.ties if t['type'] == 'ptap'}
        for name, inst in self.instances.items():
            if inst['type'] not in nmos_types:
                continue
            t = ptap_by_dev.get(name)
            if not t:
                errors.append(f'LU.b FAIL: {name} has no ptap')
                c2_ok = False
            elif t['lu_distance_nm'] > max_lu:
                errors.append(f'LU.b FAIL: {name} lu={t["lu_distance_nm"]}nm > {max_lu}nm')
                c2_ok = False
        if c2_ok:
            n_pass += 1

        # Check 3: M1 conflict
        c3_ok = True
        for tie in self.ties:
            m1 = tie['m1_pad']
            inflated = [m1[0] - M1_MIN_S, m1[1] - M1_MIN_S,
                        m1[2] + M1_MIN_S, m1[3] + M1_MIN_S]
            conflicts = self._check_m1_conflict(inflated, skip_device=tie['device'])
            if conflicts:
                for dev, rect in conflicts:
                    errors.append(f'M1 FAIL: {tie["id"]} ↔ {dev}')
                c3_ok = False
        if c3_ok:
            n_pass += 1

        # Check 4: nBuLay
        c4_ok = True
        for ext in self.nwell_extensions:
            if ext['width_nm'] >= NBULAY_THRESHOLD:
                errors.append(f'nBuLay FAIL: {ext["tie_id"]} w={ext["width_nm"]}nm >= {NBULAY_THRESHOLD}nm')
                c4_ok = False
        if c4_ok:
            n_pass += 1

        # Check 5: NWell bridge net isolation
        c5_ok = True
        for ext in self.nwell_extensions:
            for island in self.nwell_islands:
                if island['net'] == ext['net']:
                    continue
                ib = [round(v * UM) for v in island['bbox_um']]
                ib_ext = [ib[0] - NW_E, ib[1] - NW_E, ib[2] + NW_E, ib[3] + NW_E]
                r = ext['rect_nm']
                if (r[0] < ib_ext[2] and r[2] > ib_ext[0] and
                        r[1] < ib_ext[3] and r[3] > ib_ext[1]):
                    errors.append(f'NWell FAIL: {ext["tie_id"]}({ext["net"]}) ↔ {island["id"]}({island["net"]})')
                    c5_ok = False
        if c5_ok:
            n_pass += 1

        # Check 6: Tie on correct side of device
        # Tie Y is determined by via geometry (precise), not by strip Y range (rough).
        # Verify: ntap above its PMOS device, ptap below its NMOS device.
        c6_ok = True
        for tie in self.ties:
            inst = self.instances[tie['device']]
            dev_cy = round(inst['y_um'] * UM) + round(inst['h_um'] * UM) // 2
            tie_cy = tie['center_nm'][1]
            if tie['type'] == 'ntap' and tie_cy <= dev_cy:
                errors.append(f'Side FAIL: {tie["id"]} cy={tie_cy} not above device cy={dev_cy}')
                c6_ok = False
            elif tie['type'] == 'ptap' and tie_cy >= dev_cy:
                errors.append(f'Side FAIL: {tie["id"]} cy={tie_cy} not below device cy={dev_cy}')
                c6_ok = False
        if c6_ok:
            n_pass += 1

        # Check 7: Activ overlap — tie Activ must not overlap any device Activ
        c7_ok = True
        for tie in self.ties:
            tie_act = tie['activ']
            for dev_name, act_shapes in self._activ_obstacles.items():
                if dev_name == tie['device']:
                    continue
                for s in act_shapes:
                    if (tie_act[0] < s[2] and tie_act[2] > s[0] and
                            tie_act[1] < s[3] and tie_act[3] > s[1]):
                        errors.append(f'Activ FAIL: {tie["id"]} overlaps {dev_name}')
                        c7_ok = False
        if c7_ok:
            n_pass += 1

        return n_pass, n_total, errors

    def to_json(self):
        """Convert results to JSON-serializable dict."""
        n_pass, n_total, errors = self.verify()

        ties_json = []
        for t in self.ties:
            entry = {
                'id': t['id'],
                'device': t['device'],
                'type': t['type'],
                'net': t['net'],
                'center_nm': t['center_nm'],
                'lu_distance_nm': t['lu_distance_nm'],
                'cont_config': t['cont_config'],
                'layers': {
                    'Activ_1_0': [t['activ']],
                    'Cont_6_0': t['contacts'],
                    'M1_8_0': [t['m1_pad']],
                },
            }
            if t.get('bridge'):
                entry['layers']['M1_8_0'].append(t['bridge'])
            if t.get('jog'):
                entry['layers']['M1_8_0'].append(t['jog'])
            if t.get('m1_bus'):
                entry['layers']['M1_8_0'].append(t['m1_bus'])
            if t['type'] == 'ntap':
                entry['layers']['NW_31_0'] = [t['nwell']]
            if 'psd' in t:
                entry['layers']['pSD_14_0'] = [t['psd']]
            ties_json.append(entry)

        return {
            'version': '3.0',
            'ties': ties_json,
            'nwell_extensions': [
                {'tie_id': e['tie_id'], 'device': e['device'],
                 'rect_nm': e['rect_nm'], 'net': e['net'], 'width_nm': e['width_nm']}
                for e in self.nwell_extensions
            ],
            'gate_summary': {
                'all_pass': n_pass == n_total,
                'passed': n_pass,
                'total': n_total,
                'errors': errors,
            },
        }
