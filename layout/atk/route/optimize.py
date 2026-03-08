"""Post-routing optimizer: loop pruning + chain straightening (rubber-banding).

Reads routing.json, simplifies signal route segments by:
1. Removing redundant edges that form loops (keeping spanning tree)
2. Straightening zigzag chains between anchor points into L-shapes

Anchor points = via endpoints + branch points + chain endpoints.
Between any two anchors, the shortest rectilinear path is an L-shape (1-2
segments). The optimizer replaces multi-segment zigzag chains with L-shapes,
DRC-checking each replacement against a complete obstacle model (other-net
routes + access point M1/M2 pads + tie M1 + power M2).

Usage: cd layout && python -m atk.route.optimize
"""

import json
from collections import defaultdict

from ..pdk import (
    MAZE_GRID,
    M1_SIG_W, M2_SIG_W,
    M1_MIN_S, M2_MIN_S,
    DEV_MARGIN,
)
from ..paths import ROUTING_JSON, TIES_JSON, NETLIST_JSON, PLACEMENT_JSON

# For statistics reporting only (not used by optimizer logic).
JOG_THRESHOLD = MAZE_GRID + 50  # 400nm


def _is_h(seg):
    return seg[1] == seg[3] and seg[0] != seg[2]


def _is_v(seg):
    return seg[0] == seg[2] and seg[1] != seg[3]


def _seg_len(seg):
    return abs(seg[2] - seg[0]) + abs(seg[3] - seg[1])


def _rect_overlap(a, b):
    """Check if two (x1,y1,x2,y2) rects overlap."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _segs_spacing_ok(new_segs, other_segs, obstacle_rects, layer, min_s, wire_w):
    """Check new segments don't violate spacing with other nets or obstacles."""
    hw = wire_w // 2
    for ns in new_segs:
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
        for orect in obstacle_rects:
            if orect[4] != layer:
                continue
            if _rect_overlap(nr, orect[:4]):
                return False
    return True


def _creates_same_net_gap(new_segs, remaining_segs, layer, min_s, wire_w):
    """Check if new segments create close-but-not-touching gaps with same-net.

    Same-net shapes that are close but don't touch/overlap violate M1.b/M2.b.
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
            if len(rs) < 5 or rs[4] != layer:
                continue
            rr = (min(rs[0], rs[2]) - hw,
                  min(rs[1], rs[3]) - hw,
                  max(rs[0], rs[2]) + hw,
                  max(rs[1], rs[3]) + hw)
            if _rect_overlap(nr_exp, rr) and not _rect_overlap(nr, rr):
                return True
    return False


# ─── Obstacle extraction ────────────────────────────────────────────────

def _extract_obstacles(routing):
    """Extract ALL obstacle rects (M1 + M2), tagged by net.

    Returns:
        per_net: dict net_name → [(x1,y1,x2,y2,layer), ...]
        global_obs: [(x1,y1,x2,y2,layer), ...]  (ties, power — always foreign)
    """
    per_net = defaultdict(list)
    global_obs = []
    M1, M2 = 0, 1

    # Build pin → net mapping from netlist.json
    pin_net = {}
    try:
        with open(NETLIST_JSON) as f:
            netlist = json.load(f)
        for net in netlist.get('nets', []):
            for pin_str in net.get('pins', []):
                pin_net[pin_str] = net['name']
    except FileNotFoundError:
        pass

    # Access point M1 pads, M2 pads, M1 stubs (per-net)
    for pin_key, ap in routing.get('access_points', {}).items():
        net = pin_net.get(pin_key, '')
        vp = ap.get('via_pad', {})
        if 'm1' in vp:
            m1 = vp['m1']
            per_net[net].append((m1[0], m1[1], m1[2], m1[3], M1))
        if 'm2' in vp:
            m2 = vp['m2']
            per_net[net].append((m2[0], m2[1], m2[2], m2[3], M2))
        stub = ap.get('m1_stub')
        if stub:
            per_net[net].append((stub[0], stub[1], stub[2], stub[3], M1))

    # Power drop M2 vbars + jogs + via_stack M2 pads (global)
    from ..pdk import VIA1_PAD
    hw = M2_SIG_W // 2
    vhp = VIA1_PAD // 2
    for drop in routing.get('power', {}).get('drops', []):
        if 'm2_vbar' in drop:
            vb = drop['m2_vbar']
            x = vb[0]
            y1, y2 = min(vb[1], vb[3]), max(vb[1], vb[3])
            global_obs.append((x - hw, y1, x + hw, y2, M2))
        if 'm2_jog' in drop:
            jog = drop['m2_jog']
            jhw = VIA1_PAD // 2
            x1, x2 = min(jog[0], jog[2]), max(jog[0], jog[2])
            y = jog[1]
            global_obs.append((x1, y - jhw, x2, y + jhw, M2))
        if drop.get('type') == 'via_stack' and 'via2_pos' in drop:
            v2 = drop['via2_pos']
            global_obs.append((v2[0] - vhp, v2[1] - vhp,
                               v2[0] + vhp, v2[1] + vhp, M2))

    # Tie M1 shapes from ties.json (global — belong to vdd/gnd)
    try:
        with open(TIES_JSON) as f:
            ties_data = json.load(f)
        for t in ties_data.get('ties', []):
            for layer_key, shapes in t.get('layers', {}).items():
                if layer_key.startswith('M1'):
                    for r in shapes:
                        global_obs.append((r[0], r[1], r[2], r[3], M1))
    except FileNotFoundError:
        pass

    # Device bboxes on M1 (route wires must not enter device + DEV_MARGIN)
    dev_m1_bboxes = []
    try:
        with open(PLACEMENT_JSON) as f:
            placement = json.load(f)
        margin = DEV_MARGIN
        for inst_name, inst in placement.get('instances', {}).items():
            left = int(inst['x_um'] * 1000)
            bot = int(inst['y_um'] * 1000)
            right = left + int(inst['w_um'] * 1000)
            top = bot + int(inst['h_um'] * 1000)
            dev_m1_bboxes.append((left - margin, bot - margin,
                                  right + margin, top + margin))
    except FileNotFoundError:
        pass

    return per_net, global_obs, dev_m1_bboxes


# ─── Loop pruning ────────────────────────────────────────────────────────

def prune_loops(segs):
    """Remove redundant edges that form loops, keeping a spanning tree.

    Uses Kruskal's MST: processes edges shortest-first so the longest
    cycle-forming edges are removed.
    """
    wire_segs = [s for s in segs if s[4] >= 0]
    via_segs = [s for s in segs if s[4] == -1]

    if len(wire_segs) < 2:
        return segs, 0

    edges = []
    for i, s in enumerate(wire_segs):
        p1 = (s[0], s[1])
        p2 = (s[2], s[3])
        if p1 == p2:
            continue
        edges.append((p1, p2, i, _seg_len(s)))

    edges.sort(key=lambda e: e[3])

    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    remove_idx = set()
    for p1, p2, idx, length in edges:
        if not union(p1, p2):
            remove_idx.add(idx)

    if not remove_idx:
        return segs, 0

    kept_wires = [s for i, s in enumerate(wire_segs) if i not in remove_idx]
    live_points = set()
    for s in kept_wires:
        live_points.add((s[0], s[1]))
        live_points.add((s[2], s[3]))
    kept_vias = [v for v in via_segs if (v[0], v[1]) in live_points]

    return kept_vias + kept_wires, len(remove_idx)


def prune_redundant_vias(segs):
    """Remove vias that aren't needed for inter-layer connectivity.

    Uses layer-aware Union-Find: nodes are (x, y, layer).
    All wire edges are added first (mandatory), then vias are added
    only if they connect previously disconnected components.
    """
    wire_segs = [s for s in segs if s[4] >= 0]
    via_segs = [s for s in segs if s[4] == -1]

    if not via_segs:
        return segs, 0, 0

    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    # Pre-load all wire edges (mandatory)
    for s in wire_segs:
        p1 = (s[0], s[1], s[4])
        p2 = (s[2], s[3], s[4])
        if p1 != p2:
            union(p1, p2)

    # Add vias, keeping only those that connect new components
    kept_vias = []
    removed = 0
    for v in via_segs:
        n0 = (v[0], v[1], 0)  # M1 node
        n1 = (v[0], v[1], 1)  # M2 node
        if union(n0, n1):
            kept_vias.append(v)  # bridge via — needed
        else:
            removed += 1  # redundant — both layers already connected

    if not removed:
        return segs, 0, 0

    # Remove orphaned wire stubs (degree-0 after via removal)
    live_via_pts = set((v[0], v[1]) for v in kept_vias)
    all_via_pts = set((v[0], v[1]) for v in via_segs)
    removed_via_pts = all_via_pts - live_via_pts

    # Check each wire: if an endpoint is at a removed via position
    # and has no other connection, it's an orphaned stub
    from collections import defaultdict
    ep_count = defaultdict(int)
    for s in wire_segs:
        ep_count[(s[0], s[1], s[4])] += 1
        ep_count[(s[2], s[3], s[4])] += 1

    orphaned = set()
    changed = True
    while changed:
        changed = False
        kept_wires = []
        for s in wire_segs:
            p1 = (s[0], s[1])
            p2 = (s[2], s[3])
            n1 = (s[0], s[1], s[4])
            n2 = (s[2], s[3], s[4])
            # A wire is orphaned if one endpoint is at a removed via,
            # has degree 1, and is not at a kept via
            is_orphan = False
            if ep_count[n1] == 1 and p1 in removed_via_pts and p1 not in live_via_pts:
                is_orphan = True
            if ep_count[n2] == 1 and p2 in removed_via_pts and p2 not in live_via_pts:
                is_orphan = True
            if is_orphan:
                orphaned.add(id(s))
                ep_count[n1] -= 1
                ep_count[n2] -= 1
                changed = True
            else:
                kept_wires.append(s)
        wire_segs = kept_wires

    stub_count = len(orphaned)
    return kept_vias + wire_segs, removed, stub_count


# ─── Chain straightening (rubber-banding) ────────────────────────────────

def _enters_device_m1(new_segs, dev_bboxes):
    """Check if any M1 wire center enters a device bbox (+ DEV_MARGIN).

    Device bboxes are pre-expanded by DEV_MARGIN. This replicates the
    router's M1 blocking: no wire center may enter device areas.
    """
    for ns in new_segs:
        if ns[4] != 0:  # only check M1
            continue
        sx1 = min(ns[0], ns[2])
        sy1 = min(ns[1], ns[3])
        sx2 = max(ns[0], ns[2])
        sy2 = max(ns[1], ns[3])
        for db in dev_bboxes:
            if sx1 < db[2] and sx2 > db[0] and sy1 < db[3] and sy2 > db[1]:
                return True
    return False


def straighten_chains(segs, layer, other_net_segs, obstacle_rects,
                      same_net_shapes, dev_m1_bboxes=()):
    """Straighten zigzag chains between anchor points into L-shapes.

    Anchor points = via endpoints + branch points (degree!=2) + leaf endpoints.
    For each chain of >= 2 segments between anchors A and B, try replacing
    the entire chain with a 1-2 segment L-shape (or straight line if collinear).
    Two L-shape orientations are tried; the first that passes DRC is used.

    Args:
        segs: all segments for this net (all layers)
        layer: 0 (M1) or 1 (M2) to process
        other_net_segs: segments from all OTHER nets (for spacing check)
        obstacle_rects: obstacle rects from other nets + global (for spacing)
        same_net_shapes: obstacle rects from SAME net (for gap check only)

    Returns:
        (new_segments, chains_straightened)
    """
    wire_w = M1_SIG_W if layer == 0 else M2_SIG_W
    min_s = M1_MIN_S if layer == 0 else M2_MIN_S

    layer_segs = [list(s) for s in segs if s[4] == layer]
    other_layer = [list(s) for s in segs if s[4] != layer]

    if len(layer_segs) < 2:
        return segs, 0

    # Anchor points: via/cross-layer endpoints
    anchor_points = set()
    for s in other_layer:
        anchor_points.add((s[0], s[1]))
        anchor_points.add((s[2], s[3]))

    # Build endpoint map
    ep_map = defaultdict(set)
    for i, s in enumerate(layer_segs):
        ep_map[(s[0], s[1])].add(i)
        ep_map[(s[2], s[3])].add(i)

    # Degree != 2 points are also anchors (branch or leaf)
    for pt, indices in ep_map.items():
        if len(indices) != 2:
            anchor_points.add(pt)

    # Access-point connection anchors: if a segment physically overlaps
    # a same-net M1/M2 shape (AP via_pad or m1_stub), its endpoints must
    # be anchors — removing that segment would disconnect the device.
    hw = wire_w // 2
    for i, s in enumerate(layer_segs):
        sx1 = min(s[0], s[2]) - hw
        sy1 = min(s[1], s[3]) - hw
        sx2 = max(s[0], s[2]) + hw
        sy2 = max(s[1], s[3]) + hw
        for shape in same_net_shapes:
            if shape[4] != layer:
                continue
            if sx1 < shape[2] and sx2 > shape[0] and sy1 < shape[3] and sy2 > shape[1]:
                anchor_points.add((s[0], s[1]))
                anchor_points.add((s[2], s[3]))
                break

    # Walk chains between consecutive anchors
    visited_segs = set()
    chains = []  # [(anchor_a, anchor_b, [seg_indices])]

    for start_pt in list(anchor_points):
        if start_pt not in ep_map:
            continue
        for seg_i in list(ep_map[start_pt]):
            if seg_i in visited_segs:
                continue
            chain = [seg_i]
            visited_segs.add(seg_i)
            s = layer_segs[seg_i]
            p1, p2 = (s[0], s[1]), (s[2], s[3])
            current = p2 if p1 == start_pt else p1

            while current not in anchor_points:
                neighbors = ep_map[current] - visited_segs
                if len(neighbors) != 1:
                    anchor_points.add(current)
                    break
                next_i = next(iter(neighbors))
                chain.append(next_i)
                visited_segs.add(next_i)
                ns = layer_segs[next_i]
                np1, np2 = (ns[0], ns[1]), (ns[2], ns[3])
                current = np2 if np1 == current else np1

            chains.append((start_pt, current, chain))

    # Filter same-net shapes for this layer (for gap check)
    same_layer_shapes = [r for r in same_net_shapes if r[4] == layer]

    # Try straightening each chain with >= 2 segments
    straightened = 0
    replaced = set()
    new_segs = []

    for anchor_a, anchor_b, chain_indices in chains:
        if len(chain_indices) < 2:
            continue
        if anchor_a == anchor_b:
            continue

        ax, ay = anchor_a
        bx, by = anchor_b

        # Generate L-shape candidates
        candidates = []
        if ax == bx:
            candidates.append([[ax, ay, bx, by, layer]])
        elif ay == by:
            candidates.append([[ax, ay, bx, by, layer]])
        else:
            # Try both L orientations
            candidates.append([
                [ax, ay, bx, ay, layer],
                [bx, ay, bx, by, layer],
            ])
            candidates.append([
                [ax, ay, ax, by, layer],
                [ax, by, bx, by, layer],
            ])

        chain_set = set(chain_indices)

        # Verify chain connectivity: walk from anchor_a through chain to anchor_b
        chain_pts = [anchor_a]
        cur = anchor_a
        valid_chain = True
        for ci in chain_indices:
            cs = layer_segs[ci]
            cp1, cp2 = (cs[0], cs[1]), (cs[2], cs[3])
            if cp1 == cur:
                cur = cp2
            elif cp2 == cur:
                cur = cp1
            else:
                valid_chain = False
                break
            chain_pts.append(cur)
        if not valid_chain or cur != anchor_b:
            continue  # chain walking error, skip

        for cand in candidates:
            # Check M1 wire doesn't enter device areas
            if dev_m1_bboxes and _enters_device_m1(cand, dev_m1_bboxes):
                continue

            # Check spacing against other nets + foreign obstacles
            if not _segs_spacing_ok(cand, other_net_segs, obstacle_rects,
                                    layer, min_s, wire_w):
                continue

            # Check same-net gaps (close-but-not-touching)
            remaining = [layer_segs[i] for i in range(len(layer_segs))
                         if i not in replaced and i not in chain_set]
            remaining.extend(new_segs)
            remaining.extend(same_layer_shapes)
            if _creates_same_net_gap(cand, remaining, layer, min_s, wire_w):
                continue

            replaced.update(chain_indices)
            new_segs.extend(cand)
            straightened += 1
            break

    kept = [layer_segs[i] for i in range(len(layer_segs)) if i not in replaced]
    return other_layer + kept + new_segs, straightened


# ─── Statistics ──────────────────────────────────────────────────────────

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


# ─── Main entry points ──────────────────────────────────────────────────

def optimize_routing(routing):
    """Optimize all signal route segments in routing dict (in-place)."""
    signal_routes = routing.get('signal_routes', {})
    pre_routes = routing.get('pre_routes', {})

    all_segs = {}
    for net, route in {**signal_routes, **pre_routes}.items():
        all_segs[net] = route.get('segments', [])

    # Extract all obstacles (M1 + M2), tagged by net
    obs_per_net, obs_global, dev_m1_bboxes = _extract_obstacles(routing)
    m1_g = sum(1 for o in obs_global if o[4] == 0)
    m2_g = sum(1 for o in obs_global if o[4] == 1)
    ap_total = sum(len(v) for v in obs_per_net.values())
    print(f'  Obstacles: {m1_g} M1 + {m2_g} M2 global, '
          f'{ap_total} per-net, {len(dev_m1_bboxes)} device bboxes')

    total_loops = 0
    total_straightened = 0
    segs_before = 0
    segs_after = 0

    for net_name in list(signal_routes.keys()):
        route = signal_routes[net_name]
        segs = route.get('segments', [])
        if not segs:
            continue

        segs_before += len(segs)

        # Pass 1: prune loops
        segs, loops = prune_loops(segs)
        if loops:
            print(f'    {net_name}: pruned {loops} loop edge(s)')
        total_loops += loops
        all_segs[net_name] = segs

        # Build obstacle rects for this net (exclude own access points)
        net_obstacles = list(obs_global)
        for other_net, obs in obs_per_net.items():
            if other_net != net_name:
                net_obstacles.extend(obs)

        # Same-net access point shapes (for gap check)
        same_net_shapes = obs_per_net.get(net_name, [])

        # Other nets' route segments
        other_segs = []
        for other_net, other_s in all_segs.items():
            if other_net != net_name:
                other_segs.extend(other_s)

        # Pass 2: straighten chains per layer
        for ly in (0, 1):  # M1 + M2
            segs, count = straighten_chains(
                segs, ly, other_segs, net_obstacles, same_net_shapes,
                dev_m1_bboxes)
            if count:
                lname = "M1" if ly == 0 else "M2"
                print(f'    {net_name}: straightened {count} chain(s) on {lname}')
            total_straightened += count

        # Pass 3: re-prune loops introduced by straightening
        # (L-shape corner may land on a via position, creating a redundant edge)
        segs, loops2 = prune_loops(segs)
        if loops2:
            print(f'    {net_name}: re-pruned {loops2} loop edge(s) after straighten')
        total_loops += loops2

        # Pass 4: remove redundant vias (non-bridge inter-layer edges)
        result = prune_redundant_vias(segs)
        segs, vias_rm, stubs_rm = result
        if vias_rm:
            print(f'    {net_name}: removed {vias_rm} redundant via(s)'
                  f'{f", {stubs_rm} orphaned stub(s)" if stubs_rm else ""}')

        route['segments'] = segs
        all_segs[net_name] = segs
        segs_after += len(segs)

    return total_loops, total_straightened, segs_before, segs_after


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

    loops, straightened, sb, sa = optimize_routing(routing)

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
    print(f'  Pruned {loops} loops, straightened {straightened} chains '
          f'({sb} -> {sa} segments)')

    if 'statistics' in routing:
        routing['statistics']['optimizer'] = {
            'loops_pruned': loops,
            'chains_straightened': straightened,
            'segments_before': sb,
            'segments_after': sa,
        }

    with open(ROUTING_JSON, 'w') as f:
        json.dump(routing, f, indent=2)
        f.write('\n')
    print(f'  Written: {ROUTING_JSON}')


if __name__ == '__main__':
    main()
