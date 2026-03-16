#!/usr/bin/env python3
"""Diagnose M2.b: match DRC lyrdb edge-pairs to actual GDS M2 shapes.

Runs in KLayout script mode:
  klayout -n sg13g2 -zz -r diagnose_m2b_klayout.py

Reads DRC lyrdb to get M2.b violation edge-pairs, then finds the
actual M2 GDS shapes each edge belongs to. Labels each shape by
cross-referencing with routing.json for net assignment.
"""
import pya
import json
import sys
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

# ── Paths ──
LYRDB = '/tmp/drc_ci_verify/ptat_vco_ptat_vco_full.lyrdb'
GDS = 'output/ptat_vco.gds'
ROUTING = 'output/routing.json'

# ── PDK constants (inline to avoid import issues in KLayout env) ──
M2_LAYER = 10
M2_DATATYPE = 0
M2_SIG_W = 300  # nm
M2_MIN_S = 210  # nm
VIA1_PAD = 480  # nm


def load_drc_m2b_edges(lyrdb_path):
    """Extract M2.b edge pairs from lyrdb. Returns [(e1, e2), ...]
    where each edge is (x1_nm, y1_nm, x2_nm, y2_nm)."""
    tree = ET.parse(lyrdb_path)
    root = tree.getroot()
    items = root.find('items').findall('item')
    edges = []
    for item in items:
        cat = item.find('category').text.strip("'")
        if cat != 'M2.b':
            continue
        vals = item.find('values')
        if vals is None:
            continue
        for v in vals.findall('value'):
            txt = v.text.strip() if v.text else ''
            if 'edge-pair' not in txt:
                continue
            parts = txt.split('|')
            if len(parts) != 2:
                continue
            def parse_edge(s):
                s = s.replace('edge-pair:', '').strip().strip('()')
                pts = s.split(';')
                if len(pts) != 2:
                    return None
                p1 = [round(float(x) * 1000) for x in pts[0].split(',')]
                p2 = [round(float(x) * 1000) for x in pts[1].split(',')]
                return (p1[0], p1[1], p2[0], p2[1])
            e1 = parse_edge(parts[0])
            e2 = parse_edge(parts[1])
            if e1 and e2:
                edges.append((e1, e2))
    return edges


def load_m2_gds_shapes(gds_path):
    """Load all M2 shapes from GDS as a list of (x1, y1, x2, y2) bboxes."""
    layout = pya.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    if top is None:
        print("ERROR: no top cell found")
        return []

    li_m2 = None
    for li in layout.layer_indices():
        info = layout.get_info(li)
        if info.layer == M2_LAYER and info.datatype == M2_DATATYPE:
            li_m2 = li
            break
    if li_m2 is None:
        print("ERROR: M2 layer not found in GDS")
        return []

    # Flatten and collect all M2 shapes
    shapes = []
    ri = pya.RecursiveShapeIterator(layout, top, li_m2)
    while not ri.at_end():
        shape = ri.shape()
        trans = ri.trans()
        if shape.is_box():
            box = shape.box.transformed(trans)
            shapes.append((box.left, box.bottom, box.right, box.top))
        elif shape.is_polygon():
            bbox = shape.polygon.transformed(trans).bbox()
            shapes.append((bbox.left, bbox.bottom, bbox.right, bbox.top))
        elif shape.is_path():
            bbox = shape.path.polygon().transformed(trans).bbox()
            shapes.append((bbox.left, bbox.bottom, bbox.right, bbox.top))
        ri.next()
    return shapes


def build_routing_m2_labels(routing_path):
    """Build spatial index of routing M2 shapes for net labeling.
    Returns list of (x1, y1, x2, y2, net, label)."""
    with open(routing_path) as f:
        data = json.load(f)

    hw = M2_SIG_W // 2
    hp = VIA1_PAD // 2
    labeled = []

    # Pin → net mapping
    pin_to_net = {}
    for net, rd in data.get('signal_routes', {}).items():
        for pin in rd.get('pins', []):
            pin_to_net[pin] = net

    # Signal route segments
    for net, rd in data.get('signal_routes', {}).items():
        for seg in rd.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == 1:  # M2
                if x1 == x2 and y1 != y2:
                    labeled.append((x1-hw, min(y1,y2), x1+hw, max(y1,y2),
                                    net, 'sig_wire_V'))
                elif y1 == y2 and x1 != x2:
                    labeled.append((min(x1,x2), y1-hw, max(x1,x2), y1+hw,
                                    net, 'sig_wire_H'))
            elif lyr == -1:  # Via1
                labeled.append((x1-hp, y1-hp, x1+hp, y1+hp, net, 'sig_v1pad'))
            elif lyr == -2:  # Via2
                labeled.append((x1-hp, y1-hp, x1+hp, y1+hp, net, 'sig_v2pad'))

    # AP M2 pads
    for pin_id, ap in data.get('access_points', {}).items():
        net = pin_to_net.get(pin_id)
        if not net:
            continue
        m2 = ap.get('via_pad', {}).get('m2')
        if m2:
            labeled.append((m2[0], m2[1], m2[2], m2[3], net, f'ap_m2pad@{pin_id}'))

    # Power drops
    for drop in data.get('power', {}).get('drops', []):
        net = drop['net']
        tag = f"{drop.get('inst','?')}.{drop.get('pin','?')}"
        v1 = drop.get('via1_pos')
        if v1:
            labeled.append((v1[0]-hp, v1[1]-hp, v1[0]+hp, v1[1]+hp,
                            net, f'pwr_v1pad@{tag}'))
        v2 = drop.get('via2_pos')
        if v2:
            labeled.append((v2[0]-hp, v2[1]-hp, v2[0]+hp, v2[1]+hp,
                            net, f'pwr_v2pad@{tag}'))
        m2v = drop.get('m2_vbar')
        if m2v:
            labeled.append((m2v[0]-hw, min(m2v[1],m2v[3]),
                            m2v[0]+hw, max(m2v[1],m2v[3]),
                            net, f'pwr_m2vbar@{tag}'))
        m2j = drop.get('m2_jog')
        if m2j:
            jog_hp = VIA1_PAD // 2
            labeled.append((min(m2j[0],m2j[2])-hw, m2j[1]-jog_hp,
                            max(m2j[0],m2j[2])+hw, m2j[1]+jog_hp,
                            net, f'pwr_m2jog@{tag}'))

    return labeled


def find_gds_shape_for_edge(edge, gds_shapes):
    """Find the GDS M2 shape whose boundary contains this edge.
    Returns (x1, y1, x2, y2) or None."""
    ex_min = min(edge[0], edge[2])
    ex_max = max(edge[0], edge[2])
    ey_min = min(edge[1], edge[3])
    ey_max = max(edge[1], edge[3])

    best = None
    best_dist = 99999

    for rect in gds_shapes:
        rx1, ry1, rx2, ry2 = rect
        if ey_min == ey_max:  # horizontal edge
            y = ey_min
            d_bot = abs(y - ry1)
            d_top = abs(y - ry2)
            d = min(d_bot, d_top)
            if d <= 3:  # 3nm tolerance
                if ex_min <= rx2 + 5 and ex_max >= rx1 - 5:
                    if d < best_dist:
                        best_dist = d
                        best = rect
        elif ex_min == ex_max:  # vertical edge
            x = ex_min
            d_left = abs(x - rx1)
            d_right = abs(x - rx2)
            d = min(d_left, d_right)
            if d <= 3:
                if ey_min <= ry2 + 5 and ey_max >= ry1 - 5:
                    if d < best_dist:
                        best_dist = d
                        best = rect
    return best


def label_gds_shape(shape_rect, routing_labels):
    """Match a GDS shape rect to a routing label by bbox overlap.
    Returns (net, label) or ('?', 'gds_only')."""
    if shape_rect is None:
        return ('?', 'edge_not_found')

    sx1, sy1, sx2, sy2 = shape_rect
    best = None
    best_overlap = 0

    for rx1, ry1, rx2, ry2, net, label in routing_labels:
        # Compute overlap area
        ox1 = max(sx1, rx1)
        oy1 = max(sy1, ry1)
        ox2 = min(sx2, rx2)
        oy2 = min(sy2, ry2)
        if ox1 < ox2 and oy1 < oy2:
            area = (ox2 - ox1) * (oy2 - oy1)
            if area > best_overlap:
                best_overlap = area
                best = (net, label)

    if best:
        return best

    # Try proximity match (for fills that extend beyond routing shapes)
    best_dist = 99999
    for rx1, ry1, rx2, ry2, net, label in routing_labels:
        # Check if shapes are very close (touching or nearly)
        xg = max(sx1 - rx2, rx1 - sx2)
        yg = max(sy1 - ry2, ry1 - sy2)
        if xg <= 20 and yg <= 20:
            dist = max(xg, yg)
            if dist < best_dist:
                best_dist = dist
                best = (net, f'fill_near:{label}')

    if best and best_dist <= 20:
        return best

    return ('?', f'gds_only({sx1},{sy1},{sx2},{sy2})')


def main():
    if not os.path.exists(LYRDB):
        print(f"ERROR: lyrdb not found: {LYRDB}")
        return
    if not os.path.exists(GDS):
        print(f"ERROR: GDS not found: {GDS}")
        return

    print("Loading DRC violations...")
    edges = load_drc_m2b_edges(LYRDB)
    print(f"  {len(edges)} M2.b violations\n")

    print("Loading GDS M2 shapes...")
    gds_shapes = load_m2_gds_shapes(GDS)
    print(f"  {len(gds_shapes)} M2 shapes in GDS\n")

    print("Loading routing labels...")
    routing_labels = build_routing_m2_labels(ROUTING)
    print(f"  {len(routing_labels)} labeled shapes from routing.json\n")

    print(f"{'='*80}")
    print(f"M2.b DRC Violations: {len(edges)}")
    print(f"{'='*80}\n")

    buckets = defaultdict(list)

    for idx, (e1, e2) in enumerate(edges):
        # Find GDS shapes for each edge
        gs1 = find_gds_shape_for_edge(e1, gds_shapes)
        gs2 = find_gds_shape_for_edge(e2, gds_shapes)

        # Label shapes by routing
        net1, lab1 = label_gds_shape(gs1, routing_labels)
        net2, lab2 = label_gds_shape(gs2, routing_labels)

        # Gap
        e1_h = abs(e1[1] - e1[3]) <= 2
        e2_h = abs(e2[1] - e2[3]) <= 2
        if e1_h and e2_h:
            gap = abs(e1[1] - e2[1])
            orient = 'H'
        elif not e1_h and not e2_h:
            gap = abs(e1[0] - e2[0])
            orient = 'V'
        else:
            gap = 0
            orient = 'X'

        # Net relation
        if net1 == net2 and net1 != '?':
            net_rel = 'same'
        else:
            net_rel = 'cross'

        # Shape sizes
        sz1 = f"{gs1[2]-gs1[0]}x{gs1[3]-gs1[1]}" if gs1 else "?"
        sz2 = f"{gs2[2]-gs2[0]}x{gs2[3]-gs2[1]}" if gs2 else "?"

        center_x = (min(e1[0],e1[2],e2[0],e2[2]) + max(e1[0],e1[2],e2[0],e2[2])) // 2
        center_y = (min(e1[1],e1[3],e2[1],e2[3]) + max(e1[1],e1[3],e2[1],e2[3])) // 2

        # Categorize label
        cat1 = lab1.split('@')[0].split('(')[0].rstrip(':')
        cat2 = lab2.split('@')[0].split('(')[0].rstrip(':')

        print(f"V{idx+1:2d}: gap={gap:3d}nm {orient} {net_rel:5s}")
        print(f"  e1: {net1:20s} {lab1}  sz={sz1}")
        print(f"  e2: {net2:20s} {lab2}  sz={sz2}")
        print(f"  loc=({center_x},{center_y})")

        pair = f"{min(cat1,cat2)} — {max(cat1,cat2)}"
        buckets[pair].append({
            'gap': gap, 'orient': orient, 'net_rel': net_rel,
            'net1': net1, 'net2': net2,
            'lab1': lab1, 'lab2': lab2,
        })

    # Summary
    print(f"\n{'='*80}")
    print(f"Summary: {len(edges)} M2.b violations")
    print(f"{'='*80}\n")

    print(f"{'Pattern':<50s} {'Tot':>4s} {'same':>4s} {'cross':>5s}  gap range")
    print("-" * 80)
    for key in sorted(buckets.keys(), key=lambda k: -len(buckets[k])):
        items = buckets[key]
        same = sum(1 for i in items if i['net_rel'] == 'same')
        cross = len(items) - same
        gaps = [i['gap'] for i in items]
        gap_range = f"{min(gaps)}-{max(gaps)}nm"
        print(f"{key:<50s} {len(items):>4d} {same:>4d} {cross:>5d}  {gap_range}")
    print("-" * 80)
    print(f"{'TOTAL':<50s} {len(edges):>4d}")

    # Net pair summary
    print(f"\nCross-net pairs:")
    net_pairs = defaultdict(int)
    for items in buckets.values():
        for i in items:
            if i['net_rel'] == 'cross':
                na, nb = min(i['net1'], i['net2']), max(i['net1'], i['net2'])
                net_pairs[(na, nb)] += 1
    for (na, nb), cnt in sorted(net_pairs.items(), key=lambda x: -x[1]):
        print(f"  {na} — {nb}: {cnt}")


if __name__ == '__main__':
    main()
