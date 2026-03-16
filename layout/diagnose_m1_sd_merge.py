#!/usr/bin/env python3
"""Check if PMOS OTA load source M1 (VDD) and drain M1 (mid_p) merge.

Also dump ALL M1 shapes in the device+tie region for the two OTA PMOS loads.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_sd_merge.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_activ = layout.layer(1, 0)
li_gatpoly = layout.layer(5, 0)
li_cont = layout.layer(6, 0)

# ─── 1. Dump ALL M1 shapes in OTA PMOS + tie region ───
print("=" * 70)
print("ALL M1 SHAPES (x=39-53, y=80-90)")
print("=" * 70)

scan = kdb.Box(39000, 80000, 53000, 90000)
scan_region = kdb.Region(scan)
m1_all = kdb.Region(top.begin_shapes_rec(li_m1))
m1_in_scan = m1_all & scan_region

shapes = []
for poly in m1_in_scan.each():
    bb = poly.bbox()
    w = bb.right - bb.left
    h = bb.top - bb.bottom
    orient = "H" if w > h else ("V" if h > w else "□")
    shapes.append((bb.left, bb.bottom, bb.right, bb.top, w, h, orient))

shapes.sort(key=lambda s: (s[1], s[0]))  # Sort by Y then X
for i, (xl, yb, xr, yt, w, h, orient) in enumerate(shapes):
    print(f"  M1#{i:3d}: ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})  "
          f"{w:5d}x{h:5d}nm {orient}")

# ─── 2. Merge M1 in scan and check S-D connectivity ───
print(f"\n{'=' * 70}")
print("MERGED M1 IN OTA PMOS REGION")
print(f"{'=' * 70}")

m1_merged_scan = m1_in_scan.merged()
print(f"\nMerged M1 polygons: {m1_merged_scan.count()}")

# Mp_load_p: source strip x≈40.580-40.740, drain strip x≈44.960-45.120
# Mp_load_n: source strip x≈46.810-47.150, drain strip x≈51.150-51.490
source_p_probe = kdb.Box(40500, 83000, 40800, 84000)  # Source of Mp_load_p
drain_p_probe = kdb.Box(44900, 83000, 45200, 84000)   # Drain of Mp_load_p
source_n_probe = kdb.Box(46800, 83000, 47200, 84000)  # Source of Mp_load_n
drain_n_probe = kdb.Box(51100, 83000, 51500, 84000)   # Drain of Mp_load_n

for i, poly in enumerate(m1_merged_scan.each()):
    bb = poly.bbox()
    poly_region = kdb.Region(poly)

    hits_sp = not (poly_region & kdb.Region(source_p_probe)).is_empty()
    hits_dp = not (poly_region & kdb.Region(drain_p_probe)).is_empty()
    hits_sn = not (poly_region & kdb.Region(source_n_probe)).is_empty()
    hits_dn = not (poly_region & kdb.Region(drain_n_probe)).is_empty()

    labels = []
    if hits_sp: labels.append("SRC_P(vdd)")
    if hits_dp: labels.append("DRN_P(mid_p)")
    if hits_sn: labels.append("SRC_N(vdd)")
    if hits_dn: labels.append("DRN_N(mid_p)")

    if labels:
        area = poly.area() / 1e6
        print(f"\n  Merged_M1#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})  area={area:.2f}µm²")
        print(f"    Touches: {', '.join(labels)}")

        if len(labels) > 1 and any("vdd" in l for l in labels) and any("mid_p" in l for l in labels):
            print(f"    *** M1 SHORT: VDD AND mid_p ON SAME POLYGON! ***")

# ─── 3. Full-chip M1 merge: check mid_p drain vs VDD/GND ───
print(f"\n{'=' * 70}")
print("FULL-CHIP M1 MERGE: mid_p vs VDD/GND")
print(f"{'=' * 70}")

# Merge ALL M1 on chip
m1_full_merged = m1_all.merged()
print(f"\nFull-chip merged M1 polygons: {m1_full_merged.count()}")

# Probe shapes
drain_p = kdb.Region(kdb.Box(44900, 84000, 45200, 85000))  # Mid_p drain M1
source_p = kdb.Region(kdb.Box(40500, 84000, 40800, 85000)) # VDD source M1

for i, poly in enumerate(m1_full_merged.each()):
    poly_region = kdb.Region(poly)
    hits_drain = not (poly_region & drain_p).is_empty()
    hits_source = not (poly_region & source_p).is_empty()

    if hits_drain or hits_source:
        bb = poly.bbox()
        area = poly.area() / 1e6
        labels = []
        if hits_drain: labels.append("DRN_P(mid_p)")
        if hits_source: labels.append("SRC_P(vdd)")
        print(f"\n  FullM1#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})  area={area:.2f}µm²")
        print(f"    Touches: {', '.join(labels)}")

        if hits_drain and hits_source:
            print(f"    *** FULL-CHIP M1 SHORT: VDD source AND mid_p drain MERGED! ***")

# ─── 4. Check bus straps specifically ───
print(f"\n{'=' * 70}")
print("BUS STRAP ANALYSIS")
print(f"{'=' * 70}")

# Bus straps are horizontal M1 bars (width > height, height ≈ 160nm)
# Scan for horizontal M1 in the device area
for i, (xl, yb, xr, yt, w, h, orient) in enumerate(shapes):
    if orient == "H" and h < 200:  # Horizontal thin bar = bus strap
        print(f"  BUS#{i}: ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})  "
              f"{w}x{h}nm")
        # Check if it spans both source and drain X positions
        if xl < 41000 and xr > 44500:
            print(f"    *** SPANS BOTH SOURCE (x≈40.6) AND DRAIN (x≈45.0) ***")

# ─── 5. Check VIA1 in region — any V1 connecting S to D through M2? ───
print(f"\n{'=' * 70}")
print("VIA1 IN OTA PMOS REGION (x=39-53, y=80-90)")
print(f"{'=' * 70}")

li_v1 = layout.layer(19, 0)
v1_all = kdb.Region(top.begin_shapes_rec(li_v1))
v1_in_scan = v1_all & scan_region
print(f"\nVia1 shapes: {v1_in_scan.count()}")
for poly in v1_in_scan.each():
    bb = poly.bbox()
    cx = (bb.left + bb.right) / 2e3
    cy = (bb.top + bb.bottom) / 2e3
    # Which M1 strip is this on?
    if bb.left < 41000:
        loc = "source_P"
    elif bb.left > 44500 and bb.left < 45500:
        loc = "drain_P"
    elif bb.left > 46500 and bb.left < 47500:
        loc = "source_N"
    elif bb.left > 50800:
        loc = "drain_N"
    else:
        loc = "other"
    print(f"  V1: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})  "
          f"center=({cx:.3f},{cy:.3f})µm  → {loc}")

# ─── 6. M2 connectivity between source and drain ───
print(f"\n{'=' * 70}")
print("M2 IN OTA PMOS REGION (x=39-53, y=80-90)")
print(f"{'=' * 70}")

li_m2 = layout.layer(10, 0)
m2_all = kdb.Region(top.begin_shapes_rec(li_m2))
m2_in_scan = m2_all & scan_region
m2_merged = m2_in_scan.merged()

print(f"\nM2 merged polygons: {m2_merged.count()}")

# Check if any M2 polygon spans both source_P via1 and drain_P via1
sp_v1_probe = kdb.Region(kdb.Box(40400, 84000, 40900, 84600))  # Source P via1 at (40.565,84.215)
dp_v1_probe = kdb.Region(kdb.Box(44800, 84000, 45300, 84600))  # Drain P via1 area?

for i, poly in enumerate(m2_merged.each()):
    bb = poly.bbox()
    poly_region = kdb.Region(poly)
    hits_sp = not (poly_region & sp_v1_probe).is_empty()
    hits_dp = not (poly_region & dp_v1_probe).is_empty()

    if hits_sp or hits_dp:
        area = poly.area() / 1e6
        labels = []
        if hits_sp: labels.append("SRC_P_V1")
        if hits_dp: labels.append("DRN_P_V1")
        print(f"  M2#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})  area={area:.2f}µm²")
        print(f"    Touches: {', '.join(labels)}")
        if hits_sp and hits_dp:
            print(f"    *** M2 SHORT: SRC_P AND DRN_P VIA1 POSITIONS MERGED! ***")

print("\n\nDONE.")
