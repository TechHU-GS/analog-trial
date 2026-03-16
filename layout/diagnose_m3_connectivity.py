#!/usr/bin/env python3
"""Check M3 connectivity between source strip via-stack pads and vdd rail.

For each ng>=4 device, find:
1. The M3 pad from each source strip's via stack
2. The M3 vdd rail polygon
3. Whether they are the SAME merged M3 polygon

Also dump the actual M3 merged polygons in the device region to see if there
are gaps/holes in the rail.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m3_connectivity.py
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

# Correct IHP layer numbers
layers = {
    'M1':   layout.layer(8, 0),
    'Via1': layout.layer(19, 0),
    'M2':   layout.layer(10, 0),
    'Via2': layout.layer(29, 0),
    'M3':   layout.layer(30, 0),
    'Via3': layout.layer(49, 0),
    'M4':   layout.layer(50, 0),
}

# Build merged regions
merged = {}
for name, li in layers.items():
    merged[name] = kdb.Region(top.begin_shapes_rec(li)).merged()
    print(f"{name}: {merged[name].count()} merged polygons")

# Index M3 merged polygons
m3_polys = list(merged['M3'].each())
print(f"\nM3 merged polygon count: {len(m3_polys)}")

# Show all M3 polygons with bbox
print("\nAll M3 merged polygons:")
for idx, poly in enumerate(m3_polys):
    bb = poly.bbox()
    print(f"  #{idx}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
          f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

def find_m3_poly_at(x, y, expand=50):
    """Find which merged M3 polygon contains point (x,y) in nm."""
    probe = kdb.Region(kdb.Box(x - expand, y - expand, x + expand, y + expand))
    for idx, poly in enumerate(m3_polys):
        overlap = kdb.Region(poly) & probe
        if not overlap.is_empty():
            return idx
    return -1

def find_via2_from_m1_strip(strip_gx1, strip_gy1, strip_gx2, strip_gy2):
    """Trace M1 strip → Via1 → M2 → Via2 → M3, return M3 polygon index."""
    cx = (strip_gx1 + strip_gx2) // 2
    cy = (strip_gy1 + strip_gy2) // 2

    # Find M1 at strip center
    m1_probe = kdb.Region(kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50))
    m1_hit = merged['M1'] & m1_probe
    if m1_hit.is_empty():
        return {'m1': 'MISS'}

    # Find Via1 touching this M1
    via1_touch = merged['Via1'] & m1_hit.sized(10)
    if via1_touch.is_empty():
        return {'m1': 'OK', 'via1': 'MISS'}

    # Find M2 at Via1 positions
    m2_touch = merged['M2'] & via1_touch.sized(200)
    if m2_touch.is_empty():
        return {'m1': 'OK', 'via1': 'OK', 'm2': 'MISS'}

    # Find Via2 touching M2
    via2_touch = merged['Via2'] & m2_touch.sized(10)
    if via2_touch.is_empty():
        return {'m1': 'OK', 'via1': 'OK', 'm2': 'OK', 'via2': 'MISS'}

    # Find M3 at Via2 positions
    m3_touch = merged['M3'] & via2_touch.sized(200)
    if m3_touch.is_empty():
        return {'m1': 'OK', 'via1': 'OK', 'm2': 'OK', 'via2': 'OK', 'm3': 'MISS'}

    # Get M3 polygon IDs
    m3_ids = set()
    for m3p in m3_touch.each():
        bb = m3p.bbox()
        m3_cx = (bb.left + bb.right) // 2
        m3_cy = (bb.bottom + bb.top) // 2
        m3_id = find_m3_poly_at(m3_cx, m3_cy)
        m3_ids.add(m3_id)
        # Also get the actual M3 pad bbox
        result_bb = (bb.left, bb.bottom, bb.right, bb.top)

    return {
        'm1': 'OK', 'via1': 'OK', 'm2': 'OK', 'via2': 'OK', 'm3': 'OK',
        'm3_ids': m3_ids,
        'm3_pad_bb': result_bb if len(m3_ids) == 1 else None,
    }

# Find vdd rail M3 polygon
# Probe at a known vdd rail location (center of layout, high Y)
# From prior analysis: vdd rail spans roughly (90,176.12)-(115,180)
# Let's find it by probing at center
vdd_probe_x, vdd_probe_y = 100000, 178000  # 100µm, 178µm — well inside rail
vdd_m3_id = find_m3_poly_at(vdd_probe_x, vdd_probe_y)
print(f"\nvdd rail M3 polygon (probed at {vdd_probe_x/1e3:.1f},{vdd_probe_y/1e3:.1f}): #{vdd_m3_id}")
if vdd_m3_id >= 0:
    bb = m3_polys[vdd_m3_id].bbox()
    print(f"  bbox: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Process ng>=4 devices
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
    print(f"  pcell_origin: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f})")

    src_strips = sd['source']

    # Check M3 connectivity for ALL source strips
    all_m3_ids = set()
    for i, strip in enumerate(src_strips):
        gx1 = pcell_x + strip[0]
        gy1 = pcell_y + strip[1]
        gx2 = pcell_x + strip[2]
        gy2 = pcell_y + strip[3]

        result = find_via2_from_m1_strip(gx1, gy1, gx2, gy2)
        m3_ids = result.get('m3_ids', set())
        all_m3_ids.update(m3_ids)

        # Determine chain status
        if result.get('m3') == 'OK':
            on_vdd = vdd_m3_id in m3_ids
            chain_str = f"→ M3#{m3_ids} {'== vdd' if on_vdd else '!= vdd *** DISCONNECTED ***'}"
        else:
            # Find where chain breaks
            chain_parts = ['m1', 'via1', 'm2', 'via2', 'm3']
            for part in chain_parts:
                if result.get(part) == 'MISS':
                    chain_str = f"chain breaks at {part.upper()}"
                    break
            else:
                chain_str = f"unknown: {result}"

        print(f"  S{i*2}: ({gx1/1e3:.1f},{gy1/1e3:.1f})-({gx2/1e3:.1f},{gy2/1e3:.1f})  {chain_str}")

    # Summary
    on_vdd_count = sum(1 for mid in all_m3_ids if mid == vdd_m3_id)
    total_m3 = len(all_m3_ids - {-1})
    print(f"\n  SUMMARY: {len(src_strips)} source strips, {total_m3} distinct M3 polygons")
    if total_m3 == 1 and vdd_m3_id in all_m3_ids:
        print(f"  ✓ All sources on vdd M3 rail")
    elif total_m3 == 0:
        print(f"  ✗ No M3 connections at all")
    else:
        print(f"  ✗ Source strips on {total_m3} different M3 polygons (vdd=#{vdd_m3_id})")

    # Also check drain strips
    drn_strips = sd['drain']
    drn_m3_ids = set()
    print(f"\n  Drain strips:")
    for i, strip in enumerate(drn_strips):
        gx1 = pcell_x + strip[0]
        gy1 = pcell_y + strip[1]
        gx2 = pcell_x + strip[2]
        gy2 = pcell_y + strip[3]

        result = find_via2_from_m1_strip(gx1, gy1, gx2, gy2)
        m3_ids = result.get('m3_ids', set())
        drn_m3_ids.update(m3_ids)

        if result.get('m3') == 'OK':
            on_vdd = vdd_m3_id in m3_ids
            chain_str = f"→ M3#{m3_ids} {'== vdd' if on_vdd else ''}"
        else:
            chain_parts = ['m1', 'via1', 'm2', 'via2', 'm3']
            for part in chain_parts:
                if result.get(part) == 'MISS':
                    chain_str = f"chain breaks at {part.upper()}"
                    break
            else:
                chain_str = f"unknown: {result}"

        print(f"  D{i*2+1}: ({gx1/1e3:.1f},{gy1/1e3:.1f})-({gx2/1e3:.1f},{gy2/1e3:.1f})  {chain_str}")

    drn_total = len(drn_m3_ids - {-1})
    if drn_total:
        print(f"\n  Drain: {drn_total} distinct M3 polygons")

# Also check: are there M3 holes or notches in the vdd rail area?
print(f"\n{'='*70}")
print("M3 detail in device area (X=90-115, Y=175-180):")
device_probe = kdb.Region(kdb.Box(90000, 175000, 115000, 180000))
m3_in_area = merged['M3'] & device_probe
print(f"  M3 polygons in area: {m3_in_area.count()}")
for p in m3_in_area.each():
    bb = p.bbox()
    # Check if it's a small pad or part of the rail
    area_um2 = (bb.width() / 1e3) * (bb.height() / 1e3)
    label = "pad" if area_um2 < 1.0 else "rail segment" if area_um2 < 50 else "rail"
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
          f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f} [{label}]")

# Check the SAME area but for UNMERGED M3 shapes (raw)
print(f"\nRaw (unmerged) M3 shapes in device area:")
m3_raw = kdb.Region(top.begin_shapes_rec(layers['M3']))
m3_raw_in_area = m3_raw & device_probe
print(f"  Raw M3 shapes: {m3_raw_in_area.count()}")
# Show first 30
count = 0
for p in m3_raw_in_area.each():
    bb = p.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
          f"size={bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
    count += 1
    if count >= 30:
        print(f"  ... (truncated, {m3_raw_in_area.count() - 30} more)")
        break
