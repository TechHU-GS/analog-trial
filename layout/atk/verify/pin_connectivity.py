"""Check which signal routes physically reach which access points.

Compares routing.json segments vs access point M1/M2 pads
to detect misrouted connections (net reaching wrong pin).

Usage:
    python -m atk.verify.pin_connectivity [routing.json] [netlist.json]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict


def _rects_overlap(a, b) -> bool:
    """Check if two rectangles overlap (strict)."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _seg_to_rect(seg, w: int) -> tuple[int, int, int, int]:
    """Convert segment to padded rectangle."""
    hw = w // 2
    return (min(seg[0], seg[2]) - hw, min(seg[1], seg[3]) - hw,
            max(seg[0], seg[2]) + hw, max(seg[1], seg[3]) + hw)


def check_pin_connectivity(routing: dict, netlist: dict,
                           m1_w: int = 360, m2_w: int = 360) -> dict:
    """Check which signal nets physically touch which device access points.

    Returns dict with:
    - expected: {inst.pin: net_name} from netlist
    - actual: {inst.pin: [nets that reach it]} from geometry
    - mismatches: list of issues
    """
    # Build expected pin→net map from netlist
    expected = {}
    for net in netlist.get('nets', []):
        if net.get('type') == 'power':
            continue
        for pin_str in net['pins']:
            expected[pin_str] = net['name']

    # Collect M1 and M2 rects per signal net
    net_rects = {}  # {net: {layer_idx: [rects]}}
    for net_name, route in routing.get('signal_routes', {}).items():
        rects = {0: [], 1: []}  # M1, M2
        for seg in route.get('segments', []):
            if len(seg) < 5 or seg[4] == -1:
                continue
            layer = seg[4]
            w = m1_w if layer == 0 else m2_w
            rects.setdefault(layer, []).append(_seg_to_rect(seg, w))
        net_rects[net_name] = rects

    # For each access point, check which nets reach it
    actual = defaultdict(list)  # {inst.pin: [nets]}
    for key, ap in routing.get('access_points', {}).items():
        vp = ap.get('via_pad', {})
        m1_pad = vp.get('m1')
        m2_pad = vp.get('m2')

        for net_name, rects in net_rects.items():
            touched = False
            # Check M1 overlap
            if m1_pad:
                for r in rects.get(0, []):
                    if _rects_overlap(m1_pad, r):
                        touched = True
                        break
            # Check M2 overlap
            if not touched and m2_pad:
                for r in rects.get(1, []):
                    if _rects_overlap(m2_pad, r):
                        touched = True
                        break
            if touched:
                actual[key].append(net_name)

    # Compare expected vs actual
    mismatches = []
    for pin_str, expected_net in sorted(expected.items()):
        reached_nets = actual.get(pin_str, [])
        if expected_net not in reached_nets:
            mismatches.append({
                'pin': pin_str,
                'expected': expected_net,
                'actual': reached_nets,
                'issue': 'not_reached' if not reached_nets else 'wrong_net',
            })
        if len(reached_nets) > 1:
            mismatches.append({
                'pin': pin_str,
                'expected': expected_net,
                'actual': reached_nets,
                'issue': 'multi_net',
            })

    return {
        'expected': expected,
        'actual': dict(actual),
        'mismatches': mismatches,
    }


def main():
    from atk.paths import ROUTING_JSON
    routing_path = sys.argv[1] if len(sys.argv) > 1 else ROUTING_JSON
    netlist_path = sys.argv[2] if len(sys.argv) > 2 else "netlist.json"

    with open(routing_path) as f:
        routing = json.load(f)
    with open(netlist_path) as f:
        netlist = json.load(f)

    result = check_pin_connectivity(routing, netlist)

    print(f"Expected connections: {len(result['expected'])}")
    print(f"Access points with signal contact: {len(result['actual'])}")

    if not result['mismatches']:
        print("\nAll signal routes reach correct pins. No mismatches.")
    else:
        print(f"\n{len(result['mismatches'])} mismatch(es):")
        for m in result['mismatches']:
            print(f"  {m['pin']:12s}: expected={m['expected']:12s}, "
                  f"actual={m['actual']}, issue={m['issue']}")

    # Show complete mapping for buffer devices
    print("\n=== Buffer device pin connectivity ===")
    for key in sorted(result['actual']):
        if key.startswith('MBp') or key.startswith('MBn'):
            nets = result['actual'][key]
            exp = result['expected'].get(key, '?')
            ok = exp in nets
            print(f"  {key:12s}: reached_by={nets:30s}  expected={exp:10s}  {'OK' if ok else 'MISMATCH'}")


if __name__ == "__main__":
    main()
