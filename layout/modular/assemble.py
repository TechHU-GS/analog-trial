#!/usr/bin/env python3
"""Assemble all modules into the SoilZ top cell.

Reads floorplan_coords.json for placement coordinates.
Handles 90° rotation for modules where floorplan w×h differs from GDS.
Outputs: modular/output/soilz_assembled.gds

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/assemble.py
"""

import klayout.db as pya
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# GDS filename mapping (most = module_name.gds)
GDS_MAP = {
    'digital': 'soilz_digital.gds',
    'vco_5stage': 'vco_5stage.gds',
}

# Original (unrotated) GDS sizes for rotation detection
ORIG_SIZES = {
    'vco_5stage': (108.8, 14.4), 'vco_buffer': (7.2, 12.7),
    'digital': (30.0, 80.0),  # native 30x80 from LibreLane (no rotation needed) 'chopper': (9.5, 6.4), 'rin': (3.8, 5.3),
    'ota': (23.0, 18.0), 'c_fb': (27.2, 27.2), 'comp': (9.3, 25.2),
    'hbridge': (7.7, 9.2), 'dac_sw': (8.2, 6.4), 'rdac': (2.3, 3.8),
    # nol and inv_iso removed — functionality is in digital block (std cells)
    'hbridge_drive': (12.9, 4.1), 'sw': (15.6, 6.1),
    'bias_cascode': (55.0, 16.6), 'ptat_core': (14.5, 18.0), 'bias_mn': (8.5, 3.0),
    'cbyp_n': (6.2, 6.2), 'cbyp_p': (6.2, 6.2), 'rptat': (10.6, 135.5), 'rout': (1.6, 101.3),
}


def needs_rotation(name, fp_w, fp_h):
    """Check if module needs 90° rotation based on floorplan vs original size."""
    ow, oh = ORIG_SIZES.get(name, (fp_w, fp_h))
    return abs(fp_w - oh) < 0.5 and abs(fp_h - ow) < 0.5 and abs(ow - oh) > 0.5


def build():
    print('=== SoilZ Module Assembly ===\n')

    # Load floorplan
    with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
        fp = json.load(f)

    tile_w = fp['tile']['w']
    tile_h = fp['tile']['h']
    print(f'Tile: {tile_w} × {tile_h} um (1x2)')

    # Create output layout
    out = pya.Layout()
    out.dbu = 0.001  # 1nm
    top = out.create_cell('tt_um_techhu_analog_trial')

    placed = 0
    total_shapes = 0

    for name, m in sorted(fp.items()):
        if name == 'tile':
            continue

        gds_name = GDS_MAP.get(name, f'{name}.gds')
        gds_path = os.path.join(OUT_DIR, gds_name)

        if not os.path.exists(gds_path):
            print(f'  ⚠️  {name}: {gds_name} not found, skipping')
            continue

        # Load module GDS
        mod = pya.Layout()
        mod.read(gds_path)
        mod_cell = mod.top_cell()
        mod_bb = mod_cell.bbox()

        # Target position in nm
        tx = int(round(m['x'] * 1000))
        ty = int(round(m['y'] * 1000))

        rotate = needs_rotation(name, m['w'], m['h'])

        # Copy all shapes from module to top cell
        shapes_count = 0
        for li in mod.layer_indices():
            info = mod.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(mod_cell.begin_shapes_rec(li))

            for poly in region.each():
                if rotate:
                    # 90° CCW rotation around module bbox center, then translate
                    # Rotation: (x,y) → (-y, x) relative to center
                    # After rotation, bbox changes from (0,0,w,h) to (0,0,h,w)
                    # Module bbox origin
                    bx, by = mod_bb.left, mod_bb.bottom
                    bw, bh = mod_bb.width(), mod_bb.height()

                    pts = []
                    for p in poly.each_point_hull():
                        # Shift to bbox origin
                        lx = p.x - bx
                        ly = p.y - by
                        # 90° CCW: (lx, ly) → (-ly + bh, lx) → maps (w,h) bbox to (h,w)
                        # But we want the result to start at (0,0)
                        nx = bh - ly  # maps [0,h] to [h,0] → [0,h]
                        ny = lx       # maps [0,w] to [0,w]
                        # Shift to target
                        pts.append(pya.Point(tx + nx, ty + ny))
                    if len(pts) >= 3:
                        top.shapes(tli).insert(pya.Polygon(pts))
                        shapes_count += 1
                else:
                    # Simple translation
                    dx = tx - mod_bb.left
                    dy = ty - mod_bb.bottom
                    top.shapes(tli).insert(poly.moved(dx, dy))
                    shapes_count += 1

        rot_str = ' (90°)' if rotate else ''
        print(f'  {name:18s} → ({m["x"]:6.1f}, {m["y"]:5.1f}) {shapes_count:5d} shapes{rot_str}')
        placed += 1
        total_shapes += shapes_count

    # Write output
    out_path = os.path.join(OUT_DIR, 'soilz_assembled.gds')
    out.write(out_path)

    bb = top.bbox()
    print(f'\n  Placed: {placed} modules, {total_shapes} total shapes')
    print(f'  Output: {out_path}')
    print(f'  Bbox: {bb.width()/1000:.1f} × {bb.height()/1000:.1f} um')

    # Quick DRC
    for ln, dt, name, w_min, s_min in [(8, 0, 'M1', 160, 180), (10, 0, 'M2', 200, 210)]:
        li = out.find_layer(ln, dt)
        if li is not None:
            r = pya.Region(top.begin_shapes_rec(li))
            sw = r.width_check(w_min).count()
            ss = r.space_check(s_min).count()
            print(f'  Quick DRC: {name}.a={sw}, {name}.b={ss}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
