#!/usr/bin/env python3
"""Targeted M3.a experiment: understand exact geometry at each violation.

For each M3.a violation:
1. Find the exact edge-pair location (µm coordinates)
2. Identify the Via2 M3 pad and connecting stub/wire
3. Determine: is via at END of stub (needs extension) or MIDDLE of wire?
4. Classify the fix required

Then: patch just 2 specific cases with the correct fix and re-run DRC.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_targeted.py
"""
import os, re, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import xml.etree.ElementTree as ET

# ── Parse M3.a violations with proper coordinate handling ──
LYRDB = '/tmp/drc_rout_eco/ptat_vco_ptat_vco_full.lyrdb'
if not os.path.exists(LYRDB):
    for p in ['/tmp/drc_ci_verify/ptat_vco_ptat_vco_full.lyrdb',
              '/tmp/drc_main/ptat_vco_ptat_vco_full.lyrdb']:
        if os.path.exists(p):
            LYRDB = p
            break

tree = ET.parse(LYRDB)
root = tree.getroot()
items_elem = root.find('items')

# First, check what coordinate format the lyrdb uses
sample_item = None
for item in items_elem.findall('item'):
    cat = item.find('category').text.strip("'")
    if cat == 'M3.a':
        sample_item = item
        break

if sample_item:
    vals = sample_item.find('values')
    for v in vals.findall('value'):
        print(f"Sample M3.a value: {v.text[:200]}")
        break

# Parse edge-pairs properly
# lyrdb edge-pairs format: "edge-pair(x1,y1;x2,y2 / x3,y3;x4,y4)" where coords are in nm
m3a_viols = []
for item in items_elem.findall('item'):
    cat = item.find('category').text.strip("'")
    if cat != 'M3.a':
        continue
    vals = item.find('values')
    for v in vals.findall('value'):
        text = v.text or ''
        # Parse coordinates from edge-pair format
        # Format: "edge-pair (x1,y1;x2,y2)/(x3,y3;x4,y4)" with coords in DBU (nm)
        pairs = re.findall(r'\(([^)]+)\)', text)
        all_coords = []
        for p in pairs:
            parts = p.replace(';', ',').split(',')
            for i in range(0, len(parts)-1, 2):
                try:
                    all_coords.append((float(parts[i]), float(parts[i+1])))
                except ValueError:
                    pass
        if all_coords:
            # Center of all coordinate points
            cx = sum(c[0] for c in all_coords) / len(all_coords)
            cy = sum(c[1] for c in all_coords) / len(all_coords)
            m3a_viols.append((cx, cy, text[:120]))

print(f"\nM3.a violations: {len(m3a_viols)}")
for i, (cx, cy, detail) in enumerate(m3a_viols[:5]):
    print(f"  #{i}: ({cx:.1f}, {cy:.1f}) → {detail}")

# ── Load GDS ──
GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m3 = layout.layer(30, 0)
li_v2 = layout.layer(29, 0)
li_v3 = layout.layer(36, 0)  # Via3

# Collect all M3 shapes
m3_shapes = []
for si in top.begin_shapes_rec(li_m3):
    bb = si.shape().bbox().transformed(si.trans())
    m3_shapes.append(bb)

# Collect Via2 locations
via2_locs = []
for si in top.begin_shapes_rec(li_v2):
    bb = si.shape().bbox().transformed(si.trans())
    cx = (bb.left + bb.right) // 2
    cy = (bb.bottom + bb.top) // 2
    via2_locs.append((cx, cy))

# Collect Via3 locations
via3_locs = set()
for si in top.begin_shapes_rec(li_v3):
    bb = si.shape().bbox().transformed(si.trans())
    cx = (bb.left + bb.right) // 2
    cy = (bb.bottom + bb.top) // 2
    via3_locs.add((cx, cy))

print(f"\nVia2 locations: {len(via2_locs)}")
print(f"Via3 locations: {len(via3_locs)}")

# ── For each M3.a violation, probe nearby shapes ──
def classify_shape(bb):
    w, h = bb.width(), bb.height()
    min_dim, max_dim = min(w, h), max(w, h)
    if min_dim >= 2500:
        return 'power_rail'
    if 370 <= w <= 390 and 370 <= h <= 390:
        return 'via2_pad'
    if min_dim <= 220 and max_dim > 2000:
        return 'power_vbar'
    if min_dim <= 220 and max_dim <= 600:
        return 'stub'
    if min_dim <= 320 and max_dim > 600:
        return 'signal_wire'
    if 350 <= min_dim <= 420 and 350 <= max_dim <= 420:
        return 'via_pad'
    return f'other({w}x{h})'

def probe(cx, cy, radius=500):
    """Find M3 shapes near a point."""
    probe_box = kdb.Box(int(cx) - radius, int(cy) - radius,
                        int(cx) + radius, int(cy) + radius)
    found = []
    for bb in m3_shapes:
        if probe_box.overlaps(bb):
            cls = classify_shape(bb)
            found.append((cls, bb))
    return found

def find_nearest_via2(cx, cy, radius=500):
    """Find nearest Via2 to a point."""
    best = None
    best_dist = radius
    for vx, vy in via2_locs:
        dist = abs(vx - cx) + abs(vy - cy)
        if dist < best_dist:
            best_dist = dist
            best = (vx, vy)
    return best, best_dist

def has_via3(cx, cy, radius=200):
    """Check if there's a Via3 near this location."""
    for vx, vy in via3_locs:
        if abs(vx - cx) + abs(vy - cy) < radius:
            return True
    return False

# Determine coordinate scale - check if lyrdb coords are in nm or µm
# Try to match violation coords to known Via2 pad locations
# If they're in µm, multiply by 1000 to get nm
scale_factor = 1.0
if m3a_viols:
    cx0, cy0, _ = m3a_viols[0]
    # Try nm first
    v2_nm, d_nm = find_nearest_via2(cx0, cy0, radius=5000)
    # Try µm (multiply by 1000)
    v2_um, d_um = find_nearest_via2(cx0 * 1000, cy0 * 1000, radius=5000)
    print(f"\nScale detection: viol ({cx0:.1f}, {cy0:.1f})")
    print(f"  As nm: nearest via2 = {v2_nm}, dist = {d_nm}")
    print(f"  As µm: nearest via2 = {v2_um}, dist = {d_um}")
    if d_um < d_nm:
        scale_factor = 1000.0
        print(f"  → Using µm scale (×1000)")
    else:
        print(f"  → Using nm scale (×1)")

print(f"\n{'='*80}")
print("M3.a violation analysis (all violations)")
print(f"{'='*80}")

# Classify each violation
viol_classes = {
    'pad_stub': [],      # pad meets stub (width mismatch)
    'pad_wire': [],      # pad meets signal wire
    'pad_vbar': [],      # pad meets power vbar
    'wire_vbar': [],     # signal wire meets vbar
    'other': [],
}

for i, (cx_raw, cy_raw, detail) in enumerate(m3a_viols):
    cx = cx_raw * scale_factor
    cy = cy_raw * scale_factor

    shapes = probe(cx, cy, radius=400)
    types = [t for t, _ in shapes]
    bboxes = [(t, bb) for t, bb in shapes]

    # Find nearest via2
    v2, v2_dist = find_nearest_via2(cx, cy, radius=1000)
    v3_present = has_via3(cx, cy) if v2 else False

    # Classify
    type_set = set(types)
    if 'via2_pad' in type_set and 'stub' in type_set:
        viol_classes['pad_stub'].append(i)
    elif 'via2_pad' in type_set and 'signal_wire' in type_set:
        viol_classes['pad_wire'].append(i)
    elif 'via2_pad' in type_set and 'power_vbar' in type_set:
        viol_classes['pad_vbar'].append(i)
    elif 'signal_wire' in type_set and 'power_vbar' in type_set:
        viol_classes['wire_vbar'].append(i)
    else:
        viol_classes['other'].append(i)

    # Print detail for each
    shape_desc = []
    for cls, bb in bboxes[:5]:
        shape_desc.append(f"{cls}({bb.left},{bb.bottom};{bb.right},{bb.top})")

    via_info = f"via2@({v2[0]},{v2[1]}) dist={v2_dist}" if v2 else "no_via2"
    v3_info = "+via3" if v3_present else ""

    print(f"  #{i:2d} ({cx:.0f},{cy:.0f}): {via_info}{v3_info}")
    for s in shape_desc:
        print(f"       {s}")

print(f"\n{'='*80}")
print("Summary by category:")
print(f"{'='*80}")
for cat, indices in viol_classes.items():
    print(f"  {cat:15s}: {len(indices)} violations")

# ── Check which via2 pads have Via3 on top ──
via2_with_via3 = 0
via2_without_via3 = 0
for vx, vy in via2_locs:
    if has_via3(vx, vy):
        via2_with_via3 += 1
    else:
        via2_without_via3 += 1

print(f"\n{'='*80}")
print("Via2-Via3 co-location analysis:")
print(f"{'='*80}")
print(f"  Via2 with Via3 on top: {via2_with_via3}")
print(f"  Via2 without Via3:     {via2_without_via3}")
print(f"  Total Via2:            {len(via2_locs)}")

# ── For vias with no Via3, analyze M3 shape context ──
print(f"\n{'='*80}")
print("Via2-only pad analysis (no Via3 on top):")
print(f"{'='*80}")

# For each via2 pad, find neighbors and check stub direction
for vx, vy in sorted(via2_locs)[:20]:
    if has_via3(vx, vy):
        continue
    neighbors = probe(vx, vy, radius=500)
    pad_shapes = [(t, bb) for t, bb in neighbors if t == 'via2_pad']
    other_shapes = [(t, bb) for t, bb in neighbors if t != 'via2_pad']

    # Determine stub direction
    stub_dirs = []
    for t, bb in other_shapes:
        if t in ('stub', 'signal_wire', 'power_vbar'):
            bcx = (bb.left + bb.right) // 2
            bcy = (bb.bottom + bb.top) // 2
            if abs(bcx - vx) < abs(bcy - vy):
                stub_dirs.append('V' if bcy > vy else 'v')  # vertical up/down
            else:
                stub_dirs.append('H' if bcx > vx else 'h')  # horizontal right/left

    other_desc = ', '.join(f"{t}({bb.width()}×{bb.height()})" for t, bb in other_shapes[:3])
    print(f"  via2@({vx},{vy}): {other_desc} dirs={''.join(stub_dirs)}")
