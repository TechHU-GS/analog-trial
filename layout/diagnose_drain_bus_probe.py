#!/usr/bin/env python3
"""Probe the drain bus M1 region for pmos_cs8 devices.

Check if the drain bus is actually present and continuous in the GDS.
Also probe source bus region.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_drain_bus_probe.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
sys.path.insert(0, '.')
from atk.device import get_sd_strips, get_pcell_params
from atk.pdk import s5

M1_MIN_S = 180
BUS_W = 160
BUS_GAP = 200

with open('placement.json') as f:
    placement = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()

# Focus on Mpb1 and Mnb1 as representative devices
focus = ['Mpb1', 'Mnb1', 'Mpb2']

instances = placement['instances']
for name in focus:
    inst = instances[name]
    dtype = inst['type']
    lib = dev_lib[dtype]
    params = get_pcell_params(dev_lib, dtype)
    sd = get_sd_strips(dev_lib, dtype)

    pcell_x = s5(inst['x_um'] - params['ox'])
    pcell_y = s5(inst['y_um'] - params['oy'])

    src_strips = sd['source']
    drn_strips = sd['drain']
    strip_top = src_strips[0][3]
    strip_bot = src_strips[0][1]

    # Drain bus position
    drn_by2 = pcell_y + strip_bot - BUS_GAP
    drn_by1 = drn_by2 - BUS_W
    drn_bx1 = pcell_x + drn_strips[0][0]
    drn_bx2 = pcell_x + drn_strips[-1][2]

    print(f"\n{'='*70}")
    print(f"{name} ({dtype} ng={lib['params'].get('ng',1)})")
    print(f"  pcell_origin: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f}) µm")
    print(f"  strip Y range: {(pcell_y+strip_bot)/1e3:.3f} - {(pcell_y+strip_top)/1e3:.3f}")

    # Probe drain bus region
    print(f"\n  Expected DRAIN BUS: Y={drn_by1/1e3:.3f}-{drn_by2/1e3:.3f} X={drn_bx1/1e3:.3f}-{drn_bx2/1e3:.3f}")

    bus_probe = kdb.Region(kdb.Box(drn_bx1, drn_by1, drn_bx2, drn_by2))
    m1_in_bus = m1_merged & bus_probe
    print(f"  M1 in drain bus region: {m1_in_bus.count()} polygons")
    for p in m1_in_bus.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
              f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Probe BELOW drain bus (wider area)
    wider_probe = kdb.Region(kdb.Box(drn_bx1 - 500, drn_by1 - 500,
                                      drn_bx2 + 500, drn_by2 + 500))
    m1_wider = m1_merged & wider_probe
    print(f"\n  M1 in wider region (±500nm): {m1_wider.count()} polygons")
    for p in m1_wider.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
              f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Probe each drain strip + stub region
    print(f"\n  Drain strip + stub regions:")
    for i, strip in enumerate(drn_strips):
        gx1 = pcell_x + strip[0]
        gx2 = pcell_x + strip[2]
        gy1 = pcell_y + strip[1]
        gy2 = pcell_y + strip[3]
        # Also check from drain bus to strip top
        full_probe = kdb.Region(kdb.Box(gx1, drn_by1, gx2, gy2))
        m1_full = m1_merged & full_probe
        print(f"    D{i*2+1}: strip ({gx1/1e3:.3f},{gy1/1e3:.3f})-({gx2/1e3:.3f},{gy2/1e3:.3f})")
        print(f"      Full extent ({gx1/1e3:.3f},{drn_by1/1e3:.3f})-({gx2/1e3:.3f},{gy2/1e3:.3f}): "
              f"{m1_full.count()} M1 polygons")

    # Source bus position
    src_by1 = pcell_y + strip_top + BUS_GAP
    src_by2 = src_by1 + BUS_W
    src_bx1 = pcell_x + src_strips[1][0]  # current: S2
    src_bx2 = pcell_x + src_strips[-1][2]  # S8

    print(f"\n  Expected SOURCE BUS (current S2-S8): Y={src_by1/1e3:.3f}-{src_by2/1e3:.3f} X={src_bx1/1e3:.3f}-{src_bx2/1e3:.3f}")
    src_probe = kdb.Region(kdb.Box(src_bx1, src_by1, src_bx2, src_by2))
    m1_src = m1_merged & src_probe
    print(f"  M1 in source bus region: {m1_src.count()} polygons")
    for p in m1_src.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
              f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
