#!/usr/bin/env python3
"""Check if the 160×160 Cont at resistor terminals comes from the PCell GDS.

The assembly code only draws Cont for MOSFET gates. So either:
1. The PCell GDS contains these contacts (but we thought they only had 360×160)
2. Some other script adds them
3. KLayout's DRC deck creates derived shapes

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_pcell_cont.py
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# Load the assembled GDS
layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()
li_cont = layout.layer(6, 0)

# Violation Cont_SQ positions (top-cell coords)
violations = [
    (10370, 137020, 10530, 137180, 'rppd'),
    (56870, 59020, 57030, 59180, 'rhigh'),
    (25130, 59020, 25290, 59180, 'rhigh'),
    (15370, 15020, 15530, 15180, 'rhigh$1'),
]

print("=" * 80)
print("Check: are violation Cont_SQ shapes from PCell or TOP cell?")
print("=" * 80)
for vx1, vy1, vx2, vy2, rname in violations:
    # Check TOP cell
    in_top = False
    for si in top.shapes(li_cont).each():
        bb = si.bbox()
        if (bb.left == vx1 and bb.bottom == vy1 and
            bb.right == vx2 and bb.top == vy2):
            in_top = True
            break

    # Check subcells
    in_sub = None
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(li_cont).each():
            bb = si.bbox().transformed(trans)
            if (bb.left == vx1 and bb.bottom == vy1 and
                bb.right == vx2 and bb.top == vy2):
                local = si.bbox()
                in_sub = f"{cell.name} local=({local.left},{local.bottom};{local.right},{local.top})"
                break
        if in_sub:
            break

    print(f"\n  {rname} Cont ({vx1},{vy1};{vx2},{vy2}) 160×160:")
    print(f"    In TOP cell: {in_top}")
    print(f"    In subcell: {in_sub or 'NOT FOUND'}")

# Now let's check the source PCell GDS files
print("\n" + "=" * 80)
print("Check source PCell GDS files for 160×160 Cont")
print("=" * 80)
import glob
pcell_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cells')
if os.path.isdir(pcell_dir):
    for gds_file in sorted(glob.glob(f'{pcell_dir}/*.gds')):
        if 'rhi' in os.path.basename(gds_file).lower() or 'rppd' in os.path.basename(gds_file).lower():
            pc_layout = kdb.Layout()
            pc_layout.read(gds_file)
            pc_top = pc_layout.top_cell()
            pc_li = pc_layout.find_layer(6, 0)
            if pc_li is not None:
                print(f"\n  {os.path.basename(gds_file)}:")
                for si in pc_top.shapes(pc_li).each():
                    bb = si.bbox()
                    print(f"    Cont: ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")
else:
    print(f"  PCell dir not found: {pcell_dir}")
    # Try other locations
    for d in ['pcells', 'gds', 'pdk_cells']:
        if os.path.isdir(d):
            print(f"  Found dir: {d}")

# Check how PCell GDS files are loaded
print("\n" + "=" * 80)
print("How are PCell GDS cells loaded?")
print("=" * 80)
# List all cells in the assembled GDS
for cell in layout.each_cell():
    print(f"  Cell: '{cell.name}' (has children: {cell.child_cells() > 0})")

# Check if there's a separate GDS loading step
print("\n  Looking for PCell GDS source files...")
pcell_search_dirs = [
    '/private/tmp/analog-trial/layout/cells',
    '/private/tmp/analog-trial/layout/gds',
    '/private/tmp/analog-trial/layout/pcells',
    '/private/tmp/analog-trial/cells',
]
for d in pcell_search_dirs:
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith('.gds'):
                print(f"    {d}/{f}")
