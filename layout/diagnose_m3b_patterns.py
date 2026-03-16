#!/usr/bin/env python3
"""Classify M3.b violations into geometric patterns and test fixes.

For each violation:
1. Identify exact shapes (wire rect, via pad, power shape)
2. Classify pattern: L-corner-notch, via-pad-notch, parallel-spacing, etc.
3. For fixable patterns, compute the fix geometry and check safety
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.path.insert(0, '.')
from atk.pdk import (
    M3_MIN_S, M3_MIN_W, VIA2_PAD_M3, VIA3_PAD,
    M1_SIG_W, MAZE_GRID,
)
from atk.route.maze_router import M3_LYR, VIA2_SEG, VIA3_SEG

UM = 1000
LYRDB = '/tmp/drc_r11d/ptat_vco_ptat_vco_full.lyrdb'
ROUTING = 'output/routing.json'

M3_WIRE_W = M1_SIG_W  # 300nm (assemble_gds uses M1_SIG_W for M3)
HW = M3_WIRE_W // 2   # 150nm
VP2 = VIA2_PAD_M3 // 2  # 190nm
VP3 = VIA3_PAD // 2     # 190nm


def parse_edge(s):
    p1, p2 = s.split(';')
    x1, y1 = [float(c) for c in p1.split(',')]
    x2, y2 = [float(c) for c in p2.split(',')]
    return (round(x1*UM), round(y1*UM), round(x2*UM), round(y2*UM))


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


def load_m3_shapes():
    """Build all M3 rectangles as drawn by assemble_gds, grouped by net."""
    with open(ROUTING) as f:
        routing = json.load(f)

    # Per-net M3 rectangles: (x1, y1, x2, y2, shape_type, label)
    net_rects = defaultdict(list)
    all_rects = []  # (x1, y1, x2, y2, net)

    # Signal and pre-route segments
    for rk in ('signal_routes', 'pre_routes'):
        for net, rd in routing.get(rk, {}).items():
            for seg in rd.get('segments', []):
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, lyr = seg[:5]

                if lyr == M3_LYR:  # M3 wire
                    if x1 == x2:  # vertical
                        r = (x1 - HW, min(y1, y2), x1 + HW, max(y1, y2))
                    elif y1 == y2:  # horizontal
                        r = (min(x1, x2), y1 - HW, max(x1, x2), y1 + HW)
                    else:
                        continue
                    net_rects[net].append((*r, 'wire',
                        f'wire({x1},{y1})->({x2},{y2})'))
                    all_rects.append((*r, net))

                elif lyr == VIA2_SEG:  # Via2 pad on M3
                    r = (x1 - VP2, y1 - VP2, x1 + VP2, y1 + VP2)
                    net_rects[net].append((*r, 'v2pad', f'v2pad@({x1},{y1})'))
                    all_rects.append((*r, net))

                elif lyr == VIA3_SEG:  # Via3 pad on M3
                    r = (x1 - VP3, y1 - VP3, x1 + VP3, y1 + VP3)
                    net_rects[net].append((*r, 'v3pad', f'v3pad@({x1},{y1})'))
                    all_rects.append((*r, net))

    # Power shapes (vbars, v2pads, rails)
    for rid, rail in routing.get('power', {}).get('rails', {}).items():
        hw_r = rail['width'] // 2
        net = rail.get('net', rid)
        r = (rail['x1'], rail['y'] - hw_r, rail['x2'], rail['y'] + hw_r)
        net_rects[net].append((*r, 'rail', f'rail_{rid}'))
        all_rects.append((*r, net))

    for drop in routing.get('power', {}).get('drops', []):
        vbar = drop.get('m3_vbar')
        if not vbar:
            continue
        net = drop['net']
        vhw = M3_MIN_W // 2  # 100nm
        x = vbar[0]
        y1 = min(vbar[1], vbar[3])
        y2 = max(vbar[1], vbar[3])
        r = (x - vhw, y1, x + vhw, y2)
        net_rects[net].append((*r, 'vbar',
            f"vbar_{drop['inst']}.{drop['pin']}"))
        all_rects.append((*r, net))

        v2 = drop.get('via2_pos')
        if v2:
            hp = VIA2_PAD_M3 // 2
            r = (v2[0] - hp, v2[1] - hp, v2[0] + hp, v2[1] + hp)
            net_rects[net].append((*r, 'pwr_v2pad',
                f"pv2pad_{drop['inst']}.{drop['pin']}"))
            all_rects.append((*r, net))

    return net_rects, all_rects, routing


def rect_contains_point(r, px, py, margin=50):
    return r[0] - margin <= px <= r[2] + margin and r[1] - margin <= py <= r[3] + margin


def find_rects_near_edge(edge, net_rects_flat):
    """Find all M3 rects that contain the edge midpoint."""
    mx = (edge[0] + edge[2]) / 2
    my = (edge[1] + edge[3]) / 2
    matches = []
    for x1, y1, x2, y2, net, stype, label in net_rects_flat:
        if rect_contains_point((x1, y1, x2, y2), mx, my, margin=100):
            matches.append((x1, y1, x2, y2, net, stype, label))
    return matches


def classify_violation(e1, e2, net_rects, all_flat):
    """Classify a violation into a geometric pattern."""
    r1_list = find_rects_near_edge(e1, all_flat)
    r2_list = find_rects_near_edge(e2, all_flat)

    if not r1_list or not r2_list:
        return 'unknown', None

    r1 = r1_list[0]
    r2 = r2_list[0]
    net1, net2 = r1[4], r2[4]
    type1, type2 = r1[5], r2[5]
    same_net = net1 == net2

    # Determine edge orientation
    e1_horiz = abs(e1[1] - e1[3]) < 5
    e1_vert = abs(e1[0] - e1[2]) < 5

    # Gap computation from edge midpoints
    mx1, my1 = (e1[0]+e1[2])/2, (e1[1]+e1[3])/2
    mx2, my2 = (e2[0]+e2[2])/2, (e2[1]+e2[3])/2
    dx, dy = abs(mx2-mx1), abs(my2-my1)

    info = {
        'net1': net1, 'net2': net2,
        'type1': type1, 'type2': type2,
        'label1': r1[6], 'label2': r2[6],
        'same_net': same_net,
        'gap_x': dx, 'gap_y': dy,
        'rect1': r1[:4], 'rect2': r2[:4],
        'e1': e1, 'e2': e2,
    }

    if same_net:
        # Check if both edges belong to wire-wire L-corner
        both_wire = 'wire' in type1 and 'wire' in type2
        has_vpad = 'pad' in type1 or 'pad' in type2
        has_vbar = 'vbar' in type1 or 'vbar' in type2

        if both_wire:
            # Check if it's an L-corner pattern
            # Two wires meeting at a point, one H one V
            # The notch is at the concave corner
            return 'same_net_wire_notch', info
        elif has_vpad and has_vbar:
            return 'same_net_vpad_vbar_notch', info
        elif has_vbar:
            return 'same_net_vbar_self', info
        else:
            return 'same_net_other', info
    else:
        return 'cross_net_spacing', info


def find_m3_lcorners(routing):
    """Find all same-net M3 L-corners and compute corner fill rects."""
    corners = []

    for rk in ('signal_routes', 'pre_routes'):
        for net, rd in routing.get(rk, {}).items():
            segs = rd.get('segments', [])
            m3_segs = []
            via_pos = set()

            for seg in segs:
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, lyr = seg[:5]
                if lyr == M3_LYR:
                    m3_segs.append((x1, y1, x2, y2))
                elif lyr == VIA2_SEG:
                    via_pos.add((x1, y1))
                elif lyr == VIA3_SEG:
                    via_pos.add((x1, y1))

            # Find L-corners: pairs of M3 segments sharing an endpoint
            for i, s1 in enumerate(m3_segs):
                for j, s2 in enumerate(m3_segs):
                    if j <= i:
                        continue

                    # Check if they share an endpoint
                    ep1 = [(s1[0], s1[1]), (s1[2], s1[3])]
                    ep2 = [(s2[0], s2[1]), (s2[2], s2[3])]

                    shared = None
                    for p1 in ep1:
                        for p2 in ep2:
                            if p1 == p2:
                                shared = p1

                    if not shared:
                        continue

                    # Check one is H, one is V
                    s1_h = s1[1] == s1[3]
                    s1_v = s1[0] == s1[2]
                    s2_h = s2[1] == s2[3]
                    s2_v = s2[0] == s2[2]

                    if not ((s1_h and s2_v) or (s1_v and s2_h)):
                        continue

                    # Compute the concave corner fill rectangle
                    h_seg = s1 if s1_h else s2
                    v_seg = s1 if s1_v else s2

                    cx, cy = shared  # corner point

                    # Vertical wire rect
                    vr = (cx - HW, min(v_seg[1], v_seg[3]),
                          cx + HW, max(v_seg[1], v_seg[3]))

                    # Horizontal wire rect
                    hr = (min(h_seg[0], h_seg[2]), cy - HW,
                          max(h_seg[0], h_seg[2]), cy + HW)

                    # The concave corner is the area NOT covered by either rect
                    # but within the bounding box of their overlap corner.
                    # Determine which quadrant the notch is in:

                    # Horizontal wire goes left or right from the corner
                    h_goes_right = (max(h_seg[0], h_seg[2]) > cx)
                    h_goes_left = (min(h_seg[0], h_seg[2]) < cx)

                    # Vertical wire goes up or down from the corner
                    v_goes_up = (max(v_seg[1], v_seg[3]) > cy)
                    v_goes_down = (min(v_seg[1], v_seg[3]) < cy)

                    # The notch is in the quadrant OPPOSITE to where the wires go.
                    # If H goes right and V goes down, notch is top-left.
                    fills = []

                    if h_goes_right and v_goes_down:
                        # Notch at top-left: (cx-HW, cy, cx, cy+HW)
                        fills.append((cx - HW, cy, cx, cy + HW))
                    if h_goes_right and v_goes_up:
                        # Notch at bottom-left: (cx-HW, cy-HW, cx, cy)
                        fills.append((cx - HW, cy - HW, cx, cy))
                    if h_goes_left and v_goes_down:
                        # Notch at top-right: (cx, cy, cx+HW, cy+HW)
                        fills.append((cx, cy, cx + HW, cy + HW))
                    if h_goes_left and v_goes_up:
                        # Notch at bottom-right: (cx, cy-HW, cx+HW, cy)
                        fills.append((cx, cy - HW, cx + HW, cy))

                    for fill in fills:
                        corners.append({
                            'net': net,
                            'corner': shared,
                            'h_seg': h_seg,
                            'v_seg': v_seg,
                            'fill_rect': fill,
                            'at_via': shared in via_pos,
                        })

    return corners


def check_fill_safety(fill_rect, fill_net, all_rects):
    """Check if a fill rectangle would create any new cross-net violations."""
    fx1, fy1, fx2, fy2 = fill_rect
    conflicts = []

    for rx1, ry1, rx2, ry2, rnet in all_rects:
        if rnet == fill_net:
            continue  # same net, no spacing issue

        # Check spacing between fill rect and this cross-net rect
        x_gap = max(rx1 - fx2, fx1 - rx2, 0)
        y_gap = max(ry1 - fy2, fy1 - ry2, 0)

        if x_gap > 0 and y_gap > 0:
            continue  # diagonal, no issue
        if x_gap >= M3_MIN_S and y_gap >= M3_MIN_S:
            continue  # sufficient spacing

        # Parallel run check
        if x_gap < M3_MIN_S and y_gap <= 0:
            # X gap with Y overlap
            y_overlap = min(fy2, ry2) - max(fy1, ry1)
            if y_overlap > 0 and x_gap < M3_MIN_S:
                conflicts.append((rnet, x_gap, f'X-gap={x_gap}nm, Y-overlap={y_overlap}nm'))
        if y_gap < M3_MIN_S and x_gap <= 0:
            # Y gap with X overlap
            x_overlap = min(fx2, rx2) - max(fx1, rx1)
            if x_overlap > 0 and y_gap < M3_MIN_S:
                conflicts.append((rnet, y_gap, f'Y-gap={y_gap}nm, X-overlap={x_overlap}nm'))

    return conflicts


def main():
    viols = load_violations()
    net_rects, all_rects, routing = load_m3_shapes()

    # Flatten net_rects for lookup
    all_flat = []
    for net, rects in net_rects.items():
        for r in rects:
            all_flat.append((*r[:4], net, r[4], r[5]))

    print(f'Loaded {len(viols)} M3.b violations')
    print(f'Total M3 rects: {len(all_rects)}, nets: {len(net_rects)}')
    print(f'M3_MIN_S={M3_MIN_S}, M3_WIRE_W={M3_WIRE_W}, HW={HW}')
    print(f'VIA2_PAD_M3={VIA2_PAD_M3} (hp={VP2}), VIA3_PAD={VIA3_PAD} (hp={VP3})')
    print()

    # Classify each violation
    patterns = defaultdict(list)
    for idx, (e1, e2) in enumerate(viols, 1):
        pattern, info = classify_violation(e1, e2, net_rects, all_flat)
        patterns[pattern].append((idx, info))

    print('=== Pattern Classification ===\n')
    for pattern, items in sorted(patterns.items()):
        print(f'{pattern}: {len(items)} violations')
        for idx, info in items:
            if info:
                gap = max(info['gap_x'], info['gap_y'])
                net_str = f"SAME({info['net1']})" if info['same_net'] else f"CROSS({info['net1']}/{info['net2']})"
                print(f'  V{idx}: gap≈{gap:.0f}nm {net_str} '
                      f'{info["type1"]}({info["label1"]}) vs {info["type2"]}({info["label2"]})')
            else:
                print(f'  V{idx}: no info')
    print()

    # Find all same-net M3 L-corners
    corners = find_m3_lcorners(routing)
    print(f'=== M3 L-corners found: {len(corners)} ===\n')

    # Filter to corners near violations
    print('L-corners near M3.b violations:')
    for c in corners:
        cx, cy = c['corner']
        # Check if any violation is near this corner
        near_viols = []
        for idx, (e1, e2) in enumerate(viols, 1):
            mx = (e1[0]+e1[2]+e2[0]+e2[2])/4
            my = (e1[1]+e1[3]+e2[1]+e2[3])/4
            if abs(mx - cx) < 2000 and abs(my - cy) < 2000:
                near_viols.append(idx)

        if near_viols:
            fr = c['fill_rect']
            print(f'\n  Corner ({cx},{cy}) net={c["net"]} at_via={c["at_via"]}')
            print(f'    H: ({c["h_seg"][0]},{c["h_seg"][1]})->({c["h_seg"][2]},{c["h_seg"][3]})')
            print(f'    V: ({c["v_seg"][0]},{c["v_seg"][1]})->({c["v_seg"][2]},{c["v_seg"][3]})')
            print(f'    Fill: ({fr[0]},{fr[1]})->({fr[2]},{fr[3]}) = {fr[2]-fr[0]}x{fr[3]-fr[1]}nm')
            print(f'    Near violations: {near_viols}')

            # Check safety
            conflicts = check_fill_safety(fr, c['net'], all_rects)
            if conflicts:
                print(f'    ⚠ UNSAFE — {len(conflicts)} cross-net conflict(s):')
                for cnet, cgap, desc in conflicts:
                    print(f'      vs {cnet}: {desc}')
            else:
                print(f'    ✓ SAFE — no cross-net conflicts within M3_MIN_S={M3_MIN_S}nm')

    # Also check: are there any same-net via-pad L-junctions causing violations?
    print('\n\n=== Via pad notch analysis ===\n')
    for idx, (e1, e2) in enumerate(viols, 1):
        pattern, info = classify_violation(e1, e2, net_rects, all_flat)
        if not info or not info['same_net']:
            continue
        if 'pad' in info['type1'] or 'pad' in info['type2'] or 'vbar' in info['type1'] or 'vbar' in info['type2']:
            print(f'V{idx}: {pattern}')
            print(f'  {info["type1"]}({info["label1"]}) rect={info["rect1"]}')
            print(f'  {info["type2"]}({info["label2"]}) rect={info["rect2"]}')

            # Compute the notch between shapes
            r1, r2 = info['rect1'], info['rect2']
            x_gap = max(r1[0] - r2[2], r2[0] - r1[2], 0)
            y_gap = max(r1[1] - r2[3], r2[1] - r1[3], 0)
            x_overlap = min(r1[2], r2[2]) - max(r1[0], r2[0])
            y_overlap = min(r1[3], r2[3]) - max(r1[1], r2[1])
            print(f'  x_gap={x_gap} y_gap={y_gap} x_overlap={x_overlap} y_overlap={y_overlap}')

            # Check notch dimensions
            if x_overlap > 0 and y_overlap > 0:
                # Shapes overlap — merged polygon has concave corner(s)
                # Width step on each side
                for axis, o, g in [('X', x_overlap, 'x'), ('Y', y_overlap, 'y')]:
                    step_lo = abs(r1[0 if g=='x' else 1] - r2[0 if g=='x' else 1])
                    step_hi = abs(r1[2 if g=='x' else 3] - r2[2 if g=='x' else 3])
                    if 0 < step_lo < M3_MIN_S:
                        print(f'  → {axis} notch: step_lo={step_lo}nm < M3_MIN_S={M3_MIN_S}nm')
                    if 0 < step_hi < M3_MIN_S:
                        print(f'  → {axis} notch: step_hi={step_hi}nm < M3_MIN_S={M3_MIN_S}nm')
            elif x_gap > 0 and x_gap < M3_MIN_S:
                print(f'  → X gap={x_gap}nm < M3_MIN_S={M3_MIN_S}nm (fillable)')
            elif y_gap > 0 and y_gap < M3_MIN_S:
                print(f'  → Y gap={y_gap}nm < M3_MIN_S={M3_MIN_S}nm (fillable)')
    print()

    # Summary: fixable violations
    print('=== Fix Summary ===\n')

    safe_fills = []
    for c in corners:
        cx, cy = c['corner']
        near = []
        for idx, (e1, e2) in enumerate(viols, 1):
            mx = (e1[0]+e1[2]+e2[0]+e2[2])/4
            my = (e1[1]+e1[3]+e2[1]+e2[3])/4
            if abs(mx - cx) < 2000 and abs(my - cy) < 2000:
                near.append(idx)
        if near:
            conflicts = check_fill_safety(c['fill_rect'], c['net'], all_rects)
            if not conflicts:
                safe_fills.append((c, near))

    if safe_fills:
        print(f'Safe L-corner fills: {len(safe_fills)}')
        viol_ids = set()
        for c, near in safe_fills:
            fr = c['fill_rect']
            print(f'  {c["net"]} at ({c["corner"][0]},{c["corner"][1]}): '
                  f'fill ({fr[0]},{fr[1]})->({fr[2]},{fr[3]}) → fixes V{near}')
            viol_ids.update(near)
        print(f'\nTotal violations potentially fixed by L-corner fills: {len(viol_ids)}')
    else:
        print('No safe L-corner fills found.')


if __name__ == '__main__':
    main()
