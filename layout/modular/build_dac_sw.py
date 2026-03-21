#!/usr/bin/env python3
"""Build DAC switch module with complete routing including gate connections.

Circuit (2 transmission gates):
    TG1: Mdac_tg1n (NMOS) + Mdac_tg1p (PMOS) — dac_hi ↔ dac_out
    TG2: Mdac_tg2n (NMOS) + Mdac_tg2p (PMOS) — dac_lo ↔ dac_out

Net connections:
    dac_out: all 4 sources (external → Rdac)
    dac_hi:  Mdac_tg1n.D + Mdac_tg1p.D (internal)
    dac_lo:  Mdac_tg2n.D + Mdac_tg2p.D (internal)
    lat_q:   Mdac_tg1n.G + Mdac_tg2p.G (internal gate pair)
    lat_qb:  Mdac_tg1p.G + Mdac_tg2n.G (internal gate pair)

Gate positions (re-origined):
    gate0: x=0.34-0.84 (short, lat_q = Mdac_tg1n.G)
    gate1/2: x=2.53-3.03 (tall, lat_qb = Mdac_tg1p.G)
    gate3: x=4.72-5.22 (short, lat_qb = Mdac_tg2n.G)
    gate4/5: x=6.91-7.41 (tall, lat_q = Mdac_tg2p.G)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_dac_sw.py
"""

import klayout.db as pya
import os
import json

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
    print('=== Building DAC Switch ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # ─── Step 1: Extract PCells ───
    print('\n--- Step 1: Extract PCells ---')
    search = pya.Box(41500, 88500, 50500, 94000)
    origin_x = 41970
    origin_y = 89000

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('dac_sw')

    shapes_total = 0
    for li in src.layer_indices():
        info = src.get_info(li)
        tli = out.layer(info.layer, info.datatype)
        region = pya.Region(src_top.begin_shapes_rec(li))
        clipped = region & pya.Region(search)
        for poly in clipped.each():
            cell.shapes(tli).insert(poly.moved(-origin_x, -origin_y))
            shapes_total += 1

    bb = cell.bbox()
    print(f'  Extracted {shapes_total} shapes, {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    l_activ = out.layer(*ACTIV)
    l_m1 = out.layer(*M1)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)
    l_poly = out.layer(*GATPOLY)

    # ─── Step 2: Add ties (positions avoid gate routing) ───
    print('\n--- Step 2: Add ties ---')

    # ptap: in gap between TGs (x≈3.8, away from gates at 0.59,2.78,4.97,7.16)
    ptap_x = 3800
    cell.shapes(l_activ).insert(box(ptap_x, -700, ptap_x+500, -200))
    cell.shapes(l_m1).insert(box(ptap_x, -700, ptap_x+500, -200))
    cell.shapes(l_psd).insert(box(ptap_x-100, -800, ptap_x+600, -100))
    cell.shapes(l_cont).insert(box(ptap_x+170, -530, ptap_x+330, -370))

    # ntap: inside NWell, away from gate centers
    # NWell1: 1880-3680 → ntap at x=1.90 (left, away from gate1/2 at 2.78)
    # NWell2: 6260-8060 → ntap at x=7.60 (right side, away from gate4/5 at 7.16)
    for ntap_x in [1900, 7600]:
        cell.shapes(l_activ).insert(box(ntap_x, 4300, ntap_x+500, 4800))
        cell.shapes(l_m1).insert(box(ntap_x, 4300, ntap_x+500, 4800))
        cell.shapes(l_cont).insert(box(ntap_x+170, 4470, ntap_x+330, 4630))

    print('  ptap: x=3.8; ntap: x=1.9,7.6')

    # ─── Step 3: M2 routing (S/D) ───
    print('\n--- Step 3: M2 routing ---')

    def add_via1(strip_xl, strip_xr, via_y):
        cx = (strip_xl + strip_xr) // 2
        hw = 155
        cell.shapes(l_m1).insert(box(cx-hw, via_y-hw, cx+hw, via_y+hw))
        v = 95
        cell.shapes(l_via1).insert(box(cx-v, via_y-v, cx+v, via_y+v))
        m2x, m2y = 245, 155
        cell.shapes(l_m2).insert(box(cx-m2x, via_y-m2y, cx+m2x, via_y+m2y))
        return (cx-m2x, via_y-m2y, cx+m2x, via_y+m2y)

    y_dacout = 500
    y_dachi = 1200
    y_daclo = 1900

    # dac_out
    pads = []
    for xl, xr in [(70,230), (2260,2420), (4450,4610), (6640,6800)]:
        pads.append(add_via1(xl, xr, y_dacout))
    cell.shapes(l_m2).insert(box(min(p[0] for p in pads), y_dacout-155,
                                  max(p[2] for p in pads), y_dacout+155))

    # dac_hi
    pads = []
    for xl, xr in [(950,1110), (3140,3300)]:
        pads.append(add_via1(xl, xr, y_dachi))
    cell.shapes(l_m2).insert(box(min(p[0] for p in pads), y_dachi-155,
                                  max(p[2] for p in pads), y_dachi+155))

    # dac_lo
    pads = []
    for xl, xr in [(5330,5490), (7520,7680)]:
        pads.append(add_via1(xl, xr, y_daclo))
    cell.shapes(l_m2).insert(box(min(p[0] for p in pads), y_daclo-155,
                                  max(p[2] for p in pads), y_daclo+155))

    print('  dac_out/hi/lo M2 routed')

    # ─── Step 4: Gate routing (lat_q, lat_qb via M1) ───
    print('\n--- Step 4: Gate routing ---')

    # Same pattern as Chopper:
    # gate0(0.34-0.84, short, lat_q) ↔ gate4/5(6.91-7.41, tall, lat_q)
    # gate1/2(2.53-3.03, tall, lat_qb) ↔ gate3(4.72-5.22, short, lat_qb)

    # Poly extensions
    cell.shapes(l_poly).insert(box(340, 2360, 840, 2860))      # gate0 above
    cell.shapes(l_poly).insert(box(2530, 4490, 3030, 4990))    # gate1/2 above
    cell.shapes(l_poly).insert(box(4720, 2360, 5220, 2860))    # gate3 above
    cell.shapes(l_poly).insert(box(6910, 4490, 7410, 5600))    # gate4/5 above (longer)

    # Gate contacts + M1 pads
    def add_gate_contact(poly_cx, cont_cy):
        cell.shapes(l_cont).insert(box(poly_cx-80, cont_cy-80, poly_cx+80, cont_cy+80))
        cell.shapes(l_m1).insert(box(poly_cx-155, cont_cy-155, poly_cx+155, cont_cy+155))

    add_gate_contact(590, 2550)    # gate0 (lat_q)
    add_gate_contact(7160, 5300)   # gate4/5 (lat_q)
    add_gate_contact(2780, 4800)   # gate1/2 (lat_qb)
    add_gate_contact(4890, 2550)   # gate3 (lat_qb) — shifted left to avoid dac_lo Via1

    # lat_qb M1: gate1/2 (x=2780, y=4800) ↔ gate3 (x=4890, y=2550)
    cell.shapes(l_m1).insert(box(2625, 4645, 5045, 4955))   # horizontal at y=4.80
    cell.shapes(l_m1).insert(box(4735, 2705, 5045, 4645))   # vertical down to gate3

    # lat_q M1: gate0 (x=590, y=2550) ↔ gate4/5 (x=7160, y=5300)
    cell.shapes(l_m1).insert(box(435, 2705, 745, 5145))     # vertical up from gate0
    cell.shapes(l_m1).insert(box(435, 5145, 7315, 5455))    # horizontal at y=5.30

    print('  lat_q: M1 y=5.30, lat_qb: M1 y=4.80')

    # ─── Write output ───
    out_path = os.path.join(OUT_DIR, 'dac_sw.gds')
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
