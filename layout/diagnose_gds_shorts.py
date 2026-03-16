#!/usr/bin/env python3
"""GDS-level cross-net M2 short detector.

Uses KLayout to extract actual M2 shapes from the GDS, assigns net names
using routing.json data + spatial proximity, then checks overlaps between
shapes of different nets.

This catches shorts from assembler-generated shapes (gap fills, L-corner
extensions, underpasses) that routing.json-only diagnostics miss.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_gds_shorts.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
ROUTING = 'output/routing.json'

# DRC constants
M2_SIG_W = 300
VIA1_PAD = 480
VIA2_PAD = 480
M2_MIN_W = 200

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)

with open(ROUTING) as f:
    routing = json.load(f)

# ─── Build comprehensive M2 net-ownership map ───
# For each net, collect all expected M2 rectangles (from routing + assembler)
hw = M2_SIG_W // 2
M2_LYR = 1

net_rects = []  # (xl, yb, xr, yt, net_name, source)

# 1. Signal route M2 segments
for net, route in routing.get('signal_routes', {}).items():
    for seg in route.get('segments', []):
        if len(seg) < 5:
            continue
        x1, y1, x2, y2, code = seg[:5]
        if code == M2_LYR:
            if y1 == y2 and x1 != x2:
                xl, xr = min(x1, x2), max(x1, x2)
                net_rects.append((xl - hw, y1 - hw, xr + hw, y1 + hw, net, 'sig-wire'))
            elif x1 == x2 and y1 != y2:
                yb, yt = min(y1, y2), max(y1, y2)
                net_rects.append((x1 - hw, yb - hw, x1 + hw, yt + hw, net, 'sig-wire'))
        elif code == -1:  # Via1
            hp = VIA1_PAD // 2
            net_rects.append((x1 - hp, y1 - hp, x1 + hp, y1 + hp, net, 'sig-via1'))

# 2. Access point M2 pads (skip via_stack pins)
via_stack_pins = set()
for d in routing.get('power', {}).get('drops', []):
    if d['type'] == 'via_stack':
        via_stack_pins.add(f"{d['inst']}.{d['pin']}")

# Build pin→net map from netlist.json
with open('netlist.json') as f:
    netlist = json.load(f)
pin_net = {}
for ne in netlist.get('nets', []):
    for pin in ne['pins']:
        pin_net[pin] = ne['name']
# Also use signal_routes pins field
for net, route in routing.get('signal_routes', {}).items():
    for pin_key in route.get('pins', []):
        pin_net[pin_key] = net
for net, route in routing.get('pre_routes', {}).items():
    for pin_key in route.get('pins', []):
        pin_net[pin_key] = net

for key, ap in routing.get('access_points', {}).items():
    if key in via_stack_pins:
        continue  # AP M2 pad not drawn for via_stack
    net = pin_net.get(key, '')
    if not net:
        continue
    vp = ap.get('via_pad', {})
    if 'm2' in vp:
        r = vp['m2']
        net_rects.append((r[0], r[1], r[2], r[3], net, 'ap-pad'))
    if ap.get('m2_stub'):
        r = ap['m2_stub']
        net_rects.append((r[0], r[1], r[2], r[3], net, 'ap-stub'))

# 3. Power drop M2 shapes
for drop in routing.get('power', {}).get('drops', []):
    dnet = drop['net']
    # via_access: m2_vbar + m2_jog
    if drop['type'] == 'via_access':
        vb = drop.get('m2_vbar')
        if vb:
            net_rects.append((vb[0] - hw, min(vb[1], vb[3]),
                              vb[0] + hw, max(vb[1], vb[3]), dnet, 'pwr-vbar'))
        jog = drop.get('m2_jog')
        if jog:
            jhw = VIA1_PAD // 2
            net_rects.append((min(jog[0], jog[2]), jog[1] - jhw,
                              max(jog[0], jog[2]), jog[1] + jhw, dnet, 'pwr-jog'))
        # via2 M2 pad
        v2 = drop.get('via2_pos')
        if v2:
            v2hp = M2_MIN_W // 2  # narrow underpass (200nm)
            net_rects.append((v2[0] - v2hp, v2[1] - v2hp,
                              v2[0] + v2hp, v2[1] + v2hp, dnet, 'pwr-via2'))
    # via_stack: via1 M2 pad + m2_jog
    elif drop['type'] == 'via_stack':
        v1 = drop.get('via1_pos')
        if v1:
            hp = VIA1_PAD // 2
            net_rects.append((v1[0] - hp, v1[1] - hp,
                              v1[0] + hp, v1[1] + hp, dnet, 'pwr-via1'))
        jog = drop.get('m2_jog')
        if jog:
            jhw = VIA1_PAD // 2
            net_rects.append((min(jog[0], jog[2]), jog[1] - jhw,
                              max(jog[0], jog[2]), jog[1] + jhw, dnet, 'pwr-jog'))
        v2 = drop.get('via2_pos')
        if v2:
            v2hp = M2_MIN_W // 2
            net_rects.append((v2[0] - v2hp, v2[1] - v2hp,
                              v2[0] + v2hp, v2[1] + v2hp, dnet, 'pwr-via2'))

# 4. M2 underpass shapes (from assembler bridge code — approximate)
# These are dynamically generated and not in routing.json, but we can
# approximate them by checking M3 vbar crossing zones.

print(f'Net-ownership rects: {len(net_rects)}')
print(f'  Signal routes: {sum(1 for r in net_rects if r[5].startswith("sig"))}')
print(f'  AP pads: {sum(1 for r in net_rects if r[5].startswith("ap"))}')
print(f'  Power drops: {sum(1 for r in net_rects if r[5].startswith("pwr"))}')

# ─── Extract actual GDS M2 merged shapes ───
m2_region = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
print(f'\nGDS M2 merged polygons: {m2_region.count()}')

# ─── Assign net to each GDS M2 polygon ───
# For each merged polygon, find which net_rects overlap it.
# A polygon may span multiple nets (that's a short!).

def rect_overlaps_polygon(xl, yb, xr, yt, poly):
    """Check if rectangle overlaps polygon."""
    rect_region = kdb.Region(kdb.Box(xl, yb, xr, yt))
    poly_region = kdb.Region(poly)
    return not (rect_region & poly_region).is_empty()


shorts = []
multi_net_polys = 0

for pi, poly in enumerate(m2_region.each()):
    bbox = poly.bbox()
    # Find net_rects that overlap this polygon's bbox
    candidate_nets = set()
    candidate_details = []
    for xl, yb, xr, yt, net, src in net_rects:
        # Quick bbox filter
        if xr <= bbox.left or xl >= bbox.right:
            continue
        if yt <= bbox.bottom or yb >= bbox.top:
            continue
        # Detailed overlap check
        if rect_overlaps_polygon(xl, yb, xr, yt, poly):
            candidate_nets.add(net)
            candidate_details.append((net, src, xl, yb, xr, yt))

    if len(candidate_nets) > 1:
        multi_net_polys += 1
        nets_sorted = sorted(candidate_nets)
        cx = (bbox.left + bbox.right) / 2e3
        cy = (bbox.top + bbox.bottom) / 2e3
        area = poly.area() / 1e6

        # Classify: power involved?
        power_nets = {'vdd', 'gnd', 'vdd_vco'}
        has_power = any(n in power_nets for n in nets_sorted)
        marker = ' *** POWER ***' if has_power else ''

        shorts.append({
            'nets': nets_sorted,
            'cx': cx, 'cy': cy,
            'area': area,
            'details': candidate_details,
            'has_power': has_power,
        })

print(f'\nMulti-net M2 polygons: {multi_net_polys}')

# ─── Report ───
print(f'\n{"="*70}')
print(f'CROSS-NET M2 SHORTS (GDS-level)')
print(f'{"="*70}\n')

# Build union-find for net merger
parent = {}
def find(x):
    while parent.get(x, x) != x:
        parent[x] = parent.get(parent[x], parent[x])
        x = parent[x]
    return x
def union(a, b):
    a, b = find(a), find(b)
    if a != b:
        parent[b] = a

for s in shorts:
    nets = s['nets']
    for i in range(1, len(nets)):
        union(nets[0], nets[i])

    print(f'SHORT: {" <-> ".join(nets)}')
    print(f'  Location: ({s["cx"]:.3f}, {s["cy"]:.3f})µm, '
          f'poly area={s["area"]:.3f}µm²')
    # Show contributing shapes
    by_net = {}
    for net, src, xl, yb, xr, yt in s['details']:
        by_net.setdefault(net, []).append((src, xl, yb, xr, yt))
    for net in sorted(by_net):
        shapes = by_net[net]
        print(f'  [{net}]:')
        for src, xl, yb, xr, yt in shapes[:5]:
            print(f'    {src}: ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})µm')
        if len(shapes) > 5:
            print(f'    ... and {len(shapes)-5} more')
    print()

# Merged groups
print(f'{"="*70}')
print('NET MERGER GROUPS')
print(f'{"="*70}\n')
all_shorted_nets = set()
for s in shorts:
    all_shorted_nets.update(s['nets'])

groups = {}
for n in all_shorted_nets:
    r = find(n)
    groups.setdefault(r, set()).add(n)

for root, members in sorted(groups.items(), key=lambda x: -len(x[1])):
    if len(members) > 1:
        has_vdd = any(n in {'vdd', 'vdd_vco'} for n in members)
        has_gnd = 'gnd' in members
        marker = ' *** VDD-GND SHORT ***' if has_vdd and has_gnd else ''
        print(f'Group ({len(members)} nets):{marker}')
        for m in sorted(members):
            power = ' [POWER]' if m in {'vdd', 'gnd', 'vdd_vco'} else ''
            print(f'  {m}{power}')
        print()
