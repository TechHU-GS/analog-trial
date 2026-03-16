#!/usr/bin/env python3
"""Diagnose M1.b and M1.a DRC violations.

For each violation edge-pair, identify the source shapes (routing wire,
via pad, access point pad, gate contact pad, bus strap) and classify.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

sys.path.insert(0, '.')
from atk.pdk import (
    VIA1_PAD_M1, VIA1_PAD, M1_SIG_W, M1_MIN_W, M1_MIN_S,
    M1_THIN, CONT_SZ, CONT_ENC_M1_END,
)

UM = 1000  # nm per µm


def parse_edge_pairs(lyrdb_path, rule="'M1.b'"):
    """Extract edge-pair coordinates from DRC lyrdb."""
    tree = ET.parse(lyrdb_path)
    root = tree.getroot()
    items = root[7]
    pairs = []
    for item in items:
        cat = item.find('category')
        if cat is None:
            continue
        r = cat.text.strip().split(':')[0] if cat.text else ''
        if r != rule:
            continue
        vals = item.find('values')
        if vals is None:
            continue
        for v in vals:
            txt = v.text.strip() if v.text else ''
            m = re.match(
                r'edge-pair:\s*\(([^)]+)\)\|\(([^)]+)\)', txt)
            if not m:
                continue
            def parse_edge(s):
                p1, p2 = s.split(';')
                x1, y1 = [float(c) for c in p1.split(',')]
                x2, y2 = [float(c) for c in p2.split(',')]
                return (x1 * UM, y1 * UM, x2 * UM, y2 * UM)
            e1 = parse_edge(m.group(1))
            e2 = parse_edge(m.group(2))
            pairs.append((e1, e2))
    return pairs


def load_m1_shapes(routing_path):
    """Load all M1 shapes from routing.json as classified rectangles."""
    with open(routing_path) as f:
        data = json.load(f)

    shapes = []  # (category, net, x1, y1, x2, y2, label)
    hw = M1_SIG_W // 2  # 150nm
    hp_m1 = VIA1_PAD_M1 // 2  # 185nm

    # Pin→net map
    pin_to_net = {}
    for rd_name in ('signal_routes', 'pre_routes'):
        for net, rd in data.get(rd_name, {}).items():
            for pk in rd.get('pins', []):
                pin_to_net[pk] = net

    # Signal/pre-route wire segments on M1
    for rd_name in ('signal_routes', 'pre_routes'):
        for net, rd in data.get(rd_name, {}).items():
            for seg in rd.get('segments', []):
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, lyr = seg[:5]
                if lyr == 0:  # M1 wire
                    if x1 == x2:  # vertical
                        shapes.append(('sig_wire', net,
                                       x1 - hw, min(y1, y2),
                                       x1 + hw, max(y1, y2),
                                       f'wire_{net}'))
                    elif y1 == y2:  # horizontal
                        shapes.append(('sig_wire', net,
                                       min(x1, x2), y1 - hw,
                                       max(x1, x2), y1 + hw,
                                       f'wire_{net}'))
                elif lyr == -1:  # via1 → M1 pad
                    shapes.append(('v1pad', net,
                                   x1 - hp_m1, y1 - hp_m1,
                                   x1 + hp_m1, y1 + hp_m1,
                                   f'v1pad_{net}@({x1},{y1})'))

    # Access point M1 pads + stubs
    ap_data = data.get('access_points', {})
    for pk, ap in ap_data.items():
        net = pin_to_net.get(pk, '?')
        vp = ap.get('via_pad', {})
        if 'm1' in vp:
            r = vp['m1']
            shapes.append(('ap_m1pad', net,
                           r[0], r[1], r[2], r[3],
                           f'ap_{pk}'))
        stub = ap.get('m1_stub')
        if stub:
            shapes.append(('m1_stub', net,
                           stub[0], stub[1], stub[2], stub[3],
                           f'stub_{pk}'))

    # Bus straps (from routing.json if present, else heuristic)
    # Bus straps are drawn by assemble_gds section 2c
    # They're not in routing.json — we need to infer from DRC geometry

    return shapes, data


def edge_midpoint(edge):
    return ((edge[0] + edge[2]) / 2, (edge[1] + edge[3]) / 2)


def edge_near_rect(edge, x1, y1, x2, y2, margin=100):
    for px, py in [(edge[0], edge[1]), (edge[2], edge[3]),
                   ((edge[0]+edge[2])/2, (edge[1]+edge[3])/2)]:
        if x1 - margin <= px <= x2 + margin and y1 - margin <= py <= y2 + margin:
            return True
    return False


def classify_edge(edge, shapes):
    best = None
    best_dist = float('inf')
    mx, my = edge_midpoint(edge)
    for cat, net, x1, y1, x2, y2, label in shapes:
        if edge_near_rect(edge, x1, y1, x2, y2, margin=200):
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            d = abs(mx - cx) + abs(my - cy)
            if d < best_dist:
                best_dist = d
                best = (cat, net, label)
    return best


def analyze_m1_fill_gaps(routing_path):
    """Simulate _fill_same_net_gaps for M1 and report what it finds."""
    with open(routing_path) as f:
        data = json.load(f)

    hw = M1_SIG_W // 2  # 150nm
    hp_m1 = VIA1_PAD_M1 // 2  # 185nm
    min_w = M1_MIN_W  # 160nm
    min_s = M1_MIN_S  # 180nm

    pin_to_net = {}
    for rd_name in ('signal_routes', 'pre_routes'):
        for net, rd in data.get(rd_name, {}).items():
            for pk in rd.get('pins', []):
                pin_to_net[pk] = net

    net_shapes = defaultdict(list)
    ap_data = data.get('access_points', {})

    for rd_name in ('signal_routes', 'pre_routes'):
        for net, rd in data.get(rd_name, {}).items():
            for seg in rd.get('segments', []):
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, lyr = seg[:5]
                if lyr == 0:  # M1 wire
                    if x1 == x2:
                        net_shapes[net].append(
                            (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2), 'wire'))
                    elif y1 == y2:
                        net_shapes[net].append(
                            (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw, 'wire'))
                elif lyr == -1:  # via1 → M1 pad
                    net_shapes[net].append(
                        (x1 - hp_m1, y1 - hp_m1, x1 + hp_m1, y1 + hp_m1, 'v1pad'))

            # AP pads + stubs
            for pk in rd.get('pins', []):
                ap = ap_data.get(pk)
                if not ap:
                    continue
                vp = ap.get('via_pad', {})
                if 'm1' in vp:
                    r = vp['m1']
                    net_shapes[net].append((r[0], r[1], r[2], r[3], f'ap_{pk}'))
                stub = ap.get('m1_stub')
                if stub:
                    net_shapes[net].append(
                        (stub[0], stub[1], stub[2], stub[3], f'stub_{pk}'))

    # Find all pairs with gaps or overlaps
    print("\n=== M1 same-net shape pair analysis ===\n")
    gap_fills = 0
    overlap_notches = 0
    touch_cases = 0

    for net, shapes in sorted(net_shapes.items()):
        if len(shapes) < 2:
            continue
        for i in range(len(shapes)):
            a = shapes[i]
            for j in range(i+1, len(shapes)):
                b = shapes[j]
                x_gap = max(a[0] - b[2], b[0] - a[2])
                y_gap = max(a[1] - b[3], b[1] - a[3])

                # Gap case: 0 < gap < min_s with overlap
                if x_gap > 0 and x_gap < min_s and y_gap < 0:
                    overlap_h = min(a[3], b[3]) - max(a[1], b[1])
                    ext = ""
                    if overlap_h < min_w:
                        ext = f" (extended: overlap_h={overlap_h} < min_w={min_w})"
                    print(f"  GAP_X={x_gap:4d} net={net:20s} {a[4]:20s} vs {b[4]:20s}"
                          f" overlap_h={overlap_h}{ext}")
                    gap_fills += 1
                elif y_gap > 0 and y_gap < min_s and x_gap < 0:
                    overlap_w = min(a[2], b[2]) - max(a[0], b[0])
                    ext = ""
                    if overlap_w < min_w:
                        ext = f" (extended: overlap_w={overlap_w} < min_w={min_w})"
                    print(f"  GAP_Y={y_gap:4d} net={net:20s} {a[4]:20s} vs {b[4]:20s}"
                          f" overlap_w={overlap_w}{ext}")
                    gap_fills += 1
                elif x_gap == 0 or y_gap == 0:
                    print(f"  TOUCH     net={net:20s} {a[4]:20s} vs {b[4]:20s}"
                          f" x_gap={x_gap} y_gap={y_gap}")
                    touch_cases += 1
                elif x_gap < 0 and y_gap < 0:
                    # Overlap → check for width step notch
                    a_w = a[2] - a[0]
                    a_h = a[3] - a[1]
                    b_w = b[2] - b[0]
                    b_h = b[3] - b[1]
                    # Horizontal notch (width change in X)
                    if a_w != b_w:
                        step_left = abs(min(a[0], b[0]) - max(a[0], b[0]))
                        step_right = abs(min(a[2], b[2]) - max(a[2], b[2]))
                        if 0 < step_left < min_s or 0 < step_right < min_s:
                            print(f"  NOTCH_X   net={net:20s} {a[4]:20s}(w={a_w}) vs {b[4]:20s}(w={b_w})"
                                  f" step_L={step_left} step_R={step_right}")
                            overlap_notches += 1
                    if a_h != b_h:
                        step_bot = abs(min(a[1], b[1]) - max(a[1], b[1]))
                        step_top = abs(min(a[3], b[3]) - max(a[3], b[3]))
                        if 0 < step_bot < min_s or 0 < step_top < min_s:
                            print(f"  NOTCH_Y   net={net:20s} {a[4]:20s}(h={a_h}) vs {b[4]:20s}(h={b_h})"
                                  f" step_B={step_bot} step_T={step_top}")
                            overlap_notches += 1

    print(f"\n  Summary: gap_fills={gap_fills}, overlap_notches={overlap_notches}, "
          f"touch_cases={touch_cases}")


def main():
    lyrdb = '/tmp/drc_r10e/ptat_vco_ptat_vco_full.lyrdb'
    routing = 'output/routing.json'

    # 1. Classify DRC violations
    for rule_name in ("'M1.b'", "'M1.a'"):
        pairs = parse_edge_pairs(lyrdb, rule_name)
        shapes, data = load_m1_shapes(routing)
        print(f"\n=== {rule_name} Classification ({len(pairs)} violations) ===\n")

        categories = Counter()
        for e1, e2 in pairs:
            c1 = classify_edge(e1, shapes)
            c2 = classify_edge(e2, shapes)

            if c1 and c2:
                cats = sorted([c1[0], c2[0]])
                key = f"{cats[0]}-{cats[1]}"
                same_net = c1[1] == c2[1]
            elif c1:
                key = f"{c1[0]}-?"
                same_net = False
            elif c2:
                key = f"?-{c2[0]}"
                same_net = False
            else:
                key = "?-?"
                same_net = False

            net_str = f"SAME({c1[1]})" if same_net else f"CROSS({c1[1] if c1 else '?'}/{c2[1] if c2 else '?'})"
            mx1, my1 = edge_midpoint(e1)
            mx2, my2 = edge_midpoint(e2)

            # Compute edge length and gap
            e1_len = max(abs(e1[2]-e1[0]), abs(e1[3]-e1[1]))
            e2_len = max(abs(e2[2]-e2[0]), abs(e2[3]-e2[1]))
            # Distance between edges (approximation)
            gap = ((mx1-mx2)**2 + (my1-my2)**2)**0.5

            categories[key + (' SAME' if same_net else ' CROSS')] += 1
            print(f"  ({mx1/UM:.3f},{my1/UM:.3f}) → ({mx2/UM:.3f},{my2/UM:.3f})"
                  f"  gap≈{gap:.0f}nm  {key}  {net_str}"
                  f"  {c1[2] if c1 else '?'} vs {c2[2] if c2 else '?'}")

        print(f"\n  Summary:")
        for cat, cnt in categories.most_common():
            print(f"    {cat:35s}: {cnt}")

    # 2. Simulate gap fills to see what's being caught
    analyze_m1_fill_gaps(routing)


if __name__ == '__main__':
    main()
