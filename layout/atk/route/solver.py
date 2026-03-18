"""Routing orchestrator — obstacle map, pin escape, maze dispatch.

Obstacle model:
  permanent: device bbox, tie M1, power drops — physical structures, never cleared.
  soft:      pin access protection rings — per-net clearable for routing.

Margin rule: all block_rect margins = DRC_spacing + wire_half_width.
  Router walks wire CENTER; DRC checks wire EDGE.
  margin = spacing_rule + sig_wire_width / 2.

Outputs routing.json via to_json().
"""

import json

from ..pdk import (
    UM, s5,
    M1_MIN_S, M2_MIN_S, V1_MIN_S,
    M1_SIG_W, M2_SIG_W, M3_PWR_W, M3_MIN_S, M1_THIN,
    VIA1_PAD, VIA1_PAD_M1, VIA1_SZ,
    VIA_CLEAR, HBT_VIA_CLEAR,
    DEV_MARGIN, HBT_MARGIN,
    PIN_VIA_MARGIN, PIN_VIA_MARGIN_M2,
    MAZE_GRID,
)
from .maze_router import MazeRouter, M1_LYR, M2_LYR
from .access import (
    compute_access_points, inst_bbox_nm, abs_pin_nm,
    get_access_mode, get_device_info, PIN_ACCESS,
)
from .power import compute_power_rails, compute_power_drops

# ─── Routing margins (DRC rule + wire half-width) ───
# Router walks wire center; DRC checks wire edge.
M1_ROUTE_MARGIN = M1_MIN_S + M1_SIG_W // 2   # 180 + 150 = 330nm
M2_ROUTE_MARGIN = M2_MIN_S + M2_SIG_W // 2   # 210 + 150 = 360nm


class RoutingSolver:
    """Full routing solver: power + signal → routing.json."""

    def __init__(self, placement, ties, netlist):
        self.placement = placement
        self.ties = ties
        self.netlist = netlist
        self.router = None
        self.access_points = None
        self.rails = None
        self.power_drops = None
        self.pre_routes = {}
        self.signal_routes = {}
        self.errors = []

    def solve(self, seed=None):
        """Run full routing pipeline. seed controls net ordering for parallel sweep."""
        print('=== Phase 4: Routing ===')
        print()

        # 1. Access points
        print('[1] Computing access points...')
        self.access_points = compute_access_points(self.placement)
        by_mode = {}
        for ap in self.access_points.values():
            by_mode[ap['mode']] = by_mode.get(ap['mode'], 0) + 1
        print(f'  {len(self.access_points)} access points: {by_mode}')

        # 2. Power rails + drops
        print('[2] Computing power topology...')
        power_topo = self.netlist.get('constraints', {}).get('power_topology', {})
        self.rails = compute_power_rails(self.placement, power_topo)
        self.power_drops = compute_power_drops(
            self.placement, self.access_points, self.rails, power_topo)
        # via_stack pins bypass access points — no M2 pad/M1 stub physically drawn
        self.via_stack_pins = set()
        for drop in self.power_drops:
            if drop['type'] == 'via_stack':
                self.via_stack_pins.add((drop['inst'], drop['pin']))
        print(f'  {len(self.rails)} rails, {len(self.power_drops)} drops '
              f'({len(self.via_stack_pins)} via_stack)')

        # 3. Build obstacle map (M3+M4+M5 routing)
        # Device bboxes NOT blocked (PCell has no M3/M4/M5 geometry, verified)
        # Tie M1 NOT blocked (M1 layer, not relevant to M3+ routing)
        # M3 power rails NOT blocked (power moved to TopMetal1)
        print('[3] Building obstacle map (M3+M4+M5)...')
        self._init_router()
        self._register_pin_terminals() # FIRST: pin centers must be known
        # self._block_device_bbox()    # DISABLED: no M3/M4/M5 in PCell
        # self._block_tie_m1()         # DISABLED: ties on M1 only
        self.device_body_cells = {}    # empty — no device obstacles on M3+
        self.power_stub_cells = set()  # empty — old M1 power stubs not relevant
        self.power_m2_cells = set()    # empty — old M2 power pads not relevant
        self._block_pin_access()       # soft — pin Via2 pads on M3
        self._pin_escape()             # clears soft only (safe_discard)
        self._reblock_pin_access()     # re-registers soft
        self._block_power_pads_m345()  # NEW: 153 power via stack pads
        # self._block_power_rails_m3() # DISABLED: power on TM1 now
        self._signal_escape_recheck()  # re-open signal pins blocked by power
        print(f'  Router grid: {self.router.nx}×{self.router.ny} '
              f'({self.router.nx * self.router.ny} cells)')
        print(f'  Blocked: {len(self.router.blocked)} '
              f'(permanent: {len(self.router.permanent)})')

        # 4. Pre-route HBT B→C
        print('[4] Pre-routing HBT B→C...')
        self._pre_route_hbt()

        # 5. Maze route signal nets
        print(f'[5] Routing signal nets (seed={seed})...')
        self._route_signals(seed=seed)

        print()
        return self

    # ─── Router init ───

    def _init_router(self):
        """Create MazeRouter with bounding box from placement."""
        bb = self.placement['bounding_box']
        margin_nm = s5(5.0)
        x_min = s5(-3.0) - margin_nm
        x_max = s5(bb['w_um'] + 3.0) + margin_nm
        y_min = s5(-5.0) - margin_nm
        y_max = s5(bb['h_um'] + 5.0) + margin_nm
        self.router = MazeRouter((x_min, x_max), (y_min, y_max))

    # ─── Obstacle registration ───

    def _block_device_bbox(self):
        """Block device bboxes — PERMANENT.

        DEV_MARGIN (200nm): PCell bbox has ~120nm internal margin from
        M1 metal edge to bbox boundary.  200nm from bbox edge ≈ 320nm
        from metal edge, which exceeds M1.b=180nm for wire edges
        (320 - 150 wire_half = 170nm — close but the PCell internal
        margin makes it safe).  Using M1_ROUTE_MARGIN=330nm here would
        block gate/m1_pin pins that sit just outside the bbox.
        """
        self.device_body_cells = {}  # inst_name → set of (gx, gy, M1_LYR)
        count = 0
        for inst_name, inst in self.placement['instances'].items():
            dev_type = inst['type']
            left, bot, right, top = inst_bbox_nm(self.placement, inst_name)
            is_hbt = dev_type.startswith('hbt')
            margin = HBT_MARGIN if is_hbt else DEV_MARGIN
            cells = self.router.block_rect(left, bot, right, top, M1_LYR,
                                           margin=margin, permanent=True)
            self.device_body_cells[inst_name] = set(cells)
            if is_hbt:
                self.router.block_rect(left, bot, right, top, M2_LYR,
                                       margin=HBT_MARGIN, permanent=True)
            count += 1
        print(f'  Device bbox obstacles: {count} (permanent, '
              f'M1 margin={DEV_MARGIN}nm)')

    def _block_tie_m1(self):
        """Block tie cell M1 shapes — PERMANENT.

        Uses an extra half-grid-cell margin beyond M1_ROUTE_MARGIN to
        compensate for to_grid() round-to-nearest: the standard margin
        can under-block by up to GRID/2, causing sub-180nm M1.b gaps.
        """
        if not self.ties or 'ties' not in self.ties:
            print('  Tie M1 obstacles: 0 (no ties)')
            return
        tie_margin = M1_ROUTE_MARGIN + MAZE_GRID // 2
        count = 0
        for tie in self.ties['ties']:
            m1_rects = tie.get('layers', {}).get('M1_8_0', [])
            for rect in m1_rects:
                self.router.block_rect(
                    rect[0], rect[1], rect[2], rect[3],
                    M1_LYR, margin=tie_margin, permanent=True)
                count += 1
        print(f'  Tie M1 obstacles: {count} rects (permanent, '
              f'margin={tie_margin}nm)')

    def _block_pin_access(self):
        """Block pin access structures — SOFT (clearable per-net).

        Margins include wire half-width (PIN_VIA_MARGIN, PIN_VIA_MARGIN_M2).
        Skips via_stack pins (no physical access point structure).
        """
        hp = VIA1_PAD // 2
        hp_m1 = VIA1_PAD_M1 // 2
        count = 0

        for (inst_name, pin_name), ap in self.access_points.items():
            if (inst_name, pin_name) in self.via_stack_pins:
                continue
            vx, vy = ap['x'], ap['y']
            mode = ap['mode']

            if mode in ('above', 'below'):
                bbox = inst_bbox_nm(self.placement, inst_name)
                hw_m1 = max(M1_THIN, VIA1_PAD_M1) // 2
                if mode == 'above':
                    m1_y1 = bbox[3]
                    m1_y2 = vy + hp_m1
                else:
                    m1_y1 = vy - hp_m1
                    m1_y2 = bbox[1]
                self.router.block_rect(vx - hw_m1, m1_y1, vx + hw_m1, m1_y2,
                                       M1_LYR, margin=PIN_VIA_MARGIN)
                self.router.block_rect(vx - hp, vy - hp, vx + hp, vy + hp,
                                       M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1

            elif mode in ('gate', 'gate_no_m1', 'direct'):
                self.router.block_rect(
                    vx - hp_m1, vy - hp_m1, vx + hp_m1, vy + hp_m1,
                    M1_LYR, margin=PIN_VIA_MARGIN)
                self.router.block_rect(
                    vx - hp, vy - hp, vx + hp, vy + hp,
                    M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1

            elif mode == 'm1_pin':
                # M1 pad (compact)
                self.router.block_rect(
                    vx - hp_m1, vy - hp_m1, vx + hp_m1, vy + hp_m1,
                    M1_LYR, margin=PIN_VIA_MARGIN)
                # M2 pad (GDS assembly creates Via1 + M2 pad here)
                self.router.block_rect(
                    vx - hp, vy - hp, vx + hp, vy + hp,
                    M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1

            elif mode == 'm2':
                self.router.block_rect(
                    vx - hp, vy - hp, vx + hp, vy + hp,
                    M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1

            elif mode == 'm2_below':
                # Via1 below bbox: M1 pad at via + M2 stub (via to pin)
                self.router.block_rect(
                    vx - hp_m1, vy - hp_m1, vx + hp_m1, vy + hp_m1,
                    M1_LYR, margin=PIN_VIA_MARGIN)
                m2_stub = ap.get('m2_stub')
                if m2_stub:
                    self.router.block_rect(
                        m2_stub[0], m2_stub[1], m2_stub[2], m2_stub[3],
                        M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1

        print(f'  Pin access obstacles: {count} (soft)')

    def _pin_escape(self):
        """Clear escape channels from access points through device bbox.

        Uses safe_discard — only clears soft cells, permanent untouched.
        Skips via_stack pins (no access point structure to escape from).
        """
        count = 0
        for (inst_name, pin_name), ap in self.access_points.items():
            if (inst_name, pin_name) in self.via_stack_pins:
                continue
            mode = ap['mode']

            if mode in ('gate', 'gate_no_m1', 'm1_pin'):
                continue

            ax, ay = ap['x'], ap['y']
            bbox = inst_bbox_nm(self.placement, inst_name)

            if mode == 'direct':
                left, bot, right, top = bbox
                if not (left <= ax <= right and bot <= ay <= top):
                    continue

            self.router.add_pin_escape((ax, ay), bbox)
            count += 1
        print(f'  Pin escape channels: {count} (safe_discard)')

    def _reblock_pin_access(self):
        """Re-block via pad zones that escapes may have cleared — SOFT.

        Skips via_stack pins (no access point structure).
        """
        hp = VIA1_PAD // 2
        hp_m1 = VIA1_PAD_M1 // 2
        count = 0

        for (inst_name, pin_name), ap in self.access_points.items():
            if (inst_name, pin_name) in self.via_stack_pins:
                continue
            vx, vy = ap['x'], ap['y']
            mode = ap['mode']

            if mode in ('above', 'below'):
                bbox = inst_bbox_nm(self.placement, inst_name)
                hw_m1 = max(M1_THIN, VIA1_PAD_M1) // 2
                if mode == 'above':
                    m1_y1 = bbox[3]
                    m1_y2 = vy + hp_m1
                else:
                    m1_y1 = vy - hp_m1
                    m1_y2 = bbox[1]
                self.router.block_rect(vx - hw_m1, m1_y1, vx + hw_m1, m1_y2,
                                       M1_LYR, margin=PIN_VIA_MARGIN)
                self.router.block_rect(vx - hp, vy - hp, vx + hp, vy + hp,
                                       M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1
            elif mode in ('gate', 'gate_no_m1', 'direct'):
                self.router.block_rect(
                    vx - hp_m1, vy - hp_m1, vx + hp_m1, vy + hp_m1,
                    M1_LYR, margin=PIN_VIA_MARGIN)
                self.router.block_rect(
                    vx - hp, vy - hp, vx + hp, vy + hp,
                    M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1
            elif mode == 'm1_pin':
                self.router.block_rect(
                    vx - hp_m1, vy - hp_m1, vx + hp_m1, vy + hp_m1,
                    M1_LYR, margin=PIN_VIA_MARGIN)
                self.router.block_rect(
                    vx - hp, vy - hp, vx + hp, vy + hp,
                    M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1
            elif mode == 'm2_below':
                self.router.block_rect(
                    vx - hp_m1, vy - hp_m1, vx + hp_m1, vy + hp_m1,
                    M1_LYR, margin=PIN_VIA_MARGIN)
                m2_stub = ap.get('m2_stub')
                if m2_stub:
                    self.router.block_rect(
                        m2_stub[0], m2_stub[1], m2_stub[2], m2_stub[3],
                        M2_LYR, margin=PIN_VIA_MARGIN_M2)
                count += 1

        print(f'  Re-blocked via pad zones: {count} (soft)')

    def _register_pin_terminals(self):
        """Register pin center grid cells as terminals.

        Margin expansion from other cells skips pin_terminals.
        Skips via_stack pins (no access point on routing grid).
        """
        for (inst_name, pin_name), ap in self.access_points.items():
            if (inst_name, pin_name) in self.via_stack_pins:
                continue
            gx, gy = self.router.to_grid(ap['x'], ap['y'])
            self.router.pin_terminals.add((gx, gy))
        print(f'  Pin terminals: {len(self.router.pin_terminals)}')

    def _block_power_drops(self):
        """Block power drop M2 structures — PERMANENT.

        Three sources of power M2 metal:
        1. via_access: m2_vbar (vertical bar) + optional m2_jog
        2. via_stack: via2_pos M2 pad
        3. access_point via_pad: M2 pad at non-via_stack power pins
        """
        self.power_stub_cells = set()  # M1 stub cells — never demote in escape
        self.power_m2_cells = set()   # M2 vbar/jog/via cells — never demote
        count = 0
        jogs = 0
        for drop in self.power_drops:
            if drop['type'] == 'via_access' and 'm2_vbar' in drop:
                vbar = drop['m2_vbar']
                hw = M2_SIG_W // 2
                cells = self.router.block_rect(
                    vbar[0] - hw, vbar[1], vbar[2] + hw, vbar[3],
                    M2_LYR, margin=M2_ROUTE_MARGIN, permanent=True)
                self.power_m2_cells.update(cells)
                if 'm2_jog' in drop:
                    jog = drop['m2_jog']
                    cells = self.router.block_rect(
                        jog[0] - hw, jog[1] - hw, jog[2] + hw, jog[3] + hw,
                        M2_LYR, margin=M2_ROUTE_MARGIN, permanent=True)
                    self.power_m2_cells.update(cells)
                    jogs += 1
                count += 1
            elif drop['type'] == 'via_stack' and 'm3_vbar' in drop:
                v2 = drop['via2_pos']
                hp = VIA1_PAD // 2
                cells = self.router.block_rect(
                    v2[0] - hp, v2[1] - hp, v2[0] + hp, v2[1] + hp,
                    M2_LYR, margin=M2_ROUTE_MARGIN, permanent=True)
                self.power_m2_cells.update(cells)
                count += 1

        # Block M1+M2 access structures of ALL power pins.
        # These are physical pads/stubs drawn in GDS that signal routes must avoid.
        power_pins = set()
        for net in self.netlist['nets']:
            if net['type'] == 'power':
                for pin_str in net['pins']:
                    inst, pin = pin_str.split('.')
                    power_pins.add((inst, pin))

        # via_access pins: their M2 vbar blocking (above) already covers
        # the Via1 M2 pad area.  Skipping the separate M2 pad blocking
        # frees adjacent signal pins trapped between power pads
        # (e.g., MBp2.D between S1/S2 power pads on ng=2 devices).
        via_access_pins = set()
        for drop in self.power_drops:
            if drop['type'] == 'via_access':
                via_access_pins.add((drop['inst'], drop['pin']))

        m2_pad_count = 0
        m2_pad_skip = 0
        m1_pad_count = 0
        for (inst_name, pin_name) in power_pins:
            ap = self.access_points.get((inst_name, pin_name))
            if not ap:
                continue
            vp = ap.get('via_pad')
            if vp and 'm2' in vp:
                if (inst_name, pin_name) in via_access_pins:
                    m2_pad_skip += 1
                    continue
                self.router.block_rect(
                    vp['m2'][0], vp['m2'][1], vp['m2'][2], vp['m2'][3],
                    M2_LYR, margin=M2_ROUTE_MARGIN, permanent=True)
                m2_pad_count += 1
            # M1 stubs: force-permanent obstacle (overrides pin_terminal
            # exemption to prevent same-device signal pins from routing
            # through power stub DRC margin zone).
            stub = ap.get('m1_stub')
            if stub:
                cells = self.router.block_rect(
                    stub[0], stub[1], stub[2], stub[3],
                    M1_LYR, margin=M1_ROUTE_MARGIN, permanent=True,
                    force_permanent=True)
                self.power_stub_cells.update(cells)
                # Exempt same-device signal pin terminals from force_permanent.
                # Power stub may overlap gate pin on same device (e.g. MNdiode
                # S stub covers G pin). The signal pin must remain routable.
                for (si, sp), sap in self.access_points.items():
                    if si != inst_name or (si, sp) in power_pins:
                        continue
                    sgx, sgy = self.router.to_grid(sap['x'], sap['y'])
                    cell = (sgx, sgy, M1_LYR)
                    if cell in self.power_stub_cells:
                        self.router.permanent.discard(cell)
                        self.power_stub_cells.discard(cell)
                m1_pad_count += 1

        # Global sweep: exempt ALL signal pin cells from power_stub_cells.
        # The per-device exemption above (lines 408-415) handles same-device
        # overlap, but a different device's power stub can also cover a signal
        # pin cell (e.g. MBp1.S stub extending over MBp2.D grid cell).
        cross_exempt = 0
        for (si, sp), sap in self.access_points.items():
            if (si, sp) in power_pins:
                continue
            sgx, sgy = self.router.to_grid(sap['x'], sap['y'])
            cell = (sgx, sgy, M1_LYR)
            if cell in self.power_stub_cells:
                self.router.permanent.discard(cell)
                self.power_stub_cells.discard(cell)
                cross_exempt += 1
                print(f'    Cross-device exempt: {si}.{sp} at grid({sgx},{sgy})')

        print(f'  Power drop obstacles: {count} M2 vbar (permanent, '
              f'margin={M2_ROUTE_MARGIN}nm, {jogs} jogged), '
              f'{m2_pad_count} M2 pads ({m2_pad_skip} skipped/via_access), '
              f'{m1_pad_count} M1 stubs'
              f'{f", {cross_exempt} cross-device exemptions" if cross_exempt else ""}')

    def _block_power_pads_m345(self):
        """Block 153 power via stack pads on M3/M4/M5 — PERMANENT.

        Power via stacks from TM1 down to M2 have pads on M3, M4, M5.
        Signal routing must avoid these. Device bboxes are NOT blocked
        (PCell has no M3/M4/M5 geometry, verified 2026-03-18).

        Also blocks 3 cap_cmim bottom plate areas on M5.
        """
        from .maze_router import M1_LYR, M2_LYR, M3_LYR, N_ROUTING_LAYERS
        from ..pdk import (VIA3_PAD, VIA4_PAD, M5_MIN_S, M4_MIN_S, M3_MIN_S,
                           M2_SIG_W)

        # Margin = metal spacing + wire half-width
        m3_margin = M3_MIN_S + M2_SIG_W // 2   # 210 + 150 = 360nm
        m4_margin = M4_MIN_S + M2_SIG_W // 2   # 210 + 150 = 360nm
        m5_margin = M5_MIN_S + M2_SIG_W // 2   # 210 + 150 = 360nm

        pad_hw = VIA3_PAD // 2  # ~185nm half-pad (same for Via3/Via4)
        count = 0
        for drop in self.power_drops:
            if drop['type'] != 'via_stack':
                continue
            # Power pad center = AP position
            ap_key = f"{drop['inst']}.{drop['pin']}"
            ap = self.access_points.get(ap_key)
            if not ap:
                continue
            px, py = ap['x'], ap['y']

            # Block on all 3 routing layers (M3=layer0, M4=layer1, M5=layer2)
            for lyr, margin in [(M1_LYR, m3_margin),
                                (M2_LYR, m4_margin),
                                (M3_LYR, m5_margin)]:
                self.router.block_rect(
                    px - pad_hw, py - pad_hw, px + pad_hw, py + pad_hw,
                    lyr, margin=margin, permanent=True)
                count += 1

        # Block cap_cmim bottom plate areas on M5 (layer 2)
        cap_count = 0
        from ..pdk import M5_MIN_S
        for inst_name, inst in self.placement['instances'].items():
            dev_type = inst.get('type', '')
            if 'cap' not in dev_type and 'cmim' not in dev_type:
                continue
            left, bot, right, top = inst_bbox_nm(self.placement, inst_name)
            self.router.block_rect(
                left, bot, right, top,
                M3_LYR, margin=m5_margin, permanent=True)  # M3_LYR=2=M5
            cap_count += 1

        print(f'  Power pad obstacles: {count} (153 drops × 3 layers)')
        print(f'  Cap_cmim M5 obstacles: {cap_count}')

    def _block_power_rails_m3(self):
        """Block M3 power rails as permanent obstacles on M3 layer.

        M3 rails are horizontal bars spanning the full chip width.
        Signal routes on M3 must avoid these areas.
        Also blocks M3 vbar stubs from power drops.
        """
        from .maze_router import M3_LYR
        m3_margin = M2_SIG_W // 2 + M3_MIN_S  # wire half-width + M3.b spacing = 360nm
        count = 0
        for rid, rail in self.rails.items():
            y = rail['y']
            hw = rail['width'] // 2
            x1, x2 = rail.get('x1', self.router.x0), rail.get('x2', self.router.x1)
            cells = self.router.block_rect(
                x1, y - hw, x2, y + hw,
                M3_LYR, margin=m3_margin, permanent=True)
            count += len(cells)

        # Block M3 vbar stubs from power drops
        vbar_count = 0
        for drop in self.power_drops:
            if drop['type'] == 'via_stack' and 'm3_vbar' in drop:
                vbar = drop['m3_vbar']
                hw = 100  # half of 200nm vbar width
                cells = self.router.block_rect(
                    vbar[0] - hw, vbar[1], vbar[2] + hw, vbar[3],
                    M3_LYR, margin=m3_margin, permanent=True)
                vbar_count += len(cells)

        print(f'  M3 power blocked: {count} rail cells, {vbar_count} vbar cells')

    def _signal_escape_recheck(self):
        """Re-open escape channels for signal pins trapped by power obstacles.

        After _block_power_drops, some signal pins may be trapped inside
        permanent obstacle walls (e.g., MBp2.D between MBp2.S1/S2 power
        pads). This pass:
        1. Simulates punch for each signal pin
        2. BFS flood to check reachability
        3. Only demotes permanent→soft for TRAPPED pins
        4. Demotes a full directional column (not fixed radius) so the
           escape channel can traverse tall device bboxes.
        """
        from collections import deque

        signal_pins = []
        for net in self.netlist['nets']:
            if net['type'] == 'signal':
                for pin_str in net['pins']:
                    inst, pin = pin_str.split('.')
                    if (inst, pin) not in self.via_stack_pins:
                        ap = self.access_points.get((inst, pin))
                        if ap:
                            signal_pins.append((inst, pin, ap))

        REACHABLE_THRESHOLD = 20  # if fewer cells reachable, pin is trapped
        CROSS_WIDTH = 3           # half-width of demotion cross
        demoted = 0
        freed = 0

        for inst_name, pin_name, ap in signal_pins:
            gx, gy = self.router.to_grid(ap['x'], ap['y'])

            # Quick BFS to check reachability (simulate punch first)
            temp_cleared = set()
            ARM = 2
            for dx, dy in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                for step in range(ARM + 1):
                    cx, cy = gx + step * dx, gy + step * dy
                    if 0 <= cx < self.router.nx and 0 <= cy < self.router.ny:
                        for lyr in (M1_LYR, M2_LYR):
                            cell = (cx, cy, lyr)
                            if cell in self.router.blocked and cell not in self.router.permanent:
                                self.router.blocked.discard(cell)
                                temp_cleared.add(cell)

            # BFS flood
            visited = set()
            queue = deque()
            for lyr in (M1_LYR, M2_LYR):
                cell = (gx, gy, lyr)
                if cell not in self.router.blocked and cell not in self.router.used:
                    queue.append(cell)
                    visited.add(cell)
            while queue and len(visited) < REACHABLE_THRESHOLD:
                cgx, cgy, clyr = queue.popleft()
                for ddx, ddy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = cgx + ddx, cgy + ddy
                    if 0 <= nx < self.router.nx and 0 <= ny < self.router.ny:
                        nb = (nx, ny, clyr)
                        if nb not in visited and nb not in self.router.blocked and nb not in self.router.used:
                            visited.add(nb)
                            queue.append(nb)
                ol = 1 - clyr
                nb = (cgx, cgy, ol)
                if nb not in visited and nb not in self.router.blocked and nb not in self.router.used:
                    visited.add(nb)
                    queue.append(nb)

            # Restore temp cleared cells
            self.router.blocked.update(temp_cleared)

            if len(visited) < REACHABLE_THRESHOLD:
                # Pin is trapped — demote permanent cells along escape
                # directions (full column, not fixed radius) so the escape
                # channel can traverse tall device bboxes.
                # NEVER demote power stub cells or OTHER devices' body cells.
                bbox = inst_bbox_nm(self.placement, inst_name)
                gbbox = (
                    self.router.to_grid(bbox[0], bbox[1])[0],
                    self.router.to_grid(bbox[0], bbox[1])[1],
                    self.router.to_grid(bbox[2], bbox[3])[0],
                    self.router.to_grid(bbox[2], bbox[3])[1],
                )
                # Demote in all 4 cardinal directions from pin to bbox
                # edge + OVERSHOOT, with CROSS_WIDTH perpendicular spread.
                # NEVER demote power M2/M1 cells or ANY device body M1 cells.
                # Pins escape via M2 (Via1 at stub top), not by cutting
                # through device M1 metallization.
                OVERSHOOT = 5
                all_device_body = set()
                for body_cells in self.device_body_cells.values():
                    all_device_body.update(body_cells)
                protected = self.power_stub_cells | self.power_m2_cells | all_device_body
                directions = [
                    (0, +1, gbbox[3] - gy + OVERSHOOT),  # up to bbox top
                    (0, -1, gy - gbbox[1] + OVERSHOOT),  # down to bbox bot
                    (+1, 0, gbbox[2] - gx + OVERSHOOT),  # right to bbox right
                    (-1, 0, gx - gbbox[0] + OVERSHOOT),  # left to bbox left
                ]
                for ddx, ddy, length in directions:
                    for step in range(length + 1):
                        cx = gx + step * ddx
                        cy = gy + step * ddy
                        for w in range(-CROSS_WIDTH, CROSS_WIDTH + 1):
                            nx = cx + w * abs(ddy)
                            ny = cy + w * abs(ddx)
                            if 0 <= nx < self.router.nx and 0 <= ny < self.router.ny:
                                for lyr in (M1_LYR, M2_LYR):
                                    cell = (nx, ny, lyr)
                                    if cell in self.router.permanent and cell not in protected:
                                        self.router.permanent.discard(cell)
                                        demoted += 1

                # Re-run escape in ALL directions (trapped pin needs
                # channels toward distant net-mates, not just nearest edge)
                self.router.add_pin_escape((ap['x'], ap['y']), bbox,
                                           all_directions=True)

                freed += 1
                print(f'    Freed trapped pin: {inst_name}.{pin_name} '
                      f'(was {len(visited)} reachable, demoted {demoted} cells)')

        print(f'  Signal escape recheck: {freed} trapped pins freed, '
              f'{demoted} cells demoted')

    # ─── Pre-routing ───

    def _pre_route_hbt(self):
        """Pre-route HBT B→C connections.

        NOTE: B→C M2 pre-route disabled — PCell M2 emitter area shorts
        B/C to E when M2 passes through the device.  Let the maze router
        find a path around the device bbox instead.
        """
        print('  HBT B→C pre-route: disabled (PCell M2 emitter conflict)')

    # ─── Per-net pin holes ───

    def _punch_net_holes(self, pin_positions):
        """Punch cross-shaped holes for ONE net's pins before routing.

        Only clears SOFT blocked cells (safe_discard skips permanent).
        Returns set of cells actually removed, for restore after routing.
        """
        ARM = 2
        punched = set()

        for p in pin_positions:
            gx, gy = self.router.to_grid(p[0], p[1])
            pin_layer = p[2] if len(p) > 2 else None

            # Always punch both layers — even M1-only pins need via to M2.
            layers = [M1_LYR, M2_LYR]

            for dx, dy in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                for step in range(ARM + 1):
                    cx = gx + step * dx
                    cy = gy + step * dy
                    if 0 <= cx < self.router.nx and 0 <= cy < self.router.ny:
                        for lyr in layers:
                            cell = (cx, cy, lyr)
                            if cell in self.router.blocked:
                                if self.router.safe_discard(cell):
                                    punched.add(cell)
        return punched

    def _restore_holes(self, punched):
        """Re-block cells that were temporarily punched for a net."""
        self.router.blocked.update(punched)

    # ─── Signal routing ───

    def _route_signals(self, seed=None):
        """Route all signal nets via maze router.

        If seed is not None, shuffle net ordering for parallel diversity.
        Different orderings → different obstacle states → different routes.
        """
        import random
        nets = {}
        for net in self.netlist['nets']:
            if net['type'] == 'signal':
                pin_list = []
                for pin_str in net['pins']:
                    inst, pin = pin_str.split('.')
                    pin_list.append((inst, pin))
                nets[net['name']] = pin_list

        route_order = self.netlist['constraints'].get('routing_order', [])
        for net_name in nets:
            if net_name not in route_order:
                route_order.append(net_name)

        if seed is not None:
            random.Random(seed).shuffle(route_order)

        pre_routed_cfg = self.netlist['constraints'].get('pre_routed_pins', [])
        pre_routed = set()
        for pair in pre_routed_cfg:
            pre_routed.add((pair[0], pair[1]))

        routed = 0
        failed = 0
        for net_name in route_order:
            if net_name not in nets:
                continue
            pin_list = nets[net_name]

            pin_positions = []
            for inst, pin in pin_list:
                if (inst, pin) in pre_routed:
                    continue
                ap = self.access_points.get((inst, pin))
                if ap:
                    if net_name == 'nmos_bias':
                        pin_positions.append((ap['x'], ap['y'], M1_LYR))
                    else:
                        pin_positions.append((ap['x'], ap['y']))
                else:
                    msg = f'{net_name}: no access point for {inst}.{pin}'
                    print(f'  WARNING: {msg}')
                    self.errors.append(msg)

            if len(pin_positions) < 2:
                continue

            punched = self._punch_net_holes(pin_positions)
            segments = self.router.route(net_name, pin_positions)
            self._restore_holes(punched)
            if segments is not None:
                self.signal_routes[net_name] = {
                    'pins': [(inst, pin) for inst, pin in pin_list
                             if (inst, pin) not in pre_routed],
                    'segments': segments,
                }
                routed += 1
                # Claim pin terminals: once connected, enforce full spacing
                # for subsequent nets (prevents adjacent different-net wires
                # at 1 grid cell = 350nm < M2 pitch 510nm).
                for p in pin_positions:
                    gp = self.router.to_grid(p[0], p[1])
                    self.router.pin_terminals.discard(gp)
                print(f'  Routed: {net_name} ({len(pin_positions)} pins, '
                      f'{len(segments)} seg)')
            else:
                failed += 1
                msg = f'{net_name}: routing FAILED'
                print(f'  FAILED: {net_name}')
                self.errors.append(msg)

        print(f'  Result: {routed} routed, {failed} failed')

    # ─── Verification ───

    def verify(self):
        """Run gate checks on routing result."""
        checks = []

        nets = [n for n in self.netlist['nets'] if n['type'] == 'signal']
        expected = len(nets)
        actual = len(self.signal_routes) + len(self.pre_routes)
        ok = actual >= expected
        checks.append(('Net coverage', f'{actual}/{expected} signal nets', ok))

        # Count unique power nets (rails may have multiple per net)
        power_nets_in_rails = set(r.get('net', rid) for rid, r in self.rails.items())
        expected_power_nets = len(set(
            n['name'] for n in self.netlist['nets'] if n['type'] == 'power'))
        ok = len(power_nets_in_rails) >= expected_power_nets
        checks.append(('Power rails',
                        f'{len(self.rails)} rails covering {len(power_nets_in_rails)}'
                        f'/{expected_power_nets} nets', ok))

        expected_drops = sum(
            len([p for p in n['pins']])
            for n in self.netlist['nets'] if n['type'] == 'power'
        )
        actual_drops = len(self.power_drops)
        ok = actual_drops >= expected_drops
        checks.append(('Power drops',
                       f'{actual_drops} drops (≥{expected_drops} pins)', ok))

        route_failures = [e for e in self.errors if 'FAILED' in e]
        ok = len(route_failures) == 0
        checks.append(('No route failures',
                       f'{len(route_failures)} failures', ok))

        pre_count = len(self.pre_routes)
        ok = pre_count >= 1
        checks.append(('HBT pre-routes', f'{pre_count} pre-routes', ok))

        total_seg = sum(len(r['segments']) for r in self.signal_routes.values())
        total_seg += sum(len(r['segments']) for r in self.pre_routes.values())
        ok = total_seg > 0
        checks.append(('Segment count', f'{total_seg} total segments', ok))

        print()
        print('=== Routing Gate Checks ===')
        n_pass = 0
        n_total = len(checks)
        all_errors = []
        for i, (name, detail, ok) in enumerate(checks, 1):
            status = 'PASS' if ok else 'FAIL'
            if ok:
                n_pass += 1
            else:
                all_errors.append(f'{name}: {detail}')
            print(f'  [{i}/{n_total}] {name}: {detail} — {status}')

        summary = 'ALL PASS' if n_pass == n_total else f'{n_pass}/{n_total}'
        print(f'\n  Gate result: {summary}')
        return n_pass, n_total, all_errors

    # ─── JSON output ───

    def to_json(self):
        """Export routing result as JSON-serializable dict."""
        ap_out = {}
        for (inst, pin), ap in self.access_points.items():
            key = f'{inst}.{pin}'
            entry = {
                'x': ap['x'], 'y': ap['y'], 'mode': ap['mode'],
            }
            if ap.get('via_pad'):
                entry['via_pad'] = ap['via_pad']
            if ap.get('m1_stub'):
                entry['m1_stub'] = ap['m1_stub']
            if ap.get('m2_stub'):
                entry['m2_stub'] = ap['m2_stub']
            ap_out[key] = entry

        power_out = {
            'rails': self.rails,
            'drops': self.power_drops,
        }

        pre_out = {}
        for net_name, pr in self.pre_routes.items():
            pre_out[net_name] = {
                'inst': pr['inst'],
                'pins': [f'{i}.{p}' for i, p in pr['pins']],
                'segments': [list(s) for s in pr['segments']],
            }

        sig_out = {}
        for net_name, sr in self.signal_routes.items():
            sig_out[net_name] = {
                'pins': [f'{i}.{p}' for i, p in sr['pins']],
                'segments': [list(s) for s in sr['segments']],
            }

        total_seg = sum(len(r['segments']) for r in self.signal_routes.values())
        total_seg += sum(len(r['segments']) for r in self.pre_routes.values())

        return {
            'version': '4.0',
            'access_points': ap_out,
            'power': power_out,
            'pre_routes': pre_out,
            'signal_routes': sig_out,
            'statistics': {
                'nets_routed': len(self.signal_routes),
                'nets_pre_routed': len(self.pre_routes),
                'nets_failed': len([e for e in self.errors if 'FAILED' in e]),
                'total_segments': total_seg,
                'total_access_points': len(self.access_points),
                'total_power_drops': len(self.power_drops),
            },
        }
