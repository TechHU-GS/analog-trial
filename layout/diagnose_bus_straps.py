#!/usr/bin/env python3
"""Diagnose M1 S/D bus strap connectivity for ng>=2 devices.

Checks whether the M1 bus straps in the GDS actually connect all
same-terminal strips. If a bus strap has a cross-net gap that cuts
through a strip position, the strip is disconnected → LVS finger split.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_bus_straps.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
from atk.device import load_device_lib, get_pcell_params, get_sd_strips
from atk.pdk import UM, s5

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Load M1 region (un-merged to see individual shapes)
li_m1 = layout.layer(8, 0)
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()

# Load placement
with open('placement.json') as f:
    placement = json.load(f)
instances = placement['instances']

# Load device lib
device_lib = load_device_lib('atk/data/device_lib.json')
DEVICES = {dt: get_pcell_params(device_lib, dt) for dt in device_lib}

# Target devices from LVS diagnostic (uncombined fingers)
PROBLEM_DEVICES = ['MS1', 'MS2', 'MS3', 'MS4', 'MBn2', 'Mc_tail', 'Mc_inp', 'Mc_inn',
                   'Mpb1', 'Mpb2', 'Mpb3', 'Mpb4', 'Mpb5', 'PM_cas3', 'Mtail',
                   'PM_mir3', 'MBp2']

print("=" * 70)
print("M1 Bus Strap Connectivity Diagnostic")
print("=" * 70)

for inst_name in PROBLEM_DEVICES:
    info = instances.get(inst_name)
    if info is None:
        continue
    dev_type = info['type']
    sd = get_sd_strips(device_lib, dev_type)
    if sd is None:
        continue

    dev = DEVICES[dev_type]
    pcell_x = s5(info['x_um'] - dev['ox'])
    pcell_y = s5(info['y_um'] - dev['oy'])

    src_strips = sd['source']
    drn_strips = sd['drain']

    # Check source connectivity
    if len(src_strips) >= 2:
        # Get absolute positions of all source strip centers
        s_centers = []
        for strip in src_strips:
            cx = pcell_x + (strip[0] + strip[2]) // 2
            cy_top = pcell_y + strip[3]
            cy_bot = pcell_y + strip[1]
            s_centers.append((cx, cy_top, cy_bot))

        # For each pair of adjacent source strips, check M1 connectivity
        all_connected = True
        for i in range(len(s_centers) - 1):
            s1_cx, s1_top, s1_bot = s_centers[i]
            s2_cx, s2_top, s2_bot = s_centers[i+1]

            # Probe M1 at source strip 1 top (where bus strap should connect)
            probe1 = kdb.Region(kdb.Box(s1_cx - 50, s1_top, s1_cx + 50, s1_top + 500))
            probe2 = kdb.Region(kdb.Box(s2_cx - 50, s2_top, s2_cx + 50, s2_top + 500))
            # Also check below (for ng=2 bottom bus)
            probe1b = kdb.Region(kdb.Box(s1_cx - 50, s1_bot - 500, s1_cx + 50, s1_bot))
            probe2b = kdb.Region(kdb.Box(s2_cx - 50, s2_bot - 500, s2_cx + 50, s2_bot))

            # Check if both probes hit the SAME merged M1 polygon
            hit1_above = m1_merged & probe1
            hit2_above = m1_merged & probe2
            hit1_below = m1_merged & probe1b
            hit2_below = m1_merged & probe2b

            # Check connectivity: find merged polygon containing S1 top
            # and see if it also contains S2 top
            s1_point = kdb.Region(kdb.Box(s1_cx - 5, s1_top - 5, s1_cx + 5, s1_top + 5))
            s2_point = kdb.Region(kdb.Box(s2_cx - 5, s2_top - 5, s2_cx + 5, s2_top + 5))

            # Find which merged M1 polygon each source strip belongs to
            s1_poly_id = -1
            s2_poly_id = -1
            for idx, poly in enumerate(m1_merged.each()):
                pr = kdb.Region(poly)
                if not (pr & s1_point).is_empty():
                    s1_poly_id = idx
                if not (pr & s2_point).is_empty():
                    s2_poly_id = idx
                if s1_poly_id >= 0 and s2_poly_id >= 0:
                    break

            connected = (s1_poly_id == s2_poly_id and s1_poly_id >= 0)
            if not connected:
                all_connected = False

            # Check bus strap presence above
            bus_above = False
            bus_below = False
            mid_x = (s1_cx + s2_cx) // 2
            # Check for horizontal M1 bar above device
            bus_probe_above = kdb.Region(kdb.Box(mid_x - 50, s1_top + 100, mid_x + 50, s1_top + 500))
            bus_probe_below = kdb.Region(kdb.Box(mid_x - 50, s1_bot - 500, mid_x + 50, s1_bot - 100))
            if not (m1_merged & bus_probe_above).is_empty():
                bus_above = True
            if not (m1_merged & bus_probe_below).is_empty():
                bus_below = True

            if not connected:
                print(f"\n  {inst_name} ({dev_type}): S[{i}]-S[{i+1}] DISCONNECTED")
                print(f"    S[{i}] at x={s1_cx/1e3:.3f}, S[{i+1}] at x={s2_cx/1e3:.3f}")
                print(f"    M1 poly IDs: S[{i}]={s1_poly_id}, S[{i+1}]={s2_poly_id}")
                print(f"    Bus above midpoint: {'yes' if bus_above else 'NO'}")
                print(f"    Bus below midpoint: {'yes' if bus_below else 'NO'}")

        if all_connected:
            print(f"  {inst_name} ({dev_type}): all {len(src_strips)} source strips connected ✓")

    # Check drain connectivity
    if len(drn_strips) >= 2:
        d_centers = []
        for strip in drn_strips:
            cx = pcell_x + (strip[0] + strip[2]) // 2
            cy_top = pcell_y + strip[3]
            cy_bot = pcell_y + strip[1]
            d_centers.append((cx, cy_top, cy_bot))

        all_d_connected = True
        for i in range(len(d_centers) - 1):
            d1_cx, d1_top, d1_bot = d_centers[i]
            d2_cx, d2_top, d2_bot = d_centers[i+1]

            d1_point = kdb.Region(kdb.Box(d1_cx - 5, d1_bot + 5, d1_cx + 5, d1_bot + 15))
            d2_point = kdb.Region(kdb.Box(d2_cx - 5, d2_bot + 5, d2_cx + 5, d2_bot + 15))

            d1_poly_id = -1
            d2_poly_id = -1
            for idx, poly in enumerate(m1_merged.each()):
                pr = kdb.Region(poly)
                if not (pr & d1_point).is_empty():
                    d1_poly_id = idx
                if not (pr & d2_point).is_empty():
                    d2_poly_id = idx
                if d1_poly_id >= 0 and d2_poly_id >= 0:
                    break

            connected = (d1_poly_id == d2_poly_id and d1_poly_id >= 0)
            if not connected:
                all_d_connected = False
                print(f"\n  {inst_name} ({dev_type}): D[{i}]-D[{i+1}] DISCONNECTED")
                print(f"    D[{i}] at x={d1_cx/1e3:.3f}, D[{i+1}] at x={d2_cx/1e3:.3f}")
                print(f"    M1 poly IDs: D[{i}]={d1_poly_id}, D[{i+1}]={d2_poly_id}")

        if all_d_connected:
            print(f"  {inst_name} ({dev_type}): all {len(drn_strips)} drain strips connected ✓")
