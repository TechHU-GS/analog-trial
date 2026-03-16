#!/usr/bin/env python3
"""Analyze M1.a regressions and new M1.b violations from 310nm pad experiment.

Investigate:
1. 5 new M1.a violations — what thin shapes were exposed by pad shrink?
2. 4 new M1.b violations (at y≈194392, y≈91148) — what shapes conflict?

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m1b_regressions.py
"""
import os, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import xml.etree.ElementTree as ET
import glob

# Load BOTH GDS files for comparison
layout_orig = kdb.Layout()
layout_orig.read('output/ptat_vco.gds')
top_orig = layout_orig.top_cell()
li_m1_orig = layout_orig.layer(8, 0)

layout_310 = kdb.Layout()
layout_310.read('/tmp/exp_m1b_310.gds')
top_310 = layout_310.top_cell()
li_m1_310 = layout_310.layer(8, 0)

# Parse patched lyrdb for M1.a and new M1.b
lyrdbs = glob.glob('/tmp/drc_m1b_310/*_full.lyrdb')
tree = ET.parse(lyrdbs[0])
root = tree.getroot()

print("=" * 80)
print("M1.a REGRESSION ANALYSIS (5 new violations)")
print("=" * 80)

for item in root.find('items').findall('item'):
    cat = item.find('category').text.strip("'")
    if cat != 'M1.a':
        continue
    vals = item.find('values')
    for v in vals.findall('value'):
        text = v.text or ''
        pairs = re.findall(r'\(([^)]+)\)', text)
        coords = []
        for p in pairs:
            parts = p.replace(';', ',').split(',')
            for i in range(0, len(parts)-1, 2):
                try:
                    coords.append((float(parts[i])*1000, float(parts[i+1])*1000))
                except ValueError:
                    pass
        if coords:
            cx = sum(c[0] for c in coords) / len(coords)
            cy = sum(c[1] for c in coords) / len(coords)
            print(f"\n  M1.a at ({cx:.0f}, {cy:.0f}): {text[:100]}")

            # Probe shapes in BOTH original and patched GDS
            probe = kdb.Box(int(cx-500), int(cy-500), int(cx+500), int(cy+500))

            print("    Original (370nm pad) shapes:")
            for si in top_orig.shapes(li_m1_orig).each():
                bb = si.bbox()
                if probe.overlaps(bb):
                    w, h = bb.width(), bb.height()
                    marker = " ← PAD" if (w == 370 and h == 370) else ""
                    if min(w, h) < 200:
                        marker += " ← THIN (<200nm)"
                    print(f"      ({bb.left},{bb.bottom};{bb.right},{bb.top}) {w}×{h}{marker}")

            print("    Patched (310nm pad) shapes:")
            for si in top_310.shapes(li_m1_310).each():
                bb = si.bbox()
                if probe.overlaps(bb):
                    w, h = bb.width(), bb.height()
                    marker = " ← NEW_PAD" if (w == 310 and h == 310) else ""
                    if min(w, h) < 160:
                        marker += " ← VIOLATES M1.a!"
                    elif min(w, h) < 200:
                        marker += " ← THIN"
                    print(f"      ({bb.left},{bb.bottom};{bb.right},{bb.top}) {w}×{h}{marker}")

print("\n" + "=" * 80)
print("NEW M1.b VIOLATIONS (not in baseline)")
print("=" * 80)

# Baseline M1.b locations (from previous analysis)
baseline_m1b_y = {65398, 68735, 101898, 171450, 109358, 87808, 149785, 149802}

for item in root.find('items').findall('item'):
    cat = item.find('category').text.strip("'")
    if cat != 'M1.b':
        continue
    vals = item.find('values')
    for v in vals.findall('value'):
        text = v.text or ''
        pairs = re.findall(r'\(([^)]+)\)', text)
        coords = []
        for p in pairs:
            parts = p.replace(';', ',').split(',')
            for i in range(0, len(parts)-1, 2):
                try:
                    coords.append((float(parts[i])*1000, float(parts[i+1])*1000))
                except ValueError:
                    pass
        if coords:
            cx = sum(c[0] for c in coords) / len(coords)
            cy = sum(c[1] for c in coords) / len(coords)

            # Check if this is a new violation (not near baseline y values)
            is_new = all(abs(cy - by) > 3000 for by in baseline_m1b_y)
            if not is_new:
                continue

            print(f"\n  NEW M1.b at ({cx:.0f}, {cy:.0f}): {text[:100]}")

            # Probe shapes
            probe = kdb.Box(int(cx-500), int(cy-500), int(cx+500), int(cy+500))
            print("    Patched (310nm pad) shapes:")
            for si in top_310.shapes(li_m1_310).each():
                bb = si.bbox()
                if probe.overlaps(bb):
                    w, h = bb.width(), bb.height()
                    print(f"      ({bb.left},{bb.bottom};{bb.right},{bb.top}) {w}×{h}")

            print("    Original (370nm pad) shapes:")
            for si in top_orig.shapes(li_m1_orig).each():
                bb = si.bbox()
                if probe.overlaps(bb):
                    w, h = bb.width(), bb.height()
                    print(f"      ({bb.left},{bb.bottom};{bb.right},{bb.top}) {w}×{h}")

# Also check: what is 290×290nm pad used for?
print("\n" + "=" * 80)
print("290×290nm PADS — are these also AP pads?")
print("=" * 80)
count_290 = 0
for si in top_orig.shapes(li_m1_orig).each():
    bb = si.bbox()
    if bb.width() == 290 and bb.height() == 290:
        count_290 += 1
        if count_290 <= 5:
            print(f"  ({bb.left},{bb.bottom};{bb.right},{bb.top})")
print(f"  Total 290×290: {count_290}")

# Check what sizes are common
size_hist = {}
for si in top_orig.shapes(li_m1_orig).each():
    bb = si.bbox()
    w, h = bb.width(), bb.height()
    if w == h and 200 <= w <= 500:  # square pads
        size_hist[(w, h)] = size_hist.get((w, h), 0) + 1
print(f"\n  Square M1 pad sizes:")
for (w, h), count in sorted(size_hist.items()):
    print(f"    {w}×{h}: {count}")
