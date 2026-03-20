"""§1b+1c: Gate straps (ng=2) and gate contacts (all MOSFET devices).

IHP SG13G2 PCells provide NO Cont on gate poly — only S/D contacts.
This module adds gate poly extension, Cont, M1 pad for every gate pin.
"""

import klayout.db

from atk.pdk import (
    CONT, GATPOLY, UM,
    GATE_POLY_EXT, CNT_D_ENC, M1_MIN_AREA,
)
from atk.device import get_ng2_gate_data
from atk.verify.pcell_xray import load_gate_info
from atk.route.access import _DEVICES as _ACC_DEV, get_access_mode


def draw_gate_straps_and_contacts(top, li_m1, layout, instances,
                                   device_lib, devices_map, gate_info):
    """Draw gate straps (ng=2) and gate contacts (all MOSFETs).

    Args:
        gate_info: from load_gate_info()

    Returns:
        strap_count, gate_cont_count, gate_bridge_count: counters
        gate_cont_m1: dict pin_key -> [x1,y1,x2,y2]
    """
    # ═══ 1b. Gate straps for ng=2 devices ═══
    # ng=2 PCells have 2 separate poly gate fingers (G1, G2).
    # PCells provide NO gate Cont — only S/D contacts.
    # We add: M1 strap (G1→G2) + Cont at BOTH G1 and G2 to connect poly→M1.
    # Gate straps (ng=2)
    li_cont = layout.layer(*CONT)

    CONT_SZ = 160                        # Cont cut size (nm)
    CONT_ENC_M1_END = 50                 # M1.c1 endcap enclosure requirement
    STRAP_H = CONT_SZ                    # 160nm — M1.c=0 on top/bottom
    li_gatpoly = layout.layer(*GATPOLY)

    # Gate finger positions from device_lib.json (auto-extracted by probe_pcells_v2.py)
    NG2_GATE_DATA = {}
    for _dt in device_lib:
        _gd = get_ng2_gate_data(device_lib, _dt)
        if _gd is not None:
            NG2_GATE_DATA[_dt] = _gd

    strap_count = 0
    for inst_name, info in instances.items():
        dev_type = info['type']
        dev = devices_map[dev_type]
        # Skip non-MOSFET devices (resistors have ng=2 GatPoly but no gate)
        if dev['pcell'] not in ('nmos', 'pmos'):
            continue
        gdata = NG2_GATE_DATA.get(dev_type)
        if gdata is None:
            continue

        # PCell origin (nm, 5nm grid)
        pcell_x = round((info['x_um'] - dev['ox']) * UM)
        pcell_x = ((pcell_x + 2) // 5) * 5
        pcell_y = round((info['y_um'] - dev['oy']) * UM)
        pcell_y = ((pcell_y + 2) // 5) * 5

        # Absolute gate finger centres (nm, 5nm grid)
        g1_x = ((pcell_x + round(gdata['g1'] * UM) + 2) // 5) * 5
        g2_x = ((pcell_x + round(gdata['g2'] * UM) + 2) // 5) * 5
        # Poly bottom edge (absolute nm)
        poly_bot = ((pcell_y + round(gdata['poly_bot'] * UM) + 2) // 5) * 5

        hc = CONT_SZ // 2   # 80nm
        hs = STRAP_H // 2   # 80nm (strap H = Cont H = 160nm)

        # GatPoly extension for DRC-clean gate contacts (Cnt.d, Cnt.e, M1.b).
        # Extend poly down by GATE_POLY_EXT (230nm) below PCell poly_bot.
        ext_bot = poly_bot - GATE_POLY_EXT
        cont_cy = ext_bot + CNT_D_ENC + hc  # = poly_bot - 80

        # Draw GatPoly extensions at G1 and G2 (cap half-width for large-L)
        gi = gate_info.get(dev_type)
        g1_hw = min(gi.finger_hws[0], 500) if gi else 250
        g2_hw = min(gi.finger_hws[1], 500) if gi else 250
        for gx, ghw in ((g1_x, g1_hw), (g2_x, g2_hw)):
            top.shapes(li_gatpoly).insert(klayout.db.Box(
                gx - ghw, ext_bot, gx + ghw, poly_bot))

        # M1 strap from G1 to G2, centred on cont_cy
        m1_enc = CONT_SZ // 2 + CONT_ENC_M1_END  # 80+50=130nm
        m1_x1 = g1_x - m1_enc
        m1_x2 = g2_x + m1_enc
        m1_y1 = cont_cy - hs
        m1_y2 = cont_cy + hs
        top.shapes(li_m1).insert(klayout.db.Box(m1_x1, m1_y1, m1_x2, m1_y2))

        # Cont at G1 and G2 (in extended poly zone)
        for gx in (g1_x, g2_x):
            top.shapes(li_cont).insert(klayout.db.Box(
                gx - hc, cont_cy - hc, gx + hc, cont_cy + hc))

        # m1_pin Via1+M2 is drawn by access point system (section 3).
        # Gate extras only draws Cont+M1+GatPoly ext.  M1 overlaps with access M1.

        print(f'    {inst_name}: M1 [{m1_x1},{m1_y1},{m1_x2},{m1_y2}], '
              f'Cont@G1({g1_x},{cont_cy}) G2({g2_x},{cont_cy})')
        strap_count += 1

    # (print moved to main)

    # ═══ 1c. Gate contacts for ALL MOSFET devices ═══
    # IHP SG13G2 PCells provide NO Cont on gate poly — only S/D contacts.
    # Every gate pin needs an explicit Cont connecting poly→M1 in the gate
    # extension area (below active for all orientations here).
    # Gate access modes 'gate' and 'm1_pin' both need this.
    #
    # ng=1: single poly extension + Cont + M1 pad at G pin.
    # ng>=4: continuous GatPoly extension bar bridging ALL fingers on poly layer,
    #   then single Cont + M1 pad at finger[0] (same as ng=1).
    #   IHP ng>=4 PCells have SEPARATE gate poly rectangles per finger (380nm gap).
    #   We bridge them on GatPoly (in extension zone below Activ, no extra FETs).
    #   Gate connectivity on GatPoly, S/D connectivity on M1 — no layer conflict.
    # Gate contacts (all MOSFETs)

    from atk.route.access import _DEVICES as _ACC_DEV, get_access_mode
    from atk.pdk import M1_MIN_AREA

    gate_cont_count = 0
    gate_bridge_count = 0
    gate_cont_m1 = {}  # pin_key → [x1,y1,x2,y2] for fill checker
    hc = CONT_SZ // 2  # 80nm

    for inst_name, info in instances.items():
        dev_type = info['type']
        dev = devices_map[dev_type]
        acc = _ACC_DEV.get(dev_type)
        if acc is None:
            continue

        # Skip ng=2 — already handled by gate strap code above
        ng = dev.get('params', {}).get('ng', 1)
        if ng == 2:
            continue

        # Only MOSFET gates need Cont
        if 'G' not in acc['pins']:
            continue

        mode = get_access_mode(dev_type, 'G')
        if mode not in ('gate', 'm1_pin'):
            continue

        g_rel_x, g_rel_y = acc['pins']['G']

        # PCell origin (nm)
        pcell_x = round((info['x_um'] - dev['ox']) * UM)
        pcell_x = ((pcell_x + 2) // 5) * 5
        pcell_y = round((info['y_um'] - dev['oy']) * UM)
        pcell_y = ((pcell_y + 2) // 5) * 5

        # Gate poly bottom Y (absolute nm) — same for all fingers
        poly_bot = ((pcell_y + round(g_rel_y * UM) + 2) // 5) * 5

        # GatPoly extension geometry
        ext_bot = poly_bot - GATE_POLY_EXT
        cy = ext_bot + CNT_D_ENC + hc  # = poly_bot - 80

        gi = gate_info.get(dev_type)

        # ── ng>=4: bridge all gate poly fingers on GatPoly layer ──
        if ng >= 4 and gi and gi.ng >= 4:
            # Continuous GatPoly bar spanning finger[0]..finger[N-1].
            # Height = Gat.a min (130nm). Centered on poly_bot so bottom
            # extends only 65nm below poly_bot (vs 130nm), keeping Cnt.f
            # clearance to nearby tie Activ contacts (need ≥110nm).
            # Top half (poly_bot to poly_bot+65) overlaps existing finger
            # poly — still well below Activ (~180nm gap), no extra FETs.
            BRIDGE_H = 130  # nm total height (Gat.a min width = 130nm)
            bridge_bot = poly_bot - BRIDGE_H // 2  # 65nm below poly_bot
            bridge_top = poly_bot + BRIDGE_H // 2   # 65nm above poly_bot
            first_left = pcell_x + gi.finger_xs[0] - gi.finger_hws[0]
            last_right = pcell_x + gi.finger_xs[-1] + gi.finger_hws[-1]
            first_left = ((first_left + 2) // 5) * 5
            last_right = ((last_right + 2) // 5) * 5
            top.shapes(li_gatpoly).insert(klayout.db.Box(
                first_left, bridge_bot, last_right, bridge_top))
            gate_bridge_count += 1
            print(f'    {inst_name}: GatPoly bridge ng={gi.ng}, '
                  f'X=[{first_left},{last_right}] Y=[{bridge_bot},{bridge_top}]')

        # ── Single Cont + M1 pad at G pin (all ng values) ──
        gx = ((pcell_x + round(g_rel_x * UM) + 2) // 5) * 5

        # Draw GatPoly extension at contact finger.
        # Cap half-width: large-L ng=1 devices (e.g. pmos_mirror L=100µm)
        # have finger_hws ~50µm — a 100µm GatPoly bar would bridge nets.
        gate_hw = min(gi.finger_hws[0], 500) if gi else 250
        top.shapes(li_gatpoly).insert(klayout.db.Box(
            gx - gate_hw, ext_bot, gx + gate_hw, poly_bot))

        # Cont on gate poly (in extended zone)
        top.shapes(li_cont).insert(klayout.db.Box(
            gx - hc, cy - hc, gx + hc, cy + hc))

        # M1 pad covering Cont.  Via1+M2 drawn by access point system.
        # Top capped at poly_bot (avoid M1.b with S/D M1).
        # Extend downward to satisfy M1.d area ≥ 0.09 µm².
        # Width sized so downward extension stays ≤ M1.b-safe distance
        # from non-same-net M1 shapes below.
        import math
        m1_hw_min = hc + CONT_ENC_M1_END  # 130nm floor
        m1_hw_area = int(math.ceil(math.sqrt(M1_MIN_AREA) / 2))  # ~150nm
        m1_hw = ((max(m1_hw_min, m1_hw_area) + 4) // 5) * 5  # 5nm grid
        m1_w = 2 * m1_hw
        m1_min_h = (M1_MIN_AREA + m1_w - 1) // m1_w
        m1_min_h = ((m1_min_h + 4) // 5) * 5  # 5nm grid
        m1_h = max(m1_min_h, poly_bot - (cy - hc))
        gc_m1 = [gx - m1_hw, poly_bot - m1_h, gx + m1_hw, poly_bot]
        top.shapes(li_m1).insert(klayout.db.Box(*gc_m1))
        gate_cont_m1[f'{inst_name}.G'] = gc_m1

        gate_cont_count += 1

    # (print moved to main)


    return strap_count, gate_cont_count, gate_bridge_count, gate_cont_m1
