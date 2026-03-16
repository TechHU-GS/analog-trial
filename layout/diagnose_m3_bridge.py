#!/usr/bin/env python3
"""Check M3 bus bridge shapes for cross-net conflicts."""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m3 = layout.layer(30, 0)
li_m2 = layout.layer(10, 0)
li_v2 = layout.layer(29, 0)
li_v1 = layout.layer(19, 0)
li_m1 = layout.layer(8, 0)

with open('output/routing.json') as f:
    routing = json.load(f)
aps = routing.get('access_points', {})

# Get all M3 shapes from top cell (not instances)
def get_top_m3():
    shapes = []
    for si in top.shapes(li_m3).each():
        shapes.append(si.bbox())
    return shapes

def get_shapes_near(layer_idx, cx, cy, margin=2000):
    results = []
    region = kdb.Box(cx - margin, cy - margin, cx + margin, cy + margin)
    for si in top.shapes(layer_idx).each():
        bb = si.bbox()
        if bb.overlaps(region) or region.overlaps(bb):
            results.append(bb)
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(layer_idx).each():
            bb = si.bbox().transformed(inst.trans)
            if bb.overlaps(region) or region.overlaps(bb):
                results.append(bb)
    return results

# Check M3 shapes near each Mpu S/D position
for stage in [1, 2, 3, 4, 5]:
    s_ap = aps.get(f'Mpu{stage}.S')
    d_ap = aps.get(f'Mpu{stage}.D')
    if not s_ap or not d_ap:
        continue
    sx, sy = s_ap['x'], s_ap['y']
    dx, dy = d_ap['x'], d_ap['y']
    bus_cy = sy  # approx

    print(f"\n{'='*70}")
    print(f"Stage {stage}: S=({sx},{sy}), D=({dx},{dy})")

    # M3 shapes in the bridge area
    m3_near = get_shapes_near(li_m3, (sx+dx)//2, bus_cy, margin=3000)
    print(f"  M3 shapes near bus area: {len(m3_near)}")
    for i, bb in enumerate(m3_near):
        # Check if it's a VIA2 pad (square ~380x380) or a wire
        w, h = bb.width(), bb.height()
        tag = ""
        if 370 <= w <= 400 and 370 <= h <= 400:
            tag = " [Via2 pad]"
        elif w < 250 and h > 1000:
            tag = " [M3 vbar]"
        elif h < 350 and w > 500:
            tag = f" [M3 hbar/wire]"
        elif w > 1000 and h > 1000:
            tag = " [M3 power rail]"
        print(f"    [{i}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{w}x{h}{tag}")

    # Via2 shapes near bus
    v2_near = get_shapes_near(li_v2, (sx+dx)//2, bus_cy, margin=3000)
    print(f"  Via2 shapes near bus area: {len(v2_near)}")
    for i, bb in enumerate(v2_near):
        print(f"    [{i}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()}")

    # Check: is there an M3 shape that touches BOTH:
    # (a) the bus bridge M3 hbar area (roughly d1_cx..d2_cx at bus_cy)
    # (b) any M3 shape near the vco AP
    # First find bus M3 hbar candidates (horizontal, near bus_cy)
    bus_m3_hbars = []
    for bb in m3_near:
        w, h = bb.width(), bb.height()
        # Bus M3 bridge: wide horizontal bar, height ~300nm, near bus_cy
        if w > 2000 and h < 400 and abs((bb.bottom + bb.top)//2 - bus_cy) < 500:
            bus_m3_hbars.append(bb)
    if bus_m3_hbars:
        print(f"\n  *** Found {len(bus_m3_hbars)} bus M3 bridge hbar(s): ***")
        for bb in bus_m3_hbars:
            print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) {bb.width()}x{bb.height()}")
            # Check if any other M3 shape touches this hbar
            for other in m3_near:
                if other == bb:
                    continue
                xa = max(bb.left - other.right, other.left - bb.right)
                ya = max(bb.bottom - other.top, other.bottom - bb.top)
                if xa <= 5 and ya <= 5:  # touching
                    print(f"      TOUCHES: ({other.left},{other.bottom};{other.right},{other.top}) "
                          f"{other.width()}x{other.height()}")

print("\nDone.")
