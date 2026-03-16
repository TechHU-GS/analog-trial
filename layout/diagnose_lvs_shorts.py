#!/usr/bin/env python3
"""Find LVS short circuits: multi-layer BFS from device pin positions.

For each merged net pair (ns2|vco2, ns3|vco3, ns4|vco4, vco_out|vdd):
1. Get AP positions for each net's device pins
2. Find M1 shapes at those positions (device-level metal)
3. Multi-layer BFS: M1→Via1→M2→Via2→M3→Via3→M4
4. Report where net A's connected component meets net B's

Key insight: VCO ns/vco nets have 0 routed wires — they're connected
entirely through M1 device stubs. Shorts are likely on M1.

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_lvs_shorts.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

LAYERS = {
    'M1': layout.layer(8, 0),
    'Cont': layout.layer(6, 0),
    'Via1': layout.layer(19, 0),
    'M2': layout.layer(10, 0),
    'Via2': layout.layer(29, 0),
    'M3': layout.layer(30, 0),
    'Via3': layout.layer(33, 0),
    'M4': layout.layer(34, 0),
}

# Layer connectivity graph: metal↔via↔metal
METAL_LAYERS = ['M1', 'M2', 'M3', 'M4']
VIA_CONNECTS = [
    ('M1', 'Via1', 'M2'),
    ('M2', 'Via2', 'M3'),
    ('M3', 'Via3', 'M4'),
]

with open('output/routing.json') as f:
    routing = json.load(f)
aps = routing.get('access_points', {})


def get_all_shapes(layer_name):
    """Get all shapes on a layer from top cell + instances."""
    li = LAYERS[layer_name]
    shapes = []
    for si in top.shapes(li).each():
        shapes.append(si.bbox())
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(li).each():
            shapes.append(si.bbox().transformed(inst.trans))
    return shapes


def shapes_touch(a, b, margin=5):
    """Check if two boxes touch or overlap (within margin in nm)."""
    xa = max(a.left - b.right, b.left - a.right)
    ya = max(a.bottom - b.top, b.bottom - a.top)
    return xa <= margin and ya <= margin


# Pre-load all shapes per layer
print("Loading shapes...")
all_shapes = {}
for lyr in list(LAYERS.keys()):
    all_shapes[lyr] = get_all_shapes(lyr)
    print(f"  {lyr}: {len(all_shapes[lyr])} shapes")


def multi_layer_bfs(seed_positions, search_radius=300):
    """BFS from seed positions through all metal+via layers.

    Returns: dict of {(layer, shape_idx): parent} for connected component.
    seed_positions: list of (x, y) in nm.
    """
    # Node ID = (layer_name, shape_index)
    visited = set()
    queue = []
    parent = {}  # node → parent node

    # Seed: find M1 shapes near seed positions
    for layer in METAL_LAYERS:
        shapes = all_shapes[layer]
        for i, s in enumerate(shapes):
            cx = (s.left + s.right) // 2
            cy = (s.bottom + s.top) // 2
            for sx, sy in seed_positions:
                if abs(cx - sx) <= search_radius and abs(cy - sy) <= search_radius:
                    node = (layer, i)
                    if node not in visited:
                        visited.add(node)
                        queue.append(node)

    # BFS: same-layer touching + via-connected cross-layer
    while queue:
        node = queue.pop(0)
        lyr, idx = node
        current = all_shapes[lyr][idx]

        # Same-layer neighbors
        for j, other in enumerate(all_shapes[lyr]):
            n2 = (lyr, j)
            if n2 not in visited and shapes_touch(current, other):
                visited.add(n2)
                queue.append(n2)
                parent[n2] = node

        # Via-connected neighbors (cross-layer)
        for m1, via, m2 in VIA_CONNECTS:
            if lyr == m1 or lyr == m2:
                via_shapes = all_shapes[via]
                target_lyr = m2 if lyr == m1 else m1
                for vi, vs in enumerate(via_shapes):
                    if shapes_touch(current, vs):
                        # This via touches current shape — find shapes on other layer
                        for ti, ts in enumerate(all_shapes[target_lyr]):
                            n2 = (target_lyr, ti)
                            if n2 not in visited and shapes_touch(vs, ts):
                                visited.add(n2)
                                queue.append(n2)
                                parent[n2] = node

    return visited, parent


def trace_path(parent, start, end):
    """Trace path from end back to start via parent dict."""
    path = [end]
    while path[-1] in parent:
        path.append(parent[path[-1]])
        if path[-1] == start:
            break
    path.reverse()
    return path


def get_net_pin_positions(net_name):
    """Get (x,y) positions for all pins on a net."""
    positions = []
    route = routing.get('signal_routes', {}).get(net_name, {})
    for pk in route.get('pins', []):
        ap = aps.get(pk)
        if ap:
            positions.append((ap['x'], ap['y'], pk))
    # Also check power drops for vdd
    if net_name == 'vdd':
        for drop in routing.get('power', {}).get('drops', []):
            if drop['net'] == 'vdd':
                pk = f"{drop['inst']}.{drop['pin']}"
                ap = aps.get(pk)
                if ap:
                    positions.append((ap['x'], ap['y'], pk))
    return positions


# ======================== FOCUSED ANALYSIS ========================
# For ns/vco merges: check M1 shapes between Mpu S and D pins

print("\n" + "="*70)
print("FOCUSED: M1 shapes between VCO PMOS S/D pins")
print("="*70)

# Stages with merged ns|vco: 2, 3, 4
# Stages without merge: 1, 5  (for comparison)
for stage in [1, 2, 3, 4, 5]:
    s_pin = f'Mpu{stage}.S'
    d_pin = f'Mpu{stage}.D'
    s_ap = aps.get(s_pin)
    d_ap = aps.get(d_pin)
    if not s_ap or not d_ap:
        print(f"\n  Stage {stage}: AP not found for {s_pin} or {d_pin}")
        continue

    sx, sy = s_ap['x'], s_ap['y']
    dx, dy = d_ap['x'], d_ap['y']
    merged = stage in [2, 3, 4]
    label = "MERGED" if merged else "OK"

    print(f"\n  Stage {stage} ({label}): ns{stage}=Mpu{stage}.S ({sx},{sy}), vco{stage}=Mpu{stage}.D ({dx},{dy})")
    print(f"    S-D distance: {abs(dx-sx)}nm X, {abs(dy-sy)}nm Y")

    # Find M1 shapes in the region between S and D
    region_x1 = min(sx, dx) - 500
    region_x2 = max(sx, dx) + 500
    region_y1 = min(sy, dy) - 500
    region_y2 = max(sy, dy) + 500

    m1_shapes = all_shapes['M1']
    nearby = []
    for i, s in enumerate(m1_shapes):
        if (s.right >= region_x1 and s.left <= region_x2 and
            s.top >= region_y1 and s.bottom <= region_y2):
            # Check if shape is near S pin
            near_s = (abs((s.left+s.right)//2 - sx) < 500 and
                      abs((s.bottom+s.top)//2 - sy) < 500)
            # Check if shape is near D pin
            near_d = (abs((s.left+s.right)//2 - dx) < 500 and
                      abs((s.bottom+s.top)//2 - dy) < 500)
            # Check if shape spans from S to D
            spans = (s.left <= sx + 200 and s.right >= dx - 200)

            tag = ""
            if near_s: tag += " ←S(ns)"
            if near_d: tag += " ←D(vco)"
            if spans: tag += " ***BRIDGES S-D***"

            nearby.append((i, s, tag))

    print(f"    M1 shapes in S-D region: {len(nearby)}")
    for i, s, tag in nearby:
        print(f"      [{i}] ({s.left},{s.bottom};{s.right},{s.top}) "
              f"{s.width()}x{s.height()}{tag}")

    # Also check Mpb S and D (current source) — Mpb.S=vdd, Mpb.D=ns
    mpb_d_pin = f'Mpb{stage}.D'
    mpb_s1_pin = f'Mpb{stage}.S1'
    mpb_s2_pin = f'Mpb{stage}.S2'
    mpb_d_ap = aps.get(mpb_d_pin)
    mpb_s1_ap = aps.get(mpb_s1_pin)
    mpb_s2_ap = aps.get(mpb_s2_pin)

    if mpb_d_ap and mpb_s1_ap:
        print(f"    Mpb{stage}: D(ns)=({mpb_d_ap['x']},{mpb_d_ap['y']}), "
              f"S1(vdd)=({mpb_s1_ap['x']},{mpb_s1_ap['y']})")


# ======================== MULTI-LAYER BFS ========================

print("\n" + "="*70)
print("MULTI-LAYER BFS: Tracing merged net connections")
print("="*70)

MERGED = [
    ('ns2', 'vco2'),
    ('ns3', 'vco3'),
    ('ns4', 'vco4'),
    ('vco_out', 'vdd'),
]

for net_a, net_b in MERGED:
    print(f"\n{'='*70}")
    print(f"MERGED: {net_a}|{net_b}")
    print(f"{'='*70}")

    a_pos = get_net_pin_positions(net_a)
    b_pos = get_net_pin_positions(net_b)

    print(f"  {net_a}: {len(a_pos)} pins")
    for x, y, pk in a_pos[:5]:
        print(f"    {pk}: ({x},{y})")

    print(f"  {net_b}: {len(b_pos)} pins")
    for x, y, pk in b_pos[:5]:
        print(f"    {pk}: ({x},{y})")
    if len(b_pos) > 5:
        print(f"    ... and {len(b_pos)-5} more")

    # BFS from net A
    a_seeds = [(x, y) for x, y, _ in a_pos]
    print(f"\n  BFS from {net_a} pins...")
    a_visited, a_parent = multi_layer_bfs(a_seeds)
    a_layers = {}
    for lyr, idx in a_visited:
        a_layers[lyr] = a_layers.get(lyr, 0) + 1
    print(f"  Reached: {dict(sorted(a_layers.items()))}")

    # Check if any B pin positions are in A's connected component
    print(f"\n  Checking if {net_b} pins are reached...")
    for x, y, pk in b_pos:
        for lyr in METAL_LAYERS:
            for i, s in enumerate(all_shapes[lyr]):
                node = (lyr, i)
                if node in a_visited:
                    cx = (s.left + s.right) // 2
                    cy = (s.bottom + s.top) // 2
                    if abs(cx - x) <= 300 and abs(cy - y) <= 300:
                        # Found! Trace path
                        path = trace_path(a_parent, None, node)
                        print(f"    *** {pk} ({x},{y}) reached via {lyr}! ***")
                        print(f"    Path ({len(path)} steps):")
                        for pi, (pl, pidx) in enumerate(path[:15]):
                            bb = all_shapes[pl][pidx]
                            print(f"      [{pi}] {pl}: ({bb.left},{bb.bottom};"
                                  f"{bb.right},{bb.top}) {bb.width()}x{bb.height()}")
                        if len(path) > 15:
                            print(f"      ... {len(path)-15} more steps")
                        # Only show first match per pin
                        break
            else:
                continue
            break

print("\n\nDone.")
