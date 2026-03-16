#!/usr/bin/env python3
"""Detailed M3.b violation analysis: for each edge-pair, identify both
shapes from routing.json and check if either endpoint can be trimmed.

Outputs per violation:
  - Edge-pair coordinates and gap
  - Shape A and Shape B identification (net, type, segment coords)
  - Whether each shape's nearest endpoint is at a via position
  - Whether the OTHER shape's endpoint could be trimmed
"""
import json
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, '.')
from atk.pdk import (
    M3_MIN_S, M3_MIN_W, VIA2_PAD_M3, VIA3_PAD,
    MAZE_GRID,
)
from atk.route.maze_router import M3_LYR, VIA2_SEG, VIA3_SEG

UM = 1000
LYRDB = '/tmp/drc_r12/ptat_vco_ptat_vco_full.lyrdb'
ROUTING = 'output/routing.json'

M3_SIG_W = 300  # M2_SIG_W used for M3
HW = M3_SIG_W // 2


def parse_edge(s):
    p1, p2 = s.split(';')
    x1, y1 = [float(c) for c in p1.split(',')]
    x2, y2 = [float(c) for c in p2.split(',')]
    return (x1*UM, y1*UM, x2*UM, y2*UM)


def load_violations():
    tree = ET.parse(LYRDB)
    root = tree.getroot()
    viols = []
    for item in root.iter('item'):
        cat = item.find('category')
        if cat is None or not cat.text:
            continue
        r = cat.text.strip().split(':')[0].strip("'")
        if r != 'M3.b':
            continue
        vals = item.find('values')
        if vals is None:
            continue
        for v in vals:
            txt = v.text.strip() if v.text else ''
            m = re.match(r'edge-pair:\s*\(([^)]+)\)\|\(([^)]+)\)', txt)
            if not m:
                continue
            e1 = parse_edge(m.group(1))
            e2 = parse_edge(m.group(2))
            viols.append((e1, e2))
    return viols


def load_m3_data():
    with open(ROUTING) as f:
        routing = json.load(f)

    # Collect all M3 segments and via positions
    m3_segs = []  # (x1, y1, x2, y2, net, seg_idx)
    via_pos = set()  # (x, y) for via2 and via3

    all_routes = {}
    for rk in ('signal_routes', 'pre_routes'):
        for net, route in routing.get(rk, {}).items():
            all_routes[net] = route

    for net, route in all_routes.items():
        for idx, seg in enumerate(route.get('segments', [])):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == M3_LYR:
                m3_segs.append((x1, y1, x2, y2, net, idx))
            elif lyr == VIA2_SEG or lyr == VIA3_SEG:
                via_pos.add((x1, y1))

    # Power M3 shapes
    power_shapes = []  # (category, net, x1, y1, x2, y2, label)
    for rid, rail in routing.get('power', {}).get('rails', {}).items():
        hw_r = rail['width'] // 2
        net = rail.get('net', rid)
        power_shapes.append(('rail', net,
            rail['x1'], rail['y'] - hw_r, rail['x2'], rail['y'] + hw_r,
            f'rail_{rid}'))

    for drop in routing.get('power', {}).get('drops', []):
        vbar = drop.get('m3_vbar')
        if not vbar:
            continue
        net = drop['net']
        vhw = M3_MIN_W // 2
        x = vbar[0]
        y1 = min(vbar[1], vbar[3])
        y2 = max(vbar[1], vbar[3])
        power_shapes.append(('vbar', net,
            x - vhw, y1, x + vhw, y2,
            f"vbar_{drop['inst']}.{drop['pin']}"))
        # Via2 pad
        v2 = drop.get('via2_pos')
        if v2:
            hp = VIA2_PAD_M3 // 2
            power_shapes.append(('v2pad', net,
                v2[0] - hp, v2[1] - hp, v2[0] + hp, v2[1] + hp,
                f"v2pad_{drop['inst']}.{drop['pin']}"))
            via_pos.add((v2[0], v2[1]))

    return m3_segs, via_pos, power_shapes, routing


def find_shape_for_edge(edge, m3_segs, power_shapes):
    """Find the M3 shape that an edge belongs to."""
    mx = (edge[0] + edge[2]) / 2
    my = (edge[1] + edge[3]) / 2

    best = None
    best_d = float('inf')

    # Check signal/pre-route M3 segments
    for x1, y1, x2, y2, net, idx in m3_segs:
        if x1 == x2:  # vertical
            sx1, sx2 = x1 - HW, x1 + HW
            sy1, sy2 = min(y1, y2), max(y1, y2)
        elif y1 == y2:  # horizontal
            sx1, sx2 = min(x1, x2), max(x1, x2)
            sy1, sy2 = y1 - HW, y1 + HW
        else:
            continue
        # Check proximity
        dx = max(sx1 - mx, mx - sx2, 0)
        dy = max(sy1 - my, my - sy2, 0)
        d = dx + dy
        if d < 200 and d < best_d:
            best_d = d
            # Find endpoints
            if x1 == x2:
                endpoints = [(x1, min(y1,y2)), (x1, max(y1,y2))]
            else:
                endpoints = [(min(x1,x2), y1), (max(x1,x2), y1)]
            best = {
                'type': 'sig_wire',
                'net': net,
                'seg': (x1, y1, x2, y2),
                'bbox': (sx1, sy1, sx2, sy2),
                'endpoints': endpoints,
                'idx': idx,
            }

    # Check power shapes
    for cat, net, x1, y1, x2, y2, label in power_shapes:
        dx = max(x1 - mx, mx - x2, 0)
        dy = max(y1 - my, my - y2, 0)
        d = dx + dy
        if d < 200 and d < best_d:
            best_d = d
            best = {
                'type': cat,
                'net': net,
                'bbox': (x1, y1, x2, y2),
                'label': label,
                'endpoints': [],
            }

    return best


def main():
    viols = load_violations()
    m3_segs, via_pos, power_shapes, routing = load_m3_data()

    print(f'Loaded {len(viols)} M3.b violations')
    print(f'M3 segments: {len(m3_segs)}, via positions: {len(via_pos)}, '
          f'power shapes: {len(power_shapes)}')
    print()

    for idx, (e1, e2) in enumerate(viols, 1):
        mx1, my1 = (e1[0]+e1[2])/2, (e1[1]+e1[3])/2
        mx2, my2 = (e2[0]+e2[2])/2, (e2[1]+e2[3])/2
        dx, dy = abs(mx2-mx1), abs(my2-my1)
        gap = max(dx, dy)

        s1 = find_shape_for_edge(e1, m3_segs, power_shapes)
        s2 = find_shape_for_edge(e2, m3_segs, power_shapes)

        print(f'=== V{idx}: gap={gap:.0f}nm at ({mx1/UM:.3f},{my1/UM:.3f})µm ===')

        for label, shape, edge in [('A', s1, e1), ('B', s2, e2)]:
            if not shape:
                print(f'  {label}: UNKNOWN')
                continue
            net = shape['net']
            stype = shape['type']
            if stype == 'sig_wire':
                seg = shape['seg']
                ep = shape['endpoints']
                at_via = [p for p in ep if p in via_pos]
                free_ep = [p for p in ep if p not in via_pos]
                # Which endpoint is closer to the violation?
                emx, emy = (edge[0]+edge[2])/2, (edge[1]+edge[3])/2
                near_ep = min(ep, key=lambda p: abs(p[0]-emx)+abs(p[1]-emy))
                near_at_via = near_ep in via_pos
                print(f'  {label}: {stype} net={net} seg=({seg[0]},{seg[1]})-({seg[2]},{seg[3]})')
                print(f'      near_endpoint=({near_ep[0]},{near_ep[1]}) '
                      f'at_via={near_at_via} '
                      f'via_eps={len(at_via)}/{len(ep)}')
            else:
                lbl = shape.get('label', stype)
                print(f'  {label}: {stype} net={net} label={lbl}')
                print(f'      bbox=({shape["bbox"][0]},{shape["bbox"][1]})-'
                      f'({shape["bbox"][2]},{shape["bbox"][3]})')

        # Cross-net check
        if s1 and s2:
            same = s1['net'] == s2['net']
            print(f'  → {"SAME" if same else "CROSS"}-net ({s1["net"]} vs {s2["net"]})')

            # Can we trim from the other side?
            for a_label, a_shape, b_shape in [('A', s1, s2), ('B', s2, s1)]:
                if a_shape['type'] == 'sig_wire':
                    seg = a_shape['seg']
                    emx = (e1[0]+e1[2]+e2[0]+e2[2])/4
                    emy = (e1[1]+e1[3]+e2[1]+e2[3])/4
                    ep = a_shape['endpoints']
                    near = min(ep, key=lambda p: abs(p[0]-emx)+abs(p[1]-emy))
                    if near not in via_pos:
                        print(f'  ✓ Shape {a_label} ({a_shape["net"]}) '
                              f'endpoint ({near[0]},{near[1]}) is FREE — trimmable')
                    else:
                        print(f'  ✗ Shape {a_label} ({a_shape["net"]}) '
                              f'endpoint ({near[0]},{near[1]}) is at VIA — protected')
        print()


if __name__ == '__main__':
    main()
