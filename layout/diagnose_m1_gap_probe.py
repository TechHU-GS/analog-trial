#!/usr/bin/env python3
"""Probe M1 shapes in the gap region between D3 and D5 for Mpb1-5.

Directly reads GDS to find what's at X=102-103 (Mpb1 gap area).
Shows both raw (unmerged) and merged M1 shapes.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_gap_probe.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
sys.path.insert(0, '.')
from atk.device import get_sd_strips, get_pcell_params
from atk.pdk import s5

with open('placement.json') as f:
    placement = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)
with open('netlist.json') as f:
    netlist = json.load(f)
with open('output/ties.json') as f:
    ties = json.load(f)

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
m1_raw = kdb.Region(top.begin_shapes_rec(li_m1))
m1_merged = m1_raw.merged()

BUS_W = 160
BUS_GAP = 200
M1_MIN_S = 180

# Find tie bars in pmos_cs8 area
tie_m1_bars = []
for t in ties.get('ties', []):
    for r in t.get('layers', {}).get('M1_8_0', []):
        tie_m1_bars.append(tuple(r))

# Focus on Mpb1
devices = netlist['devices']
for d in devices:
    name = d['name']
    dtype = d['type']
    if name not in ('Mpb1', 'Mnb1'):
        continue

    sd = get_sd_strips(dev_lib, dtype)
    inst = placement['instances'][name]
    params = get_pcell_params(dev_lib, dtype)
    pcell_x = s5(inst['x_um'] - params['ox'])
    pcell_y = s5(inst['y_um'] - params['oy'])

    drn_strips = sd['drain']
    src_strips = sd['source']
    strip_bot = src_strips[0][1]

    # Simulate drain bus position with tie pushdown
    by2_init = pcell_y + strip_bot - BUS_GAP
    by2 = by2_init
    bx1 = pcell_x + drn_strips[0][0]
    bx2 = pcell_x + drn_strips[-1][2]

    for txl, tyb, txr, tyt in tie_m1_bars:
        if bx2 <= txl or bx1 >= txr:
            continue
        if tyb < by2 + M1_MIN_S and tyt > by2 - BUS_W - M1_MIN_S:
            needed = tyb - M1_MIN_S - BUS_W
            if needed < by2 - BUS_W:
                print(f"  {name}: tie ({txl/1e3:.3f},{tyb/1e3:.3f})-({txr/1e3:.3f},{tyt/1e3:.3f})"
                      f" pushes by2 {by2}→{((needed + BUS_W) // 5) * 5}")
                by2 = ((needed + BUS_W) // 5) * 5
    by1 = by2 - BUS_W

    print(f"\n{'='*70}")
    print(f"{name} ({dtype})")
    print(f"  pcell: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f})")
    print(f"  drain bus expected: X=({bx1/1e3:.3f},{by1/1e3:.3f})-({bx2/1e3:.3f},{by2/1e3:.3f})")
    print(f"  by2_init={by2_init/1e3:.3f} → by2={by2/1e3:.3f} (delta={(by2_init-by2)/1e3:.3f}µm)")

    # Drain strip positions
    print(f"\n  Drain strips (global):")
    for i, strip in enumerate(drn_strips):
        gx1 = pcell_x + strip[0]
        gy1 = pcell_y + strip[1]
        gx2 = pcell_x + strip[2]
        gy2 = pcell_y + strip[3]
        print(f"    D{i*2+1}: ({gx1/1e3:.3f},{gy1/1e3:.3f})-({gx2/1e3:.3f},{gy2/1e3:.3f})")

    # For Mpb1: gap is around X=102-103. Probe a wider area.
    # Use the D3-D5 X range
    if len(drn_strips) >= 3:
        d3_right = pcell_x + drn_strips[1][2]  # D3 right edge
        d5_left = pcell_x + drn_strips[2][0]   # D5 left edge
        probe_xl = d3_right - 500
        probe_xr = d5_left + 500
    else:
        probe_xl = bx1
        probe_xr = bx2

    # Probe Y range: from drain bus to strip top
    probe_yb = by1 - 500
    probe_yt = pcell_y + src_strips[0][3] + 500

    probe = kdb.Region(kdb.Box(probe_xl, probe_yb, probe_xr, probe_yt))

    # Raw M1 shapes
    m1_raw_in_probe = m1_raw & probe
    print(f"\n  Raw M1 shapes in probe ({probe_xl/1e3:.1f},{probe_yb/1e3:.1f})-({probe_xr/1e3:.1f},{probe_yt/1e3:.1f}):")
    print(f"  Count: {m1_raw_in_probe.count()}")
    for p in m1_raw_in_probe.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Merged M1 shapes
    m1_merged_in_probe = m1_merged & probe
    print(f"\n  Merged M1 in probe: {m1_merged_in_probe.count()}")
    for p in m1_merged_in_probe.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Specifically check: is there M1 at the drain bus position spanning D3→D5?
    bus_d3d5_probe = kdb.Region(kdb.Box(d3_right, by1, d5_left, by2))
    m1_at_bus_d3d5 = m1_raw & bus_d3d5_probe
    print(f"\n  Raw M1 at drain bus between D3-D5 ({d3_right/1e3:.3f},{by1/1e3:.3f})-({d5_left/1e3:.3f},{by2/1e3:.3f}):")
    print(f"  Count: {m1_at_bus_d3d5.count()}")
    for p in m1_at_bus_d3d5.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

    # Check tie M1 bars in this area
    print(f"\n  Tie M1 bars in probe area:")
    for txl, tyb, txr, tyt in tie_m1_bars:
        if txr <= probe_xl or txl >= probe_xr:
            continue
        if tyt <= probe_yb or tyb >= probe_yt:
            continue
        print(f"    ({txl/1e3:.3f},{tyb/1e3:.3f})-({txr/1e3:.3f},{tyt/1e3:.3f})")
