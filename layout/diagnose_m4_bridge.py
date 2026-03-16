#!/usr/bin/env python3
"""Find exactly which Via3 on the shared M4 polygon bridges VDD and GND M3.

The flood-fill found ONE shared M4 polygon at (45.710,84.660)-(50.950,89.050).
This script traces all Via3 on it and identifies which M3 polygons they connect to.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m4_bridge.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m3 = layout.layer(30, 0)
li_m4 = layout.layer(50, 0)
li_v3 = layout.layer(49, 0)

m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
m4_merged = kdb.Region(top.begin_shapes_rec(li_m4)).merged()
v3_all = kdb.Region(top.begin_shapes_rec(li_v3))

m3_polys = list(m3_merged.each())

# Load routing for rail identification
with open('output/routing.json') as f:
    routing = json.load(f)

rails = routing.get('power', {}).get('rails', {})
print("Power rails:")
for rn, rl in sorted(rails.items()):
    net = rl.get('net', rn)
    y = rl['y']
    hw = rl['width'] // 2
    print(f"  {rn:12s} net={net:5s}  y={y/1e3:.3f}µm  [{(y-hw)/1e3:.3f},{(y+hw)/1e3:.3f}]")

# Find the shared M4 polygon
m4_probe = kdb.Box(45710, 84660, 50950, 89050)

print(f"\n{'='*70}")
print("M4 polygon at (45.710,84.660)-(50.950,89.050)")
print(f"{'='*70}")

for m4p in m4_merged.each():
    m4r = kdb.Region(m4p)
    if (m4r & kdb.Region(m4_probe)).is_empty():
        continue

    bb = m4p.bbox()
    print(f"\nM4: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={m4p.area()/1e6:.1f}µm²")

    # Find ALL Via3 on this M4
    v3_on_m4 = v3_all & m4r
    print(f"\nVia3 on this M4: {v3_on_m4.count()}")

    for i, v3 in enumerate(v3_on_m4.each()):
        v3b = v3.bbox()
        cx = (v3b.left + v3b.right) / 2e3
        cy = (v3b.top + v3b.bottom) / 2e3
        print(f"\n  V3#{i}: ({v3b.left/1e3:.3f},{v3b.bottom/1e3:.3f})-"
              f"({v3b.right/1e3:.3f},{v3b.top/1e3:.3f})  center=({cx:.3f},{cy:.3f})")

        # Find M3 polygon at this Via3
        v3_center = kdb.Box(v3b.left + 20, v3b.bottom + 20,
                           v3b.right - 20, v3b.top - 20)
        v3_probe = kdb.Region(v3_center)
        for m3p in m3_polys:
            m3r = kdb.Region(m3p)
            if not (m3r & v3_probe).is_empty():
                m3b = m3p.bbox()
                area = m3p.area() / 1e6
                # Check if this is a power rail
                is_rail = ""
                for rn, rl in rails.items():
                    rnet = rl.get('net', rn)
                    rh = rl['width'] // 2
                    ry1 = rl['y'] - rh
                    ry2 = rl['y'] + rh
                    if (m3b.bottom <= ry2 and m3b.top >= ry1 and
                            m3b.right - m3b.left > 50000):  # chip-wide
                        is_rail = f" ← RAIL {rn} ({rnet})"
                        break

                # Check if it's a local signal M3
                if not is_rail and area < 50:
                    is_rail = " ← LOCAL SIGNAL M3"

                print(f"    → M3: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                      f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) "
                      f"area={area:.1f}µm²{is_rail}")
                break

# ─── Also check: unmerged M4 shapes in the region ───
print(f"\n{'='*70}")
print("UNMERGED M4 shapes in OTA region (x=42-55, y=80-95)")
print(f"{'='*70}")

m4_raw = kdb.Region(top.begin_shapes_rec(li_m4))
scan = kdb.Region(kdb.Box(42000, 80000, 55000, 95000))
m4_raw_scan = m4_raw & scan

shapes = []
for poly in m4_raw_scan.each():
    pb = poly.bbox()
    w = pb.right - pb.left
    h = pb.top - pb.bottom
    orient = "H" if w > h else ("V" if h > w else "□")
    shapes.append((pb.left, pb.bottom, pb.right, pb.top, w, h, orient))

shapes.sort(key=lambda s: (s[0], s[1]))
for i, (xl, yb, xr, yt, w, h, orient) in enumerate(shapes):
    print(f"  M4raw#{i}: ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})  "
          f"{w}x{h}nm {orient}")

# ─── Check unmerged M3 in OTA region near the shared M3 ───
print(f"\n{'='*70}")
print("UNMERGED M3 shapes near shared M3 at (44.93,84.36)-(47.76,85.38)")
print(f"{'='*70}")

m3_raw = kdb.Region(top.begin_shapes_rec(li_m3))
m3_scan = kdb.Region(kdb.Box(44000, 83000, 50000, 90000))
m3_raw_scan = m3_raw & m3_scan

m3_shapes = []
for poly in m3_raw_scan.each():
    pb = poly.bbox()
    w = pb.right - pb.left
    h = pb.top - pb.bottom
    orient = "H" if w > h else ("V" if h > w else "□")
    m3_shapes.append((pb.left, pb.bottom, pb.right, pb.top, w, h, orient))

m3_shapes.sort(key=lambda s: (s[1], s[0]))
for i, (xl, yb, xr, yt, w, h, orient) in enumerate(m3_shapes):
    # Check if it's in the rail Y range
    in_rail = ""
    for rn, rl in rails.items():
        rnet = rl.get('net', rn)
        rh = rl['width'] // 2
        ry1 = rl['y'] - rh
        ry2 = rl['y'] + rh
        if yb < ry2 and yt > ry1:
            in_rail = f" ← in {rn}({rnet}) range"
            break
    print(f"  M3raw#{i}: ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})  "
          f"{w}x{h}nm {orient}{in_rail}")

print("\n\nDONE.")
