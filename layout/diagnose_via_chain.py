#!/usr/bin/env python3
"""Trace full via stack connectivity for each source strip of ng>=4 devices.

For each source strip, trace:
  M1 → Via1 → M2 → Via2 → M3
Report which merged polygon each strip reaches at each layer.
Identify if all strips reach the same merged polygon at ANY layer.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_via_chain.py
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

# Layers
layers = {
    'M1': layout.layer(8, 0),
    'Via1': layout.layer(19, 0),
    'M2': layout.layer(10, 0),
    'Via2': layout.layer(30, 0),
    'M3': layout.layer(11, 0),
}

# Build merged regions
merged = {}
for name, li in layers.items():
    merged[name] = kdb.Region(top.begin_shapes_rec(li)).merged()
    print(f"{name}: {merged[name].count()} merged polygons")

# Index merged polygons for identity checking
poly_index = {}
for name in ['M1', 'M2', 'M3']:
    poly_index[name] = list(merged[name].each())

def find_poly_id(layer_name, gx, gy, expand=10):
    """Find which merged polygon contains point, return (index, bbox)."""
    probe = kdb.Region(kdb.Box(gx - expand, gy - expand, gx + expand, gy + expand))
    for idx, poly in enumerate(poly_index[layer_name]):
        if not (kdb.Region(poly) & probe).is_empty():
            bb = poly.bbox()
            return idx, (bb.left, bb.bottom, bb.right, bb.top)
    return -1, None

def trace_strip_via_chain(gx1, gy1, gx2, gy2):
    """Trace via chain from an M1 strip region through all layers."""
    result = {}

    # Start with M1 polygon containing strip center
    cx, cy = (gx1 + gx2) // 2, (gy1 + gy2) // 2
    m1_id, m1_bb = find_poly_id('M1', cx, cy)
    result['m1'] = {'id': m1_id, 'bb': m1_bb}

    if m1_id < 0:
        return result

    # Find the full M1 polygon
    m1_poly = poly_index['M1'][m1_id]
    m1_region = kdb.Region(m1_poly)

    # Find Via1 touching this M1
    via1_touch = merged['Via1'] & m1_region
    result['via1_count'] = via1_touch.count()

    if via1_touch.is_empty():
        return result

    # Find M2 touching these Via1s
    via1_expanded = via1_touch.sized(100)  # generous expansion
    m2_touch = merged['M2'] & via1_expanded
    result['m2_count'] = m2_touch.count()

    # For each M2 polygon, get its ID
    m2_ids = set()
    for m2p in m2_touch.each():
        m2_bb = m2p.bbox()
        m2_cx = (m2_bb.left + m2_bb.right) // 2
        m2_cy = (m2_bb.bottom + m2_bb.top) // 2
        m2_id, m2_bb_full = find_poly_id('M2', m2_cx, m2_cy)
        if m2_id >= 0:
            m2_ids.add(m2_id)
            result['m2'] = {'id': m2_id, 'bb': m2_bb_full}
    result['m2_ids'] = m2_ids

    if not m2_ids:
        return result

    # Find Via2 touching these M2 polygons
    for m2_id in m2_ids:
        m2_poly = poly_index['M2'][m2_id]
        m2_region = kdb.Region(m2_poly)
        via2_touch = merged['Via2'] & m2_region
        result['via2_count'] = via2_touch.count()

        if not via2_touch.is_empty():
            # Find M3
            via2_expanded = via2_touch.sized(100)
            m3_touch = merged['M3'] & via2_expanded
            result['m3_count'] = m3_touch.count()

            m3_ids = set()
            for m3p in m3_touch.each():
                m3_bb = m3p.bbox()
                m3_cx = (m3_bb.left + m3_bb.right) // 2
                m3_cy = (m3_bb.bottom + m3_bb.top) // 2
                m3_id, m3_bb_full = find_poly_id('M3', m3_cx, m3_cy)
                if m3_id >= 0:
                    m3_ids.add(m3_id)
                    result['m3'] = {'id': m3_id, 'bb': m3_bb_full}
            result['m3_ids'] = m3_ids

    return result

# Process devices
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

    src_strips = sd['source']
    all_m1_ids = set()
    all_m2_ids = set()
    all_m3_ids = set()

    for i, strip in enumerate(src_strips):
        gx1 = pcell_x + strip[0]
        gy1 = pcell_y + strip[1]
        gx2 = pcell_x + strip[2]
        gy2 = pcell_y + strip[3]

        chain = trace_strip_via_chain(gx1, gy1, gx2, gy2)
        m1_id = chain.get('m1', {}).get('id', -1)
        via1_cnt = chain.get('via1_count', 0)
        m2_ids = chain.get('m2_ids', set())
        via2_cnt = chain.get('via2_count', 0)
        m3_ids = chain.get('m3_ids', set())

        all_m1_ids.add(m1_id)
        all_m2_ids.update(m2_ids)
        all_m3_ids.update(m3_ids)

        chain_str = f"M1#{m1_id}"
        if via1_cnt:
            chain_str += f" → {via1_cnt}xV1"
            if m2_ids:
                chain_str += f" → M2#{m2_ids}"
                if via2_cnt:
                    chain_str += f" → {via2_cnt}xV2"
                    if m3_ids:
                        chain_str += f" → M3#{m3_ids}"
        print(f"  S{i*2}: ({gx1/1e3:.1f},{gy1/1e3:.1f})-({gx2/1e3:.1f},{gy2/1e3:.1f})  {chain_str}")

    # Summary
    m1_merged = len(all_m1_ids) == 1
    m2_merged = len(all_m2_ids) == 1 and all_m2_ids != {-1} and len(all_m2_ids) > 0
    m3_merged = len(all_m3_ids) == 1 and all_m3_ids != {-1} and len(all_m3_ids) > 0

    print(f"\n  SUMMARY:")
    print(f"    M1: {len(all_m1_ids)} groups → {'CONNECTED' if m1_merged else 'SPLIT'}")
    if all_m2_ids - {-1}:  # some strips have M2
        print(f"    M2: {len(all_m2_ids - {-1})} groups → {'CONNECTED' if m2_merged else 'SPLIT' if len(all_m2_ids - {-1}) > 1 else 'partial'}")
    else:
        print(f"    M2: no Via1 connections")
    if all_m3_ids - {-1}:
        print(f"    M3: {len(all_m3_ids - {-1})} groups → {'CONNECTED' if m3_merged else 'SPLIT'}")
    else:
        print(f"    M3: no Via2→M3 connections")

    # Also check drain strips for pmos_cs8
    if 'pmos_cs8' in dtype:
        drn_strips = sd['drain']
        print(f"\n  Drain strips:")
        drn_m1_ids = set()
        for i, strip in enumerate(drn_strips):
            gx1 = pcell_x + strip[0]
            gy1 = pcell_y + strip[1]
            gx2 = pcell_x + strip[2]
            gy2 = pcell_y + strip[3]
            chain = trace_strip_via_chain(gx1, gy1, gx2, gy2)
            m1_id = chain.get('m1', {}).get('id', -1)
            drn_m1_ids.add(m1_id)
            print(f"  D{i*2+1}: M1#{m1_id}")
        print(f"    M1: {len(drn_m1_ids)} groups → {'CONNECTED' if len(drn_m1_ids)==1 else 'SPLIT'}")
