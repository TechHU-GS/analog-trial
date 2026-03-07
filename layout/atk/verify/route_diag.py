"""Route failure diagnosis — find WHY a net cannot be routed.

Rebuilds router state up to the target net, then BFS-floods from each
pin to find reachable cells.  Reports:
  - reachable area per pin (grid cells)
  - whether pins are mutually reachable
  - obstacle frontier: which cells block the shortest path and their type
    (permanent / used-by-net / soft-blocked)

Usage:
    python -m atk.verify.route_diag [--net NET_NAME]

Pipeline position: run AFTER a routing failure to diagnose the cause.
"""
import json
import sys
from collections import deque
from pathlib import Path

from ..pdk import MAZE_GRID
from ..route.solver import RoutingSolver, M1_LYR, M2_LYR


def _bfs_flood(router, start_gxy, layers=None):
    """BFS from start, return set of reachable (gx, gy, layer) cells."""
    if layers is None:
        layers = (M1_LYR, M2_LYR)
    visited = set()
    queue = deque()

    for lyr in layers:
        cell = (start_gxy[0], start_gxy[1], lyr)
        if cell not in router.blocked and cell not in router.used:
            queue.append(cell)
            visited.add(cell)

    while queue:
        gx, gy, layer = queue.popleft()
        # Cardinal neighbors
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = gx + dx, gy + dy
            if 0 <= nx < router.nx and 0 <= ny < router.ny:
                nb = (nx, ny, layer)
                if nb not in visited and nb not in router.blocked and nb not in router.used:
                    visited.add(nb)
                    queue.append(nb)
        # Via
        ol = 1 - layer
        nb = (gx, gy, ol)
        if nb not in visited and nb not in router.blocked and nb not in router.used:
            visited.add(nb)
            queue.append(nb)

    return visited


def _obstacle_frontier(router, reachable):
    """Find obstacle cells adjacent to reachable set — the 'wall'."""
    frontier = {}  # cell -> type_str
    for gx, gy, layer in reachable:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = gx + dx, gy + dy
            nb = (nx, ny, layer)
            if nb in reachable:
                continue
            if not (0 <= nx < router.nx and 0 <= ny < router.ny):
                continue
            if nb in router.permanent:
                frontier[nb] = 'permanent'
            elif nb in router.blocked:
                frontier[nb] = 'soft-blocked'
            elif nb in router.used:
                frontier[nb] = 'used'

    return frontier


def _find_used_owner(router, cell, signal_routes, pre_routes):
    """Given a used cell, figure out which net occupies it.

    Brute-force: for each routed net, check if cell's nm position
    falls within any of its segments (with wire half-width + margin).
    """
    from shapely.geometry import Point, box as sbox
    gx, gy, layer = cell
    cx_nm = router.x0 + gx * router.GRID
    cy_nm = router.y0 + gy * router.GRID
    pt = Point(cx_nm, cy_nm)

    HW = 150  # wire half-width
    margin = 1  # MAZE_MARGIN in grid cells → check within margin*GRID nm

    for net_name, route in {**signal_routes, **pre_routes}.items():
        segs = route.get('segments', [])
        for s in segs:
            if s[4] == -1:
                continue
            if s[4] != layer:
                continue
            x1, y1, x2, y2 = s[0], s[1], s[2], s[3]
            b = sbox(min(x1, x2) - HW - margin * MAZE_GRID,
                     min(y1, y2) - HW - margin * MAZE_GRID,
                     max(x1, x2) + HW + margin * MAZE_GRID,
                     max(y1, y2) + HW + margin * MAZE_GRID)
            if b.contains(pt):
                return net_name
    return '?'


def diagnose(target_net, placement_path=None, ties_path=None, netlist_path=None):
    """Diagnose why target_net failed to route.

    Rebuilds the full router state (including routing all nets before
    target_net in order), then analyzes reachability from target_net's pins.
    """
    if placement_path is None:
        from atk.paths import PLACEMENT_JSON
        placement_path = PLACEMENT_JSON
    if ties_path is None:
        from atk.paths import TIES_JSON
        ties_path = TIES_JSON
    if netlist_path is None:
        from atk.paths import NETLIST_JSON
        netlist_path = NETLIST_JSON

    with open(placement_path) as f:
        placement = json.load(f)
    with open(ties_path) as f:
        ties = json.load(f)
    with open(netlist_path) as f:
        netlist = json.load(f)

    print(f'=== Route Diagnosis: {target_net} ===')
    print()

    # Build solver and run everything up to signal routing
    solver = RoutingSolver(placement, ties, netlist)

    # Steps 1-3: access points, power, obstacle map
    print('[1] Rebuilding router state...')
    solver.access_points = __import__('atk.route.access', fromlist=['compute_access_points']).compute_access_points(placement)
    solver.rails = solver.__class__.__dict__  # dummy — we need to call solve() properly

    # Actually just run solve() but intercept before target_net
    # Simpler: run full solve, then read the routing.json that was produced
    # and check the router state. But we need the actual router object.
    # Let's just run solve() — it will print the FAILED message — that's fine.

    solver2 = RoutingSolver(placement, ties, netlist)
    solver2.solve()

    router = solver2.router

    # Find target net pins
    target_pins = []
    for net in netlist['nets']:
        if net['name'] == target_net:
            for pin_str in net['pins']:
                inst, pin = pin_str.split('.')
                ap = solver2.access_points.get((inst, pin))
                if ap:
                    target_pins.append({
                        'key': pin_str,
                        'x': ap['x'], 'y': ap['y'],
                        'mode': ap['mode'],
                    })

    if not target_pins:
        print(f'  ERROR: no pins found for {target_net}')
        return

    print(f'\n[2] Target net pins ({len(target_pins)}):')
    for p in target_pins:
        gx, gy = router.to_grid(p['x'], p['y'])
        bl_m1 = (gx, gy, M1_LYR) in router.blocked
        bl_m2 = (gx, gy, M2_LYR) in router.blocked
        us_m1 = (gx, gy, M1_LYR) in router.used
        us_m2 = (gx, gy, M2_LYR) in router.used
        pm_m1 = (gx, gy, M1_LYR) in router.permanent
        pm_m2 = (gx, gy, M2_LYR) in router.permanent
        print(f'  {p["key"]}: ({p["x"]/1000:.2f}, {p["y"]/1000:.2f}) µm '
              f'grid=({gx},{gy}) mode={p["mode"]}')
        print(f'    M1: blocked={bl_m1} permanent={pm_m1} used={us_m1}')
        print(f'    M2: blocked={bl_m2} permanent={pm_m2} used={us_m2}')

    # Simulate punch_net_holes (clear soft blocks at pin centers)
    print(f'\n[2b] Simulating pin hole punch...')
    punched = set()
    ARM = 2
    for p in target_pins:
        gx, gy = router.to_grid(p['x'], p['y'])
        for dx, dy in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
            for step in range(ARM + 1):
                cx = gx + step * dx
                cy = gy + step * dy
                if 0 <= cx < router.nx and 0 <= cy < router.ny:
                    for lyr in (M1_LYR, M2_LYR):
                        cell = (cx, cy, lyr)
                        if cell in router.blocked and cell not in router.permanent:
                            router.blocked.discard(cell)
                            punched.add(cell)
    print(f'  Punched {len(punched)} soft cells')

    # BFS flood from each pin
    print(f'\n[3] Reachability analysis (after punch):')
    floods = []
    for p in target_pins:
        gxy = router.to_grid(p['x'], p['y'])
        reachable = _bfs_flood(router, gxy)
        floods.append(reachable)
        print(f'  {p["key"]}: {len(reachable)} reachable cells')

    # Check mutual reachability
    if len(floods) >= 2:
        for i in range(len(floods)):
            for j in range(i + 1, len(floods)):
                gxy_j = router.to_grid(target_pins[j]['x'], target_pins[j]['y'])
                any_match = any((gxy_j[0], gxy_j[1], lyr) in floods[i]
                                for lyr in (M1_LYR, M2_LYR))
                status = 'CONNECTED' if any_match else 'DISCONNECTED'
                print(f'  {target_pins[i]["key"]} <-> {target_pins[j]["key"]}: {status}')

    # Obstacle frontier analysis
    print(f'\n[4] Obstacle frontier (what blocks the path):')

    # Use the smaller flood (likely the stuck pin)
    smallest_idx = min(range(len(floods)), key=lambda i: len(floods[i]))
    smallest_flood = floods[smallest_idx]
    frontier = _obstacle_frontier(router, smallest_flood)

    # Categorize
    by_type = {}
    for cell, typ in frontier.items():
        by_type.setdefault(typ, []).append(cell)

    for typ, cells in sorted(by_type.items()):
        print(f'  {typ}: {len(cells)} cells')
        for gx, gy, lyr in sorted(cells)[:20]:
            nm_x, nm_y = router.to_nm(gx, gy)
            lyr_name = 'M1' if lyr == M1_LYR else 'M2'
            print(f'    grid({gx},{gy}) = ({nm_x/1000:.2f},{nm_y/1000:.2f})µm {lyr_name}')

    # For 'used' cells, identify which nets own them
    used_cells = by_type.get('used', [])
    if used_cells:
        print(f'\n[5] Used-cell owners (which nets block the corridor):')
        # Build route data for owner lookup
        route_data = {}
        for nn, sr in solver2.signal_routes.items():
            route_data[nn] = {'segments': [list(s) for s in sr['segments']]}
        for nn, pr in solver2.pre_routes.items():
            route_data[nn] = {'segments': [list(s) for s in pr['segments']]}

        owner_counts = {}
        sample_cells = used_cells[:200]  # limit for performance
        for cell in sample_cells:
            owner = _find_used_owner(router, cell, route_data, {})
            owner_counts[owner] = owner_counts.get(owner, 0) + 1

        for owner, cnt in sorted(owner_counts.items(), key=lambda x: -x[1]):
            pct = cnt * 100 / len(sample_cells)
            print(f'    {owner}: {cnt} cells ({pct:.0f}%)')

    # For 'permanent' cells, identify what they are
    perm_cells = by_type.get('permanent', [])
    if perm_cells:
        print(f'\n[6] Permanent obstacle sources:')
        # Check if any are power stubs
        for net in netlist['nets']:
            if net['type'] != 'power':
                continue
            for pin_str in net['pins']:
                inst, pin = pin_str.split('.')
                ap = solver2.access_points.get((inst, pin))
                if not ap:
                    continue
                stub = ap.get('m1_stub')
                if not stub:
                    continue
                # Check if any permanent frontier cell falls within stub + margin
                from ..pdk import M1_MIN_S, M1_SIG_W
                margin = M1_MIN_S + M1_SIG_W // 2
                s_gx1, s_gy1 = router.to_grid(stub[0] - margin, stub[1] - margin)
                s_gx2, s_gy2 = router.to_grid(stub[2] + margin, stub[3] + margin)
                count = sum(1 for gx, gy, lyr in perm_cells
                            if s_gx1 <= gx <= s_gx2 and s_gy1 <= gy <= s_gy2
                            and lyr == M1_LYR)
                if count > 0:
                    print(f'    {pin_str} ({net["name"]}) M1 stub '
                          f'[{stub[0]},{stub[1]},{stub[2]},{stub[3]}]: '
                          f'{count} frontier cells')

    # Summary: manhattan corridor between pins
    if len(target_pins) >= 2:
        print(f'\n[7] Corridor analysis (pin-to-pin bounding box):')
        all_x = [p['x'] for p in target_pins]
        all_y = [p['y'] for p in target_pins]
        corridor = (min(all_x), min(all_y), max(all_x), max(all_y))
        gx1, gy1 = router.to_grid(corridor[0], corridor[1])
        gx2, gy2 = router.to_grid(corridor[2], corridor[3])
        total_cells = 0
        blocked_cells = 0
        used_cells_c = 0
        free_cells = 0
        for gx in range(gx1, gx2 + 1):
            for gy in range(gy1, gy2 + 1):
                for lyr in (M1_LYR, M2_LYR):
                    total_cells += 1
                    cell = (gx, gy, lyr)
                    if cell in router.permanent:
                        blocked_cells += 1
                    elif cell in router.blocked:
                        blocked_cells += 1
                    elif cell in router.used:
                        used_cells_c += 1
                    else:
                        free_cells += 1
        print(f'  Corridor: ({corridor[0]/1000:.1f},{corridor[1]/1000:.1f}) - '
              f'({corridor[2]/1000:.1f},{corridor[3]/1000:.1f}) µm')
        print(f'  Grid: ({gx1},{gy1}) - ({gx2},{gy2})')
        print(f'  Cells: {total_cells} total, {blocked_cells} blocked, '
              f'{used_cells_c} used, {free_cells} free')
        if total_cells > 0:
            print(f'  Utilization: {(blocked_cells+used_cells_c)*100/total_cells:.0f}% occupied')

    print()
    return frontier


def run(target_net=None, **kwargs):
    if target_net is None:
        target_net = 'vco_out'
    return diagnose(target_net, **kwargs)


if __name__ == '__main__':
    net = sys.argv[1] if len(sys.argv) > 1 else 'vco_out'
    run(net)
