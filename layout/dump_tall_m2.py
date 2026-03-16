#!/usr/bin/env python3
"""KLayout script: dump all M2 shapes taller than 500nm with exact coordinates.

Run: klayout -n sg13g2 -zz -r dump_tall_m2.py
"""
import pya

GDS = 'output/ptat_vco.gds'
M2_LAYER = 10
M2_DATATYPE = 0
MIN_HEIGHT = 500  # nm — only show shapes taller than this

layout = pya.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m2 = None
for li in layout.layer_indices():
    info = layout.get_info(li)
    if info.layer == M2_LAYER and info.datatype == M2_DATATYPE:
        li_m2 = li
        break

if li_m2 is None:
    print("ERROR: M2 layer not found")
    exit(1)

shapes = []
ri = pya.RecursiveShapeIterator(layout, top, li_m2)
while not ri.at_end():
    shape = ri.shape()
    trans = ri.trans()
    if shape.is_box():
        box = shape.box.transformed(trans)
        shapes.append((box.left, box.bottom, box.right, box.top))
    elif shape.is_polygon():
        bbox = shape.polygon.transformed(trans).bbox()
        shapes.append((bbox.left, bbox.bottom, bbox.right, bbox.top))
    elif shape.is_path():
        bbox = shape.path.polygon().transformed(trans).bbox()
        shapes.append((bbox.left, bbox.bottom, bbox.right, bbox.top))
    ri.next()

# Filter and sort
tall = []
for x1, y1, x2, y2 in shapes:
    w = x2 - x1
    h = y2 - y1
    if h > MIN_HEIGHT:
        tall.append((x1, y1, x2, y2, w, h))

tall.sort(key=lambda s: (s[4], s[5], s[0], s[1]))  # sort by w, h, x, y

print(f"Total M2 shapes: {len(shapes)}")
print(f"Tall M2 shapes (h > {MIN_HEIGHT}nm): {len(tall)}\n")

# Group by size
from collections import defaultdict
by_size = defaultdict(list)
for x1, y1, x2, y2, w, h in tall:
    by_size[(w, h)].append((x1, y1, x2, y2))

print(f"{'Size':>15s}  {'Count':>5s}  Coordinates")
print("-" * 100)
for (w, h), rects in sorted(by_size.items()):
    print(f"{w}x{h}nm  {len(rects):>5d}")
    for x1, y1, x2, y2 in sorted(rects):
        cx = (x1 + x2) // 2
        print(f"  ({x1},{y1})-({x2},{y2})  cx={cx}")
