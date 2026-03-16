#!/usr/bin/env python3
"""Test: instantiate a single resistor PCell and check for 160×160 Cont.

If the 160×160 Cont appears from just the PCell instantiation (no assembly code),
then the PCell itself is the source.

Run: cd layout && source ~/pdk/venv/bin/activate && klayout -n sg13g2 -zz -r test_pcell_cont.py
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import klayout.lib

LIB_NAME = 'SG13_dev'

layout = kdb.Layout(True)
layout.dbu = 0.001

lib = kdb.Library.library_by_name(LIB_NAME)
if not lib:
    raise RuntimeError(f'Library {LIB_NAME} not found')

top = layout.cell(layout.add_cell('test'))

# Instantiate an rhigh PCell (same params as the actual design)
# From device_lib.json: rhigh_ptat has pcell='rhigh', params vary
# Let's use minimal params
import json
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)

for dev_type in dev_lib:
    if 'rhi' in dev_type.lower() or 'rppd' in dev_type.lower():
        info = dev_lib[dev_type]
        pcell_name = info.get('pcell', dev_type)
        params = info.get('klayout_params', {})
        print(f"\n{'='*60}")
        print(f"Testing PCell: {dev_type} → {pcell_name}")
        print(f"  Params: {params}")

        pcell_decl = lib.layout().pcell_declaration(pcell_name)
        if not pcell_decl:
            print(f"  PCell '{pcell_name}' not found in library")
            continue

        pcell_id = layout.add_pcell_variant(lib, pcell_decl.id(), params)
        inst = top.insert(kdb.CellInstArray(
            pcell_id,
            kdb.Trans(0, False, kdb.Point(0, 0))
        ))

        # Force shape generation
        pcell_cell = layout.cell(pcell_id)
        li_cont = layout.layer(6, 0)

        # Check shapes in the PCell cell
        print(f"\n  Shapes in PCell cell '{pcell_cell.name}':")
        for si in pcell_cell.shapes(li_cont).each():
            bb = si.bbox()
            print(f"    Cont: ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")

        # Check shapes in TOP cell
        print(f"\n  Shapes in TOP cell:")
        has_top_cont = False
        for si in top.shapes(li_cont).each():
            bb = si.bbox()
            print(f"    Cont: ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")
            has_top_cont = True
        if not has_top_cont:
            print(f"    (none)")

        # Check all layers in PCell cell
        print(f"\n  All layers in PCell cell:")
        for li_info in layout.layer_infos():
            li_idx = layout.find_layer(li_info.layer, li_info.datatype)
            count = 0
            for si in pcell_cell.shapes(li_idx).each():
                count += 1
            if count > 0:
                print(f"    {li_info.layer}/{li_info.datatype}: {count} shapes")

        # Remove instance for next test
        top.shapes(li_cont).clear()

# Now check: does the assembled GDS contain these same shapes?
print(f"\n{'='*60}")
print("Loading assembled GDS for comparison")
layout2 = kdb.Layout()
layout2.read('output/ptat_vco.gds')
top2 = layout2.top_cell()
li_cont2 = layout2.layer(6, 0)

# Count Cont shapes in TOP cell only
top_cont_160 = 0
for si in top2.shapes(li_cont2).each():
    bb = si.bbox()
    if bb.width() == 160 and bb.height() == 160:
        top_cont_160 += 1
print(f"Assembled GDS: {top_cont_160} × 160×160 Cont in TOP cell")

# Count Cont shapes in all subcells
sub_cont_160 = 0
sub_cont_360 = 0
for cell in layout2.each_cell():
    if cell == top2:
        continue
    for si in cell.shapes(li_cont2).each():
        bb = si.bbox()
        if bb.width() == 160 and bb.height() == 160:
            sub_cont_160 += 1
        elif bb.width() == 360 and bb.height() == 160:
            sub_cont_360 += 1
print(f"Assembled GDS: {sub_cont_160} × 160×160 Cont in subcells")
print(f"Assembled GDS: {sub_cont_360} × 360×160 Cont in subcells")
