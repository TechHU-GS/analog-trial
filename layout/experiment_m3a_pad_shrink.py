#!/usr/bin/env python3
"""Minimal M3.a experiment: shrink Via2 M3 pads at 2 specific locations.

Tests hypothesis: shrinking 380nm M3 pad to 200nm (matching M3_MIN_W stub width)
eliminates M3.a thin-wing violations when pad merges with connecting stub/wire.

Picks:
  Case A (merged): near an M3.a violation where pad + 200nm stub
  Case B (standalone): near an M3.a violation where pad has no adjacent stub

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_pad_shrink.py
"""
import os, sys, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'
GDS_OUT = '/tmp/experiment_m3a_pad_shrink.gds'

layout = kdb.Layout()
layout.read(GDS_IN)
top = layout.top_cell()

li_m3 = layout.layer(30, 0)   # Metal3
li_v2 = layout.layer(29, 0)   # Via2

# --- Collect ALL M3 shapes with their geometry ---
m3_shapes = []
for si in top.begin_shapes_rec(li_m3):
    bb = si.shape().bbox().transformed(si.trans())
    m3_shapes.append(bb)

print(f"Total M3 shapes: {len(m3_shapes)}")

# --- Find all 380x380 M3 pads (Via2 M3 pads) ---
via2_m3_pads = []
for si in top.begin_shapes_rec(li_m3):
    bb = si.shape().bbox().transformed(si.trans())
    w, h = bb.width(), bb.height()
    if 370 <= w <= 390 and 370 <= h <= 390:
        via2_m3_pads.append((bb, si))

print(f"Found {len(via2_m3_pads)} Via2 M3 pads (370-390nm square)")

# --- For each pad, check if it merges with neighboring M3 shapes ---
def find_neighbors(pad_bb, all_shapes, margin=5):
    """Find M3 shapes that overlap or touch the pad (within margin nm)."""
    probe = kdb.Box(pad_bb.left - margin, pad_bb.bottom - margin,
                    pad_bb.right + margin, pad_bb.top + margin)
    neighbors = []
    for bb in all_shapes:
        if bb == pad_bb:
            continue
        if probe.overlaps(bb) or pad_bb.overlaps(bb):
            neighbors.append(bb)
    return neighbors

# Classify each pad
merged_pads = []
standalone_pads = []
for pad_bb, si in via2_m3_pads:
    neighbors = find_neighbors(pad_bb, [bb for bb, _ in via2_m3_pads] +
                               [bb for bb in m3_shapes if bb.width() != pad_bb.width() or bb.height() != pad_bb.height()])
    # Actually just check all m3_shapes
    neighbors = find_neighbors(pad_bb, m3_shapes)
    if neighbors:
        merged_pads.append((pad_bb, si, neighbors))
    else:
        standalone_pads.append((pad_bb, si))

print(f"Merged pads: {len(merged_pads)}, Standalone pads: {len(standalone_pads)}")

# --- Identify the specific experiment cases ---
# Parse the DRC violations to find M3.a locations
import xml.etree.ElementTree as ET
import re

LYRDB = '/tmp/drc_rout_eco/ptat_vco_ptat_vco_full.lyrdb'
if not os.path.exists(LYRDB):
    # Try main DRC path
    for p in ['/tmp/drc_ci_verify/ptat_vco_ptat_vco_full.lyrdb',
              '/tmp/drc_main/ptat_vco_ptat_vco_full.lyrdb']:
        if os.path.exists(p):
            LYRDB = p
            break

print(f"\nUsing DRC report: {LYRDB}")

tree = ET.parse(LYRDB)
root = tree.getroot()
items_elem = root.find('items')

m3a_viols = []
for item in items_elem.findall('item'):
    cat = item.find('category').text.strip("'")
    if cat != 'M3.a':
        continue
    vals = item.find('values')
    for v in vals.findall('value'):
        text = v.text or ''
        nums = [int(n) for n in re.findall(r'-?\d+', text)]
        if nums:
            cx = sum(nums[0::2]) // len(nums[0::2])
            cy = sum(nums[1::2]) // len(nums[1::2])
            m3a_viols.append((cx, cy, text[:80]))

print(f"\nM3.a violations: {len(m3a_viols)}")

# --- For each M3.a violation, find the nearest Via2 M3 pad ---
print(f"\n{'='*70}")
print("M3.a violations and nearby Via2 M3 pads:")
print(f"{'='*70}")

for vx, vy, detail in m3a_viols[:10]:
    # Find nearest pad
    best_dist = 999999
    best_pad = None
    is_merged = None
    for pad_bb, si, neighbors in merged_pads:
        cx = (pad_bb.left + pad_bb.right) // 2
        cy = (pad_bb.bottom + pad_bb.top) // 2
        dist = abs(cx - vx) + abs(cy - vy)
        if dist < best_dist:
            best_dist = dist
            best_pad = pad_bb
            is_merged = True
    for pad_bb, si in standalone_pads:
        cx = (pad_bb.left + pad_bb.right) // 2
        cy = (pad_bb.bottom + pad_bb.top) // 2
        dist = abs(cx - vx) + abs(cy - vy)
        if dist < best_dist:
            best_dist = dist
            best_pad = pad_bb
            is_merged = False

    if best_pad and best_dist < 500:
        ntype = "MERGED" if is_merged else "STANDALONE"
        # Find the neighbor shapes for merged pads
        neighbor_desc = ""
        if is_merged:
            for pad_bb, si, neighbors in merged_pads:
                if pad_bb == best_pad:
                    for nb in neighbors[:3]:
                        w, h = nb.width(), nb.height()
                        neighbor_desc += f" + {w}x{h}nm"
                    break
        print(f"  viol ({vx/1e3:.2f}, {vy/1e3:.2f}) → pad ({best_pad.left/1e3:.2f},{best_pad.bottom/1e3:.2f})-"
              f"({best_pad.right/1e3:.2f},{best_pad.top/1e3:.2f}) dist={best_dist}nm [{ntype}]{neighbor_desc}")
    else:
        print(f"  viol ({vx/1e3:.2f}, {vy/1e3:.2f}) → no nearby pad (dist={best_dist}nm)")

if len(m3a_viols) > 10:
    print(f"  ... +{len(m3a_viols)-10} more")

# --- Now do the experiment: shrink ALL Via2 M3 pads from 380nm to 200nm ---
# This tests the hypothesis globally (fastest way to get definitive data)
# We keep the original via2 cut and just shrink the M3 pad
print(f"\n{'='*70}")
print("EXPERIMENT: Shrinking ALL Via2 M3 pads from 380nm to 200nm")
print(f"{'='*70}")

NEW_PAD = 200  # Match M3_MIN_W (stub width)
shrink_count = 0

# We need to work with the actual cell shapes, not recursive iteration
# Collect shapes to modify in each cell
for cell_idx in range(layout.cells()):
    cell = layout.cell(cell_idx)
    shapes_to_remove = []
    shapes_to_add = []

    for si in cell.shapes(li_m3).each():
        bb = si.bbox()
        w, h = bb.width(), bb.height()
        if 370 <= w <= 390 and 370 <= h <= 390:
            # This is a Via2 M3 pad — shrink it
            cx = (bb.left + bb.right) // 2
            cy = (bb.bottom + bb.top) // 2
            hp = NEW_PAD // 2  # 100nm
            new_box = kdb.Box(cx - hp, cy - hp, cx + hp, cy + hp)
            shapes_to_remove.append(si.dup())
            shapes_to_add.append(new_box)

    # Apply changes
    for si in shapes_to_remove:
        cell.shapes(li_m3).erase(si)
    for box in shapes_to_add:
        cell.shapes(li_m3).insert(box)
    shrink_count += len(shapes_to_add)

print(f"Shrunk {shrink_count} M3 pads from ~380nm to {NEW_PAD}nm")

# Save modified GDS
layout.write(GDS_OUT)
print(f"Saved to: {GDS_OUT}")
print(f"\nNext: run DRC on {GDS_OUT} and compare M3.a count")
print("Expected: M3.a should decrease (no thin wings at pad-stub junctions)")
print("Watch for: M3.c (enclosure), M3.c1 (endcap), M3.d (min area) regressions")
