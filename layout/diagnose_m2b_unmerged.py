#!/usr/bin/env python3
"""M2.b violations: find the original (unmerged) shapes at each edge."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
import xml.etree.ElementTree as ET

GDS = 'output/ptat_vco.gds'
LYRDB = '/tmp/drc_verify_now/ptat_vco_ptat_vco_full.lyrdb'
M2 = (10, 0)
M2_MIN_S = 210  # nm

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m2 = layout.layer(*M2)

def classify(w, h):
    if 470 <= w <= 490 and 470 <= h <= 490:
        return 'AP_PAD'
    if 360 <= w <= 380 and 360 <= h <= 380:
        return 'VIA1_PAD'
    if w == 200 and h > 500:
        return 'M2_VBAR'
    if h == 200 and w > 500:
        return 'M2_HBAR'
    if w == 300 or h == 300:
        return 'WIRE_300'
    if w == 160 or h == 160:
        return 'WIRE_160'
    return f'({w}x{h})'

def find_shape_at_edge(ex, ey, is_vertical, edge_coord):
    """Find the unmerged M2 shape whose edge matches edge_coord.
    For a vertical edge at x=edge_coord, find shape with left or right = edge_coord.
    For a horizontal edge at y=edge_coord, find shape with top or bottom = edge_coord.
    """
    search = kdb.Box(ex - 500, ey - 500, ex + 500, ey + 500)
    candidates = []
    for si in top.begin_shapes_rec_overlapping(li_m2, search):
        box = si.shape().bbox().transformed(si.trans())
        if is_vertical:
            # Check if left or right edge matches
            if abs(box.left - edge_coord) <= 5 or abs(box.right - edge_coord) <= 5:
                candidates.append(box)
        else:
            if abs(box.bottom - edge_coord) <= 5 or abs(box.top - edge_coord) <= 5:
                candidates.append(box)
    # Return closest to edge midpoint
    if not candidates:
        # Fallback: just find closest
        for si in top.begin_shapes_rec_overlapping(li_m2, search):
            box = si.shape().bbox().transformed(si.trans())
            candidates.append(box)
    if not candidates:
        return None
    # Sort by distance to (ex, ey)
    candidates.sort(key=lambda b: abs(b.center().x - ex) + abs(b.center().y - ey))
    return candidates[0]

# Parse violations
tree = ET.parse(LYRDB)
root = tree.getroot()
items_el = root.find('items')
viols = []
for item in items_el.findall('item'):
    cat = item.find('category').text.strip().strip("'\"")
    if cat != 'M2.b':
        continue
    values = item.find('values')
    if values is None:
        continue
    for v in values.findall('value'):
        if v.text:
            viols.append(v.text.strip())
            break

print(f"{'='*70}")
print(f"M2.b: {len(viols)} violations — UNMERGED shape identification")
print(f"{'='*70}")

for vi, coords in enumerate(viols):
    parts = coords.replace('edge-pair: ', '').replace('(', '').replace(')', '')
    sep = '|' if '|' in parts else '/'
    sides = parts.split(sep)

    edges = []
    for side in sides:
        pts = side.strip().split(';')
        edge_pts = []
        for pt in pts:
            xy = pt.split(',')
            edge_pts.append((int(float(xy[0]) * 1000), int(float(xy[1]) * 1000)))
        edges.append(edge_pts)

    e1, e2 = edges[0], edges[1]

    # Determine edge orientation and key coordinate
    e1_dx = abs(e1[0][0] - e1[1][0])
    e1_dy = abs(e1[0][1] - e1[1][1])
    e1_is_vert = (e1_dy > e1_dx)
    e1_coord = e1[0][0] if e1_is_vert else e1[0][1]  # constant coord
    e1_mx = (e1[0][0] + e1[1][0]) // 2
    e1_my = (e1[0][1] + e1[1][1]) // 2

    e2_dx = abs(e2[0][0] - e2[1][0])
    e2_dy = abs(e2[0][1] - e2[1][1])
    e2_is_vert = (e2_dy > e2_dx)
    e2_coord = e2[0][0] if e2_is_vert else e2[0][1]
    e2_mx = (e2[0][0] + e2[1][0]) // 2
    e2_my = (e2[0][1] + e2[1][1]) // 2

    gap = abs(e1_coord - e2_coord)
    needed = max(0, M2_MIN_S - gap)
    gap_dir = 'X' if e1_is_vert else 'Y'

    s1 = find_shape_at_edge(e1_mx, e1_my, e1_is_vert, e1_coord)
    s2 = find_shape_at_edge(e2_mx, e2_my, e2_is_vert, e2_coord)

    s1t = classify(s1.width(), s1.height()) if s1 else '?'
    s2t = classify(s2.width(), s2.height()) if s2 else '?'

    print(f"\nV{vi+1}: gap={gap}nm ({gap_dir}), need +{needed}nm")
    if s1:
        side1 = 'R' if (e1_is_vert and e1_coord == s1.right) else \
                'L' if (e1_is_vert and e1_coord == s1.left) else \
                'T' if (not e1_is_vert and e1_coord == s1.top) else 'B'
        print(f"  S1: {s1t:12s} [{s1.left/1e3:.3f},{s1.bottom/1e3:.3f}]-"
              f"[{s1.right/1e3:.3f},{s1.top/1e3:.3f}] edge={side1}")
    if s2:
        side2 = 'R' if (e2_is_vert and e2_coord == s2.right) else \
                'L' if (e2_is_vert and e2_coord == s2.left) else \
                'T' if (not e2_is_vert and e2_coord == s2.top) else 'B'
        print(f"  S2: {s2t:12s} [{s2.left/1e3:.3f},{s2.bottom/1e3:.3f}]-"
              f"[{s2.right/1e3:.3f},{s2.top/1e3:.3f}] edge={side2}")

    # Fixability
    types = {s1t, s2t}
    if 'AP_PAD' in types and len(types) == 1:
        fix = 'HARD — AP_PAD vs AP_PAD'
    elif 'AP_PAD' in types:
        other = (types - {'AP_PAD'}).pop()
        fix = f'POSSIBLE — move {other} +{needed}nm from AP_PAD'
    elif 'M2_VBAR' in types:
        fix = f'POSSIBLE — shift M2_VBAR +{needed}nm'
    else:
        fix = f'CHECK — {s1t} vs {s2t}, +{needed}nm'
    print(f"  >> {fix}")
