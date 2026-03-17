#!/usr/bin/env python3
"""Snap routing segment endpoints to nearest AP positions.

The maze router routes on a grid. Segment endpoints land on grid points,
NOT on AP (access point) positions. In KLayout, assemble_gds.py bridges
this gap with M2 pads. In Magic, we need endpoints to physically touch
AP M2 pads for extraction to see the connection.

This script post-processes routing.json: for each segment endpoint,
if there's an AP within SNAP_RADIUS, move the endpoint to the AP position.

Usage:
    cd layout && python3 -m atk.snap_routing_to_ap
"""

import json
import os


SNAP_RADIUS = 500  # nm — max distance to snap


def snap_routing(routing_path=None):
    if routing_path is None:
        routing_path = 'output/routing.json'

    with open(routing_path) as f:
        routing = json.load(f)

    aps = routing.get('access_points', {})
    routes = routing.get('signal_routes', {})

    # Build AP position lookup: (x, y) → pin_key
    # Also build spatial index: for each AP, store position
    ap_list = [(ap['x'], ap['y'], pk) for pk, ap in aps.items()]

    # Build net → set of AP positions
    # Each AP belongs to a device pin, pin belongs to a net
    # We need to know which APs belong to which net
    pin_to_net = {}
    for net_name, route in routes.items():
        # The route's segments connect APs that belong to this net
        # Find APs for this net from the pin keys
        pass

    # Actually, just snap ALL endpoints to nearest AP regardless of net
    # The APs already encode the correct positions for each pin
    snapped = 0
    total_endpoints = 0

    for net_name, route in routes.items():
        segs = route.get('segments', [])
        new_segs = []

        for seg in segs:
            if len(seg) < 5:
                new_segs.append(seg)
                continue

            x1, y1, x2, y2, lyr = seg[:5]
            extra = seg[5:] if len(seg) > 5 else []

            # Try to snap each endpoint
            nx1, ny1, s1 = _snap_point(x1, y1, ap_list)
            nx2, ny2, s2 = _snap_point(x2, y2, ap_list)

            if s1:
                snapped += 1
            if s2:
                snapped += 1
            total_endpoints += 2

            new_segs.append([nx1, ny1, nx2, ny2, lyr] + extra)

        route['segments'] = new_segs

    with open(routing_path, 'w') as f:
        json.dump(routing, f, indent=2)

    print(f'  Endpoints: {total_endpoints}')
    print(f'  Snapped: {snapped} ({snapped * 100 // total_endpoints}%)')
    print(f'  Unchanged: {total_endpoints - snapped}')


def _snap_point(x, y, ap_list):
    """Snap (x, y) to nearest AP if within SNAP_RADIUS."""
    best_d = SNAP_RADIUS + 1
    best_x, best_y = x, y

    for ax, ay, _ in ap_list:
        d = abs(x - ax) + abs(y - ay)
        if d < best_d:
            best_d = d
            best_x, best_y = ax, ay

    if best_d <= SNAP_RADIUS:
        return best_x, best_y, True
    return x, y, False


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    snap_routing()
