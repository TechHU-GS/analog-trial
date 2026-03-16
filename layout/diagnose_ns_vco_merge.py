#!/usr/bin/env python3
"""Diagnose ns|vco merge: find conductive path between Mpu S and D.

For each VCO stage (1-5):
- Mpu.S = ns_x (current source node)
- Mpu.D = vco_x (inverter output)
- Merge means extractor sees conductive path from S to D

Strategy: Load GDS, find ALL shapes near Mpu S and D APs,
trace connectivity layer by layer.
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

LAYERS = {
    'Cont': (6, 0),
    'M1': (8, 0),
    'Via1': (19, 0),
    'M2': (10, 0),
    'Via2': (29, 0),
    'M3': (30, 0),
}
li = {name: layout.layer(*gds) for name, gds in LAYERS.items()}

with open('output/routing.json') as f:
    routing = json.load(f)
aps = routing.get('access_points', {})

with open('placement.json') as f:
    placement = json.load(f)


def get_shapes_in_region(layer_name, x1, y1, x2, y2):
    """Get all shapes on layer within bounding box, from top cell + instances."""
    layer_idx = li[layer_name]
    results = []
    region = kdb.Box(x1, y1, x2, y2)
    # Top cell shapes
    for si in top.shapes(layer_idx).each():
        bb = si.bbox()
        if bb.overlaps(region) or region.overlaps(bb):
            results.append(('top', bb))
    # Instance shapes
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(layer_idx).each():
            bb = si.bbox().transformed(inst.trans)
            if bb.overlaps(region) or region.overlaps(bb):
                results.append((inst.cell.name, bb))
    return results


def shapes_touch(a, b, margin=5):
    """Check if two boxes touch or overlap (within margin in nm)."""
    xa = max(a.left - b.right, b.left - a.right)
    ya = max(a.bottom - b.top, b.bottom - a.top)
    return xa <= margin and ya <= margin


def find_connected_component(seed_shapes, all_shapes, margin=5):
    """BFS: find all shapes connected to any seed shape."""
    visited = set()
    queue = []
    for i, s in enumerate(all_shapes):
        for seed in seed_shapes:
            if shapes_touch(s, seed, margin):
                if i not in visited:
                    visited.add(i)
                    queue.append(i)
                break
    while queue:
        idx = queue.pop(0)
        current = all_shapes[idx]
        for j, other in enumerate(all_shapes):
            if j not in visited and shapes_touch(current, other, margin):
                visited.add(j)
                queue.append(j)
    return visited


print("=" * 70)
print("DIAGNOSE ns|vco MERGE: M2 shapes near Mpu S/D access points")
print("=" * 70)

for stage in [1, 2, 3, 4, 5]:
    s_pin = f'Mpu{stage}.S'
    d_pin = f'Mpu{stage}.D'
    s_ap = aps.get(s_pin)
    d_ap = aps.get(d_pin)
    if not s_ap or not d_ap:
        print(f"\nStage {stage}: AP not found for {s_pin} or {d_pin}")
        continue

    sx, sy = s_ap['x'], s_ap['y']
    dx, dy = d_ap['x'], d_ap['y']

    print(f"\n{'='*70}")
    print(f"Stage {stage}: {s_pin}=ns{stage} ({sx},{sy}), {d_pin}=vco{stage} ({dx},{dy})")
    print(f"  S-D distance: {abs(dx-sx)}nm X, {abs(dy-sy)}nm Y")

    # Get Mpu and Mpb placement
    mpu_key = f'Mpu{stage}'
    mpb_key = f'Mpb{stage}'
    mpu_pl = placement.get(mpu_key, {})
    mpb_pl = placement.get(mpb_key, {})
    if mpu_pl:
        print(f"  {mpu_key}: x={mpu_pl.get('x_um')}, y={mpu_pl.get('y_um')}, "
              f"w={mpu_pl.get('w_um')}, h={mpu_pl.get('h_um')}")
    if mpb_pl:
        print(f"  {mpb_key}: x={mpb_pl.get('x_um')}, y={mpb_pl.get('y_um')}, "
              f"w={mpb_pl.get('w_um')}, h={mpb_pl.get('h_um')}")

    # Search region: around both S and D APs with generous margin
    margin = 2000  # 2um
    rx1 = min(sx, dx) - margin
    ry1 = min(sy, dy) - margin
    rx2 = max(sx, dx) + margin
    ry2 = max(sy, dy) + margin

    # Find all M2 shapes in region
    m2_shapes = get_shapes_in_region('M2', rx1, ry1, rx2, ry2)
    print(f"\n  M2 shapes within {margin}nm of S/D APs: {len(m2_shapes)}")

    # For each M2 shape, check proximity to S and D
    s_box = kdb.Box(sx - 240, sy - 240, sx + 240, sy + 240)  # VIA1_PAD/2
    d_box = kdb.Box(dx - 240, dy - 240, dx + 240, dy + 240)

    for i, (src, bb) in enumerate(m2_shapes):
        near_s = shapes_touch(bb, s_box, margin=50)
        near_d = shapes_touch(bb, d_box, margin=50)
        tag = ""
        if near_s: tag += " ←S(ns)"
        if near_d: tag += " ←D(vco)"
        if near_s and near_d: tag += " ***BRIDGES S-D!***"

        # Classify by size
        w, h = bb.width(), bb.height()
        size_tag = ""
        if w > 1000 or h > 1000:
            size_tag = " [LARGE]"
        elif w == h:
            size_tag = " [SQUARE/pad]"

        if tag or True:  # Show all M2 shapes
            print(f"    [{i}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{w}x{h}{size_tag}{tag}")

    # Check Via1 shapes in region — these connect M1↔M2
    via1_shapes = get_shapes_in_region('Via1', rx1, ry1, rx2, ry2)
    print(f"\n  Via1 shapes in region: {len(via1_shapes)}")
    for i, (src, bb) in enumerate(via1_shapes):
        near_s = shapes_touch(bb, s_box, margin=100)
        near_d = shapes_touch(bb, d_box, margin=100)
        tag = ""
        if near_s: tag += " ←S(ns)"
        if near_d: tag += " ←D(vco)"
        if tag:
            print(f"    [{i}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()}{tag}")

    # M1 shapes in tighter region (near S and D only)
    m1_s_shapes = get_shapes_in_region('M1', sx-500, sy-500, sx+500, sy+500)
    m1_d_shapes = get_shapes_in_region('M1', dx-500, dy-500, dx+500, dy+500)
    print(f"\n  M1 shapes near S AP: {len(m1_s_shapes)}")
    for i, (src, bb) in enumerate(m1_s_shapes):
        print(f"    [{i}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()}")
    print(f"  M1 shapes near D AP: {len(m1_d_shapes)}")
    for i, (src, bb) in enumerate(m1_d_shapes):
        print(f"    [{i}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()}")

    # === M2 CONNECTIVITY ANALYSIS ===
    # Get ALL M2 shapes as flat list for BFS
    all_m2 = [bb for _, bb in m2_shapes]
    if not all_m2:
        print("\n  No M2 shapes found — short must be on M1")
        continue

    # BFS from S AP M2 shapes
    s_connected = find_connected_component([s_box], all_m2)
    d_connected = find_connected_component([d_box], all_m2)

    overlap = s_connected & d_connected
    if overlap:
        print(f"\n  *** M2 SHORT FOUND: {len(overlap)} shapes connect S and D ***")
        for idx in sorted(overlap):
            src, bb = m2_shapes[idx]
            print(f"    [{idx}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()}")
    else:
        print(f"\n  No M2 short found (S reaches {len(s_connected)}, D reaches {len(d_connected)} shapes)")

    # === CHECK M1 CONNECTIVITY (S to D on M1) ===
    m1_all = get_shapes_in_region('M1', rx1, ry1, rx2, ry2)
    all_m1_boxes = [bb for _, bb in m1_all]
    s_m1_connected = find_connected_component([s_box], all_m1_boxes)
    d_m1_connected = find_connected_component([d_box], all_m1_boxes)
    m1_overlap = s_m1_connected & d_m1_connected
    if m1_overlap:
        print(f"\n  *** M1 SHORT FOUND: {len(m1_overlap)} shapes connect S and D ***")
        for idx in sorted(m1_overlap):
            src, bb = m1_all[idx]
            print(f"    [{idx}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()}")
    else:
        print(f"  No M1 short found (S reaches {len(s_m1_connected)}, D reaches {len(d_m1_connected)} shapes)")

    # === CROSS-LAYER CONNECTIVITY ===
    # Check if an M2 shape connected to S also connects (via Via1) to M1 connected to D
    print(f"\n  Cross-layer check (M2 from S ↔ Via1 ↔ M1 from D):")
    s_m2_boxes = [all_m2[i] for i in s_connected]
    d_m1_boxes = [all_m1_boxes[i] for i in d_m1_connected]
    via1_all = [bb for _, bb in via1_shapes]

    for vi, vbox in enumerate(via1_all):
        # Does this Via1 touch any M2 from S?
        touches_s_m2 = any(shapes_touch(vbox, m2b) for m2b in s_m2_boxes)
        # Does this Via1 touch any M1 from D?
        touches_d_m1 = any(shapes_touch(vbox, m1b) for m1b in d_m1_boxes)
        if touches_s_m2 and touches_d_m1:
            src, bb = via1_shapes[vi]
            print(f"    *** CROSS-LAYER SHORT via Via1 [{vi}] {src}: "
                  f"({bb.left},{bb.bottom};{bb.right},{bb.top}) ***")
            print(f"        M2(S/ns) → Via1 → M1(D/vco) path exists!")

    # Also check reverse: M2 from D ↔ Via1 ↔ M1 from S
    d_m2_boxes = [all_m2[i] for i in d_connected]
    s_m1_boxes = [all_m1_boxes[i] for i in s_m1_connected]
    for vi, vbox in enumerate(via1_all):
        touches_d_m2 = any(shapes_touch(vbox, m2b) for m2b in d_m2_boxes)
        touches_s_m1 = any(shapes_touch(vbox, m1b) for m1b in s_m1_boxes)
        if touches_d_m2 and touches_s_m1:
            src, bb = via1_shapes[vi]
            print(f"    *** CROSS-LAYER SHORT via Via1 [{vi}] {src}: "
                  f"({bb.left},{bb.bottom};{bb.right},{bb.top}) ***")
            print(f"        M2(D/vco) → Via1 → M1(S/ns) path exists!")


# === ALSO CHECK vco_out|vdd ===
print(f"\n{'='*70}")
print("vco_out|vdd merge analysis")
print(f"{'='*70}")
# vco_out is the output of the last VCO stage
# Check routing for vco_out
vco_out_route = routing.get('signal_routes', {}).get('vco_out', {})
if vco_out_route:
    print(f"vco_out route: {len(vco_out_route.get('wires', []))} wires, "
          f"{len(vco_out_route.get('vertices', []))} vertices")
    for w in vco_out_route.get('wires', []):
        print(f"  wire: layer={w.get('layer')}, ({w.get('x1')},{w.get('y1')})->({w.get('x2')},{w.get('y2')})")
    for pk in vco_out_route.get('pins', []):
        ap = aps.get(pk)
        if ap:
            print(f"  pin: {pk} ({ap['x']},{ap['y']})")

# Get M3 power shapes near vco_out pins to check for vbar/rail collisions
vco_out_pins = vco_out_route.get('pins', [])
for pk in vco_out_pins:
    ap = aps.get(pk)
    if not ap:
        continue
    ax, ay = ap['x'], ap['y']
    m3_near = get_shapes_in_region('M3', ax - 2000, ay - 2000, ax + 2000, ay + 2000)
    print(f"\n  M3 shapes near {pk} ({ax},{ay}): {len(m3_near)}")
    for i, (src, bb) in enumerate(m3_near):
        print(f"    [{i}] {src}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()}")

print("\nDone.")
