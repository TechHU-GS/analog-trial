#!/usr/bin/env python3
"""Route inter-module nets using M3/M4/Via2/Via3 only.

Layer strategy: M3=H, M4=V, M5=H (LEF default).
No M1/M2 added — only Via2 landing on existing M2 pads.

Route pattern for L-shaped connection:
  Source M2 pad → Via2 → M3 horizontal → Via3 → M4 vertical → Via3 → M3 → Via2 → Dest M2 pad

For simple cases (small Δx or Δy), simpler patterns are used.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_m3.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Layer definitions (GDS layer, datatype)
M2 = (10, 0)
VIA2 = (29, 0)
M3 = (30, 0)
VIA3 = (49, 0)
M4 = (50, 0)

# DRC rules (nm)
VIA_SZ = 190      # Via2/Via3 size
VIA_SP = 220      # Via2/Via3 spacing
M3_W = 200        # M3 min width
M3_SP = 210       # M3 min spacing
M4_W = 200        # M4 min width
M_ENC = 50        # Metal endcap enclosure of via
M_ENC_SIDE = 5    # Metal side enclosure of via (min)

# Safe pad sizes for via landing
VIA_PAD = 290     # metal pad = via + 2*50nm endcap enclosure


def box(x1, y1, x2, y2):
    return pya.Box(int(x1), int(y1), int(x2), int(y2))


def add_via2(cell, layers, cx, cy):
    """Add Via2 centered at (cx, cy). M2 pad assumed already present. Adds M3 pad."""
    hs = VIA_SZ // 2  # 95
    cell.shapes(layers['via2']).insert(box(cx - hs, cy - hs, cx + hs, cy + hs))
    # M3 pad
    pad_hs = VIA_PAD // 2  # 145
    cell.shapes(layers['m3']).insert(box(cx - pad_hs, cy - pad_hs, cx + pad_hs, cy + pad_hs))


def add_via3(cell, layers, cx, cy):
    """Add Via3 at (cx, cy). Adds M3 and M4 pads."""
    hs = VIA_SZ // 2
    cell.shapes(layers['via3']).insert(box(cx - hs, cy - hs, cx + hs, cy + hs))
    pad_hs = VIA_PAD // 2
    cell.shapes(layers['m3']).insert(box(cx - pad_hs, cy - pad_hs, cx + pad_hs, cy + pad_hs))
    cell.shapes(layers['m4']).insert(box(cx - pad_hs, cy - pad_hs, cx + pad_hs, cy + pad_hs))


def check_collision(cell, layers, new_shape, layer_name):
    """Check if new_shape conflicts with existing shapes on the same layer.
    Returns list of violation descriptions, empty if clean."""
    layer_map = {'m3': M3, 'm4': M4, 'via2': VIA2, 'via3': VIA3}
    ln, dt = layer_map[layer_name]
    li = cell.layout().find_layer(ln, dt)
    if li is None:
        return []

    existing = pya.Region(cell.begin_shapes_rec(li))
    new_r = pya.Region(new_shape)

    violations = []
    # Check overlap (= short with different net)
    overlap = existing & new_r
    if overlap.count() > 0:
        violations.append(f'OVERLAP on {layer_name}')

    # Check spacing (< 210nm)
    combined = existing + new_r
    space_viol = combined.space_check(210)
    if space_viol.count() > 0:
        violations.append(f'SPACING on {layer_name} ({space_viol.count()} violations)')

    return violations


def route_L(cell, layers, src_x, src_y, dst_x, dst_y, name, m4_x=None):
    """Route an L-shaped connection: M3-H from src, Via3, M4-V to dst level, Via3, M3-H to dst.

    Pattern: src → Via2 → M3(H) → Via3 → M4(V) → Via3 → M3(H) → Via2 → dst
    m4_x: explicit M4 vertical x position (to avoid overlap with parallel routes).
    """
    print(f'\n--- {name}: ({src_x/1000:.1f},{src_y/1000:.1f}) → ({dst_x/1000:.1f},{dst_y/1000:.1f}) ---')

    # Choose M4 vertical x position
    if m4_x is not None:
        mid_x = m4_x
    else:
        mid_x = (src_x + dst_x) // 2
    # Snap to 5nm grid
    mid_x = (mid_x // 5) * 5

    w3 = 300   # M3 wire width (comfortable > 200nm min)
    w4 = 300   # M4 wire width
    hw3 = w3 // 2
    hw4 = w4 // 2

    # Build shapes first, check collisions, then commit
    m3_y = src_y
    x1_s = min(src_x, mid_x); x2_s = max(src_x, mid_x)
    m3_src = box(x1_s - 145, m3_y - hw3, x2_s + 145, m3_y + hw3)

    y1 = min(src_y, dst_y); y2 = max(src_y, dst_y)
    m4_seg = box(mid_x - hw4, y1 - 145, mid_x + hw4, y2 + 145)

    m3_y2 = dst_y
    x1_d = min(mid_x, dst_x); x2_d = max(mid_x, dst_x)
    m3_dst = box(x1_d - 145, m3_y2 - hw3, x2_d + 145, m3_y2 + hw3)

    # Collision check
    all_clean = True
    for ln, shape in [('m3', m3_src), ('m4', m4_seg), ('m3', m3_dst)]:
        violations = check_collision(cell, layers, shape, ln)
        if violations:
            b = shape
            print(f'  ❌ {", ".join(violations)} at ({b.left/1000:.1f},{b.bottom/1000:.1f})-({b.right/1000:.1f},{b.top/1000:.1f})')
            all_clean = False

    if not all_clean:
        print(f'  ⚠️ {name}: SKIPPED due to collisions')
        return False

    # Commit all shapes
    add_via2(cell, layers, src_x, src_y)
    cell.shapes(layers['m3']).insert(m3_src)
    add_via3(cell, layers, mid_x, src_y)
    cell.shapes(layers['m4']).insert(m4_seg)
    add_via3(cell, layers, mid_x, dst_y)
    cell.shapes(layers['m3']).insert(m3_dst)
    add_via2(cell, layers, dst_x, dst_y)

    print(f'  ✅ {name}: routed, collision-free')
    return True


def route():
    print('=== M3/M4 Inter-Module Routing ===')

    ly = pya.Layout()
    ly.read(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell = ly.top_cell()

    layers = {
        'm2': ly.layer(*M2),
        'via2': ly.layer(*VIA2),
        'm3': ly.layer(*M3),
        'via3': ly.layer(*VIA3),
        'm4': ly.layer(*M4),
    }

    # ─── Route 1: comp_outp ───
    # comp M2 pad center: (142620, 27340)
    # hbridge M2 pad center: (150500, 33900)
    # M4 at x=148000 (right side, closer to hbridge)
    route_L(cell, layers,
            142620, 27340,   # comp comp_outp
            150500, 33900,   # hbridge comp_outp gate
            'comp_outp', m4_x=148000)

    # ─── Route 2: comp_outn ───
    # comp M2 pad center: (142120, 29840)
    # hbridge M2 pad center: (150500, 39840)
    # M4 at x=144500 (left side, closer to comp) — 3.5um gap from comp_outp M4
    route_L(cell, layers,
            142120, 29840,   # comp comp_outn
            150500, 39840,   # hbridge comp_outn gate
            'comp_outn', m4_x=144500)

    # ─── Route 3: chop_out ───
    # chopper M2 bus right end: (92360, 22300) — use right-end Via1 pad center
    # rin M2 pad center: (113210, 30830)
    route_L(cell, layers,
            92360, 22300,    # chopper chop_out
            113210, 30830,   # rin terminal
            'chop_out')

    # ─── Route 4: exc_out ───
    # hbridge_drive M2 bus (MS1.D+MS3.D): center (65700, 22650)
    # sw M2 bus (all SW.S): center (66350, 34150)
    # Nearly vertical — M4 at x=66000
    route_L(cell, layers,
            65700, 22650,    # hbridge_drive exc_out
            66350, 34150,    # sw exc_out
            'exc_out', m4_x=66000)

    # ─── Write ───
    out_path = os.path.join(OUT_DIR, 'soilz_assembled.gds')
    ly.write(out_path)
    print(f'\n  Output: {out_path}')

    # Quick DRC on M3/M4
    m3_r = pya.Region(cell.begin_shapes_rec(layers['m3']))
    m4_r = pya.Region(cell.begin_shapes_rec(layers['m4']))
    print(f'\n  Quick DRC:')
    print(f'    M3.b (space): {m3_r.space_check(210).count()}')
    print(f'    M3.a (width): {m3_r.width_check(200).count()}')
    print(f'    M4.b (space): {m4_r.space_check(210).count()}')
    print(f'    M4.a (width): {m4_r.width_check(200).count()}')


if __name__ == '__main__':
    route()
    print('\n=== Done ===')
