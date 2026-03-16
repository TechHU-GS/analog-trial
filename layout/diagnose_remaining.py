#!/usr/bin/env python3
"""Diagnose remaining DRC violations: identify the M2/M3 shapes involved."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
M2 = (9, 0)
M3 = (30, 0)
M2_MIN_S = 210  # nm

layout = kdb.Layout()
layout.read(GDS)
cell = layout.top_cell()

# M2.b violations from DRC
m2b_violations = [
    (195855, 171450, 195770, 171470, "buf1 area 1"),
    (58350, 217150, 58210, 217240, "div area 1"),
    (58350, 202100, 58210, 202240, "div area 2"),
    (96550, 216760, 96450, 216800, "div area 3"),
    (82633, 179850, 83000, 179990, "mid area"),
    (97200, 217150, 97030, 217240, "div area 4"),
    (46700, 88760, 46620, 89165, "vco area"),
    (153470, 72240, 153550, 72250, "right area 1"),
    (46040, 75970, 45960, 76030, "tail area"),
    (197660, 171450, 197650, 171470, "buf1 area 2"),
    (67600, 239750, 67470, 239900, "top area"),
    (153340, 72240, 153680, 72250, "right area 2"),
    (46950, 69600, 47120, 69760, "bot area"),
]

li_m2 = layout.layer(*M2)

# For each violation, find the M2 shapes near both edges
print("=== M2.b Violations — Nearby M2 Shapes ===")
for x1, y1, x2, y2, label in m2b_violations:
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    gap = abs(x1 - x2) if abs(x1 - x2) > abs(y1 - y2) else abs(y1 - y2)
    print(f"\n  {label}: ({x1/1000:.3f},{y1/1000:.3f}) gap≈{gap}nm")

    # Search area: 2µm around violation center
    search = kdb.Box(cx - 2000, cy - 2000, cx + 2000, cy + 2000)
    shapes_near = []
    for si in cell.begin_shapes_rec_overlapping(li_m2, search):
        shape = si.shape()
        box = shape.bbox().transformed(si.trans())
        # Get cell path for identification
        cell_path = []
        ci = si.cell_inst()
        # Just use the shape bbox
        shapes_near.append(box)

    # Group shapes by which side of the gap they're on
    # The violation is between two edges — find shapes touching each edge
    for box in shapes_near:
        w = box.width()
        h = box.height()
        print(f"    M2 [{box.left/1000:.3f},{box.bottom/1000:.3f}]-"
              f"[{box.right/1000:.3f},{box.top/1000:.3f}] "
              f"w={w} h={h}")

print("\n\n=== M3.b Remaining Violation ===")
li_m3 = layout.layer(*M3)
# Violation at x≈84935 vs x≈84920
search = kdb.Box(84000, 179000, 86000, 180000)
print(f"  M3 shapes near (84.93, 179.5)µm:")
for si in cell.begin_shapes_rec_overlapping(li_m3, search):
    shape = si.shape()
    box = shape.bbox().transformed(si.trans())
    print(f"    M3 [{box.left/1000:.3f},{box.bottom/1000:.3f}]-"
          f"[{box.right/1000:.3f},{box.top/1000:.3f}] "
          f"w={box.width()} h={box.height()}")
