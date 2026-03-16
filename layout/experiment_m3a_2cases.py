#!/usr/bin/env python3
"""M3.a targeted experiment: patch exactly 2 violation locations.

Case A: via2@(87350, 217000) — stub goes W and SW
  pad(87160,216810;87540,217190) = 380×380nm
  stub(87200,216900;87350,217100) = 150×200nm (horizontal stub going west)
  stub(87100,217000;87300,217150) = 200×150nm
  signal_wire(86150,217000;87200,217300) = 1050×300nm

  Fix: Replace pad with a 200nm-tall horizontal bar that extends:
  - West: to stub edge (87200) — already covered by stub
  - East: 50nm past via right edge → 87350+95+50 = 87495
  Combined shape merges with stub → 295nm×200nm rectangle
  M3.c1: E-W ≥50nm endcap, N-S two_opposite_sides_allowed

Case B: via2@(41470, 62630) — stub goes E and NE
  pad(41280,62440;41660,62820) = 380×380nm
  stub(41350,62530;41470,62730) = 120×200nm (horizontal stub going east)
  signal_wire(41350,62650;47300,62950) = 5950×300nm

  Fix: Same approach — 200nm-tall bar extending 50nm past via edge in anti-stub direction

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_2cases.py
"""
import os, subprocess, glob
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'
GDS_OUT = '/tmp/exp_m3a_2case.gds'

VIA2_HW = 190 // 2    # 95nm
ENDCAP = 50            # 50nm M3.c1 endcap
M3_HW = 200 // 2      # 100nm (M3_MIN_W / 2)

layout = kdb.Layout()
layout.read(GDS_IN)
top = layout.top_cell()
li_m3 = layout.layer(30, 0)

# Target pads to replace (identified by bbox center ±5nm tolerance)
targets = [
    # (center_x, center_y, stub_direction, description)
    (87350, 217000, 'W', 'Case A: stub goes west'),
    (41470, 62630, 'E', 'Case B: stub goes east'),
]

# For each target, we need to:
# 1. Find and remove the 380nm pad at that location
# 2. Draw a 200nm×200nm pad
# 3. Draw a 200nm-tall extension in the anti-stub direction (50nm past via edge)

for target_cx, target_cy, stub_dir, desc in targets:
    print(f"\n{desc}: via2@({target_cx}, {target_cy})")

    # Find and remove the 380nm pad
    removed = False
    for si in top.shapes(li_m3).each():
        bb = si.bbox()
        w, h = bb.width(), bb.height()
        if not (370 <= w <= 390 and 370 <= h <= 390):
            continue
        cx = (bb.left + bb.right) // 2
        cy = (bb.bottom + bb.top) // 2
        if abs(cx - target_cx) <= 20 and abs(cy - target_cy) <= 20:
            print(f"  Removing pad: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {w}×{h}")
            top.shapes(li_m3).erase(si)
            removed = True
            break

    if not removed:
        # Try recursive shapes (pad might be in a subcell flattened)
        print(f"  Pad not found in top cell shapes, searching recursively...")
        found_cells = []
        for ci in range(layout.cells()):
            cell = layout.cell(ci)
            for si in cell.shapes(li_m3).each():
                bb = si.bbox()
                w, h = bb.width(), bb.height()
                if not (370 <= w <= 390 and 370 <= h <= 390):
                    continue
                # For subcells, need to account for transformation
                # But AP via2s are drawn directly in top cell
                cx = (bb.left + bb.right) // 2
                cy = (bb.bottom + bb.top) // 2
                if abs(cx - target_cx) <= 50 and abs(cy - target_cy) <= 50:
                    found_cells.append((ci, cell.name, bb))
        for ci, name, bb in found_cells:
            print(f"  Found in cell '{name}': ({bb.left},{bb.bottom};{bb.right},{bb.top})")

    # Draw new 200nm×200nm pad
    new_pad = kdb.Box(target_cx - M3_HW, target_cy - M3_HW,
                      target_cx + M3_HW, target_cy + M3_HW)
    top.shapes(li_m3).insert(new_pad)
    print(f"  New pad: ({new_pad.left},{new_pad.bottom};{new_pad.right},{new_pad.top}) = {new_pad.width()}×{new_pad.height()}")

    # Draw anti-stub extension (200nm wide, 50nm past via edge)
    anti_dir = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E'}[stub_dir]

    if anti_dir == 'E':
        ext = kdb.Box(target_cx + M3_HW, target_cy - M3_HW,
                      target_cx + VIA2_HW + ENDCAP, target_cy + M3_HW)
    elif anti_dir == 'W':
        ext = kdb.Box(target_cx - VIA2_HW - ENDCAP, target_cy - M3_HW,
                      target_cx - M3_HW, target_cy + M3_HW)
    elif anti_dir == 'N':
        ext = kdb.Box(target_cx - M3_HW, target_cy + M3_HW,
                      target_cx + M3_HW, target_cy + VIA2_HW + ENDCAP)
    elif anti_dir == 'S':
        ext = kdb.Box(target_cx - M3_HW, target_cy - VIA2_HW - ENDCAP,
                      target_cx + M3_HW, target_cy - M3_HW)

    top.shapes(li_m3).insert(ext)
    print(f"  Extension ({anti_dir}): ({ext.left},{ext.bottom};{ext.right},{ext.top}) = {ext.width()}×{ext.height()}")

    # What the merged shape looks like (pad + extension + existing stub)
    merged_left = min(new_pad.left, ext.left)
    merged_right = max(new_pad.right, ext.right)
    merged_bottom = min(new_pad.bottom, ext.bottom)
    merged_top = max(new_pad.top, ext.top)
    print(f"  Merged pad+ext: ({merged_left},{merged_bottom};{merged_right},{merged_top}) = {merged_right-merged_left}×{merged_top-merged_bottom}")
    print(f"  Via2 cut: ({target_cx-VIA2_HW},{target_cy-VIA2_HW};{target_cx+VIA2_HW},{target_cy+VIA2_HW})")

    # Verify enclosure
    via_l, via_b = target_cx - VIA2_HW, target_cy - VIA2_HW
    via_r, via_t = target_cx + VIA2_HW, target_cy + VIA2_HW
    print(f"  M3 enclosure check (from pad+ext only, excluding stub):")
    print(f"    Left:  {via_l - merged_left}nm", "✓" if via_l - merged_left >= 50 else "✗ (stub provides)")
    print(f"    Right: {merged_right - via_r}nm", "✓" if merged_right - via_r >= 50 else "✗ (stub provides)")
    print(f"    Bottom:{via_b - merged_bottom}nm", "✓" if via_b - merged_bottom >= 50 else "✗ (two_opp)")
    print(f"    Top:   {merged_top - via_t}nm", "✓" if merged_top - via_t >= 50 else "✗ (two_opp)")

# Save
layout.write(GDS_OUT)
print(f"\nSaved: {GDS_OUT}")

# Run DRC
print("\nRunning DRC...")
cmd = [
    'python3',
    os.path.expanduser('~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py'),
    f'--path={GDS_OUT}',
    '--topcell=ptat_vco',
    '--run_dir=/tmp/drc_m3a_2case',
    '--mp=1', '--no_density'
]
subprocess.run(cmd, capture_output=True, text=True, timeout=300)

# Parse and compare
import xml.etree.ElementTree as ET
lyrdbs = glob.glob('/tmp/drc_m3a_2case/*_full.lyrdb')
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
    print("RESULTS: 2-case targeted patch")
    print(f"{'='*70}")
    print(f"  {'Rule':15s} {'Baseline':>10s} {'Patched':>10s} {'Delta':>8s}")
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

    # Count M3.a violations near our target locations
    m3a_near_targets = 0
    for item in items.findall('item'):
        cat = item.find('category').text.strip("'")
        if cat != 'M3.a':
            continue
        import re
        vals = item.find('values')
        for v in vals.findall('value'):
            text = v.text or ''
            pairs = re.findall(r'\(([^)]+)\)', text)
            for p in pairs:
                parts = p.replace(';', ',').split(',')
                try:
                    coords = [(float(parts[i]), float(parts[i+1])) for i in range(0, len(parts)-1, 2)]
                    cx = sum(c[0] for c in coords) / len(coords) * 1000  # µm→nm
                    cy = sum(c[1] for c in coords) / len(coords) * 1000
                    for tx, ty, _, _ in targets:
                        if abs(cx - tx) < 1000 and abs(cy - ty) < 1000:
                            m3a_near_targets += 1
                            break
                except (ValueError, IndexError):
                    pass

    print(f"\n  M3.a near target locations: {m3a_near_targets}")
else:
    print("ERROR: No lyrdb file found")
