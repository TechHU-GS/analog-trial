"""Routing DRC pre-check from JSON geometry — no GDS needed.

Collects all M1/M2 shapes from:
  - routing.json signal segments + pre-routes
  - routing.json access point via pads + M1 stubs
  - placement.json device M1 (via device_lib or access.py _DEVICES)
  - ties.json M1 shapes

Checks:
  - M1.b spacing (180nm)
  - M2.b spacing (210nm)
  - V1.b spacing (220nm)  — from via positions in segments
  - M2 cross-net overlap (shorts)

Uses shapely STRtree for fast pairwise distance queries.
"""

import json
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from ..pdk import (
    UM, M1_MIN_S, M2_MIN_S, V1_MIN_S,
    M1_SIG_W, M2_SIG_W, VIA1_SZ,
)
from ..route.maze_router import M1_LYR, M2_LYR


def _seg_to_box(seg, wire_w):
    """Convert (x1, y1, x2, y2, layer) segment to shapely box in µm."""
    x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
    hw = wire_w / 2
    # Normalize
    lx, rx = (min(x1, x2) - hw) / UM, (max(x1, x2) + hw) / UM
    ly, ry = (min(y1, y2) - hw) / UM, (max(y1, y2) + hw) / UM
    return box(lx, ly, rx, ry)


def _rect_to_box(rect):
    """Convert [x1, y1, x2, y2] nm rect to shapely box in µm."""
    return box(rect[0] / UM, rect[1] / UM, rect[2] / UM, rect[3] / UM)


def _build_pin_net_map(routing):
    """Build inst.pin → net_name map from routing data.

    Access point shapes must carry their actual net name so that
    same-net spacing checks are correctly skipped.
    """
    pin_net = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        for pin_key in route.get('pins', []):
            pin_net[pin_key] = net_name
    for net_name, route in routing.get('pre_routes', {}).items():
        for pin_key in route.get('pins', []):
            pin_net[pin_key] = net_name
    for drop in routing.get('power', {}).get('drops', []):
        key = f"{drop['inst']}.{drop['pin']}"
        pin_net[key] = drop['net']
    return pin_net


def collect_shapes(routing, placement=None, ties=None):
    """Collect all routed shapes by layer.

    Returns:
        m1_shapes: list of (shapely_poly, net_name)
        m2_shapes: list of (shapely_poly, net_name)
        via_shapes: list of (shapely_poly, net_name)  — Via1 squares
    """
    m1_shapes = []
    m2_shapes = []
    via_shapes = []

    pin_net = _build_pin_net_map(routing)

    # ─── Signal route segments ───
    for net_name, route in routing.get('signal_routes', {}).items():
        for seg in route.get('segments', []):
            layer = seg[4]
            if layer == M1_LYR:
                m1_shapes.append((_seg_to_box(seg, M1_SIG_W), net_name))
            elif layer == M2_LYR:
                m2_shapes.append((_seg_to_box(seg, M2_SIG_W), net_name))
            elif layer == -1:  # VIA
                # Via at (x, y) — square VIA1_SZ
                hs = VIA1_SZ / 2
                vb = box((seg[0] - hs) / UM, (seg[1] - hs) / UM,
                         (seg[0] + hs) / UM, (seg[1] + hs) / UM)
                via_shapes.append((vb, net_name))

    # ─── Pre-route segments ───
    for net_name, route in routing.get('pre_routes', {}).items():
        for seg in route.get('segments', []):
            layer = seg[4]
            if layer == M1_LYR:
                m1_shapes.append((_seg_to_box(seg, M1_SIG_W), net_name))
            elif layer == M2_LYR:
                m2_shapes.append((_seg_to_box(seg, M2_SIG_W), net_name))

    # ─── Access point via pads + M1 stubs ───
    # Skip via_stack power drop pins — they bypass access points entirely
    via_stack_pins = set()
    for drop in routing.get('power', {}).get('drops', []):
        if drop['type'] == 'via_stack':
            via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

    for key, ap in routing.get('access_points', {}).items():
        if key in via_stack_pins:
            continue
        # Use actual net name if known; fall back to _ap_ tag
        tag = pin_net.get(key, f'_ap_{key}')
        if ap.get('via_pad'):
            vp = ap['via_pad']
            if 'm1' in vp:
                m1_shapes.append((_rect_to_box(vp['m1']), tag))
            if 'm2' in vp:
                m2_shapes.append((_rect_to_box(vp['m2']), tag))
            if 'via1' in vp:
                via_shapes.append((_rect_to_box(vp['via1']), tag))
        if ap.get('m1_stub'):
            m1_shapes.append((_rect_to_box(ap['m1_stub']), tag))

    # ─── Tie M1 shapes ───
    if ties:
        for tie in ties.get('ties', []):
            tag = tie.get('net', f'_tie_{tie["id"]}')
            for rect in tie.get('layers', {}).get('M1_8_0', []):
                m1_shapes.append((_rect_to_box(rect), tag))

    return m1_shapes, m2_shapes, via_shapes


def check_layer_spacing(shapes, min_spacing_um, rule_name):
    """Check spacing on a single layer.

    shapes: list of (shapely_poly, net_name)
    min_spacing_um: minimum spacing in µm

    Returns list of violations: [(i, j, dist_um, loc_x, loc_y, net_i, net_j)]
    """
    if len(shapes) < 2:
        return []

    polys = [s[0] for s in shapes]
    nets = [s[1] for s in shapes]

    # Merge same-net shapes
    net_groups = {}
    for i, (poly, net) in enumerate(shapes):
        net_groups.setdefault(net, []).append(poly)

    merged_shapes = []
    merged_nets = []
    for net, group in net_groups.items():
        merged = unary_union(group)
        if merged.geom_type == 'Polygon':
            merged_shapes.append(merged)
            merged_nets.append(net)
        elif merged.geom_type == 'MultiPolygon':
            for g in merged.geoms:
                merged_shapes.append(g)
                merged_nets.append(net)

    if len(merged_shapes) < 2:
        return []

    tree = STRtree(merged_shapes)
    search_dist = min_spacing_um * 1.5

    violations = []
    for i, poly in enumerate(merged_shapes):
        candidates = tree.query(poly.buffer(search_dist))
        for j_idx in candidates:
            if j_idx <= i:
                continue

            ni, nj = merged_nets[i], merged_nets[j_idx]

            # Same-net: skip (same net shapes have no spacing rule)
            if ni == nj:
                continue

            # Same-device access pads: skip (PCell-internal spacing
            # is verified by the PDK DRC deck, not inter-net rules)
            if ni.startswith('_ap_') and nj.startswith('_ap_'):
                di = ni.split('.')[0][4:]   # "_ap_MBp2.D" → "MBp2"
                dj = nj.split('.')[0][4:]
                if di == dj:
                    continue

            j_poly = merged_shapes[j_idx]
            if poly.intersects(j_poly):
                continue  # overlapping/touching

            dist = poly.distance(j_poly)
            if 0 < dist < min_spacing_um - 1e-6:
                p1 = poly.representative_point()
                p2 = j_poly.representative_point()
                violations.append((
                    i, j_idx, dist,
                    (p1.x + p2.x) / 2, (p1.y + p2.y) / 2,
                    ni, nj,
                ))

    return violations


def check_shorts(m2_shapes):
    """Check for M2 cross-net overlaps (shorts).

    Returns list of (net_a, net_b, overlap_area_um2, loc_x, loc_y).
    """
    # Group by net
    net_groups = {}
    for poly, net in m2_shapes:
        if net.startswith('_ap_') or net.startswith('_tie_'):
            continue  # access points are not routed M2
        net_groups.setdefault(net, []).append(poly)

    net_names = list(net_groups.keys())
    shorts = []

    for i in range(len(net_names)):
        for j in range(i + 1, len(net_names)):
            na, nb = net_names[i], net_names[j]
            ua = unary_union(net_groups[na])
            ub = unary_union(net_groups[nb])
            if ua.intersects(ub):
                overlap = ua.intersection(ub)
                if overlap.area > 1e-9:
                    p = overlap.representative_point()
                    shorts.append((na, nb, overlap.area, p.x, p.y))

    return shorts


def check_routing(routing_json_path, ties_json_path=None):
    """Full routing DRC check from JSON files.

    Returns dict of results.
    """
    with open(routing_json_path) as f:
        routing = json.load(f)

    ties = None
    if ties_json_path:
        with open(ties_json_path) as f:
            ties = json.load(f)

    m1_shapes, m2_shapes, via_shapes = collect_shapes(routing, ties=ties)

    results = {}

    # M1.b
    m1_viols = check_layer_spacing(m1_shapes, M1_MIN_S / UM, 'M1.b')
    results['M1.b'] = m1_viols

    # M2.b
    m2_viols = check_layer_spacing(m2_shapes, M2_MIN_S / UM, 'M2.b')
    results['M2.b'] = m2_viols

    # V1.b
    v1_viols = check_layer_spacing(via_shapes, V1_MIN_S / UM, 'V1.b')
    results['V1.b'] = v1_viols

    # M2 shorts
    shorts = check_shorts(m2_shapes)
    results['M2_shorts'] = shorts

    return results


def print_report(results):
    """Print routing DRC report."""
    print(f"\n{'='*50}")
    print("Routing DRC Pre-Check (JSON + shapely)")
    print(f"{'='*50}")

    total = 0
    for rule in ['M1.b', 'M2.b', 'V1.b']:
        viols = results.get(rule, [])
        n = len(viols)
        total += n
        status = "PASS" if n == 0 else f"FAIL ({n})"
        print(f"  {rule}: {status}")
        for item in viols[:5]:
            i, j, dist, x, y = item[:5]
            nets = ''
            if len(item) > 5:
                nets = f' [{item[5]} ↔ {item[6]}]'
            print(f"    [{i}↔{j}] dist={dist:.3f}µm at ({x:.1f},{y:.1f}){nets}")
        if n > 5:
            print(f"    ... and {n-5} more")

    shorts = results.get('M2_shorts', [])
    total += len(shorts)
    status = "PASS" if len(shorts) == 0 else f"FAIL ({len(shorts)})"
    print(f"  M2 shorts: {status}")
    for na, nb, area, x, y in shorts[:5]:
        print(f"    {na} ↔ {nb}: area={area:.4f}µm² at ({x:.1f},{y:.1f})")

    print(f"\nTotal violations: {total}")
    return total == 0


def check_all_shorts(routing, netlist, ties=None):
    """Exhaustive inter-net short check on M1 and M2.

    Builds per-net per-layer shapes from route segments, access pads/stubs,
    power pads, and tie M1 shapes. Checks all net pairs on same layer
    for intersection.

    Returns list of (net_a, net_b, layer_name, overlap_area_nm2).
    """
    m1_shapes, m2_shapes, _ = collect_shapes(routing, ties=ties)

    # Also add power net access pads/stubs (they physically exist)
    power_nets = {}
    for net in netlist.get('nets', []):
        if net['type'] == 'power':
            power_nets[net['name']] = net['pins']

    for pwr_name, pins in power_nets.items():
        for pin_key in pins:
            ap = routing.get('access_points', {}).get(pin_key)
            if not ap:
                continue
            vp = ap.get('via_pad', {})
            if 'm1' in vp:
                m1_shapes.append((_rect_to_box(vp['m1']), pwr_name))
            if 'm2' in vp:
                m2_shapes.append((_rect_to_box(vp['m2']), pwr_name))
            stub = ap.get('m1_stub')
            if stub:
                m1_shapes.append((_rect_to_box(stub), pwr_name))

    shorts = []
    for layer_shapes, layer_name in [(m1_shapes, 'M1'), (m2_shapes, 'M2')]:
        net_groups = {}
        for poly, net in layer_shapes:
            net_groups.setdefault(net, []).append(poly)

        net_names = list(net_groups.keys())
        for i in range(len(net_names)):
            for j in range(i + 1, len(net_names)):
                na, nb = net_names[i], net_names[j]
                ua = unary_union(net_groups[na])
                ub = unary_union(net_groups[nb])
                if ua.intersects(ub):
                    area = ua.intersection(ub).area
                    if area > 0:
                        # Convert µm² to nm² (×1e6)
                        shorts.append((na, nb, layer_name, area * 1e6))

    return shorts


def check_components(routing):
    """Check which signal nets have disconnected routing components.

    Uses shared-endpoint adjacency + BFS to find connected components
    per net. Disconnected components = routing gap.

    Returns dict of {net_name: n_components} for nets with >1 component.
    """
    from collections import defaultdict

    disconnected = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        segs = route.get('segments', [])
        if not segs:
            continue

        pt_seg = defaultdict(set)
        for i, s in enumerate(segs):
            lyr = s[4]
            if lyr == -1:
                for l in (0, 1):
                    pt_seg[(s[0], s[1], l)].add(i)
            else:
                pt_seg[(s[0], s[1], lyr)].add(i)
                pt_seg[(s[2], s[3], lyr)].add(i)

        n = len(segs)
        adj = [set() for _ in range(n)]
        for indices in pt_seg.values():
            idx_list = list(indices)
            for a in idx_list:
                for b in idx_list:
                    if a != b:
                        adj[a].add(b)

        visited = [False] * n
        components = 0
        for start in range(n):
            if visited[start]:
                continue
            components += 1
            stack = [start]
            while stack:
                node = stack.pop()
                if visited[node]:
                    continue
                visited[node] = True
                for nb in adj[node]:
                    if not visited[nb]:
                        stack.append(nb)

        if components > 1:
            disconnected[net_name] = components

    return disconnected


def check_diagonals(routing):
    """Find diagonal (non-manhattan) segments in routing.

    Returns list of (net_name, segment, route_type) for diagonal segments.
    """
    diags = []
    for net_name, route in routing.get('signal_routes', {}).items():
        for seg in route.get('segments', []):
            x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
            if x1 != x2 and y1 != y2 and seg[4] != -1:
                diags.append((net_name, seg, 'signal'))

    for net_name, route in routing.get('pre_routes', {}).items():
        for seg in route.get('segments', []):
            x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
            if x1 != x2 and y1 != y2 and seg[4] != -1:
                diags.append((net_name, seg, 'pre_route'))

    return diags


def full_check(routing_json_path, ties_json_path=None, netlist_json_path=None):
    """Comprehensive routing check: DRC + shorts + components + diagonals.

    Returns (all_ok, results_dict).
    """
    with open(routing_json_path) as f:
        routing = json.load(f)

    ties = None
    if ties_json_path:
        with open(ties_json_path) as f:
            ties = json.load(f)

    netlist = None
    if netlist_json_path:
        with open(netlist_json_path) as f:
            netlist = json.load(f)

    # DRC spacing
    results = check_routing(routing_json_path, ties_json_path)

    # Exhaustive shorts (M1 + M2, including power)
    if netlist:
        all_shorts = check_all_shorts(routing, netlist, ties)
        results['all_shorts'] = all_shorts
    else:
        results['all_shorts'] = []

    # Connectivity (disconnected components)
    disconnected = check_components(routing)
    results['disconnected'] = disconnected

    # Diagonal segments
    diags = check_diagonals(routing)
    results['diagonals'] = diags

    # Print extended report
    ok = print_report(results)

    if results['all_shorts']:
        print(f"\n  All-layer shorts: FAIL ({len(results['all_shorts'])})")
        for na, nb, lyr, area in results['all_shorts']:
            print(f"    {na} <-> {nb} on {lyr}: {area:.0f} nm2")
        ok = False
    else:
        print(f"  All-layer shorts: PASS")

    if disconnected:
        print(f"  Connectivity: FAIL ({len(disconnected)} nets)")
        for net, nc in disconnected.items():
            print(f"    {net}: {nc} components")
        ok = False
    else:
        print(f"  Connectivity: PASS")

    if diags:
        print(f"  Diagonals: FAIL ({len(diags)})")
        for net, seg, rt in diags:
            print(f"    {net}: ({seg[0]},{seg[1]})-({seg[2]},{seg[3]}) layer={seg[4]}")
        ok = False
    else:
        print(f"  Diagonals: PASS")

    return ok, results


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m atk.verify.routing_check <routing.json> [ties.json] [netlist.json]")
        sys.exit(1)

    routing_path = sys.argv[1]
    ties_path = sys.argv[2] if len(sys.argv) > 2 else None
    netlist_path = sys.argv[3] if len(sys.argv) > 3 else None

    if netlist_path:
        ok, _ = full_check(routing_path, ties_path, netlist_path)
    else:
        results = check_routing(routing_path, ties_path)
        ok = print_report(results)
    sys.exit(0 if ok else 1)
