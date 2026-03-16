#!/usr/bin/env python3
"""Find Via2 cuts inside VDD M3 rails that connect to non-VDD M2 shapes.

These are the bridge points where a non-VDD via on the VDD M3 rail
creates a gnd↔vdd merger.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_via2_on_vdd_rail.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)
li_v2 = layout.layer(29, 0)

with open('output/routing.json') as f:
    routing = json.load(f)

rails = routing.get('power', {}).get('rails', {})

# Build VDD and GND rail boxes (expanded slightly for via pad overlap)
VIA2_PAD_M3 = 380
hp = VIA2_PAD_M3 // 2  # 190

vdd_rail_boxes = []
for rn, rl in rails.items():
    net = rl.get('net', rn)
    if net != 'vdd':
        continue
    rh = rl['width'] // 2
    ry1 = rl['y'] - rh
    ry2 = rl['y'] + rh
    vdd_rail_boxes.append((rn, ry1, ry2))

# Get known VDD Via2 positions from power drops
vdd_via2_set = set()
for drop in routing.get('power', {}).get('drops', []):
    if drop['net'] == 'vdd' and 'via2_pos' in drop:
        v2 = drop['via2_pos']
        vdd_via2_set.add((v2[0], v2[1]))

# Get ALL Via2 cuts
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))
m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m2_polys = list(m2_merged.each())

print(f"Total Via2 cuts: {v2_all.count()}")
print(f"Known VDD Via2 positions: {len(vdd_via2_set)}")

# For each VDD rail, find Via2 cuts inside the rail Y band
for rn, ry1, ry2 in vdd_rail_boxes:
    rail_region = kdb.Region(kdb.Box(0, ry1, 200000, ry2))
    v2_in_rail = v2_all & rail_region
    print(f"\n{'='*70}")
    print(f"VDD rail {rn}: y=[{ry1/1e3:.3f},{ry2/1e3:.3f}]  Via2 inside: {v2_in_rail.count()}")
    print(f"{'='*70}")

    for v2 in v2_in_rail.each():
        v2b = v2.bbox()
        cx = (v2b.left + v2b.right) // 2
        cy = (v2b.top + v2b.bottom) // 2

        # Check if this is a known VDD Via2
        is_vdd = (cx, cy) in vdd_via2_set
        # Also check nearby positions (within 100nm)
        if not is_vdd:
            for vx, vy in vdd_via2_set:
                if abs(vx - cx) < 100 and abs(vy - cy) < 100:
                    is_vdd = True
                    break

        if is_vdd:
            continue  # Skip known VDD vias

        # This Via2 is inside a VDD rail but NOT a known VDD via
        # Find which M2 polygon it connects to
        v2_center = kdb.Box(v2b.left + 20, v2b.bottom + 20,
                           v2b.right - 20, v2b.top - 20)
        v2_probe = kdb.Region(v2_center)

        m2_desc = "unknown"
        for m2p in m2_polys:
            m2r = kdb.Region(m2p)
            if not (m2r & v2_probe).is_empty():
                m2b = m2p.bbox()
                m2_area = m2p.area() / 1e6
                m2_desc = (f"M2 ({m2b.left/1e3:.3f},{m2b.bottom/1e3:.3f})-"
                          f"({m2b.right/1e3:.3f},{m2b.top/1e3:.3f}) "
                          f"area={m2_area:.2f}µm²")
                break

        print(f"  NON-VDD Via2 at ({cx/1e3:.3f},{cy/1e3:.3f})  → {m2_desc}")

# Also check: signal route Via2 positions that fall inside VDD rails
print(f"\n{'='*70}")
print("Signal route Via2 in VDD rail Y bands")
print(f"{'='*70}")

for sn, sr in routing.get('signal_routes', {}).items():
    for seg in sr.get('segments', []):
        if len(seg) < 5:
            continue
        x1, y1, x2, y2, slyr = seg[:5]
        if slyr != -2:  # Not via2
            continue
        for rn, ry1, ry2 in vdd_rail_boxes:
            if ry1 <= y1 <= ry2:
                print(f"  Signal {sn}: Via2 at ({x1/1e3:.3f},{y1/1e3:.3f}) "
                      f"in VDD rail {rn} [{ry1/1e3:.3f},{ry2/1e3:.3f}]")

# Check power drops: GND drops with Via2 inside VDD rail Y bands
print(f"\n{'='*70}")
print("GND power drop Via2 in VDD rail Y bands")
print(f"{'='*70}")

for drop in routing.get('power', {}).get('drops', []):
    if drop['net'] != 'gnd' or 'via2_pos' not in drop:
        continue
    v2 = drop['via2_pos']
    for rn, ry1, ry2 in vdd_rail_boxes:
        if ry1 <= v2[1] <= ry2:
            print(f"  GND drop {drop['inst']}.{drop['pin']}: Via2 at "
                  f"({v2[0]/1e3:.3f},{v2[1]/1e3:.3f}) in VDD rail {rn}")

print("\n\nDONE.")
