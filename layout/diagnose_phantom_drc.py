#!/usr/bin/env python3
"""Reproduce DRC derived layer computation for CntB.b2/Rhi.d/Rppd.c.

The violations are at (170,-590; 330,-430) nm — a 160×160nm Contact square
OUTSIDE the design area. This script recreates the DRC boolean ops step by step
to find where these phantom shapes originate.

Key derived layers:
- ContBar = Cont shapes with area > 0.16² µm²
- Cont_SQ = Cont shapes that are exactly 0.16×0.16µm
- Rhigh_a = GatPoly_res ∩ pSD_nSD ∩ SalBlock(not esd)
- SalBlock_Rhigh = SalBlock ∩ Rhigh_a
- Rhigh_Cont = EXTBlock covering Rhigh_a ∩ Cont
- Rppd_0 = GatPoly_res ∩ pSD ∩ SalBlock(not esd)
- Rppd_all = Rppd_0 NOT interacting (Activ ∪ nSD_drv)
- SalBlock_Rppd = SalBlock ∩ Rppd_all
- Rppd_Cont = EXTBlock covering Rppd_all ∩ Cont

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_phantom_drc.py
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

# Layer map
LY = {
    'Activ': (1, 0),
    'GatPoly': (5, 0),
    'Cont': (6, 0),
    'nSD': (7, 0),
    'M1': (8, 0),
    'M2': (10, 0),
    'pSD': (14, 0),
    'Via1': (19, 0),
    'SalBlock': (28, 0),
    'NWell': (31, 0),
    'EXTBlock': (111, 0),
    'PolyRes': (128, 0),
}

def get_layer(name):
    ln, dt = LY[name]
    idx = layout.find_layer(ln, dt)
    return idx

def collect_all_shapes_flat(layer_name):
    """Collect all shapes on layer, flattened (top + all subcells transformed)."""
    idx = get_layer(layer_name)
    if idx is None:
        return []
    shapes = []
    # Top cell
    for si in top.shapes(idx).each():
        shapes.append(si.polygon)
    # Subcells
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(idx).each():
            shapes.append(si.polygon.transformed(trans))
    return shapes

def shapes_to_region(shapes):
    """Convert list of polygons to KLayout Region."""
    r = kdb.Region()
    for p in shapes:
        r.insert(p)
    return r

print("=" * 80)
print("Step 1: Collect base layers (flattened)")
print("=" * 80)

regions = {}
for name in LY:
    shapes = collect_all_shapes_flat(name)
    regions[name] = shapes_to_region(shapes)
    count = regions[name].count()
    if count > 0:
        print(f"  {name}: {count} polygons")

# Check for shapes near origin on all layers
print("\n" + "=" * 80)
print("Step 2: Shapes near absolute origin (0,0) on any layer")
print("=" * 80)
origin_probe = kdb.Region(kdb.Box(-1000, -1000, 1000, 1000))
for name, reg in regions.items():
    near = reg & origin_probe
    if near.count() > 0:
        for p in near.each():
            bb = p.bbox()
            print(f"  {name}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# Step 3: Compute derived layers (following DRC deck)
print("\n" + "=" * 80)
print("Step 3: Compute derived layers")
print("=" * 80)

# GatPoly_res = GatPoly | PolyRes
GatPoly_res = regions['GatPoly'] | regions['PolyRes']
print(f"  GatPoly_res = GatPoly ∪ PolyRes: {GatPoly_res.count()} polygons")

# pSD_nSD = pSD & nSD (note: nSD_drv may differ, but approximate)
pSD_nSD = regions['pSD'] & regions['nSD']
print(f"  pSD_nSD = pSD ∩ nSD: {pSD_nSD.count()} polygons")

# SalBlock (no esd filter needed since we don't have Recog_esd in GDS)
SalBlock = regions['SalBlock']

# Rhigh_a = GatPoly_res ∩ pSD_nSD ∩ SalBlock
Rhigh_a = GatPoly_res & pSD_nSD & SalBlock
print(f"  Rhigh_a = GatPoly_res ∩ pSD_nSD ∩ SalBlock: {Rhigh_a.count()} polygons")
for p in Rhigh_a.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# SalBlock_Rhigh = SalBlock ∩ Rhigh_a
SalBlock_Rhigh = SalBlock & Rhigh_a
print(f"  SalBlock_Rhigh = SalBlock ∩ Rhigh_a: {SalBlock_Rhigh.count()} polygons")
for p in SalBlock_Rhigh.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# Rhigh_Cont = EXTBlock covering Rhigh_a & Cont
# "covering" = EXTBlock shapes that contain/cover Rhigh_a shapes
# Approximate: EXTBlock ∩ Rhigh_a should give the overlap
EXTBlock_covering_Rhigh = regions['EXTBlock'].interacting(Rhigh_a)
print(f"  EXTBlock covering Rhigh_a: {EXTBlock_covering_Rhigh.count()} polygons")
Rhigh_Cont = EXTBlock_covering_Rhigh & regions['Cont']
print(f"  Rhigh_Cont = EXTBlock_covering ∩ Cont: {Rhigh_Cont.count()} polygons")
for p in Rhigh_Cont.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# Rppd_0 = GatPoly_res ∩ pSD ∩ SalBlock
Rppd_0 = GatPoly_res & regions['pSD'] & SalBlock
print(f"  Rppd_0 = GatPoly_res ∩ pSD ∩ SalBlock: {Rppd_0.count()} polygons")
for p in Rppd_0.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# Rppd_all = Rppd_0 NOT interacting (Activ | nSD)
Activ_or_nSD = regions['Activ'] | regions['nSD']
Rppd_all = Rppd_0.not_interacting(Activ_or_nSD)
print(f"  Rppd_all = Rppd_0 NOT interacting (Activ ∪ nSD): {Rppd_all.count()} polygons")
for p in Rppd_all.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# SalBlock_Rppd = SalBlock ∩ Rppd_all
SalBlock_Rppd = SalBlock & Rppd_all
print(f"  SalBlock_Rppd = SalBlock ∩ Rppd_all: {SalBlock_Rppd.count()} polygons")
for p in SalBlock_Rppd.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# Rppd_Cont = EXTBlock covering Rppd_all & Cont
EXTBlock_covering_Rppd = regions['EXTBlock'].interacting(Rppd_all)
Rppd_Cont = EXTBlock_covering_Rppd & regions['Cont']
print(f"  Rppd_Cont: {Rppd_Cont.count()} polygons")
for p in Rppd_Cont.each():
    bb = p.bbox()
    print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

# Step 4: ContBar / Cont_SQ
print("\n" + "=" * 80)
print("Step 4: ContBar and Cont_SQ analysis")
print("=" * 80)

cont_shapes = []
for p in regions['Cont'].each():
    bb = p.bbox()
    w, h = bb.width(), bb.height()
    area = p.area()
    cont_shapes.append((bb, w, h, area))

cont_sq_count = 0
contbar_count = 0
MIN_CONT = 160  # 0.16µm in nm
MIN_AREA = MIN_CONT * MIN_CONT  # 25600 nm²

for bb, w, h, area in cont_shapes:
    is_sq = (w == MIN_CONT and h == MIN_CONT)
    is_bar = (area > MIN_AREA)
    if is_sq:
        cont_sq_count += 1
    if is_bar:
        contbar_count += 1

print(f"  Cont_SQ (160x160): {cont_sq_count}")
print(f"  ContBar (area > {MIN_AREA}): {contbar_count}")
print(f"  Total Cont: {len(cont_shapes)}")

# List all unique Cont sizes
from collections import Counter
size_counter = Counter()
for bb, w, h, area in cont_shapes:
    size_counter[(w, h)] += 1
print(f"\n  Cont shape sizes:")
for (w, h), count in sorted(size_counter.items()):
    marker = ""
    if w == MIN_CONT and h == MIN_CONT:
        marker = " ← Cont_SQ"
    elif w * h > MIN_AREA:
        marker = " ← ContBar"
    print(f"    {w}x{h}: {count}{marker}")

# Step 5: Check if any Cont shapes are near the violation coordinates
print("\n" + "=" * 80)
print("Step 5: Cont shapes near violation region")
print("=" * 80)
viol_region = kdb.Region(kdb.Box(-1000, -1000, 1000, 1000))
near_cont = regions['Cont'] & viol_region
print(f"  Cont near origin: {near_cont.count()}")

# Wider search
viol_region_wide = kdb.Region(kdb.Box(-5000, -5000, 5000, 5000))
near_cont_wide = regions['Cont'] & viol_region_wide
print(f"  Cont within 5µm of origin: {near_cont_wide.count()}")

# Step 6: Check resistor PCell internals in detail
print("\n" + "=" * 80)
print("Step 6: Resistor PCell internal shapes (ALL layers)")
print("=" * 80)

for inst in top.each_inst():
    cell = inst.cell
    if 'rhi' not in cell.name.lower() and 'rppd' not in cell.name.lower():
        continue
    trans = inst.trans
    print(f"\n  {cell.name} at ({trans.disp.x},{trans.disp.y}):")
    for name, (ln, dt) in LY.items():
        idx = layout.find_layer(ln, dt)
        if idx is None:
            continue
        shapes_list = []
        for si in cell.shapes(idx).each():
            bb = si.bbox()
            top_bb = bb.transformed(trans)
            shapes_list.append((name, bb, top_bb))
        if shapes_list:
            print(f"    {name} ({ln}/{dt}): {len(shapes_list)} shapes")
            for sname, local_bb, top_bb in shapes_list:
                print(f"      local=({local_bb.left},{local_bb.bottom};{local_bb.right},{local_bb.top})"
                      f" → top=({top_bb.left},{top_bb.bottom};{top_bb.right},{top_bb.top})"
                      f" {local_bb.width()}x{local_bb.height()}")

# Step 7: Check if DRC deck sees anything we don't
# The DRC uses "deep" mode (hierarchical). Check cell-level shapes.
print("\n" + "=" * 80)
print("Step 7: ALL cells in layout and their shapes on DRC-relevant layers")
print("=" * 80)
for cell in layout.each_cell():
    if cell == top:
        continue
    has_shapes = False
    for name, (ln, dt) in LY.items():
        idx = layout.find_layer(ln, dt)
        if idx is None:
            continue
        count = 0
        for si in cell.shapes(idx).each():
            count += 1
        if count > 0:
            if not has_shapes:
                print(f"\n  Cell '{cell.name}':")
                has_shapes = True
            print(f"    {name}: {count} shapes")

# Step 8: Check if the layout has cells at unusual hierarchy depths
print("\n" + "=" * 80)
print("Step 8: Cell hierarchy — subcells of subcells")
print("=" * 80)
for inst in top.each_inst():
    cell = inst.cell
    sub_insts = list(cell.each_inst())
    if sub_insts:
        print(f"  {cell.name} has {len(sub_insts)} sub-instances:")
        for sub in sub_insts:
            print(f"    → {sub.cell.name} at ({sub.trans.disp.x},{sub.trans.disp.y})")

# Step 9: Actually run the DRC check ourselves for these specific rules
print("\n" + "=" * 80)
print("Step 9: Manual ContBar vs Cont_SQ spacing check")
print("=" * 80)

# Get all Cont shapes
all_cont = []
for p in regions['Cont'].each():
    bb = p.bbox()
    all_cont.append((bb.left, bb.bottom, bb.right, bb.top, bb.width(), bb.height(), p.area()))

cont_sq = [(x1, y1, x2, y2) for x1, y1, x2, y2, w, h, a in all_cont if w == 160 and h == 160]
contbar = [(x1, y1, x2, y2) for x1, y1, x2, y2, w, h, a in all_cont if a > 25600]

print(f"  Cont_SQ shapes: {len(cont_sq)}")
print(f"  ContBar shapes: {len(contbar)}")

# Find pairs with spacing < 220nm
import math
violations_found = []
for sq in cont_sq:
    for bar in contbar:
        x_gap = max(sq[0] - bar[2], bar[0] - sq[2])
        y_gap = max(sq[1] - bar[3], bar[1] - sq[3])
        if x_gap <= 0 and y_gap <= 0:
            continue  # overlapping
        if x_gap <= 0:
            dist = max(y_gap, 0)
        elif y_gap <= 0:
            dist = max(x_gap, 0)
        else:
            dist = math.sqrt(x_gap**2 + y_gap**2)
        if 0 < dist < 220:
            violations_found.append({
                'sq': sq, 'bar': bar, 'dist': dist,
                'x_gap': x_gap, 'y_gap': y_gap
            })

print(f"  CntB.b2 violations found by manual check: {len(violations_found)}")
for v in violations_found:
    sq = v['sq']
    bar = v['bar']
    print(f"    Cont_SQ ({sq[0]},{sq[1]};{sq[2]},{sq[3]}) vs "
          f"ContBar ({bar[0]},{bar[1]};{bar[2]},{bar[3]}) "
          f"dist={v['dist']:.0f}nm")
