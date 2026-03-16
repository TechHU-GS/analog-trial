#!/usr/bin/env python3
"""Diagnose NW.b1 violations: why do 148 bridges not fix them?

Reads the output GDS, finds all NWell shapes, computes pairwise gaps,
and reports which gaps are in the violation range (0 < gap < 1800nm).
Cross-references with known violation locations.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = os.path.join(os.path.dirname(__file__), 'output', 'ptat_vco.gds')
NWELL = (31, 0)
NW_B1_MAX = 1800  # nm — rule threshold
NW_B_MAX = 620    # nm — same-net notch threshold

# Known violation locations (from DRC report, in µm)
KNOWN_VIOLATIONS = [
    # NW.b1 violations
    (46.0, 88.8, "NW.b1 V1-V4 area"),
    (47.0, 88.8, "NW.b1 V1-V4 area"),
    (48.0, 88.8, "NW.b1 V1-V4 area"),
    (141.0, 84.8, "NW.b1 V5-V6 area"),
    # NW.b violation
    # exact location unknown
]

def main():
    layout = kdb.Layout()
    layout.read(GDS)
    cell = layout.top_cell()
    li_nw = layout.layer(*NWELL)

    # Collect all NWell shapes as boxes (in nm = database units)
    nw_shapes = []
    for si in cell.begin_shapes_rec(li_nw):
        shape = si.shape()
        if shape.is_box() or shape.is_path() or shape.is_polygon():
            box = shape.bbox().transformed(si.trans())
            nw_shapes.append(box)

    print(f"Total NWell shapes: {len(nw_shapes)}")

    # Merge overlapping shapes to get distinct NWell islands
    region = kdb.Region()
    for box in nw_shapes:
        region.insert(box)
    merged = region.merged()
    islands = []
    for poly in merged.each():
        islands.append(poly.bbox())
    print(f"Merged NWell islands: {len(islands)}")

    # Sort by x
    islands.sort(key=lambda b: (b.left, b.bottom))

    # Print all islands
    print("\n=== NWell Islands ===")
    for i, b in enumerate(islands):
        print(f"  [{i:3d}] x=[{b.left/1000:.3f}, {b.right/1000:.3f}] "
              f"y=[{b.bottom/1000:.3f}, {b.top/1000:.3f}] "
              f"w={b.width()} h={b.height()}")

    # Find all X-direction gaps < NW_B1_MAX between islands
    print(f"\n=== X-Gaps < {NW_B1_MAX}nm (NW.b1 threshold) ===")
    x_gaps = []
    for i in range(len(islands)):
        for j in range(i + 1, len(islands)):
            x_gap = islands[j].left - islands[i].right
            if x_gap >= NW_B1_MAX:
                continue
            if x_gap <= 0:
                continue
            # Check Y overlap
            y_ov_min = max(islands[i].bottom, islands[j].bottom)
            y_ov_max = min(islands[i].top, islands[j].top)
            y_ov = y_ov_max - y_ov_min
            print(f"  [{i}]-[{j}] x_gap={x_gap}nm y_overlap={y_ov}nm "
                  f"x=[{islands[i].right/1000:.3f}, {islands[j].left/1000:.3f}] "
                  f"y=[{y_ov_min/1000:.3f}, {y_ov_max/1000:.3f}]")
            x_gaps.append((i, j, x_gap, y_ov, y_ov_min, y_ov_max))

    # Find all Y-direction gaps < NW_B1_MAX between islands
    print(f"\n=== Y-Gaps < {NW_B1_MAX}nm (NW.b1 threshold) ===")
    y_gaps = []
    islands_by_y = sorted(range(len(islands)), key=lambda k: (islands[k].bottom, islands[k].left))
    for ii in range(len(islands_by_y)):
        for jj in range(ii + 1, len(islands_by_y)):
            i, j = islands_by_y[ii], islands_by_y[jj]
            y_gap = islands[j].bottom - islands[i].top
            if y_gap >= NW_B1_MAX:
                continue
            if y_gap <= 0:
                continue
            # Check X overlap
            x_ov_min = max(islands[i].left, islands[j].left)
            x_ov_max = min(islands[i].right, islands[j].right)
            x_ov = x_ov_max - x_ov_min
            print(f"  [{i}]-[{j}] y_gap={y_gap}nm x_overlap={x_ov}nm "
                  f"y=[{islands[i].top/1000:.3f}, {islands[j].bottom/1000:.3f}] "
                  f"x=[{x_ov_min/1000:.3f}, {x_ov_max/1000:.3f}]")
            y_gaps.append((i, j, y_gap, x_ov, x_ov_min, x_ov_max))

    # Cross-reference with known violations
    print("\n=== Near Known Violation Locations ===")
    for vx, vy, label in KNOWN_VIOLATIONS:
        vx_nm, vy_nm = int(vx * 1000), int(vy * 1000)
        print(f"\n  {label} ({vx}, {vy})µm:")
        # Find islands near this point
        nearby = []
        for i, b in enumerate(islands):
            dx = max(b.left - vx_nm, vx_nm - b.right, 0)
            dy = max(b.bottom - vy_nm, vy_nm - b.top, 0)
            dist = (dx**2 + dy**2)**0.5
            if dist < 5000:  # within 5µm
                nearby.append((i, b, dist))
        nearby.sort(key=lambda x: x[2])
        for i, b, dist in nearby[:6]:
            print(f"    island[{i}] dist={dist:.0f}nm "
                  f"x=[{b.left/1000:.3f}, {b.right/1000:.3f}] "
                  f"y=[{b.bottom/1000:.3f}, {b.top/1000:.3f}]")

    # Run actual DRC check using region spacing
    print("\n=== KLayout Region Space Check (NW.b1 = 1800nm) ===")
    violations = merged.space_check(NW_B1_MAX)
    print(f"  Total edge pairs: {violations.size()}")
    for ep in violations.each():
        e1 = ep.first
        e2 = ep.second
        # Get edge midpoints
        mx1 = (e1.p1.x + e1.p2.x) / 2
        my1 = (e1.p1.y + e1.p2.y) / 2
        mx2 = (e2.p1.x + e2.p2.x) / 2
        my2 = (e2.p1.y + e2.p2.y) / 2
        dist = ep.distance()
        print(f"  gap={dist}nm "
              f"e1=({e1.p1.x/1000:.3f},{e1.p1.y/1000:.3f})-({e1.p2.x/1000:.3f},{e1.p2.y/1000:.3f}) "
              f"e2=({e2.p1.x/1000:.3f},{e2.p1.y/1000:.3f})-({e2.p2.x/1000:.3f},{e2.p2.y/1000:.3f})")


if __name__ == '__main__':
    main()
