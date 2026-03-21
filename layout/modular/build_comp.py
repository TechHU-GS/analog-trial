#!/usr/bin/env python3
"""Build COMP (StrongARM comparator) module with routing.

Circuit (5 bands):
    Band 1 (y≈0):  Mc_tail (NMOS tail switch)
    Band 2 (y≈6):  Mc_inp, Mc_inn (NMOS diff pair)
    Band 3 (y≈11): Mc_ln1, Mc_ln2 (NMOS latch)
    Band 4 (y≈16): Mc_lp1, Mc_lp2 (PMOS latch)
    Band 5 (y≈21): Mc_rst_dp/dn/op/on (PMOS reset)

Internal nets:
    c_tail: Mc_tail.D + Mc_inp.S + Mc_inn.S (band 1→2)
    c_di_p: Mc_inp.D + Mc_rst_dp.D + Mc_ln1.S (band 2→3→5)
    c_di_n: Mc_inn.D + Mc_rst_dn.D + Mc_ln2.S (band 2→3→5)
    comp_outp: Mc_ln1.D + Mc_lp1.D + Mc_rst_op.D + cross-coupled gates (band 3→4→5)
    comp_outn: Mc_ln2.D + Mc_lp2.D + Mc_rst_on.D + cross-coupled gates (band 3→4→5)
    comp_clk: Mc_tail.G + Mc_rst_*.G (band 1+5)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_comp.py
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
NWELL = (31, 0)


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building COMP ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # ─── Step 1: Extract PCells ───
    print('\n--- Step 1: Extract PCells ---')

    # Full area: x=41-52, y=97-123 (5 bands)
    search = pya.Box(40500, 96000, 52000, 123000)
    origin_x = 41350   # Mc_rst_dp x (leftmost)
    origin_y = 97000    # Mc_tail y (bottom)

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('comp')

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

    # ─── Step 2: Add ties ───
    print('\n--- Step 2: Add ties ---')

    # ptap for NMOS bands (1, 2, 3)
    for ptap_x, ptap_y in [(2000, -700), (6000, -700),       # below tail
                            (2000, 3500), (6000, 3500),       # between tail and diff
                            (2000, 9000), (6000, 9000)]:      # between diff and latch
        cell.shapes(l_activ).insert(box(ptap_x, ptap_y, ptap_x+500, ptap_y+500))
        cell.shapes(l_m1).insert(box(ptap_x, ptap_y, ptap_x+500, ptap_y+500))
        cell.shapes(l_psd).insert(box(ptap_x-100, ptap_y-100, ptap_x+600, ptap_y+600))
        cell.shapes(l_cont).insert(box(ptap_x+170, ptap_y+170, ptap_x+330, ptap_y+330))

    # ntap for PMOS (bands 4, 5) — inside NWell
    li_nw = out.find_layer(*NWELL)
    if li_nw is not None:
        nw_region = pya.Region(cell.begin_shapes_rec(li_nw))
        print(f'  NWell regions: {nw_region.count()}')
        for poly in nw_region.each():
            b = poly.bbox()
            if b.width() > 1000:
                ntap_x = (b.left + b.right) // 2 - 250
                ntap_y = b.top + 200
                cell.shapes(l_activ).insert(box(ntap_x, ntap_y, ntap_x+500, ntap_y+500))
                cell.shapes(l_m1).insert(box(ntap_x, ntap_y, ntap_x+500, ntap_y+500))
                cell.shapes(l_cont).insert(box(ntap_x+170, ntap_y+170, ntap_x+330, ntap_y+330))

    print('  ties placed')

    # ─── Step 3: c_tail M2 connection ───
    print('\n--- Step 3: c_tail M2 ---')

    def add_via1(strip_xl, strip_xr, via_y):
        cx = (strip_xl + strip_xr) // 2
        hw = 155
        cell.shapes(l_m1).insert(box(cx-hw, via_y-hw, cx+hw, via_y+hw))
        v = 95
        cell.shapes(l_via1).insert(box(cx-v, via_y-v, cx+v, via_y+v))
        m2x, m2y = 245, 155
        cell.shapes(l_m2).insert(box(cx-m2x, via_y-m2y, cx+m2x, via_y+m2y))
        return cx

    # Mc_tail.D strip: [4.57] = (4570,4730), y=0.18-2.18
    # Mc_inp source strips + Mc_inn source strips need to connect to c_tail
    # For multi-finger devices, alternating S/D — source strips are c_tail
    # Mc_inp strips: [2.31,3.19,4.07,5.07,5.95] and Mc_inn: [5.07,5.95,6.83]
    # Shared [5.07,5.95] must be c_tail (only common net)
    # So: Mc_inp: S=[2.31,4.07,5.95?] or S=[3.19,5.07]
    #     If [5.07]=S=c_tail: Mc_inp pattern D-S-D-S-D → S=[3.19,5.07], D=[2.31,4.07,5.95]
    #     Then Mc_inn: [5.07]=S, [5.95]=D, [6.83]=S → S=[5.07,6.83], D=[5.95]
    #     But [5.95] is D=c_di_p for Mc_inp AND D=c_di_n for Mc_inn → conflict!
    #
    # Alternative: [5.07]=D, [5.95]=S for both (but D=c_di_p vs D=c_di_n conflict)
    #
    # The shared strips must be c_tail (source). Looking at the physical structure,
    # maybe [5.07] and [5.95] are in a gap between Mc_inp and Mc_inn with no gate,
    # forming a continuous source (c_tail) region. One shared S region, not two separate strips.
    #
    # Practical approach: connect Mc_tail.D up to the shared source region via M2

    # Via1 on Mc_tail center strip (D=c_tail) at y≈1800
    cx_tail = add_via1(4570, 4730, 1800)

    # Via1 on shared source region at y≈6000 (middle of diff pair strips)
    # Use strip at x≈5.07 (center of shared region)
    cx_src = add_via1(5070, 5230, 6000)

    # M2 vertical bar connecting tail.D to diff source (span both Via1 X positions)
    m2_left = min(cx_tail, cx_src) - 245
    m2_right = max(cx_tail, cx_src) + 245
    cell.shapes(l_m2).insert(box(m2_left, 1645, m2_right, 6155))
    print(f'  c_tail M2 vertical: x={m2_left/1000:.2f}-{m2_right/1000:.2f}, y=1.65-6.16')

    # ─── Step 4: comp_outp/outn vertical M2 ───
    print('\n--- Step 4: comp_out M2 ---')

    # comp_outp connects band 3 (Mc_ln1.D) → band 4 (Mc_lp1.D) → band 5 (Mc_rst_op.D)
    # Mc_ln1 strips: [3.19,4.07,5.07,5.95], Mc_ln2: [5.07,5.95]
    # Mc_ln1.D would be at the outer strip (away from shared region)
    # If shared [5.07,5.95] are source (c_di_p/c_di_n): then outer strips are drain
    # Mc_ln1.D: [3.19] (leftmost, D=comp_outp)
    # Mc_lp1.D: [3.76] (inner strip, D=comp_outp) — Mc_lp1 strips [2.88,3.76,5.38,6.26]
    # Mc_rst_op.D: [6.26] (inner strip)

    # comp_outp: Via1 at Mc_ln1 outer [3190-3350] y≈11700
    cx_outp_ln = add_via1(3190, 3350, 11700)
    # Via1 at Mc_lp1 [3760-3920] y≈16300
    cx_outp_lp = add_via1(3760, 3920, 16300)
    # Via1 at Mc_rst_op [6260-6420] y≈21200
    cx_outp_rst = add_via1(6260, 6420, 21200)

    # M2 vertical connecting ln1.D to lp1.D
    cell.shapes(l_m2).insert(box(cx_outp_ln-150, 11545, cx_outp_ln+150, 13500))
    cell.shapes(l_m2).insert(box(cx_outp_lp-150, 13500, cx_outp_lp+150, 16455))
    # M2 horizontal bridge at y=13500 connecting the two verticals
    x1 = min(cx_outp_ln, cx_outp_lp) - 150
    x2 = max(cx_outp_ln, cx_outp_lp) + 150
    cell.shapes(l_m2).insert(box(x1, 13345, x2, 13655))

    # comp_outp up to rst_op
    cell.shapes(l_m2).insert(box(cx_outp_lp-150, 16145, cx_outp_lp+150, 18500))
    cell.shapes(l_m2).insert(box(cx_outp_rst-150, 18500, cx_outp_rst+150, 21355))
    x1 = min(cx_outp_lp, cx_outp_rst) - 150
    x2 = max(cx_outp_lp, cx_outp_rst) + 150
    cell.shapes(l_m2).insert(box(x1, 18345, x2, 18655))
    print(f'  comp_outp M2 vertical chain')

    # comp_outn: similar but on the right side
    # Mc_ln2.D: shared region... Mc_ln2 has [5.07,5.95], if [5.07]=S then [5.95]=D=comp_outn
    # But [5.95] is shared with Mc_ln1. Let me use the outer strip of Mc_ln2.
    # Actually Mc_ln2 only has 2 strips. If S-G-D: [5.07]=S, [5.95]=D=comp_outn
    cx_outn_ln = add_via1(5950, 6110, 11700)
    # Mc_lp2.D: [6.26] → (6260-6420)
    cx_outn_lp = add_via1(6260, 6420, 16800)
    # Mc_rst_on.D: [8.76] → (8760-8920)
    cx_outn_rst = add_via1(8760, 8920, 21700)

    cell.shapes(l_m2).insert(box(cx_outn_ln-150, 11545, cx_outn_ln+150, 14000))
    cell.shapes(l_m2).insert(box(cx_outn_lp-150, 14000, cx_outn_lp+150, 16955))
    x1 = min(cx_outn_ln, cx_outn_lp) - 150
    x2 = max(cx_outn_ln, cx_outn_lp) + 150
    cell.shapes(l_m2).insert(box(x1, 13845, x2, 14155))

    cell.shapes(l_m2).insert(box(cx_outn_lp-150, 16645, cx_outn_lp+150, 19000))
    cell.shapes(l_m2).insert(box(cx_outn_rst-150, 19000, cx_outn_rst+150, 21855))
    x1 = min(cx_outn_lp, cx_outn_rst) - 150
    x2 = max(cx_outn_lp, cx_outn_rst) + 150
    cell.shapes(l_m2).insert(box(x1, 18845, x2, 19155))
    print(f'  comp_outn M2 vertical chain')

    # ─── Write output ───
    out_path = os.path.join(OUT_DIR, 'comp.gds')
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
