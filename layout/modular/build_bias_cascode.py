#!/usr/bin/env python3
"""Build BIAS cascode with compact re-placement.

Pairs (mirror above cascode, X-aligned):
    Col 0: PM_cas_ref (NW 11.3) + PM_cas_diode (NW 11.1) + MN_cas_load
    Col 1: PM_mir1 (NW 11.3) + PM_cas1 (NW 11.1)
    Col 2: PM_mir2 (NW 11.3) + PM_cas2 (NW 13.5)
    Col 3: PM_mir3 (NW 15.0) + PM_cas3 (NW 5.7)

Vertical: MN_cas_load → cascode → mirror (NW.b1=1.8um gap)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_bias_cascode.py
"""

import klayout.db as pya
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def build():
    print('=== Building BIAS Cascode (compact) ===')

    with open(os.path.join(LAYOUT_DIR, 'placement.json')) as f:
        placement = json.load(f)

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('bias_cascode')

    # Column layout: 4 columns, uniform width based on widest device (mirror 7um)
    # + NW.b1=1.8um gap between columns
    col_width = 7500   # 7um device + 0.5um margin
    nw_gap = 2500      # NW.b1 = 1.8um + margin

    col_center = [col_width // 2]
    for i in range(1, 4):
        col_center.append(col_center[-1] + col_width + nw_gap)
    # Centers at: 3750, 13750, 23750, 33750

    # Y bands: MN at y=0, cascode at y=6000, mirror at y=12000
    mn_y = 0
    cas_y = 5000
    mir_y = 11000

    # Device definitions: (name, col, band_y, search_dx, search_dy)
    # Search widths: must be < 7800nm (min device gap) to avoid capturing neighbors
    # Activ is 2.7um, use 5000nm search width for cascode, 7000nm for mirrors
    devices = [
        # (name, column, target_y, search_width, search_height)
        ('MN_cas_load', 0, mn_y, 5000, 4000),
        ('PM_cas_diode', 0, cas_y, 5000, 4000),
        ('PM_cas1', 1, cas_y, 5000, 4000),
        ('PM_cas2', 2, cas_y, 5000, 4000),
        ('PM_cas3', 3, cas_y, 5000, 4000),
        ('PM_cas_ref', 0, mir_y, 7000, 4000),
        ('PM_mir1', 1, mir_y, 7000, 4000),
        ('PM_mir2', 2, mir_y, 7000, 4000),
        ('PM_mir3', 3, mir_y, 7000, 4000),
    ]

    print('\n--- Extracting and re-placing ---')
    for name, col, target_y, sdx, sdy in devices:
        inst = placement['instances'][name]
        ox = int(inst['x_um'] * 1000)
        oy = int(inst['y_um'] * 1000)

        search = pya.Box(ox - 500, oy - 1000, ox + sdx, oy + sdy)

        # Find actual Activ center for precise alignment
        li_act = src.find_layer(1, 0)
        act_r = pya.Region(src_top.begin_shapes_rec(li_act)) & pya.Region(search)
        act_bb = act_r.bbox()
        dev_center_x = (act_bb.left + act_bb.right) // 2
        new_center_x = col_center[col]
        new_y = target_y
        dx = new_center_x - dev_center_x
        dy = new_y - oy + 1000

        count = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(src_top.begin_shapes_rec(li))
            clipped = region & pya.Region(search)
            for poly in clipped.each():
                shifted = poly.moved(dx, dy)
                cell.shapes(tli).insert(shifted)
                count += 1

        print(f'  {name}: col={col} → cx={new_center_x/1000:.1f} y={new_y/1000:.1f} ({count} shapes)')

    # Add ties
    l_activ = out.layer(1, 0)
    l_m1 = out.layer(8, 0)
    l_cont = out.layer(6, 0)
    l_psd = out.layer(14, 0)

    # ptap for MN_cas_load (NMOS)
    cell.shapes(l_activ).insert(box(3000, -700, 3500, -200))
    cell.shapes(l_m1).insert(box(3000, -700, 3500, -200))
    cell.shapes(l_psd).insert(box(2900, -800, 3600, -100))
    cell.shapes(l_cont).insert(box(3170, -530, 3330, -370))

    # ntap for PMOS (inside NWell, above each column)
    li_nw = out.find_layer(31, 0)
    if li_nw:
        nw_region = pya.Region(cell.begin_shapes_rec(li_nw))
        for poly in nw_region.each():
            b = poly.bbox()
            if b.width() > 2000 and b.height() > 1000:
                nx = (b.left + b.right) // 2 - 250
                ny = b.top + 300
                cell.shapes(l_activ).insert(box(nx, ny, nx+500, ny+500))
                cell.shapes(l_m1).insert(box(nx, ny, nx+500, ny+500))
                cell.shapes(l_cont).insert(box(nx+170, ny+170, nx+330, ny+330))

    # Write
    out_path = os.path.join(OUT_DIR, 'bias_cascode.gds')
    out.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    m1r = pya.Region(cell.begin_shapes_rec(out.find_layer(8, 0)))
    print(f'  Quick DRC: M1.b={m1r.space_check(180).count()} M1.a={m1r.width_check(160).count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
