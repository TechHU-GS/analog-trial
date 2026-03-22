#!/usr/bin/env python3
"""Add Via1+M2 landing pads to modules that need them for inter-module routing.

Modules like rin (passive) only have M1 terminals. This script adds
Via1+M2 on top of existing M1 pads so Via2→M3 routing can connect.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/add_m2_pads.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

VIA1_SZ = 190
M1_ENC = 90   # M1 enclosure of Via1
M2_ENC = 145  # M2 enclosure of Via1 (safe)


def add_via1_m2(cell, layout, cx, cy):
    """Add Via1 + M2 pad centered at (cx, cy). M1 pad assumed already present."""
    v1_li = layout.layer(19, 0)
    m1_li = layout.layer(8, 0)
    m2_li = layout.layer(10, 0)

    hs = VIA1_SZ // 2  # 95
    # Via1
    cell.shapes(v1_li).insert(pya.Box(cx - hs, cy - hs, cx + hs, cy + hs))
    # M1 pad (ensure enclosure)
    m1_hs = hs + M1_ENC  # 185
    cell.shapes(m1_li).insert(pya.Box(cx - m1_hs, cy - m1_hs, cx + m1_hs, cy + m1_hs))
    # M2 pad
    m2_hs = hs + M2_ENC  # 240
    cell.shapes(m2_li).insert(pya.Box(cx - m2_hs, cy - m2_hs, cx + m2_hs, cy + m2_hs))


def patch_rin():
    """Add Via1+M2 at rin's M1 terminal."""
    path = os.path.join(OUT_DIR, 'rin.gds')
    ly = pya.Layout()
    ly.read(path)
    cell = ly.top_cell()

    # rin has 1 M1 terminal at (9480,9700)-(9940,9960), center (9710, 9830)
    m1_li = ly.find_layer(8, 0)
    m1 = pya.Region(cell.begin_shapes_rec(m1_li))
    if m1.count() == 0:
        print('  rin: no M1 found!')
        return

    # Find M1 center
    for p in m1.each():
        b = p.bbox()
        cx = (b.left + b.right) // 2
        cy = (b.bottom + b.top) // 2
        print(f'  rin: adding Via1+M2 at ({cx}, {cy})')
        add_via1_m2(cell, ly, cx, cy)

    ly.write(path)
    print(f'  rin: written to {path}')


def main():
    print('=== Adding Via1+M2 landing pads ===\n')
    patch_rin()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
