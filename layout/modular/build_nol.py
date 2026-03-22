#!/usr/bin/env python3
"""Build NOL (non-overlapping logic) module.

22 devices generating H-bridge gate drive signals:
    M_inv0: f_exc inverter → f_exc_b
    M_da1/da2: delay chain A (f_exc → f_exc_d)
    M_db1/db2: delay chain B (f_exc_b → f_exc_b_d)
    M_na (NAND A): f_exc + f_exc_b_d → nand_a
    M_nb (NAND B): f_exc_b + f_exc_d → nand_b
    M_ia: nand_a inverter → phi_p (H-bridge drive)
    M_ib: nand_b inverter → phi_n (H-bridge drive)

Extraction from soilz_bare.gds. Ties + local routing TBD.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_nol.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

M1 = (8, 0)
ACTIV = (1, 0)
CONT = (6, 0)
PSD = (14, 0)
GATPOLY = (5, 0)
NWELL = (31, 0)


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building NOL (non-overlapping logic) ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # ─── Step 1: Extract ───
    print('\n--- Step 1: Extract ---')
    # Block A+B: x=131.2-158.8, y=71.8-82.1 (absolute)
    # M_inv0: x=112.0, y=72/77.5 — isolated, relocate to block A left edge
    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('nol')

    def extract_region(search_box, dx, dy):
        count = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(src_top.begin_shapes_rec(li))
            for poly in (region & pya.Region(search_box)).each():
                cell.shapes(tli).insert(poly.moved(dx, dy))
                count += 1
        return count

    # Extract main block (DA/DB/NA/NB/IA/IB): x=130.5-159.5
    block_origin_x = 131200  # DA1_p x (leftmost in block)
    block_origin_y = 72000
    inv0_slot = 2500  # space reserved for M_inv0 at the left
    n1 = extract_region(
        pya.Box(130500, 71500, 159500, 83000),
        -block_origin_x + inv0_slot, -block_origin_y)
    print(f'  Block A+B: {n1} shapes, shifted to x={inv0_slot/1000:.1f}+')

    # Extract M_inv0 and place at x=0 (left of block)
    # M_inv0_n: x=112.0 y=72.0 (nmos_vco, w=1.18)
    # M_inv0_p: x=112.0 y=77.5 (pmos_vco, NWell offset +310)
    # pmos_vco NWell extends to x=113800, must include fully
    inv0_search = pya.Box(111500, 71500, 113900, 83000)
    inv0_target_x = 0
    n2 = extract_region(
        inv0_search,
        inv0_target_x - 112000, -block_origin_y)
    print(f'  M_inv0: {n2} shapes, placed at x={inv0_target_x/1000:.1f}')

    bb = cell.bbox()
    print(f'  Total: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    # ─── Step 2: Ties ───
    print('--- Step 2: Ties ---')
    l_m1 = out.layer(*M1)
    l_activ = out.layer(*ACTIV)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_nw = out.layer(*NWELL)

    # NMOS row: y≈0 (local). PMOS row: y≈5500 (local).
    # ptap below NMOS (within module width)
    module_w = cell.bbox().width()
    for px in [3000, 10000, 17000, 24000]:
        cell.shapes(l_activ).insert(box(px, -600, px + 500, -100))
        cell.shapes(l_m1).insert(box(px, -600, px + 500, -100))
        cell.shapes(l_psd).insert(box(px - 100, -700, px + 600, 0))
        cell.shapes(l_cont).insert(box(px + 170, -430, px + 330, -270))

    # ntap above PMOS — need to check NWell extent first
    # PMOS types: pmos_vco (h=2.62, NWell top at y=5500+2310=7810)
    #             pmos_buf1 (h=4.62, NWell top at y=5500+4310=9810)
    # Use the tallest NWell top + 400nm gap for ntap
    # Merge all NWell into one block covering ntap
    nw_region = pya.Region(cell.begin_shapes_rec(l_nw))
    if nw_region.count() > 0:
        nw_bb = nw_region.bbox()
        ntap_y = nw_bb.top + 400
        cell.shapes(l_nw).insert(box(nw_bb.left, nw_bb.bottom, nw_bb.right, ntap_y + 600))
        for nx in [5000, 15000, 25000, 35000]:
            if nx >= nw_bb.left and nx + 500 <= nw_bb.right:
                cell.shapes(l_activ).insert(box(nx, ntap_y, nx + 500, ntap_y + 500))
                cell.shapes(l_m1).insert(box(nx, ntap_y, nx + 500, ntap_y + 500))
                cell.shapes(l_cont).insert(box(nx + 170, ntap_y + 170, nx + 330, ntap_y + 330))
        print(f'  NWell merged, ntap at y={ntap_y/1000:.1f}')

    # ─── Step 3: Inverter output routing (NMOS.D ↔ PMOS.D via Via1+M2) ───
    print('--- Step 3: Inverter outputs ---')
    l_m2 = out.layer(10, 0)
    l_via1 = out.layer(19, 0)

    def add_via1(strip_cx, via_y):
        cell.shapes(l_m1).insert(box(strip_cx-155, via_y-155, strip_cx+155, via_y+155))
        cell.shapes(l_via1).insert(box(strip_cx-95, via_y-95, strip_cx+95, via_y+95))
        cell.shapes(l_m2).insert(box(strip_cx-240, via_y-155, strip_cx+240, via_y+155))

    # (nmos_D_cx, pmos_D_cx, net_name, pmos_is_buf1, m2_bus_y)
    # Different y levels to avoid M2 overlap between crossing nets
    # Left block: f_exc_b(1.0-1.3), da1(3.8-6.6), f_exc_d(6.3-8.5), phi_p(13.8-14.2)
    #   da1 and f_exc_d overlap in x → different y
    # Right block: db1(19.3-19.6), f_exc_b_d(21.2-22.1), phi_n(26.9-29.6) → no overlap
    inv_nets = [
        (1030, 1340, 'f_exc_b', False, 3000),
        (6630, 3840, 'da1', False, 3500),
        (8510, 6340, 'f_exc_d', False, 4200),    # shifted to avoid da1
        (19330, 19640, 'db1', False, 3000),
        (21210, 22140, 'f_exc_b_d', False, 3500),
        (14150, 13840, 'phi_p', True, 4200),
        (26850, 29640, 'phi_n', True, 4200),
    ]

    for n_dcx, p_dcx, name, is_buf1, bus_y in inv_nets:
        # nmos_vco strip top ≈ 1180, nmos_buf1 strip top ≈ 2180
        # Place Via1 within strip range, not above
        n_via_y = 800 if not is_buf1 else 1400
        add_via1(n_dcx, n_via_y)
        p_via_y = 7500 if is_buf1 else 6400
        add_via1(p_dcx, p_via_y)
        cell.shapes(l_m2).insert(box(n_dcx-150, 1245, n_dcx+150, bus_y+155))
        cell.shapes(l_m2).insert(box(p_dcx-150, bus_y-155, p_dcx+150, p_via_y+155))
        x1 = min(n_dcx, p_dcx) - 150
        x2 = max(n_dcx, p_dcx) + 150
        cell.shapes(l_m2).insert(box(x1, bus_y-155, x2, bus_y+155))
        print(f'  {name}: n.D({n_dcx/1000:.1f}) ↔ p.D({p_dcx/1000:.1f})')

    # ─── Step 4: NAND mid nodes (M1 bridge) ───
    print('--- Step 4: NAND mid ---')
    cell.shapes(l_m1).insert(box(9430, 500, 12350, 660))
    cell.shapes(l_m1).insert(box(22130, 500, 25050, 660))
    print('  na_mid: x=9.4-12.4, nb_mid: x=22.1-25.1')

    # ─── Write + DRC ───
    out_path = os.path.join(OUT_DIR, 'nol.gds')
    out.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    li_m1 = out.find_layer(*M1)
    if li_m1 is not None:
        m1r = pya.Region(cell.begin_shapes_rec(li_m1))
        print(f'  Quick DRC: M1.b={m1r.space_check(180).count()}, M1.a={m1r.width_check(160).count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
