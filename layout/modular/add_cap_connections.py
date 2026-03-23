#!/usr/bin/env python3
"""Add CMIM cap via stacks to routed GDS (post-routing step).

Each cap has 2 terminals (M5 bottom plate corners) that need
via stacks (M5→Via4→M4→Via3→M3→Via2→M2) to connect to signal nets.
Run AFTER route_intermodule.py to avoid creating routing obstacles.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/add_cap_connections.py
"""
import json
import os
import gdstk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
os.chdir(os.path.dirname(SCRIPT_DIR))

# Via stack dimensions (nm → um for gdstk)
VIA_SIZE = 0.190
VIA_HALF = VIA_SIZE / 2
PAD_HW = 0.150  # metal pad half-width at via locations
M_WIDTH = 0.200
M_HW = M_WIDTH / 2


def add_via_stack(cell, cx, cy):
    """Add via stack M5→Via4→M4→Via3→M3→Via2→M2 at (cx, cy) in um."""
    for metal_layer in [10, 30, 50, 67]:  # M2, M3, M4, M5
        cell.add(gdstk.rectangle(
            (cx - PAD_HW, cy - PAD_HW), (cx + PAD_HW, cy + PAD_HW),
            layer=metal_layer, datatype=0))
    for via_layer in [29, 49, 66]:  # Via2, Via3, Via4
        cell.add(gdstk.rectangle(
            (cx - VIA_HALF, cy - VIA_HALF), (cx + VIA_HALF, cy + VIA_HALF),
            layer=via_layer, datatype=0))


def main():
    print('=== Adding CMIM cap connections (post-routing) ===\n')

    with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
        fp = json.load(f)

    # Cap terminal positions (500nm from M5 plate edge)
    # Net assignments from sim/_soilz_full.sp
    MARGIN = 0.8  # 800nm from edge to avoid M4.b spacing with nearby routes
    caps = [
        ('cbyp_n', fp['cbyp_n'], 'nmos_bias', 'gnd'),
        ('cbyp_p', fp['cbyp_p'], 'pmos_bias', 'vdd'),
        ('c_fb',   fp['c_fb'],   'sum_n',     'ota_out'),
    ]

    lib = gdstk.read_gds(os.path.join(OUT_DIR, 'soilz_routed.gds'))
    cell = [c for c in lib.cells if c.name == 'tt_um_techhu_analog_trial'][0]

    total = 0
    for name, pos, net1, net2 in caps:
        x, y, w, h = pos['x'], pos['y'], pos['w'], pos['h']
        # Terminal 1: bottom-left corner → net1
        t1x, t1y = x + MARGIN, y + MARGIN
        # Terminal 2: top-right corner → net2
        t2x, t2y = x + w - MARGIN, y + h - MARGIN

        add_via_stack(cell, t1x, t1y)
        add_via_stack(cell, t2x, t2y)
        total += 2
        print(f'  {name}: T1({t1x:.1f},{t1y:.1f})→{net1}, T2({t2x:.1f},{t2y:.1f})→{net2}')

    out_path = os.path.join(OUT_DIR, 'soilz_routed.gds')
    lib.write_gds(out_path)
    print(f'\n  Added {total} via stacks to {out_path}')
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
