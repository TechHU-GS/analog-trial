#!/usr/bin/env python3
"""Fix fragmented nets in routing.json by adding bridge segments.

For each net with disconnected components, finds the closest pair of
endpoints between fragments and adds an M2 bridge segment to connect them.
Repeats until the net is fully connected.

Usage:
    python3 -m atk.fix_routing_fragments
"""

import json
import math
import os
from collections import defaultdict


def find_components(segs):
    """Find connected components in a list of segments."""
    adj = defaultdict(set)
    for i, seg in enumerate(segs):
        x1, y1, x2, y2 = seg[:4]
        adj[(x1, y1)].add(i)
        adj[(x2, y2)].add(i)

    visited = set()
    components = []

    for i in range(len(segs)):
        if i in visited:
            continue
        queue = [i]
        comp = set()
        while queue:
            si = queue.pop()
            if si in visited:
                continue
            visited.add(si)
            comp.add(si)
            x1, y1, x2, y2 = segs[si][:4]
            for p in [(x1, y1), (x2, y2)]:
                for ni in adj[p]:
                    if ni not in visited:
                        queue.append(ni)
        components.append(comp)

    return components


def get_endpoints(segs, comp):
    """Get all unique endpoints of segments in a component."""
    pts = set()
    for i in comp:
        x1, y1, x2, y2 = segs[i][:4]
        pts.add((x1, y1))
        pts.add((x2, y2))
    return pts


def fix_routing(routing_path=None, output_path=None):
    """Fix fragmented nets by adding M2 bridge segments."""
    if routing_path is None:
        layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        routing_path = os.path.join(layout_dir, 'output', 'routing.json')
    if output_path is None:
        output_path = routing_path

    with open(routing_path) as f:
        routing = json.load(f)

    fixed = 0
    bridges_added = 0

    for net_name, route in routing.get('signal_routes', {}).items():
        segs = route.get('segments', [])
        if not segs:
            continue

        while True:
            components = find_components(segs)
            if len(components) <= 1:
                break

            # Find closest pair of endpoints between any two components
            best_dist = float('inf')
            best_pair = None
            best_comps = None

            for ci, comp_a in enumerate(components):
                pts_a = get_endpoints(segs, comp_a)
                for cj in range(ci + 1, len(components)):
                    pts_b = get_endpoints(segs, components[cj])
                    for pa in pts_a:
                        for pb in pts_b:
                            d = abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])
                            if d < best_dist:
                                best_dist = d
                                best_pair = (pa, pb)
                                best_comps = (ci, cj)

            if best_pair is None:
                break

            # Add M2 bridge segment (layer 1 = M2)
            (x1, y1), (x2, y2) = best_pair
            # Route Manhattan: horizontal then vertical
            if x1 != x2:
                segs.append([x1, y1, x2, y1, 1])  # horizontal M2
                if y1 != y2:
                    segs.append([x2, y1, x2, y2, 1])  # vertical M2
            elif y1 != y2:
                segs.append([x1, y1, x1, y2, 1])  # vertical M2
            else:
                # Same point — shouldn't happen
                break

            bridges_added += 1

        new_comps = find_components(segs)
        if len(new_comps) == 1:
            fixed += 1

        route['segments'] = segs

    with open(output_path, 'w') as f:
        json.dump(routing, f, indent=2)

    print(f'  Fixed nets: {fixed}')
    print(f'  Bridges added: {bridges_added}')
    print(f'  Total segments: {sum(len(r.get("segments", [])) for r in routing["signal_routes"].values())}')


if __name__ == '__main__':
    fix_routing()
