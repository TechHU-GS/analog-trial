#!/usr/bin/env python3
"""Diagnose multi-finger device extraction splitting.

For each ng>1 device in the schematic, examine the physical PCell to see
if S1/S2 (or D) contacts are internally connected via M1 straps.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_multifinger.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

# Load design data
with open('netlist.json') as f:
    netlist = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)
with open('placement.json') as f:
    placement = json.load(f)

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# IHP layers
li_m1 = layout.layer(8, 0)
li_cont = layout.layer(6, 0)
li_gatpoly = layout.layer(5, 0)
li_activ = layout.layer(1, 0)  # Active area (OD)

m1_region = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
cont_region = kdb.Region(top.begin_shapes_rec(li_cont))
gatpoly_region = kdb.Region(top.begin_shapes_rec(li_gatpoly))

# For each ng>1 device, check if S/D contacts are connected
devices = netlist['devices']

print(f"{'Device':<12} {'Type':<18} {'ng':>3} {'W':>5} {'L':>5}  Split?  S_merge  D_merge")
print("-" * 90)

for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        continue
    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)
    if ng <= 1:
        continue

    w = lib['params']['w']
    l = lib['params']['l']
    pcell_name = lib.get('pcell_name', lib.get('pcell', '?'))

    # Get placement info
    inst = placement['instances'].get(name)
    if not inst:
        print(f"{name:<12} {dtype:<18} {ng:>3} {w:>5} {l:>5}  NO PLACEMENT")
        continue

    x_nm = int(inst['x_um'] * 1000)
    y_nm = int(inst['y_um'] * 1000)
    w_nm = int(inst['w_um'] * 1000)
    h_nm = int(inst['h_um'] * 1000)
    rot = inst.get('rotation', 0)

    # Probe box around device
    if rot in (90, 270):
        bbox = kdb.Box(x_nm, y_nm, x_nm + h_nm, y_nm + w_nm)
    else:
        bbox = kdb.Box(x_nm, y_nm, x_nm + w_nm, y_nm + h_nm)

    # Expand probe slightly
    probe = kdb.Region(kdb.Box(bbox.left - 100, bbox.bottom - 100,
                                bbox.right + 100, bbox.top + 100))

    # Get M1 shapes in this area
    m1_local = []
    for poly in m1_region.each():
        pr = kdb.Region(poly)
        if not (pr & probe).is_empty():
            m1_local.append(poly)

    # Get gate poly in this area
    gp_local = gatpoly_region & probe

    # Count gate fingers
    gp_count = gp_local.count()

    # Get contacts in this area
    cont_local = cont_region & probe

    # Check M1 merged connectivity
    # If all source contacts are on the same M1 polygon, they're connected
    m1_merged_local = kdb.Region()
    for p in m1_local:
        m1_merged_local.insert(p)
    m1_merged_local = m1_merged_local.merged()

    # For ng=2 layout (S1-G1-D-G2-S2):
    # Source contacts are at the edges, drain contacts in the middle
    # Count how many distinct M1 polygons touch the contacts
    m1_poly_count = m1_merged_local.count()

    # Check if source and drain regions are connected
    # Simple check: count M1 polygons overlapping the device area
    print(f"{name:<12} {dtype:<18} {ng:>3} {w:>5} {l:>5}  "
          f"GP={gp_count:>2}  M1={m1_poly_count:>2}  cont={cont_local.count():>3}")

# Now check extracted netlist for split info
print("\n\n=== Extracted netlist split analysis ===")
print("Devices with asymmetric AS/AD (sign of finger split):\n")

import re
with open('/tmp/lvs_run5/ptat_vco_extracted.cir') as f:
    lines = f.readlines()

joined = []
for line in lines:
    line = line.rstrip('\n')
    if line.startswith('+') and joined:
        joined[-1] += ' ' + line[1:].strip()
    else:
        joined.append(line)

for line in joined:
    line = line.strip()
    if not line.startswith('M'):
        continue
    # Check for asymmetric AS/AD
    as_m = re.search(r'AS=([\d.]+)', line)
    ad_m = re.search(r'AD=([\d.]+)', line)
    if as_m and ad_m:
        as_val = float(as_m.group(1))
        ad_val = float(ad_m.group(1))
        if abs(as_val - ad_val) > 0.001:
            # Extract W and L
            w_m = re.search(r'W=([\d.]+)', line)
            l_m = re.search(r'L=([\d.]+)', line)
            model_m = re.search(r'sg13_lv_[np]mos', line)
            name_m = re.match(r'M(\S+)', line)
            if w_m and l_m:
                print(f"  M{name_m.group(1)}: {model_m.group(0) if model_m else '?'} "
                      f"W={w_m.group(1)}u L={l_m.group(1)}u "
                      f"AS={as_val}p AD={ad_val}p (asymmetric)")
