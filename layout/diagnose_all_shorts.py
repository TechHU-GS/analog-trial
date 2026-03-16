#!/usr/bin/env python3
"""Find ALL cross-net metal shorts in the assembled GDS.

Uses routing.json to assign net names to M2 shapes, then checks
for overlaps between shapes of different nets on M1, M2, M3.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
ROUTING = 'output/routing.json'

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)

with open(ROUTING) as f:
    routing = json.load(f)

M1_LYR, M2_LYR, M3_LYR, M4_LYR = 0, 1, 2, 3
M1_SIG_W, M2_SIG_W = 300, 300
M3_PWR_W = 200  # approximate

# Build per-net shape lists from routing.json for M1 and M2
# Format: list of (xl, yb, xr, yt) per net

def collect_signal_shapes():
    """Collect M1/M2/M3 shapes from signal routes per net."""
    shapes = {'M1': {}, 'M2': {}, 'M3': {}, 'M4': {}}
    hw = {0: M1_SIG_W // 2, 1: M2_SIG_W // 2, 2: M2_SIG_W // 2, 3: M2_SIG_W // 2}
    lyr_name = {0: 'M1', 1: 'M2', 2: 'M3', 3: 'M4'}

    VIA1_PAD = 480

    for net_type in ['signal_routes', 'pre_routes']:
        for net, route in routing.get(net_type, {}).items():
            for seg in route.get('segments', []):
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, code = seg[:5]
                if code >= 0 and code <= 3:
                    layer = lyr_name[code]
                    w = hw[code]
                    if y1 == y2 and x1 != x2:
                        xl, xr = min(x1, x2), max(x1, x2)
                        shapes[layer].setdefault(net, []).append(
                            (xl - w, y1 - w, xr + w, y1 + w))
                    elif x1 == x2 and y1 != y2:
                        yb, yt = min(y1, y2), max(y1, y2)
                        shapes[layer].setdefault(net, []).append(
                            (x1 - w, yb - w, x1 + w, yt + w))
                elif code == -1:  # Via1
                    hp = VIA1_PAD // 2
                    shapes['M1'].setdefault(net, []).append(
                        (x1 - hp, y1 - hp, x1 + hp, y1 + hp))
                    shapes['M2'].setdefault(net, []).append(
                        (x1 - hp, y1 - hp, x1 + hp, y1 + hp))
    return shapes


def collect_ap_shapes():
    """Collect AP M2/M1 pads per net."""
    shapes = {'M1': {}, 'M2': {}}
    for key, ap in routing.get('access_points', {}).items():
        # Find which net uses this AP
        ap_net = None
        for net_type in ['signal_routes', 'pre_routes']:
            for net, route in routing.get(net_type, {}).items():
                if key in route.get('pins', []):
                    ap_net = net
                    break
            if ap_net:
                break
        if not ap_net:
            continue
        vp = ap.get('via_pad', {})
        if 'm2' in vp:
            r = vp['m2']
            shapes['M2'].setdefault(ap_net, []).append(tuple(r))
        if 'm1' in vp:
            r = vp['m1']
            shapes['M1'].setdefault(ap_net, []).append(tuple(r))
        if ap.get('m1_stub'):
            r = ap['m1_stub']
            shapes['M1'].setdefault(ap_net, []).append(tuple(r))
        if ap.get('m2_stub'):
            r = ap['m2_stub']
            shapes['M2'].setdefault(ap_net, []).append(tuple(r))
    return shapes


def collect_power_shapes():
    """Collect power M2/M3 shapes per net."""
    shapes = {'M1': {}, 'M2': {}, 'M3': {}}
    power = routing.get('power', {})

    # M3 rails
    for rail_id, rail in power.get('rails', {}).items():
        net = rail.get('net', rail_id)
        hw = rail['width'] // 2
        shapes['M3'].setdefault(net, []).append(
            (rail['x1'], rail['y'] - hw, rail['x2'], rail['y'] + hw))

    # Power drops
    for drop in power.get('drops', []):
        net = drop.get('net', '?')
        # M2 shapes
        for s in drop.get('m2_shapes', []):
            shapes['M2'].setdefault(net, []).append(tuple(s))
        m2up = drop.get('m2_underpass')
        if m2up:
            shapes['M2'].setdefault(net, []).append(tuple(m2up))
        # M1 shapes (via stack base)
        for s in drop.get('m1_shapes', []):
            shapes['M1'].setdefault(net, []).append(tuple(s))

    # Tie cell power connections
    ties = routing.get('ties', {})
    for tie_id, tie in ties.items() if isinstance(ties, dict) else []:
        net = tie.get('net', '?')
        for s in tie.get('m1_shapes', []):
            shapes['M1'].setdefault(net, []).append(tuple(s))

    return shapes


def check_overlaps(all_shapes, layer_name):
    """Find cross-net overlaps on a given layer."""
    nets = list(all_shapes.keys())
    shorts = []
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            n1, n2 = nets[i], nets[j]
            for r1 in all_shapes[n1]:
                for r2 in all_shapes[n2]:
                    # Check box overlap
                    if (r1[0] < r2[2] and r1[2] > r2[0] and
                            r1[1] < r2[3] and r1[3] > r2[1]):
                        # Overlap area
                        ox1 = max(r1[0], r2[0])
                        oy1 = max(r1[1], r2[1])
                        ox2 = min(r1[2], r2[2])
                        oy2 = min(r1[3], r2[3])
                        area = (ox2 - ox1) * (oy2 - oy1)
                        cx = (ox1 + ox2) / 2e3
                        cy = (oy1 + oy2) / 2e3
                        shorts.append((n1, n2, layer_name, cx, cy, area))
    return shorts


# Merge all shape sources
sig_shapes = collect_signal_shapes()
ap_shapes = collect_ap_shapes()
pwr_shapes = collect_power_shapes()

print("=== Comprehensive Cross-Net Short Check ===\n")

for layer in ['M1', 'M2', 'M3']:
    # Merge all sources for this layer
    all_shapes = {}
    for src in [sig_shapes, ap_shapes, pwr_shapes]:
        for net, rects in src.get(layer, {}).items():
            all_shapes.setdefault(net, []).extend(rects)

    net_count = len(all_shapes)
    shape_count = sum(len(v) for v in all_shapes.values())
    print(f"{layer}: {net_count} nets, {shape_count} shapes")

    shorts = check_overlaps(all_shapes, layer)
    if shorts:
        print(f"  *** {len(shorts)} CROSS-NET SHORTS ***")
        # Deduplicate by net pair
        by_pair = {}
        for n1, n2, lyr, cx, cy, area in shorts:
            pair = tuple(sorted([n1, n2]))
            by_pair.setdefault(pair, []).append((cx, cy, area))

        for (n1, n2), locs in sorted(by_pair.items()):
            total_area = sum(a for _, _, a in locs)
            print(f"    {n1} <-> {n2}: {len(locs)} overlap(s), "
                  f"total area={total_area/1e6:.3f}µm²")
            for cx, cy, area in locs[:3]:
                print(f"      at ({cx:.3f}, {cy:.3f})µm, area={area}nm²")
            if len(locs) > 3:
                print(f"      ... and {len(locs)-3} more")
    else:
        print(f"  No cross-net shorts found")
    print()

# Summary
print("=" * 60)
print("SUMMARY")
all_shorts = []
for layer in ['M1', 'M2', 'M3']:
    all_shapes = {}
    for src in [sig_shapes, ap_shapes, pwr_shapes]:
        for net, rects in src.get(layer, {}).items():
            all_shapes.setdefault(net, []).extend(rects)
    all_shorts.extend(check_overlaps(all_shapes, layer))

if all_shorts:
    # Build union-find to see which nets merge
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

    for n1, n2, lyr, cx, cy, area in all_shorts:
        union(n1, n2)

    # Find merged groups
    groups = {}
    all_nets = set()
    for n1, n2, _, _, _, _ in all_shorts:
        all_nets.add(n1)
        all_nets.add(n2)
    for n in all_nets:
        r = find(n)
        groups.setdefault(r, set()).add(n)

    for root, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(members) > 1:
            has_vdd = 'vdd' in members or 'vdd_vco' in members
            has_gnd = 'gnd' in members
            marker = " *** VDD-GND SHORT ***" if has_vdd and has_gnd else ""
            print(f"\n  Merged group ({len(members)} nets):{marker}")
            for m in sorted(members):
                print(f"    {m}")
else:
    print("\nNo cross-net shorts found in routing data!")
    print("Shorts may be from:")
    print("  - Gap fill shapes bridging different nets")
    print("  - PCell shapes overlapping with routing")
    print("  - Shapes not tracked in routing.json")
