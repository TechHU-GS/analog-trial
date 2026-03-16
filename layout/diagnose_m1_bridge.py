#!/usr/bin/env python3
"""Find M1 merged polygons that bridge VDD and GND through Via1→M2→Via2→M3.

For each M1 merged polygon, check if it connects (via Via1) to M2 polygons
that reach (via Via2) BOTH VDD-net and GND-net M3 rails.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_bridge.py
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
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)

print("Merging layers...")
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
v1_all = kdb.Region(top.begin_shapes_rec(li_v1))
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))

m1_polys = list(m1_merged.each())
m2_polys = list(m2_merged.each())
m3_polys = list(m3_merged.each())

print(f"M1: {len(m1_polys)}, M2: {len(m2_polys)}, M3: {len(m3_polys)}")

# Load rail info
with open('output/routing.json') as f:
    routing = json.load(f)

rails = routing.get('power', {}).get('rails', {})
vdd_bands = []
gnd_bands = []
for rn, rl in rails.items():
    net = rl.get('net', rn)
    rh = rl['width'] // 2
    ry1 = rl['y'] - rh
    ry2 = rl['y'] + rh
    if net == 'vdd':
        vdd_bands.append((ry1, ry2, rn))
    else:
        gnd_bands.append((ry1, ry2, rn))

print(f"VDD bands: {[(b[2], b[0]/1e3, b[1]/1e3) for b in vdd_bands]}")
print(f"GND bands: {[(b[2], b[0]/1e3, b[1]/1e3) for b in gnd_bands]}")

# Step 1: classify M3 merged polygons as VDD, GND, signal, or both
m3_net = {}  # index -> set of nets
for i, m3p in enumerate(m3_polys):
    bb = m3p.bbox()
    w = bb.right - bb.left
    if w < 50000:  # skip small signal M3
        continue
    nets = set()
    for ry1, ry2, rn in vdd_bands:
        if bb.bottom < ry2 and bb.top > ry1:
            nets.add('vdd')
    for ry1, ry2, rn in gnd_bands:
        if bb.bottom < ry2 and bb.top > ry1:
            nets.add('gnd')
    if nets:
        m3_net[i] = nets

# Step 2: classify M2 merged polygons by which M3 net they reach via Via2
print("\nClassifying M2 polygons by Via2→M3 net connectivity...")
m2_net = {}  # m2_index -> set of nets
for m2_idx, m2p in enumerate(m2_polys):
    m2r = kdb.Region(m2p)
    v2_on = v2_all & m2r
    if v2_on.count() == 0:
        continue

    nets = set()
    for v2 in v2_on.each():
        v2b = v2.bbox()
        cx = (v2b.left + v2b.right) // 2
        cy = (v2b.top + v2b.bottom) // 2
        probe = kdb.Region(kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50))
        for m3_idx, m3p in enumerate(m3_polys):
            if m3_idx not in m3_net:
                continue
            m3r = kdb.Region(m3p)
            if not (m3r & probe).is_empty():
                nets.update(m3_net[m3_idx])
                break
    if nets:
        m2_net[m2_idx] = nets

# Check M2-level bridges first
m2_bridges = [(i, m2_net[i]) for i in m2_net if 'vdd' in m2_net[i] and 'gnd' in m2_net[i]]
print(f"\nM2-level bridges (Via2 to both VDD & GND M3): {len(m2_bridges)}")
for m2_idx, nets in m2_bridges:
    bb = m2_polys[m2_idx].bbox()
    print(f"  M2#{m2_idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Step 3: For each M1 merged polygon, check Via1→M2 connectivity
print("\nChecking M1 polygons for Via1→M2 bridge to VDD+GND...")
m1_bridges = []
for m1_idx, m1p in enumerate(m1_polys):
    m1r = kdb.Region(m1p)
    v1_on = v1_all & m1r
    if v1_on.count() < 2:
        continue

    # Find which M2 polys this M1 connects to
    connected_m2_nets = set()
    connected_m2_detail = []
    for v1 in v1_on.each():
        v1b = v1.bbox()
        cx = (v1b.left + v1b.right) // 2
        cy = (v1b.top + v1b.bottom) // 2
        probe = kdb.Region(kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50))
        for m2_idx, m2p in enumerate(m2_polys):
            if m2_idx not in m2_net:
                continue
            m2r = kdb.Region(m2p)
            if not (m2r & probe).is_empty():
                connected_m2_nets.update(m2_net[m2_idx])
                connected_m2_detail.append((cx, cy, m2_idx, m2_net[m2_idx]))
                break

    if 'vdd' in connected_m2_nets and 'gnd' in connected_m2_nets:
        bb = m1p.bbox()
        m1_bridges.append((m1_idx, bb, connected_m2_detail))

print(f"\nM1 BRIDGES (Via1→M2→Via2 reaching both VDD & GND M3): {len(m1_bridges)}")
for m1_idx, bb, details in m1_bridges:
    print(f"\n  M1#{m1_idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
    for cx, cy, m2_idx, nets in details:
        m2bb = m2_polys[m2_idx].bbox()
        print(f"    Via1@({cx/1e3:.3f},{cy/1e3:.3f}) → M2#{m2_idx} "
              f"({m2bb.left/1e3:.3f},{m2bb.bottom/1e3:.3f})-"
              f"({m2bb.right/1e3:.3f},{m2bb.top/1e3:.3f}) nets={nets}")

print("\n\nDONE.")
