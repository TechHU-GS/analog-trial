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


def patch_dac_sw():
    """Add Via1+M2 for lat_q and lat_qb gate M1 bars in dac_sw."""
    path = os.path.join(OUT_DIR, 'dac_sw.gds')
    ly = pya.Layout()
    ly.read(path)
    cell = ly.top_cell()

    # lat_q M1 bar: y=5145-5455, x=435-7315. Via1+M2 at left end (x=590, y=5300)
    print('  dac_sw lat_q: adding Via1+M2 at (590, 5300)')
    add_via1_m2(cell, ly, 590, 5300)

    # lat_qb M1 bar: y=4645-4955, x=2625-5045. Via1+M2 at left end (x=2780, y=4800)
    print('  dac_sw lat_qb: adding Via1+M2 at (2780, 4800)')
    add_via1_m2(cell, ly, 2780, 4800)

    ly.write(path)
    print(f'  dac_sw: written to {path}')


def patch_passive(name, description):
    """Add Via1+M2 at all M1 terminals of a passive module."""
    path = os.path.join(OUT_DIR, f'{name}.gds')
    ly = pya.Layout()
    ly.read(path)
    cell = ly.top_cell()

    m1_li = ly.find_layer(8, 0)
    if m1_li is None:
        print(f'  {name}: no M1 found!')
        return

    m1 = pya.Region(cell.begin_shapes_rec(m1_li))
    count = 0
    for p in m1.each():
        b = p.bbox()
        cx = (b.left + b.right) // 2
        cy = (b.bottom + b.top) // 2
        # Skip tiny M1 fragments
        if b.width() < 200 or b.height() < 200:
            continue
        # Check if Via1 already exists here
        v1_li = ly.find_layer(19, 0)
        if v1_li is not None:
            v1 = pya.Region(cell.begin_shapes_rec(v1_li))
            if (v1 & pya.Region(pya.Box(cx-100, cy-100, cx+100, cy+100))).count() > 0:
                continue  # already has Via1
        print(f'  {name} ({description}): adding Via1+M2 at ({cx}, {cy})')
        add_via1_m2(cell, ly, cx, cy)
        count += 1

    ly.write(path)
    print(f'  {name}: {count} pads added, written to {path}')


def patch_comp_inp():
    """Add gate contact + M1 + Via1 + M2 for Mc_inp.G (ota_out) in comp."""
    path = os.path.join(OUT_DIR, 'comp.gds')
    ly = pya.Layout()
    ly.read(path)
    cell = ly.top_cell()

    # Mc_inp.G: gate poly at local x≈3710, band 2 (y≈4-8)
    # Add contact on poly extension ABOVE the device (y≈3500, below existing M2 routing)
    gcx = 3710
    gcy = 3500  # below band 2 gates, above c_tail M2 at y≈1

    # Gate Contact (160x160)
    cont_li = ly.layer(6, 0)
    cell.shapes(cont_li).insert(pya.Box(gcx - 80, gcy - 80, gcx + 80, gcy + 80))

    # M1 pad
    m1_li = ly.layer(8, 0)
    cell.shapes(m1_li).insert(pya.Box(gcx - 185, gcy - 185, gcx + 185, gcy + 185))

    # Via1 + M2
    add_via1_m2(cell, ly, gcx, gcy)

    print(f'  comp Mc_inp.G: gate contact + Via1+M2 at ({gcx}, {gcy})')
    ly.write(path)
    print(f'  comp: written to {path}')


def main():
    print('=== Adding Via1+M2 landing pads ===\n')
    patch_rin()
    patch_dac_sw()
    patch_passive('rdac', 'dac_out terminal')
    patch_passive('rout', 'vptat terminal')
    patch_comp_inp()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
