#!/usr/bin/env python3
"""For each M2.b violation, find which routing net owns the violating wire/pad,
and whether it was a retry net (routed without AP protection)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
import xml.etree.ElementTree as ET
from atk.pdk import M2_SIG_W, M2_MIN_S, VIA1_PAD

GDS = 'output/ptat_vco.gds'
LYRDB = '/tmp/drc_verify_now/ptat_vco_ptat_vco_full.lyrdb'
ROUTING = 'output/routing.json'

with open(ROUTING) as f:
    routing = json.load(f)

# Collect all M2 shapes from routing with their net names
hw = M2_SIG_W // 2  # 150nm
M2_LYR = 1
m2_shapes = []  # (xl, yb, xr, yt, net, kind)

for net_type in ['signal_routes', 'pre_routes']:
    for net, route in routing.get(net_type, {}).items():
        for seg in route.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, code = seg[:5]
            if code == M2_LYR:
                if y1 == y2 and x1 != x2:  # H-wire
                    xl, xr = min(x1, x2), max(x1, x2)
                    m2_shapes.append((xl, y1-hw, xr, y1+hw, net, 'H-wire'))
                elif x1 == x2 and y1 != y2:  # V-wire
                    yb, yt = min(y1, y2), max(y1, y2)
                    m2_shapes.append((x1-hw, yb, x1+hw, yt, net, 'V-wire'))
            elif code < 0:  # Via
                via_layer = -code  # 1=Via1, 2=Via2
                if via_layer == 1:  # Via1 → M2 pad
                    hp = VIA1_PAD // 2
                    m2_shapes.append((x1-hp, y1-hp, x1+hp, y1+hp, net, 'Via1-pad'))

# Also collect AP pads (access point M2 pads)
for key, ap in routing.get('access_points', {}).items():
    vp = ap.get('via_pad', {})
    m2 = vp.get('m2')
    if m2:
        m2_shapes.append((m2[0], m2[1], m2[2], m2[3], f'AP:{key}', 'AP-pad'))

# Power M2 shapes
power = routing.get('power', {})
for drop in power.get('drops', []):
    net_name = drop.get('net', '?')
    for shape in drop.get('m2_shapes', []):
        m2_shapes.append((shape[0], shape[1], shape[2], shape[3],
                         f'PWR:{net_name}', 'pwr-drop'))
    # Also add M2 underpass/bridge shapes
    m2_up = drop.get('m2_underpass')
    if m2_up:
        m2_shapes.append((m2_up[0], m2_up[1], m2_up[2], m2_up[3],
                         f'PWR:{net_name}', 'pwr-underpass'))

# Parse M2.b violations
tree = ET.parse(LYRDB)
root = tree.getroot()
viols = []
for item in root.find('items').findall('item'):
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

print(f"M2.b Net Attribution ({len(viols)} violations)")
print("=" * 70)

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

    e1, e2 = edges[0], edges[1]
    cx = (e1[0][0] + e1[1][0] + e2[0][0] + e2[1][0]) // 4
    cy = (e1[0][1] + e1[1][1] + e2[0][1] + e2[1][1]) // 4

    # Find M2 shapes near each edge
    def find_near(mx, my, radius=500):
        matches = []
        for xl, yb, xr, yt, net, kind in m2_shapes:
            if xl - radius <= mx <= xr + radius and yb - radius <= my <= yt + radius:
                d = max(0, max(xl - mx, mx - xr)) + max(0, max(yb - my, my - yt))
                if d < radius:
                    matches.append((d, xl, yb, xr, yt, net, kind))
        matches.sort()
        return matches[:3]

    e1_mx = (e1[0][0] + e1[1][0]) // 2
    e1_my = (e1[0][1] + e1[1][1]) // 2
    e2_mx = (e2[0][0] + e2[1][0]) // 2
    e2_my = (e2[0][1] + e2[1][1]) // 2

    m1 = find_near(e1_mx, e1_my)
    m2_match = find_near(e2_mx, e2_my)

    net1 = m1[0][5] if m1 else '?'
    kind1 = m1[0][6] if m1 else '?'
    net2 = m2_match[0][5] if m2_match else '?'
    kind2 = m2_match[0][6] if m2_match else '?'

    print(f"\nV{vi+1}: ({cx/1e3:.3f}, {cy/1e3:.3f})µm")
    print(f"  Shape1: {net1} ({kind1})")
    print(f"  Shape2: {net2} ({kind2})")
    if net1 != net2:
        print(f"  >> CROSS-NET: {net1} vs {net2}")
    else:
        print(f"  >> SAME-NET: {net1}")
