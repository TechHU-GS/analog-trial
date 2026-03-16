#!/usr/bin/env python3
"""Find the source of salblock_drw and extblock_drw shapes near PM3/PM4.

These mos_exclude layers are blocking PM3/PM4 PMOS extraction.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_salblock_source.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Area of interest: between PM3 right edge and PM4 left edge
# PM3 salblock: (36.320,153.810)-(38.510,156.930)
# PM4 salblock: (37.510,153.810)-(39.940,156.930)
probe_box = kdb.Box(35000, 153000, 41000, 158000)  # nm
probe = kdb.Region(probe_box)

LAYERS_OF_INTEREST = {
    'salblock_drw': (28, 0),
    'extblock_drw': (111, 0),
    'pSD': (14, 0),
    'Activ': (1, 0),
    'NWell': (31, 0),
    'GatPoly': (5, 0),
    'Substrate': (40, 0),
}

print("=" * 70)
print(f"Shapes in probe area ({probe_box.left/1e3:.1f}-{probe_box.right/1e3:.1f}, "
      f"{probe_box.bottom/1e3:.1f}-{probe_box.top/1e3:.1f}) µm")
print("=" * 70)

for lname, (ln, dt) in LAYERS_OF_INTEREST.items():
    li = layout.layer(ln, dt)
    # Check un-merged shapes to trace origin
    print(f"\n{lname} ({ln}/{dt}):")

    # Check direct (non-recursive) shapes in top cell
    shapes_direct = kdb.Region(top.shapes(li)) & probe
    if not shapes_direct.is_empty():
        for poly in shapes_direct.each():
            bb = poly.bbox()
            print(f"  DIRECT in top: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                  f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Check shapes from cell instances (references)
    for ci_idx in range(top.child_cells()):
        ci = top.cell_index_at(ci_idx) if hasattr(top, 'cell_index_at') else None

    # Use begin_shapes_rec to trace back to source cells
    count = 0
    for si in top.begin_shapes_rec(li):
        shape_box = si.shape().bbox().transformed(si.trans())
        if not probe_box.overlaps(shape_box):
            continue
        cell_idx = si.cell_index()
        cell = layout.cell(cell_idx)
        bb = shape_box
        trans = si.trans()
        print(f"  from cell '{cell.name}' trans=({trans.disp.x/1e3:.3f},{trans.disp.y/1e3:.3f}): "
              f"({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
              f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
        count += 1
        if count >= 10:
            print(f"  ... more shapes")
            break

# Also check what devices are placed in the gap area (35-41µm x)
print(f"\n{'='*70}")
print(f"Devices placed in x=35-41µm range:")
with open('placement.json') as f:
    placement = json.load(f)
for name, info in sorted(placement['instances'].items()):
    x = info['x_um']
    if 33 < x < 43:
        print(f"  {name}: type={info['type']} at ({info['x_um']}, {info['y_um']}) "
              f"w={info['w_um']} h={info['h_um']}")
