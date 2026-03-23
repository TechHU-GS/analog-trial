#!/usr/bin/env python3
"""Assemble all modules into the SoilZ top cell.

Reads floorplan_coords.json for placement coordinates.
Auto-detects rotation by comparing floorplan w/h with actual GDS bbox.
All modules are PCell-generated (no soilz_bare extraction).

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/assemble.py
"""
import klayout.db as pya
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

GDS_MAP = {
    'digital': 'soilz_digital.gds',
}

TILE_W = 202.08
TILE_H = 627.48


def find_cell(layout, name):
    """Find the named cell, falling back to top_cell."""
    for ci in range(layout.cells()):
        c = layout.cell(ci)
        if c.name == name:
            return c
    try:
        return layout.top_cell()
    except:
        return layout.cell(0)


def needs_rotation(gds_w, gds_h, fp_w, fp_h):
    """Check if GDS needs 90° rotation to match floorplan dimensions."""
    if abs(gds_w - fp_w) < 1.0 and abs(gds_h - fp_h) < 1.0:
        return False
    if abs(gds_w - fp_h) < 1.0 and abs(gds_h - fp_w) < 1.0:
        return True
    if abs(gds_w - gds_h) < 0.5:
        return False
    return False


def build():
    print('=== SoilZ Module Assembly ===\n')
    print(f'Tile: {TILE_W} x {TILE_H} um\n')

    with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
        fp = json.load(f)

    out = pya.Layout()
    out.dbu = 0.001
    top = out.create_cell('tt_um_techhu_analog_trial')

    placed = 0
    total_shapes = 0

    for name in sorted(fp.keys()):
        if name == 'tile':
            continue
        m = fp[name]

        gds_name = GDS_MAP.get(name, f'{name}.gds')
        gds_path = os.path.join(OUT_DIR, gds_name)

        if not os.path.exists(gds_path):
            print(f'  ⚠️  {name}: {gds_name} not found')
            continue

        mod = pya.Layout()
        mod.read(gds_path)
        mod_cell = find_cell(mod, name)
        if mod_cell is None:
            print(f'  ⚠️  {name}: no cell found')
            continue

        # Flatten to get all shapes (PCell hierarchy)
        flat = mod.create_cell(f'_{name}_flat')
        flat.copy_tree(mod_cell)
        flat.flatten(True)

        mod_bb = flat.bbox()
        gds_w = mod_bb.width() / 1000.0
        gds_h = mod_bb.height() / 1000.0

        tx = int(round(m['x'] * 1000))
        ty = int(round(m['y'] * 1000))
        fp_w = m.get('w', gds_w)
        fp_h = m.get('h', gds_h)

        rotate = needs_rotation(gds_w, gds_h, fp_w, fp_h)

        shapes_count = 0
        for li in mod.layer_indices():
            info = mod.get_info(li)
            tli = out.layer(info.layer, info.datatype)

            for si in flat.shapes(li).each():
                if si.is_polygon() or si.is_box() or si.is_path():
                    poly = si.polygon if si.is_polygon() else pya.Polygon(si.bbox()) if si.is_box() else si.polygon
                    if rotate:
                        bx, by = mod_bb.left, mod_bb.bottom
                        bh = mod_bb.height()
                        pts = []
                        for p in poly.each_point_hull():
                            lx = p.x - bx
                            ly = p.y - by
                            pts.append(pya.Point(tx + bh - ly, ty + lx))
                        if len(pts) >= 3:
                            top.shapes(tli).insert(pya.Polygon(pts))
                            shapes_count += 1
                    else:
                        dx = tx - mod_bb.left
                        dy = ty - mod_bb.bottom
                        top.shapes(tli).insert(poly.moved(dx, dy))
                        shapes_count += 1

        rot_str = ' (90°)' if rotate else ''
        print(f'  {name:18s} ({fp_w:5.1f}x{fp_h:5.1f}) -> ({m["x"]:6.1f},{m["y"]:5.1f}) {shapes_count:5d} shapes{rot_str}')
        placed += 1
        total_shapes += shapes_count

    out_path = os.path.join(OUT_DIR, 'soilz_assembled.gds')
    out.write(out_path)

    bb = top.bbox()
    print(f'\n  Placed: {placed} modules, {total_shapes} total shapes')
    print(f'  Output: {out_path}')
    print(f'  Bbox: {bb.width()/1000:.1f} x {bb.height()/1000:.1f} um')

    # Quick DRC
    for ln, dt, lname, w_min, s_min in [(8, 0, 'M1', 160, 180), (10, 0, 'M2', 200, 210)]:
        li = out.find_layer(ln, dt)
        if li is not None:
            r = pya.Region(top.begin_shapes_rec(li))
            print(f'  Quick DRC: {lname}.a={r.width_check(w_min).count()}, {lname}.b={r.space_check(s_min).count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
