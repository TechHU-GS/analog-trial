#!/usr/bin/env python3
"""Build Chopper module — PCell instantiation + routing.

Circuit (2 transmission gates):
    TG1: Mchop1n (NMOS W=2u L=0.5u) + Mchop1p (PMOS W=4u L=0.5u) — sens_p ↔ chop_out
    TG2: Mchop2n (NMOS W=2u L=0.5u) + Mchop2p (PMOS W=4u L=0.5u) — sens_n ↔ chop_out

    chop_out: all S terminals (external → Rin)
    sens_p:   TG1 D terminals
    sens_n:   TG2 D terminals
    f_exc:    Mchop1n.G + Mchop2p.G
    f_exc_b:  Mchop1p.G + Mchop2n.G

Device params from sim/_soilz_full.sp.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_chopper.py
"""

import klayout.db as pya
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from pcell_utils import (create_nmos, create_pmos, probe_device, place_device,
                         abs_strips, abs_gates, add_ptap, add_ntap, quick_drc, box)

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


def build():
    print('=== Building Chopper (PCell) ===')

    ly = pya.Layout()
    ly.dbu = 0.001
    cell = ly.create_cell('chopper')

    # ─── Step 1: Create PCells ───
    print('\n--- Step 1: PCell creation ---')
    nmos_cell = create_nmos(ly, w_um=2, l_um=0.5)
    pmos_cell = create_pmos(ly, w_um=4, l_um=0.5)

    n_info = probe_device(ly, nmos_cell)
    p_info = probe_device(ly, pmos_cell)
    print(f'  NMOS: {n_info["w"]/1000:.1f}x{n_info["h"]/1000:.1f}um, '
          f'{len(n_info["strips"])} strips, {len(n_info["gates"])} gates')
    print(f'  PMOS: {p_info["w"]/1000:.1f}x{p_info["h"]/1000:.1f}um, '
          f'{len(p_info["strips"])} strips, {len(p_info["gates"])} gates')

    # ─── Step 2: Place devices ───
    print('\n--- Step 2: Placement ---')
    # Layout: TG1(left) gap TG2(right)
    # Each TG: NMOS at bottom, PMOS above with gap for NWell spacing
    nmos_h = n_info['h']
    pmos_h = p_info['h']
    nmos_w = n_info['w']
    pmos_w = p_info['w']

    np_gap = 2000   # vertical gap between NMOS top and PMOS bottom
    tg_gap = 3000   # horizontal gap between TG1 and TG2
    pmos_x_ofs = 500  # horizontal offset for PMOS to avoid strip Via1 overlap

    # NMOS devices at y=0
    # PMOS devices above (need NWell separation from NMOS)
    pmos_y = nmos_h + np_gap

    # TG1: nmos + pmos (left)
    n1_x, n1_y = 0, 0
    p1_x, p1_y = pmos_x_ofs, pmos_y

    # TG2: nmos + pmos (right)
    tg2_x = max(nmos_w, pmos_w + pmos_x_ofs) + tg_gap
    n2_x, n2_y = tg2_x, 0
    p2_x, p2_y = tg2_x + pmos_x_ofs, pmos_y

    place_device(cell, nmos_cell, n1_x, n1_y)  # Mchop1n
    place_device(cell, pmos_cell, p1_x, p1_y)  # Mchop1p
    place_device(cell, nmos_cell, n2_x, n2_y)  # Mchop2n
    place_device(cell, pmos_cell, p2_x, p2_y)  # Mchop2p

    # Get absolute strip/gate positions
    n1_strips = abs_strips(n_info, n1_x, n1_y)  # [(xl,xr,yb,yt), ...]
    p1_strips = abs_strips(p_info, p1_x, p1_y)
    n2_strips = abs_strips(n_info, n2_x, n2_y)
    p2_strips = abs_strips(p_info, p2_x, p2_y)

    n1_gates = abs_gates(n_info, n1_x, n1_y)
    p1_gates = abs_gates(p_info, p1_x, p1_y)
    n2_gates = abs_gates(n_info, n2_x, n2_y)
    p2_gates = abs_gates(p_info, p2_x, p2_y)

    # NMOS: S=strip[0](left), D=strip[-1](right)  (ng=1, 2 strips)
    # PMOS: S=strip[0](left), D=strip[-1](right)
    # TG net mapping:
    #   chop_out = TG1 S (n1_S + p1_S) + TG2 S (n2_S + p2_S)
    #   sens_p = TG1 D (n1_D + p1_D)
    #   sens_n = TG2 D (n2_D + p2_D)

    print(f'  Mchop1n: x={n1_x}, strips@x={[s[0] for s in n1_strips]}')
    print(f'  Mchop1p: x={p1_x}, strips@x={[s[0] for s in p1_strips]}')
    print(f'  Mchop2n: x={n2_x}, strips@x={[s[0] for s in n2_strips]}')
    print(f'  Mchop2p: x={p2_x}, strips@x={[s[0] for s in p2_strips]}')

    # ─── Step 3: Ties ───
    print('\n--- Step 3: Ties ---')
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_via1 = ly.layer(*VIA1)
    l_poly = ly.layer(*GATPOLY)
    l_cont = ly.layer(*CONT)
    l_nw = ly.layer(*NWELL)

    # ptap below NMOS
    ptap_y1 = -700
    ptap_y2 = -200
    total_w = max(n2_strips[-1][1], p2_strips[-1][1]) + 500
    mid_x = (n1_strips[-1][1] + n2_strips[0][0]) // 2
    add_ptap(cell, ly, mid_x, ptap_y1, ptap_y2)

    # ntap above PMOS (inside NWell)
    pmos_top = max(p1_strips[-1][3], p2_strips[-1][3])
    ntap_y1 = pmos_top + 800  # 800nm gap to avoid Cnt.b with gate contacts
    ntap_y2 = ntap_y1 + 500

    # NWell covering both PMOS + ntaps
    p_bb = p_info['bbox']
    nw_margin = 310
    nw_x1 = min(p1_x, p2_x) - nw_margin
    nw_x2 = max(p1_x + pmos_w, p2_x + pmos_w) + nw_margin
    nw_y1 = pmos_y - nw_margin
    nw_y2 = ntap_y2 + 100
    cell.shapes(l_nw).insert(box(nw_x1, nw_y1, nw_x2, nw_y2))

    add_ntap(cell, ly, (p1_strips[0][0] + p1_strips[-1][1]) // 2, ntap_y1, ntap_y2)
    add_ntap(cell, ly, (p2_strips[0][0] + p2_strips[-1][1]) // 2, ntap_y1, ntap_y2)
    print(f'  ptap: x={mid_x}, ntaps above PMOS')

    # ─── Step 4: M2 routing (Via1 on S/D strips → M2 buses) ───
    print('\n--- Step 4: M2 routing ---')

    def add_via1_pad(strip, via_y):
        """Add Via1+M1+M2 pad on a strip at given y. Returns M2 pad bbox."""
        cx = (strip[0] + strip[1]) // 2
        cell.shapes(l_m1).insert(box(cx - 155, via_y - 155, cx + 155, via_y + 155))
        cell.shapes(ly.layer(*VIA1)).insert(box(cx - 95, via_y - 95, cx + 95, via_y + 95))
        cell.shapes(l_m2).insert(box(cx - 245, via_y - 155, cx + 245, via_y + 155))
        return (cx - 245, via_y - 155, cx + 245, via_y + 155)

    # M2 Y centers (spacing ≥ M2.b=210nm)
    y_chop = 500     # chop_out
    y_sensp = 1200   # sens_p
    y_sensn = 1900   # sens_n

    # chop_out: S strips of all 4 devices
    chop_strips = [n1_strips[0], p1_strips[0], n2_strips[0], p2_strips[0]]
    chop_pads = [add_via1_pad(s, y_chop) for s in chop_strips]
    chop_x1 = min(p[0] for p in chop_pads)
    chop_x2 = max(p[2] for p in chop_pads)
    cell.shapes(l_m2).insert(box(chop_x1, y_chop - 155, chop_x2, y_chop + 155))
    print(f'  chop_out M2: y={y_chop}')

    # sens_p: D strips of TG1
    sp_strips = [n1_strips[-1], p1_strips[-1]]
    sp_pads = [add_via1_pad(s, y_sensp) for s in sp_strips]
    sp_x1 = min(p[0] for p in sp_pads)
    sp_x2 = max(p[2] for p in sp_pads)
    cell.shapes(l_m2).insert(box(sp_x1, y_sensp - 155, sp_x2, y_sensp + 155))
    print(f'  sens_p M2: y={y_sensp}')

    # sens_n: D strips of TG2
    sn_strips = [n2_strips[-1], p2_strips[-1]]
    sn_pads = [add_via1_pad(s, y_sensn) for s in sn_strips]
    sn_x1 = min(p[0] for p in sn_pads)
    sn_x2 = max(p[2] for p in sn_pads)
    cell.shapes(l_m2).insert(box(sn_x1, y_sensn - 155, sn_x2, y_sensn + 155))
    print(f'  sens_n M2: y={y_sensn}')

    # ─── Step 5: Gate routing (f_exc, f_exc_b via M2) ───
    # Gate contacts extend BELOW devices (avoids M1 conflicts with S/D strips)
    # Then Via1 → M2 horizontal bar connects gate pairs
    print('\n--- Step 5: Gate routing (M2) ---')

    g_n1 = n1_gates[0]  # Mchop1n → f_exc
    g_p1 = p1_gates[0]  # Mchop1p → f_exc_b
    g_n2 = n2_gates[0]  # Mchop2n → f_exc_b
    g_p2 = p2_gates[0]  # Mchop2p → f_exc

    poly_ext = 500

    # Gap zone between NMOS top and PMOS bottom: y=nmos_h to pmos_y
    # Extend NMOS gates UP, PMOS gates DOWN, meet in the gap
    gap_mid = (nmos_h + pmos_y) // 2  # center of gap

    def gate_to_m2(g, extend_up=True):
        """Extend gate poly into gap zone, add Contact+Via1+M2. Returns (cx, m2_cy)."""
        gcx = (g[0] + g[1]) // 2
        gw = g[1] - g[0]
        if extend_up:
            cell.shapes(l_poly).insert(box(gcx - gw // 2, g[3], gcx + gw // 2, g[3] + poly_ext))
            cy = g[3] + poly_ext - 250
        else:
            cell.shapes(l_poly).insert(box(gcx - gw // 2, g[2] - poly_ext, gcx + gw // 2, g[2]))
            cy = g[2] - poly_ext + 250
        cell.shapes(l_cont).insert(box(gcx - 80, cy - 80, gcx + 80, cy + 80))
        cell.shapes(l_m1).insert(box(gcx - 155, cy - 155, gcx + 155, cy + 155))
        cell.shapes(ly.layer(*VIA1)).insert(box(gcx - 95, cy - 95, gcx + 95, cy + 95))
        cell.shapes(l_m2).insert(box(gcx - 245, cy - 155, gcx + 245, cy + 155))
        return gcx, cy

    n1_gc = gate_to_m2(g_n1, extend_up=True)   # NMOS → extend up into gap
    n2_gc = gate_to_m2(g_n2, extend_up=True)
    p1_gc = gate_to_m2(g_p1, extend_up=False)  # PMOS → extend down into gap
    p2_gc = gate_to_m2(g_p2, extend_up=False)

    # f_exc_b M2: connect p1_gc ↔ n2_gc
    fexcb_y = min(p1_gc[1], n2_gc[1])
    cell.shapes(l_m2).insert(box(min(p1_gc[0], n2_gc[0]) - 245, fexcb_y - 155,
                                  max(p1_gc[0], n2_gc[0]) + 245, fexcb_y + 155))
    # M2 verticals to bar
    for gcx, gcy in [p1_gc, n2_gc]:
        y1, y2 = min(gcy, fexcb_y) - 155, max(gcy, fexcb_y) + 155
        cell.shapes(l_m2).insert(box(gcx - 150, y1, gcx + 150, y2))
    print(f'  f_exc_b M2: y={fexcb_y}')

    # f_exc M2: connect n1_gc ↔ p2_gc (ABOVE f_exc_b to avoid overlap with S/D M2)
    fexc_y = fexcb_y + 600
    cell.shapes(l_m2).insert(box(min(n1_gc[0], p2_gc[0]) - 245, fexc_y - 155,
                                  max(n1_gc[0], p2_gc[0]) + 245, fexc_y + 155))
    for gcx, gcy in [n1_gc, p2_gc]:
        y1, y2 = min(gcy, fexc_y) - 155, max(gcy, fexc_y) + 155
        cell.shapes(l_m2).insert(box(gcx - 150, y1, gcx + 150, y2))
    print(f'  f_exc M2: y={fexc_y}')

    # ─── Output ───
    out_path = os.path.join(OUT_DIR, 'chopper.gds')
    ly.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')
    print(f'  Written: {out_path}')

    quick_drc(ly, cell)
    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
