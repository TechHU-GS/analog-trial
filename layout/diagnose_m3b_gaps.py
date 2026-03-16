#!/usr/bin/env python3
"""Diagnose M3.b violations: show exact gap geometry and fill eligibility.

Reuses the same shape collection logic as _fill_same_net_gaps() in
assemble_gds.py, then shows why each same-net gap pair is or isn't fillable.

Also shows cross-net M3.b violations with gap distances.

Usage: cd layout && python3 diagnose_m3b_gaps.py
"""
import json
import xml.etree.ElementTree as ET
import re
import sys
from collections import defaultdict
from math import sqrt

sys.path.insert(0, '.')
from atk.pdk import (
    M1_SIG_W, M2_SIG_W, M3_MIN_W, M3_MIN_S, M4_MIN_W,
    VIA1_PAD, VIA1_PAD_M1, VIA2_PAD, VIA2_PAD_M2, VIA2_PAD_M3,
    VIA3_PAD, MAZE_GRID,
)
from atk.paths import ROUTING_JSON

UM = 1000

# ── Load routing data ──
with open(ROUTING_JSON) as f:
    routing = json.load(f)

# ── Collect ALL M3 shapes with net labels ──
# Mirrors _fill_same_net_gaps logic for M3

m3_shapes = []  # (x1, y1, x2, y2, net, label)

hw = M1_SIG_W // 2  # 150nm — M3 signal wire half-width

# Signal + pre-route wire segments on M3
for route_key in ('signal_routes', 'pre_routes'):
    for net, rd in routing.get(route_key, {}).items():
        for si, seg in enumerate(rd.get('segments', [])):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == 2:  # M3 wire
                if x1 == x2 and y1 != y2:  # vertical
                    m3_shapes.append((
                        x1 - hw, min(y1, y2), x1 + hw, max(y1, y2),
                        net, f'wire_V({x1},{min(y1,y2)}-{max(y1,y2)})',
                    ))
                elif y1 == y2 and x1 != x2:  # horizontal
                    m3_shapes.append((
                        min(x1, x2), y1 - hw, max(x1, x2), y1 + hw,
                        net, f'wire_H({min(x1,x2)}-{max(x1,x2)},{y1})',
                    ))
            elif lyr == -2:  # Via2 → M3 pad
                hp = VIA2_PAD_M3 // 2
                m3_shapes.append((
                    x1 - hp, y1 - hp, x1 + hp, y1 + hp,
                    net, f'v2pad({x1},{y1})',
                ))
            elif lyr == -3:  # Via3 → M3 pad
                hp = VIA3_PAD // 2
                m3_shapes.append((
                    x1 - hp, y1 - hp, x1 + hp, y1 + hp,
                    net, f'v3pad({x1},{y1})',
                ))

# Power vbar M3 shapes
for drop in routing.get('power', {}).get('drops', []):
    net = drop['net']
    vbar = drop.get('m3_vbar')
    if vbar:
        vhw = M3_MIN_W // 2
        x = vbar[0]
        y1 = min(vbar[1], vbar[3])
        y2 = max(vbar[1], vbar[3])
        tag = f"{drop.get('inst','?')}.{drop.get('pin','?')}"
        m3_shapes.append((
            x - vhw, y1, x + vhw, y2,
            net, f'vbar_{tag}',
        ))

# Power via2 M3 pads
for drop in routing.get('power', {}).get('drops', []):
    net = drop['net']
    v2p = drop.get('via2_pos')
    if v2p and drop.get('m3_vbar'):
        hp = VIA2_PAD_M3 // 2
        tag = f"{drop.get('inst','?')}.{drop.get('pin','?')}"
        m3_shapes.append((
            v2p[0] - hp, v2p[1] - hp, v2p[0] + hp, v2p[1] + hp,
            net, f'v2pad_{tag}',
        ))

# Power rails M3
for rid, rail in routing.get('power', {}).get('rails', {}).items():
    net = rail.get('net', rid)
    rhw = rail['width'] // 2
    m3_shapes.append((
        rail['x1'], rail['y'] - rhw, rail['x2'], rail['y'] + rhw,
        net, f'rail_{rid}',
    ))

# ── AP via pads on M3 ──
# These are NOT in _fill_same_net_gaps currently — could be the missing pieces
ap_data = routing.get('access_points', {})

# Build pin → net mapping
pin_net = {}
try:
    from atk.paths import NETLIST_JSON
    with open(NETLIST_JSON) as f:
        netlist = json.load(f)
    for n in netlist.get('nets', []):
        for pin_str in n.get('pins', []):
            pin_net[pin_str] = n['name']
except Exception:
    pass

# Check if any AP has M3 pads (via2 upper or via3 lower)
ap_m3_count = 0
for pin_key, ap in ap_data.items():
    vp = ap.get('via_pad', {})
    if 'm3' in vp:
        net = pin_net.get(pin_key, '?')
        m3 = vp['m3']
        m3_shapes.append((
            m3[0], m3[1], m3[2], m3[3],
            net, f'ap_m3pad@{pin_key}',
        ))
        ap_m3_count += 1

print(f"Total M3 shapes indexed: {len(m3_shapes)}")
print(f"  Signal wires: {sum(1 for s in m3_shapes if 'wire_' in s[5])}")
print(f"  Via2 pads: {sum(1 for s in m3_shapes if 'v2pad' in s[5])}")
print(f"  Via3 pads: {sum(1 for s in m3_shapes if 'v3pad' in s[5])}")
print(f"  Power vbar: {sum(1 for s in m3_shapes if 'vbar_' in s[5])}")
print(f"  Power rail: {sum(1 for s in m3_shapes if 'rail_' in s[5])}")
print(f"  AP M3 pads: {ap_m3_count}")

# ── Build per-net shape list ──
net_shapes = defaultdict(list)
for s in m3_shapes:
    net_shapes[s[4]].append(s)

# ── Find all M3.b violations ──
MIN_S = M3_MIN_S
MIN_W = M3_MIN_W

print(f"\nM3.b check: min_spacing = {MIN_S}nm, min_width = {MIN_W}nm\n")

# ALL pairs (cross-net and same-net)
violations = []
for i in range(len(m3_shapes)):
    for j in range(i + 1, len(m3_shapes)):
        a = m3_shapes[i]
        b = m3_shapes[j]
        ax1, ay1, ax2, ay2 = a[:4]
        bx1, by1, bx2, by2 = b[:4]

        # Check overlap
        if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
            continue  # overlapping

        x_gap = max(bx1 - ax2, ax1 - bx2, 0)
        y_gap = max(by1 - ay2, ay1 - by2, 0)

        if x_gap > 0 and y_gap > 0:
            dist = sqrt(x_gap**2 + y_gap**2)
        elif x_gap > 0:
            dist = x_gap
        elif y_gap > 0:
            dist = y_gap
        else:
            continue

        if dist < MIN_S:
            same_net = a[4] == b[4]
            violations.append((dist, i, j, x_gap, y_gap, same_net))

violations.sort(key=lambda v: v[0])

same_net_count = sum(1 for v in violations if v[5])
cross_net_count = sum(1 for v in violations if not v[5])
print(f"M3.b violations: {len(violations)} total "
      f"({same_net_count} same-net, {cross_net_count} cross-net)\n")

# ── Same-net violations detail ──
print("=" * 100)
print("SAME-NET M3.b violations (fillable?)")
print("=" * 100)

for vi, (dist, i, j, x_gap, y_gap, same_net) in enumerate(violations):
    if not same_net:
        continue
    a = m3_shapes[i]
    b = m3_shapes[j]
    need = MIN_S - dist

    # Determine gap type and fillability
    if x_gap > 0 and y_gap <= 0:
        gap_type = "X-gap"
        # Y overlap dimension
        fy1 = max(a[1], b[1])
        fy2 = min(a[3], b[3])
        y_ovlp = fy2 - fy1
        if y_ovlp < MIN_W:
            can_extend = MIN_W - y_ovlp
            fillable = f"needs Y-extend {can_extend}nm"
        else:
            fillable = "YES (Y-overlap OK)"
    elif y_gap > 0 and x_gap <= 0:
        gap_type = "Y-gap"
        fx1 = max(a[0], b[0])
        fx2 = min(a[2], b[2])
        x_ovlp = fx2 - fx1
        if x_ovlp < MIN_W:
            can_extend = MIN_W - x_ovlp
            fillable = f"needs X-extend {can_extend}nm"
        else:
            fillable = "YES (X-overlap OK)"
    else:
        gap_type = "Corner"
        fillable = "corner fill"

    print(f"\n  V{vi+1}: gap={dist:.0f}nm (+{need:.0f}nm) type={gap_type} "
          f"fillable={fillable}")
    print(f"    A: ({a[0]},{a[1]})-({a[2]},{a[3]}) net={a[4]} {a[5]}")
    print(f"    B: ({b[0]},{b[1]})-({b[2]},{b[3]}) net={b[4]} {b[5]}")
    if gap_type == "X-gap":
        print(f"    X-gap={x_gap}nm  Y-overlap=({max(a[1],b[1])},{min(a[3],b[3])}) "
              f"= {min(a[3],b[3])-max(a[1],b[1])}nm")
    elif gap_type == "Y-gap":
        print(f"    Y-gap={y_gap}nm  X-overlap=({max(a[0],b[0])},{min(a[2],b[2])}) "
              f"= {min(a[2],b[2])-max(a[0],b[0])}nm")
    else:
        print(f"    X-gap={x_gap}nm  Y-gap={y_gap}nm")

# ── Cross-net violations detail ──
print("\n" + "=" * 100)
print("CROSS-NET M3.b violations")
print("=" * 100)

for vi, (dist, i, j, x_gap, y_gap, same_net) in enumerate(violations):
    if same_net:
        continue
    a = m3_shapes[i]
    b = m3_shapes[j]
    need = MIN_S - dist

    if x_gap > 0 and y_gap <= 0:
        gap_type = "X-gap"
    elif y_gap > 0 and x_gap <= 0:
        gap_type = "Y-gap"
    else:
        gap_type = "Corner"

    print(f"\n  V{vi+1}: gap={dist:.0f}nm (+{need:.0f}nm) type={gap_type}")
    print(f"    A: ({a[0]},{a[1]})-({a[2]},{a[3]}) net={a[4]} {a[5]}")
    print(f"    B: ({b[0]},{b[1]})-({b[2]},{b[3]}) net={b[4]} {b[5]}")

# ── Summary ──
print("\n" + "=" * 100)
print("SUMMARY")
print("=" * 100)

# Group by type
from collections import Counter
same_types = Counter()
cross_types = Counter()
for dist, i, j, x_gap, y_gap, same_net in violations:
    a = m3_shapes[i]
    b = m3_shapes[j]
    la = a[5].split('(')[0].split('@')[0]
    lb = b[5].split('(')[0].split('@')[0]
    key = f"{min(la,lb)}-{max(la,lb)}"
    if same_net:
        same_types[key] += 1
    else:
        cross_types[key] += 1

print(f"\nSame-net patterns ({same_net_count}):")
for k, v in same_types.most_common():
    print(f"  {k}: {v}")

print(f"\nCross-net patterns ({cross_net_count}):")
for k, v in cross_types.most_common():
    print(f"  {k}: {v}")
