#!/usr/bin/env python3
"""Diagnose CntB.b2 / Rhi.d / Rppd.c violations at (250,-510) coordinates.

These rules operate on derived layers (boolean combos of GatPoly_res, pSD, nSD,
SalBlock, EXTBlock, Cont). This script:
1. Lists all resistor PCell instances + their transforms
2. For each PCell, checks what layers have shapes at LOCAL coords that map
   to the violation region in TOP-cell coordinates
3. Probes the TOP cell and subcells for all DRC-relevant layers near violations
4. Reconstructs the derived layers to understand what the DRC deck sees

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_resistor_drc.py
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

# Layer definitions (IHP SG13G2)
LAYERS = {
    'GatPoly': (5, 0),
    'Cont': (6, 0),
    'nSD': (7, 0),
    'Metal1': (8, 0),
    'pSD': (14, 0),
    'Via1': (19, 0),
    'NWell': (31, 0),
    'SalBlock': (28, 0),
    'EXTBlock': (111, 0),
    'ThickGateOx': (44, 0),
    'Activ': (1, 0),
    'GatPoly_drawn': (5, 0),  # alias
    'Rhigh': (5, 21),  # GatPoly purpose 21 = resistor marking?
    'Metal2': (10, 0),
    'Metal3': (30, 0),
}

# Get layer indices
li = {}
for name, (ln, dt) in LAYERS.items():
    idx = layout.find_layer(ln, dt)
    li[name] = idx
    if idx is None:
        print(f"  WARNING: layer {name} ({ln}/{dt}) not found in GDS")

# Also search for ALL layers present in GDS
print("=" * 80)
print("ALL LAYERS IN GDS")
print("=" * 80)
for layer_info in layout.layer_infos():
    print(f"  {layer_info.layer}/{layer_info.datatype}: {layer_info.name}")

# Find all subcell instances
print("\n" + "=" * 80)
print("ALL SUBCELL INSTANCES IN TOP CELL")
print("=" * 80)
resistor_cells = []
for inst in top.each_inst():
    cell = inst.cell
    trans = inst.trans
    print(f"  {cell.name}: origin=({trans.disp.x},{trans.disp.y}) rot={trans.rot} mirror={trans.is_mirror()}")
    if 'rhi' in cell.name.lower() or 'rppd' in cell.name.lower() or 'res' in cell.name.lower():
        resistor_cells.append((cell, inst))

print(f"\nResistor-related cells: {len(resistor_cells)}")

# Violation coordinates from DRC lyrdb (in nm)
VIOL_COORDS = [
    (250, -510),   # approximate center of violations
    (170, -360),
    (430, -590),
    (320, -480),
]

# Probe: for EACH subcell, check what shapes exist at coords that would
# map to violation region in top-cell coords
print("\n" + "=" * 80)
print("PROBE: SHAPES NEAR VIOLATION COORDS IN TOP-CELL SPACE")
print("=" * 80)

probe_radius = 2000  # nm, generous search radius
for vx, vy in VIOL_COORDS[:1]:  # use first coord as representative
    probe = kdb.Box(vx - probe_radius, vy - probe_radius,
                    vx + probe_radius, vy + probe_radius)
    print(f"\nProbe region: ({vx-probe_radius},{vy-probe_radius}) to ({vx+probe_radius},{vy+probe_radius})")

    # Check TOP cell shapes on all layers
    print("\n  TOP cell shapes in probe region:")
    found_any = False
    for name, idx in li.items():
        if idx is None:
            continue
        count = 0
        for si in top.shapes(idx).each():
            bb = si.bbox()
            if probe.overlaps(bb):
                count += 1
                if count <= 3:
                    print(f"    {name}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")
        if count > 3:
            print(f"    {name}: ... {count} total shapes")
        if count > 0:
            found_any = True
    if not found_any:
        print("    (none)")

    # Check subcell shapes that land in probe region after transform
    print("\n  Subcell shapes landing in probe region:")
    found_any = False
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for name, idx in li.items():
            if idx is None:
                continue
            for si in cell.shapes(idx).each():
                bb = si.bbox().transformed(trans)
                if probe.overlaps(bb):
                    print(f"    {cell.name}.{name}: local=({si.bbox().left},{si.bbox().bottom};{si.bbox().right},{si.bbox().top})"
                          f" → top=({bb.left},{bb.bottom};{bb.right},{bb.top})")
                    found_any = True
    if not found_any:
        print("    (none)")

# Now the key question: the DRC deck computes derived layers.
# Let's check if any subcell has shapes at NEGATIVE local coordinates
print("\n" + "=" * 80)
print("SUBCELLS WITH SHAPES AT NEGATIVE COORDINATES")
print("=" * 80)
for inst in top.each_inst():
    cell = inst.cell
    trans = inst.trans
    neg_shapes = []
    for name, idx in li.items():
        if idx is None:
            continue
        for si in cell.shapes(idx).each():
            bb = si.bbox()
            if bb.bottom < 0 or bb.left < 0:
                neg_shapes.append((name, bb))
    if neg_shapes:
        print(f"\n  {cell.name} (origin={trans.disp.x},{trans.disp.y}):")
        for name, bb in neg_shapes[:10]:
            top_bb = bb.transformed(trans)
            print(f"    {name}: local=({bb.left},{bb.bottom};{bb.right},{bb.top})"
                  f" → top=({top_bb.left},{top_bb.bottom};{top_bb.right},{top_bb.top})")
        if len(neg_shapes) > 10:
            print(f"    ... {len(neg_shapes)} total")

# Check: do any subcells have their origin such that shapes land at y < 0 in top?
print("\n" + "=" * 80)
print("SUBCELL SHAPES LANDING AT NEGATIVE Y IN TOP CELL")
print("=" * 80)
found_any = False
for inst in top.each_inst():
    cell = inst.cell
    trans = inst.trans
    for name, idx in li.items():
        if idx is None:
            continue
        for si in cell.shapes(idx).each():
            bb = si.bbox().transformed(trans)
            if bb.bottom < 0:
                print(f"  {cell.name}.{name}: top=({bb.left},{bb.bottom};{bb.right},{bb.top})")
                found_any = True
if not found_any:
    print("  (none)")

# Check TOP cell shapes at negative Y
print("\n" + "=" * 80)
print("TOP CELL SHAPES AT NEGATIVE Y")
print("=" * 80)
found_any = False
for name, idx in li.items():
    if idx is None:
        continue
    for si in top.shapes(idx).each():
        bb = si.bbox()
        if bb.bottom < 0:
            print(f"  {name}: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
            found_any = True
if not found_any:
    print("  (none)")

# The violations reference (250,-510) in µm coordinates from lyrdb.
# But wait — lyrdb coordinates are in µm. Let's check if the coords
# might actually be in µm, meaning nm values would be 250000, -510000
print("\n" + "=" * 80)
print("PROBE AT µm-scale COORDINATES (250µm, -510µm → nm)")
print("=" * 80)
for vx_um, vy_um in [(0.250, -0.510), (0.170, -0.360), (0.430, -0.590)]:
    vx_nm = int(vx_um * 1000)
    vy_nm = int(vy_um * 1000)
    probe = kdb.Box(vx_nm - 500, vy_nm - 500, vx_nm + 500, vy_nm + 500)
    print(f"\n  Probe at ({vx_um}µm, {vy_um}µm) = ({vx_nm},{vy_nm})nm:")
    found = False
    for name, idx in li.items():
        if idx is None:
            continue
        for si in top.shapes(idx).each():
            bb = si.bbox()
            if probe.overlaps(bb):
                print(f"    TOP.{name}: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
                found = True
        for inst in top.each_inst():
            cell = inst.cell
            for si in cell.shapes(idx).each():
                bb = si.bbox().transformed(inst.trans)
                if probe.overlaps(bb):
                    print(f"    {cell.name}.{name}: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
                    found = True
    if not found:
        print("    (none)")

# Check the actual lyrdb file to get EXACT coordinates
print("\n" + "=" * 80)
print("EXACT VIOLATION COORDINATES FROM LYRDB")
print("=" * 80)
import xml.etree.ElementTree as ET
import glob
lyrdbs = glob.glob('/tmp/drc_ci_verify/*_full.lyrdb')
if not lyrdbs:
    lyrdbs = glob.glob('/tmp/drc_ci_verify/*.lyrdb')
if lyrdbs:
    tree = ET.parse(lyrdbs[0])
    root = tree.getroot()
    for item in root.find('items').findall('item'):
        cat_el = item.find('category')
        if cat_el is None:
            continue
        cat = cat_el.text.strip().strip("'")
        if cat in ('CntB.b2', 'Rhi.d', 'Rppd.c'):
            vals = item.find('values')
            if vals is None:
                continue
            for v in vals.findall('value'):
                text = v.text or ''
                print(f"  {cat}: {text}")
else:
    print("  No lyrdb found in /tmp/drc_ci_verify/")
    # Try other locations
    for d in ['/tmp/drc_m2b_r20', '/tmp/drc_r20']:
        lyrdbs = glob.glob(f'{d}/*_full.lyrdb') + glob.glob(f'{d}/*.lyrdb')
        if lyrdbs:
            print(f"  Found in {d}")
            tree = ET.parse(lyrdbs[0])
            root = tree.getroot()
            for item in root.find('items').findall('item'):
                cat_el = item.find('category')
                if cat_el is None:
                    continue
                cat = cat_el.text.strip().strip("'")
                if cat in ('CntB.b2', 'Rhi.d', 'Rppd.c'):
                    vals = item.find('values')
                    if vals is None:
                        continue
                    for v in vals.findall('value'):
                        text = v.text or ''
                        print(f"  {cat}: {text}")
            break

# Also: check the GDS bounding box
print("\n" + "=" * 80)
print("TOP CELL BOUNDING BOX")
print("=" * 80)
bb = top.bbox()
print(f"  ({bb.left},{bb.bottom}) to ({bb.right},{bb.top})")
print(f"  Size: {bb.width()}nm x {bb.height()}nm = {bb.width()/1000:.1f}µm x {bb.height()/1000:.1f}µm")

# Check: are there shapes EXACTLY at the design boundary?
print("\n" + "=" * 80)
print("SHAPES NEAR BOTTOM EDGE OF DESIGN (y < 1000nm)")
print("=" * 80)
for name, idx in li.items():
    if idx is None:
        continue
    count = 0
    for si in top.shapes(idx).each():
        bb = si.bbox()
        if bb.bottom < 1000:
            count += 1
            if count <= 3:
                print(f"  TOP.{name}: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(idx).each():
            bb = si.bbox().transformed(inst.trans)
            if bb.bottom < 1000:
                count += 1
                if count <= 3:
                    print(f"  {inst.cell.name}.{name}: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
    if count > 6:
        print(f"  ... {count} total {name} shapes near bottom")
