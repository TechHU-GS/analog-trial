#!/usr/bin/env python3
"""Diagnose M1 connectivity for all ng>=2 multi-finger MOSFET devices.

For each device:
1. Find all source/drain M1 strips (PCell-local → global)
2. Probe which merged M1 polygon each strip center belongs to
3. Report grouping: which strips share the same M1 polygon?

This reveals exactly which S/D contacts are connected vs isolated.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_connectivity.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
sys.path.insert(0, '.')
from atk.device import get_sd_strips, get_pcell_params
from atk.pdk import s5

# Load design data
with open('placement.json') as f:
    placement = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)
with open('netlist.json') as f:
    netlist = json.load(f)

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()

# Pre-index all merged M1 polygons
m1_polys = list(m1_merged.each())
print(f"Total merged M1 polygons: {len(m1_polys)}")

def find_m1_poly_index(gx, gy):
    """Find which merged M1 polygon contains point (gx, gy)."""
    probe = kdb.Region(kdb.Box(gx - 5, gy - 5, gx + 5, gy + 5))
    for idx, poly in enumerate(m1_polys):
        if not (kdb.Region(poly) & probe).is_empty():
            return idx
    return -1

# Also check Via1 + M2 connectivity for disconnected strips
li_via1 = layout.layer(19, 0)
li_m2 = layout.layer(10, 0)
li_via2 = layout.layer(30, 0)
li_m3 = layout.layer(11, 0)
m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
via1_all = kdb.Region(top.begin_shapes_rec(li_via1))
via2_all = kdb.Region(top.begin_shapes_rec(li_via2))

def trace_via_stack(gx1, gy1, gx2, gy2):
    """Check if an M1 region has Via1→M2→Via2→M3 connectivity."""
    probe = kdb.Region(kdb.Box(gx1, gy1, gx2, gy2))
    # Check Via1 touching this M1 region
    v1_touch = via1_all & probe
    if v1_touch.is_empty():
        return {'via1': False}
    # Find M2 connected to those via1s
    v1_expanded = v1_touch.sized(50)  # expand to find M2 overlap
    m2_touch = m2_merged & v1_expanded
    if m2_touch.is_empty():
        return {'via1': True, 'm2': False}
    # Find Via2 on that M2
    v2_touch = via2_all & m2_touch
    if v2_touch.is_empty():
        return {'via1': True, 'm2': True, 'via2': False}
    # Find M3
    v2_expanded = v2_touch.sized(50)
    m3_touch = m3_merged & v2_expanded
    if m3_touch.is_empty():
        return {'via1': True, 'm2': True, 'via2': True, 'm3': False}
    m3_bb = list(m3_touch.each())[0].bbox()
    return {
        'via1': True, 'm2': True, 'via2': True, 'm3': True,
        'm3_bbox': (m3_bb.left, m3_bb.bottom, m3_bb.right, m3_bb.top)
    }

# Process all ng>=2 devices
devices = netlist['devices']
split_devices = []
ok_devices = []

for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        continue
    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)
    if ng < 2:
        continue

    strips = get_sd_strips(dev_lib, dtype)
    if strips is None:
        continue

    inst = placement['instances'].get(name)
    if not inst:
        continue

    params = get_pcell_params(dev_lib, dtype)
    pcell_x = s5(inst['x_um'] - params['ox'])
    pcell_y = s5(inst['y_um'] - params['oy'])

    result = {'name': name, 'type': dtype, 'ng': ng, 'issues': []}

    for label, strip_list in [('S', strips['source']), ('D', strips['drain'])]:
        # Map each strip to its merged M1 polygon index
        strip_groups = {}  # poly_index -> [strip_indices]
        strip_details = []

        for i, strip in enumerate(strip_list):
            gx1 = pcell_x + strip[0]
            gy1 = pcell_y + strip[1]
            gx2 = pcell_x + strip[2]
            gy2 = pcell_y + strip[3]
            cx = (gx1 + gx2) // 2
            cy = (gy1 + gy2) // 2
            poly_idx = find_m1_poly_index(cx, cy)
            strip_details.append({
                'global': (gx1, gy1, gx2, gy2),
                'poly_idx': poly_idx,
            })
            if poly_idx not in strip_groups:
                strip_groups[poly_idx] = []
            strip_groups[poly_idx].append(i)

        n_groups = len(strip_groups)
        if n_groups > 1:
            result['issues'].append({
                'terminal': label,
                'n_strips': len(strip_list),
                'n_groups': n_groups,
                'groups': strip_groups,
                'details': strip_details,
            })

    if result['issues']:
        split_devices.append(result)
    else:
        ok_devices.append(result)

# Report
print(f"\n{'='*70}")
print(f"SUMMARY: {len(ok_devices)} OK, {len(split_devices)} SPLIT")
print(f"{'='*70}")

for r in ok_devices:
    print(f"  OK: {r['name']} ({r['type']} ng={r['ng']})")

print()
for r in split_devices:
    print(f"\n{'='*70}")
    print(f"SPLIT: {r['name']} ({r['type']} ng={r['ng']})")
    for issue in r['issues']:
        label = issue['terminal']
        print(f"  {label}: {issue['n_strips']} strips → {issue['n_groups']} M1 groups")
        for poly_idx, indices in issue['groups'].items():
            strip_names = [f"{label}{i*2}" for i in indices]
            print(f"    Group (M1#{poly_idx}): {strip_names}")
            # For each strip in this group, trace via stack
            for si in indices:
                det = issue['details'][si]
                g = det['global']
                vs = trace_via_stack(*g)
                via_str = "M1"
                if vs.get('via1'): via_str += "→V1"
                if vs.get('m2'): via_str += "→M2"
                if vs.get('via2'): via_str += "→V2"
                if vs.get('m3'):
                    bb = vs['m3_bbox']
                    via_str += f"→M3({bb[0]/1e3:.1f},{bb[1]/1e3:.1f})-({bb[2]/1e3:.1f},{bb[3]/1e3:.1f})"
                print(f"      {label}{i*2}: ({g[0]/1e3:.1f},{g[1]/1e3:.1f})-({g[2]/1e3:.1f},{g[3]/1e3:.1f}) via_stack: {via_str}")
