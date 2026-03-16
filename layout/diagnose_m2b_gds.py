#!/usr/bin/env python3
"""Diagnose M2.b from actual DRC lyrdb + routing.json shapes.

Extracts edge-pair locations from DRC output, finds nearby M2 shapes
from routing.json, and classifies each violation by source.

Covers ALL M2 sources drawn by assemble_gds.py:
  - Signal route M2 wires + Via1/Via2 M2 pads
  - Access point M2 pads + M2 stubs
  - Power drop M2 vbars + Via1/Via2 M2 pads + M2 jogs
  - Power bridge M2 vbars + Via2 M2 pads
  - Fill shapes (vbar-to-pad, via-ap-m2-gaps)
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, '.')
from atk.pdk import (
    M2_SIG_W, M2_MIN_S, VIA1_PAD, VIA2_PAD, VIA2_PAD_M2,
    METAL2, MAZE_GRID,
)
from atk.route.maze_router import M2_LYR

LYRDB = '/tmp/drc_ci_verify/ptat_vco_ptat_vco_full.lyrdb'
GDS = 'output/ptat_vco.gds'
ROUTING = 'output/routing.json'


def load_drc_m2b_edges(lyrdb_path):
    """Extract M2.b edge pairs from lyrdb."""
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


def load_routing_m2_shapes(routing_path):
    """Build a dict of ALL M2 shape rects keyed by net.

    Covers every M2 source drawn by assemble_gds.py:
      1. Signal route M2 wires (layer == M2_LYR)
      2. Signal route Via1 M2 pads (layer == -1)
      3. Signal route Via2 M2 pads (layer == -2)
      4. Access point M2 pads (via_pad.m2)
      5. Access point M2 stubs (m2_stub)
      6. Power drop Via1/Via2 M2 pads
      7. Power drop M2 vbars
      8. Power drop M2 jogs
      9. Power bridge M2 vbars + Via2 M2 pads
     10. Fill shapes: vbar-to-pad, via-ap M2 gaps
    """
    with open(routing_path) as f:
        data = json.load(f)

    hw = M2_SIG_W // 2
    v1_hp = VIA1_PAD // 2
    v2_hp = VIA2_PAD_M2 // 2  # M2 pad for Via2

    # net -> [(x1,y1,x2,y2, label)]
    shapes = defaultdict(list)

    # ── Build pin → net mapping ──
    pin_to_net = {}
    for net, rd in data.get('signal_routes', {}).items():
        for pin in rd.get('pins', []):
            pin_to_net[pin] = net

    # ── 1-3. Signal route segments ──
    m2_signal_segs = []  # for bridge conflict check later
    for net, rd in data.get('signal_routes', {}).items():
        for seg in rd.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == M2_LYR:
                if x1 == x2 and y1 != y2:
                    shapes[net].append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2),
                                        f'sig_wire_V@x={x1}'))
                elif y1 == y2 and x1 != x2:
                    shapes[net].append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw,
                                        f'sig_wire_H@y={y1}'))
                m2_signal_segs.append((x1, y1, x2, y2))
            elif lyr == -1:  # Via1 → M2 pad
                shapes[net].append((x1 - v1_hp, y1 - v1_hp, x1 + v1_hp, y1 + v1_hp,
                                    f'sig_v1pad@({x1},{y1})'))
            elif lyr == -2:  # Via2 → M2 pad
                shapes[net].append((x1 - v2_hp, y1 - v2_hp, x1 + v2_hp, y1 + v2_hp,
                                    f'sig_v2pad@({x1},{y1})'))

    # ── 4-5. Access point M2 pads + stubs ──
    for pin_id, ap in data.get('access_points', {}).items():
        net = pin_to_net.get(pin_id)
        if not net:
            continue
        m2 = ap.get('via_pad', {}).get('m2')
        if m2:
            shapes[net].append((m2[0], m2[1], m2[2], m2[3], f'ap_m2pad@{pin_id}'))
        m2_stub = ap.get('m2_stub')
        if m2_stub:
            shapes[net].append((m2_stub[0], m2_stub[1], m2_stub[2], m2_stub[3],
                                f'ap_m2stub@{pin_id}'))

    # ── 6-8. Power drops ──
    for drop in data.get('power', {}).get('drops', []):
        net = drop['net']
        inst_pin = f"{drop.get('inst','?')}.{drop.get('pin','?')}"
        v1 = drop.get('via1_pos')
        if v1:
            shapes[net].append((v1[0]-v1_hp, v1[1]-v1_hp, v1[0]+v1_hp, v1[1]+v1_hp,
                                f'pwr_v1pad@{inst_pin}'))
        v2 = drop.get('via2_pos')
        if v2:
            shapes[net].append((v2[0]-v2_hp, v2[1]-v2_hp, v2[0]+v2_hp, v2[1]+v2_hp,
                                f'pwr_v2pad@{inst_pin}'))
        m2v = drop.get('m2_vbar')
        if m2v:
            shapes[net].append((m2v[0]-hw, min(m2v[1],m2v[3]),
                               m2v[0]+hw, max(m2v[1],m2v[3]),
                               f'pwr_m2vbar@{inst_pin}'))
        # M2 jog (horizontal bar connecting via1 to offset via2)
        m2j = drop.get('m2_jog')
        if m2j:
            jog_hp = VIA1_PAD // 2  # assemble_gds uses VIA1_PAD width
            shapes[net].append((min(m2j[0], m2j[2]) - hw, m2j[1] - jog_hp,
                               max(m2j[0], m2j[2]) + hw, m2j[1] + jog_hp,
                               f'pwr_m2jog@{inst_pin}'))

    # ── 9. Power bridge M2 vbars + Via2 M2 pads ──
    # Replicate bridge computation from assemble_gds._draw_rail_bridges
    rails = data.get('power', {}).get('rails', {})
    net_rails = defaultdict(list)
    for rid, rail in rails.items():
        rnet = rail.get('net', rid)
        net_rails[rnet].append((rid, rail))

    net_idx = 0
    for bnet, rail_list in sorted(net_rails.items()):
        if len(rail_list) < 2:
            continue
        rail_list.sort(key=lambda r: r[1]['y'])
        for i in range(len(rail_list) - 1):
            _rid1, r1 = rail_list[i]
            _rid2, r2 = rail_list[i + 1]
            y1, y2 = r1['y'], r2['y']
            base_x = r1['x1'] + 1500
            bridge_x = base_x + net_idx * 2000
            # Check M2 signal conflict (same logic as assemble_gds)
            bhp = VIA2_PAD // 2
            has_conflict = False
            for sx1, sy1, sx2, sy2 in m2_signal_segs:
                sw = M2_SIG_W // 2
                seg_x1 = min(sx1, sx2) - sw
                seg_x2 = max(sx1, sx2) + sw
                seg_y1 = min(sy1, sy2)
                seg_y2 = max(sy1, sy2)
                if (bridge_x - bhp < seg_x2 and bridge_x + bhp > seg_x1 and
                        seg_y1 < y2 and seg_y2 > y1):
                    has_conflict = True
                    break
            if has_conflict:
                bridge_x = r1['x2'] - 1500 - net_idx * 2000
            # Via2 M2 pads at bridge endpoints
            shapes[bnet].append((bridge_x - v2_hp, y1 - v2_hp,
                                 bridge_x + v2_hp, y1 + v2_hp,
                                 f'bridge_v2pad@y={y1}'))
            shapes[bnet].append((bridge_x - v2_hp, y2 - v2_hp,
                                 bridge_x + v2_hp, y2 + v2_hp,
                                 f'bridge_v2pad@y={y2}'))
            # M2 vbar between (using VIA2_PAD width, same as assemble_gds)
            shapes[bnet].append((bridge_x - bhp, min(y1, y2),
                                 bridge_x + bhp, max(y1, y2),
                                 f'bridge_m2vbar@x={bridge_x}'))
        net_idx += 1

    # ── 10. Fill shapes: vbar-to-pad ──
    # Replicate _fill_vbar_to_pad logic
    for drop in data.get('power', {}).get('drops', []):
        net = drop['net']
        m2v = drop.get('m2_vbar')
        if not m2v:
            continue
        inst_pin = f"{drop.get('inst','?')}.{drop.get('pin','?')}"
        # Find access point for this drop's pin
        ap_key = f"{drop.get('inst','')}.{drop.get('pin','')}"
        ap = data.get('access_points', {}).get(ap_key)
        if not ap:
            continue
        m2_pad = ap.get('via_pad', {}).get('m2')
        if not m2_pad:
            continue
        vbar_x1 = m2v[0] - hw
        vbar_x2 = m2v[0] + hw
        vbar_y1 = min(m2v[1], m2v[3])
        vbar_y2 = max(m2v[1], m2v[3])
        fill_x1 = min(vbar_x2, m2_pad[2])
        fill_x2 = max(vbar_x1, m2_pad[0])
        if fill_x1 >= fill_x2:
            continue  # no gap
        fill_y1 = max(vbar_y1, m2_pad[1])
        fill_y2 = min(vbar_y2, m2_pad[3])
        if fill_y1 < fill_y2:
            shapes[net].append((fill_x1, fill_y1, fill_x2, fill_y2,
                                f'fill_vbar2pad@{inst_pin}'))

    # ── 10b. Fill shapes: via-ap M2 gaps ──
    # Replicate _fill_via_ap_m2_gaps logic
    for net, rd in data.get('signal_routes', {}).items():
        via_m2_pads = []
        for seg in rd.get('segments', []):
            if len(seg) >= 5 and seg[4] == -1:
                x, y = seg[0], seg[1]
                via_m2_pads.append((x - v1_hp, y - v1_hp, x + v1_hp, y + v1_hp))
        if not via_m2_pads:
            continue
        for pin_id in rd.get('pins', []):
            ap = data.get('access_points', {}).get(pin_id)
            if not ap:
                continue
            pad = ap.get('via_pad', {}).get('m2')
            if not pad:
                continue
            for via_m2 in via_m2_pads:
                # X-aligned fill (same X range, vertical gap)
                ox = max(via_m2[0], pad[0])
                ox2 = min(via_m2[2], pad[2])
                if ox < ox2:
                    fy1 = min(via_m2[3], pad[3])
                    fy2 = max(via_m2[1], pad[1])
                    if fy1 < fy2:
                        shapes[net].append((ox, fy1, ox2, fy2,
                                            f'fill_via2ap@{pin_id}'))
                # Y-aligned fill (same Y range, horizontal gap)
                oy = max(via_m2[1], pad[1])
                oy2 = min(via_m2[3], pad[3])
                if oy < oy2:
                    fx1 = min(via_m2[2], pad[2])
                    fx2 = max(via_m2[0], pad[0])
                    if fx1 < fx2:
                        shapes[net].append((fx1, oy, fx2, oy2,
                                            f'fill_via2ap@{pin_id}'))

    # Print shape stats
    total = sum(len(s) for s in shapes.values())
    by_type = defaultdict(int)
    for ss in shapes.values():
        for s in ss:
            label = s[4].split('@')[0]
            by_type[label] += 1
    print(f"Total M2 shapes modeled: {total}")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print()

    return dict(shapes)


def identify_edge_shape(e, routing_shapes):
    """Try to identify which routing shape an edge belongs to."""
    # Edge is (x1,y1,x2,y2). Check which shapes contain/touch this edge.
    ex_min = min(e[0], e[2])
    ex_max = max(e[0], e[2])
    ey_min = min(e[1], e[3])
    ey_max = max(e[1], e[3])

    best = None
    best_dist = 99999
    EDGE_TOL = 15  # nm tolerance for edge-to-boundary matching
    OVERLAP_TOL = 100  # nm tolerance for overlap check

    for net, shapes in routing_shapes.items():
        for rect in shapes:
            rx1, ry1, rx2, ry2, label = rect
            # Check if edge is on a boundary of this rect
            # For horizontal edge at y: check if y matches rect top or bottom
            if ey_min == ey_max:  # horizontal edge
                y = ey_min
                if (abs(y - ry1) <= EDGE_TOL or abs(y - ry2) <= EDGE_TOL):
                    # X overlap check
                    if ex_min < rx2 + OVERLAP_TOL and ex_max > rx1 - OVERLAP_TOL:
                        dist = min(abs(y - ry1), abs(y - ry2))
                        if dist < best_dist:
                            best_dist = dist
                            best = (net, label, rect[:4])
            elif ex_min == ex_max:  # vertical edge
                x = ex_min
                if (abs(x - rx1) <= EDGE_TOL or abs(x - rx2) <= EDGE_TOL):
                    if ey_min < ry2 + OVERLAP_TOL and ey_max > ry1 - OVERLAP_TOL:
                        dist = min(abs(x - rx1), abs(x - rx2))
                        if dist < best_dist:
                            best_dist = dist
                            best = (net, label, rect[:4])

    return best  # (net, label, rect) or None


def main():
    edges = load_drc_m2b_edges(LYRDB)
    routing_shapes = load_routing_m2_shapes(ROUTING)

    print(f"=== M2.b DRC violations: {len(edges)} from lyrdb ===\n")

    buckets = defaultdict(list)

    for idx, (e1, e2) in enumerate(edges):
        # Classify edge orientations
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

        # Try to identify shapes
        s1 = identify_edge_shape(e1, routing_shapes)
        s2 = identify_edge_shape(e2, routing_shapes)

        s1_label = f"{s1[0]}:{s1[1]}" if s1 else "UNMATCHED"
        s2_label = f"{s2[0]}:{s2[1]}" if s2 else "UNMATCHED"

        # Cross-net or same-net?
        net1 = s1[0] if s1 else "?"
        net2 = s2[0] if s2 else "?"
        if net1 == net2 and net1 != "?":
            net_rel = "same"
        else:
            net_rel = "cross"

        # Shape type pair
        t1 = s1[1] if s1 else "unmatched"
        t2 = s2[1] if s2 else "unmatched"
        pair = f"{min(t1,t2)} — {max(t1,t2)}"

        center_x = (min(e1[0],e1[2],e2[0],e2[2]) + max(e1[0],e1[2],e2[0],e2[2])) // 2
        center_y = (min(e1[1],e1[3],e2[1],e2[3]) + max(e1[1],e1[3],e2[1],e2[3])) // 2

        print(f"V{idx+1:2d}: gap={gap:3d}nm {orient} {net_rel:5s} {pair}")
        print(f"      e1={s1_label}  e2={s2_label}")
        print(f"      loc=({center_x},{center_y})")

        bucket_key = pair
        buckets[bucket_key].append({
            'gap': gap, 'orient': orient, 'net_rel': net_rel,
            's1': s1_label, 's2': s2_label,
        })

    # Summary table
    print(f"\n{'='*70}")
    print(f"Summary: {len(edges)} M2.b violations")
    print(f"{'='*70}\n")

    print(f"{'Pattern':<40s} {'Count':>5s} {'same':>5s} {'cross':>5s}  gap range")
    print("-" * 75)
    for key in sorted(buckets.keys(), key=lambda k: -len(buckets[k])):
        items = buckets[key]
        same = sum(1 for i in items if i['net_rel'] == 'same')
        cross = sum(1 for i in items if i['net_rel'] != 'same')
        gaps = [i['gap'] for i in items]
        gap_range = f"{min(gaps)}-{max(gaps)}nm"
        print(f"{key:<40s} {len(items):>5d} {same:>5d} {cross:>5d}  {gap_range}")

    # Count identified vs unidentified
    n_both = sum(1 for e1, e2 in edges
                 if identify_edge_shape(e1, routing_shapes) and
                    identify_edge_shape(e2, routing_shapes))
    n_one = sum(1 for e1, e2 in edges
                if bool(identify_edge_shape(e1, routing_shapes)) !=
                   bool(identify_edge_shape(e2, routing_shapes)))
    n_none = len(edges) - n_both - n_one
    print(f"\nEdge identification:")
    print(f"  Both edges matched routing: {n_both}")
    print(f"  One edge matched: {n_one}")
    print(f"  Neither matched (unmodeled M2 source): {n_none}")


if __name__ == '__main__':
    main()
