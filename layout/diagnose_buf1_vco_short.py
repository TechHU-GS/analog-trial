#!/usr/bin/env python3
"""Trace buf1↔vco_out short.

Both nets have labels on M2. Trace connectivity from buf1's M2 label
to find how it connects to vco_out.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_buf1_vco_short.py
"""
import os
from collections import deque
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

def get_region(layer, dt):
    li = layout.layer(layer, dt)
    return kdb.Region(top.begin_shapes_rec(li))

LAYERS = {'M1': (8,0), 'M2': (10,0), 'M3': (30,0), 'M4': (50,0)}
VIAS = {'Via1': ((19,0), 'M1', 'M2'), 'Via2': ((29,0), 'M2', 'M3'), 'Via3': ((49,0), 'M3', 'M4')}
LABEL_LAYERS = {'M1': (8,25), 'M2': (10,25), 'M3': (30,25)}

layer_polys = {}
layer_regions = {}
for name, (l, d) in LAYERS.items():
    reg = get_region(l, d).merged()
    layer_polys[name] = list(reg.each())
    layer_regions[name] = reg

via_regions = {}
for vname, ((vl, vd), _, _) in VIAS.items():
    via_regions[vname] = get_region(vl, vd)

# Build label index
labels = {}
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

# Build graph
graph = {}
def add_edge(n1, n2, via_name):
    if n1 not in graph: graph[n1] = set()
    if n2 not in graph: graph[n2] = set()
    graph[n1].add((n2, via_name))
    graph[n2].add((n1, via_name))

for vname, ((vl, vd), lower, upper) in VIAS.items():
    if upper is None:
        continue
    for vshape in via_regions[vname].each():
        vc = kdb.Point((vshape.bbox().left + vshape.bbox().right) // 2,
                       (vshape.bbox().bottom + vshape.bbox().top) // 2)
        vprobe = kdb.Region(kdb.Box(vc.x - 20, vc.y - 20, vc.x + 20, vc.y + 20))
        lower_idx = -1
        for idx, poly in enumerate(layer_polys[lower]):
            if not (kdb.Region(poly) & vprobe).is_empty():
                lower_idx = idx
                break
        upper_idx = -1
        for idx, poly in enumerate(layer_polys[upper]):
            if not (kdb.Region(poly) & vprobe).is_empty():
                upper_idx = idx
                break
        if lower_idx >= 0 and upper_idx >= 0:
            add_edge((lower, lower_idx), (upper, upper_idx), vname)

# Find buf1 and vco_out nodes
buf1_nodes = []
vco_nodes = []
for (lname, idx), nets in labels.items():
    if 'buf1' in nets:
        buf1_nodes.append((lname, idx))
    if 'vco_out' in nets:
        vco_nodes.append((lname, idx))

print(f'buf1 labels: {buf1_nodes}')
print(f'vco_out labels: {vco_nodes}')

# BFS from buf1
visited = {}
queue = deque()
for bn in buf1_nodes:
    visited[bn] = None
    queue.append(bn)

vco_found = None
while queue:
    node = queue.popleft()
    if node in labels and 'vco_out' in labels[node]:
        vco_found = node
        break
    if node not in graph:
        continue
    for neighbor, via_name in graph[node]:
        if neighbor not in visited:
            visited[neighbor] = (node, via_name)
            queue.append(neighbor)

if vco_found:
    print(f'\n*** buf1 → vco_out path found! ***')
    path = []
    node = vco_found
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
        poly = layer_polys[layer_name][idx]
        bb = poly.bbox()
        lbl = labels.get(node, set())
        lbl_str = f" labels={lbl}" if lbl else ""
        print(f'  [{i}] {layer_name}#{idx} ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})'
              f'-({bb.right/1e3:.3f},{bb.top/1e3:.3f}){lbl_str}')
        if via:
            print(f'       ↑ via {via}')
else:
    print(f'\nNo path from buf1 to vco_out through metal ({len(visited)} nodes visited)')
    # Show component labels
    comp_labels = set()
    for node in visited:
        if node in labels:
            comp_labels.update(labels[node])
    print(f'Labels in buf1 component: {sorted(comp_labels)}')
    print(f'Visited by layer: {dict(sorted({n[0]: sum(1 for x in visited if x[0]==n[0]) for n in visited}.items()))}')
