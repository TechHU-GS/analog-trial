#!/usr/bin/env python3
"""BEOL DRC violation attribution: read GDS shapes directly.

Uses gdstk to extract all M1-M4 rectangles from the actual GDS,
then for each DRC violation finds the two closest shapes.

This gives ground truth — no shape modeling assumptions needed.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import gdstk

DRC_REPORT = '/tmp/drc_run/ptat_vco_ptat_vco_full.lyrdb'
GDS_FILE = os.path.join(os.path.dirname(__file__), 'output', 'ptat_vco.gds')

# IHP SG13G2 layer numbers (layer, datatype)
LAYER_MAP = {
    'M1': (8, 0),
    'M2': (10, 0),
    'M3': (30, 0),
    'M4': (50, 0),
}

# DRC minimum spacing (nm)
MIN_SPACING = {
    'M1': 160,
    'M2': 210,
    'M3': 210,
    'M4': 210,
}


def parse_beol_violations(path):
    """Parse M1-M4 spacing violations from lyrdb."""
    tree = ET.parse(path)
    root = tree.getroot()
    markers = []
    for item in root.findall('.//item'):
        cat_el = item.find('category')
        if cat_el is None or not cat_el.text:
            continue
        rule = cat_el.text.strip().strip("'")
        if rule not in ('M1.b', 'M1.a', 'M2.b', 'M3.b', 'M4.b'):
            continue
        values_el = item.find('.//value')
        if values_el is None:
            continue
        values_text = values_el.text.strip() if values_el.text else ''
        coords = []
        for m in re.finditer(r'([0-9.eE+-]+),([0-9.eE+-]+)', values_text):
            coords.append((float(m.group(1)), float(m.group(2))))
        if coords:
            cx = sum(c[0] for c in coords) / len(coords)
            cy = sum(c[1] for c in coords) / len(coords)
            markers.append({
                'rule': rule,
                'cx_um': cx, 'cy_um': cy,
                'coords': coords,
            })
    return markers


def load_gds_rects(gds_path, cell_name='ptat_vco'):
    """Load all rectangles from GDS, organized by metal layer.

    Returns dict: layer_name -> list of (x1_nm, y1_nm, x2_nm, y2_nm)
    Coordinates converted from µm (GDS) to nm.
    """
    lib = gdstk.read_gds(gds_path)
    cell = None
    for c in lib.cells:
        if c.name == cell_name:
            cell = c
            break
    if cell is None:
        raise ValueError(f'Cell {cell_name} not found in {gds_path}')

    # Flatten to get all polygons
    polys = cell.get_polygons(depth=-1)

    shapes_by_layer = defaultdict(list)
    for layer_name, (lyr, dt) in LAYER_MAP.items():
        count = 0
        for poly in polys:
            if poly.layer == lyr and poly.datatype == dt:
                pts = poly.points
                if len(pts) == 4:
                    # Rectangle — convert to bbox in nm
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    x1 = round(min(xs) * 1000)
                    y1 = round(min(ys) * 1000)
                    x2 = round(max(xs) * 1000)
                    y2 = round(max(ys) * 1000)
                    shapes_by_layer[layer_name].append((x1, y1, x2, y2))
                    count += 1
                else:
                    # Non-rectangular polygon — use bounding box
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    x1 = round(min(xs) * 1000)
                    y1 = round(min(ys) * 1000)
                    x2 = round(max(xs) * 1000)
                    y2 = round(max(ys) * 1000)
                    shapes_by_layer[layer_name].append((x1, y1, x2, y2))
                    count += 1
        print(f'  {layer_name}: {count} polygons')

    return shapes_by_layer


def classify_shape(rect, layer):
    """Classify a shape as wire, via_pad, power, or other based on dimensions."""
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    min_dim = min(w, h)
    max_dim = max(w, h)

    # Via pads are roughly square, ~370-480nm
    if min_dim >= 300 and max_dim <= 550 and abs(w - h) < 150:
        return 'via_pad'

    # Power rails on M3 are wide (3000nm) horizontal bars
    if layer == 'M3' and min_dim >= 2000:
        return 'power_rail'

    # Thin wires
    if min_dim <= 350:
        if max_dim > 2000:
            return 'long_wire'
        else:
            return 'short_wire'

    return 'other'


def rect_edge_gap(a, b):
    """Minimum edge-to-edge gap between two rects.

    Returns the gap in nm. Negative = overlap.
    For non-overlapping rects, returns the minimum gap in either axis.
    For rects that overlap in one axis, returns the gap in the other.
    """
    dx = max(a[0] - b[2], b[0] - a[2])  # positive = separated in X
    dy = max(a[1] - b[3], b[1] - a[3])  # positive = separated in Y

    if dx > 0 and dy > 0:
        # Fully separated — diagonal gap (DRC: edge-to-edge)
        return max(dx, dy)  # conservative: use Manhattan
    elif dx > 0:
        # Separated in X only (overlap in Y)
        return dx
    elif dy > 0:
        # Separated in Y only (overlap in X)
        return dy
    else:
        # Overlapping in both — negative gap
        return max(dx, dy)


def build_spatial_index(shapes, bucket_size=5000):
    """Build a simple grid-based spatial index for fast neighbor lookup."""
    index = defaultdict(list)
    for i, s in enumerate(shapes):
        bx1 = s[0] // bucket_size
        by1 = s[1] // bucket_size
        bx2 = s[2] // bucket_size
        by2 = s[3] // bucket_size
        for bx in range(bx1, bx2 + 1):
            for by in range(by1, by2 + 1):
                index[(bx, by)].append(i)
    return index


def find_violating_pair(vx_nm, vy_nm, shapes, spatial_idx, min_s, bucket_size=5000):
    """Find two non-overlapping shapes nearest to the violation with 0 < gap < min_s.

    DRC spacing violations are between shapes that are close but NOT touching.
    Overlapping shapes merge (same net) and aren't spacing violations.
    """
    bx = vx_nm // bucket_size
    by = vy_nm // bucket_size

    # Search in nearby buckets
    candidates = set()
    for dbx in range(-2, 3):
        for dby in range(-2, 3):
            for idx in spatial_idx.get((bx + dbx, by + dby), []):
                candidates.add(idx)

    # Filter to shapes near the violation
    nearby = []
    for idx in candidates:
        s = shapes[idx]
        dx = max(s[0] - vx_nm, vx_nm - s[2], 0)
        dy = max(s[1] - vy_nm, vy_nm - s[3], 0)
        dist = max(dx, dy)
        if dist < 2000:
            nearby.append((dist, idx, s))

    nearby.sort()

    # Find the tightest pair with 0 < gap < min_s (actual spacing violation)
    best = None
    for i in range(min(len(nearby), 30)):
        s1 = nearby[i][2]
        for j in range(i + 1, min(len(nearby), 40)):
            s2 = nearby[j][2]
            gap = rect_edge_gap(s1, s2)
            # Must be positive (non-touching) and below minimum spacing
            if 0 < gap < min_s and (best is None or gap < best[2]):
                best = (s1, s2, gap)

    # Fallback: if no positive-gap pair found, find closest non-touching pair
    if best is None:
        for i in range(min(len(nearby), 30)):
            s1 = nearby[i][2]
            for j in range(i + 1, min(len(nearby), 40)):
                s2 = nearby[j][2]
                gap = rect_edge_gap(s1, s2)
                if gap > 0 and (best is None or gap < best[2]):
                    best = (s1, s2, gap)

    return best


def main():
    print(f'Loading GDS: {GDS_FILE}')
    shapes_by_layer = load_gds_rects(GDS_FILE)

    # Build spatial indices
    indices = {}
    for layer, shapes in shapes_by_layer.items():
        indices[layer] = build_spatial_index(shapes)

    # Parse violations
    violations = parse_beol_violations(DRC_REPORT)
    print(f'\nParsed {len(violations)} BEOL violations')

    # Categorize each violation
    rule_layer = {'M1.b': 'M1', 'M1.a': 'M1', 'M2.b': 'M2', 'M3.b': 'M3', 'M4.b': 'M4'}
    gap_histogram = Counter()
    type_pairs = Counter()
    matched = 0
    unmatched = 0
    examples = []

    for v in violations:
        layer = rule_layer[v['rule']]
        min_s = MIN_SPACING[layer]
        vx_nm = round(v['cx_um'] * 1000)
        vy_nm = round(v['cy_um'] * 1000)

        pair = find_violating_pair(vx_nm, vy_nm,
                                   shapes_by_layer[layer],
                                   indices[layer],
                                   min_s)
        if pair is None:
            unmatched += 1
            continue

        s1, s2, gap = pair
        matched += 1
        gap_nm = round(gap)
        gap_bucket = (gap_nm // 10) * 10
        gap_histogram[gap_bucket] += 1

        t1 = classify_shape(s1, layer)
        t2 = classify_shape(s2, layer)
        tk = tuple(sorted([t1, t2]))
        type_pairs[tk] += 1

        if len(examples) < 15:
            examples.append((v, s1, s2, gap, t1, t2))

    print(f'\n=== BEOL Violation Attribution (GDS ground truth) ===')
    print(f'Matched: {matched}/{len(violations)} ({unmatched} unmatched)')

    print(f'\n--- By Shape Type Pair ---')
    for (t1, t2), cnt in type_pairs.most_common():
        print(f'  {t1:15s} ↔ {t2:15s} = {cnt}')

    print(f'\n--- Gap Distribution (nm) ---')
    for gap, cnt in sorted(gap_histogram.items()):
        bar = '█' * min(cnt, 60)
        print(f'  {gap:5d}nm: {cnt:3d} {bar}')

    # Breakdown by rule
    print(f'\n--- By Rule × Shape Type ---')
    rule_type = Counter()
    for v in violations:
        layer = rule_layer[v['rule']]
        min_s = MIN_SPACING[layer]
        vx_nm = round(v['cx_um'] * 1000)
        vy_nm = round(v['cy_um'] * 1000)
        pair = find_violating_pair(vx_nm, vy_nm,
                                   shapes_by_layer[layer],
                                   indices[layer], min_s)
        if pair:
            s1, s2, gap = pair
            t1 = classify_shape(s1, layer)
            t2 = classify_shape(s2, layer)
            tk = tuple(sorted([t1, t2]))
            rule_type[(v['rule'], tk)] += 1

    for (rule, (t1, t2)), cnt in sorted(rule_type.items(), key=lambda x: (-x[1])):
        print(f'  {rule:6s} {t1:15s} ↔ {t2:15s} = {cnt}')

    # Load routing.json for net attribution
    import json as _json
    routing_path = os.path.join(os.path.dirname(__file__), 'output', 'routing.json')
    with open(routing_path) as _f:
        routing = _json.load(_f)

    # Build via position → net map from routing.json
    via_to_net = {}  # (x_nm, y_nm) → net_name
    for route_dict_name in ('signal_routes', 'pre_routes'):
        for net_name, rd in routing.get(route_dict_name, {}).items():
            for seg in rd.get('segments', []):
                if len(seg) >= 5 and seg[4] < 0:  # via
                    via_to_net[(seg[0], seg[1])] = net_name
    # Power drop vias
    for drop in routing.get('power', {}).get('drops', []):
        net = drop.get('net', 'power')
        v1 = drop.get('via1_pos')
        if v1:
            via_to_net[(v1[0], v1[1])] = net
        v2 = drop.get('via2_pos')
        if v2:
            via_to_net[(v2[0], v2[1])] = net
    print(f'Built via→net map: {len(via_to_net)} vias')

    # Also build wire segment → net map for M2 shapes
    wire_rects = []  # (x1, y1, x2, y2, net)
    for route_dict_name in ('signal_routes', 'pre_routes'):
        for net_name, rd in routing.get(route_dict_name, {}).items():
            for seg in rd.get('segments', []):
                if len(seg) >= 5 and seg[4] == 1:  # M2 wire
                    hw = 150  # M2_SIG_W // 2
                    if seg[0] == seg[2]:
                        wire_rects.append((seg[0]-hw, min(seg[1],seg[3]),
                                          seg[0]+hw, max(seg[1],seg[3]), net_name))
                    else:
                        wire_rects.append((min(seg[0],seg[2]), seg[1]-hw,
                                          max(seg[0],seg[2]), seg[1]+hw, net_name))

    def find_net_for_shape(shape):
        """Try to find the net for a GDS shape by matching to routing vias or wires."""
        cx = (shape[0] + shape[2]) // 2
        cy = (shape[1] + shape[3]) // 2
        # Check via positions within 250nm (via pads are 240nm from center)
        best_dist = 250
        best_net = '?'
        for (vx, vy), net in via_to_net.items():
            d = max(abs(vx - cx), abs(vy - cy))
            if d < best_dist:
                best_dist = d
                best_net = net
        if best_net != '?':
            return best_net
        # Check wire segments — shape overlaps wire?
        for wr in wire_rects:
            if (shape[0] < wr[2] and shape[2] > wr[0] and
                shape[1] < wr[3] and shape[3] > wr[1]):
                return wr[4]
        return '?'

    # Comprehensive same-net vs different-net analysis for ALL violations
    print(f'\n--- Net Attribution (ALL violations) ---')
    net_cats = Counter()  # (rule, same/diff/unknown) -> count
    fixable_same_net = []
    diff_net_examples = []
    for v in violations:
        layer = rule_layer[v['rule']]
        min_s = MIN_SPACING[layer]
        vx_nm = round(v['cx_um'] * 1000)
        vy_nm = round(v['cy_um'] * 1000)
        pair = find_violating_pair(vx_nm, vy_nm, shapes_by_layer[layer],
                                   indices[layer], min_s)
        if pair is None:
            net_cats[(v['rule'], 'unmatched')] += 1
            continue
        s1, s2, gap = pair
        n1 = find_net_for_shape(s1)
        n2 = find_net_for_shape(s2)
        if n1 == '?' or n2 == '?':
            net_cats[(v['rule'], 'unknown')] += 1
        elif n1 == n2:
            net_cats[(v['rule'], 'same_net')] += 1
            fixable_same_net.append((v, s1, s2, gap, n1))
        else:
            net_cats[(v['rule'], 'diff_net')] += 1
            if len(diff_net_examples) < 5:
                diff_net_examples.append((v, s1, s2, gap, n1, n2))

    print('  Rule    Same-net  Diff-net  Unknown')
    for rule in ('M1.a', 'M1.b', 'M2.b', 'M3.b', 'M4.b'):
        sn = net_cats.get((rule, 'same_net'), 0)
        dn = net_cats.get((rule, 'diff_net'), 0)
        uk = net_cats.get((rule, 'unknown'), 0)
        if sn + dn + uk > 0:
            print(f'  {rule:5s}   {sn:5d}     {dn:5d}     {uk:5d}')
    total_sn = sum(v for (r, c), v in net_cats.items() if c == 'same_net')
    total_dn = sum(v for (r, c), v in net_cats.items() if c == 'diff_net')
    total_uk = sum(v for (r, c), v in net_cats.items() if c == 'unknown')
    print(f'  TOTAL   {total_sn:5d}     {total_dn:5d}     {total_uk:5d}')
    print(f'\n  Same-net gaps (fixable by fill): {total_sn}')
    print(f'  Different-net (need reroute/placement): {total_dn}')
    print(f'  Unknown (need better attribution): {total_uk}')

    if fixable_same_net:
        print(f'\n--- Same-net gap examples (fixable!) ---')
        for v, s1, s2, gap, net in fixable_same_net[:10]:
            t1 = classify_shape(s1, rule_layer[v['rule']])
            t2 = classify_shape(s2, rule_layer[v['rule']])
            print(f'  {v["rule"]:5s} net={net:15s} gap={gap:.0f}nm '
                  f'{t1}↔{t2}')

    if diff_net_examples:
        print(f'\n--- Different-net spacing examples ---')
        for v, s1, s2, gap, n1, n2 in diff_net_examples:
            t1 = classify_shape(s1, rule_layer[v['rule']])
            t2 = classify_shape(s2, rule_layer[v['rule']])
            print(f'  {v["rule"]:5s} {n1}↔{n2} gap={gap:.0f}nm '
                  f'{t1}↔{t2}')

    # Detailed analysis of 200nm gap violations
    print(f'\n--- Detailed Analysis: gap=200nm violations (M2.b + M3.b) ---')
    detail_count = 0
    for v in violations:
        layer = rule_layer[v['rule']]
        min_s = MIN_SPACING[layer]
        vx_nm = round(v['cx_um'] * 1000)
        vy_nm = round(v['cy_um'] * 1000)
        pair = find_violating_pair(vx_nm, vy_nm, shapes_by_layer[layer],
                                   indices[layer], min_s)
        if pair is None:
            continue
        s1, s2, gap = pair
        gap_nm = round(gap)
        if gap_nm < 195 or gap_nm > 205:
            continue
        if detail_count >= 15:
            break
        t1 = classify_shape(s1, layer)
        t2 = classify_shape(s2, layer)
        # Compute gap direction
        dx = max(s1[0] - s2[2], s2[0] - s1[2])  # X gap (positive = separated)
        dy = max(s1[1] - s2[3], s2[1] - s1[3])  # Y gap
        gap_dir = 'X' if dx > dy else 'Y'
        w1 = f'{s1[2]-s1[0]}×{s1[3]-s1[1]}'
        w2 = f'{s2[2]-s2[0]}×{s2[3]-s2[1]}'
        cx1 = (s1[0]+s1[2])//2
        cy1 = (s1[1]+s1[3])//2
        cx2 = (s2[0]+s2[2])//2
        cy2 = (s2[1]+s2[3])//2
        print(f'  {v["rule"]:5s} gap={gap_nm}nm dir={gap_dir} dx={dx} dy={dy}')
        print(f'    {t1:12s} {w1:>12s}nm c=({cx1},{cy1}) [{s1[0]},{s1[1]},{s1[2]},{s1[3]}]')
        print(f'    {t2:12s} {w2:>12s}nm c=({cx2},{cy2}) [{s2[0]},{s2[1]},{s2[2]},{s2[3]}]')
        detail_count += 1

    # Detailed analysis of 10nm gap violations
    print(f'\n--- Detailed Analysis: gap≤20nm violations ---')
    detail_count = 0
    for v in violations:
        layer = rule_layer[v['rule']]
        min_s = MIN_SPACING[layer]
        vx_nm = round(v['cx_um'] * 1000)
        vy_nm = round(v['cy_um'] * 1000)
        pair = find_violating_pair(vx_nm, vy_nm, shapes_by_layer[layer],
                                   indices[layer], min_s)
        if pair is None:
            continue
        s1, s2, gap = pair
        gap_nm = round(gap)
        if gap_nm > 20:
            continue
        if detail_count >= 15:
            break
        t1 = classify_shape(s1, layer)
        t2 = classify_shape(s2, layer)
        dx = max(s1[0] - s2[2], s2[0] - s1[2])
        dy = max(s1[1] - s2[3], s2[1] - s1[3])
        gap_dir = 'X' if dx > dy else 'Y'
        w1 = f'{s1[2]-s1[0]}×{s1[3]-s1[1]}'
        w2 = f'{s2[2]-s2[0]}×{s2[3]-s2[1]}'
        cx1 = (s1[0]+s1[2])//2
        cy1 = (s1[1]+s1[3])//2
        cx2 = (s2[0]+s2[2])//2
        cy2 = (s2[1]+s2[3])//2
        print(f'  {v["rule"]:5s} gap={gap_nm}nm dir={gap_dir} dx={dx} dy={dy}')
        print(f'    {t1:12s} {w1:>12s}nm c=({cx1},{cy1}) [{s1[0]},{s1[1]},{s1[2]},{s1[3]}]')
        print(f'    {t2:12s} {w2:>12s}nm c=({cx2},{cy2}) [{s2[0]},{s2[1]},{s2[2]},{s2[3]}]')
        detail_count += 1


if __name__ == '__main__':
    main()
