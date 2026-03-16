#!/usr/bin/env python3
"""Detailed M2.b analysis: identify the exact two shapes in each violation,
classify them (AP pad / via pad / power drop / signal wire), and compute
how much shift would fix each."""
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

# Merge M2 to get distinct polygons
region = kdb.Region(top.begin_shapes_rec(li_m2))
merged = region.merged()

# Parse M2.b violations
tree = ET.parse(LYRDB)
root = tree.getroot()
items = root.find('items')
viols = []
for item in items.findall('item'):
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

def classify_shape(box):
    """Classify M2 shape by dimensions."""
    w, h = box.width(), box.height()
    if 470 <= w <= 490 and 470 <= h <= 490:
        return 'AP_PAD'  # 480x480
    if 360 <= w <= 380 and 360 <= h <= 380:
        return 'VIA1_PAD'  # 370x370
    if w == 200 and h > 500:
        return 'M2_VBAR'  # power drop underpass (narrowed)
    if h == 200 and w > 500:
        return 'M2_HBAR'  # horizontal underpass
    if (280 <= w <= 320 and h > 280) or (280 <= h <= 320 and w > 280):
        return 'SIGNAL_WIRE'
    if w < 250 and h < 250:
        return 'VIA_PAD_SM'
    return f'OTHER({w}x{h})'

def find_shape_at_edge(edge_pts, all_shapes):
    """Find the merged polygon that contains/touches this edge."""
    # edge_pts = [(x1,y1), (x2,y2)] in nm
    mx = (edge_pts[0][0] + edge_pts[1][0]) // 2
    my = (edge_pts[0][1] + edge_pts[1][1]) // 2
    probe = kdb.Region(kdb.Box(mx - 5, my - 5, mx + 5, my + 5))
    touching = merged & probe
    best = None
    best_area = 0
    for p in touching.each():
        b = p.bbox()
        a = b.width() * b.height()
        if best is None or a > best_area:
            best = b
            best_area = a
    return best

print("=" * 80)
print("M2.b DETAILED VIOLATION ANALYSIS")
print(f"Total M2.b violations: {len(viols)}")
print("=" * 80)

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

    # Find shapes at each edge
    shape1 = find_shape_at_edge(edges[0], merged)
    shape2 = find_shape_at_edge(edges[1], merged)

    # Compute actual gap
    e1_coords = edges[0]
    e2_coords = edges[1]

    # Edge midpoints
    e1_mx = (e1_coords[0][0] + e1_coords[1][0]) / 2
    e1_my = (e1_coords[0][1] + e1_coords[1][1]) / 2
    e2_mx = (e2_coords[0][0] + e2_coords[1][0]) / 2
    e2_my = (e2_coords[0][1] + e2_coords[1][1]) / 2

    # Gap direction
    dx = abs(e1_mx - e2_mx)
    dy = abs(e1_my - e2_my)
    if dx > dy:
        gap = dx
        gap_dir = 'X'
    else:
        gap = dy
        gap_dir = 'Y'

    needed = M2_MIN_S - gap  # how much more spacing needed

    s1_type = classify_shape(shape1) if shape1 else '?'
    s2_type = classify_shape(shape2) if shape2 else '?'

    print(f"\n{'─'*60}")
    print(f"V{vi+1}: gap={gap:.0f}nm ({gap_dir}) — need +{needed:.0f}nm to fix")
    print(f"  Edge1: ({e1_coords[0][0]/1000:.3f},{e1_coords[0][1]/1000:.3f})-"
          f"({e1_coords[1][0]/1000:.3f},{e1_coords[1][1]/1000:.3f})")
    print(f"  Edge2: ({e2_coords[0][0]/1000:.3f},{e2_coords[0][1]/1000:.3f})-"
          f"({e2_coords[1][0]/1000:.3f},{e2_coords[1][1]/1000:.3f})")

    if shape1:
        print(f"  Shape1: {s1_type:15s} [{shape1.left/1000:.3f},{shape1.bottom/1000:.3f}]-"
              f"[{shape1.right/1000:.3f},{shape1.top/1000:.3f}]")
    else:
        print(f"  Shape1: NOT FOUND")

    if shape2:
        print(f"  Shape2: {s2_type:15s} [{shape2.left/1000:.3f},{shape2.bottom/1000:.3f}]-"
              f"[{shape2.right/1000:.3f},{shape2.top/1000:.3f}]")
    else:
        print(f"  Shape2: NOT FOUND")

    # Assess fixability
    fixable = '?'
    if s1_type == 'AP_PAD' and s2_type == 'AP_PAD':
        fixable = 'HARD — both AP pads (fixed positions)'
    elif s1_type == 'AP_PAD' or s2_type == 'AP_PAD':
        other = s2_type if s1_type == 'AP_PAD' else s1_type
        if other in ('M2_VBAR', 'M2_HBAR', 'SIGNAL_WIRE'):
            fixable = f'POSSIBLE — move {other} away from AP_PAD (+{needed:.0f}nm)'
        else:
            fixable = f'MAYBE — AP_PAD vs {other}'
    elif s1_type in ('M2_VBAR', 'SIGNAL_WIRE') or s2_type in ('M2_VBAR', 'SIGNAL_WIRE'):
        fixable = f'LIKELY — routing shapes, adjust spacing (+{needed:.0f}nm)'
    else:
        fixable = f'{s1_type} vs {s2_type}'

    print(f"  Assessment: {fixable}")

# Also check: which shapes are AP pads (near analog pin positions)?
# AP pins from integrate_tile.py: ua[0]=191.04, ua[1]=166.56, at y=1µm (bottom)
print("\n\n" + "=" * 80)
print("SHAPE TYPE SUMMARY")
print("=" * 80)

# Collect all unmerged M2 shapes and classify
all_shapes = []
for si in top.begin_shapes_rec(li_m2):
    box = si.shape().bbox().transformed(si.trans())
    all_shapes.append(box)

from collections import Counter
types = Counter()
for box in all_shapes:
    t = classify_shape(box)
    types[t] += 1

for t, c in types.most_common():
    print(f"  {t}: {c}")
