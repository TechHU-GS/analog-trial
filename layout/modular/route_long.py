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

    # ─── f_exc: digital → chopper (Mchop1n.G+Mchop2p.G) ───
    # chopper at (84, 21). f_exc connects to chopper gates.
    # Need to find chopper f_exc M2 endpoint.
    # From build_chopper.py: f_exc = gate1/2 bus at local y≈1.0-1.35
    # In assembled (no rotation): y ≈ 21+1.2 = 22.2
    # Chopper M2 bus at y_c=22.3 is chop_out (widest bus, all S pins)
    # The other buses might be f_exc/f_exc_b
    # From earlier probe: chopper has buses at y=22.14 and two shorter at y=22.8/23.5(approx)
    # Actually from the chopper local M2 probe:
    #   y=0.34-0.66: chop_out (widest)
    #   y=1.04-1.35: f_exc? (2 Via1)
    #   y=1.75-2.06: f_exc_b? (2 Via1)
    # In assembled (chopper at 84000, 21000):
    #   f_exc ≈ y=21000+1200 = 22200 ... but this is very close to chop_out bus
    # Let me use the second bus: assembled y≈22200+800=23000? Need exact position.
    # From earlier full probe: chopper buses were:
    #   (84.0,22.14)-(92.36,22.45) = chop_out
    #   (84.9,22.84)-(87.56,23.15) = f_exc?
    #   (90.56,23.55)-(93.24,23.86) = f_exc_b?
    # Let me try the second bus center: (86.2, 23.0)
    route_digital_to_m2(cell, layers,
                        dig_ports['f_exc'][0], dig_ports['f_exc'][1],
                        86200, 23000,  # chopper f_exc bus (approx)
                        52000,         # M4 between digital and chopper
                        'f_exc')

    # ─── f_exc_b: digital → chopper (Mchop1p.G+Mchop2n.G) ───
    route_digital_to_m2(cell, layers,
                        dig_ports['f_exc_b'][0], dig_ports['f_exc_b'][1],
                        91900, 23550,  # chopper f_exc_b bus (approx)
                        50000,         # M4 column
                        'f_exc_b')

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
