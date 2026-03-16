#!/usr/bin/env python3
"""Scan ALL GDS layers at mid_p device positions and check NSD existence.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_midp_layers.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# ─── 1. Inventory all layers in GDS ───
print("=" * 70)
print("ALL LAYERS IN GDS")
print("=" * 70)
layer_map = {}
for li in layout.layer_indexes():
    info = layout.get_info(li)
    ln, dt = info.layer, info.datatype
    count = 0
    for shape in top.begin_shapes_rec(li):
        count += 1
        if count > 10000:
            break
    layer_map[(ln, dt)] = (li, count)
    name = ""
    known = {
        (1,0): "ACTIV", (5,0): "GATPOLY", (6,0): "CONT", (7,0): "NSD",
        (14,0): "PSD", (31,0): "NWELL", (32,0): "NBULAY",
        (8,0): "Metal1", (10,0): "Metal2", (30,0): "Metal3", (50,0): "Metal4",
        (19,0): "Via1", (29,0): "Via2", (49,0): "Via3",
        (126,0): "TopMetal1", (8,1): "M1_LBL", (10,1): "M2_LBL",
        (8,2): "M1_PIN", (10,2): "M2_PIN", (30,2): "M3_PIN", (50,2): "M4_PIN",
        (30,1): "M3_LBL", (50,1): "M4_LBL", (126,2): "TM1_PIN",
    }
    name = known.get((ln, dt), "")
    marker = " ***" if ln == 7 else ""
    print(f"  Layer ({ln:3d},{dt:2d}) {name:12s}  shapes>={count:6d}{marker}")

# ─── 2. Check NSD layer specifically ───
print(f"\n{'=' * 70}")
print("NSD LAYER (7,0) ANALYSIS")
print(f"{'=' * 70}")

if (7, 0) in layer_map:
    li_nsd = layer_map[(7, 0)][0]
    nsd_region = kdb.Region(top.begin_shapes_rec(li_nsd))
    print(f"\nNSD total shapes: {nsd_region.count()}")
    nsd_merged = nsd_region.merged()
    print(f"NSD merged polygons: {nsd_merged.count()}")
    for i, poly in enumerate(nsd_merged.each()):
        bb = poly.bbox()
        print(f"  NSD#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm "
              f"({(bb.right-bb.left)/1e3:.1f}x{(bb.top-bb.bottom)/1e3:.1f}µm)")
        if i > 50:
            print("  ... (truncated)")
            break
else:
    print("\n*** NSD layer (7,0) DOES NOT EXIST in GDS! ***")
    # Check alternative: maybe NSD is on different datatype
    for (ln, dt), (li, cnt) in sorted(layer_map.items()):
        if ln == 7:
            print(f"  Layer 7 exists as ({ln},{dt}) with {cnt} shapes")

# ─── 3. Scan ALL layers at specific device positions ───
print(f"\n{'=' * 70}")
print("ALL LAYERS AT NMOS DEVICE POSITION (Min_p, x≈38, y≈78-80)")
print(f"{'=' * 70}")

# Min_p NMOS position: active at ~(35.680-45.500, 77.180-79.680)
# But Min_p.D AP is at (38.210, 80.730) — let's scan near the NMOS active
probe_nmos = kdb.Box(37000, 77000, 40000, 80000)  # Around Min_p
probe_region = kdb.Region(probe_nmos)

for (ln, dt), (li, cnt) in sorted(layer_map.items()):
    if cnt == 0:
        continue
    layer_region = kdb.Region(top.begin_shapes_rec(li))
    overlap = layer_region & probe_region
    if not overlap.is_empty():
        shapes = []
        for poly in overlap.each():
            bb = poly.bbox()
            shapes.append(f"({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
        known = {
            (1,0): "ACTIV", (5,0): "GATPOLY", (6,0): "CONT", (7,0): "NSD",
            (14,0): "PSD", (31,0): "NWELL", (8,0): "Metal1", (10,0): "Metal2",
            (19,0): "Via1", (30,0): "Metal3", (50,0): "Metal4",
        }
        name = known.get((ln, dt), "")
        print(f"  ({ln:3d},{dt:2d}) {name:10s}: {len(shapes)} shapes")
        for s in shapes[:5]:
            print(f"    {s}")
        if len(shapes) > 5:
            print(f"    ... and {len(shapes)-5} more")

# ─── 4. Scan ALL layers at PMOS OTA load position ───
print(f"\n{'=' * 70}")
print("ALL LAYERS AT PMOS OTA LOAD (Mp_load_p, x≈40-45, y≈82-87)")
print(f"{'=' * 70}")

probe_pmos = kdb.Box(40000, 82000, 46000, 87000)
probe_region_p = kdb.Region(probe_pmos)

for (ln, dt), (li, cnt) in sorted(layer_map.items()):
    if cnt == 0:
        continue
    layer_region = kdb.Region(top.begin_shapes_rec(li))
    overlap = layer_region & probe_region_p
    if not overlap.is_empty():
        shapes = []
        for poly in overlap.each():
            bb = poly.bbox()
            shapes.append(f"({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
        known = {
            (1,0): "ACTIV", (5,0): "GATPOLY", (6,0): "CONT", (7,0): "NSD",
            (14,0): "PSD", (31,0): "NWELL", (8,0): "Metal1", (10,0): "Metal2",
            (19,0): "Via1", (30,0): "Metal3", (50,0): "Metal4",
        }
        name = known.get((ln, dt), "")
        print(f"  ({ln:3d},{dt:2d}) {name:10s}: {len(shapes)} shapes")
        for s in shapes[:8]:
            print(f"    {s}")
        if len(shapes) > 8:
            print(f"    ... and {len(shapes)-8} more")

# ─── 5. Scan at tie/tap region (y≈87-88) ───
print(f"\n{'=' * 70}")
print("ALL LAYERS AT TIE/TAP REGION (x≈40-48, y≈87-88.5)")
print(f"{'=' * 70}")

probe_tie = kdb.Box(40000, 86500, 48000, 89000)
probe_region_t = kdb.Region(probe_tie)

for (ln, dt), (li, cnt) in sorted(layer_map.items()):
    if cnt == 0:
        continue
    layer_region = kdb.Region(top.begin_shapes_rec(li))
    overlap = layer_region & probe_region_t
    if not overlap.is_empty():
        shapes = []
        for poly in overlap.each():
            bb = poly.bbox()
            shapes.append(f"({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
        known = {
            (1,0): "ACTIV", (5,0): "GATPOLY", (6,0): "CONT", (7,0): "NSD",
            (14,0): "PSD", (31,0): "NWELL", (8,0): "Metal1", (10,0): "Metal2",
            (19,0): "Via1", (30,0): "Metal3", (50,0): "Metal4",
        }
        name = known.get((ln, dt), "")
        print(f"  ({ln:3d},{dt:2d}) {name:10s}: {len(shapes)} shapes")
        for s in shapes[:8]:
            print(f"    {s}")
        if len(shapes) > 8:
            print(f"    ... and {len(shapes)-8} more")

# ─── 6. Check M1 labels in scan region ───
print(f"\n{'=' * 70}")
print("M1 LABELS (8,1) in mid_p region (x=35-55, y=75-95)")
print(f"{'=' * 70}")

li_m1_lbl = layout.layer(8, 1)
scan_box_full = kdb.Box(35000, 75000, 55000, 95000)
for shape in top.begin_shapes_rec(li_m1_lbl):
    s = shape.shape()
    if s.is_text():
        t = s.text
        pos = t.trans * kdb.Point(0, 0)
        if scan_box_full.contains(pos):
            print(f"  Label '{t.string}' at ({pos.x/1e3:.3f},{pos.y/1e3:.3f})µm")

print(f"\n{'=' * 70}")
print("ALL TEXT LABELS in mid_p region")
print(f"{'=' * 70}")
for (ln, dt), (li, cnt) in sorted(layer_map.items()):
    if dt != 1:  # Labels are on datatype 1
        continue
    for shape in top.begin_shapes_rec(li):
        s = shape.shape()
        if s.is_text():
            t = s.text
            pos = t.trans * kdb.Point(0, 0)
            if scan_box_full.contains(pos):
                known = {8: "M1", 10: "M2", 30: "M3", 50: "M4"}
                lname = known.get(ln, f"L{ln}")
                print(f"  {lname} Label '{t.string}' at ({pos.x/1e3:.3f},{pos.y/1e3:.3f})µm")

print("\n\nDONE.")
