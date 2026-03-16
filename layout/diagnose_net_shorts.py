#!/usr/bin/env python3
"""Trace net shorts in the GDS by probing connectivity.

Identifies where gnd connects to tail, and where vdd connects to vdd_vco.
Uses KLayout region operations to find the bridging metal layer.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_net_shorts.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
sys.path.insert(0, '.')

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Layer indices
layers = {
    'M1': layout.layer(8, 0),
    'Via1': layout.layer(19, 0),
    'M2': layout.layer(10, 0),
    'Via2': layout.layer(29, 0),
    'M3': layout.layer(30, 0),
    'Via3': layout.layer(49, 0),
    'M4': layout.layer(50, 0),
}

# Label layers
lbl_layers = {
    'M1_lbl': layout.layer(8, 25),
    'M2_lbl': layout.layer(10, 25),
    'M3_lbl': layout.layer(30, 25),
}

# Collect all labels
print("=== Labels ===")
for lbl_name, li in lbl_layers.items():
    labels = []
    for shape in top.shapes(li).each():
        if shape.is_text():
            t = shape.text
            labels.append((t.string, t.x, t.y))
    print(f"{lbl_name}: {len(labels)} labels")
    for name, x, y in sorted(labels):
        if name in ('gnd', 'tail', 'vdd', 'vdd_vco'):
            print(f"  {name}: ({x/1000:.3f}, {y/1000:.3f}) µm")

# Load routing to find where gnd and tail rails are
with open('output/routing_optimized.json') as f:
    routing = json.load(f)

rails = routing.get('power', {}).get('rails', {})
print("\n=== Power Rails ===")
for rail_id, rail in rails.items():
    net = rail.get('net', rail_id)
    print(f"  {rail_id} (net={net}): y={rail['y']/1000:.3f}µm"
          f" x={rail['x1']/1000:.3f}-{rail['x2']/1000:.3f}µm")

# Find M3 shapes that could bridge gnd and tail rails
# Identify the Y positions of gnd and tail rails
gnd_rails = [(rid, r) for rid, r in rails.items() if r.get('net') == 'gnd']
tail_rails = [(rid, r) for rid, r in rails.items() if r.get('net') == 'tail']
vdd_rails = [(rid, r) for rid, r in rails.items() if r.get('net') == 'vdd']
vdd_vco_rails = [(rid, r) for rid, r in rails.items() if r.get('net') == 'vdd_vco']

print(f"\ngnd rails: {[r[0] for r in gnd_rails]}")
print(f"tail rails: {[r[0] for r in tail_rails]}")
print(f"vdd rails: {[r[0] for r in vdd_rails]}")
print(f"vdd_vco rails: {[r[0] for r in vdd_vco_rails]}")

# Check: is there a power vbar (M3 vertical) connecting gnd and tail?
drops = routing.get('power', {}).get('drops', [])
vbars = routing.get('power', {}).get('vbars', [])

print(f"\n=== Power VBars ===")
for vb in vbars:
    net = vb.get('net', '?')
    x = vb.get('x', 0)
    y1 = vb.get('y1', 0)
    y2 = vb.get('y2', 0)
    print(f"  net={net} x={x/1000:.3f} y={y1/1000:.3f}-{y2/1000:.3f}")

# Check: do gnd and tail have adjacent/overlapping M3 rails?
print("\n=== Adjacent Rail Check ===")
all_rails_sorted = sorted(rails.items(), key=lambda x: x[1]['y'])
for i in range(len(all_rails_sorted) - 1):
    r1_id, r1 = all_rails_sorted[i]
    r2_id, r2 = all_rails_sorted[i + 1]
    n1 = r1.get('net', r1_id)
    n2 = r2.get('net', r2_id)
    gap = r2['y'] - r1['y']
    if n1 != n2:
        print(f"  {r1_id}({n1}) y={r1['y']/1000:.1f} -- gap={gap/1000:.3f}µm"
              f" -- {r2_id}({n2}) y={r2['y']/1000:.1f}")

# Check M3 region overlap between gnd and tail positions
# First, find all M3 shapes
m3_region = kdb.Region(top.begin_shapes_rec(layers['M3']))
m3_merged = m3_region.merged()

# For each pair (gnd, tail) and (vdd, vdd_vco), probe for bridging M3
for pair_name, rails_a, rails_b in [('gnd↔tail', gnd_rails, tail_rails),
                                     ('vdd↔vdd_vco', vdd_rails, vdd_vco_rails)]:
    if not rails_a or not rails_b:
        print(f"\n{pair_name}: one side has no rails, skipping")
        continue

    print(f"\n=== Probing {pair_name} bridging ===")
    for rid_a, ra in rails_a:
        for rid_b, rb in rails_b:
            # Find X overlap
            x_overlap_l = max(ra['x1'], rb['x1'])
            x_overlap_r = min(ra['x2'], rb['x2'])
            if x_overlap_l >= x_overlap_r:
                continue
            # Find Y span
            y_min = min(ra['y'], rb['y'])
            y_max = max(ra['y'], rb['y'])
            if y_max - y_min < 100:  # too close, probably same rail
                continue

            # Probe each metal layer for shapes spanning the gap
            for lyr_name in ('M1', 'M2', 'M3', 'M4'):
                li = layers[lyr_name]
                region = kdb.Region(top.begin_shapes_rec(li))
                # Probe rectangle between the two rails
                probe = kdb.Region(kdb.Box(x_overlap_l, y_min - 500,
                                          x_overlap_r, y_max + 500))
                intersection = region & probe
                # Look for shapes that span from one rail Y to the other
                for p in intersection.each():
                    bb = p.bbox()
                    # Shape must touch both rail Y positions (±200nm tolerance)
                    touches_a = abs(bb.top - ra['y']) < 500 or abs(bb.bottom - ra['y']) < 500 or \
                               (bb.bottom <= ra['y'] <= bb.top)
                    touches_b = abs(bb.top - rb['y']) < 500 or abs(bb.bottom - rb['y']) < 500 or \
                               (bb.bottom <= rb['y'] <= bb.top)
                    if touches_a and touches_b:
                        print(f"  BRIDGE on {lyr_name}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
                              f" spans {rid_a}↔{rid_b}")

# Also check: are there vbars that connect gnd rails to tail rails?
print("\n=== VBar Net-Crossing Check ===")
for vb in vbars:
    net = vb.get('net', '?')
    x = vb.get('x', 0)
    y1 = vb.get('y1', 0)
    y2 = vb.get('y2', 0)
    # Check if this vbar's Y range crosses from one net's rail to another
    for rid, rail in rails.items():
        rnet = rail.get('net', rid)
        ry = rail['y']
        if rnet != net and y1 <= ry <= y2:
            print(f"  VBar net={net} x={x/1000:.3f} y={y1/1000:.3f}-{y2/1000:.3f}"
                  f" CROSSES {rid}(net={rnet}) at y={ry/1000:.3f}")

# Check: multi-rail bridges (these can cross nets!)
print("\n=== Checking assemble_gds bridge logic ===")
# The bridges connect same-net rails at x=1.5µm and x=3.5µm
# If gnd and tail share a bridge position, that's the short
bridge_x_gnd = 1500  # gnd bridge at x=1.5µm (from assemble output)
bridge_x_vdd = 3500  # vdd bridge at x=3.5µm

# Check: what's the M3 label situation for vdd_vco?
print("\n=== VDD_VCO Label Check ===")
for lbl_name, li in lbl_layers.items():
    for shape in top.shapes(li).each():
        if shape.is_text() and 'vco' in shape.text.string.lower():
            t = shape.text
            print(f"  {lbl_name}: '{t.string}' at ({t.x/1000:.3f}, {t.y/1000:.3f})")
