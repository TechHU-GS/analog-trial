#!/usr/bin/env python3
"""Find where mid_p and GND merge in the extracted layout.

BFS from known mid_p points and known GND points, find shared polygons.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_midp_gnd.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)
li_m4 = layout.layer(50, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)
li_v3 = layout.layer(49, 0)

print("Loading and merging layers...")
layers_data = {
    'M1': kdb.Region(top.begin_shapes_rec(li_m1)).merged(),
    'M2': kdb.Region(top.begin_shapes_rec(li_m2)).merged(),
    'M3': kdb.Region(top.begin_shapes_rec(li_m3)).merged(),
    'M4': kdb.Region(top.begin_shapes_rec(li_m4)).merged(),
}
via_regions = {
    'V1': (kdb.Region(top.begin_shapes_rec(li_v1)), 'M1', 'M2'),
    'V2': (kdb.Region(top.begin_shapes_rec(li_v2)), 'M2', 'M3'),
    'V3': (kdb.Region(top.begin_shapes_rec(li_v3)), 'M3', 'M4'),
}

# Build indexed polygon lists
poly_lists = {}
for lname, region in layers_data.items():
    polys = list(region.each())
    poly_lists[lname] = polys
    print(f"  {lname}: {len(polys)} merged polygons")


def poly_id(poly):
    bb = poly.bbox()
    return (bb.left, bb.bottom, bb.right, bb.top)


def find_polys_at(layer_name, probe_box):
    """Find all merged polygons on layer that overlap probe."""
    probe = kdb.Region(probe_box)
    results = []
    for idx, poly in enumerate(poly_lists[layer_name]):
        pr = kdb.Region(poly)
        if not (pr & probe).is_empty():
            results.append((idx, poly))
    return results


def bfs_flood(start_probes, label):
    """BFS flood-fill from probe points through via stack.
    Returns dict: layer_name -> set of poly indices.
    Also records BFS parent for back-trace.
    """
    print(f"\n{'=' * 70}")
    print(f"BFS from {label}")
    print(f"{'=' * 70}")

    visited = {ln: set() for ln in layers_data}
    parent = {}  # (layer, idx) -> (parent_layer, parent_idx, via_name, vx, vy) or None
    queue = []

    # Seed
    for probe, probe_layers in start_probes:
        for ln in probe_layers:
            hits = find_polys_at(ln, probe)
            for idx, poly in hits:
                if idx not in visited[ln]:
                    visited[ln].add(idx)
                    queue.append((ln, idx))
                    parent[(ln, idx)] = None
                    bb = poly.bbox()
                    print(f"  Seed {ln}#{idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

    iteration = 0
    while queue:
        iteration += 1
        if iteration > 5000:
            print("  BFS iteration limit!")
            break

        cur_layer, cur_idx = queue.pop(0)
        cur_poly = poly_lists[cur_layer][cur_idx]
        cur_region = kdb.Region(cur_poly)

        for vname, (vreg, lo, hi) in via_regions.items():
            if cur_layer not in (lo, hi):
                continue
            v_on = vreg & cur_region
            if v_on.count() == 0:
                continue
            other = hi if cur_layer == lo else lo
            for v in v_on.each():
                vb = v.bbox()
                cx = (vb.left + vb.right) // 2
                cy = (vb.top + vb.bottom) // 2
                vprobe = kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50)
                for oidx, opoly in enumerate(poly_lists[other]):
                    if oidx in visited[other]:
                        continue
                    opr = kdb.Region(opoly)
                    if not (opr & kdb.Region(vprobe)).is_empty():
                        visited[other].add(oidx)
                        queue.append((other, oidx))
                        parent[(other, oidx)] = (cur_layer, cur_idx, vname, cx, cy)

    total = sum(len(s) for s in visited.values())
    print(f"  Reachable: {total} (M1={len(visited['M1'])}, M2={len(visited['M2'])}, "
          f"M3={len(visited['M3'])}, M4={len(visited['M4'])})")
    return visited, parent


# Load routing for mid_p route coordinates
with open('output/routing.json') as f:
    routing = json.load(f)

# mid_p probes from its routing segments
# Via3 at (44150, 84850) — this is a known mid_p point on M3 and M4
midp_probes = [
    (kdb.Box(44050, 84750, 44250, 84950), ['M3', 'M4']),  # Via3 location
    (kdb.Box(42650, 84750, 42850, 84950), ['M2']),  # M2 segment
    (kdb.Box(42650, 85000, 42850, 85200), ['M1']),  # M1 vertical segment
]

# GND probes — use ptap at Mc_tail.S (known good from previous diagnostic)
gnd_probes = [
    (kdb.Box(45000, 98000, 45300, 98300), ['M1']),  # Mc_tail.S source (GND)
]

midp_visited, midp_parent = bfs_flood(midp_probes, "mid_p")
gnd_visited, gnd_parent = bfs_flood(gnd_probes, "GND")

# Find merge points
print(f"\n{'=' * 70}")
print("mid_p ↔ GND MERGE CHECK")
print(f"{'=' * 70}")

any_merge = False
for lname in ['M1', 'M2', 'M3', 'M4']:
    common = midp_visited[lname] & gnd_visited[lname]
    if common:
        any_merge = True
        print(f"\n  *** {lname} MERGE: {len(common)} shared polygon(s)! ***")
        for idx in sorted(common):
            poly = poly_lists[lname][idx]
            bb = poly.bbox()
            area = poly.area() / 1e6
            print(f"    #{idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.1f}µm²")

            # Back-trace from mid_p side
            key = (lname, idx)
            if key in midp_parent:
                print(f"    mid_p path:")
                trace = key
                depth = 0
                while trace and depth < 15:
                    tl, ti = trace
                    tbb = poly_lists[tl][ti].bbox()
                    p = midp_parent.get(trace)
                    via_info = ""
                    if p:
                        pl, pi, vn, vx, vy = p
                        via_info = f" via {vn}@({vx/1e3:.3f},{vy/1e3:.3f})"
                    print(f"      {tl}#{ti}: ({tbb.left/1e3:.3f},{tbb.bottom/1e3:.3f})-"
                          f"({tbb.right/1e3:.3f},{tbb.top/1e3:.3f}){via_info}")
                    trace = (p[0], p[1]) if p else None
                    depth += 1

            # Back-trace from GND side
            if key in gnd_parent:
                print(f"    GND path:")
                trace = key
                depth = 0
                while trace and depth < 15:
                    tl, ti = trace
                    tbb = poly_lists[tl][ti].bbox()
                    p = gnd_parent.get(trace)
                    via_info = ""
                    if p:
                        pl, pi, vn, vx, vy = p
                        via_info = f" via {vn}@({vx/1e3:.3f},{vy/1e3:.3f})"
                    print(f"      {tl}#{ti}: ({tbb.left/1e3:.3f},{tbb.bottom/1e3:.3f})-"
                          f"({tbb.right/1e3:.3f},{tbb.top/1e3:.3f}){via_info}")
                    trace = (p[0], p[1]) if p else None
                    depth += 1
    else:
        print(f"  {lname}: no merge (mid_p={len(midp_visited[lname])}, GND={len(gnd_visited[lname])})")

if not any_merge:
    print("\n  No mid_p↔GND merge found via metal stack BFS.")
    print("  The merger may be through substrate/well (ptap/ntap body connections).")

print("\n\nDONE.")
