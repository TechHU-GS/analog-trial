#!/usr/bin/env python3
"""Build H-bridge (SR latch) — compact symmetric placement + ties only.

Placement: left-right mirror, NMOS directly under PMOS (Active aligned).
    PMOS: Mp1a  Mp1b  |  Mp2b(flip)  Mp2a(flip)
    NMOS: Mn1a  Mn1b  |  Mn2b(flip)  Mn2a(flip)

Pair2 devices are X-flipped so D/S swap sides for correct stacking.
No routing — placement evaluation only.

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
NWELL = (31, 0)

# PCell geometry (nm)
ACT_W = 1180
ACT_H = 2000
NW_OFS = 310

# Spacing — relaxed for DRC margin
GAP_PAIR = 700      # between devices in same pair
GAP_CENTER = 1000   # between inner devices across pairs
NMOS_PMOS_GAP = 3500  # routing channel between NMOS and PMOS


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


# Source Active origins from placement.json
# PMOS: placement x/y is NWell corner, Active = +310
ORIG = {
    'Mn1a': (40940, 126000), 'Mn1b': (42820, 126000),
    'Mn2a': (48000, 126000), 'Mn2b': (49880, 126000),
    'Mp1a': (39700 + NW_OFS, 131500 + NW_OFS),
    'Mp1b': (42200 + NW_OFS, 131500 + NW_OFS),
    'Mp2a': (48000 + NW_OFS, 131500 + NW_OFS),
    'Mp2b': (50500 + NW_OFS, 131500 + NW_OFS),
}

W = ACT_W
NX = {
    'Mn1a': 0,
    'Mn1b': W + GAP_PAIR,
    'Mn2b': 2 * W + 2 * GAP_PAIR + GAP_CENTER - W,
    'Mn2a': 2 * W + 2 * GAP_PAIR + GAP_CENTER,
}
# Recalculate cleanly
NX['Mn1a'] = 0
NX['Mn1b'] = W + GAP_PAIR                    # 1880
NX['Mn2b'] = NX['Mn1b'] + W + GAP_CENTER     # 4060
NX['Mn2a'] = NX['Mn2b'] + W + GAP_PAIR       # 5940

PX = {'Mp1a': NX['Mn1a'], 'Mp1b': NX['Mn1b'],
      'Mp2b': NX['Mn2b'], 'Mp2a': NX['Mn2a']}

NY_N = 0
NY_P = ACT_H + NMOS_PMOS_GAP  # 5500

FLIP_DEVICES = {'Mn2a', 'Mn2b', 'Mp2a', 'Mp2b'}


def build():
    print('=== Building H-bridge (SR latch) — placement + ties ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('hbridge')

    # ─── Step 1: Extract + re-place ───
    print('\n--- Step 1: Extract + re-place ---')

    def extract_device(name, src_ax, src_ay, tgt_ax, tgt_ay, is_pmos, flip):
        margin = 50
        if is_pmos:
            sx1 = src_ax - NW_OFS - margin
            sy1 = src_ay - NW_OFS - margin
            sx2 = src_ax + W + NW_OFS + margin
            sy2 = src_ay + ACT_H + NW_OFS + margin
        else:
            sx1 = src_ax - margin
            sy1 = src_ay - 180 - margin
            sx2 = src_ax + W + margin
            sy2 = src_ay + ACT_H + 180 + margin

        search = pya.Box(sx1, sy1, sx2, sy2)
        count = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(src_top.begin_shapes_rec(li))
            for poly in (region & pya.Region(search)).each():
                if flip:
                    pts = []
                    for p in poly.each_point_hull():
                        local_x = p.x - src_ax
                        local_y = p.y - src_ay
                        pts.append(pya.Point(tgt_ax + (W - local_x), tgt_ay + local_y))
                    if len(pts) >= 3:
                        cell.shapes(tli).insert(pya.Polygon(pts[::-1]))
                    count += 1
                else:
                    cell.shapes(tli).insert(poly.moved(tgt_ax - src_ax, tgt_ay - src_ay))
                    count += 1

        flip_str = ' (flip)' if flip else ''
        print(f'  {name}{flip_str}: {count} shapes')

    for name in ['Mn1a', 'Mn1b', 'Mn2a', 'Mn2b']:
        ax, ay = ORIG[name]
        extract_device(name, ax, ay, NX[name], NY_N, False, name in FLIP_DEVICES)

    for name in ['Mp1a', 'Mp1b', 'Mp2a', 'Mp2b']:
        ax, ay = ORIG[name]
        extract_device(name, ax, ay, PX[name], NY_P, True, name in FLIP_DEVICES)

    # ─── Step 2: Ties ───
    print('--- Step 2: Ties ---')
    l_m1 = out.layer(*M1)
    l_activ = out.layer(*ACTIV)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_poly = out.layer(*GATPOLY)
    l_nw = out.layer(*NWELL)

    # ptap below NMOS center
    ptap_x = (NX['Mn1b'] + W + NX['Mn2b']) // 2 - 250
    cell.shapes(l_activ).insert(box(ptap_x, -600, ptap_x + 500, -100))
    cell.shapes(l_m1).insert(box(ptap_x, -600, ptap_x + 500, -100))
    cell.shapes(l_psd).insert(box(ptap_x - 100, -700, ptap_x + 600, 0))
    cell.shapes(l_cont).insert(box(ptap_x + 170, -430, ptap_x + 330, -270))

    # ntap above PMOS — well inside NWell, 400nm gap from PMOS Active top
    # PMOS Active top = NY_P + ACT_H = 7500
    # NWell top (from PCell) = 7500 + 310 = 7810
    ntap_y = NY_P + ACT_H + 400   # 7900 — above PCell NWell, need to extend NWell
    ntap_h = 500
    # Extend NWell to cover ntaps
    cell.shapes(l_nw).insert(box(-NW_OFS, NY_P - NW_OFS,
                                  NX['Mn2a'] + W + NW_OFS, ntap_y + ntap_h + 100))
    for px in [PX['Mp1a'] + 340, PX['Mp1b'] + 340, PX['Mp2b'] + 340, PX['Mp2a'] + 340]:
        cell.shapes(l_activ).insert(box(px, ntap_y, px + 500, ntap_y + ntap_h))
        cell.shapes(l_m1).insert(box(px, ntap_y, px + 500, ntap_y + ntap_h))
        cell.shapes(l_cont).insert(box(px + 170, ntap_y + 170, px + 330, ntap_y + 330))

    # ─── Step 3: n1_mid, n2_mid M1 bridges ───
    print('--- Step 3: n1_mid / n2_mid ---')
    # n1_mid: Mn1a.D(right, 950-1110) ↔ Mn1b.S(left, 1950-2110)
    cell.shapes(l_m1).insert(box(1110, 500, 1950, 660))
    # n2_mid: Mn2b.S(right-flip, 5010-5170) ↔ Mn2a.D(left-flip, 6010-6170)
    cell.shapes(l_m1).insert(box(5170, 500, 6010, 660))
    print('  n1_mid: x=1110-1950, n2_mid: x=5170-6010')

    # ─── Step 4: Input gate routing (comp_outp, comp_outn) ───
    print('--- Step 4: Input gates ---')

    def add_gate_contact(poly_cx, cont_cy):
        cell.shapes(l_cont).insert(box(poly_cx - 80, cont_cy - 80, poly_cx + 80, cont_cy + 80))
        cell.shapes(l_m1).insert(box(poly_cx - 155, cont_cy - 155, poly_cx + 155, cont_cy + 155))

    # From GDS: NMOS poly top ≈ y=2230, PMOS poly bottom ≈ y=5320
    # Poly extensions bridge the gap to routing channel
    poly_ext = 500

    # comp_outp: Mn1a.G ↔ Mp1a.G (both at x=590, aligned)
    gcx1 = 590
    cell.shapes(l_poly).insert(box(gcx1 - 250, 2230, gcx1 + 250, 2230 + poly_ext))  # above NMOS
    cell.shapes(l_poly).insert(box(gcx1 - 250, 5320 - poly_ext, gcx1 + 250, 5320))  # below PMOS
    add_gate_contact(gcx1, 2230 + 250)   # NMOS gate contact
    add_gate_contact(gcx1, 5320 - 250)   # PMOS gate contact
    # M1 vertical connecting both contacts
    cell.shapes(l_m1).insert(box(gcx1 - 155, 2230 + 405, gcx1 + 155, 5320 - 405))
    print(f'  comp_outp: x={gcx1}, M1 vertical y={2230+405}-{5320-405}')

    # comp_outn: Mn2a.G ↔ Mp2a.G (both at x=6530, aligned)
    gcx2 = 6530
    cell.shapes(l_poly).insert(box(gcx2 - 250, 2230, gcx2 + 250, 2230 + poly_ext))
    cell.shapes(l_poly).insert(box(gcx2 - 250, 5320 - poly_ext, gcx2 + 250, 5320))
    add_gate_contact(gcx2, 2230 + 250)
    add_gate_contact(gcx2, 5320 - 250)
    cell.shapes(l_m1).insert(box(gcx2 - 155, 2230 + 405, gcx2 + 155, 5320 - 405))
    print(f'  comp_outn: x={gcx2}, M1 vertical y={2230+405}-{5320-405}')

    # ─── Step 4b: Via1+M2 pads for inter-module routing ───
    # Place BELOW NMOS (y=-500) where M2 is completely free.
    # Gate M1 vertical extends from gate contact (y≈2480) down to Via1 pad.
    # M1 at x=435-745 (comp_outp) and x=6375-6685 (comp_outn) passes between
    # S/D strips (gap ≥205nm > M1.b=180nm).
    print('--- Step 4b: Inter-module Via1+M2 pads ---')
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)
    via1_y = -500  # below NMOS, clear of all M2

    for gcx, name in [(gcx1, 'comp_outp'), (gcx2, 'comp_outn')]:
        # Extend gate M1 down from gate contact (y=2480) to Via1 pad
        cell.shapes(l_m1).insert(box(gcx - 155, via1_y - 185, gcx + 155, 2230 + 95))
        # Via1 (190x190)
        cell.shapes(l_via1).insert(box(gcx - 95, via1_y - 95, gcx + 95, via1_y + 95))
        # M1 pad for Via1 (already covered by the extension above)
        # M2 pad (480x310, safe enclosure)
        cell.shapes(l_m2).insert(box(gcx - 240, via1_y - 155, gcx + 240, via1_y + 155))
        print(f'  {name}: Via1+M2 at ({gcx}, {via1_y})')

    # ─── Step 5: lat_q / lat_qb drain collection (Via1 + M2) ───
    print('--- Step 5: lat_q / lat_qb M2 ---')
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)

    def add_via1(strip_xl, strip_xr, via_y):
        """Place Via1 + M1 pad + M2 pad on a strip. Returns cx."""
        cx = (strip_xl + strip_xr) // 2
        cell.shapes(l_m1).insert(box(cx - 155, via_y - 155, cx + 155, via_y + 155))
        cell.shapes(l_via1).insert(box(cx - 95, via_y - 95, cx + 95, via_y + 95))
        cell.shapes(l_m2).insert(box(cx - 240, via_y - 155, cx + 240, via_y + 155))
        return cx

    # M2 bus Y positions (in routing channel between NMOS top=2180 and PMOS bot=5500)
    y_latq = 3200    # lat_q M2 bus
    y_latqb = 3800   # lat_qb M2 bus  (gap = 600-310 = 290 > M2.b=210 ✓)

    # lat_q drains: Mn1b.D(right,2830-2990) + Mp1a.D(right,950-1110) + Mp1b.D(right,2830-2990 @PMOS)
    # After extraction: NMOS strips at y≈180-2180, PMOS strips at y≈5500-7500
    v1_mn1b_d = add_via1(2830, 2990, 1400)   # Mn1b.D
    v1_mp1a_d = add_via1(950, 1110, 6400)    # Mp1a.D
    v1_mp1b_d = add_via1(2830, 2990, 6400)   # Mp1b.D

    # M2 verticals: each Via1 connects to bus only (not full height)
    def m2_vert(cx, via_y, bus_y):
        """M2 vertical from Via1 position to bus, 300nm wide."""
        y1 = min(via_y - 155, bus_y - 155)
        y2 = max(via_y + 155, bus_y + 155)
        cell.shapes(l_m2).insert(box(cx - 150, y1, cx + 150, y2))

    # lat_q: NMOS drain goes UP to bus, PMOS drains go DOWN to bus
    m2_vert(v1_mn1b_d, 1400, y_latq)   # Mn1b.D ↑ bus
    m2_vert(v1_mp1a_d, 6400, y_latq)   # Mp1a.D ↓ bus
    m2_vert(v1_mp1b_d, 6400, y_latq)   # Mp1b.D ↓ bus
    # M2 horizontal bus
    x_min = min(v1_mp1a_d, v1_mn1b_d, v1_mp1b_d) - 150
    x_max = max(v1_mp1a_d, v1_mn1b_d, v1_mp1b_d) + 150
    cell.shapes(l_m2).insert(box(x_min, y_latq - 155, x_max, y_latq + 155))
    print(f'  lat_q M2 bus: y={y_latq}, x={x_min}-{x_max}')

    # lat_qb drains (flipped = D on left side)
    v1_mn2b_d = add_via1(4130, 4290, 1400)   # Mn2b.D
    v1_mp2a_d = add_via1(6010, 6170, 6400)   # Mp2a.D
    v1_mp2b_d = add_via1(4130, 4290, 6400)   # Mp2b.D

    m2_vert(v1_mn2b_d, 1400, y_latqb)
    m2_vert(v1_mp2a_d, 6400, y_latqb)
    m2_vert(v1_mp2b_d, 6400, y_latqb)
    x_min2 = min(v1_mn2b_d, v1_mp2a_d, v1_mp2b_d) - 150
    x_max2 = max(v1_mn2b_d, v1_mp2a_d, v1_mp2b_d) + 150
    cell.shapes(l_m2).insert(box(x_min2, y_latqb - 155, x_max2, y_latqb + 155))
    print(f'  lat_qb M2 bus: y={y_latqb}, x={x_min2}-{x_max2}')

    # ─── Write + DRC ───
    out_path = os.path.join(OUT_DIR, 'hbridge.gds')
    out.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width() / 1000:.1f}x{bb.height() / 1000:.1f}um')

    li_m1 = out.find_layer(*M1)
    if li_m1 is not None:
        m1r = pya.Region(cell.begin_shapes_rec(li_m1))
        print(f'  Quick DRC: M1.b={m1r.space_check(180).count()}, M1.a={m1r.width_check(160).count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
