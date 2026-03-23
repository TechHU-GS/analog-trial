#!/usr/bin/env python3
"""Build passive modules from PCell (not extracted from soilz_bare).

Resistors: rhigh (rptat, rin, rdac), rppd (rout)
Capacitors: cmim (c_fb, cbyp_n, cbyp_p)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_passives_pcell.py
"""
import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

PASSIVES = [
    # (name, pcell_name, params)
    ('rptat',  'rhigh', {'w': 0.5e-6, 'l': 133e-6, 'b': 12, 'm': 1}),
    ('rout',   'rppd',  {'w': 0.5e-6, 'l': 25e-6, 'b': 4, 'm': 1}),
    ('rin',    'rhigh', {'w': 0.5e-6, 'l': 20e-6, 'b': 2, 'm': 1}),
    ('rdac',   'rhigh', {'w': 0.5e-6, 'l': 20e-6, 'b': 2, 'm': 1}),
    ('c_fb',   'cmim',  {'w': 26e-6, 'l': 26e-6, 'm': 1}),
    ('cbyp_n', 'cmim',  {'w': 5e-6, 'l': 5e-6, 'm': 1}),
    ('cbyp_p', 'cmim',  {'w': 5e-6, 'l': 5e-6, 'm': 1}),
]

for name, pcell, params in PASSIVES:
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell(name)
    pc = ly.create_cell(pcell, 'SG13_dev', params)
    if pc is None:
        print(f'  {name}: FAILED to create {pcell} PCell')
        continue
    top.insert(pya.CellInstArray(pc.cell_index(), pya.Trans()))
    bb = top.bbox()
    out = os.path.join(OUT_DIR, f'{name}.gds')
    ly.write(out)
    print(f'  {name:8s} ({pcell:5s}): {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um -> {out}')

print('\n=== Done ===')
