#!/usr/bin/env python3
"""Find the exact Via2 that connects mid_p M2 to a power M3 rail.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_via2_short.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)
li_v2 = layout.layer(29, 0)

m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))
m3_polys = list(m3_merged.each())

# Find the mid_p M2 polygon
midp_m2_probe = kdb.Region(kdb.Box(44900, 87300, 45200, 87600))
midp_m2 = None
for poly in m2_merged.each():
    pr = kdb.Region(poly)
    if not (pr & midp_m2_probe).is_empty():
        midp_m2 = poly
        break

if midp_m2 is None:
    print("ERROR: Could not find mid_p M2 polygon")
    sys.exit(1)

bb = midp_m2.bbox()
print(f"mid_p M2 polygon: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
print(f"  Area: {midp_m2.area()/1e6:.2f} µm²")

# Find ALL Via2 on this M2 polygon
m2r = kdb.Region(midp_m2)
v2_on_m2 = v2_all & m2r

print(f"\nVia2 on mid_p M2: {v2_on_m2.count()}")
for i, v2 in enumerate(v2_on_m2.each()):
    v2b = v2.bbox()
    cx = (v2b.left + v2b.right) / 2e3
    cy = (v2b.top + v2b.bottom) / 2e3
    print(f"\n  V2#{i}: ({v2b.left/1e3:.3f},{v2b.bottom/1e3:.3f})-({v2b.right/1e3:.3f},{v2b.top/1e3:.3f})"
          f"  center=({cx:.3f},{cy:.3f})µm")

    # Find which M3 polygon this V2 connects to
    v2_center = kdb.Box(v2b.left + 20, v2b.bottom + 20, v2b.right - 20, v2b.top - 20)
    v2_probe = kdb.Region(v2_center)
    for m3p in m3_polys:
        m3r = kdb.Region(m3p)
        if not (m3r & v2_probe).is_empty():
            m3b = m3p.bbox()
            m3_area = m3p.area() / 1e6
            if m3_area > 100:
                print(f"    → M3 POWER RAIL: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                      f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) area={m3_area:.1f}µm²")
                print(f"    *** THIS VIA2 CREATES THE mid_p ↔ POWER MERGER! ***")
            else:
                print(f"    → M3 local: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                      f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) area={m3_area:.1f}µm²")

# ─── Show all M2 shapes (unmerged) that form this polygon ───
print(f"\n{'=' * 70}")
print("UNMERGED M2 shapes that form the mid_p M2 polygon")
print(f"{'=' * 70}")

m2_raw = kdb.Region(top.begin_shapes_rec(li_m2))
m2_raw_in_bbox = m2_raw & kdb.Region(kdb.Box(bb.left - 100, bb.bottom - 100,
                                              bb.right + 100, bb.top + 100))

shapes = []
for poly in m2_raw_in_bbox.each():
    pb = poly.bbox()
    # Check if this raw shape overlaps the merged polygon
    if not (kdb.Region(poly) & m2r).is_empty():
        w = pb.right - pb.left
        h = pb.top - pb.bottom
        orient = "H" if w > h else ("V" if h > w else "□")
        shapes.append((pb.left, pb.bottom, pb.right, pb.top, w, h, orient))

shapes.sort(key=lambda s: (s[1], s[0]))
for i, (xl, yb, xr, yt, w, h, orient) in enumerate(shapes):
    print(f"  M2raw#{i:2d}: ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})  "
          f"{w:5d}x{h:5d}nm {orient}")

# ─── Check M3 labels to identify which M3 rail is VDD vs GND ───
print(f"\n{'=' * 70}")
print("M3 LABELS (layer 30,25)")
print(f"{'=' * 70}")

li_m3_lbl = layout.layer(30, 25)
for shape in top.begin_shapes_rec(li_m3_lbl):
    s = shape.shape()
    if s.is_text():
        t = s.text
        pos = t.trans * kdb.Point(0, 0)
        print(f"  M3 label '{t.string}' at ({pos.x/1e3:.3f},{pos.y/1e3:.3f})µm")

# Also check layer 30,1
li_m3_lbl2 = layout.layer(30, 1)
for shape in top.begin_shapes_rec(li_m3_lbl2):
    s = shape.shape()
    if s.is_text():
        t = s.text
        pos = t.trans * kdb.Point(0, 0)
        print(f"  M3 label(30,1) '{t.string}' at ({pos.x/1e3:.3f},{pos.y/1e3:.3f})µm")

# ─── What net does routing.json say is at the Via2 position? ───
print(f"\n{'=' * 70}")
print("ROUTING.JSON context for Via2 positions")
print(f"{'=' * 70}")

with open('output/routing.json') as f:
    routing = json.load(f)

# Check power rails
for rail_name, rail in routing.get('power', {}).get('rails', {}).items():
    rail_y = rail['y']
    rail_w = rail.get('width', 0)
    rail_net = rail.get('net', rail_name)
    ry1 = rail_y - rail_w // 2
    ry2 = rail_y + rail_w // 2
    print(f"  Rail {rail_name:12s} net={rail_net:8s}  y={rail_y/1e3:.3f}µm "
          f"  range=[{ry1/1e3:.3f},{ry2/1e3:.3f}]µm  width={rail_w}nm")

# Check mid_p route segments
mid_p_route = routing.get('signal_routes', {}).get('mid_p', {})
if mid_p_route:
    print(f"\n  mid_p route segments:")
    for seg in mid_p_route.get('segments', []):
        if len(seg) >= 5:
            x1, y1, x2, y2, code = seg[:5]
            codes = {-1: 'Via1', 0: 'M1', 1: 'M2', -2: 'Via2', 2: 'M3', -3: 'Via3', 3: 'M4'}
            print(f"    ({x1/1e3:.3f},{y1/1e3:.3f})-({x2/1e3:.3f},{y2/1e3:.3f}) layer={codes.get(code, code)}")

print("\n\nDONE.")
