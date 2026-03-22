#!/usr/bin/env python3
"""Build OTA module with routing.

Circuit (5T OTA + bias):
    Top (y≈12): Mp_load_p (diode, mid_p), Mp_load_n (ota_out)
    Mid (y≈7):  Min_p (diff+, mid_p/tail), Min_n (diff-, ota_out/tail)
    Bot (y≈0):  M_bias_mir, Mbias_d (diode, bias_n), Mtail (tail/bias_n)

Internal nets:
    mid_p: Mp_load_p.D/G + Mp_load_n.G + Min_p.D (cross-band)
    ota_out: Mp_load_n.D + Min_n.D (cross-band)
    tail: Min_p.S + Min_n.S + Mtail.D (cross-band)
    bias_n: Mbias_d.D/G + Mtail.G + M_bias_mir.D (bottom band)

Strip assignments (S/D alternating for multi-finger):
    Min_p (6 strips): D[4.75] S[7.13] D[9.51] S[11.89] D[14.27] S[15.54]
    Min_n (5 strips): S[15.54] D[17.92] S[20.30] D[22.68] S[25.06]
    Mp_load_p (3 strips): S[9.58] D[13.96] S[15.88]
    Mp_load_n (2 strips): S[15.88] D[20.26]

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_ota.py
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
NWELL = (31, 0)


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building OTA ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # ─── Step 1: Extract PCells ───
    print('\n--- Step 1: Extract PCells ---')

    # Right edge: include our M1 strip (right=53840) but exclude neighbor poly (left=53950)
    search = pya.Box(30500, 69500, 53940, 86500)
    origin_x = 31000   # M_bias_mir x
    origin_y = 70500   # bottom band y

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('ota')

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

    l_m1 = out.layer(*M1)
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)
    l_activ = out.layer(*ACTIV)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_poly = out.layer(5, 0)  # GatPoly

    # ─── Step 2: Add ties ───
    print('\n--- Step 2: Add ties ---')

    # ptap for NMOS (bottom and mid bands)
    for ptap_x, ptap_y in [(1000, -700), (7000, -700), (13000, -700),
                            (1000, 5200), (8000, 5200), (18000, 5200)]:
        cell.shapes(l_activ).insert(box(ptap_x, ptap_y, ptap_x+500, ptap_y+500))
        cell.shapes(l_m1).insert(box(ptap_x, ptap_y, ptap_x+500, ptap_y+500))
        cell.shapes(l_psd).insert(box(ptap_x-100, ptap_y-100, ptap_x+600, ptap_y+600))
        cell.shapes(l_cont).insert(box(ptap_x+170, ptap_y+170, ptap_x+330, ptap_y+330))

    # ntap for PMOS (in NWell near top band)
    # NWell PCell: (9.20-14.50, 11.50-16.00) and (15.50-20.80, 11.50-16.00)
    # Merge NWell + extend to cover ntap
    l_nw = out.layer(*NWELL)
    cell.shapes(l_nw).insert(box(9200, 11500, 20800, 17200))
    # Place ntap well above PCell poly top (y=15990), gap ≥ 400nm
    # ntap at y=16500-17000 (inside extended NWell)
    for ntap_x in [10000, 17000]:
        cell.shapes(l_activ).insert(box(ntap_x, 16600, ntap_x + 500, 17100))
        cell.shapes(l_m1).insert(box(ntap_x, 16600, ntap_x + 500, 17100))
        cell.shapes(l_cont).insert(box(ntap_x + 170, 16770, ntap_x + 330, 16930))

    # Also ntap for M_bias_mir NWell (0.00-3.30, 0.00-1.12)
    cell.shapes(l_activ).insert(box(1000, 1300, 1500, 1800))
    cell.shapes(l_m1).insert(box(1000, 1300, 1500, 1800))
    cell.shapes(l_cont).insert(box(1170, 1470, 1330, 1630))

    print('  ties placed')

    # ─── Step 3: M2 S/D bus straps for diff pair ───
    print('\n--- Step 3: M2 bus straps ---')

    def add_via1(strip_xl, strip_xr, via_y):
        cx = (strip_xl + strip_xr) // 2
        hw = 155
        cell.shapes(l_m1).insert(box(cx-hw, via_y-hw, cx+hw, via_y+hw))
        v = 95
        cell.shapes(l_via1).insert(box(cx-v, via_y-v, cx+v, via_y+v))
        m2x, m2y = 245, 155
        cell.shapes(l_m2).insert(box(cx-m2x, via_y-m2y, cx+m2x, via_y+m2y))
        return (cx-m2x, via_y-m2y, cx+m2x, via_y+m2y)

    # Diff pair strips (y=6680-9180, 2.5um range):
    # Min_p: D[4750] S[7130] D[9510] S[11890] D[14270] S[15540]
    # Min_n: S[15540] D[17920] S[20300] D[22680] S[25060]
    #
    # M2 bus Y levels (within diff pair strip range):
    y_tail = 7000      # tail (source bus)
    y_midp = 7600      # mid_p (Min_p drain bus)
    y_otaout = 8200     # ota_out (Min_n drain bus)

    # tail bus: Min_p.S [7130,11890,15540] + Min_n.S [15540,20300,25060]
    tail_pads = []
    for xl, xr in [(7130,7290), (11890,12050), (15540,15700),
                    (20300,20460)]:
        tail_pads.append(add_via1(xl, xr, y_tail))
    m2_x1 = min(p[0] for p in tail_pads)
    m2_x2 = max(p[2] for p in tail_pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_tail-155, m2_x2, y_tail+155))
    print(f'  tail M2 bus: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_tail/1000:.1f}')

    # mid_p bus: Min_p.D [4750,9510,14270]
    midp_pads = []
    for xl, xr in [(4750,4910), (9510,9670), (14270,14430)]:
        midp_pads.append(add_via1(xl, xr, y_midp))
    m2_x1 = min(p[0] for p in midp_pads)
    m2_x2 = max(p[2] for p in midp_pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_midp-155, m2_x2, y_midp+155))
    print(f'  mid_p M2 bus: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_midp/1000:.1f}')

    # ota_out bus: Min_n.D [17920,22680]
    otaout_pads = []
    for xl, xr in [(17920,18080), (22680,22840)]:
        otaout_pads.append(add_via1(xl, xr, y_otaout))
    m2_x1 = min(p[0] for p in otaout_pads)
    m2_x2 = max(p[2] for p in otaout_pads)
    cell.shapes(l_m2).insert(box(m2_x1, y_otaout-155, m2_x2, y_otaout+155))
    print(f'  ota_out M2 bus: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_otaout/1000:.1f}')

    # ─── Step 4: M2 vertical connections (cross-band) ───
    print('\n--- Step 4: M2 vertical connections ---')

    # tail → Mtail.D: Via1 on Mtail.D strip [14920-15080] at y≈3800
    add_via1(14920, 15080, 3800)
    # M2 vertical bar from Mtail.D (y=3800) up to tail bus (y=7000)
    cell.shapes(l_m2).insert(box(14850, 3645, 15150, 7155))
    print('  tail vertical: Mtail.D → diff pair S bus')

    # mid_p → Mp_load_p.D: Via1 on [13960-14120] at y≈12200
    add_via1(13960, 14120, 12200)
    # M2 vertical bar from mid_p bus (y=7600) up to Mp_load_p.D (y=12200)
    cell.shapes(l_m2).insert(box(13890, 7445, 14190, 12355))
    print('  mid_p vertical: Min_p.D bus → Mp_load_p.D')

    # ota_out → Mp_load_n.D: Via1 on [20260-20420] at y≈12200
    add_via1(20260, 20420, 12200)
    # M2 vertical bar from ota_out bus (y=8200) up to Mp_load_n.D (y=12200)
    cell.shapes(l_m2).insert(box(20190, 8045, 20490, 12355))
    print('  ota_out vertical: Min_n.D bus → Mp_load_n.D')

    # ─── Step 5: Gate routing (bias_n + mid_p gates) ───
    print('\n--- Step 5: Gate routing ---')

    # === bias_n: Mbias_d.D/G (diode) + Mtail.G + M_bias_mir.D ===
    # Bottom band, all at y≈0-4.

    # Mbias_d gate poly at (5130-9130, 0-4360). Extend above to 4860.
    # Widen poly ext right edge to ensure Contact enclosure ≥ 70nm
    cell.shapes(l_poly).insert(box(5130, 4360, 9200, 4860))
    # Gate contact near D strip [9240]: at x=9000, y=4600
    cell.shapes(l_cont).insert(box(8920, 4520, 9080, 4680))
    cell.shapes(l_m1).insert(box(8845, 4445, 9155, 4755))

    # M1 bridge: Mbias_d.D strip [9240-9400] top → gate contact pad
    # Overlap strip and pad in one M1 rect
    cell.shapes(l_m1).insert(box(8845, 4180, 9400, 4755))

    # Mtail gate poly at (10810-14810, 0-4360). Extend above to 4860.
    cell.shapes(l_poly).insert(box(10810, 4360, 14810, 4860))
    # Gate contact at x=11500, y=4600
    cell.shapes(l_cont).insert(box(11420, 4520, 11580, 4680))
    cell.shapes(l_m1).insert(box(11345, 4445, 11655, 4755))

    # bias_n M1 bus: horizontal bar connecting Mbias_d diode to Mtail gate
    cell.shapes(l_m1).insert(box(8845, 4445, 11655, 4755))

    # M_bias_mir.D strip [2760-2920, y=0.31-0.81]: vertical M1 up to bias_n bus
    cell.shapes(l_m1).insert(box(2760, 810, 2920, 4445))
    # Horizontal extension from M_bias_mir.D to Mbias_d gate pad
    cell.shapes(l_m1).insert(box(2760, 4445, 8845, 4755))

    print('  bias_n: M_bias_mir.D → M1 vertical+horizontal → Mbias_d diode → Mtail.G')

    # === mid_p gates: Mp_load_p.G (diode) + Mp_load_n.G ===
    # Top band, y≈12-16.

    # Mp_load_p gate poly at (9850-13850, 11630-15990). Extend above to 16490.
    cell.shapes(l_poly).insert(box(9850, 15990, 13850, 16490))
    # Gate contact at x=13500, y=16200 (near D strip [13960])
    cell.shapes(l_cont).insert(box(13420, 16120, 13580, 16280))
    # M1 bridge connecting D strip [13960] top to gate contact (diode)
    cell.shapes(l_m1).insert(box(13345, 15810, 14120, 16355))

    # Mp_load_n gate poly at (16150-20150, 11630-15990). Extend above to 16490.
    cell.shapes(l_poly).insert(box(16150, 15990, 20150, 16490))
    # Gate contact at x=16500, y=16200
    cell.shapes(l_cont).insert(box(16420, 16120, 16580, 16280))
    cell.shapes(l_m1).insert(box(16345, 16045, 16655, 16355))

    # Via1 on Mp_load_n gate pad for M2 connection to mid_p
    cell.shapes(l_via1).insert(box(16405, 16105, 16595, 16295))
    cell.shapes(l_m2).insert(box(16255, 16045, 16745, 16355))

    # Extend mid_p M2 vertical bar up to gate level and add horizontal
    cell.shapes(l_m2).insert(box(13890, 12355, 14190, 16355))   # extend vertical
    cell.shapes(l_m2).insert(box(14190, 16045, 16255, 16355))   # horizontal to Mp_load_n gate

    print('  mid_p: Mp_load_p diode (M1) + Mp_load_n.G via M2')

    # ─── Write output ───
    out_path = os.path.join(OUT_DIR, 'ota.gds')
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
