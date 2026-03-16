#!/usr/bin/env python3
"""M3.a experiment v3: replace Via2 M3 pads with cross-shaped extensions.

Hypothesis: M3.a thin wings come from width mismatch at pad-stub junctions.
Fix: instead of a square pad, draw a 200nm-wide cross centered on via2,
extending 50nm past the via edge in all 4 directions.

This provides:
- M3.c: 5nm side enclosure (200nm shape, 190nm via → 5nm each side) ✓
- M3.c1: 50nm endcap via cross arms → two_opposite_sides_allowed ✓
- M3.a: 200nm width everywhere → no thin wings ✓
- M3.d: merged with connecting stub → area >> 144000nm² ✓

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_pad_v3.py
"""
import os, subprocess, glob
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'
GDS_OUT = '/tmp/exp_m3a_cross.gds'

layout = kdb.Layout()
layout.read(GDS_IN)
top = layout.top_cell()

li_m3 = layout.layer(30, 0)   # Metal3
li_v2 = layout.layer(29, 0)   # Via2

# --- Step 1: Collect all Via2 cut locations ---
via2_locs = set()
for si in top.begin_shapes_rec(li_v2):
    bb = si.shape().bbox().transformed(si.trans())
    cx = (bb.left + bb.right) // 2
    cy = (bb.bottom + bb.top) // 2
    via2_locs.add((cx, cy))

print(f"Via2 cut locations: {len(via2_locs)}")

# --- Step 2: Remove all 380nm Via2 M3 pads ---
removed = 0
for cell_idx in range(layout.cells()):
    cell = layout.cell(cell_idx)
    to_remove = []
    for si in cell.shapes(li_m3).each():
        bb = si.bbox()
        w, h = bb.width(), bb.height()
        if 370 <= w <= 390 and 370 <= h <= 390:
            to_remove.append(si.dup())
    for si in to_remove:
        cell.shapes(li_m3).erase(si)
    removed += len(to_remove)

print(f"Removed {removed} M3 pads (370-390nm square)")

# --- Step 3: Draw cross-shaped M3 at each Via2 location ---
# Cross = two rectangles:
#   Horizontal bar: 200nm tall × (190+2×50)=290nm wide
#   Vertical bar:   (190+2×50)=290nm tall × 200nm wide
# This gives 50nm endcap past via edge in all 4 directions
# Width is always 200nm (M3_MIN_W) → no thin wings

VIA2_HW = 190 // 2   # 95nm half-via
ENDCAP = 50           # M3.c1 endcap enclosure
M3_HW = 200 // 2     # 100nm half-width (M3_MIN_W / 2)

crosses_drawn = 0
for cx, cy in via2_locs:
    # Horizontal bar (provides N-S endcap check → E-W extension)
    h_bar = kdb.Box(cx - VIA2_HW - ENDCAP, cy - M3_HW,
                    cx + VIA2_HW + ENDCAP, cy + M3_HW)
    # Vertical bar (provides E-W endcap check → N-S extension)
    v_bar = kdb.Box(cx - M3_HW, cy - VIA2_HW - ENDCAP,
                    cx + M3_HW, cy + VIA2_HW + ENDCAP)

    top.shapes(li_m3).insert(h_bar)
    top.shapes(li_m3).insert(v_bar)
    crosses_drawn += 1

print(f"Drew {crosses_drawn} cross-shaped M3 extensions")

# --- Step 4: Save and run DRC ---
layout.write(GDS_OUT)
print(f"Saved: {GDS_OUT}")

print("\nRunning DRC...")
cmd = [
    'python3',
    os.path.expanduser('~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py'),
    f'--path={GDS_OUT}',
    '--topcell=ptat_vco',
    '--run_dir=/tmp/drc_m3a_cross',
    '--mp=1', '--no_density'
]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

# Parse results
import xml.etree.ElementTree as ET
lyrdbs = glob.glob('/tmp/drc_m3a_cross/*_full.lyrdb')
if lyrdbs:
    tree = ET.parse(lyrdbs[0])
    root = tree.getroot()
    items = root.find('items')
    counts = {}
    for item in items.findall('item'):
        cat = item.find('category').text.strip("'")
        counts[cat] = counts.get(cat, 0) + 1

    baseline = {'M1.b':32, 'M3.a':26, 'M2.b':12, 'NW.b1':6, 'Cnt.d':4, 'M3.b':4,
                'CntB.b2':3, 'M2.c1':3, 'M1.d':2, 'Rhi.d':2, 'V2.c1':1, 'Rppd.c':1}

    print(f"\n{'='*70}")
    print("RESULTS: Cross-shaped M3 extension (200nm wide, 50nm endcap)")
    print(f"{'='*70}")
    print(f"  {'Rule':15s} {'Baseline':>10s} {'Cross':>10s} {'Delta':>8s}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*8}")
    all_rules = sorted(set(list(baseline.keys()) + list(counts.keys())))
    total_b, total_e = 0, 0
    for rule in all_rules:
        b = baseline.get(rule, 0)
        e = counts.get(rule, 0)
        total_b += b
        total_e += e
        delta = e - b
        m = '***' if delta != 0 else ''
        print(f"  {rule:15s} {b:10d} {e:10d} {delta:+8d} {m}")
    print(f"  {'TOTAL':15s} {total_b:10d} {total_e:10d} {total_e-total_b:+8d}")
else:
    print("ERROR: No lyrdb file found")
    print(result.stderr[-500:] if result.stderr else "no stderr")
