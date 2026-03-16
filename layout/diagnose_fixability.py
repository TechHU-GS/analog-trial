#!/usr/bin/env python3
"""For each DRC violation, identify the two shapes and whether they
come from a device cell (unfixable) or the top-cell routing (fixable)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
import xml.etree.ElementTree as ET

GDS = 'output/ptat_vco.gds'
LYRDB = '/tmp/drc_verify_now/ptat_vco_ptat_vco_full.lyrdb'

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Layer map: IHP SG13G2
LAYER_MAP = {
    (1, 0): 'Activ', (5, 0): 'GatPoly', (6, 0): 'Cont',
    (7, 0): 'Via1', (8, 0): 'M1', (9, 0): 'Via1_alt?',
    (10, 0): 'M2', (19, 0): 'Via2', (29, 0): 'Via2_alt?',
    (30, 0): 'M3', (49, 0): 'Via3', (50, 0): 'M4',
    (31, 0): 'NWell', (14, 0): 'nSD', (32, 0): 'ThickGateOx',
}

# Build device cells set
device_cells = set()
for ci in range(layout.cells()):
    c = layout.cell(ci)
    if c.name != top.name:
        device_cells.add(c.name)

# Parse violations from lyrdb
tree = ET.parse(LYRDB)
root = tree.getroot()
violations = []
items = root.find('items')
for item in items.findall('item'):
    cat = item.find('category').text.strip()
    values = item.find('values')
    coords_text = ''
    if values:
        for v in values.findall('value'):
            if v.text:
                coords_text = v.text.strip()
                break
    violations.append((cat, coords_text))

# For each violation, find the nearby shapes and their source
def find_shapes_at(layer_num, layer_dt, cx, cy, radius=500):
    """Find shapes near (cx, cy) in nm coords. Returns list of (bbox, source)."""
    li = layout.layer(layer_num, layer_dt)
    search = kdb.Box(cx - radius, cy - radius, cx + radius, cy + radius)
    results = []
    for si in top.begin_shapes_rec_overlapping(li, search):
        shape = si.shape()
        box = shape.bbox().transformed(si.trans())
        # Determine source: device cell or top cell routing
        cell_idx = si.cell().cell_index()
        cell_name = layout.cell(cell_idx).name
        if cell_name == top.name:
            source = 'ROUTING'
        else:
            source = f'DEVICE({cell_name})'
        results.append((box, source, cell_name))
    return results

# Layer for each rule
RULE_LAYER = {
    'M1.a': (8, 0), 'M1.b': (8, 0),
    'M2.a': (10, 0), 'M2.b': (10, 0),
    'M3.a': (30, 0), 'M3.b': (30, 0),
    'NW.b1': (31, 0), 'NW.b': (31, 0),
    'Gat.a1': (5, 0),
    'V1.b': (7, 0),
}

print("=" * 80)
print("DRC FIXABILITY ANALYSIS")
print("=" * 80)

# Group by rule
from collections import defaultdict
by_rule = defaultdict(list)
for cat, coords in violations:
    by_rule[cat].append(coords)

for rule_raw in sorted(by_rule.keys()):
    rule = rule_raw.strip("'\"")  # lyrdb may wrap in quotes
    vlist = by_rule[rule_raw]
    ln, ld = RULE_LAYER.get(rule, (0, 0))
    print(f"\n{'='*60}")
    print(f"  {rule}: {len(vlist)} violation(s)  [layer {ln}/{ld}]")
    print(f"{'='*60}")

    for vi, coords in enumerate(vlist):
        # Parse edge pair coords - format: "edge-pair: (x1,y1;x2,y2)|(x3,y3;x4,y4)"
        # or "edge-pair: (x1,y1;x2,y2)/(x3,y3;x4,y4)"
        # Coordinates in µm, need to convert to nm
        parts = coords.replace('edge-pair: ', '').replace('(', '').replace(')', '')
        sep = '|' if '|' in parts else '/'
        sides = parts.split(sep)

        all_coords = []
        for side in sides:
            pts = side.strip().split(';')
            for pt in pts:
                xy = pt.split(',')
                all_coords.append((float(xy[0]) * 1000, float(xy[1]) * 1000))

        cx = int(sum(c[0] for c in all_coords) / len(all_coords))
        cy = int(sum(c[1] for c in all_coords) / len(all_coords))

        # Compute gap from edge pair
        e1_pts = sides[0].strip().split(';')
        e2_pts = sides[1].strip().split(';')
        e1_x = [(float(p.split(',')[0])*1000) for p in e1_pts]
        e1_y = [(float(p.split(',')[1])*1000) for p in e1_pts]
        e2_x = [(float(p.split(',')[0])*1000) for p in e2_pts]
        e2_y = [(float(p.split(',')[1])*1000) for p in e2_pts]

        # Approximate gap
        gap_x = abs(sum(e1_x)/len(e1_x) - sum(e2_x)/len(e2_x))
        gap_y = abs(sum(e1_y)/len(e1_y) - sum(e2_y)/len(e2_y))
        gap = max(gap_x, gap_y) if min(gap_x, gap_y) < 50 else min(gap_x, gap_y)

        print(f"\n  V{vi+1}: center=({cx/1000:.3f}, {cy/1000:.3f})µm  gap≈{gap:.0f}nm")

        shapes = find_shapes_at(ln, ld, cx, cy, radius=1000)

        # Deduplicate by bbox
        seen = set()
        unique = []
        for box, source, cname in shapes:
            key = (box.left, box.bottom, box.right, box.top, source)
            if key not in seen:
                seen.add(key)
                unique.append((box, source, cname))

        # Find the two shapes closest to each edge
        for box, source, cname in sorted(unique, key=lambda t: abs(t[0].center().x - cx) + abs(t[0].center().y - cy)):
            w = box.width()
            h = box.height()
            print(f"    {source:30s} [{box.left/1000:.3f},{box.bottom/1000:.3f}]-"
                  f"[{box.right/1000:.3f},{box.top/1000:.3f}] "
                  f"w={w}nm h={h}nm")

    # Summary
    sources = set()
    for vi, coords in enumerate(vlist):
        parts = coords.replace('edge-pair: ', '').replace('(', '').replace(')', '')
        sep = '|' if '|' in parts else '/'
        sides = parts.split(sep)
        all_coords = []
        for side in sides:
            pts = side.strip().split(';')
            for pt in pts:
                xy = pt.split(',')
                all_coords.append((float(xy[0]) * 1000, float(xy[1]) * 1000))
        cx = int(sum(c[0] for c in all_coords) / len(all_coords))
        cy = int(sum(c[1] for c in all_coords) / len(all_coords))
        for box, source, cname in find_shapes_at(ln, ld, cx, cy, radius=500):
            sources.add('ROUTING' if source == 'ROUTING' else 'DEVICE')

    if sources == {'ROUTING'}:
        print(f"\n  >> {rule}: ALL shapes are ROUTING — potentially FIXABLE")
    elif sources == {'DEVICE'}:
        print(f"\n  >> {rule}: ALL shapes are DEVICE — needs PCell change")
    else:
        print(f"\n  >> {rule}: MIX of ROUTING + DEVICE — partially fixable")
