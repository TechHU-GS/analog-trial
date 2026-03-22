#!/usr/bin/env python3
"""Route LONG inter-module nets involving the digital block.

Digital block has M3 pins at block boundary (LibreLane port labels on layer 30,25).
Pattern: extend M3 from digital pin → Via3 → M4 vertical → Via3 → M3 → Via2 → target M2.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_long.py

Prerequisite: run route_m3.py first (places LOCAL+MEDIUM routes).
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

M2 = (10, 0)
VIA2 = (29, 0)
M3 = (30, 0)
VIA3 = (49, 0)
M4 = (50, 0)

VIA_SZ = 190
VIA_PAD = 290
W = 210  # wire width


def box(x1, y1, x2, y2):
    return pya.Box(int(x1), int(y1), int(x2), int(y2))


def check_collision(cell, new_shape, layer_gds):
    """Check overlap and spacing between new shape and existing shapes only."""
    li = cell.layout().find_layer(*layer_gds)
    if li is None:
        return []
    existing = pya.Region(cell.begin_shapes_rec(li))
    new_r = pya.Region(new_shape)
    violations = []
    if (existing & new_r).count() > 0:
        violations.append(f'OVERLAP on ({layer_gds[0]},{layer_gds[1]})')
    # Check spacing: new vs existing only (not existing vs existing)
    sep = new_r.separation_check(existing, 210)
    if sep.count() > 0:
        violations.append(f'SPACING on ({layer_gds[0]},{layer_gds[1]})')
    return violations


def route_digital_to_m2(cell, layers, dig_x, dig_y, dst_x, dst_y, m4_x, name):
    """Route from digital M3 pin to a target M2 pad.

    Pattern: M3(H) from digital → Via3 → M4(V) → Via3 → M3(H) → Via2 → M2
    dig_x/dig_y: absolute position of digital M3 pin (already on M3)
    dst_x/dst_y: absolute position of target M2 pad
    m4_x: M4 vertical column x position
    """
    print(f'\n--- {name}: dig({dig_x/1000:.1f},{dig_y/1000:.1f}) → dst({dst_x/1000:.1f},{dst_y/1000:.1f}) ---')

    hw = W // 2
    pad_hs = VIA_PAD // 2
    via_hs = VIA_SZ // 2

    # Build shapes
    shapes = []

    # 1. M3 horizontal from digital pin to M4 column
    x1 = min(dig_x, m4_x)
    x2 = max(dig_x, m4_x)
    m3_src = box(x1 - pad_hs, dig_y - hw, x2 + pad_hs, dig_y + hw)
    shapes.append((M3, m3_src))

    # 2. Via3 at (m4_x, dig_y)
    shapes.append((VIA3, box(m4_x - via_hs, dig_y - via_hs, m4_x + via_hs, dig_y + via_hs)))
    shapes.append((M4, box(m4_x - pad_hs, dig_y - pad_hs, m4_x + pad_hs, dig_y + pad_hs)))

    # 3. M4 vertical from dig_y to dst_y
    y1 = min(dig_y, dst_y)
    y2 = max(dig_y, dst_y)
    m4_seg = box(m4_x - hw, y1 - pad_hs, m4_x + hw, y2 + pad_hs)
    shapes.append((M4, m4_seg))

    # 4. Via3 at (m4_x, dst_y)
    shapes.append((VIA3, box(m4_x - via_hs, dst_y - via_hs, m4_x + via_hs, dst_y + via_hs)))
    shapes.append((M3, box(m4_x - pad_hs, dst_y - pad_hs, m4_x + pad_hs, dst_y + pad_hs)))

    # 5. M3 horizontal from M4 column to target Via2
    x1 = min(m4_x, dst_x)
    x2 = max(m4_x, dst_x)
    m3_dst = box(x1 - pad_hs, dst_y - hw, x2 + pad_hs, dst_y + hw)
    shapes.append((M3, m3_dst))

    # 6. Via2 at target (dst_x, dst_y)
    shapes.append((VIA2, box(dst_x - via_hs, dst_y - via_hs, dst_x + via_hs, dst_y + via_hs)))
    shapes.append((M3, box(dst_x - pad_hs, dst_y - pad_hs, dst_x + pad_hs, dst_y + pad_hs)))

    # Collision check — skip source M3 (intentional overlap with digital pin)
    all_clean = True
    for i, (layer_gds, shape) in enumerate(shapes):
        if layer_gds in [VIA2, VIA3]:
            continue  # skip via collision
        if i == 0:
            continue  # skip source M3 (connects to digital pin by overlap)
        violations = check_collision(cell, shape, layer_gds)
        if violations:
            b = shape
            print(f'  ❌ {", ".join(violations)} at ({b.left/1000:.1f},{b.bottom/1000:.1f})-({b.right/1000:.1f},{b.top/1000:.1f})')
            all_clean = False

    if not all_clean:
        print(f'  ⚠️ {name}: SKIPPED')
        return False

    # Commit
    for layer_gds, shape in shapes:
        li = layers.get(layer_gds)
        if li is None:
            li = cell.layout().layer(*layer_gds)
            layers[layer_gds] = li
        cell.shapes(li).insert(shape)

    print(f'  ✅ {name}: routed')
    return True


def route():
    print('=== LONG Net Routing (digital → analog) ===')

    ly = pya.Layout()
    ly.read(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell = ly.top_cell()

    layers = {
        M2: ly.layer(*M2),
        VIA2: ly.layer(*VIA2),
        M3: ly.layer(*M3),
        VIA3: ly.layer(*VIA3),
        M4: ly.layer(*M4),
    }

    # Digital block placed at (16500, 5000), no rotation
    DIG_X = 16500
    DIG_Y = 5000

    # Digital M3 pin positions — use pin OUTER EDGE (not center)
    # to avoid overlapping with digital internal M3.
    # Right edge pins: local x=29.5 (rightmost M3 extent) → abs x=46.0
    # Left edge pins: local x=0.5 (leftmost M3 extent) → abs x=17.0
    DIG_RIGHT = DIG_X + 29500  # 46000 — right edge of M3 pins
    DIG_LEFT = DIG_X + 500     # 17000 — left edge of M3 pins
    dig_ports = {
        'phi_n':    (DIG_RIGHT, DIG_Y + 60100),  # (46000, 65100)
        'phi_p':    (DIG_RIGHT, DIG_Y + 58400),  # (46000, 63400)
        'f_exc':    (DIG_RIGHT, DIG_Y + 50000),  # (46000, 55000)
        'f_exc_b':  (DIG_RIGHT, DIG_Y + 59200),  # (46000, 64200)
        # Left edge port:
        'vco_out':  (DIG_LEFT,  DIG_Y + 23100),  # (17000, 28100)
    }

    # ─── phi_p: digital → hbridge_drive MS1.G+MS4.G ───
    # hbridge_drive M2 bus y_c=23.7 (x=68.1-73.9, 4 Via1): likely phi_p gates
    route_digital_to_m2(cell, layers,
                        dig_ports['phi_p'][0], dig_ports['phi_p'][1],
                        68100, 23700,  # hbridge_drive left end of top bus
                        55000,         # M4 between digital and hbridge_drive
                        'phi_p')

    # ─── phi_n: digital → hbridge_drive MS2.G+MS3.G ───
    # hbridge_drive M2 bus y_c=23.2 (x=65.4-73.0, 2 Via1): likely phi_n gates
    route_digital_to_m2(cell, layers,
                        dig_ports['phi_n'][0], dig_ports['phi_n'][1],
                        65400, 23200,  # hbridge_drive left end
                        57000,         # M4 column (2um from phi_p's M4)
                        'phi_n')

    # ─── f_exc + f_exc_b: Z-route to avoid M3 congestion at y=22-24 ───
    # M3 at y=22-24 is occupied by exc_out/phi routes. Use intermediate M3 at y=28/30.
    # Pattern: dig M3 → Via3 → M4↓(to mid_y) → Via3 → M3(mid_y) → Via3 → M4↓(to dst) → Via3 → M3 → Via2

    def route_z(dig_x, dig_y, dst_x, dst_y, m4_top, mid_y, m4_bot, name):
        """Z-route with intermediate M3 level to avoid congestion."""
        print(f'\n--- {name}: Z dig({dig_x/1000:.1f},{dig_y/1000:.1f}) → dst({dst_x/1000:.1f},{dst_y/1000:.1f}) mid_y={mid_y/1000:.0f} ---')
        hw, phs, vhs = W//2, VIA_PAD//2, VIA_SZ//2
        S = []  # (layer_gds, shape)

        # 1: M3 digital → m4_top
        S.append((M3, box(min(dig_x,m4_top)-phs, dig_y-hw, max(dig_x,m4_top)+phs, dig_y+hw)))
        for lg in [VIA3, M4, M3]:
            S.append((lg, box(m4_top-phs, dig_y-phs, m4_top+phs, dig_y+phs)))
        # 2: M4 dig_y → mid_y
        S.append((M4, box(m4_top-hw, min(dig_y,mid_y)-phs, m4_top+hw, max(dig_y,mid_y)+phs)))
        for lg in [VIA3, M3, M4]:
            S.append((lg, box(m4_top-phs, mid_y-phs, m4_top+phs, mid_y+phs)))
        # 3: M3 m4_top → m4_bot at mid_y
        S.append((M3, box(min(m4_top,m4_bot)-phs, mid_y-hw, max(m4_top,m4_bot)+phs, mid_y+hw)))
        for lg in [VIA3, M4, M3]:
            S.append((lg, box(m4_bot-phs, mid_y-phs, m4_bot+phs, mid_y+phs)))
        # 4: M4 mid_y → dst_y
        S.append((M4, box(m4_bot-hw, min(mid_y,dst_y)-phs, m4_bot+hw, max(mid_y,dst_y)+phs)))
        for lg in [VIA3, M3]:
            S.append((lg, box(m4_bot-phs, dst_y-phs, m4_bot+phs, dst_y+phs)))
        # 5: M3 m4_bot → dst Via2
        S.append((M3, box(min(m4_bot,dst_x)-phs, dst_y-hw, max(m4_bot,dst_x)+phs, dst_y+hw)))
        S.append((VIA2, box(dst_x-vhs, dst_y-vhs, dst_x+vhs, dst_y+vhs)))
        S.append((M3, box(dst_x-phs, dst_y-phs, dst_x+phs, dst_y+phs)))

        # Check (skip first M3 = digital overlap, skip vias)
        ok = True
        for i, (lg, sh) in enumerate(S):
            if lg in [VIA2, VIA3] or i == 0:
                continue
            v = check_collision(cell, sh, lg)
            if v:
                b = sh
                print(f'  ❌ {", ".join(v)} at ({b.left/1000:.1f},{b.bottom/1000:.1f})-({b.right/1000:.1f},{b.top/1000:.1f})')
                ok = False
        if not ok:
            print(f'  ⚠️ {name}: SKIPPED')
            return False
        for lg, sh in S:
            cell.shapes(layers.get(lg, cell.layout().layer(*lg))).insert(sh)
        print(f'  ✅ {name}: routed (Z)')
        return True

    # f_exc: mid_y=28000, m4_top@52, m4_bot@86 (near chopper)
    route_z(dig_ports['f_exc'][0], dig_ports['f_exc'][1],
            86200, 23000, 52000, 28000, 86000, 'f_exc')

    # f_exc_b: mid_y=30000, m4_top@50, m4_bot@92
    route_z(dig_ports['f_exc_b'][0], dig_ports['f_exc_b'][1],
            91900, 23550, 50000, 30000, 92000, 'f_exc_b')

    # ─── vco_out: digital LEFT → vco_buffer ───
    # digital LEFT M3 port: (17000, 28100)
    # vco_buffer M2 bus: (180800,7900)-(182000,8300), center (181400, 8100)
    # 161um horizontal M3 run! M4 near vco_buffer.
    route_digital_to_m2(cell, layers,
                        dig_ports['vco_out'][0], dig_ports['vco_out'][1],
                        181400, 8100,   # vco_buffer vco_out bus
                        178000,         # M4 near vco_buffer
                        'vco_out')

    # ─── net_c1: ptat_core gate bus → bias_cascode gate bus ───
    # Both M2 endpoints. Use L-route pattern (Via2 → M3 → Via3 → M4 → Via3 → M3 → Via2)
    # ptat_core bus right end: (169300, 62150)
    # bias_cascode bus right end: (107700, 59300)
    # Nearly horizontal, Δy=2.9um. M4 at x=135000.
    route_digital_to_m2(cell, layers,
                        107700, 59300,   # bias_cascode (treated as "digital" — just needs M3 pad)
                        169300, 62150,   # ptat_core
                        135000,          # M4 column
                        'net_c1')
    # Note: source is M2 not M3, so Via2 is needed at source too.
    # route_digital_to_m2 doesn't add Via2 at source — add manually:
    vhs = VIA_SZ // 2
    phs = VIA_PAD // 2
    cell.shapes(layers[VIA2]).insert(box(107700-vhs, 59300-vhs, 107700+vhs, 59300+vhs))
    cell.shapes(layers[M3]).insert(box(107700-phs, 59300-phs, 107700+phs, 59300+phs))

    # ─── net_rptat: ptat_core MN2.S → rptat PLUS ───
    # Both M2 endpoints. ptat_core (160500, 51000), rptat (188100, 79100)
    route_digital_to_m2(cell, layers,
                        160500, 51000,   # ptat_core bottom M2 bus
                        188100, 79100,   # rptat M2 pad
                        175000,          # M4 column
                        'net_rptat')
    # Add Via2 at ptat_core source (M2, not M3)
    cell.shapes(layers[VIA2]).insert(box(160500-vhs, 51000-vhs, 160500+vhs, 51000+vhs))
    cell.shapes(layers[M3]).insert(box(160500-phs, 51000-phs, 160500+phs, 51000+phs))

    # ─── nmos_bias: bias_mn → vco_5stage bottom bus ───
    # bias_mn M2 bus: (161.9,36.7)-(167.3,37.0). Via2 at left end (163000, 36900)
    # vco_5stage bottom bus: (155.0,2.5)-(157.9,2.8). Via2 at right end (157000, 2600)
    route_digital_to_m2(cell, layers,
                        163000, 36900,  # bias_mn (as "source")
                        157000, 2600,   # vco_5stage nmos_bias bus
                        162000,         # M4 column
                        'nmos_bias')
    cell.shapes(layers[VIA2]).insert(box(163000-vhs, 36900-vhs, 163000+vhs, 36900+vhs))
    cell.shapes(layers[M3]).insert(box(163000-phs, 36900-phs, 163000+phs, 36900+phs))

    # ─── pmos_bias: SKIPPED — bias_mn MN_pgen.D has M1 only, no M2 pad ───
    # Need Via1+M2 at MN_pgen.D (local x=8.13-8.29) before routing
    print('\n--- pmos_bias: SKIPPED (no M2 endpoint in bias_mn) ---')

    # ─── Write ───
    out_path = os.path.join(OUT_DIR, 'soilz_assembled.gds')
    ly.write(out_path)
    print(f'\n  Output: {out_path}')

    # Quick DRC
    m3_r = pya.Region(cell.begin_shapes_rec(layers[M3]))
    m4_r = pya.Region(cell.begin_shapes_rec(layers[M4]))
    print(f'  Quick DRC: M3.b={m3_r.space_check(210).count()}, M4.b={m4_r.space_check(210).count()}')


if __name__ == '__main__':
    route()
    print('\n=== Done ===')
