#!/usr/bin/env python3
"""DRC violation diagnostic tool — traces violations to code origin.

Usage:
    python3 -m atk.diagnose_drc --lyrdb /tmp/drc_precheck/*.lyrdb \
                                 --gds output/soilz.gds \
                                 --routing output/routing.json

For each DRC violation:
  1. Parses edge-pair coordinates from .lyrdb
  2. Finds actual GDS shapes at those coordinates
  3. Classifies shapes (stub/pad/PCell/wire/vbar)
  4. Maps to routing.json AP or power drop
  5. Reports: rule, gap, shape types, AP ownership, code origin
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

import klayout.db as db


def classify_shape(w, h):
    """Classify M1/M3/M5 shape by dimensions."""
    mn, mx = min(w, h), max(w, h)
    if mn <= 170 and mx > 500:
        return 'stub'
    elif mn <= 220 and mx <= 400:
        return 'via_enc'
    elif mn <= 320 and mx <= 320:
        return 'std_pad'
    elif mx > 2000 and mn < 500:
        return 'vbar'
    elif mn > 200 and mx > 400:
        return 'ext_pad'
    else:
        return f'{w}x{h}'


def find_shape_at(top, li, x, y, radius=30):
    """Find GDS shape overlapping (x,y) on layer li."""
    box = db.Box(x - radius, y - radius, x + radius, y + radius)
    for s in top.shapes(li).each_overlapping(box):
        if s.is_box():
            b = s.box
            return {
                'bbox': (b.left, b.bottom, b.right, b.top),
                'w': b.width(), 'h': b.height(),
                'type': classify_shape(b.width(), b.height()),
                'cx': (b.left + b.right) // 2,
                'cy': (b.bottom + b.top) // 2,
            }
    return None


def find_ap_owner(shape, aps, ap_net):
    """Find which AP owns a GDS shape by proximity."""
    if not shape:
        return '?', '?'
    cx, cy = shape['cx'], shape['cy']
    best_d = 2000
    best_ak = '?'
    for ak, ap in aps.items():
        d = abs(ap['x'] - cx) + abs(ap['y'] - cy)
        if d < best_d:
            best_d = d
            best_ak = ak
    return best_ak, ap_net.get(best_ak, '?')


def parse_violations(lyrdb_path):
    """Parse .lyrdb and return list of violations."""
    tree = ET.parse(lyrdb_path)
    root = tree.getroot()
    violations = []
    for item in root.findall('.//items/item'):
        cat = item.find('category')
        if cat is None or not cat.text:
            continue
        rule = cat.text.strip("'")
        val = item.find('.//value')
        if val is None:
            continue
        pairs = re.findall(r'([\d.]+),([\d.]+)', val.text)
        if len(pairs) >= 4:
            x1 = int(float(pairs[0][0]) * 1000)
            y1 = int(float(pairs[0][1]) * 1000)
            x2 = int(float(pairs[2][0]) * 1000)
            y2 = int(float(pairs[2][1]) * 1000)
            violations.append({
                'rule': rule,
                'x1': x1, 'y1': y1,
                'x2': x2, 'y2': y2,
                'raw': val.text[:80],
            })
    return violations


# Layer GDS numbers
LAYER_MAP = {
    'M1.b': (8, 0), 'M1.a': (8, 0), 'M1.d': (8, 0), 'M1.j': (8, 0),
    'M2.a': (10, 0), 'M2.b': (10, 0), 'M2.d': (10, 0), 'M2.j': (10, 0),
    'M3.a': (30, 0), 'M3.b': (30, 0), 'M3.d': (30, 0), 'M3.j': (30, 0),
    'M3.c1': (30, 0), 'M3.e': (30, 0),
    'M4.a': (50, 0), 'M4.b': (50, 0), 'M4.d': (50, 0), 'M4.j': (50, 0),
    'M5.a': (67, 0), 'M5.b': (67, 0), 'M5.j': (67, 0), 'M5.e': (67, 0),
    'V1.b': (19, 0), 'V2.c1': (29, 0), 'V3.b': (49, 0), 'V3.c1': (49, 0),
    'Cnt.b': (6, 0), 'Cnt.g1': (6, 0),
    'TV1.a': (125, 0), 'TV1.b': (125, 0),
    'TM1.b': (126, 0), 'TM1.c': (126, 0),
}


def diagnose(lyrdb_path, gds_path, routing_path, output_path=None):
    """Run full DRC diagnosis."""
    # Load data
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    with open(routing_path) as f:
        routing = json.load(f)
    aps = routing.get('access_points', {})

    # Build AP → net map
    ap_net = {}
    for net, rt in routing.get('signal_routes', {}).items():
        for pin in rt.get('pins', []):
            ap_net[pin] = net
    for net, rt in routing.get('pre_routes', {}).items():
        for pin in rt.get('pins', []):
            ap_net[pin] = net
    for d in routing.get('power', {}).get('drops', []):
        ap_net[f'{d["inst"]}.{d["pin"]}'] = d['net']

    violations = parse_violations(lyrdb_path)
    print(f'Parsed {len(violations)} violations from {lyrdb_path}')

    # Analyze each violation
    results = []
    for v in violations:
        rule = v['rule']
        gds_layer = LAYER_MAP.get(rule)
        if not gds_layer:
            results.append({**v, 'shape1': None, 'shape2': None,
                         'ap1': '?', 'ap2': '?', 'net1': '?', 'net2': '?',
                         'gap': -1, 'collision': 'unknown'})
            continue

        li = layout.layer(*gds_layer)
        s1 = find_shape_at(top, li, v['x1'], v['y1'])
        s2 = find_shape_at(top, li, v['x2'], v['y2'])

        ap1, net1 = find_ap_owner(s1, aps, ap_net)
        ap2, net2 = find_ap_owner(s2, aps, ap_net)

        # Compute gap
        gap = -1
        if s1 and s2 and s1['bbox'] != s2['bbox']:
            b1, b2 = s1['bbox'], s2['bbox']
            dx = max(0, max(b1[0], b2[0]) - min(b1[2], b2[2]))
            dy = max(0, max(b1[1], b2[1]) - min(b1[3], b2[3]))
            gap = min(dx, dy) if dx > 0 and dy > 0 else max(dx, dy)

        # Classify collision type
        if ap1 == ap2 and ap1 != '?':
            collision = 'self'  # same AP shapes collide
        elif net1 == net2 and net1 != '?':
            collision = 'same_net'
        elif net1 != '?' and net2 != '?':
            collision = 'cross_net'
        else:
            collision = 'unknown'

        results.append({
            **v,
            'shape1': s1, 'shape2': s2,
            'ap1': ap1, 'ap2': ap2,
            'net1': net1, 'net2': net2,
            'gap': gap,
            'collision': collision,
        })

    # Summary by rule
    print('\n=== DRC Summary by Rule ===')
    rule_counts = Counter(r['rule'] for r in results)
    for rule, cnt in rule_counts.most_common():
        print(f'  {cnt:5d}  {rule}')
    print(f'  -----')
    print(f'  {len(results):5d}  TOTAL')

    # Detailed analysis for top rules
    for rule in [r for r, _ in rule_counts.most_common(5)]:
        rule_results = [r for r in results if r['rule'] == rule]
        collision_types = Counter(r['collision'] for r in rule_results)
        shape_pairs = Counter()
        for r in rule_results:
            if r.get('shape1') and r.get('shape2'):
                pair = tuple(sorted([r['shape1']['type'], r['shape2']['type']]))
                shape_pairs[pair] += 1

        print(f'\n=== {rule} ({len(rule_results)} violations) ===')
        print(f'  Collision types: {dict(collision_types)}')
        print(f'  Shape pairs:')
        for pair, cnt in shape_pairs.most_common(5):
            print(f'    {pair[0]:10s} ↔ {pair[1]:10s}: {cnt}')

        # Show specific examples
        print(f'  Examples:')
        for r in rule_results[:3]:
            s1t = r['shape1']['type'] if r.get('shape1') else '?'
            s2t = r['shape2']['type'] if r.get('shape2') else '?'
            print(f'    gap={r["gap"]:3d}nm {r["collision"]:9s}: '
                  f'{s1t} ({r["ap1"]}) ↔ {s2t} ({r["ap2"]})')

    # Save detailed JSON report
    if output_path:
        report = {
            'total': len(results),
            'by_rule': dict(rule_counts),
            'violations': [{
                'rule': r['rule'],
                'gap': r['gap'],
                'collision': r['collision'],
                'ap1': r.get('ap1', '?'),
                'ap2': r.get('ap2', '?'),
                'net1': r.get('net1', '?'),
                'net2': r.get('net2', '?'),
                'shape1_type': r['shape1']['type'] if r.get('shape1') else '?',
                'shape2_type': r['shape2']['type'] if r.get('shape2') else '?',
            } for r in results],
        }
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'\nDetailed report: {output_path}')


def main():
    parser = argparse.ArgumentParser(description='DRC violation diagnostic')
    parser.add_argument('--lyrdb', required=True, help='KLayout .lyrdb DRC report')
    parser.add_argument('--gds', required=True, help='GDS file')
    parser.add_argument('--routing', required=True, help='routing.json')
    parser.add_argument('--output', help='Output JSON report path')
    args = parser.parse_args()
    diagnose(args.lyrdb, args.gds, args.routing, args.output)


if __name__ == '__main__':
    main()
