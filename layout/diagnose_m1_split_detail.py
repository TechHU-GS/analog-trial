#!/usr/bin/env python3
"""Detailed M1 merged polygon assignment for each S/D strip of ng>=4 devices.

Shows which merged M1 polygon each strip belongs to, and whether the M1
source/drain bus connects them.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_split_detail.py
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

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
m1_polys = list(m1_merged.each())
print(f"M1: {len(m1_polys)} merged polygons")

def find_m1_poly(x, y, expand=20):
    """Find merged M1 polygon index at (x,y) nm."""
    probe = kdb.Region(kdb.Box(x - expand, y - expand, x + expand, y + expand))
    for idx, poly in enumerate(m1_polys):
        if not (kdb.Region(poly) & probe).is_empty():
            bb = poly.bbox()
            return idx, (bb.left, bb.bottom, bb.right, bb.top)
    return -1, None

devices = netlist['devices']
for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        continue
    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)
    if ng < 4:
        continue

    sd = get_sd_strips(dev_lib, dtype)
    if sd is None:
        continue
    inst = placement['instances'].get(name)
    if not inst:
        continue

    params = get_pcell_params(dev_lib, dtype)
    pcell_x = s5(inst['x_um'] - params['ox'])
    pcell_y = s5(inst['y_um'] - params['oy'])

    print(f"\n{'='*70}")
    print(f"{name} ({dtype} ng={ng})")

    # Source strips
    src_strips = sd['source']
    src_poly_ids = {}
    for i, strip in enumerate(src_strips):
        gx1 = pcell_x + strip[0]
        gy1 = pcell_y + strip[1]
        gx2 = pcell_x + strip[2]
        gy2 = pcell_y + strip[3]
        cx, cy = (gx1 + gx2) // 2, (gy1 + gy2) // 2
        poly_id, bb = find_m1_poly(cx, cy)
        src_poly_ids[i] = poly_id
        bb_str = f"({bb[0]/1e3:.1f},{bb[1]/1e3:.1f})-({bb[2]/1e3:.1f},{bb[3]/1e3:.1f})" if bb else "NONE"
        print(f"  S{i*2}: M1#{poly_id} bbox={bb_str}")

    # Count groups
    src_groups = set(src_poly_ids.values()) - {-1}
    if len(src_groups) == 1:
        print(f"  → Source: ALL on M1#{src_groups.pop()} ✓")
    elif len(src_groups) == 0:
        print(f"  → Source: NO M1 found!")
    else:
        print(f"  → Source: SPLIT into {len(src_groups)} M1 groups: {src_groups}")
        # Show which strips are in each group
        for gid in sorted(src_groups):
            strips_in = [f"S{i*2}" for i, pid in src_poly_ids.items() if pid == gid]
            print(f"    Group M1#{gid}: {', '.join(strips_in)}")

    # Drain strips
    drn_strips = sd['drain']
    drn_poly_ids = {}
    for i, strip in enumerate(drn_strips):
        gx1 = pcell_x + strip[0]
        gy1 = pcell_y + strip[1]
        gx2 = pcell_x + strip[2]
        gy2 = pcell_y + strip[3]
        cx, cy = (gx1 + gx2) // 2, (gy1 + gy2) // 2
        poly_id, bb = find_m1_poly(cx, cy)
        drn_poly_ids[i] = poly_id
        bb_str = f"({bb[0]/1e3:.1f},{bb[1]/1e3:.1f})-({bb[2]/1e3:.1f},{bb[3]/1e3:.1f})" if bb else "NONE"
        print(f"  D{i*2+1}: M1#{poly_id} bbox={bb_str}")

    drn_groups = set(drn_poly_ids.values()) - {-1}
    if len(drn_groups) == 1:
        print(f"  → Drain: ALL on M1#{drn_groups.pop()} ✓")
    elif len(drn_groups) == 0:
        print(f"  → Drain: NO M1 found!")
    else:
        print(f"  → Drain: SPLIT into {len(drn_groups)} M1 groups: {drn_groups}")
        for gid in sorted(drn_groups):
            strips_in = [f"D{i*2+1}" for i, pid in drn_poly_ids.items() if pid == gid]
            print(f"    Group M1#{gid}: {', '.join(strips_in)}")
