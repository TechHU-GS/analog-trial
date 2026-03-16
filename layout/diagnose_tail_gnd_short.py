#!/usr/bin/env python3
"""Trace the gnd↔tail short: find the exact shape that bridges them.

Strategy: KLayout Region-based connectivity flood from the 'tail' label.
1. Find the M1 shape under the 'tail' label
2. Flood-fill through Via1→M2→Via2→M3, collecting all connected shapes
3. Check if any connected shape overlaps a 'gnd'-labeled shape or power rail
4. Report the bridging shape (layer, bbox, likely source)

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# ── Layer map ──
L = {
    'M1':   layout.layer(8, 0),
    'V1':   layout.layer(19, 0),
    'M2':   layout.layer(10, 0),
    'V2':   layout.layer(29, 0),
    'M3':   layout.layer(30, 0),
    'V3':   layout.layer(49, 0),
    'M4':   layout.layer(50, 0),
}
LBL = {
    'M1': layout.layer(8, 25),
    'M2': layout.layer(10, 25),
    'M3': layout.layer(30, 25),
}

# ── Collect all regions ──
R = {}
for name, li in L.items():
    R[name] = kdb.Region(top.begin_shapes_rec(li)).merged()
    print(f"  {name}: {R[name].count()} merged shapes")

# ── Find label positions ──
def get_labels(layer_name):
    """Return list of (net_name, x, y) for text labels."""
    result = []
    for shape in top.shapes(LBL[layer_name]).each():
        if shape.is_text():
            t = shape.text
            result.append((t.string, t.x, t.y))
    return result

# Find 'tail' label (M1)
tail_labels = [(n, x, y) for n, x, y in get_labels('M1') if n == 'tail']
if not tail_labels:
    # Also check M2
    tail_labels = [(n, x, y) for n, x, y in get_labels('M2') if n == 'tail']
    if tail_labels:
        print(f"\n'tail' label on M2 at ({tail_labels[0][1]/1e3:.3f}, {tail_labels[0][2]/1e3:.3f})")
    else:
        print("ERROR: no 'tail' label found on M1 or M2")
        sys.exit(1)
else:
    print(f"\n'tail' label on M1 at ({tail_labels[0][1]/1e3:.3f}, {tail_labels[0][2]/1e3:.3f})")

# Find 'gnd' labels (M3)
gnd_labels = [(n, x, y) for n, x, y in get_labels('M3') if n == 'gnd']
print(f"'gnd' labels on M3: {len(gnd_labels)}")
for _, x, y in gnd_labels:
    print(f"  ({x/1e3:.3f}, {y/1e3:.3f})")

# ── Step 1: Find M1 shape under 'tail' label ──
_, tx, ty = tail_labels[0]
probe_r = 50  # 50nm probe radius
tail_probe = kdb.Region(kdb.Box(tx - probe_r, ty - probe_r, tx + probe_r, ty + probe_r))

tail_m1_start = R['M1'] & tail_probe
if tail_m1_start.is_empty():
    print(f"ERROR: no M1 shape at tail label position ({tx/1e3:.3f}, {ty/1e3:.3f})")
    # Try wider probe
    tail_probe = kdb.Region(kdb.Box(tx - 500, ty - 500, tx + 500, ty + 500))
    tail_m1_start = R['M1'] & tail_probe
    if tail_m1_start.is_empty():
        print("ERROR: no M1 within 500nm of tail label either!")
        sys.exit(1)
    print(f"Found M1 within 500nm probe")

bb = tail_m1_start.bbox()
print(f"\nTail M1 seed shape: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# ── Step 2: Flood fill through layers ──
# Use iterative expansion: current_metal → find vias → next_metal → ...
# Track shapes per layer for the connected component.

def expand_via(metal_region, via_region, next_metal_region):
    """Given a set of metal shapes, find vias that touch them,
    then find next-metal shapes that touch those vias.
    Returns (touching_vias, touching_next_metal)."""
    # Vias touching current metal (overlap)
    vias = via_region & metal_region.sized(1)  # 1nm overlap tolerance
    if vias.is_empty():
        return kdb.Region(), kdb.Region()
    # Next metal touching those vias
    next_metal = next_metal_region & vias.sized(1)
    return vias, next_metal


# Start with M1 shapes connected to tail label
# First, find the FULL connected M1 region (merged polygon containing seed)
connected_m1 = kdb.Region()
for poly in R['M1'].each():
    test = kdb.Region(poly) & tail_probe
    if not test.is_empty():
        connected_m1.insert(poly)
        break

if connected_m1.is_empty():
    print("Could not find connected M1 polygon")
    sys.exit(1)

bb = connected_m1.bbox()
print(f"Tail connected M1 polygon: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
      f" size={bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

# Iterative flood fill
# collected[layer] = Region of shapes in the tail connected component
collected = {'M1': connected_m1.dup()}
layer_order = [
    ('M1', 'V1', 'M2'),
    ('M2', 'V2', 'M3'),
    ('M3', 'V3', 'M4'),
]

MAX_ITERS = 5
for iteration in range(MAX_ITERS):
    changed = False
    for metal_name, via_name, next_name in layer_order:
        if metal_name not in collected or collected[metal_name].is_empty():
            continue
        vias, next_metal = expand_via(collected[metal_name], R[via_name], R[next_name])
        if vias.is_empty():
            continue

        # Add new vias
        if via_name not in collected:
            collected[via_name] = kdb.Region()
        old_count = collected[via_name].count()
        collected[via_name] = (collected[via_name] + vias).merged()
        if collected[via_name].count() > old_count:
            changed = True

        # Add new metal shapes - but need FULL merged polygons, not just overlap
        if next_name not in collected:
            collected[next_name] = kdb.Region()
        old_count = collected[next_name].count()
        # Find full merged polygons that touch the via pads
        for poly in R[next_name].each():
            test = kdb.Region(poly) & vias.sized(10)
            if not test.is_empty():
                already = kdb.Region(poly) & collected[next_name]
                if already.is_empty():
                    collected[next_name].insert(poly)
                    changed = True

        # Also check reverse: next_metal vias back to metal
        # (e.g., M2 might connect to more M1 through other Via1)
    # Also check reverse directions (M2→V1→M1, M3→V2→M2, etc.)
    for next_name, via_name, metal_name in reversed(layer_order):
        if next_name not in collected or collected[next_name].is_empty():
            continue
        vias = R[via_name] & collected[next_name].sized(1)
        if vias.is_empty():
            continue
        if via_name not in collected:
            collected[via_name] = kdb.Region()
        old_v = collected[via_name].count()
        collected[via_name] = (collected[via_name] + vias).merged()

        if metal_name not in collected:
            collected[metal_name] = kdb.Region()
        for poly in R[metal_name].each():
            test = kdb.Region(poly) & vias.sized(10)
            if not test.is_empty():
                already = kdb.Region(poly) & collected[metal_name]
                if already.is_empty():
                    collected[metal_name].insert(poly)
                    changed = True

    if not changed:
        print(f"\nFlood fill converged after {iteration + 1} iterations")
        break
else:
    print(f"\nFlood fill did NOT converge after {MAX_ITERS} iterations")

# Summary of collected shapes
print("\n=== Tail Connected Component ===")
for name in ('M1', 'V1', 'M2', 'V2', 'M3', 'V3', 'M4'):
    if name in collected and not collected[name].is_empty():
        print(f"  {name}: {collected[name].count()} shapes")
        for poly in collected[name].each():
            bb = poly.bbox()
            print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                  f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
                  f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

# ── Step 3: Check overlap with gnd ──
# Find gnd connected component: start from gnd M3 labels
print("\n=== Checking overlap with GND ===")

# Method 1: Check if any collected M3 shape overlaps a gnd-labeled M3 rail
with open('output/routing_optimized.json') as f:
    routing = json.load(f)

rails = routing.get('power', {}).get('rails', {})
M3_HW = 100  # M3 rail half-width (assumed 200nm total)

for rail_id, rail in rails.items():
    net = rail.get('net', rail_id)
    if net != 'gnd':
        continue
    ry = rail['y']
    rx1 = rail['x1']
    rx2 = rail['x2']
    rail_region = kdb.Region(kdb.Box(rx1, ry - M3_HW, rx2, ry + M3_HW))

    for layer_name in ('M1', 'M2', 'M3', 'M4'):
        if layer_name not in collected:
            continue
        overlap = collected[layer_name] & rail_region
        if not overlap.is_empty():
            print(f"  *** OVERLAP: tail {layer_name} touches {rail_id} (gnd)"
                  f" at y={ry/1e3:.3f}µm")
            for poly in overlap.each():
                bb = poly.bbox()
                print(f"      overlap: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Method 2: Direct region overlap check (all gnd M3 vs all tail shapes)
# Build gnd M3 region from labels
gnd_m3_seed = kdb.Region()
for _, gx, gy in gnd_labels:
    for poly in R['M3'].each():
        test = kdb.Region(poly) & kdb.Region(kdb.Box(gx - 50, gy - 50, gx + 50, gy + 50))
        if not test.is_empty():
            gnd_m3_seed.insert(poly)

print(f"\nGND M3 seed shapes: {gnd_m3_seed.count()}")

# Check each layer of tail component against M3 gnd
# But the real bridge might be through a drop/vbar on a different layer
# Let's check if any tail shape on ANY layer directly overlaps any gnd shape on SAME layer

# More thorough: check if tail M1 region overlaps gnd M1 region
# First need to find gnd connected shapes on M1
# This is expensive, so let's just check direct overlaps

# Check: do any collected shapes have a 'gnd' label on them?
for lbl_layer_name, lbl_li in LBL.items():
    metal_name = lbl_layer_name
    if metal_name not in collected:
        continue
    for shape in top.shapes(lbl_li).each():
        if not shape.is_text():
            continue
        t = shape.text
        if t.string != 'gnd':
            continue
        gnd_probe = kdb.Region(kdb.Box(t.x - 50, t.y - 50, t.x + 50, t.y + 50))
        overlap = collected[metal_name] & gnd_probe
        if not overlap.is_empty():
            print(f"\n  *** DIRECT HIT: tail's {metal_name} component contains"
                  f" 'gnd' label at ({t.x/1e3:.3f}, {t.y/1e3:.3f})!")

# ── Step 4: Trace the bridge path ──
# If we found overlap on M3, trace back: which M2 via connects to it?
# If on M1, trace up.
print("\n=== Bridge Path Trace ===")

# Check each collected shape against the FULL gnd region
# The key insight: if tail's connected component reaches a gnd M3 rail,
# the bridge is wherever the tail component jumps from M1→M2→M3.
# List all via positions in the tail component.
if 'V1' in collected:
    print("\nVia1 positions in tail component:")
    for poly in collected['V1'].each():
        bb = poly.bbox()
        cx, cy = (bb.left + bb.right) // 2, (bb.bottom + bb.top) // 2
        print(f"  Via1 at ({cx/1e3:.3f}, {cy/1e3:.3f})"
              f" box=({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

if 'V2' in collected:
    print("\nVia2 positions in tail component:")
    for poly in collected['V2'].each():
        bb = poly.bbox()
        cx, cy = (bb.left + bb.right) // 2, (bb.bottom + bb.top) // 2
        print(f"  Via2 at ({cx/1e3:.3f}, {cy/1e3:.3f})"
              f" box=({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# For each M2 shape in tail component, check if it also overlaps a gnd-connected shape
# Actually, the simplest diagnostic: list ALL shapes in the tail component
# and let us visually identify what's a device shape vs routing vs power
print("\n=== All M2 shapes in tail component ===")
if 'M2' in collected:
    for poly in collected['M2'].each():
        bb = poly.bbox()
        print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

print("\n=== All M3 shapes in tail component ===")
if 'M3' in collected:
    for poly in collected['M3'].each():
        bb = poly.bbox()
        print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")
