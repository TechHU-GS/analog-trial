#!/usr/bin/env python3
"""Diagnose M3 via-pad notch geometry for same-net M3.b violations.

For each signal net, find M3 via pads and adjacent wire segments,
compute notch dimensions, and identify which patterns cause DRC violations.
"""
import json
import sys
sys.path.insert(0, '.')
from atk.pdk import (
    VIA2_PAD_M3, VIA3_PAD, M3_MIN_W, M3_MIN_S,
    VIA2_SZ, VIA3_SZ,
)
from atk.route.maze_router import M3_LYR

PAD_HP_V2 = VIA2_PAD_M3 // 2  # 190
PAD_HP_V3 = VIA3_PAD // 2      # 190
WIRE_HW = M3_MIN_W // 2        # 100

def load_m3_shapes_per_net(routing):
    """Return {net: {'via2': [(x,y),...], 'via3': [(x,y),...], 'wires': [(x1,y1,x2,y2),...]}}"""
    nets = {}
    for dict_name in ('signal_routes', 'pre_routes'):
        for net, rd in routing.get(dict_name, {}).items():
            d = nets.setdefault(net, {'via2': [], 'via3': [], 'wires': []})
            for seg in rd.get('segments', []):
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, lyr = seg[:5]
                if lyr == -2:
                    d['via2'].append((x1, y1))
                elif lyr == -3:
                    d['via3'].append((x1, y1))
                elif lyr == M3_LYR:
                    d['wires'].append((x1, y1, x2, y2))
    return nets

def pad_box(x, y, hp):
    return (x - hp, y - hp, x + hp, y + hp)

def wire_box(x1, y1, x2, y2, hw):
    if x1 == x2:  # vertical
        return (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
    else:  # horizontal
        return (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)

def rect_gap(a, b):
    """Return (x_gap, y_gap) between two rects. Negative = overlap."""
    xg = max(a[0] - b[2], b[0] - a[2])
    yg = max(a[1] - b[3], b[1] - a[3])
    return xg, yg

def main():
    with open('output/routing.json') as f:
        routing = json.load(f)

    nets = load_m3_shapes_per_net(routing)

    # For each net, find all pairs of M3 shapes with potential DRC issues
    print("=== M3 via pad + wire notch analysis ===\n")

    problem_nets = {}

    for net, d in sorted(nets.items()):
        n_via2 = len(d['via2'])
        n_via3 = len(d['via3'])
        n_wires = len(d['wires'])

        if n_via2 + n_via3 == 0:
            continue

        # Build all M3 shape boxes
        shapes = []  # (type, box, pos_label)
        for vx, vy in d['via2']:
            shapes.append(('v2pad', pad_box(vx, vy, PAD_HP_V2), f'via2@({vx},{vy})'))
        for vx, vy in d['via3']:
            shapes.append(('v3pad', pad_box(vx, vy, PAD_HP_V3), f'via3@({vx},{vy})'))
        for w in d['wires']:
            shapes.append(('wire', wire_box(*w, WIRE_HW), f'wire({w[0]},{w[1]}→{w[2]},{w[3]})'))

        issues = []

        # Check all pairs
        for i in range(len(shapes)):
            for j in range(i+1, len(shapes)):
                t1, b1, l1 = shapes[i]
                t2, b2, l2 = shapes[j]
                xg, yg = rect_gap(b1, b2)

                # Case 1: Both positive but < min_s (diagonal gap, missed by _fill_same_net_gaps)
                if xg > 0 and yg > 0 and (xg < M3_MIN_S or yg < M3_MIN_S):
                    issues.append(f'  DIAG_GAP: {l1} vs {l2}  xg={xg} yg={yg}')

                # Case 2: One positive gap < min_s (handled by _fill_same_net_gaps?)
                elif (xg > 0 and xg < M3_MIN_S and yg < 0) or (yg > 0 and yg < M3_MIN_S and xg < 0):
                    issues.append(f'  GAP<210: {l1} vs {l2}  xg={xg} yg={yg}')

                # Case 3: Overlap → check for notch at width transition
                elif xg < 0 and yg < 0:
                    # Two overlapping shapes. Check if they create a notch.
                    # Notch happens at width transitions: pad (380) to wire (200)
                    if ('pad' in t1 and t2 == 'wire') or ('pad' in t2 and t1 == 'wire'):
                        pad_b = b1 if 'pad' in t1 else b2
                        wire_b = b1 if t1 == 'wire' else b2
                        pad_l = l1 if 'pad' in t1 else l2
                        wire_l = l1 if t1 == 'wire' else l2

                        # Width difference perpendicular to wire
                        pad_w = pad_b[2] - pad_b[0]
                        pad_h = pad_b[3] - pad_b[1]
                        wire_w = wire_b[2] - wire_b[0]
                        wire_h = wire_b[3] - wire_b[1]

                        # Determine wire direction
                        if wire_w < wire_h:  # vertical wire
                            step = (pad_w - wire_w) // 2
                            if 0 < step < M3_MIN_S:
                                issues.append(f'  NOTCH_V: {pad_l} vs {wire_l}  step={step}nm')
                        else:  # horizontal wire
                            step = (pad_h - wire_h) // 2
                            if 0 < step < M3_MIN_S:
                                issues.append(f'  NOTCH_H: {pad_l} vs {wire_l}  step={step}nm')

                    # Two pads overlapping — check if they create notch with adjacent wire
                    elif 'pad' in t1 and 'pad' in t2:
                        # Pads overlap — merged into one shape. Check notch with wires.
                        pass  # will be caught by pad-wire check above

        if issues:
            problem_nets[net] = issues
            print(f'{net}: {n_via2} via2, {n_via3} via3, {n_wires} M3 wires')
            for issue in issues:
                print(issue)
            print()

    print(f'\n=== Summary: {len(problem_nets)} nets with potential M3 notch issues ===')

    # Count by type
    from collections import Counter
    type_counts = Counter()
    for issues in problem_nets.values():
        for issue in issues:
            if 'DIAG_GAP' in issue:
                type_counts['diagonal_gap'] += 1
            elif 'GAP<210' in issue:
                type_counts['gap_under_210'] += 1
            elif 'NOTCH' in issue:
                type_counts['notch'] += 1

    for t, c in type_counts.most_common():
        print(f'  {t}: {c}')

if __name__ == '__main__':
    main()
