#!/usr/bin/env python3
"""Probe drain bus at ACTUAL position (after tie adjustment) for pmos_cs8."""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
sys.path.insert(0, '.')
from atk.device import get_sd_strips, get_pcell_params
from atk.pdk import s5

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m1 = layout.layer(8, 0)
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()

# From debug output: actual Mpb1 drain bus at by1=175015 by2=175175
devices = {
    'Mpb1': (175015, 175175, 94760, 109200),
    'Mpb2': (175015, 175175, 115260, 129700),
}

for name, (by1, by2, bx1, bx2) in devices.items():
    print(f"\n{'='*60}")
    print(f"{name} ACTUAL drain bus: Y={by1/1e3:.3f}-{by2/1e3:.3f} X={bx1/1e3:.3f}-{bx2/1e3:.3f}")

    # Probe at actual bus position
    probe = kdb.Region(kdb.Box(bx1, by1, bx2, by2))
    m1_bus = m1_merged & probe
    print(f"  M1 in actual bus region: {m1_bus.count()} polygon(s)")
    for p in m1_bus.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
              f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Also probe the full stub region (bus to strip_bot)
    pcell_y_strip_bot = 176310  # pcell_y + strip_bot = 176310 + 0
    full_probe = kdb.Region(kdb.Box(bx1, by1, bx2, pcell_y_strip_bot))
    m1_full = m1_merged & full_probe
    print(f"\n  M1 in full bus+stub region (Y={by1/1e3:.3f}-176.310):")
    print(f"  {m1_full.count()} polygon(s)")
    for p in m1_full.each():
        bb = p.bbox()
        # Check if it spans the full bus width
        if bb.width() > 5000:  # more than 5µm wide = likely bus bar
            print(f"    *** BUS BAR ***: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
        else:
            print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
