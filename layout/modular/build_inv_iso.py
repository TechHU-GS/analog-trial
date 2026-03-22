#!/usr/bin/env python3
"""Build INV_iso (VCO→TFF isolation buffer) module.

4 devices, 2 inverters:
    INV_iso (n+p): vco_out → vco_buf
    INV_isob (n+p): vco_buf → vco_buf_b

Routing: inverter output D-D via Via1+M2.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_inv_iso.py
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
    print('=== Building INV_iso ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # Devices: x=88-91.8, y=178-186.1
    # INV_iso_p is pmos_buf1 (h=4.62, NWell extends further)
    # NWell right = 88000+1800=89800 (pmos_buf1) and 90000+1800=91800 (pmos_vco)
    # INV_iso_p NWell top = 181500+4310=185810 (pmos_buf1 bbox)
    # Search box must cover all NWell/pSD
    search = pya.Box(87500, 177500, 92500, 186500)
    origin_x = 88000
    origin_y = 178000

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('inv_iso')

    for li in src.layer_indices():
        info = src.get_info(li)
        tli = out.layer(info.layer, info.datatype)
        region = pya.Region(src_top.begin_shapes_rec(li))
        for poly in (region & pya.Region(search)).each():
            cell.shapes(tli).insert(poly.moved(-origin_x, -origin_y))

    bb = cell.bbox()
    print(f'  Extracted: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    l_m1 = out.layer(*M1)
    l_m2 = out.layer(*M2)
    l_via1 = out.layer(*VIA1)
    l_activ = out.layer(*ACTIV)
    l_cont = out.layer(*CONT)
    l_psd = out.layer(*PSD)
    l_nw = out.layer(*NWELL)

    # ─── Ties ───
    print('--- Ties ---')
    # ptap below NMOS
    cell.shapes(l_activ).insert(box(500, -600, 1000, -100))
    cell.shapes(l_m1).insert(box(500, -600, 1000, -100))
    cell.shapes(l_psd).insert(box(400, -700, 1100, 0))
    cell.shapes(l_cont).insert(box(670, -430, 830, -270))

    # ntap above PMOS — merge NWell + extend
    nw_region = pya.Region(cell.begin_shapes_rec(l_nw))
    if nw_region.count() > 0:
        nw_bb = nw_region.bbox()
        ntap_y = nw_bb.top + 400
        cell.shapes(l_nw).insert(box(nw_bb.left, nw_bb.bottom, nw_bb.right, ntap_y + 600))
        cell.shapes(l_activ).insert(box(500, ntap_y, 1000, ntap_y + 500))
        cell.shapes(l_m1).insert(box(500, ntap_y, 1000, ntap_y + 500))
        cell.shapes(l_cont).insert(box(670, ntap_y + 170, 830, ntap_y + 330))

    # ─── Routing: inverter outputs (Via1+M2) ───
    print('--- Routing ---')

    def add_via1(cx, vy):
        cell.shapes(l_m1).insert(box(cx-155, vy-155, cx+155, vy+155))
        cell.shapes(l_via1).insert(box(cx-95, vy-95, cx+95, vy+95))
        cell.shapes(l_m2).insert(box(cx-240, vy-155, cx+240, vy+155))

    # INV_iso: local coords
    # INV_iso_n at (0, 0), nmos_buf1: D at x=1030, strip y=0-2000
    # INV_iso_p at (0, 3500), pmos_buf1: D at x=310+1030=1340, strip y=3810-5810
    # INV_isob_n at (2000, 1000), nmos_vco: D at x=3030, strip y=1000-2000 (short)
    # INV_isob_p at (2000, 4500), pmos_vco: D at x=2310+1030=3340, strip y=4810-6810

    # vco_buf: INV_iso_n.D(1030) ↔ INV_iso_p.D(1340)
    bus_y1 = 2800
    add_via1(1030, 1400)
    add_via1(1340, 4800)
    cell.shapes(l_m2).insert(box(880, 1245, 1180, bus_y1+155))
    cell.shapes(l_m2).insert(box(1100, bus_y1-155, 1490, 4955))
    cell.shapes(l_m2).insert(box(880, bus_y1-155, 1490, bus_y1+155))
    print(f'  vco_buf: n.D(1.03) ↔ p.D(1.34) via M2 y={bus_y1/1000:.1f}')

    # vco_buf_b: INV_isob_n.D(3030) ↔ INV_isob_p.D(3340)
    bus_y2 = 3200
    add_via1(3030, 1500)  # nmos_vco strip is shorter
    add_via1(3340, 5500)
    cell.shapes(l_m2).insert(box(2880, 1345, 3180, bus_y2+155))
    cell.shapes(l_m2).insert(box(3100, bus_y2-155, 3490, 5655))
    cell.shapes(l_m2).insert(box(2880, bus_y2-155, 3490, bus_y2+155))
    print(f'  vco_buf_b: n.D(3.03) ↔ p.D(3.34) via M2 y={bus_y2/1000:.1f}')

    # ─── Write + DRC ───
    out_path = os.path.join(OUT_DIR, 'inv_iso.gds')
    out.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    li_m1 = out.find_layer(*M1)
    li_m2 = out.find_layer(*M2)
    if li_m1 is not None:
        m1r = pya.Region(cell.begin_shapes_rec(li_m1))
        print(f'  Quick DRC: M1.b={m1r.space_check(180).count()}, M1.a={m1r.width_check(160).count()}')
    if li_m2 is not None:
        m2r = pya.Region(cell.begin_shapes_rec(li_m2))
        print(f'  Quick DRC: M2.b={m2r.space_check(210).count()}, M2.a={m2r.width_check(200).count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
