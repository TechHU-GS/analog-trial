#!/usr/bin/env python3
"""KLayout script: dump M3 shapes near M3.b DRC violation locations.

Run: klayout -n sg13g2 -zz -r dump_m3_near_viols.py
"""
import pya

GDS = 'output/ptat_vco.gds'
M3_LAYER = 30
M3_DATATYPE = 0

# Violation locations from DRC edge-pairs (x_nm, y_nm, label)
VIOLS = [
    (100300, 215608, "V1: BUF_I_p vs BUF_I_n vbar"),
    (100350, 251695, "V2: BUF_I_n v2pad area"),
    (100350, 179520, "V3: rail area"),
    (72000, 247950, "V4/V5: div16_Q vs ref_Q"),
    (48955, 143830, "V6: PM_pdiode same-net"),
    (184400, 170350, "V7/V9: vco5 vs vco4"),
    (84928, 179520, "V8: INV_VCO_p same-net"),
    (43300, 131650, "V10/V11: lat_q vs lat_qb"),
]

RADIUS = 1000  # nm search radius

layout = pya.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m3 = None
for li in layout.layer_indices():
    info = layout.get_info(li)
    if info.layer == M3_LAYER and info.datatype == M3_DATATYPE:
        li_m3 = li
        break

if li_m3 is None:
    print("ERROR: M3 layer not found")
    exit(1)

# Collect all M3 shapes
all_m3 = []
ri = pya.RecursiveShapeIterator(layout, top, li_m3)
while not ri.at_end():
    shape = ri.shape()
    trans = ri.trans()
    if shape.is_box():
        box = shape.box.transformed(trans)
        all_m3.append((box.left, box.bottom, box.right, box.top))
    elif shape.is_polygon():
        bbox = shape.polygon.transformed(trans).bbox()
        all_m3.append((bbox.left, bbox.bottom, bbox.right, bbox.top))
    elif shape.is_path():
        bbox = shape.path.polygon().transformed(trans).bbox()
        all_m3.append((bbox.left, bbox.bottom, bbox.right, bbox.top))
    ri.next()

print(f"Total M3 shapes in GDS: {len(all_m3)}")

for vx, vy, label in VIOLS:
    print(f"\n{'='*80}")
    print(f"{label} @ ({vx},{vy})")
    print(f"{'='*80}")

    nearby = []
    for x1, y1, x2, y2 in all_m3:
        # Check if shape is within RADIUS of violation point
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        # Check if bbox is near the point
        dx = max(x1 - vx, vx - x2, 0)
        dy = max(y1 - vy, vy - y2, 0)
        if dx <= RADIUS and dy <= RADIUS:
            w = x2 - x1
            h = y2 - y1
            nearby.append((x1, y1, x2, y2, w, h))

    nearby.sort(key=lambda s: (s[0], s[1]))
    print(f"  M3 shapes within {RADIUS}nm: {len(nearby)}")
    for x1, y1, x2, y2, w, h in nearby:
        print(f"    ({x1},{y1})-({x2},{y2})  {w}x{h}nm  "
              f"cx={x1+w//2}")
