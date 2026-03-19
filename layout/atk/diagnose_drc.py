#!/usr/bin/env python3
"""DRC violation diagnostic tool — uses KLayout RDB + LayoutToNetlist APIs.

For each DRC violation:
  1. Reads edge-pair geometry from .lyrdb via ReportDatabase API
  2. Probes GDS net at violation edges via LayoutToNetlist
  3. Classifies: self-collision (same net) vs cross-net
  4. Maps to routing.json AP ownership
  5. Reports actionable fix direction

Usage:
    python3 -m atk.diagnose_drc --lyrdb FILE --gds FILE --routing FILE [--output FILE]
"""

import argparse
import json
import sys
from collections import Counter

import klayout.db as db
import klayout.rdb as rdb


# GDS layer definitions for net extraction
METAL_LAYERS = [
    (8,   0, 'Metal1'),
    (19,  0, 'Via1'),
    (10,  0, 'Metal2'),
    (29,  0, 'Via2'),
    (30,  0, 'Metal3'),
    (49,  0, 'Via3'),
    (50,  0, 'Metal4'),
    (66,  0, 'Via4'),
    (67,  0, 'Metal5'),
    (125, 0, 'TopVia1'),
    (126, 0, 'TopMetal1'),
]

# Map DRC rule prefix to GDS layer for shape lookup
RULE_LAYER = {
    'M1': (8, 0), 'M2': (10, 0), 'M3': (30, 0), 'M4': (50, 0), 'M5': (67, 0),
    'V1': (19, 0), 'V2': (29, 0), 'V3': (49, 0),
    'Cnt': (6, 0), 'CntB': (6, 0),
    'TV1': (125, 0), 'TM1': (126, 0), 'TM2': (134, 0),
    'NW': (31, 0), 'pSD': (14, 0), 'nSD': (7, 0),
    'Act': (1, 0), 'LU': (1, 0),
    'AFil': (1, 0), 'GFil': (5, 0),
}


def get_layer_for_rule(rule):
    """Map DRC rule name to GDS layer number."""
    for prefix, layer in RULE_LAYER.items():
        if rule.startswith(prefix):
            return layer
    return None


def classify_shape(w, h):
    """Classify shape by dimensions."""
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


def build_net_extractor(layout, top_cell):
    """Build LayoutToNetlist for net probing."""
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top_cell, []))

    layers = {}
    for gds_l, gds_d, name in METAL_LAYERS:
        li = layout.find_layer(gds_l, gds_d)
        if li >= 0:
            layers[name] = l2n.make_layer(li, name)

    # Connect metals through vias
    connections = [
        ('Metal1', 'Via1'), ('Metal2', 'Via1'),
        ('Metal2', 'Via2'), ('Metal3', 'Via2'),
        ('Metal3', 'Via3'), ('Metal4', 'Via3'),
        ('Metal4', 'Via4'), ('Metal5', 'Via4'),
        ('Metal5', 'TopVia1'), ('TopMetal1', 'TopVia1'),
    ]
    for name in layers:
        l2n.connect(layers[name])  # intra-layer
    for m, v in connections:
        if m in layers and v in layers:
            l2n.connect(layers[m], layers[v])

    l2n.extract_netlist()
    return l2n, layers


def probe_net_at(l2n, layer_obj, x_um, y_um, dbu):
    """Probe net at a point. Returns (net_name, cluster_id) or (None, None)."""
    pt = db.DPoint(x_um, y_um)
    net = l2n.probe_net(layer_obj, pt)
    if net:
        name = net.name if net.name else net.expanded_name()
        return name, net.cluster_id
    return None, None


def find_gds_shape(top, layout, gds_layer, x_um, y_um, dbu):
    """Find GDS shape at position, return bbox + classification."""
    li = layout.find_layer(*gds_layer)
    if li < 0:
        return None
    x_dbu = int(x_um / dbu)
    y_dbu = int(y_um / dbu)
    box = db.Box(x_dbu - 30, y_dbu - 30, x_dbu + 30, y_dbu + 30)
    for s in top.shapes(li).each_overlapping(box):
        if s.is_box():
            b = s.box
            return {
                'bbox': (b.left, b.bottom, b.right, b.top),
                'w': b.width(), 'h': b.height(),
                'type': classify_shape(b.width(), b.height()),
            }
    return None


def diagnose(lyrdb_path, gds_path, routing_path, output_path=None):
    """Run full DRC diagnosis with net probing."""
    # Load GDS
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    dbu = layout.dbu

    # Build net extractor
    print('Building net extractor...')
    l2n, layers = build_net_extractor(layout, top)
    netlist = l2n.netlist()
    top_circuit = None
    for c in netlist.each_circuit():
        top_circuit = c  # last = top
    if top_circuit:
        print(f'  Extracted: {len(list(top_circuit.each_net()))} nets in {top_circuit.name}')

    # Load routing.json for AP mapping
    with open(routing_path) as f:
        routing = json.load(f)
    aps = routing.get('access_points', {})
    ap_net = {}
    for net, rt in routing.get('signal_routes', {}).items():
        for pin in rt.get('pins', []):
            ap_net[pin] = net
    for d in routing.get('power', {}).get('drops', []):
        ap_net[f'{d["inst"]}.{d["pin"]}'] = d['net']

    def find_ap(x_dbu, y_dbu):
        """Find nearest AP by proximity."""
        best_d, best_ak = 2000, '?'
        for ak, ap in aps.items():
            d = abs(ap['x'] - x_dbu) + abs(ap['y'] - y_dbu)
            if d < best_d:
                best_d = d
                best_ak = ak
        return best_ak

    # Load DRC report
    rdb_db = rdb.ReportDatabase('drc')
    rdb_db.load(lyrdb_path)
    print(f'Loaded {rdb_db.num_items()} violations from {lyrdb_path}')

    # Analyze each violation
    results = []
    for cat in rdb_db.each_category():
        if cat.num_items() == 0:
            continue
        rule = cat.name()
        gds_layer = get_layer_for_rule(rule)

        # Find the layer Region for net probing
        layer_name = None
        layer_obj = None
        if gds_layer:
            for gds_l, gds_d, name in METAL_LAYERS:
                if (gds_l, gds_d) == gds_layer:
                    layer_name = name
                    layer_obj = layers.get(name)
                    break

        for item in rdb_db.each_item_per_category(cat.rdb_id()):
            result = {'rule': rule}

            for v in item.each_value():
                if v.is_edge_pair():
                    ep = v.edge_pair()
                    # Edge endpoints (microns)
                    p1 = ep.first.p1
                    p2 = ep.second.p1

                    # Probe nets at both edges
                    net1_name, net1_id = None, None
                    net2_name, net2_id = None, None
                    if layer_obj:
                        net1_name, net1_id = probe_net_at(l2n, layer_obj, p1.x, p1.y, dbu)
                        net2_name, net2_id = probe_net_at(l2n, layer_obj, p2.x, p2.y, dbu)

                    # Find GDS shapes
                    shape1 = find_gds_shape(top, layout, gds_layer, p1.x, p1.y, dbu) if gds_layer else None
                    shape2 = find_gds_shape(top, layout, gds_layer, p2.x, p2.y, dbu) if gds_layer else None

                    # AP ownership
                    x1_dbu = int(p1.x / dbu)
                    y1_dbu = int(p1.y / dbu)
                    x2_dbu = int(p2.x / dbu)
                    y2_dbu = int(p2.y / dbu)
                    ap1 = find_ap(x1_dbu, y1_dbu)
                    ap2 = find_ap(x2_dbu, y2_dbu)

                    # Gap
                    gap = -1
                    if shape1 and shape2 and shape1['bbox'] != shape2['bbox']:
                        b1, b2 = shape1['bbox'], shape2['bbox']
                        dx = max(0, max(b1[0], b2[0]) - min(b1[2], b2[2]))
                        dy = max(0, max(b1[1], b2[1]) - min(b1[3], b2[3]))
                        gap = min(dx, dy) if dx > 0 and dy > 0 else max(dx, dy)

                    # Classify: net probing + AP ownership cross-check
                    # Net probing alone is unreliable for notch cases:
                    # same-AP shapes with gap → extraction splits into 2 nets
                    # → probe_net says "cross_net" but it's actually self-collision.
                    if net1_id is not None and net2_id is not None:
                        if net1_id == net2_id:
                            collision = 'same_net'
                        elif ap1 == ap2 and ap1 != '?':
                            # Same AP, different extracted nets → notch broke connectivity
                            collision = 'notch'
                        elif ap1 != '?' and ap2 != '?':
                            collision = 'cross_device'
                        else:
                            collision = 'cross_net'
                    elif ap1 == ap2 and ap1 != '?':
                        collision = 'self_ap'
                    else:
                        collision = 'unknown'

                    result.update({
                        'gap': gap,
                        'collision': collision,
                        'net1': net1_name, 'net2': net2_name,
                        'net1_id': net1_id, 'net2_id': net2_id,
                        'ap1': ap1, 'ap2': ap2,
                        'shape1_type': shape1['type'] if shape1 else '?',
                        'shape2_type': shape2['type'] if shape2 else '?',
                        'p1': (round(p1.x, 3), round(p1.y, 3)),
                        'p2': (round(p2.x, 3), round(p2.y, 3)),
                    })
                    break  # first edge_pair only
                elif v.is_polygon():
                    poly = v.polygon()
                    bb = poly.bbox()
                    cx, cy = bb.center().x, bb.center().y

                    net_name, net_id = None, None
                    if layer_obj:
                        net_name, net_id = probe_net_at(l2n, layer_obj, cx, cy, dbu)

                    result.update({
                        'gap': -1,
                        'collision': 'polygon',
                        'net1': net_name, 'net2': None,
                        'shape1_type': f'poly({int(bb.width()*1000)}x{int(bb.height()*1000)})',
                        'shape2_type': '?',
                        'ap1': find_ap(int(cx / dbu), int(cy / dbu)),
                        'ap2': '?',
                    })
                    break

            if 'collision' not in result:
                result['collision'] = 'no_geometry'
                result['gap'] = -1
            results.append(result)

    # === Summary ===
    print(f'\n=== DRC Summary ({len(results)} violations) ===')
    rule_counts = Counter(r['rule'] for r in results)
    for rule, cnt in rule_counts.most_common():
        print(f'  {cnt:5d}  {rule}')
    print(f'  -----')
    print(f'  {len(results):5d}  TOTAL')

    # Per-rule detailed analysis
    for rule in [r for r, _ in rule_counts.most_common(8)]:
        rr = [r for r in results if r['rule'] == rule]
        ct = Counter(r['collision'] for r in rr)
        sp = Counter()
        for r in rr:
            if r.get('shape1_type') and r.get('shape2_type'):
                sp[tuple(sorted([r['shape1_type'], r['shape2_type']]))] += 1

        print(f'\n--- {rule} ({len(rr)}) ---')
        print(f'  Collision: {dict(ct)}')
        if sp:
            print(f'  Shape pairs:')
            for pair, cnt in sp.most_common(5):
                print(f'    {pair[0]:10s} ↔ {pair[1]:10s}: {cnt}')
        print(f'  Examples:')
        for r in rr[:3]:
            n1 = r.get('net1', '?') or '?'
            n2 = r.get('net2', '?') or '?'
            s1 = r.get('shape1_type', '?')
            s2 = r.get('shape2_type', '?')
            print(f'    gap={r["gap"]:3d}nm {r["collision"]:9s} '
                  f'{s1}[{n1}] ↔ {s2}[{n2}]')

    # Save JSON report
    if output_path:
        report = {
            'total': len(results),
            'by_rule': dict(rule_counts),
            'violations': results,
        }
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'\nDetailed report: {output_path}')


def main():
    parser = argparse.ArgumentParser(description='DRC violation diagnostic (KLayout RDB + L2N)')
    parser.add_argument('--lyrdb', required=True, help='KLayout .lyrdb DRC report')
    parser.add_argument('--gds', required=True, help='GDS file')
    parser.add_argument('--routing', required=True, help='routing.json')
    parser.add_argument('--output', help='Output JSON report path')
    args = parser.parse_args()
    diagnose(args.lyrdb, args.gds, args.routing, args.output)


if __name__ == '__main__':
    main()
