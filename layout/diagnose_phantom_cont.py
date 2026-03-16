#!/usr/bin/env python3
"""Find the source of 160×160 Cont shapes at resistor terminals.

The CntB.b2 violations come from 160×160 Cont_SQ shapes that are 70nm
from 360×160 ContBar shapes at resistor PCell terminals.
The PCells only have 360×160 Conts. Where do the 160×160 ones come from?

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_phantom_cont.py
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()
li_cont = layout.layer(6, 0)

# The 4 Cont_SQ shapes from the violations (in top-cell nm coords)
viol_sq = [
    (10370, 137020, 10530, 137180),  # rppd terminal
    (56870, 59020, 57030, 59180),    # rhigh terminal
    (25130, 59020, 25290, 59180),    # rhigh terminal
    (15370, 15020, 15530, 15180),    # rhigh$1 terminal
]

# Check if these are TOP cell shapes
print("=" * 80)
print("Checking if violation Cont_SQ shapes are in TOP cell")
print("=" * 80)
for vx1, vy1, vx2, vy2 in viol_sq:
    found_top = False
    for si in top.shapes(li_cont).each():
        bb = si.bbox()
        if (bb.left == vx1 and bb.bottom == vy1 and
            bb.right == vx2 and bb.top == vy2):
            found_top = True
            break
    print(f"  ({vx1},{vy1};{vx2},{vy2}): TOP cell = {found_top}")

# Check subcells
for vx1, vy1, vx2, vy2 in viol_sq:
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(li_cont).each():
            bb = si.bbox().transformed(trans)
            if (bb.left == vx1 and bb.bottom == vy1 and
                bb.right == vx2 and bb.top == vy2):
                print(f"  ({vx1},{vy1};{vx2},{vy2}): from subcell {cell.name} at ({trans.disp.x},{trans.disp.y})")

# Also check ALL Cont shapes that are exactly 160×160 in the TOP cell only
print("\n" + "=" * 80)
print("ALL 160×160 Cont shapes in TOP cell (not subcells)")
print("=" * 80)
top_sq_count = 0
for si in top.shapes(li_cont).each():
    bb = si.bbox()
    if bb.width() == 160 and bb.height() == 160:
        top_sq_count += 1
        if top_sq_count <= 20:
            print(f"  ({bb.left},{bb.bottom};{bb.right},{bb.top})")
print(f"Total 160×160 Cont in TOP: {top_sq_count}")

# Count ALL Cont shapes in TOP cell (any size)
print("\n" + "=" * 80)
print("ALL Cont shapes in TOP cell (any size)")
print("=" * 80)
from collections import Counter
size_counter = Counter()
for si in top.shapes(li_cont).each():
    bb = si.bbox()
    size_counter[(bb.width(), bb.height())] += 1
for (w, h), count in sorted(size_counter.items()):
    print(f"  {w}×{h}: {count}")
print(f"Total Cont in TOP: {sum(size_counter.values())}")

# Check which 160×160 TOP Cont shapes are near resistor positions
print("\n" + "=" * 80)
print("160×160 TOP Cont shapes near resistor cells")
print("=" * 80)
res_origins = [
    ('rhigh$1', 15200, 15610),
    ('rhigh', 56700, 59610),
    ('rhigh', 24960, 59610),
    ('rppd', 10200, 137610),
]
for rname, rx, ry in res_origins:
    probe = kdb.Box(rx - 2000, ry - 2000, rx + 15000, ry + 150000)
    near = []
    for si in top.shapes(li_cont).each():
        bb = si.bbox()
        if bb.width() == 160 and bb.height() == 160 and probe.overlaps(bb):
            near.append(bb)
    if near:
        print(f"\n  {rname} at ({rx},{ry}): {len(near)} nearby 160×160 Cont")
        for bb in near[:5]:
            dx = bb.left - rx
            dy = bb.bottom - ry
            print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) offset=({dx},{dy})")
