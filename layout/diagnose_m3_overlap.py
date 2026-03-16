#!/usr/bin/env python3
"""Find M3 shapes that bridge GND and VDD by overlapping with power rails.

Specifically: check if any non-rail M3 shape overlaps with BOTH a VDD M3 rail
and a GND M3 polygon (M3 vbar segment or jog bar).

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m3_overlap.py
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

with open('output/routing.json') as f:
    routing = json.load(f)

rails = routing.get('power', {}).get('rails', {})

# Classify rails
vdd_rails = []
gnd_rails = []
for rn, rl in rails.items():
    net = rl.get('net', rn)
    rh = rl['width'] // 2
    ry1 = rl['y'] - rh
    ry2 = rl['y'] + rh
    entry = (rn, net, rl['y'], ry1, ry2)
    if net == 'vdd':
        vdd_rails.append(entry)
    else:
        gnd_rails.append(entry)

print("VDD rails:", [(r[0], r[3]/1e3, r[4]/1e3) for r in vdd_rails])
print("GND rails:", [(r[0], r[3]/1e3, r[4]/1e3) for r in gnd_rails])

# Get all M3 raw shapes
m3_raw = kdb.Region(top.begin_shapes_rec(li_m3))
m3_merged = m3_raw.merged()

# Build rail regions
vdd_m3_region = kdb.Region()
for rn, net, y, y1, y2 in vdd_rails:
    vdd_m3_region.insert(kdb.Box(0, y1, 200000, y2))
vdd_m3_region = vdd_m3_region.merged()

gnd_m3_region = kdb.Region()
for rn, net, y, y1, y2 in gnd_rails:
    gnd_m3_region.insert(kdb.Box(0, y1, 200000, y2))
gnd_m3_region = gnd_m3_region.merged()

# Find non-rail M3 shapes that overlap BOTH VDD and GND rail regions
print(f"\n{'='*70}")
print("Check: M3 shapes overlapping BOTH VDD and GND rail Y ranges")
print(f"{'='*70}")

for poly in m3_raw.each():
    bb = poly.bbox()
    pr = kdb.Region(poly)
    in_vdd = not (pr & vdd_m3_region).is_empty()
    in_gnd = not (pr & gnd_m3_region).is_empty()
    if in_vdd and in_gnd:
        area = poly.area() / 1e6
        print(f"  BOTH: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.2f}µm²")

# More detailed: find non-rail M3 merged polygons that connect VDD M3 to GND M3
# via shared merged polygon
print(f"\n{'='*70}")
print("Check: MERGED M3 polygons touching BOTH VDD and GND M3 rails")
print(f"{'='*70}")

m3_polys = list(m3_merged.each())
for poly in m3_polys:
    bb = poly.bbox()
    pr = kdb.Region(poly)
    area = poly.area() / 1e6

    # Check if this merged polygon overlaps BOTH VDD and GND rail bands
    touches_vdd = not (pr & vdd_m3_region).is_empty()
    touches_gnd = not (pr & gnd_m3_region).is_empty()

    if touches_vdd and touches_gnd and area < 500:
        # Skip chip-wide power rail polygons (they touch everything)
        print(f"\n  MERGED M3 touches BOTH:")
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.1f}µm²")

        # Show which VDD rails
        for rn, net, y, y1, y2 in vdd_rails:
            rail_probe = kdb.Region(kdb.Box(bb.left, y1, bb.right, y2))
            if not (pr & rail_probe).is_empty():
                print(f"    touches VDD rail: {rn} y=[{y1/1e3:.3f},{y2/1e3:.3f}]")

        # Show which GND rails
        for rn, net, y, y1, y2 in gnd_rails:
            rail_probe = kdb.Region(kdb.Box(bb.left, y1, bb.right, y2))
            if not (pr & rail_probe).is_empty():
                print(f"    touches GND rail: {rn} y=[{y1/1e3:.3f},{y2/1e3:.3f}]")

# Direct approach: for each GND M3 vbar (200nm wide, vertical),
# check if it overlaps with VDD M3 rail region
print(f"\n{'='*70}")
print("Check: M3 vbar shapes (200nm wide) overlapping VDD M3 rail area")
print(f"{'='*70}")

for poly in m3_raw.each():
    bb = poly.bbox()
    w = bb.right - bb.left
    h = bb.top - bb.bottom
    if w != 200:  # Not a 200nm vbar
        continue
    pr = kdb.Region(poly)
    if not (pr & vdd_m3_region).is_empty():
        print(f"  M3 vbar (200nm): ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})  {h}nm tall")
        # Which VDD rail?
        for rn, net, y, y1, y2 in vdd_rails:
            rail_probe = kdb.Region(kdb.Box(bb.left, y1, bb.right, y2))
            if not (pr & rail_probe).is_empty():
                print(f"    overlaps VDD rail: {rn} [{y1/1e3:.3f},{y2/1e3:.3f}]")

# Check M2 shapes: any M2 connected to both VDD Via2 and GND Via2?
print(f"\n{'='*70}")
print("Check: M2 underpasses (200nm wide) in VDD rail Y range")
print(f"{'='*70}")

m2_raw = kdb.Region(top.begin_shapes_rec(li_m2))
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))

for poly in m2_raw.each():
    bb = poly.bbox()
    w = bb.right - bb.left
    h = bb.top - bb.bottom
    if w != 200 or h < 2000:  # Not an underpass (200nm wide, tall)
        continue
    pr = kdb.Region(poly)
    if not (pr & vdd_m3_region).is_empty():
        # This M2 underpass Y range overlaps a VDD M3 rail
        v2_on = v2_all & pr
        if v2_on.count() >= 2:
            print(f"\n  M2 underpass: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
            for v2 in v2_on.each():
                v2b = v2.bbox()
                cx = (v2b.left + v2b.right) / 2e3
                cy = (v2b.top + v2b.bottom) / 2e3
                # Check which M3 this Via2 connects to
                v2_probe = kdb.Region(kdb.Box(v2b.left + 20, v2b.bottom + 20,
                                              v2b.right - 20, v2b.top - 20))
                in_vdd_rail = not (v2_probe & vdd_m3_region).is_empty()
                in_gnd_rail = not (v2_probe & gnd_m3_region).is_empty()
                print(f"    Via2 center=({cx:.3f},{cy:.3f})  "
                      f"in_VDD_rail={in_vdd_rail}  in_GND_rail={in_gnd_rail}")

print("\n\nDONE.")
