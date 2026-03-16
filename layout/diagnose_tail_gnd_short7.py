#!/usr/bin/env python3
"""Trace gnd↔tail short — Phase 7: FULL BFS flood fill across all layers.

Previous scripts only traced 1-2 hops. This does unlimited BFS:
  M1 ↔ Via1 ↔ M2 ↔ Via2 ↔ M3 ↔ Via3 ↔ M4
  M1 ↔ Contact ↔ ptap → pwell (implicit gnd)

Also checks: pwell_sub connectivity (IHP LVS connects pwell to ptap to cont to M1).

For each merged polygon on each layer, we assign an index. Then we build
an adjacency graph: two polygons are connected if a via overlaps both.
BFS from the tail M1 polygon. If we reach any polygon that has a gnd label,
we found the short path.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short7.py
"""
import os, sys, time
from collections import deque
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

t0 = time.time()
GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

def get_region(layer, dt):
    li = layout.layer(layer, dt)
    return kdb.Region(top.begin_shapes_rec(li))

# ── Build merged polygon lists for each metal layer ──
LAYERS = {
    'M1':  (8, 0),
    'M2':  (10, 0),
    'M3':  (30, 0),
    'M4':  (50, 0),
}
VIAS = {
    'Via1': ((19, 0), 'M1', 'M2'),
    'Cont': ((6, 0),  'M1', None),   # Contact: M1 to active/ptap (special)
    'Via2': ((29, 0), 'M2', 'M3'),
    'Via3': ((49, 0), 'M3', 'M4'),
}
LABEL_LAYERS = {
    'M1': (8, 25),
    'M2': (10, 25),
    'M3': (30, 25),
}

print("Building merged polygon index...")
layer_polys = {}  # layer_name -> list of merged polygons
layer_regions = {}
for name, (l, d) in LAYERS.items():
    reg = get_region(l, d).merged()
    polys = list(reg.each())
    layer_polys[name] = polys
    layer_regions[name] = reg
    print(f"  {name}: {len(polys)} merged polygons")

# Via regions
via_regions = {}
for vname, ((vl, vd), _, _) in VIAS.items():
    via_regions[vname] = get_region(vl, vd)
    print(f"  {vname}: {via_regions[vname].count()} shapes")

# ── Also build ptap connectivity (IHP LVS path: pwell → ptap → Contact → M1) ──
activ = get_region(1, 0)
psd_drw = get_region(14, 0)
nwell_drw = get_region(31, 0)
gatpoly = get_region(5, 0)
cont_drw = get_region(6, 0)

pactiv = activ & psd_drw
bb = top.bbox()
CHIP = kdb.Region(bb)
pwell = CHIP - nwell_drw
ptap = (pactiv & pwell) - gatpoly
ptap_polys = list(ptap.each())
print(f"  ptap: {len(ptap_polys)} shapes")

# ── Collect all labels ──
print("\nCollecting labels...")
labels = {}  # (layer_name, poly_idx) -> set of net names
for lname, (ll, ld) in LABEL_LAYERS.items():
    li = layout.layer(ll, ld)
    polys = layer_polys[lname]
    for shape in top.shapes(li).each():
        if not shape.is_text():
            continue
        net = shape.text.string
        pt = kdb.Point(shape.text.x, shape.text.y)
        probe = kdb.Region(kdb.Box(pt.x - 50, pt.y - 50, pt.x + 50, pt.y + 50))
        for idx, poly in enumerate(polys):
            if not (kdb.Region(poly) & probe).is_empty():
                key = (lname, idx)
                if key not in labels:
                    labels[key] = set()
                labels[key].add(net)
                break

# Show label summary
label_counts = {}
for (lname, idx), nets in labels.items():
    for n in nets:
        label_counts[n] = label_counts.get(n, 0) + 1
print(f"  Found {len(labels)} labeled polygons, {len(label_counts)} unique nets")

# Find tail and gnd labels
tail_nodes = []
gnd_nodes = []
for (lname, idx), nets in labels.items():
    if 'tail' in nets:
        tail_nodes.append((lname, idx))
        print(f"  tail label: {lname}#{idx} bbox={layer_polys[lname][idx].bbox()}")
    if 'gnd' in nets:
        gnd_nodes.append((lname, idx))

print(f"  gnd labels on {len(gnd_nodes)} polygons")
for lname, idx in gnd_nodes[:5]:
    print(f"    {lname}#{idx} bbox={layer_polys[lname][idx].bbox()}")
if len(gnd_nodes) > 5:
    print(f"    ... and {len(gnd_nodes)-5} more")

# ── Build adjacency graph via via overlaps ──
# Node = (layer_name, poly_idx) or ('ptap', ptap_idx) or ('pwell', 0)
# Edge = via overlap
print("\nBuilding connectivity graph...")

graph = {}  # node -> set of (neighbor_node, via_name)

def add_edge(n1, n2, via_name):
    if n1 not in graph:
        graph[n1] = set()
    if n2 not in graph:
        graph[n2] = set()
    graph[n1].add((n2, via_name))
    graph[n2].add((n1, via_name))

# For each via type, find which metal polygons it connects
for vname, ((vl, vd), lower, upper) in VIAS.items():
    if vname == 'Cont':
        # Contact connects M1 to ptap (and nsd_fet, but we handle that separately)
        # For each Contact shape, find overlapping M1 and overlapping ptap
        cont_shapes = list(via_regions[vname].each())
        print(f"  Processing {len(cont_shapes)} Contact shapes...")

        # Build spatial index: for each Contact, check M1 and ptap
        ptap_contact_count = 0
        for ci, cshape in enumerate(cont_shapes):
            cr = kdb.Region(cshape)
            # Find M1 polygon
            m1_overlap = layer_regions['M1'] & cr.sized(10)
            if m1_overlap.is_empty():
                continue

            # Find ptap overlap
            ptap_overlap = ptap & cr.sized(10)
            if ptap_overlap.is_empty():
                continue

            # This contact connects M1 to ptap!
            # Find which M1 polygon
            m1_center = kdb.Point(
                (cshape.bbox().left + cshape.bbox().right) // 2,
                (cshape.bbox().bottom + cshape.bbox().top) // 2)
            m1_probe = kdb.Region(kdb.Box(
                m1_center.x - 20, m1_center.y - 20,
                m1_center.x + 20, m1_center.y + 20))

            for m1_idx, m1_poly in enumerate(layer_polys['M1']):
                if not (kdb.Region(m1_poly) & m1_probe).is_empty():
                    # Find which ptap polygon
                    for pt_idx, pt_poly in enumerate(ptap_polys):
                        pt_r = kdb.Region(pt_poly)
                        if not (pt_r & cr.sized(10)).is_empty():
                            add_edge(('M1', m1_idx), ('ptap', pt_idx), 'Cont-ptap')
                            ptap_contact_count += 1
                            break
                    break

        print(f"    ptap↔M1 connections via Contact: {ptap_contact_count}")
        continue

    if upper is None:
        continue

    # Standard via: connects lower metal to upper metal
    via_shapes = list(via_regions[vname].each())
    print(f"  Processing {len(via_shapes)} {vname} shapes...")

    lower_polys = layer_polys[lower]
    upper_polys = layer_polys[upper]

    conn_count = 0
    for vi, vshape in enumerate(via_shapes):
        vr = kdb.Region(vshape)
        vc = kdb.Point(
            (vshape.bbox().left + vshape.bbox().right) // 2,
            (vshape.bbox().bottom + vshape.bbox().top) // 2)
        vprobe = kdb.Region(kdb.Box(vc.x - 20, vc.y - 20, vc.x + 20, vc.y + 20))

        # Find lower polygon
        lower_idx = -1
        for idx, poly in enumerate(lower_polys):
            if not (kdb.Region(poly) & vprobe).is_empty():
                lower_idx = idx
                break

        # Find upper polygon
        upper_idx = -1
        for idx, poly in enumerate(upper_polys):
            if not (kdb.Region(poly) & vprobe).is_empty():
                upper_idx = idx
                break

        if lower_idx >= 0 and upper_idx >= 0:
            add_edge((lower, lower_idx), (upper, upper_idx), vname)
            conn_count += 1

    print(f"    {lower}↔{upper} connections: {conn_count}")

# Add pwell↔ptap connections (IHP LVS: connect(pwell, ptap))
# All ptap shapes are in pwell by definition
pwell_node = ('pwell', 0)
for pt_idx in range(len(ptap_polys)):
    add_edge(pwell_node, ('ptap', pt_idx), 'pwell-ptap')

print(f"\nGraph: {len(graph)} nodes")

# ── BFS from tail ──
print("\n" + "="*60)
print("BFS from tail label...")
print("="*60)

if not tail_nodes:
    print("ERROR: No tail label found!")
    sys.exit(1)

visited = {}  # node -> (parent_node, via_name) or None for start
queue = deque()

for tn in tail_nodes:
    visited[tn] = None
    queue.append(tn)

gnd_found = None
step = 0

while queue:
    node = queue.popleft()
    step += 1

    # Check if this node has a gnd label
    if node in labels and 'gnd' in labels[node]:
        gnd_found = node
        print(f"\n*** FOUND GND at {node} after {step} steps! ***")
        break

    # Check if this is pwell (connected to all gnd ptap)
    if node == pwell_node:
        # pwell is the implicit ground — if tail reaches pwell, it's shorted to gnd
        # But only if pwell is actually labeled gnd somewhere
        # In IHP LVS, pwell connects to pwell_sub which gets "sub!" label
        # Let's check if any ptap-connected M1 has gnd label
        pass

    if node not in graph:
        continue

    for neighbor, via_name in graph[node]:
        if neighbor not in visited:
            visited[neighbor] = (node, via_name)
            queue.append(neighbor)

# ── Report results ──
if gnd_found:
    print(f"\n{'='*60}")
    print("SHORTEST PATH: tail → gnd")
    print(f"{'='*60}")

    # Trace back path
    path = []
    node = gnd_found
    while node is not None:
        entry = visited[node]
        if entry is None:
            path.append((node, None))
        else:
            parent, via = entry
            path.append((node, via))
        node = entry[0] if entry else None

    path.reverse()

    for i, (node, via) in enumerate(path):
        layer_name, idx = node
        if layer_name in layer_polys:
            poly = layer_polys[layer_name][idx]
            bb = poly.bbox()
            lbl = labels.get(node, set())
            lbl_str = f" labels={lbl}" if lbl else ""
            area = poly.area() / 1e6
            print(f"  [{i}] {layer_name}#{idx} bbox=({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                  f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.3f}µm²{lbl_str}")
        elif layer_name == 'ptap':
            poly = ptap_polys[idx]
            bb = poly.bbox()
            print(f"  [{i}] ptap#{idx} bbox=({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                  f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
        elif layer_name == 'pwell':
            print(f"  [{i}] pwell (entire chip minus NWell)")

        if via:
            print(f"       ↑ via {via}")
else:
    print(f"\nNo gnd label found in tail's connected component ({len(visited)} nodes visited)")

    # Show what labels ARE in the component
    component_labels = set()
    for node in visited:
        if node in labels:
            component_labels.update(labels[node])

    if component_labels:
        print(f"Labels in tail component: {sorted(component_labels)}")

    # Show layer breakdown of visited nodes
    layer_counts = {}
    for node in visited:
        ln = node[0]
        layer_counts[ln] = layer_counts.get(ln, 0) + 1
    print(f"Visited nodes by layer: {dict(sorted(layer_counts.items()))}")

    # Check if pwell was reached
    if pwell_node in visited:
        print("\n*** tail component reaches pwell! ***")
        print("In IHP LVS, pwell is connected to all ptap, which connect to gnd M1.")
        print("This means tail is shorted to gnd through the substrate!")

        # Trace path to pwell
        path = []
        node = pwell_node
        while node is not None:
            entry = visited[node]
            if entry is None:
                path.append((node, None))
            else:
                parent, via = entry
                path.append((node, via))
            node = entry[0] if entry else None

        path.reverse()

        print(f"\nPATH: tail → pwell:")
        for i, (node, via) in enumerate(path):
            layer_name, idx = node
            if layer_name in layer_polys:
                poly = layer_polys[layer_name][idx]
                bb = poly.bbox()
                lbl = labels.get(node, set())
                lbl_str = f" labels={lbl}" if lbl else ""
                print(f"  [{i}] {layer_name}#{idx} bbox=({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f}){lbl_str}")
            elif layer_name == 'ptap':
                poly = ptap_polys[idx]
                bb = poly.bbox()
                print(f"  [{i}] ptap#{idx} bbox=({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
            elif layer_name == 'pwell':
                print(f"  [{i}] pwell (entire chip minus NWell)")

            if via:
                print(f"       ↑ via {via}")

    # Also: check if any gnd-labeled polygon is in the graph but NOT in tail's component
    gnd_component_nodes = set()
    for gn in gnd_nodes:
        if gn in visited:
            print(f"\n*** gnd node {gn} IS in tail's component! ***")
        else:
            gnd_component_nodes.add(gn)

    if gnd_component_nodes:
        print(f"\ngnd nodes NOT in tail component: {len(gnd_component_nodes)}")
        # BFS from gnd to see its component
        gnd_visited = set()
        gnd_queue = deque()
        for gn in gnd_nodes:
            if gn not in visited:
                gnd_visited.add(gn)
                gnd_queue.append(gn)

        while gnd_queue:
            node = gnd_queue.popleft()
            if node not in graph:
                continue
            for neighbor, via_name in graph[node]:
                if neighbor not in gnd_visited:
                    gnd_visited.add(neighbor)
                    gnd_queue.append(neighbor)

        gnd_layer_counts = {}
        for node in gnd_visited:
            ln = node[0]
            gnd_layer_counts[ln] = gnd_layer_counts.get(ln, 0) + 1
        print(f"gnd component nodes by layer: {dict(sorted(gnd_layer_counts.items()))}")

        gnd_component_labels = set()
        for node in gnd_visited:
            if node in labels:
                gnd_component_labels.update(labels[node])
        print(f"Labels in gnd component: {sorted(gnd_component_labels)}")

        if pwell_node in gnd_visited:
            print("gnd component also reaches pwell")

elapsed = time.time() - t0
print(f"\nElapsed: {elapsed:.1f}s")
