#!/usr/bin/env python3
"""Build Chopper module with complete routing.

Circuit (2 transmission gates):
    TG1: Mchop1n (NMOS) + Mchop1p (PMOS) — sens_p ↔ chop_out
    TG2: Mchop2n (NMOS) + Mchop2p (PMOS) — sens_n ↔ chop_out

Net connections:
    chop_out: all 4 sources (external → Rin)
    sens_p:   Mchop1n.D + Mchop1p.D (internal)
    sens_n:   Mchop2n.D + Mchop2p.D (internal)
    f_exc:    Mchop1n.G + Mchop2p.G (external clock)
    f_exc_b:  Mchop1p.G + Mchop2n.G (external clock complement)

PCell layout (from bare GDS):
    M1 strips left→right:
      41.39,42.27 (2um,NMOS-only) → 43.58,44.46 (4um,shared) → 47.07,47.95 (2um,shared) → 49.26,50.14 (4um,shared)
    NWell: (43.20-45.00) and (48.88-50.68)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_chopper.py
"""

import klayout.db as pya
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Layer definitions
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
M1 = (8, 0)
M2 = (10, 0)
PSD = (14, 0)
VIA1 = (19, 0)
NWELL = (31, 0)
SUBSTRATE = (40, 0)

# DRC values (nm)
M1_MIN_S = 180
M1_MIN_W = 160
M2_MIN_W = 210
VIA1_SIZE = 190


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building Chopper ===')

    # ─── Step 1: Extract PCells from bare GDS ───
    print('\n--- Step 1: Extract PCells ---')

    with open(os.path.join(LAYOUT_DIR, 'placement.json')) as f:
        placement = json.load(f)

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # Full chopper search area (covers all 4 devices + NWell margins)
    # Devices span x=41.32-50.37, y=63.50-68.12
    # Add margins: left 500nm, right 500nm, bottom 500nm, top 500nm
    search_x1 = 40800
    search_y1 = 63000
    search_x2 = 51200
    search_y2 = 68700
    search = pya.Box(search_x1, search_y1, search_x2, search_y2)

    # Origin shift: place at (0, 0)
    # Use leftmost Activ as reference
    origin_x = 41320  # Mchop1n Activ left edge
    origin_y = 63500  # placement y

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('chopper')

    shapes_total = 0
    for li in src.layer_indices():
        info = src.get_info(li)
        tli = out.layer(info.layer, info.datatype)

        region = pya.Region(src_top.begin_shapes_rec(li))
        clipped = region & pya.Region(search)

        for poly in clipped.each():
            shifted = poly.moved(-origin_x, -origin_y)
            cell.shapes(tli).insert(shifted)
            shapes_total += 1

    bb = cell.bbox()
    print(f'  Extracted {shapes_total} shapes')
    print(f'  Size: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    # ─── Step 2: Add ties (positions chosen to avoid gate routing conflicts) ───
    print('\n--- Step 2: Add ties ---')

    l_activ = out.layer(*ACTIV)
    l_m1 = out.layer(*M1)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_nwell = out.layer(*NWELL)
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)
    l_poly = out.layer(*GATPOLY)

    # Gates at: x=0.59(g0), 2.78(g1), 6.27(g3), 8.46(g4)
    # Ties must avoid gate X positions for M1.b clearance
    ptap_size = 500

    # ptap: in gap between TG1 and TG2 (x≈4.2, away from all gates)
    ptap_x = 4200
    ptap_y = -700
    cell.shapes(l_activ).insert(box(ptap_x, ptap_y, ptap_x + ptap_size, ptap_y + ptap_size))
    cell.shapes(l_m1).insert(box(ptap_x, ptap_y, ptap_x + ptap_size, ptap_y + ptap_size))
    cell.shapes(l_psd).insert(box(ptap_x - 100, ptap_y - 100, ptap_x + ptap_size + 100, ptap_y + ptap_size + 100))
    cell.shapes(l_cont).insert(box(ptap_x + 170, ptap_y + 170, ptap_x + 330, ptap_y + 330))

    # ntap: inside NWell, 400nm above PMOS Active top (4310)
    # NWell extended to cover ntap
    l_nw = out.layer(31, 0)
    cell.shapes(l_nw).insert(box(1880, 0, 9360, 5300))
    ntap_y = 4700
    for ntap_x in [1900, 8900]:
        cell.shapes(l_activ).insert(box(ntap_x, ntap_y, ntap_x + ptap_size, ntap_y + ptap_size))
        cell.shapes(l_m1).insert(box(ntap_x, ntap_y, ntap_x + ptap_size, ntap_y + ptap_size))
        cell.shapes(l_cont).insert(box(ntap_x + 170, ntap_y + 170, ntap_x + 330, ntap_y + 330))

    print('  ptap: x=4.2 y=-0.70; ntap: x=1.9,8.9 y=4.70')

    # ─── Step 3: M2 routing (TG NMOS↔PMOS bridges + chop_out bus) ───
    print('\n--- Step 3: M2 routing ---')

    # Strip positions (re-origined, center X):
    # NMOS strips (short, y=0.18-2.18):
    #   [0] x=0.15  (Mchop1n)
    #   [1] x=1.03  (Mchop1n)
    #   [7] x=5.83  (junction Mchop1p/Mchop2n)
    #   [8] x=6.71  (junction Mchop1p/Mchop2n)
    # PMOS strips (tall, y=0.31-4.31):
    #   [3/4] x=2.34  (TG1 shared)
    #   [5/6] x=3.22  (TG1 shared)
    #   [10/11] x=8.02 (TG2 shared)
    #   [12/13] x=8.90 (TG2 shared)
    #
    # Net assignment (terminal A=left of gate, B=right):
    #   chop_out: [0](0.07), [3/4](2.26), [7](5.75), [10/11](7.94)
    #   sens_p:   [1](0.95), [5/6](3.14)
    #   sens_n:   [8](6.63), [12/13](8.82)
    #
    # Gates: gate0(0.34-0.84)=f_exc, gate1/2(2.53-3.03)=f_exc_b,
    #         gate3(6.02-6.52)=f_exc_b, gate4/5(8.21-8.71)=f_exc

    # Helper: add Via1 + M1 pad + M2 pad at a strip location
    def add_via1(strip_xl, strip_xr, via_y_center):
        """Add Via1 with M1+M2 pads on a strip. Returns M2 pad bbox."""
        cx = (strip_xl + strip_xr) // 2
        # M1 pad: 310x310nm centered on strip
        m1_hw = 155
        m1_pad = box(cx - m1_hw, via_y_center - m1_hw, cx + m1_hw, via_y_center + m1_hw)
        cell.shapes(l_m1).insert(m1_pad)
        # Via1: 190x190nm centered
        v_hw = 95
        cell.shapes(l_via1).insert(box(cx - v_hw, via_y_center - v_hw,
                                       cx + v_hw, via_y_center + v_hw))
        # M2 pad: 490x310nm centered
        m2_hw_x = 245
        m2_hw_y = 155
        m2_pad = box(cx - m2_hw_x, via_y_center - m2_hw_y,
                     cx + m2_hw_x, via_y_center + m2_hw_y)
        cell.shapes(l_m2).insert(m2_pad)
        return (cx - m2_hw_x, via_y_center - m2_hw_y,
                cx + m2_hw_x, via_y_center + m2_hw_y)

    # M2 route Y centers (need M2.b=210nm spacing between routes)
    # Route 1: chop_out at y=500nm (center)
    # Route 2: sens_p at y=1200nm
    # Route 3: sens_n at y=1900nm
    y_chop = 500
    y_sensp = 1200
    y_sensn = 1900

    # ── chop_out M2 bus ──
    # Via1 on strips: [0](70-230), [3/4](2260-2420), [7](5750-5910), [10/11](7940-8100)
    pads_chop = []
    for xl, xr in [(70, 230), (2260, 2420), (5750, 5910), (7940, 8100)]:
        p = add_via1(xl, xr, y_chop)
        pads_chop.append(p)

    # M2 horizontal bar connecting all chop_out Via1s
    m2_x1 = min(p[0] for p in pads_chop)
    m2_x2 = max(p[2] for p in pads_chop)
    cell.shapes(l_m2).insert(box(m2_x1, y_chop - 155, m2_x2, y_chop + 155))
    print(f'  chop_out M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_chop/1000:.2f}')

    # ── sens_p M2 ──
    # Via1 on strips: [1](950-1110), [5/6](3140-3300)
    pads_sp = []
    for xl, xr in [(950, 1110), (3140, 3300)]:
        p = add_via1(xl, xr, y_sensp)
        pads_sp.append(p)

    m2_x1 = min(p[0] for p in pads_sp)
    m2_x2 = max(p[2] for p in pads_sp)
    cell.shapes(l_m2).insert(box(m2_x1, y_sensp - 155, m2_x2, y_sensp + 155))
    print(f'  sens_p M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_sensp/1000:.2f}')

    # ── sens_n M2 ──
    # Via1 on strips: [8](6630-6790), [12/13](8820-8980)
    pads_sn = []
    for xl, xr in [(6630, 6790), (8820, 8980)]:
        p = add_via1(xl, xr, y_sensn)
        pads_sn.append(p)

    m2_x1 = min(p[0] for p in pads_sn)
    m2_x2 = max(p[2] for p in pads_sn)
    cell.shapes(l_m2).insert(box(m2_x1, y_sensn - 155, m2_x2, y_sensn + 155))
    print(f'  sens_n M2: x={m2_x1/1000:.2f}-{m2_x2/1000:.2f}, y={y_sensn/1000:.2f}')

    # ─── Step 4: Gate routing (f_exc, f_exc_b) ───
    print('\n--- Step 4: Gate routing ---')

    # Gate positions:
    #   gate0: x=340-840, y=0-2360 (short, f_exc = Mchop1n.G)
    #   gate1/2: x=2530-3030, y=130-4490 (tall, f_exc_b = Mchop1p.G)
    #   gate3: x=6020-6520, y=0-2360 (short, f_exc_b = Mchop2n.G)
    #   gate4/5: x=8210-8710, y=130-4490 (tall, f_exc = Mchop2p.G)
    #
    # Strategy: M1-only gate routing above all S/D strips
    #   - Short gates: extend poly above to y=2860, contact at y≈2550
    #   - Tall gates: extend poly above to y=5600, contact at y≈4800 (f_exc_b) or 5300 (f_exc)
    #   - f_exc_b M1 horizontal at y≈4800 (4645-4955)
    #   - f_exc M1 horizontal at y≈5300 (5145-5455)
    #   - Verticals connect short gate contacts up to horizontal bars

    # Poly extensions
    cell.shapes(l_poly).insert(box(340, 2360, 840, 2860))      # gate0 above
    cell.shapes(l_poly).insert(box(2530, 4490, 3030, 4990))    # gate1/2 above
    cell.shapes(l_poly).insert(box(6020, 2360, 6520, 2860))    # gate3 above
    cell.shapes(l_poly).insert(box(8210, 4490, 8710, 5600))    # gate4/5 above (longer for f_exc)

    # Gate contacts (160x160nm) + M1 pads (310x310nm)
    def add_gate_contact(poly_cx, cont_cy):
        """Add contact + M1 pad on gate poly. Returns M1 pad bbox."""
        cx, cy = poly_cx, cont_cy
        cell.shapes(l_cont).insert(box(cx - 80, cy - 80, cx + 80, cy + 80))
        cell.shapes(l_m1).insert(box(cx - 155, cy - 155, cx + 155, cy + 155))
        return (cx - 155, cy - 155, cx + 155, cy + 155)

    # gate0 (f_exc): contact above short poly, at y=2550
    g0_pad = add_gate_contact(590, 2550)   # poly center x=590
    # gate4/5 (f_exc): contact above tall poly extension, at y=5300
    g4_pad = add_gate_contact(8460, 5300)  # poly center x=8460

    # gate1/2 (f_exc_b): contact above tall poly, at y=4800
    g1_pad = add_gate_contact(2780, 4800)  # poly center x=2780
    # gate3 (f_exc_b): contact above short poly, at y=2550
    g3_pad = add_gate_contact(6190, 2550)  # poly center x=6190 (shifted left to avoid sens_n Via1 M1)

    # f_exc_b M1 route: gate1/2 (x=2780, y=4800) ↔ gate3 (x=6190, y=2550)
    # Horizontal bar at y=4800 + vertical down to gate3
    cell.shapes(l_m1).insert(box(2625, 4645, 6345, 4955))   # horizontal
    cell.shapes(l_m1).insert(box(6035, 2705, 6345, 4645))   # vertical down to gate3
    print('  f_exc_b: M1 bar y=4.80 (x=2.63-6.35) + vertical x=6.19')

    # f_exc M1 route: gate0 (x=590, y=2550) ↔ gate4/5 (x=8460, y=5300)
    # Vertical from gate0 up + horizontal bar at y=5300
    cell.shapes(l_m1).insert(box(435, 2705, 745, 5145))     # vertical up from gate0
    cell.shapes(l_m1).insert(box(435, 5145, 8615, 5455))    # horizontal
    print('  f_exc: M1 bar y=5.30 (x=0.44-8.62) + vertical x=0.59')

    # ─── Write output ───
    out_path = os.path.join(OUT_DIR, 'chopper.gds')
    out.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')
    print(f'  Written: {out_path}')

    # Quick DRC
    li_m1 = out.find_layer(*M1)
    m1r = pya.Region(cell.begin_shapes_rec(li_m1))
    m1b = m1r.space_check(M1_MIN_S)
    m1a = m1r.width_check(M1_MIN_W)
    print(f'  Quick DRC: M1.b={m1b.count()}, M1.a={m1a.count()}')

    li_m2 = out.find_layer(*M2)
    if li_m2 is not None:
        m2r = pya.Region(cell.begin_shapes_rec(li_m2))
        m2b = m2r.space_check(210)
        m2a = m2r.width_check(M2_MIN_W)
        print(f'  Quick DRC: M2.b={m2b.count()}, M2.a={m2a.count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
