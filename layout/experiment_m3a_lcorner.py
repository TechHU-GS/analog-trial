#!/usr/bin/env python3
"""M3.a experiment: pad shrink + L-corner fill for Case A.

The L-shaped stub at Case A has two bars:
  H-bar: (87200, 216900; 87350, 217100) — 150nm × 200nm
  V-bar: (87100, 217000; 87300, 217150) — 200nm × 150nm

L-junction creates thin protrusions where bars extend < 200nm past each other.
Fix: replace two bars with their bounding-box rectangle (no L-corner notch).

Then add the 200nm pad + extension for M3.c1.

Also apply to Case B for comparison.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_lcorner.py
"""
import os, subprocess, glob, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'
GDS_OUT = '/tmp/exp_m3a_lcorner.gds'

VIA2_HW = 190 // 2
ENDCAP = 50
M3_HW = 200 // 2

layout = kdb.Layout()
layout.read(GDS_IN)
top = layout.top_cell()
li_m3 = layout.layer(30, 0)

# --- Helpers ---
def shapes_near(cx, cy, radius=500):
    """Find M3 shapes near a point in top cell."""
    probe = kdb.Box(cx - radius, cy - radius, cx + radius, cy + radius)
    found = []
    for si in top.shapes(li_m3).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            found.append((si, bb))
    return found

# --- Case A: via2@(87350, 217000) ---
print("CASE A: via2@(87350, 217000)")
print("  Removing: pad + stubs")

# Find all M3 shapes near this via (pad + stubs)
near_a = shapes_near(87350, 217000, radius=400)
removed_a = []
for si, bb in near_a:
    w, h = bb.width(), bb.height()
    # Remove pad (380×380) and stubs (small shapes)
    if (370 <= w <= 390 and 370 <= h <= 390) or (max(w,h) <= 250):
        print(f"    Remove: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {w}×{h}")
        removed_a.append(si)

# Don't remove signal_wire shapes (they're large)
for si in removed_a:
    top.shapes(li_m3).erase(si)

# Draw replacement: bounding-box rectangle of L-stub + pad + extension
# Original stubs:
#   H-bar: (87200, 216900; 87350, 217100)
#   V-bar: (87100, 217000; 87300, 217150)
# Bounding box: (87100, 216900; 87350, 217150) = 250×250nm
# Pad extends via rightward to 87450, extension to 87495

# Strategy: draw a single large M3 shape covering the bounding box of
# (route_vertex → via_center) plus M3.c1 endcap extension

# Route vertex at (87200, 217150), via at (87350, 217000)
rx_a, ry_a = 87200, 217150  # estimated from stub geometry
ap_x_a, ap_y_a = 87350, 217000

# Bounding box of L-path, expanded by M3_HW
l_x1 = min(rx_a, ap_x_a) - M3_HW   # 87200-100 = 87100
l_y1 = min(ry_a, ap_y_a) - M3_HW   # 217000-100 = 216900
l_x2 = max(rx_a, ap_x_a) + M3_HW   # 87350+100 = 87450
l_y2 = max(ry_a, ap_y_a) + M3_HW   # 217150+100 = 217250

# Add M3.c1 endcap: extend 50nm past via edge in ALL directions
# where the bounding box doesn't already provide enough
via_l = ap_x_a - VIA2_HW  # 87255
via_r = ap_x_a + VIA2_HW  # 87445
via_b = ap_y_a - VIA2_HW  # 216905
via_t = ap_y_a + VIA2_HW  # 217095

# Check each side
need_ext_right = (l_x2 - via_r) < ENDCAP   # 87450-87445 = 5 < 50 → yes
need_ext_left  = (via_l - l_x1) < ENDCAP   # 87255-87100 = 155 → no
need_ext_top   = (l_y2 - via_t) < ENDCAP   # 217250-217095 = 155 → no
need_ext_bot   = (via_b - l_y1) < ENDCAP   # 216905-216900 = 5 < 50 → yes

if need_ext_right: l_x2 = via_r + ENDCAP  # 87495
if need_ext_left:  l_x1 = via_l - ENDCAP
if need_ext_top:   l_y2 = via_t + ENDCAP
if need_ext_bot:   l_y1 = via_b - ENDCAP  # 216855

bbox_a = kdb.Box(l_x1, l_y1, l_x2, l_y2)
top.shapes(li_m3).insert(bbox_a)
print(f"  New bbox: ({bbox_a.left},{bbox_a.bottom};{bbox_a.right},{bbox_a.top}) = {bbox_a.width()}×{bbox_a.height()}")

# Check M3.a: all dimensions ≥ 200nm?
print(f"  Width: {bbox_a.width()}nm, Height: {bbox_a.height()}nm")
print(f"  Min dimension: {min(bbox_a.width(), bbox_a.height())}nm {'✓' if min(bbox_a.width(), bbox_a.height()) >= 200 else '✗'}")

# M3 enclosure of via
print(f"  Enclosure: L={via_l-bbox_a.left}, R={bbox_a.right-via_r}, B={via_b-bbox_a.bottom}, T={bbox_a.top-via_t}")


# --- Case B: via2@(41470, 62630) ---
print("\nCASE B: via2@(41470, 62630)")

near_b = shapes_near(41470, 62630, radius=400)
removed_b = []
for si, bb in near_b:
    w, h = bb.width(), bb.height()
    if (370 <= w <= 390 and 370 <= h <= 390) or (max(w,h) <= 250):
        print(f"    Remove: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {w}×{h}")
        removed_b.append(si)

for si in removed_b:
    top.shapes(li_m3).erase(si)

# Original stubs from probe data:
#   stub(41350,62530;41470,62730) = 120×200 — H-bar
#   stub(41250,62630;41450,62800) = 200×170 — V-bar
# Route vertex at ~(41350, 62800)? Or look at stub geometry
rx_b = 41350   # min x of H-bar
ry_b = 62800   # max y of V-bar
ap_x_b, ap_y_b = 41470, 62630

l_x1 = min(rx_b, ap_x_b) - M3_HW   # 41350-100 = 41250
l_y1 = min(ry_b, ap_y_b) - M3_HW   # 62630-100 = 62530
l_x2 = max(rx_b, ap_x_b) + M3_HW   # 41470+100 = 41570
l_y2 = max(ry_b, ap_y_b) + M3_HW   # 62800+100 = 62900

via_l = ap_x_b - VIA2_HW  # 41375
via_r = ap_x_b + VIA2_HW  # 41565
via_b = ap_y_b - VIA2_HW  # 62535
via_t = ap_y_b + VIA2_HW  # 62725

need_ext_right = (l_x2 - via_r) < ENDCAP
need_ext_left  = (via_l - l_x1) < ENDCAP
need_ext_top   = (l_y2 - via_t) < ENDCAP
need_ext_bot   = (via_b - l_y1) < ENDCAP

if need_ext_right: l_x2 = via_r + ENDCAP
if need_ext_left:  l_x1 = via_l - ENDCAP
if need_ext_top:   l_y2 = via_t + ENDCAP
if need_ext_bot:   l_y1 = via_b - ENDCAP

bbox_b = kdb.Box(l_x1, l_y1, l_x2, l_y2)
top.shapes(li_m3).insert(bbox_b)
print(f"  New bbox: ({bbox_b.left},{bbox_b.bottom};{bbox_b.right},{bbox_b.top}) = {bbox_b.width()}×{bbox_b.height()}")
print(f"  Width: {bbox_b.width()}nm, Height: {bbox_b.height()}nm")
print(f"  Min dimension: {min(bbox_b.width(), bbox_b.height())}nm {'✓' if min(bbox_b.width(), bbox_b.height()) >= 200 else '✗'}")
print(f"  Enclosure: L={via_l-bbox_b.left}, R={bbox_b.right-via_r}, B={via_b-bbox_b.bottom}, T={bbox_b.top-via_t}")


# Save and run DRC
layout.write(GDS_OUT)
print(f"\nSaved: {GDS_OUT}")

print("\nRunning DRC...")
cmd = [
    'python3',
    os.path.expanduser('~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py'),
    f'--path={GDS_OUT}',
    '--topcell=ptat_vco',
    '--run_dir=/tmp/drc_m3a_lcorner',
    '--mp=1', '--no_density'
]
subprocess.run(cmd, capture_output=True, text=True, timeout=300)

# Parse results
import xml.etree.ElementTree as ET
lyrdbs = glob.glob('/tmp/drc_m3a_lcorner/*_full.lyrdb')
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
    print("RESULTS: L-corner bbox fix (2 cases)")
    print(f"{'='*70}")
    print(f"  {'Rule':15s} {'Baseline':>10s} {'Fixed':>10s} {'Delta':>8s}")
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

    # Violations near targets
    m3a_detail = []
    for item in items.findall('item'):
        cat = item.find('category').text.strip("'")
        if cat != 'M3.a':
            continue
        vals = item.find('values')
        for v in vals.findall('value'):
            text = v.text or ''
            pairs = re.findall(r'\(([^)]+)\)', text)
            for p in pairs:
                parts = p.replace(';', ',').split(',')
                try:
                    coords = [(float(parts[i])*1000, float(parts[i+1])*1000) for i in range(0, len(parts)-1, 2)]
                    cx = sum(c[0] for c in coords) / len(coords)
                    cy = sum(c[1] for c in coords) / len(coords)
                    m3a_detail.append((cx, cy))
                except (ValueError, IndexError):
                    pass

    targets = [(87350, 217000, 'A'), (41470, 62630, 'B')]
    for tx, ty, name in targets:
        near = [(cx, cy) for cx, cy in m3a_detail if abs(cx-tx)<1000 and abs(cy-ty)<1000]
        print(f"\n  M3.a near Case {name}: {len(near)}")
        for cx, cy in near:
            print(f"    ({cx:.0f}, {cy:.0f})")
else:
    print("ERROR: No lyrdb found")
