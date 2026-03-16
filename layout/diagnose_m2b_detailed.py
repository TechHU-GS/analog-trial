#!/usr/bin/env python3
"""Detailed M2.b diagnostic: for each violation, identify the two M2 shapes."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
M2 = (10, 0)
M2_MIN_S = 210  # nm

layout = kdb.Layout()
layout.read(GDS)
cell = layout.top_cell()
li_m2 = layout.layer(*M2)

# Collect all M2 shapes
region = kdb.Region(cell.begin_shapes_rec(li_m2))
print(f"Total M2 polygons (before merge): {region.count()}")

# Run space check
violations = region.space_check(M2_MIN_S)
print(f"M2 space violations (< {M2_MIN_S}nm): {violations.count()}")

# Merge to get same-net shapes combined
merged = region.merged()
violations_merged = merged.space_check(M2_MIN_S)
print(f"M2 space violations (merged, cross-net only): {violations_merged.count()}")

# Print each violation
for i, ep in enumerate(violations_merged.each()):
    e1 = ep.first
    e2 = ep.second
    dist = ep.distance()
    mx = (e1.p1.x + e1.p2.x + e2.p1.x + e2.p2.x) / 4
    my = (e1.p1.y + e1.p2.y + e2.p1.y + e2.p2.y) / 4

    # Find the two merged polygons touching these edges
    # Use a small search region around each edge midpoint
    e1_mx = (e1.p1.x + e1.p2.x) // 2
    e1_my = (e1.p1.y + e1.p2.y) // 2
    e2_mx = (e2.p1.x + e2.p2.x) // 2
    e2_my = (e2.p1.y + e2.p2.y) // 2

    # Find shape dimensions at edge 1
    probe1 = kdb.Region(kdb.Box(e1_mx - 1, e1_my - 1, e1_mx + 1, e1_my + 1))
    shapes1 = merged & probe1.sized(500)
    s1_info = "?"
    for p in shapes1.each():
        b = p.bbox()
        s1_info = f"[{b.left/1000:.3f},{b.bottom/1000:.3f}]-[{b.right/1000:.3f},{b.top/1000:.3f}] w={b.width()} h={b.height()}"
        break

    probe2 = kdb.Region(kdb.Box(e2_mx - 1, e2_my - 1, e2_mx + 1, e2_my + 1))
    shapes2 = merged & probe2.sized(500)
    s2_info = "?"
    for p in shapes2.each():
        b = p.bbox()
        s2_info = f"[{b.left/1000:.3f},{b.bottom/1000:.3f}]-[{b.right/1000:.3f},{b.top/1000:.3f}] w={b.width()} h={b.height()}"
        break

    print(f"\n  V{i+1}: gap={dist}nm at ({mx/1000:.3f},{my/1000:.3f})µm")
    print(f"    e1: ({e1.p1.x/1000:.3f},{e1.p1.y/1000:.3f})-({e1.p2.x/1000:.3f},{e1.p2.y/1000:.3f})")
    print(f"    e2: ({e2.p1.x/1000:.3f},{e2.p1.y/1000:.3f})-({e2.p2.x/1000:.3f},{e2.p2.y/1000:.3f})")
    print(f"    shape1: {s1_info}")
    print(f"    shape2: {s2_info}")
