#!/usr/bin/env python3
"""Extract all 7 passive devices from soilz_bare.gds.

Each passive is extracted as a separate GDS file.
No routing needed — just two terminals (PLUS/MINUS).

Devices:
    Rptat:  rhigh_ptat    9.1×135.5um  (PTAT resistor)
    Rout:   rhigh_rout    1.6×101.3um  (output resistor)
    Rin:    rhigh_200k   22.2×2.3um   (input resistor)
    Rdac:   rhigh_200k   22.2×2.3um   (DAC resistor)
    C_fb:   cap_cmim_1p  27.2×27.2um  (feedback cap)
    Cbyp_n: cap_cmim     6.2×6.2um    (bypass cap)
    Cbyp_p: cap_cmim     6.2×6.2um    (bypass cap)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_passives.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# (name, abs_x, abs_y, w, h, margin)
PASSIVES = [
    # Coordinates from marker-layer analysis (seed bbox + contacts + 500nm margin)
    # (name, search_x1, search_y1, search_w, search_h, origin_x_offset)
    # Using absolute search boxes, not placement+margin
]

# Precise search boxes based on actual PCell extent (marker + contacts)
PASSIVES_V2 = [
    # (name, search_x1, search_y1, search_x2, search_y2)
    ('rptat',  10770, 14750, 32000, 152610),
    ('rout',   10700, 14750, 18500, 125500),
    ('rin',    18500, 52500, 32040, 71640),
    ('rdac',   49600, 58750, 59060, 75500),  # extended: Contact at x=50.1, Res to y=75
    ('c_fb',   81500, 59500, 113920, 87700),
    ('cbyp_n', 70325, 145500, 78700, 152700),
    ('cbyp_p', 59500, 138500, 66700, 145700),
]


def build():
    print('=== Extracting passive devices ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    for name, sx1, sy1, sx2, sy2 in PASSIVES_V2:
        out = pya.Layout()
        out.dbu = 0.001
        cell = out.create_cell(name)

        search = pya.Box(sx1, sy1, sx2, sy2)

        count = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(src_top.begin_shapes_rec(li))
            for poly in (region & pya.Region(search)).each():
                cell.shapes(tli).insert(poly.moved(-sx1, -sy1))
                count += 1

        out_path = os.path.join(OUT_DIR, f'{name}.gds')
        out.write(out_path)

        bb = cell.bbox()
        print(f'  {name:8s}: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um, {count} shapes')

    print('\n=== Done ===')


if __name__ == '__main__':
    build()
