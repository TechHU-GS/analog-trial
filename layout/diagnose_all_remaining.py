#!/usr/bin/env python3
"""Diagnose ALL remaining DRC violations: source cell, fixability, root cause.

For each violation:
1. Parse edge-pair → find two shapes → identify source (ROUTING vs DEVICE)
2. Classify fix type (endpoint trim, placement shift, reroute, unfixable)
3. Print actionable summary
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
import xml.etree.ElementTree as ET
from collections import defaultdict

GDS = 'output/ptat_vco.gds'
LYRDB = '/tmp/drc_verify_now/ptat_vco_ptat_vco_full.lyrdb'

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
top_name = top.name

RULE_LAYER = {
    'M1.a': (8, 0), 'M1.b': (8, 0),
    'M2.a': (10, 0), 'M2.b': (10, 0),
    'NW.b1': (31, 0),
}

# Parse violations
tree = ET.parse(LYRDB)
root = tree.getroot()
by_rule = defaultdict(list)
for item in root.find('items').findall('item'):
    cat = item.find('category').text.strip().strip("'\"")
    values = item.find('values')
    if values is None:
        continue
    for v in values.findall('value'):
        if v.text:
            by_rule[cat].append(v.text.strip())
            break


def parse_edge_pair(coords):
    """Parse lyrdb edge-pair string → two edges [(x1,y1),(x2,y2)]."""
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
    return edges


def find_shapes_at(layer_info, cx, cy, radius=1000):
    """Find unmerged shapes near (cx,cy). Returns [(bbox, source_cell)]."""
    li = layout.layer(*layer_info)
    search = kdb.Box(cx - radius, cy - radius, cx + radius, cy + radius)
    results = []
    seen = set()
    for si in top.begin_shapes_rec_overlapping(li, search):
        box = si.shape().bbox().transformed(si.trans())
        cell_name = layout.cell(si.cell_index()).name
        key = (box.left, box.bottom, box.right, box.top, cell_name)
        if key not in seen:
            seen.add(key)
            results.append((box, cell_name))
    return results


def edge_info(edge):
    """Compute edge midpoint, orientation, constant coordinate."""
    dx = abs(edge[0][0] - edge[1][0])
    dy = abs(edge[0][1] - edge[1][1])
    is_vert = dy > dx
    coord = edge[0][0] if is_vert else edge[0][1]
    mx = (edge[0][0] + edge[1][0]) // 2
    my = (edge[0][1] + edge[1][1]) // 2
    return mx, my, is_vert, coord


def find_shape_at_edge(layer_info, mx, my, is_vert, coord):
    """Find the specific unmerged shape whose edge matches coord."""
    shapes = find_shapes_at(layer_info, mx, my, radius=800)
    best = None
    best_dist = 999999
    for box, cell in shapes:
        match = False
        if is_vert:
            if abs(box.left - coord) <= 5 or abs(box.right - coord) <= 5:
                match = True
        else:
            if abs(box.bottom - coord) <= 5 or abs(box.top - coord) <= 5:
                match = True
        if match:
            d = abs(box.center().x - mx) + abs(box.center().y - my)
            if d < best_dist:
                best = (box, cell)
                best_dist = d
    if best is None and shapes:
        # Fallback: closest shape
        shapes.sort(key=lambda s: abs(s[0].center().x - mx) + abs(s[0].center().y - my))
        best = shapes[0]
    return best


# ════════════════════════════════════════════════════════
# Analyze each rule
# ════════════════════════════════════════════════════════

summary = defaultdict(lambda: {'fixable': 0, 'unfixable': 0, 'details': []})

for rule in ['M1.a', 'M1.b', 'M2.b', 'NW.b1']:
    viols = by_rule.get(rule, [])
    if not viols:
        continue
    layer_info = RULE_LAYER[rule]

    print(f"\n{'='*70}")
    print(f"  {rule}: {len(viols)} violation(s)")
    print(f"{'='*70}")

    for vi, coords in enumerate(viols):
        edges = parse_edge_pair(coords)
        e1, e2 = edges[0], edges[1]

        e1_mx, e1_my, e1_vert, e1_coord = edge_info(e1)
        e2_mx, e2_my, e2_vert, e2_coord = edge_info(e2)

        gap = abs(e1_coord - e2_coord)
        cx = (e1_mx + e2_mx) // 2
        cy = (e1_my + e2_my) // 2

        s1 = find_shape_at_edge(layer_info, e1_mx, e1_my, e1_vert, e1_coord)
        s2 = find_shape_at_edge(layer_info, e2_mx, e2_my, e2_vert, e2_coord)

        src1 = 'ROUTING' if s1 and s1[1] == top_name else (f'DEVICE({s1[1]})' if s1 else '?')
        src2 = 'ROUTING' if s2 and s2[1] == top_name else (f'DEVICE({s2[1]})' if s2 else '?')

        b1 = s1[0] if s1 else None
        b2 = s2[0] if s2 else None

        def classify_m1(box):
            if box is None:
                return '?'
            w, h = box.width(), box.height()
            if 470 <= w <= 490 and 470 <= h <= 490:
                return 'AP_PAD'
            if 360 <= w <= 380 and 360 <= h <= 380:
                return 'VIA1_PAD'
            if w == 200 and h > 300:
                return 'PWR_VBAR'
            if h == 200 and w > 300:
                return 'PWR_HBAR'
            if w == 370 or h == 370:
                return 'VIA_M1_PAD'
            if 280 <= w <= 320 or 280 <= h <= 320:
                return 'WIRE_300'
            return f'({w}x{h})'

        t1 = classify_m1(b1)
        t2 = classify_m1(b2)

        # Determine fixability
        if rule == 'M1.a':
            # Width violation — which shape is narrow?
            narrow_shape = None
            if b1 and min(b1.width(), b1.height()) < 160:
                narrow_shape = (b1, src1, t1)
            elif b2 and min(b2.width(), b2.height()) < 160:
                narrow_shape = (b2, src2, t2)
            if narrow_shape:
                ns, ns_src, ns_type = narrow_shape
                nw = min(ns.width(), ns.height())
                fix = f'{ns_src} {ns_type} width={nw}nm'
                fixable = 'ROUTING' in ns_src
            else:
                fix = f'? (no narrow shape found, gap={gap}nm)'
                fixable = False
        elif rule == 'M1.b':
            needed = max(0, 160 - gap)
            both_routing = src1 == 'ROUTING' and src2 == 'ROUTING'
            has_device = 'DEVICE' in src1 or 'DEVICE' in src2
            fix = f'gap={gap}nm need+{needed}nm [{t1} vs {t2}]'
            if both_routing:
                fix += ' — BOTH ROUTING'
                fixable = True
            elif has_device:
                fix += f' — {src1}/{src2}'
                fixable = False
            else:
                fixable = False
        elif rule == 'M2.b':
            needed = max(0, 210 - gap)
            both_routing = src1 == 'ROUTING' and src2 == 'ROUTING'
            fix = f'gap={gap}nm need+{needed}nm [{t1} vs {t2}]'
            if both_routing:
                fix += ' — BOTH ROUTING'
            else:
                fix += f' — {src1}/{src2}'
            fixable = both_routing
        elif rule == 'NW.b1':
            needed = max(0, 1000 - gap)  # approximate
            fix = f'gap={gap}nm [{t1} vs {t2}] {src1}/{src2}'
            fixable = False  # NWell gaps with NMOS — confirmed unfixable

        if fixable:
            summary[rule]['fixable'] += 1
        else:
            summary[rule]['unfixable'] += 1

        tag = '✓ FIXABLE' if fixable else '✗ HARD'
        print(f"\n  V{vi+1}: ({cx/1e3:.3f}, {cy/1e3:.3f})µm  {tag}")
        if b1:
            print(f"    S1: {src1:12s} {t1:12s} [{b1.left/1e3:.3f},{b1.bottom/1e3:.3f}]-"
                  f"[{b1.right/1e3:.3f},{b1.top/1e3:.3f}]")
        if b2:
            print(f"    S2: {src2:12s} {t2:12s} [{b2.left/1e3:.3f},{b2.bottom/1e3:.3f}]-"
                  f"[{b2.right/1e3:.3f},{b2.top/1e3:.3f}]")
        print(f"    >> {fix}")

        summary[rule]['details'].append((vi+1, tag, fix))


# ════════════════════════════════════════════════════════
print(f"\n\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
total_fixable = 0
total_unfixable = 0
for rule in ['M1.a', 'M1.b', 'M2.b', 'NW.b1']:
    s = summary[rule]
    f, u = s['fixable'], s['unfixable']
    total_fixable += f
    total_unfixable += u
    print(f"  {rule:6s}: {f} fixable, {u} hard  (total {f+u})")
print(f"  {'TOTAL':6s}: {total_fixable} fixable, {total_unfixable} hard  (total {total_fixable+total_unfixable})")
