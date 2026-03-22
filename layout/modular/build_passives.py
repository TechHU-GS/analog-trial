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
    ('rptat',  15000, 15000,  9060, 135540, 1500),
    ('rout',   11000, 15000,  1580, 101310, 1500),
    ('rin',    24760, 59000, 22160,   2260, 1500),
    ('rdac',   56500, 59000, 22160,   2260, 1500),
    ('c_fb',   82000, 60000, 27200,  27200, 1500),
    ('cbyp_n', 72000, 146000, 6200,   6200, 900),  # tight left margin to avoid neighbor at x=71055
    ('cbyp_p', 60000, 139000, 6200,   6200, 1500),
]


def build():
    print('=== Extracting passive devices ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    for name, px, py, pw, ph, margin in PASSIVES:
        out = pya.Layout()
        out.dbu = 0.001
        cell = out.create_cell(name)

        search = pya.Box(px - margin, py - margin, px + pw + margin, py + ph + margin)

        count = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(src_top.begin_shapes_rec(li))
            for poly in (region & pya.Region(search)).each():
                cell.shapes(tli).insert(poly.moved(-px, -py))
                count += 1

        out_path = os.path.join(OUT_DIR, f'{name}.gds')
        out.write(out_path)

        bb = cell.bbox()
        print(f'  {name:8s}: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um, {count} shapes')

    print('\n=== Done ===')


if __name__ == '__main__':
    build()
