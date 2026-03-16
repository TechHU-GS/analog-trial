#!/usr/bin/env python3
"""Check if rppd poly shapes overlap PM3/PM4 gate poly.

If the rppd meander poly crosses through the mirror island,
there's a physical short between the resistor and MOSFET gates.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_rppd_overlap.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Find the rppd cell
rppd_cell = None
for ci in range(layout.cells()):
    cell = layout.cell(ci)
    if cell.name.startswith('rppd'):
        rppd_cell = cell
        print(f"Found cell: '{cell.name}' ({cell.shapes(layout.layer(5,0)).size()} GatPoly shapes)")
        break

if rppd_cell is None:
    print("No rppd cell found!")
    exit()

# List ALL layers in the rppd cell with shape counts
print(f"\nAll layers in '{rppd_cell.name}':")
for li_idx in range(layout.layers()):
    li_info = layout.get_info(li_idx)
    count = rppd_cell.shapes(li_idx).size()
    if count > 0:
        print(f"  ({li_info.layer}/{li_info.datatype}): {count} shapes")
        # Show bounding boxes
        for shape in rppd_cell.shapes(li_idx).each():
            bb = shape.bbox()
            print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                  f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

# Check global GatPoly overlap between rppd and mirror devices
print(f"\n{'='*60}")
print("Checking GatPoly overlap between rppd and mirror devices")
print(f"{'='*60}")

li_gp = layout.layer(5, 0)

# Get rppd GatPoly in global coords
rppd_gpoly = kdb.Region()
for inst in top.each_inst():
    if inst.cell.name.startswith('rppd'):
        trans = inst.trans
        print(f"\nrppd instance: trans=({trans.disp.x/1e3:.3f},{trans.disp.y/1e3:.3f})")
        for shape in inst.cell.shapes(li_gp).each():
            transformed = shape.bbox().transformed(trans)
            rppd_gpoly.insert(transformed)
            print(f"  GatPoly global: ({transformed.left/1e3:.3f},{transformed.bottom/1e3:.3f})-"
                  f"({transformed.right/1e3:.3f},{transformed.top/1e3:.3f})")

# Get mirror device GatPoly in global coords
mirror_gpoly = kdb.Region()
mirror_cells = set()
for inst in top.each_inst():
    if inst.cell.name.startswith('pmos'):
        trans = inst.trans
        # Check if it's in the mirror island region (y ~ 154-156)
        for shape in inst.cell.shapes(li_gp).each():
            transformed = shape.bbox().transformed(trans)
            if 153000 < transformed.bottom < 157000:
                mirror_gpoly.insert(transformed)
                mirror_cells.add(f"{inst.cell.name}@({trans.disp.x/1e3:.1f},{trans.disp.y/1e3:.1f})")

print(f"\nMirror island pmos cells: {mirror_cells}")

# Check overlap
overlap = rppd_gpoly & mirror_gpoly
if overlap.is_empty():
    print("\nNO overlap between rppd GatPoly and mirror GatPoly")
else:
    print(f"\n*** OVERLAP FOUND between rppd GatPoly and mirror GatPoly! ***")
    for poly in overlap.each():
        bb = poly.bbox()
        print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Also check: is the rppd meander poly (PolyRes layer 128/0) passing through?
li_polyres = layout.layer(128, 0)
for inst in top.each_inst():
    if inst.cell.name.startswith('rppd'):
        trans = inst.trans
        for shape in inst.cell.shapes(li_polyres).each():
            transformed = shape.bbox().transformed(trans)
            if transformed.top > 153000 and transformed.bottom < 157000:
                print(f"\n*** PolyRes (128/0) shape passes through mirror island: "
                      f"({transformed.left/1e3:.3f},{transformed.bottom/1e3:.3f})-"
                      f"({transformed.right/1e3:.3f},{transformed.top/1e3:.3f})")

# Check: what actual poly (gatpoly 5/0) from rppd passes through mirror Y range?
for inst in top.each_inst():
    if inst.cell.name.startswith('rppd'):
        trans = inst.trans
        count = 0
        for shape in inst.cell.shapes(li_gp).each():
            transformed = shape.bbox().transformed(trans)
            if transformed.top > 153000 and transformed.bottom < 157000:
                count += 1
                if count <= 5:
                    print(f"\nrppd GatPoly in mirror Y range: "
                          f"({transformed.left/1e3:.3f},{transformed.bottom/1e3:.3f})-"
                          f"({transformed.right/1e3:.3f},{transformed.top/1e3:.3f}) "
                          f"{transformed.width()/1e3:.3f}x{transformed.height()/1e3:.3f}")
        if count > 5:
            print(f"  ... +{count-5} more shapes")
        if count == 0:
            print(f"\nNo rppd GatPoly shapes in mirror Y range (153-157µm)")

# Check total GatPoly from ALL cells in the mirror island region
print(f"\n{'='*60}")
print("All GatPoly sources in mirror island (y=153-157µm, x=25-75µm)")
print(f"{'='*60}")
mirror_probe = kdb.Box(25000, 153000, 75000, 157000)
for si in top.begin_shapes_rec(li_gp):
    shape_box = si.shape().bbox().transformed(si.trans())
    if mirror_probe.overlaps(shape_box):
        cell_idx = si.cell_index()
        cell = layout.cell(cell_idx)
        if cell.name != top.name:
            bb = shape_box
            print(f"  '{cell.name}': ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) {bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
