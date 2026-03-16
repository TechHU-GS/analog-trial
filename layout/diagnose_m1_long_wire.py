#!/usr/bin/env python3
"""Investigate the 26µm × 160nm M1 shape causing M1.b violations at y=149.8.
Is it from L-corner extension? From routing? From assembly?"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m1 = layout.layer(8, 0)

# The suspicious shape: [40.165,149.820]-[66.605,149.980] (26440x160nm)
# Search for unmerged shapes that contribute to this area
search = kdb.Box(39000, 149500, 67000, 150200)

print("Unmerged M1 shapes in y=149.5-150.2 µm, x=39-67 µm:")
print("=" * 70)
shapes = []
for si in top.begin_shapes_rec_overlapping(li_m1, search):
    box = si.shape().bbox().transformed(si.trans())
    cell = layout.cell(si.cell_index()).name
    # Only shapes that are within the Y range of interest
    if box.bottom <= 150000 and box.top >= 149700:
        shapes.append((box, cell))
        source = 'TOP' if cell == top.name else cell
        w, h = box.width(), box.height()
        print(f"  {source:15s} [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
              f"[{box.right/1e3:.3f},{box.top/1e3:.3f}] ({w}x{h}nm)")

# Check merged M1 in this area
region = kdb.Region(top.begin_shapes_rec(li_m1))
merged = region.merged()
probe = kdb.Region(kdb.Box(39000, 149700, 67000, 150100))
local_merged = merged & probe
print(f"\nMerged M1 shapes in probe area:")
for p in local_merged.each():
    b = p.bbox()
    print(f"  [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}]"
          f" ({b.width()}x{b.height()}nm)")
    # Check for narrow features
    viols = kdb.Region(p).width_check(160)
    if viols.count() > 0:
        print(f"    >> Has {viols.count()} width violation(s) < 160nm")
        for ep in viols.each():
            e1, e2 = ep.first, ep.second
            gap = abs(e1.p1.y - e2.p1.y) if abs(e1.p1.x - e2.p1.x) < 10 else abs(e1.p1.x - e2.p1.x)
            print(f"       width={gap}nm at ({(e1.p1.x+e2.p1.x)/2e3:.3f},"
                  f"{(e1.p1.y+e2.p1.y)/2e3:.3f})")

# Also check routing.json for M1 wires in this area
print("\n\nRouting M1 segments near y=149.8:")
print("=" * 70)
with open('output/routing.json') as f:
    routing = json.load(f)

M1_LYR = 0
for net_type in ['signal_routes', 'pre_routes']:
    for net, route in routing.get(net_type, {}).items():
        for seg in route.get('segments', []):
            if len(seg) < 5:
                continue
            if seg[4] != M1_LYR:
                continue
            x1, y1, x2, y2 = seg[:4]
            if min(y1, y2) <= 150000 and max(y1, y2) >= 149500:
                if min(x1, x2) <= 67000 and max(x1, x2) >= 39000:
                    print(f"  {net_type}/{net}: ({x1},{y1})-({x2},{y2})")

# Check: is the 160nm height from L-corner extensions?
# L-corner extensions create M1 fills of size HW × HW = 150×150nm
# If two fill shapes overlap, they could create a 160nm strip
print("\n\nM1 shapes exactly 160nm tall or wide (potential L-corner artifacts):")
count = 0
for si in top.begin_shapes_rec(li_m1):
    box = si.shape().bbox().transformed(si.trans())
    cell = layout.cell(si.cell_index()).name
    if cell == top.name and (box.height() == 160 or box.width() == 160):
        count += 1
        if count <= 20:
            print(f"  [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
                  f"[{box.right/1e3:.3f},{box.top/1e3:.3f}]"
                  f" ({box.width()}x{box.height()}nm)")
if count > 20:
    print(f"  ... and {count-20} more")
print(f"Total: {count} shapes with 160nm dimension")
