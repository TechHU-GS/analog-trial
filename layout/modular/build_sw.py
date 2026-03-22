#!/usr/bin/env python3
"""Build Current SW module with routing.

Circuit (3 transmission gates for current source selection):
    TG1: SW1n+SW1p — src1 ↔ exc_out, gates sel0/sel0b
    TG2: SW2n+SW2p — src2 ↔ exc_out, gates sel1/sel1b
    TG3: SW3n+SW3p — src3 ↔ exc_out, gates sel2/sel2b

Net connections:
    exc_out: all 6 sources (external → MS1.D, MS3.D)
    src1/src2/src3: TG drain pairs (external → PM_cas1/2/3)
    sel0/0b,sel1/1b,sel2/2b: individual gate signals (6 external nets)

M1 strips (re-origined from x=137130, y=85500):
    TG1: [0](0.07) [1](0.95) short | [2/3](2.26) [4/5](3.14) tall | NWell 1.88-3.68
    Junction: [6](4.45) [7](5.33) short (SW2n)
    TG2: [8/9](9.94) [10/11](10.82) tall | NWell 9.56-11.36
    Junction: [12](12.13) [13](13.01) short (SW3n)
    TG3: [14/15](14.32) [16/17](15.20) tall | NWell 13.94-15.37

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_sw.py
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


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building Current SW ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # ─── Step 1: Extract PCells ───
    print('\n--- Step 1: Extract PCells ---')
    search = pya.Box(136500, 85000, 152600, 90000)
    origin_x = 137130
    origin_y = 85500

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('current_sw')

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

    # ─── Step 2: Add ties ───
    print('\n--- Step 2: Add ties ---')

    # ptap for NMOS (outside NWell)
    for ptap_x in [500, 4500, 7500, 12000]:
        cell.shapes(l_activ).insert(box(ptap_x, -700, ptap_x+500, -200))
        cell.shapes(l_m1).insert(box(ptap_x, -700, ptap_x+500, -200))
        cell.shapes(l_psd).insert(box(ptap_x-100, -800, ptap_x+600, -100))
        cell.shapes(l_cont).insert(box(ptap_x+170, -530, ptap_x+330, -370))

    # ntap inside NWell, 400nm above PMOS Active top (4310)
    l_nw = out.layer(31, 0)
    cell.shapes(l_nw).insert(box(1880, 0, 15500, 5300))
    for ntap_x in [2200, 9900, 14300]:
        cell.shapes(l_activ).insert(box(ntap_x, 4700, ntap_x+500, 5200))
        cell.shapes(l_m1).insert(box(ntap_x, 4700, ntap_x+500, 5200))
        cell.shapes(l_cont).insert(box(ntap_x+170, 4870, ntap_x+330, 5030))

    print('  ptap: 4 positions at y=-0.70; ntap: 3 positions at y=4.70')

    # ─── Step 3: M2 routing ───
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

    # 4 M2 routes at y=335, 855, 1375, 1895 (520nm pitch, M2.b=210nm ✅)
    y_excout = 335
    y_src1 = 855
    y_src2 = 1375
    y_src3 = 1895

    # exc_out: [0](70-230), [2/3](2260-2420), [6](4450-4610), [8/9](9940-10100), [12](12130-12290), [14/15](14320-14480)
    pads = []
    for xl, xr in [(70,230), (2260,2420), (4450,4610), (9940,10100), (12130,12290), (14320,14480)]:
        pads.append(add_via1(xl, xr, y_excout))
    m2_x1 = min(p[0] for p in pads)
    m2_x2 = max(p[2] for p in pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_excout-155, m2_x2, y_excout+155))
    print(f'  exc_out M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_excout/1000:.3f}')

    # src1: [1](950-1110), [4/5](3140-3300)
    pads = []
    for xl, xr in [(950,1110), (3140,3300)]:
        pads.append(add_via1(xl, xr, y_src1))
    m2_x1 = min(p[0] for p in pads)
    m2_x2 = max(p[2] for p in pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_src1-155, m2_x2, y_src1+155))
    print(f'  src1 M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_src1/1000:.3f}')

    # src2: [7](5330-5490), [10/11](10820-10980)
    pads = []
    for xl, xr in [(5330,5490), (10820,10980)]:
        pads.append(add_via1(xl, xr, y_src2))
    m2_x1 = min(p[0] for p in pads)
    m2_x2 = max(p[2] for p in pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_src2-155, m2_x2, y_src2+155))
    print(f'  src2 M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_src2/1000:.3f}')

    # src3: [13](13010-13170), [16/17](15200-15360)
    pads = []
    for xl, xr in [(13010,13170), (15200,15360)]:
        pads.append(add_via1(xl, xr, y_src3))
    m2_x1 = min(p[0] for p in pads)
    m2_x2 = max(p[2] for p in pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_src3-155, m2_x2, y_src3+155))
    print(f'  src3 M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_src3/1000:.3f}')

    # ─── Write output ───
    out_path = os.path.join(OUT_DIR, 'sw.gds')
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
