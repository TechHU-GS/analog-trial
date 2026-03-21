#!/usr/bin/env python3
"""Build H-bridge (SR latch) with complete routing including cross-coupling.

Circuit:
    Left: Mn1a(gnd→n1_mid)→Mn1b(n1_mid→lat_q), Mp1a(vdd→lat_q), Mp1b(vdd→lat_q)
    Right: Mn2a(gnd→n2_mid)→Mn2b(n2_mid→lat_qb), Mp2a(vdd→lat_qb), Mp2b(vdd→lat_qb)
    Cross: lat_q→Mn2b.G+Mp2b.G, lat_qb→Mn1b.G+Mp1b.G
    Input: comp_outp→Mn1a.G+Mp1a.G, comp_outn→Mn2a.G+Mp2a.G

Gate positions:
    NMOS (y=0-2.36): Mn1a.G(1.58-2.08), Mn1b.G(3.46-3.96), Mn2a.G(8.64-9.14), Mn2b.G(10.52-11.02)
    PMOS (y=5.63-7.99): Mp1a.G(0.65-1.15), Mp1b.G(3.15-3.65), Mp2a.G(8.95-9.45), Mp2b.G(11.45-11.95)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_hbridge.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

M1 = (8, 0)
M2 = (10, 0)
VIA1 = (19, 0)
ACTIV = (1, 0)
CONT = (6, 0)
PSD = (14, 0)
GATPOLY = (5, 0)


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building H-bridge (SR latch) ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # ─── Step 1: Extract PCells ───
    print('\n--- Step 1: Extract ---')
    search = pya.Box(39000, 125500, 52500, 136000)
    origin_x = 39700
    origin_y = 126000

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('hbridge')

    for li in src.layer_indices():
        info = src.get_info(li)
        tli = out.layer(info.layer, info.datatype)
        region = pya.Region(src_top.begin_shapes_rec(li))
        for poly in (region & pya.Region(search)).each():
            cell.shapes(tli).insert(poly.moved(-origin_x, -origin_y))

    l_m1 = out.layer(*M1)
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)
    l_activ = out.layer(*ACTIV)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_poly = out.layer(*GATPOLY)

    # ─── Step 2: Ties (positions avoid gate routing areas) ───
    print('--- Step 2: Ties ---')
    # ptap: x=6.5 (center gap, away from all gates)
    for px in [6500]:
        cell.shapes(l_activ).insert(box(px, 2800, px+500, 3300))
        cell.shapes(l_m1).insert(box(px, 2800, px+500, 3300))
        cell.shapes(l_psd).insert(box(px-100, 2700, px+600, 3400))
        cell.shapes(l_cont).insert(box(px+170, 2970, px+330, 3130))
    # ntap: inside each NWell, at y=8.0
    for nx in [400, 2900, 8700, 11200]:
        cell.shapes(l_activ).insert(box(nx, 8000, nx+500, 8500))
        cell.shapes(l_m1).insert(box(nx, 8000, nx+500, 8500))
        cell.shapes(l_cont).insert(box(nx+170, 8170, nx+330, 8330))

    # ─── Step 3: n1_mid, n2_mid M1 ───
    print('--- Step 3: Internal M1 ---')
    cell.shapes(l_m1).insert(box(2190, 180, 3350, 340))   # n1_mid
    cell.shapes(l_m1).insert(box(9250, 180, 10410, 340))   # n2_mid

    # ─── Step 4: lat_q/lat_qb S/D M2 ───
    print('--- Step 4: lat_q/qb S/D M2 ---')

    def add_via1(strip_xl, strip_xr, via_y):
        cx = (strip_xl + strip_xr) // 2
        hw = 155
        cell.shapes(l_m1).insert(box(cx-hw, via_y-hw, cx+hw, via_y+hw))
        cell.shapes(l_via1).insert(box(cx-95, via_y-95, cx+95, via_y+95))
        cell.shapes(l_m2).insert(box(cx-245, via_y-155, cx+245, via_y+155))
        return cx

    y_latq = 4000
    y_latqb = 4600

    # lat_q: Mn1b.D[4070-4230] + Mp1a.D[1260-1420] + Mp1b.D[3760-3920]
    cx1 = add_via1(4070, 4230, 1800)
    cx2 = add_via1(1260, 1420, 6200)
    cx3 = add_via1(3760, 3920, 6200)
    cell.shapes(l_m2).insert(box(cx1-150, 1645, cx1+150, y_latq+155))
    cell.shapes(l_m2).insert(box(cx2-150, y_latq-155, cx2+150, 6355))
    cell.shapes(l_m2).insert(box(cx3-150, y_latq-155, cx3+150, 6355))
    cell.shapes(l_m2).insert(box(min(cx2,cx1,cx3)-150, y_latq-155,
                                  max(cx2,cx1,cx3)+150, y_latq+155))

    # lat_qb: Mn2b.D[11130-11290] + Mp2a.D[9560-9720] + Mp2b.D[12060-12220]
    cx4 = add_via1(11130, 11290, 1800)
    cx5 = add_via1(9560, 9720, 6200)
    cx6 = add_via1(12060, 12220, 6200)
    cell.shapes(l_m2).insert(box(cx4-150, 1645, cx4+150, y_latqb+155))
    cell.shapes(l_m2).insert(box(cx5-150, y_latqb-155, cx5+150, 6355))
    cell.shapes(l_m2).insert(box(cx6-150, y_latqb-155, cx6+150, 6355))
    cell.shapes(l_m2).insert(box(min(cx5,cx4,cx6)-150, y_latqb-155,
                                  max(cx5,cx4,cx6)+150, y_latqb+155))

    # ─── Step 5: Cross-coupling gate routing ───
    print('--- Step 5: Cross-coupling gates ---')

    def add_gate_contact(poly_cx, cont_cy):
        cell.shapes(l_cont).insert(box(poly_cx-80, cont_cy-80, poly_cx+80, cont_cy+80))
        cell.shapes(l_m1).insert(box(poly_cx-155, cont_cy-155, poly_cx+155, cont_cy+155))
        return poly_cx

    # lat_q → Mn2b.G(10.52-11.02) + Mp2b.G(11.45-11.95)
    # Use M1 verticals to avoid M2 crossing with lat_qb
    cell.shapes(l_poly).insert(box(10520, 2360, 11020, 2860))  # Mn2b.G poly ext above
    g_mn2b = add_gate_contact(10770, 2550)
    # M1 vertical from gate contact up to lat_q M2 level, Via1 at top
    cell.shapes(l_m1).insert(box(10615, 2705, 10925, y_latq+155))
    cell.shapes(l_via1).insert(box(10675, y_latq-95, 10865, y_latq+95))

    cell.shapes(l_poly).insert(box(11450, 5130, 11950, 5630))  # Mp2b.G poly ext below
    g_mp2b = add_gate_contact(11700, 5380)
    # M1 vertical from gate contact down to lat_q M2 level, Via1 at bottom
    cell.shapes(l_m1).insert(box(11545, y_latq-155, 11855, 5225))
    cell.shapes(l_via1).insert(box(11605, y_latq-95, 11795, y_latq+95))

    # Extend lat_q M2 horizontal to cover both Via1s
    lat_q_right = max(g_mn2b, g_mp2b) + 150
    cell.shapes(l_m2).insert(box(cx1+150, y_latq-155, lat_q_right, y_latq+155))
    print(f'  lat_q cross: → Mn2b.G(x={g_mn2b/1000:.2f}) + Mp2b.G(x={g_mp2b/1000:.2f})')

    # lat_qb → Mn1b.G(3.46-3.96) + Mp1b.G(3.15-3.65)
    cell.shapes(l_poly).insert(box(3460, 2360, 3960, 2860))  # Mn1b.G poly ext above
    g_mn1b = add_gate_contact(3710, 2550)
    cell.shapes(l_m1).insert(box(3555, 2705, 3865, y_latqb+155))
    cell.shapes(l_via1).insert(box(3615, y_latqb-95, 3805, y_latqb+95))

    cell.shapes(l_poly).insert(box(3150, 5130, 3650, 5630))  # Mp1b.G poly ext below
    g_mp1b = add_gate_contact(3400, 5380)
    cell.shapes(l_m1).insert(box(3245, y_latqb-155, 3555, 5225))
    cell.shapes(l_via1).insert(box(3305, y_latqb-95, 3495, y_latqb+95))

    lat_qb_left = min(g_mn1b, g_mp1b) - 150
    cell.shapes(l_m2).insert(box(lat_qb_left, y_latqb-155, cx5-150, y_latqb+155))
    print(f'  lat_qb cross: → Mn1b.G(x={g_mn1b/1000:.2f}) + Mp1b.G(x={g_mp1b/1000:.2f})')

    # ─── Step 6: Input gate routing (comp_outp, comp_outn) ───
    print('--- Step 6: Input gates ---')

    # comp_outp: Mn1a.G(1.58-2.08) ↔ Mp1a.G(0.65-1.15)
    # Both on left side, close X. Use M1 vertical through gap.
    cell.shapes(l_poly).insert(box(1580, 2360, 2080, 2860))  # Mn1a.G ext above
    cell.shapes(l_poly).insert(box(650, 5130, 1150, 5630))   # Mp1a.G ext below
    add_gate_contact(1830, 2550)  # Mn1a.G
    add_gate_contact(900, 5380)   # Mp1a.G
    # M1 L-route: vertical at x≈0.90 from Mp1a pad (5.38) down to y=2.70,
    # then horizontal to Mn1a pad (1.83)
    cell.shapes(l_m1).insert(box(745, 2705, 1055, 5225))    # vertical
    cell.shapes(l_m1).insert(box(745, 2395, 1985, 2705))    # horizontal to Mn1a pad
    print('  comp_outp: M1 L-route Mn1a.G ↔ Mp1a.G')

    # comp_outn: Mn2a.G(8.64-9.14) ↔ Mp2a.G(8.95-9.45)
    cell.shapes(l_poly).insert(box(8640, 2360, 9140, 2860))  # Mn2a.G ext above
    cell.shapes(l_poly).insert(box(8950, 5130, 9450, 5630))  # Mp2a.G ext below
    add_gate_contact(8890, 2550)  # Mn2a.G
    add_gate_contact(9200, 5380)  # Mp2a.G
    cell.shapes(l_m1).insert(box(8735, 2705, 9355, 5225))    # vertical (covers both X)
    cell.shapes(l_m1).insert(box(8735, 2395, 9355, 2705))    # merge with Mn2a pad
    print('  comp_outn: M1 block Mn2a.G ↔ Mp2a.G')

    # ─── Write ───
    out_path = os.path.join(OUT_DIR, 'hbridge.gds')
    out.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')
    m1r = pya.Region(cell.begin_shapes_rec(out.find_layer(*M1)))
    m2r = pya.Region(cell.begin_shapes_rec(out.find_layer(*M2)))
    print(f'  Quick DRC: M1.b={m1r.space_check(180).count()}, M1.a={m1r.width_check(160).count()}')
    print(f'  Quick DRC: M2.b={m2r.space_check(210).count()}, M2.a={m2r.width_check(210).count()}')
    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
