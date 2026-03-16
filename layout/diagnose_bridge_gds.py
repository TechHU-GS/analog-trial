#!/usr/bin/env python3
"""Find the actual GND↔VDD bridge by checking GDS shapes directly.

For every Via2 in the GDS, check if its M3 pad connects to a VDD M3 rail
AND its M2 connects to a GND net (or vice versa).

Strategy: for each merged M3 polygon, check if it has Via2s connecting to
M2 polygons that reach BOTH GND and VDD M3 rails.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_bridge_gds.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)

m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
v1_all = kdb.Region(top.begin_shapes_rec(li_v1))
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))

m2_polys = list(m2_merged.each())
m3_polys = list(m3_merged.each())

# Classify M3 merged polygons
# VDD M3: polygon overlaps with y=81120-84120 or 85620-88620 or 154620-157620 or 176120-179120
# GND M3: polygon overlaps with y=64000-67000 or 68500-71500 or 144500-147500 or 162000-165000
vdd_bands = [(81120,84120), (85620,88620), (154620,157620), (176120,179120)]
gnd_bands = [(64000,67000), (68500,71500), (144500,147500), (162000,165000)]

def classify_m3(poly):
    bb = poly.bbox()
    is_vdd = any(bb.bottom < y2 and bb.top > y1 for y1, y2 in vdd_bands)
    is_gnd = any(bb.bottom < y2 and bb.top > y1 for y1, y2 in gnd_bands)
    # Large chip-wide polygons touching rail bands
    if bb.right - bb.left > 100000:  # >100µm wide = power rail
        if is_vdd and not is_gnd:
            return 'VDD'
        elif is_gnd and not is_vdd:
            return 'GND'
        elif is_vdd and is_gnd:
            return 'BOTH'  # Bridge!
    return 'signal'

# Instead of classifying, directly check:
# For each Via2, find its M3 merged polygon and M2 merged polygon.
# If the M3 polygon is a VDD rail, check if the M2 connects to a GND M3 via another path.
# Too complex — use simpler approach.

# APPROACH: Check if any M2 merged polygon connects (via Via2) to BOTH
# a VDD M3 rail polygon AND a GND M3 polygon.

print("Checking each M2 merged polygon for VDD↔GND bridging...")
print(f"M2 polys: {len(m2_polys)}, M3 polys: {len(m3_polys)}")

# First, identify VDD and GND M3 polygons
vdd_m3_ids = set()
gnd_m3_ids = set()

for i, m3p in enumerate(m3_polys):
    bb = m3p.bbox()
    width = bb.right - bb.left
    if width < 50000:  # Skip small polygons
        continue
    for y1, y2 in vdd_bands:
        if bb.bottom < y2 and bb.top > y1:
            vdd_m3_ids.add(i)
    for y1, y2 in gnd_bands:
        if bb.bottom < y2 and bb.top > y1:
            gnd_m3_ids.add(i)

print(f"VDD M3 rail polygons: {len(vdd_m3_ids)}")
print(f"GND M3 rail polygons: {len(gnd_m3_ids)}")

# Check overlap between VDD and GND M3 sets
both = vdd_m3_ids & gnd_m3_ids
if both:
    print(f"\n*** M3 polygons touching BOTH VDD and GND bands: {len(both)} ***")
    for idx in both:
        bb = m3_polys[idx].bbox()
        print(f"  M3#{idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
else:
    print("\nNo M3 polygon touches both VDD and GND bands.")

# For each M2 polygon, check Via2 connections to M3
bridge_found = False
for m2_idx, m2p in enumerate(m2_polys):
    m2r = kdb.Region(m2p)
    v2_on_m2 = v2_all & m2r
    if v2_on_m2.count() < 2:
        continue

    # Find which M3 polys this M2 connects to via Via2
    connected_m3 = set()
    for v2 in v2_on_m2.each():
        v2b = v2.bbox()
        center = kdb.Box(v2b.left + 20, v2b.bottom + 20,
                        v2b.right - 20, v2b.top - 20)
        probe = kdb.Region(center)
        for i, m3p in enumerate(m3_polys):
            m3r = kdb.Region(m3p)
            if not (m3r & probe).is_empty():
                connected_m3.add(i)
                break

    has_vdd = bool(connected_m3 & vdd_m3_ids)
    has_gnd = bool(connected_m3 & gnd_m3_ids)

    if has_vdd and has_gnd:
        bridge_found = True
        m2b = m2p.bbox()
        print(f"\n*** M2 BRIDGE: ({m2b.left/1e3:.3f},{m2b.bottom/1e3:.3f})-"
              f"({m2b.right/1e3:.3f},{m2b.top/1e3:.3f}) ***")
        print(f"  Via2 count: {v2_on_m2.count()}")
        for v2 in v2_on_m2.each():
            v2b = v2.bbox()
            cx = (v2b.left + v2b.right) / 2e3
            cy = (v2b.top + v2b.bottom) / 2e3
            center = kdb.Box(v2b.left + 20, v2b.bottom + 20,
                            v2b.right - 20, v2b.top - 20)
            probe = kdb.Region(center)
            for i, m3p in enumerate(m3_polys):
                m3r = kdb.Region(m3p)
                if not (m3r & probe).is_empty():
                    m3b = m3p.bbox()
                    net = "VDD" if i in vdd_m3_ids else ("GND" if i in gnd_m3_ids else "signal")
                    print(f"  Via2 ({cx:.3f},{cy:.3f}) → M3#{i} "
                          f"({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                          f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) [{net}]")
                    break

# Also check Via1: M1 polygon connecting to both VDD and GND via Via1
# (less likely but possible)
if not bridge_found:
    print("\nNo M2-level bridge found. Checking M1...")
    m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
    m1_polys = list(m1_merged.each())

    for m1_idx, m1p in enumerate(m1_polys):
        m1r = kdb.Region(m1p)
        v1_on_m1 = v1_all & m1r
        if v1_on_m1.count() < 2:
            continue

        connected_m2 = set()
        for v1 in v1_on_m1.each():
            v1b = v1.bbox()
            center = kdb.Box(v1b.left + 20, v1b.bottom + 20,
                            v1b.right - 20, v1b.top - 20)
            probe = kdb.Region(center)
            for i, m2p in enumerate(m2_polys):
                m2r = kdb.Region(m2p)
                if not (m2r & probe).is_empty():
                    connected_m2.add(i)
                    break

        # Check if any connected M2 reaches both VDD and GND M3
        # This is more complex - skip for now
        # Instead, check if M1 directly connects VDD M2 and GND M2
        # by checking if the M2 polys have Via2 to VDD and GND M3

if not bridge_found:
    print("No direct bridge found via M2. The bridge may be through Via1→M2→Via2.")

print("\n\nDONE.")
