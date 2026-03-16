#!/usr/bin/env python3
"""Diagnose M4.b DRC violations — find all M4 cross-net shape pairs with gap < M4_MIN_S.

Includes: M4 wire segments + Via3 pad M4 footprints + fill shapes.
"""
import json
import sys

sys.path.insert(0, '.')
from atk.pdk import M4_MIN_S, M4_SIG_W, VIA3_PAD
from atk.route.maze_router import M4_LYR

HW = M4_SIG_W // 2   # 100nm
V3_HP = VIA3_PAD // 2  # 190nm


def load_m4_shapes(routing_path):
    """Load ALL M4 physical shapes per net: wire rects + via3 pad rects."""
    with open(routing_path) as f:
        data = json.load(f)

    # net → [(x1,y1,x2,y2, type_label), ...]
    net_shapes = {}

    for route_dict_name in ('signal_routes', 'pre_routes'):
        for net, rd in data.get(route_dict_name, {}).items():
            shapes = net_shapes.setdefault(net, [])
            for seg in rd.get('segments', []):
                if len(seg) < 5:
                    continue
                x1, y1, x2, y2, lyr = seg[:5]
                if lyr == M4_LYR:
                    # Wire segment → rect
                    if x1 == x2:  # vertical
                        shapes.append((x1 - HW, min(y1, y2), x1 + HW, max(y1, y2),
                                       f'wire_V@x={x1}'))
                    elif y1 == y2:  # horizontal
                        shapes.append((min(x1, x2), y1 - HW, max(x1, x2), y1 + HW,
                                       f'wire_H@y={y1}'))
                    else:
                        shapes.append((min(x1, x2) - HW, min(y1, y2) - HW,
                                       max(x1, x2) + HW, max(y1, y2) + HW,
                                       f'wire_D'))
                elif lyr == -3:  # Via3 → M4 pad
                    shapes.append((x1 - V3_HP, y1 - V3_HP, x1 + V3_HP, y1 + V3_HP,
                                   f'v3pad@({x1},{y1})'))

    return net_shapes, data


def rect_gap_xy(a, b):
    """Return (x_gap, y_gap) between two rects. Positive = separated."""
    xg = max(a[0] - b[2], b[0] - a[2])
    yg = max(a[1] - b[3], b[1] - a[3])
    return xg, yg


def main():
    routing_path = 'output/routing.json'
    net_shapes, data = load_m4_shapes(routing_path)

    print("=== M4.b Violation Diagnosis (wires + via3 pads) ===\n")
    print(f"M4_MIN_S = {M4_MIN_S}nm, M4_SIG_W = {M4_SIG_W}nm, VIA3_PAD = {VIA3_PAD}nm\n")

    # Count shapes per net
    total_shapes = sum(len(s) for s in net_shapes.values())
    wire_count = sum(1 for shapes in net_shapes.values()
                     for s in shapes if s[4].startswith('wire'))
    v3_count = sum(1 for shapes in net_shapes.values()
                   for s in shapes if s[4].startswith('v3pad'))
    print(f"Total M4 shapes: {total_shapes} ({wire_count} wires, {v3_count} via3 pads)")
    print(f"Nets with M4 shapes: {len(net_shapes)}\n")

    # Find all cross-net M4 shape pairs with edge gap < M4_MIN_S
    nets = list(net_shapes.keys())
    violations = []

    for i, net_a in enumerate(nets):
        for net_b in nets[i+1:]:
            shapes_a = net_shapes[net_a]
            shapes_b = net_shapes[net_b]
            for sa in shapes_a:
                for sb in shapes_b:
                    xg, yg = rect_gap_xy(sa[:4], sb[:4])
                    # Violation: one dimension gap < M4_MIN_S, other dimension overlapping
                    if (xg >= 0 and xg < M4_MIN_S and yg < 0) or \
                       (yg >= 0 and yg < M4_MIN_S and xg < 0):
                        gap = xg if yg < 0 else yg
                        violations.append((gap, net_a, net_b, sa, sb, xg, yg))

    violations.sort(key=lambda v: v[0])

    # Categorize
    categories = {}
    for idx, (gap, net_a, net_b, sa, sb, xg, yg) in enumerate(violations):
        type_a = 'v3pad' if sa[4].startswith('v3pad') else 'wire'
        type_b = 'v3pad' if sb[4].startswith('v3pad') else 'wire'
        cat = f"{min(type_a,type_b)}-{max(type_a,type_b)}"
        categories[cat] = categories.get(cat, 0) + 1

        print(f"Viol {idx+1}: gap={gap}nm  xg={xg} yg={yg}")
        print(f"  {net_a:20s} {sa[4]}")
        print(f"    rect=({sa[0]},{sa[1]},{sa[2]},{sa[3]})")
        print(f"  {net_b:20s} {sb[4]}")
        print(f"    rect=({sb[0]},{sb[1]},{sb[2]},{sb[3]})")
        print()

    print(f"=== Total M4 violations: {len(violations)} ===")
    print(f"\nBy category:")
    for cat, cnt in sorted(categories.items()):
        print(f"  {cat}: {cnt}")

    # Unique net pairs
    net_pairs = set()
    for gap, net_a, net_b, sa, sb, xg, yg in violations:
        net_pairs.add((min(net_a, net_b), max(net_a, net_b)))
    print(f"\nUnique net pairs: {len(net_pairs)}")
    for na, nb in sorted(net_pairs):
        cnt = sum(1 for v in violations
                  if (min(v[1], v[2]), max(v[1], v[2])) == (na, nb))
        print(f"  {na} — {nb}: {cnt}")


if __name__ == '__main__':
    main()
