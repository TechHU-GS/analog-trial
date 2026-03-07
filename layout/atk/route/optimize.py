"""Post-routing optimizer: Z-jog elimination.

Reads routing.json, simplifies signal route segments by removing
unnecessary Z-shaped jogs (H->V(short)->H or V->H(short)->V patterns).

DRC-safe: checks that straightened paths don't violate minimum spacing
with other nets' segments before applying each transformation.

Usage: cd layout && python -m atk.route.optimize
"""

import json
import sys
from collections import defaultdict

from ..pdk import (
    MAZE_GRID,
    M1_SIG_W, M2_SIG_W,
    M1_MIN_S, M2_MIN_S,
)
from ..paths import ROUTING_JSON

# Eliminate jogs shorter than this (nm).
# MAZE_GRID = 350nm; threshold catches 1-grid-step quantization jogs.
JOG_THRESHOLD = MAZE_GRID + 50  # 400nm


def _is_h(seg):
    return seg[1] == seg[3] and seg[0] != seg[2]


def _is_v(seg):
    return seg[0] == seg[2] and seg[1] != seg[3]


def _seg_len(seg):
    return abs(seg[2] - seg[0]) + abs(seg[3] - seg[1])


def _far_ep(seg, shared):
    """Return the endpoint of seg that is NOT shared."""
    p1 = (seg[0], seg[1])
    p2 = (seg[2], seg[3])
    return p2 if p1 == shared else p1


def _rect_overlap(a, b):
    """Check if two (x1,y1,x2,y2) rects overlap."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _segs_spacing_ok(new_segs, other_segs, obstacle_rects, layer, min_s, wire_w):
    """Check new segments don't violate spacing with other nets or obstacles.

    Args:
        other_segs: segments from other nets (centerlines, use wire_w)
        obstacle_rects: pre-computed (x1,y1,x2,y2,layer) rectangles from
                        power drops, access points, etc. (already full-size)
    """
    hw = wire_w // 2
    for ns in new_segs:
        # Bounding box of new segment expanded by half-width + spacing
        nr = (min(ns[0], ns[2]) - hw - min_s,
              min(ns[1], ns[3]) - hw - min_s,
              max(ns[0], ns[2]) + hw + min_s,
              max(ns[1], ns[3]) + hw + min_s)
        for os in other_segs:
            if len(os) < 5 or os[4] != layer:
                continue
            ob = (min(os[0], os[2]) - hw,
                  min(os[1], os[3]) - hw,
                  max(os[0], os[2]) + hw,
                  max(os[1], os[3]) + hw)
            if _rect_overlap(nr, ob):
                return False
        # Check against obstacle rectangles (power M2, access M2 pads)
        for orect in obstacle_rects:
            if orect[4] != layer:
                continue
            if _rect_overlap(nr, orect[:4]):
                return False
    return True


def _creates_same_net_gap(new_segs, remaining_segs, layer, min_s, wire_w):
    """Check if new segments create close-but-not-touching gaps with same-net.

    DRC checks spacing between ALL shapes regardless of net connectivity.
    Same-net shapes that are close but don't touch/overlap violate M2.b/M1.b.
    """
    hw = wire_w // 2
    for ns in new_segs:
        if ns[4] != layer:
            continue
        nr = (min(ns[0], ns[2]) - hw,
              min(ns[1], ns[3]) - hw,
              max(ns[0], ns[2]) + hw,
              max(ns[1], ns[3]) + hw)
        nr_exp = (nr[0] - min_s, nr[1] - min_s,
                  nr[2] + min_s, nr[3] + min_s)
        for rs in remaining_segs:
            if rs[4] != layer:
                continue
            rr = (min(rs[0], rs[2]) - hw,
                  min(rs[1], rs[3]) - hw,
                  max(rs[0], rs[2]) + hw,
                  max(rs[1], rs[3]) + hw)
            if _rect_overlap(nr_exp, rr) and not _rect_overlap(nr, rr):
                return True
    return False


def eliminate_zjogs(segs, layer, other_net_segs, obstacle_rects):
    """Remove Z-jogs from segments on a single layer.

    A Z-jog is a short perpendicular segment connecting two parallel
    segments (H->V(short)->H or V->H(short)->V). The optimizer replaces
    the 3-segment Z with a 2-segment L-shape.

    Args:
        segs: all segments for this net (all layers)
        layer: 0 (M1) or 1 (M2) to process
        other_net_segs: segments from all OTHER nets (for spacing check)
        obstacle_rects: M2/M1 obstacle rectangles from power/access points

    Returns:
        (new_segments, jogs_eliminated)
    """
    wire_w = M1_SIG_W if layer == 0 else M2_SIG_W
    min_s = M1_MIN_S if layer == 0 else M2_MIN_S

    layer_segs = [list(s) for s in segs if s[4] == layer]
    other_layer = [list(s) for s in segs if s[4] != layer]

    if len(layer_segs) < 3:
        return segs, 0

    # Collect via and other-layer endpoint positions — these are anchor
    # points that must NOT be moved (vias connect layers at exact coords)
    anchor_points = set()
    for s in other_layer:
        anchor_points.add((s[0], s[1]))
        anchor_points.add((s[2], s[3]))

    total_jogs = 0

    for _pass in range(10):
        ep_map = defaultdict(list)
        for i, s in enumerate(layer_segs):
            ep_map[(s[0], s[1])].append(i)
            ep_map[(s[2], s[3])].append(i)

        removed = set()
        additions = []
        jogs_this_pass = 0

        for mid_i, seg in enumerate(layer_segs):
            if mid_i in removed:
                continue
            if _seg_len(seg) == 0 or _seg_len(seg) > JOG_THRESHOLD:
                continue

            p1 = (seg[0], seg[1])
            p2 = (seg[2], seg[3])

            # Skip if a via or other-layer segment connects at junction
            if p1 in anchor_points or p2 in anchor_points:
                continue

            n1 = [j for j in ep_map[p1] if j != mid_i and j not in removed]
            n2 = [j for j in ep_map[p2] if j != mid_i and j not in removed]

            if len(n1) != 1 or len(n2) != 1:
                continue

            sa = layer_segs[n1[0]]
            sb = layer_segs[n2[0]]

            new_pair = None

            if _is_v(seg) and _is_h(sa) and _is_h(sb):
                # H -> V(short) -> H: replace with L-shape
                a_far = _far_ep(sa, p1)
                b_far = _far_ep(sb, p2)
                new_pair = (
                    [a_far[0], a_far[1], b_far[0], a_far[1], layer],
                    [b_far[0], a_far[1], b_far[0], b_far[1], layer],
                )
            elif _is_h(seg) and _is_v(sa) and _is_v(sb):
                # V -> H(short) -> V: replace with L-shape
                a_far = _far_ep(sa, p1)
                b_far = _far_ep(sb, p2)
                new_pair = (
                    [a_far[0], a_far[1], a_far[0], b_far[1], layer],
                    [a_far[0], b_far[1], b_far[0], b_far[1], layer],
                )

            if new_pair is None:
                continue

            # DRC safety check against other nets AND infrastructure shapes
            if not _segs_spacing_ok(list(new_pair), other_net_segs,
                                    obstacle_rects, layer, min_s, wire_w):
                continue

            # Same-net gap check: new segments must not create
            # close-but-not-touching gaps with remaining same-net segments
            to_remove = {mid_i, n1[0], n2[0]}
            remaining = [s for i, s in enumerate(layer_segs)
                         if i not in removed and i not in to_remove]
            if _creates_same_net_gap(list(new_pair), remaining,
                                     layer, min_s, wire_w):
                continue

            removed.update(to_remove)
            additions.extend(new_pair)
            jogs_this_pass += 1

        if jogs_this_pass == 0:
            break

        total_jogs += jogs_this_pass
        layer_segs = [s for i, s in enumerate(layer_segs) if i not in removed]
        layer_segs.extend(additions)

    return other_layer + layer_segs, total_jogs


def count_stats(segs):
    """Count segments, corners, and short jogs per layer."""
    stats = {}
    for layer in (0, 1):
        layer_segs = [s for s in segs if s[4] == layer]
        ep_map = defaultdict(list)
        for s in layer_segs:
            ep_map[(s[0], s[1])].append(s)
            ep_map[(s[2], s[3])].append(s)

        corners = 0
        for pt, pt_segs in ep_map.items():
            if len(pt_segs) >= 2:
                has_h = any(_is_h(s) for s in pt_segs)
                has_v = any(_is_v(s) for s in pt_segs)
                if has_h and has_v:
                    corners += 1

        short = sum(1 for s in layer_segs
                    if 0 < _seg_len(s) <= JOG_THRESHOLD)

        stats[layer] = {
            'segments': len(layer_segs),
            'corners': corners,
            'short_jogs': short,
        }
    stats['vias'] = sum(1 for s in segs if s[4] == -1)
    return stats


def _extract_m2_obstacles(routing):
    """Extract M2 obstacle rectangles from power drops and access points.

    These shapes are drawn on M2 but NOT stored as signal route segments.
    The optimizer must check against them to avoid M2.b spacing violations.

    Returns list of (x1, y1, x2, y2, layer=1) obstacle rects.
    """
    obstacles = []
    M2 = 1

    # Power drop M2 vbars (vertical, width = M2_SIG_W)
    hw = M2_SIG_W // 2
    for drop in routing.get('power', {}).get('drops', []):
        if 'm2_vbar' in drop:
            vb = drop['m2_vbar']
            x = vb[0]
            y1, y2 = min(vb[1], vb[3]), max(vb[1], vb[3])
            obstacles.append((x - hw, y1, x + hw, y2, M2))

        # M2 jogs use VIA1_PAD width (480nm)
        if 'm2_jog' in drop:
            from ..pdk import VIA1_PAD
            jog = drop['m2_jog']
            jhw = VIA1_PAD // 2
            x1, x2 = min(jog[0], jog[2]), max(jog[0], jog[2])
            y = jog[1]
            obstacles.append((x1, y - jhw, x2, y + jhw, M2))

    # Access point M2 pads (from via_pad.m2)
    for _pin, ap in routing.get('access_points', {}).items():
        vp = ap.get('via_pad', {})
        if 'm2' in vp:
            m2 = vp['m2']
            obstacles.append((m2[0], m2[1], m2[2], m2[3], M2))

    return obstacles


def optimize_routing(routing):
    """Optimize all signal route segments in routing dict (in-place)."""
    signal_routes = routing.get('signal_routes', {})
    pre_routes = routing.get('pre_routes', {})

    all_segs = {}
    for net, route in {**signal_routes, **pre_routes}.items():
        all_segs[net] = route.get('segments', [])

    # Extract M2 infrastructure obstacles (power drops, access pads)
    obstacle_rects = _extract_m2_obstacles(routing)
    print(f'  Loaded {len(obstacle_rects)} M2 obstacle rects '
          f'(power drops + access pads)')

    total_jogs = 0
    segs_before = 0
    segs_after = 0

    for net_name in list(signal_routes.keys()):
        route = signal_routes[net_name]
        segs = route.get('segments', [])
        if not segs:
            continue

        segs_before += len(segs)

        # Other nets' segments for collision checking
        other_segs = []
        for other_net, other_s in all_segs.items():
            if other_net != net_name:
                other_segs.extend(other_s)

        for layer in (0, 1):
            segs, jogs = eliminate_zjogs(segs, layer, other_segs,
                                        obstacle_rects)
            if jogs:
                print(f'    {net_name}: eliminated {jogs} Z-jog(s) on '
                      f'{"M1" if layer == 0 else "M2"}')
            total_jogs += jogs

        route['segments'] = segs
        all_segs[net_name] = segs
        segs_after += len(segs)

    return total_jogs, segs_before, segs_after


def main():
    with open(ROUTING_JSON) as f:
        routing = json.load(f)

    print('=== Route Optimizer ===')
    print(f'  Input: {ROUTING_JSON}')

    # Before stats
    all_segs_before = []
    for route in routing.get('signal_routes', {}).values():
        all_segs_before.extend(route.get('segments', []))
    before = count_stats(all_segs_before)
    print(f'  Before: {len(all_segs_before)} segments, '
          f'M1({before[0]["segments"]} seg, {before[0]["corners"]} corners, '
          f'{before[0]["short_jogs"]} jogs), '
          f'M2({before[1]["segments"]} seg, {before[1]["corners"]} corners, '
          f'{before[1]["short_jogs"]} jogs), '
          f'{before["vias"]} vias')

    jogs, sb, sa = optimize_routing(routing)

    # After stats
    all_segs_after = []
    for route in routing.get('signal_routes', {}).values():
        all_segs_after.extend(route.get('segments', []))
    after = count_stats(all_segs_after)
    print(f'  After:  {len(all_segs_after)} segments, '
          f'M1({after[0]["segments"]} seg, {after[0]["corners"]} corners, '
          f'{after[0]["short_jogs"]} jogs), '
          f'M2({after[1]["segments"]} seg, {after[1]["corners"]} corners, '
          f'{after[1]["short_jogs"]} jogs), '
          f'{after["vias"]} vias')
    print(f'  Eliminated {jogs} Z-jogs ({sb} -> {sa} segments)')

    # Update statistics in routing.json
    if 'statistics' in routing:
        routing['statistics']['optimizer'] = {
            'zjogs_eliminated': jogs,
            'segments_before': sb,
            'segments_after': sa,
        }

    with open(ROUTING_JSON, 'w') as f:
        json.dump(routing, f, indent=2)
        f.write('\n')
    print(f'  Written: {ROUTING_JSON}')


if __name__ == '__main__':
    main()
