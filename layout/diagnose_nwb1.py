#!/usr/bin/env python3
"""Diagnose NW.b1 violations: find all NWell pairs with diagonal gap < 1800nm.

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_nwb1.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

NW_B1 = 1800  # NW.b1 minimum NWell spacing (nm)

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()
li_nw = layout.layer(31, 0)

# Collect ALL NWell shapes with source info
nw_shapes = []

# TOP cell shapes
for si in top.shapes(li_nw).each():
    bb = si.bbox()
    nw_shapes.append(('TOP', bb))

# PCell instance shapes
for inst in top.each_inst():
    cell = inst.cell
    for si in cell.shapes(li_nw).each():
        shape_box = si.bbox().transformed(inst.trans)
        nw_shapes.append((cell.name, shape_box))

# De-duplicate (same bbox from duplicate TOP shapes)
seen = set()
unique = []
for src, bb in nw_shapes:
    key = (src, bb.left, bb.bottom, bb.right, bb.top)
    if key not in seen:
        seen.add(key)
        unique.append((src, bb))
nw_shapes = unique

print(f'Total unique NWell shapes: {len(nw_shapes)}')

# Find all pairs with gap < NW.b1 that are NOT overlapping
violations = []
for i in range(len(nw_shapes)):
    src1, b1 = nw_shapes[i]
    for j in range(i + 1, len(nw_shapes)):
        src2, b2 = nw_shapes[j]

        # X and Y gaps (negative = overlap)
        x_gap = max(b2.left - b1.right, b1.left - b2.right)
        y_gap = max(b2.bottom - b1.top, b1.bottom - b2.top)

        # Skip if overlapping in both dimensions
        if x_gap <= 0 and y_gap <= 0:
            continue

        # Compute minimum distance
        if x_gap <= 0:
            # Y-adjacent (has X overlap)
            dist = max(y_gap, 0)
        elif y_gap <= 0:
            # X-adjacent (has Y overlap)
            dist = max(x_gap, 0)
        else:
            # Diagonal (no overlap in either dimension)
            import math
            dist = math.sqrt(x_gap**2 + y_gap**2)

        if 0 < dist < NW_B1:
            gap_type = 'diagonal' if x_gap > 0 and y_gap > 0 else ('X-adj' if y_gap <= 0 else 'Y-adj')
            violations.append({
                'src1': src1, 'b1': b1,
                'src2': src2, 'b2': b2,
                'x_gap': x_gap, 'y_gap': y_gap,
                'dist': dist, 'type': gap_type,
            })

print(f'\nNWell pairs with gap < {NW_B1}nm (potential NW.b1 violations):')
print(f'  Total: {len(violations)}')
for v in sorted(violations, key=lambda v: v['type']):
    b1 = v['b1']
    b2 = v['b2']
    print(f"\n  {v['type']}: dist={v['dist']:.0f}nm (x_gap={v['x_gap']}, y_gap={v['y_gap']})")
    print(f"    {v['src1']}: ({b1.left},{b1.bottom};{b1.right},{b1.top}) {b1.width()}x{b1.height()}")
    print(f"    {v['src2']}: ({b2.left},{b2.bottom};{b2.right},{b2.top}) {b2.width()}x{b2.height()}")

# Count by type
from collections import Counter
type_counts = Counter(v['type'] for v in violations)
print(f'\nBy type: {dict(type_counts)}')
