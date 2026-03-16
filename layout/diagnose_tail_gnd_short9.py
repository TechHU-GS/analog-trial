#!/usr/bin/env python3
"""Phase 9: Identify devices on M1#611 and check if M1 merge is the cause.

The short path:
  tail M1#610 → Via1 → M2#473 → Via1 → M1#611 → Via1 → M2#565(480x480) → Via2 → M3#1(gnd)

Hypothesis: M1#611 merges contacts from TWO different nets:
  - Mtail source (should be gnd) — the x=50.380 column
  - Min_n/Min_p source (should be tail) — the x=46.620/51.380/56.140 columns
This creates a gnd↔tail short through the merged M1.

This script:
1. Examines M1#611 shape to find where tail-M1 and gnd-M1 sub-shapes meet
2. Cross-references placement data to identify which device is at each position
3. Checks if un-merged M1 has separate polygons that shouldn't be merged

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short9.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

def get_region(layer, dt):
    li = layout.layer(layer, dt)
    return kdb.Region(top.begin_shapes_rec(li))

# ── Un-merged M1 — see individual shapes that compose M1#611 ──
m1_raw = get_region(8, 0)  # NOT merged
m1_merged = m1_raw.merged()
m1_polys = list(m1_merged.each())

m1_611 = m1_polys[611]
m1_611_r = kdb.Region(m1_611)
bb611 = m1_611.bbox()

print("="*60)
print("Un-merged M1 shapes within M1#611 bbox")
print("="*60)

# Find raw M1 shapes that overlap M1#611
raw_in_611 = m1_raw & m1_611_r
raw_shapes = list(raw_in_611.each())
print(f"Raw M1 shapes in M1#611 region: {len(raw_shapes)}")

# Sort by position for readability
raw_shapes.sort(key=lambda p: (p.bbox().left, p.bbox().bottom))

for i, shape in enumerate(raw_shapes):
    bb = shape.bbox()
    area = shape.area() / 1e6
    print(f"  raw#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
          f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
          f" {bb.width()/1e3:.3f}x{bb.height()/1e3:.3f} area={area:.4f}µm²")

# ── Check which raw shapes are near the bridge Via1 at (50.380, 72.680) ──
print(f"\n{'='*60}")
print("Raw M1 shapes near bridge Via1 (50.380, 72.680)")
print("="*60)

bridge_probe = kdb.Region(kdb.Box(50350, 72650, 50410, 72710))
for i, shape in enumerate(raw_shapes):
    if not (kdb.Region(shape) & bridge_probe).is_empty():
        bb = shape.bbox()
        print(f"  raw#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) *** BRIDGE SHAPE ***")

# ── Check which raw shapes are near the tail Via1 entry points ──
print(f"\n{'='*60}")
print("Raw M1 shapes near tail Via1 entries")
print("="*60)

# Via1 connecting M1#611 to M2#473 (tail bridge) at (46.620, 76.130)
tail_v1_probe = kdb.Region(kdb.Box(46590, 76100, 46650, 76160))
for i, shape in enumerate(raw_shapes):
    if not (kdb.Region(shape) & tail_v1_probe).is_empty():
        bb = shape.bbox()
        print(f"  raw#{i} near Via1(46.620,76.130): ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) *** TAIL ENTRY ***")

# ── Now find the MERGE POINT: which raw shapes bridge the gnd and tail sub-regions? ──
# We'll do a mini connectivity analysis on the raw shapes
print(f"\n{'='*60}")
print("Mini connectivity: how raw shapes merge")
print("="*60)

# Two key positions:
# A = bridge Via1 position (50.380, 72.680) — connects to gnd
# B = tail Via1 position (46.620, 76.130) — connects from tail

# Find raw shape containing A
a_idx = -1
b_idx = -1
for i, shape in enumerate(raw_shapes):
    if not (kdb.Region(shape) & bridge_probe).is_empty():
        a_idx = i
    if not (kdb.Region(shape) & tail_v1_probe).is_empty():
        b_idx = i

print(f"Shape at gnd bridge: raw#{a_idx}")
print(f"Shape at tail entry: raw#{b_idx}")

if a_idx == b_idx and a_idx >= 0:
    bb = raw_shapes[a_idx].bbox()
    print(f"*** SAME RAW SHAPE! raw#{a_idx} ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
          f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) ***")
    print("The short is WITHIN a single M1 shape, not from merging!")
else:
    print(f"Different shapes — merge is the issue")
    # BFS on raw shapes to find path from A to B
    # Two raw shapes are neighbors if they overlap (touch/intersect)
    print("\nBuilding raw shape adjacency...")
    adj = {i: set() for i in range(len(raw_shapes))}
    for i in range(len(raw_shapes)):
        for j in range(i+1, len(raw_shapes)):
            ri = kdb.Region(raw_shapes[i])
            rj = kdb.Region(raw_shapes[j])
            # Check if they touch (overlap when sized slightly)
            if not (ri.sized(5) & rj.sized(5)).is_empty():
                adj[i].add(j)
                adj[j].add(i)

    # BFS from a_idx to b_idx
    from collections import deque
    visited = {a_idx: None}
    queue = deque([a_idx])
    while queue:
        node = queue.popleft()
        if node == b_idx:
            break
        for n in adj[node]:
            if n not in visited:
                visited[n] = node
                queue.append(n)

    if b_idx in visited:
        # Trace path
        path = []
        node = b_idx
        while node is not None:
            path.append(node)
            node = visited[node]
        path.reverse()
        print(f"\nMerge path (raw shapes A→B): {path}")
        for p_idx in path:
            bb = raw_shapes[p_idx].bbox()
            print(f"  raw#{p_idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                  f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
                  f" {bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
    else:
        print("No path found between A and B in raw shapes!")

# ── Load placement data to identify devices ──
print(f"\n{'='*60}")
print("Device identification from placement")
print("="*60)

# Load placement
try:
    with open('output/placement_optimized.json') as f:
        placement = json.load(f)
except FileNotFoundError:
    placement = None

if placement:
    devices = placement.get('devices', {})
    # Find devices whose placement overlaps M1#611 bbox
    for dev_name, dev_data in devices.items():
        dx = dev_data.get('x', 0)
        dy = dev_data.get('y', 0)
        # Check if device center is within M1#611 bbox (with margin)
        if bb611.left - 2000 <= dx <= bb611.right + 2000 and \
           bb611.bottom - 2000 <= dy <= bb611.top + 2000:
            dev_type = dev_data.get('type', '?')
            mirror = dev_data.get('mirror', '?')
            print(f"  {dev_name}: type={dev_type} pos=({dx/1e3:.3f},{dy/1e3:.3f}) mirror={mirror}")
            # Show pin positions
            pins = dev_data.get('pins', {})
            for pin_name, pin_data in pins.items():
                if isinstance(pin_data, dict):
                    px, py = pin_data.get('x', dx), pin_data.get('y', dy)
                    print(f"    {pin_name}: ({px/1e3:.3f},{py/1e3:.3f})")

# ── Also check: what is the source of M2#565? Search assemble_gds code paths ──
print(f"\n{'='*60}")
print("Via1 and Via2 sources at bridge position (50.380, 72.680)")
print("="*60)

# Check if there's a power drop in the raw power data (not just routing_optimized)
# Power drops create Via1+M2+Via2 stacks
try:
    with open('output/routing_optimized.json') as f:
        routing = json.load(f)

    # Check vbar positions
    power = routing.get('power', {})
    vbars = power.get('vbars', [])
    print(f"\nVbars near x=50.380:")
    for vb in vbars:
        vx = vb.get('x', 0)
        net = vb.get('net', '?')
        if abs(vx - 50380) < 2000:
            print(f"  net={net} x={vx/1e3:.3f}")

    # Check M3 rail positions
    rails = power.get('rails', [])
    print(f"\nM3 rails near y=72.680:")
    for rail in rails:
        ry = rail.get('y', 0)
        net = rail.get('net', '?')
        if abs(ry - 72680) < 5000:
            print(f"  net={net} y={ry/1e3:.3f} "
                  f"range=({rail.get('y_min',0)/1e3:.3f},{rail.get('y_max',0)/1e3:.3f})")

    # Check if any drops are near this position (wider search)
    print(f"\nAll power drops within 5µm:")
    for drop in power.get('drops', []):
        dx, dy = drop.get('x', 0), drop.get('y', 0)
        if abs(dx - 50380) < 5000 and abs(dy - 72680) < 5000:
            print(f"  net={drop.get('net','?')} pos=({dx/1e3:.3f},{dy/1e3:.3f})"
                  f" dist=({abs(dx-50380)/1e3:.3f},{abs(dy-72680)/1e3:.3f})")

except Exception as e:
    print(f"Error loading routing data: {e}")

# ── Dump M1#611 outline points for visualization ──
print(f"\n{'='*60}")
print("M1#611 polygon vertices (56 points)")
print("="*60)
for pt in m1_611.each_point_hull():
    print(f"  ({pt.x/1e3:.3f}, {pt.y/1e3:.3f})")
