#!/usr/bin/env python3
"""Diagnose M2.b cross-net violations from routing.json geometry.

Finds all M2 wire-vs-pad and pad-vs-pad pairs that violate M2_MIN_S=210nm,
then classifies which are fixable by endpoint trimming in optimize.py.

Usage: cd layout && python3 diagnose_m2b_routing.py
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, '.')
from atk.pdk import (
    M2_SIG_W, M2_MIN_S, M2_MIN_W,
    VIA1_PAD, VIA2_PAD_M2,
    MAZE_GRID, M1_SIG_W,
)
from atk.paths import ROUTING_JSON, NETLIST_JSON

with open(ROUTING_JSON) as f:
    data = json.load(f)

# Build pin → net mapping
pin_net = {}
try:
    with open(NETLIST_JSON) as f:
        netlist = json.load(f)
    for net in netlist.get('nets', []):
        for pin_str in net.get('pins', []):
            pin_net[pin_str] = net['name']
except FileNotFoundError:
    pass

# ── Collect all M2 shapes with net labels ──
# Each shape: (x1, y1, x2, y2, net, label, segment_ref)
# segment_ref: (route_dict_key, net_name, seg_index) for wire segments

m2_shapes = []

hw = M2_SIG_W // 2  # 150nm — signal wire half-width

# Signal + pre-route wire segments on M2
for route_key in ('signal_routes', 'pre_routes'):
    for net, rd in data.get(route_key, {}).items():
        for si, seg in enumerate(rd.get('segments', [])):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == 1:  # M2 wire
                if x1 == x2 and y1 != y2:  # vertical
                    m2_shapes.append((
                        x1 - hw, min(y1, y2), x1 + hw, max(y1, y2),
                        net, 'wire_V', (route_key, net, si)
                    ))
                elif y1 == y2 and x1 != x2:  # horizontal
                    m2_shapes.append((
                        min(x1, x2), y1 - hw, max(x1, x2), y1 + hw,
                        net, 'wire_H', (route_key, net, si)
                    ))
            elif lyr == -1:  # Via1 → M2 pad
                hp = VIA1_PAD // 2
                m2_shapes.append((
                    x1 - hp, y1 - hp, x1 + hp, y1 + hp,
                    net, 'via1_pad', (route_key, net, si)
                ))
            elif lyr == -2:  # Via2 → M2 pad
                hp = VIA2_PAD_M2 // 2
                m2_shapes.append((
                    x1 - hp, y1 - hp, x1 + hp, y1 + hp,
                    net, 'via2_pad', (route_key, net, si)
                ))

# AP M2 pads
for pin_key, ap in data.get('access_points', {}).items():
    net = pin_net.get(pin_key, '?')
    m2 = ap.get('via_pad', {}).get('m2')
    if m2:
        m2_shapes.append((
            m2[0], m2[1], m2[2], m2[3],
            net, f'ap_m2pad@{pin_key}', None
        ))

# Power drop M2 shapes
vhp = VIA1_PAD // 2
for di, drop in enumerate(data.get('power', {}).get('drops', [])):
    dnet = drop['net']
    tag = f"{drop.get('inst', '?')}.{drop.get('pin', '?')}"
    v1 = drop.get('via1_pos')
    if v1:
        m2_shapes.append((
            v1[0] - vhp, v1[1] - vhp, v1[0] + vhp, v1[1] + vhp,
            dnet, f'pwr_v1pad@{tag}', None
        ))
    v2 = drop.get('via2_pos')
    if v2:
        m2_shapes.append((
            v2[0] - vhp, v2[1] - vhp, v2[0] + vhp, v2[1] + vhp,
            dnet, f'pwr_v2pad@{tag}', None
        ))
    m2v = drop.get('m2_vbar')
    if m2v:
        m2_shapes.append((
            m2v[0] - hw, min(m2v[1], m2v[3]), m2v[0] + hw, max(m2v[1], m2v[3]),
            dnet, f'pwr_m2vbar@{tag}', None
        ))

# ── Find all cross-net M2.b violations ──
MIN_S = M2_MIN_S  # 210nm

violations = []
for i in range(len(m2_shapes)):
    for j in range(i + 1, len(m2_shapes)):
        a = m2_shapes[i]
        b = m2_shapes[j]
        # Skip same-net
        if a[4] == b[4]:
            continue

        ax1, ay1, ax2, ay2 = a[:4]
        bx1, by1, bx2, by2 = b[:4]

        # Check if shapes overlap (merged = no spacing issue)
        if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
            continue

        # Compute gap (Euclidean for corners, Manhattan for edges)
        x_gap = max(bx1 - ax2, ax1 - bx2, 0)
        y_gap = max(by1 - ay2, ay1 - by2, 0)

        if x_gap > 0 and y_gap > 0:
            # Corner — Euclidean
            dist = (x_gap ** 2 + y_gap ** 2) ** 0.5
        elif x_gap > 0:
            dist = x_gap
        elif y_gap > 0:
            dist = y_gap
        else:
            continue  # overlapping

        if dist < MIN_S:
            violations.append((dist, i, j, x_gap, y_gap))

violations.sort(key=lambda v: v[0])

print(f"Total M2 shapes indexed: {len(m2_shapes)}")
print(f"Cross-net M2.b violations (gap < {MIN_S}nm): {len(violations)}\n")

# ── Classify each violation ──
print(f"{'#':>3s} {'gap':>5s} {'need':>5s} {'type':>10s}  shape_A  ←→  shape_B")
print("-" * 110)

# Track patterns
patterns = defaultdict(list)

for vi, (dist, i, j, x_gap, y_gap) in enumerate(violations):
    a = m2_shapes[i]
    b = m2_shapes[j]
    need = MIN_S - dist

    # Classify labels
    lab_a = a[5].split('@')[0]
    lab_b = b[5].split('@')[0]
    pair_key = f"{min(lab_a, lab_b)}—{max(lab_a, lab_b)}"

    # Can we fix by endpoint trimming?
    fix_type = "none"

    # Check if shape A is a wire that can be trimmed
    for shape, other in [(a, b), (b, a)]:
        if 'wire_' not in shape[5]:
            continue
        seg_ref = shape[6]
        if seg_ref is None:
            continue

        route_key, net, si = seg_ref
        seg = data[route_key][net]['segments'][si]
        x1, y1, x2, y2, lyr = seg[:5]
        ox1, oy1, ox2, oy2 = other[:4]

        if 'wire_V' in shape[5]:
            # Vertical wire: can trim Y endpoints
            ylo, yhi = min(y1, y2), max(y1, y2)
            # Overlap zone in Y with the other shape (expanded by MIN_S)
            pad_ylo = oy1 - MIN_S
            pad_yhi = oy2 + MIN_S

            # Can trim bottom? (wire extends below overlap zone)
            # Wire bottom must be below pad_yhi to have an endpoint to trim
            if ylo < pad_ylo and yhi > pad_ylo:
                # Trim top endpoint to pad_ylo
                trim_amount = yhi - pad_ylo
                if trim_amount > 0 and trim_amount < (yhi - ylo) * 0.5:
                    fix_type = f"trim_V_top(-{trim_amount}nm)"
            if yhi > pad_yhi and ylo < pad_yhi:
                # Trim bottom endpoint to pad_yhi
                trim_amount = pad_yhi - ylo
                if trim_amount > 0 and trim_amount < (yhi - ylo) * 0.5:
                    fix_type = f"trim_V_bot(+{trim_amount}nm)"
            # Alternative: nudge X
            if fix_type == "none":
                fix_type = f"nudge_X(+{int(need + 1)}nm)"

        elif 'wire_H' in shape[5]:
            # Horizontal wire: can trim X endpoints
            xlo, xhi = min(x1, x2), max(x1, x2)
            pad_xlo = ox1 - MIN_S
            pad_xhi = ox2 + MIN_S

            if xlo < pad_xlo and xhi > pad_xlo:
                trim_amount = xhi - pad_xlo
                if trim_amount > 0 and trim_amount < (xhi - xlo) * 0.5:
                    fix_type = f"trim_H_right(-{trim_amount}nm)"
            if xhi > pad_xhi and xlo < pad_xhi:
                trim_amount = pad_xhi - xlo
                if trim_amount > 0 and trim_amount < (xhi - xlo) * 0.5:
                    fix_type = f"trim_H_left(+{trim_amount}nm)"
            if fix_type == "none":
                fix_type = f"nudge_Y(+{int(need + 1)}nm)"

        if fix_type != "none":
            break

    print(f"{vi+1:3d} {dist:5.0f} +{need:4.0f}  {fix_type:>30s}  "
          f"{a[4]}:{a[5][:25]}  ←→  {b[4]}:{b[5][:25]}")

    patterns[pair_key].append({
        'gap': dist, 'need': need, 'fix': fix_type,
        'a': a, 'b': b, 'idx_a': i, 'idx_b': j,
    })

# ── Summary by pattern ──
print(f"\n{'Pattern':<40s} {'Tot':>4s} {'trimmable':>9s} {'nudge':>5s} {'none':>5s}")
print("-" * 70)
for key in sorted(patterns.keys(), key=lambda k: -len(patterns[k])):
    items = patterns[key]
    trimmable = sum(1 for x in items if 'trim' in x['fix'])
    nudge = sum(1 for x in items if 'nudge' in x['fix'])
    none = sum(1 for x in items if x['fix'] == 'none')
    print(f"{key:<40s} {len(items):>4d} {trimmable:>9d} {nudge:>5d} {none:>5d}")

total = len(violations)
total_trim = sum(1 for v in violations
                 for p in [patterns] if True
                 for items in [sum(patterns.values(), [])] if True)
print(f"\nTotal: {total} violations")
print(f"  Trimmable: {sum(1 for p in sum(patterns.values(), []) if 'trim' in p['fix'])}")
print(f"  Nudgeable: {sum(1 for p in sum(patterns.values(), []) if 'nudge' in p['fix'])}")
print(f"  Not fixable by optimize.py: {sum(1 for p in sum(patterns.values(), []) if p['fix'] == 'none')}")

# ── Detailed wire-vs-pad violations with segment info ──
print(f"\n{'='*80}")
print("Detailed wire segments involved (for optimize.py implementation)")
print(f"{'='*80}\n")

for vi, (dist, i, j, x_gap, y_gap) in enumerate(violations):
    a = m2_shapes[i]
    b = m2_shapes[j]
    need = MIN_S - dist

    # Only show wire-involved violations
    wire_shape = None
    pad_shape = None
    for s in [a, b]:
        if 'wire_' in s[5]:
            wire_shape = s
        else:
            pad_shape = s

    if wire_shape is None:
        continue

    seg_ref = wire_shape[6]
    if seg_ref is None:
        continue

    route_key, net, si = seg_ref
    seg = data[route_key][net]['segments'][si]

    # Find connected vias at endpoints
    segs = data[route_key][net]['segments']
    x1, y1, x2, y2, lyr = seg[:5]
    ep1, ep2 = (x1, y1), (x2, y2)
    via_at_ep1 = via_at_ep2 = False
    for s in segs:
        if len(s) < 5:
            continue
        if s[4] < 0:  # via
            vp = (s[0], s[1])
            if vp == ep1:
                via_at_ep1 = True
            if vp == ep2:
                via_at_ep2 = True

    print(f"V{vi+1}: gap={dist:.0f}nm need=+{need:.0f}nm  "
          f"wire={wire_shape[4]}  pad={pad_shape[4] if pad_shape else '?'}")
    print(f"  wire: ({x1},{y1})-({x2},{y2}) M2 [{wire_shape[5]}]")
    print(f"  via@ep1=({x1},{y1}):{via_at_ep1}  via@ep2=({x2},{y2}):{via_at_ep2}")
    if pad_shape:
        print(f"  pad: ({pad_shape[0]},{pad_shape[1]})-({pad_shape[2]},{pad_shape[3]}) [{pad_shape[5]}]")
    print()
