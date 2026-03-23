#!/usr/bin/env python3
"""Add M2 pads (Via1+M2) to passive module terminals for inter-module routing.

Resistors: add Via1+M2 on each M1 terminal
c_fb: add via stack M5→Via4→M4→Via3→M3→Via2→M2 on both terminals

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/add_passive_m2.py
"""
import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')


def box(x1, y1, x2, y2):
    return pya.Box(min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2))


def add_via1_m2(cell, ly, cx, cy):
    """Add Via1+M1 pad+M2 pad at (cx, cy) in nm."""
    cell.shapes(ly.layer(8, 0)).insert(box(cx-155, cy-155, cx+155, cy+155))
    cell.shapes(ly.layer(19, 0)).insert(box(cx-95, cy-95, cx+95, cy+95))
    cell.shapes(ly.layer(10, 0)).insert(box(cx-245, cy-155, cx+245, cy+155))


def add_via_stack_m5_to_m2(cell, ly, cx, cy):
    """Add via stack from M5 down to M2 at (cx, cy) in nm."""
    # M2 + Via2 + M3 + Via3 + M4 + Via4 + M5
    # Each via = 190nm, enclosure ~55nm
    hw = 150  # half width for metal pads
    v_half = 95  # via half size

    for metal_ln in [10, 30, 50, 67]:  # M2, M3, M4, M5
        cell.shapes(ly.layer(metal_ln, 0)).insert(box(cx-hw, cy-hw, cx+hw, cy+hw))
    for via_ln in [29, 49, 66]:  # Via2, Via3, Via4
        cell.shapes(ly.layer(via_ln, 0)).insert(box(cx-v_half, cy-v_half, cx+v_half, cy+v_half))


def process_resistor(mod_name):
    """Add Via1+M2 on resistor M1 terminals."""
    gds_path = os.path.join(OUT_DIR, f'{mod_name}.gds')
    ly = pya.Layout()
    ly.read(gds_path)

    cell = None
    for ci in range(ly.cells()):
        c = ly.cell(ci)
        if c.name == mod_name:
            cell = c; break
    if not cell:
        try: cell = ly.top_cell()
        except: return

    # Flatten to find M1 terminals
    flat = ly.create_cell('_f')
    flat.copy_tree(cell)
    flat.flatten(True)

    m1_li = ly.find_layer(8, 0)
    if m1_li is None:
        return

    terminals = []
    for si in flat.shapes(m1_li).each():
        b = si.bbox()
        terminals.append(((b.left+b.right)//2, (b.bottom+b.top)//2))
    flat.delete()

    # Add Via1+M2 on each terminal
    for cx, cy in terminals:
        add_via1_m2(cell, ly, cx, cy)

    ly.write(gds_path)
    print(f'  {mod_name}: {len(terminals)} M2 pads added')


def process_cap(mod_name):
    """Add via stack M5→M2 on cap terminals."""
    gds_path = os.path.join(OUT_DIR, f'{mod_name}.gds')
    ly = pya.Layout()
    ly.read(gds_path)

    cell = None
    for ci in range(ly.cells()):
        c = ly.cell(ci)
        if c.name == mod_name:
            cell = c; break
    if not cell:
        try: cell = ly.top_cell()
        except: return

    flat = ly.create_cell('_f')
    flat.copy_tree(cell)
    flat.flatten(True)

    # Find M5 (layer 67) shapes as terminals
    m5_li = ly.find_layer(67, 0)
    if m5_li is None:
        print(f'  {mod_name}: no M5 found')
        flat.delete()
        return

    m5_shapes = []
    for si in flat.shapes(m5_li).each():
        b = si.bbox()
        m5_shapes.append(b)
    flat.delete()

    if not m5_shapes:
        print(f'  {mod_name}: no M5 terminals')
        return

    # Add via stack at two corners of the M5 plate (PLUS and MINUS terminals)
    # CMIM: bottom plate = M5, top plate = TM1
    # Terminal pads at opposite corners
    bb = m5_shapes[0]
    margin = 500  # 0.5um from edge
    t1 = (bb.left + margin, bb.bottom + margin)
    t2 = (bb.right - margin, bb.top - margin)

    for cx, cy in [t1, t2]:
        add_via_stack_m5_to_m2(cell, ly, cx, cy)

    ly.write(gds_path)
    print(f'  {mod_name}: 2 via stacks (M5→M2) added')


print('=== Adding M2 pads to passive modules ===')
for mod in ['rin', 'rdac', 'rptat', 'rout']:
    process_resistor(mod)
for mod in ['c_fb', 'cbyp_n', 'cbyp_p']:
    process_cap(mod)
print('\n=== Done ===')
