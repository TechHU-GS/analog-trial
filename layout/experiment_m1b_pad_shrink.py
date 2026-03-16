#!/usr/bin/env python3
"""M1.b experiment: shrink Via1 M1 AP pad from 370nm to test sizes.

DRC facts:
  V1.c  = 10nm  (M1 side enclosure of Via1, basic deck)
  V1.c1 = 50nm  (M1 endcap enclosure, maximal deck, two_opposite_sides_allowed)
  M1.d  = 90000nm² (min M1 area, merged shape)
  M1.b  = 180nm (min M1 space, euclidean)

Current: VIA1_PAD_M1 = 370nm → M1_VIA_ENC = 90nm (9x overestimate of actual 10nm)
Minimum: 190 + 2*50 = 290nm (V1.c1), area = 84100 < 90000 ✗
Safe:    190 + 2*60 = 310nm, area = 96100 > 90000 ✓

Strategy: Replace all 370×370nm M1 AP pads with smaller pads.
Check how many M1.b violations this eliminates.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m1b_pad_shrink.py
"""
import os, subprocess, glob, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import xml.etree.ElementTree as ET

GDS_IN  = 'output/ptat_vco.gds'
PAD_SIZES = [310, 300]  # test these sizes

# Baseline DRC counts
baseline = {}
lyrdbs = glob.glob('/tmp/drc_main_r17/*_full.lyrdb')
if lyrdbs:
    tree = ET.parse(lyrdbs[0])
    root = tree.getroot()
    for item in root.find('items').findall('item'):
        cat = item.find('category').text.strip("'")
        baseline[cat] = baseline.get(cat, 0) + 1

print(f"Baseline: {sum(baseline.values())} violations")
for r in sorted(baseline.keys()):
    print(f"  {r:12s} {baseline[r]:3d}")

li_m1_ln = 8

for new_pad in PAD_SIZES:
    print(f"\n{'='*70}")
    print(f"EXPERIMENT: M1 AP pad {370}→{new_pad}nm")
    print(f"{'='*70}")
    print(f"  V1 enclosure: {(new_pad - 190)//2}nm (need: V1.c=10nm, V1.c1=50nm)")
    print(f"  Pad area: {new_pad*new_pad}nm² (need: M1.d ≥ 90000nm²)")

    gds_out = f'/tmp/exp_m1b_{new_pad}.gds'
    drc_dir = f'/tmp/drc_m1b_{new_pad}'

    # Load GDS
    layout = kdb.Layout()
    layout.read(GDS_IN)
    top = layout.top_cell()
    li_m1 = layout.layer(li_m1_ln, 0)

    # Find and replace 370×370nm M1 pads
    old_hw = 370 // 2  # 185
    new_hw = new_pad // 2
    replaced = 0
    skipped = 0

    shapes_to_replace = []
    for si in top.shapes(li_m1).each():
        bb = si.bbox()
        w, h = bb.width(), bb.height()
        if w == 370 and h == 370:
            cx = (bb.left + bb.right) // 2
            cy = (bb.bottom + bb.top) // 2
            shapes_to_replace.append((si, cx, cy))

    for si, cx, cy in shapes_to_replace:
        top.shapes(li_m1).erase(si)
        new_box = kdb.Box(cx - new_hw, cy - new_hw, cx + new_hw, cy + new_hw)
        top.shapes(li_m1).insert(new_box)
        replaced += 1

    # Also check for 290×290nm pads (AP_PAD_SMALL)
    small_pads = []
    for si in top.shapes(li_m1).each():
        bb = si.bbox()
        w, h = bb.width(), bb.height()
        if w == 290 and h == 290:
            small_pads.append(bb)

    print(f"  Replaced: {replaced} pads (370→{new_pad}nm)")
    print(f"  Small pads (290nm): {len(small_pads)} (not modified)")

    layout.write(gds_out)

    # Run DRC
    print(f"  Running DRC...")
    cmd = [
        'python3',
        os.path.expanduser('~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py'),
        f'--path={gds_out}',
        '--topcell=ptat_vco',
        f'--run_dir={drc_dir}',
        '--mp=1', '--no_density'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # Parse results
    lyrdbs = glob.glob(f'{drc_dir}/*_full.lyrdb')
    if not lyrdbs:
        print("  ERROR: No lyrdb found")
        continue

    tree = ET.parse(lyrdbs[0])
    root = tree.getroot()
    counts = {}
    for item in root.find('items').findall('item'):
        cat = item.find('category').text.strip("'")
        counts[cat] = counts.get(cat, 0) + 1

    # Compare
    print(f"\n  {'Rule':15s} {'Baseline':>10s} {'Patched':>10s} {'Delta':>8s}")
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

    # Detail remaining M1.b violations
    m1b_remaining = []
    for item in root.find('items').findall('item'):
        cat = item.find('category').text.strip("'")
        if cat != 'M1.b':
            continue
        vals = item.find('values')
        for v in vals.findall('value'):
            text = v.text or ''
            pairs = re.findall(r'\(([^)]+)\)', text)
            if len(pairs) >= 2:
                def parse_edge(s):
                    parts = s.replace(';', ',').split(',')
                    return [(float(parts[i])*1000, float(parts[i+1])*1000) for i in range(0, len(parts)-1, 2)]
                e1 = parse_edge(pairs[0])
                e2 = parse_edge(pairs[1])
                cx = (sum(p[0] for p in e1+e2)) / len(e1+e2)
                cy = (sum(p[1] for p in e1+e2)) / len(e1+e2)
                m1b_remaining.append((cx, cy, text[:80]))

    if m1b_remaining:
        print(f"\n  Remaining M1.b ({len(m1b_remaining)}):")
        for cx, cy, desc in m1b_remaining:
            print(f"    ({cx:.0f}, {cy:.0f}) {desc[:60]}")
