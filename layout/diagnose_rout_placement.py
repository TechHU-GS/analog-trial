#!/usr/bin/env python3
"""Find valid X positions for Rout (rppd_out) that avoid MOSFET overlap.

The rppd salblock extends 3.62µm in X and 26.1µm in Y.
Need to find X positions where salblock doesn't overlap any MOSFET Activ.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_rout_placement.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Current Rout position
with open('placement.json') as f:
    placement = json.load(f)

rout_info = placement['instances']['Rout']
print(f"Current Rout: x={rout_info['x_um']}, y={rout_info['y_um']}, type={rout_info['type']}")

# Load Activ regions (all MOSFET Activ in global coords)
li_activ = layout.layer(1, 0)
all_activ = kdb.Region(top.begin_shapes_rec(li_activ)).merged()

# Rppd salblock extent in PCell coords: (-200, 0) to (3420, 26115)
# Rppd PCell bbox: (-200, -610) to (3420, 26750)
# With no rotation, PCell origin at (x_um - ox, y_um - oy) where ox=-0.2, oy=-0.61
# So PCell origin = (x_um + 0.2, y_um + 0.61) in µm

SALBLOCK_DX = (-200, 3420)  # nm relative to PCell origin
SALBLOCK_DY = (0, 26115)    # nm relative to PCell origin

# Current PCell origin
ox_um = -0.2  # from device_lib
oy_um = -0.61
pcell_x = int((rout_info['x_um'] - ox_um) * 1000)
pcell_y = int((rout_info['y_um'] - oy_um) * 1000)
print(f"Current PCell origin: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f}) µm")
print(f"Current salblock: ({(pcell_x+SALBLOCK_DX[0])/1e3:.3f}, {(pcell_y+SALBLOCK_DY[0])/1e3:.3f}) - "
      f"({(pcell_x+SALBLOCK_DX[1])/1e3:.3f}, {(pcell_y+SALBLOCK_DY[1])/1e3:.3f}) µm")

# Scan X positions: for each X, check if salblock overlaps any MOSFET Activ
# Keep Y fixed at current value
print(f"\n{'='*60}")
print("Scanning X positions (Y fixed)")
print(f"{'='*60}")

results = []
for x_um_10 in range(100, 2000, 5):  # x from 10µm to 200µm in 0.5µm steps
    x_um = x_um_10 / 10.0
    test_pcell_x = int((x_um - ox_um) * 1000)

    sal_x1 = test_pcell_x + SALBLOCK_DX[0]
    sal_y1 = pcell_y + SALBLOCK_DY[0]  # keep Y same
    sal_x2 = test_pcell_x + SALBLOCK_DX[1]
    sal_y2 = pcell_y + SALBLOCK_DY[1]

    sal_region = kdb.Region(kdb.Box(sal_x1, sal_y1, sal_x2, sal_y2))
    overlap = all_activ & sal_region

    if overlap.is_empty():
        results.append((x_um, 0))
    else:
        results.append((x_um, overlap.area()))

# Print results
clear_ranges = []
in_clear = False
for x_um, area in results:
    if area == 0:
        if not in_clear:
            start = x_um
            in_clear = True
    else:
        if in_clear:
            clear_ranges.append((start, x_um - 0.5))
            in_clear = False
if in_clear:
    clear_ranges.append((start, results[-1][0]))

print(f"\nClear X ranges (no MOSFET Activ overlap):")
for s, e in clear_ranges:
    width = e - s + 0.5
    print(f"  x = {s:.1f} - {e:.1f} µm (width = {width:.1f}µm)")

# Also check which specific devices overlap at current X
current_sal = kdb.Region(kdb.Box(
    pcell_x + SALBLOCK_DX[0], pcell_y + SALBLOCK_DY[0],
    pcell_x + SALBLOCK_DX[1], pcell_y + SALBLOCK_DY[1]
))
overlap_at_current = all_activ & current_sal
print(f"\nDevices overlapping salblock at current position:")
print(f"  Overlap area: {overlap_at_current.area() / 1e6:.2f} µm²")
for poly in overlap_at_current.each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
          f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

# Check Y sweep too: for current X, scan Y for clear positions
print(f"\n{'='*60}")
print("Scanning Y positions (X fixed)")
print(f"{'='*60}")

y_results = []
for y_um_10 in range(200, 2400, 5):
    y_um = y_um_10 / 10.0
    test_pcell_y = int((y_um - oy_um) * 1000)

    sal_x1 = pcell_x + SALBLOCK_DX[0]  # keep X same
    sal_y1 = test_pcell_y + SALBLOCK_DY[0]
    sal_x2 = pcell_x + SALBLOCK_DX[1]
    sal_y2 = test_pcell_y + SALBLOCK_DY[1]

    sal_region = kdb.Region(kdb.Box(sal_x1, sal_y1, sal_x2, sal_y2))
    overlap = all_activ & sal_region

    if overlap.is_empty():
        y_results.append((y_um, 0))
    else:
        y_results.append((y_um, overlap.area()))

clear_y_ranges = []
in_clear = False
for y_um, area in y_results:
    if area == 0:
        if not in_clear:
            start = y_um
            in_clear = True
    else:
        if in_clear:
            clear_y_ranges.append((start, y_um - 0.5))
            in_clear = False
if in_clear:
    clear_y_ranges.append((start, y_results[-1][0]))

print(f"\nClear Y ranges (no MOSFET Activ overlap at current X):")
for s, e in clear_y_ranges:
    print(f"  y = {s:.1f} - {e:.1f} µm (span = {e-s+0.5:.1f}µm)")

# Print device positions for context
print(f"\n{'='*60}")
print("All devices with y in salblock range (y=137.6-163.7µm):")
print(f"{'='*60}")
from atk.device import load_device_lib, get_pcell_params
from atk.pdk import UM, s5
device_lib = load_device_lib('atk/data/device_lib.json')
DEVICES = {dt: get_pcell_params(device_lib, dt) for dt in device_lib}

for name, info in sorted(placement['instances'].items(), key=lambda x: x[1]['x_um']):
    dev = DEVICES[info['type']]
    pcx = s5(info['x_um'] - dev['ox'])
    pcy = s5(info['y_um'] - dev['oy'])
    dev_w = int(dev['w'] * UM)
    dev_h = int(dev['h'] * UM)

    # Check if device is in salblock Y range
    if pcy + dev_h > pcell_y + SALBLOCK_DY[0] and pcy < pcell_y + SALBLOCK_DY[1]:
        if pcx + dev_w > pcell_x + SALBLOCK_DX[0] and pcx < pcell_x + SALBLOCK_DX[1]:
            marker = " *** OVERLAP ***"
        else:
            marker = ""
        print(f"  {name:12s} ({info['type']:16s}) x={info['x_um']:7.2f} y={info['y_um']:7.2f} "
              f"PCell ({pcx/1e3:.1f}-{(pcx+dev_w)/1e3:.1f}, {pcy/1e3:.1f}-{(pcy+dev_h)/1e3:.1f}){marker}")
