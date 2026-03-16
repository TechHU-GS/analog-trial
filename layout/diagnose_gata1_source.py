#!/usr/bin/env python3
"""Find the source cell of the pSD shape causing the Gat.a1 violation."""
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# The violating pSD shape: [36.340,146.180]-[39.920,156.180]
# Search around x=38, y=151 (center of that shape)
li_psd = layout.layer(14, 0)
search = kdb.Box(36000, 148000, 40500, 153000)

print("pSD shapes near Gat.a1 violation:")
print("=" * 70)
for si in top.begin_shapes_rec_overlapping(li_psd, search):
    cell_name = layout.cell(si.cell_index()).name
    box = si.shape().bbox().transformed(si.trans())
    print(f"  {cell_name:20s} [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
          f"[{box.right/1e3:.3f},{box.top/1e3:.3f}] ({box.width()}x{box.height()}nm)")

# Also check: which cell is nmos$4? Where is it placed?
print("\nnmos$4 cell instances:")
for ci in range(layout.cells()):
    c = layout.cell(ci)
    if 'nmos' in c.name.lower():
        # Check if it has instances in top cell
        for inst in top.each_inst():
            if inst.cell.name == c.name:
                t = inst.trans
                print(f"  {c.name} at ({t.disp.x/1e3:.3f}, {t.disp.y/1e3:.3f})")

# Show the activ shapes from nmos$4 cell near violation
li_activ = layout.layer(1, 0)
print("\nActiv shapes in nmos$4 cell near violation:")
for si in top.begin_shapes_rec_overlapping(li_activ, search):
    cell_name = layout.cell(si.cell_index()).name
    if 'nmos' in cell_name.lower():
        box = si.shape().bbox().transformed(si.trans())
        print(f"  {cell_name:20s} [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
              f"[{box.right/1e3:.3f},{box.top/1e3:.3f}] ({box.width()}x{box.height()}nm)")

# Show gatpoly shapes from nmos$4 near violation
li_poly = layout.layer(5, 0)
print("\nGatPoly shapes near violation:")
for si in top.begin_shapes_rec_overlapping(li_poly, search):
    cell_name = layout.cell(si.cell_index()).name
    box = si.shape().bbox().transformed(si.trans())
    if box.top > 149000 and box.bottom < 153000:
        print(f"  {cell_name:20s} [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
              f"[{box.right/1e3:.3f},{box.top/1e3:.3f}] ({box.width()}x{box.height()}nm)")
