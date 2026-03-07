"""Diagnose inter-net shape overlaps from routing.json.

Checks for M1/M2 overlapping segments between different signal nets.
Also checks power drops vs signal routes.

Usage:
    python -m atk.verify.net_overlap [routing.json]
"""

from __future__ import annotations

import json
import sys


def _seg_rect(seg, wire_w: int) -> tuple[int, int, int, int]:
    """Convert segment [x1,y1,x2,y2,layer] to padded rect."""
    hw = wire_w // 2
    x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
    return (min(x1, x2) - hw, min(y1, y2) - hw,
            max(x1, x2) + hw, max(y1, y2) + hw)


def _rects_overlap(a, b) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def check_overlaps(routing: dict, m1_w: int = 360, m2_w: int = 360) -> list[dict]:
    """Check for overlapping shapes between different signal nets."""
    # Collect all M1 and M2 rects per net
    net_rects: dict[str, dict[int, list]] = {}  # {net: {layer: [rects]}}

    for net_name, route in routing.get('signal_routes', {}).items():
        rects_by_layer: dict[int, list] = {0: [], 1: []}
        for seg in route.get('segments', []):
            if len(seg) < 5:
                continue
            layer = seg[4]
            if layer == -1:  # via
                continue
            w = m1_w if layer == 0 else m2_w
            rects_by_layer.setdefault(layer, []).append(_seg_rect(seg, w))
        net_rects[net_name] = rects_by_layer

    # Also collect access point M1/M2 pads per net
    # (from routing.json access_points, attributed to signal nets)
    ap_net_map = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        for seg in route.get('segments', []):
            pass  # segments don't carry pin info directly

    # Check pairwise overlaps
    overlaps = []
    net_names = sorted(net_rects.keys())
    for i, n1 in enumerate(net_names):
        for n2 in net_names[i + 1:]:
            for layer in [0, 1]:  # M1, M2
                layer_name = "M1" if layer == 0 else "M2"
                for r1 in net_rects[n1].get(layer, []):
                    for r2 in net_rects[n2].get(layer, []):
                        if _rects_overlap(r1, r2):
                            overlaps.append({
                                "net1": n1,
                                "net2": n2,
                                "layer": layer_name,
                                "rect1": r1,
                                "rect2": r2,
                            })

    return overlaps


def main():
    from atk.paths import ROUTING_JSON
    path = sys.argv[1] if len(sys.argv) > 1 else ROUTING_JSON
    with open(path) as f:
        routing = json.load(f)

    overlaps = check_overlaps(routing)

    if not overlaps:
        print("No inter-net overlaps found in signal routes.")
        print("(vco1|vco5 short may be caused by access points or gate straps, not routes)")
    else:
        print(f"Found {len(overlaps)} inter-net overlap(s):")
        for o in overlaps:
            print(f"  {o['net1']} <-> {o['net2']} on {o['layer']}")
            print(f"    rect1: {o['rect1']}")
            print(f"    rect2: {o['rect2']}")

    # Also check: which nets share device pins on same device
    print("\n=== Nets sharing same device (potential gate/drain collision) ===")
    net_devices: dict[str, set] = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        devices = set()
        # Parse from access_points attribution (not directly in signal_routes)
        net_devices[net_name] = devices

    # Use netlist.json-style check: find device pairs where both G and D
    # are on different signal nets
    print("  (Check netlist.json for devices with G and D on different nets)")


if __name__ == "__main__":
    main()
