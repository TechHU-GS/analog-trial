#!/usr/bin/env python3
"""Categorize M3.b and M3.a DRC violations by source shape type.

For each violation, probes the GDS to identify which M3 shapes conflict
and labels them as: signal wire, power vbar, power rail, gap fill, AP stub, via pad.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_drc_m3.py
"""
import os, re, json
import xml.etree.ElementTree as ET
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# ── Parse DRC violations ──
LYRDB = '/tmp/drc_rout_eco/ptat_vco_ptat_vco_full.lyrdb'
tree = ET.parse(LYRDB)
root = tree.getroot()

violations = {}  # rule -> [(x_nm, y_nm, detail), ...]
items = root.find('items')
for item in items.findall('item'):
    rule = item.find('category').text.strip("'")
    vals = item.find('values')
    coords = []
    for v in vals.findall('value'):
        text = v.text or ''
        # edge-pair(x1,y1;x2,y2 / x3,y3;x4,y4) or polygon(...)
        nums = [int(n) for n in re.findall(r'-?\d+', text)]
        if nums:
            cx = sum(nums[0::2]) // len(nums[0::2])
            cy = sum(nums[1::2]) // len(nums[1::2])
            coords.append((cx, cy, text[:60]))
    if coords:
        violations.setdefault(rule, []).extend(coords)
    elif vals is not None:
        violations.setdefault(rule, []).append((0, 0, 'unparsed'))

# ── Load GDS ──
GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m3 = layout.layer(30, 0)

# Collect ALL M3 shapes with their bounding boxes
m3_shapes = []
for si in top.begin_shapes_rec(li_m3):
    bb = si.shape().bbox().transformed(si.trans())
    m3_shapes.append(bb)

# ── Load routing to identify signal vs power ──
with open('output/routing.json') as f:
    routing = json.load(f)
with open('placement.json') as f:
    placement = json.load(f)

# Build set of signal M3 wire bboxes from routing
signal_m3 = []
for net_name, net_data in routing.get('nets', {}).items():
    for seg in net_data.get('segments', []):
        if seg.get('layer', -1) == 2:  # M3_LYR = 2
            x1, y1, x2, y2 = seg['x1'], seg['y1'], seg['x2'], seg['y2']
            # Wire half-width = 150nm (M1_SIG_W // 2 for M3 signal)
            hw = 150
            if x1 == x2:  # vertical
                signal_m3.append(kdb.Box(x1-hw, min(y1,y2), x1+hw, max(y1,y2)))
            else:  # horizontal
                signal_m3.append(kdb.Box(min(x1,x2), y1-hw, max(x1,x2), y1+hw))

# ── Classify each violation ──
def classify_m3_shape(x, y, radius=300):
    """Find the nearest M3 shape to (x,y) and classify it."""
    probe = kdb.Box(x - radius, y - radius, x + radius, y + radius)
    near = []
    for bb in m3_shapes:
        if probe.overlaps(bb):
            w = bb.width()
            h = bb.height()
            # Classify by geometry
            if min(w, h) > 2500:  # wide shape = power rail
                near.append(('power_rail', bb))
            elif min(w, h) <= 200 and max(w, h) > 1000:  # thin long = power vbar
                near.append(('power_vbar', bb))
            elif min(w, h) <= 200 and max(w, h) <= 1000:  # short stub
                near.append(('stub', bb))
            else:
                # Check against signal routes
                is_signal = False
                for sb in signal_m3:
                    if sb.overlaps(bb):
                        is_signal = True
                        break
                if is_signal:
                    near.append(('signal', bb))
                elif min(w, h) <= 400 and max(w, h) <= 600:
                    near.append(('via_pad', bb))
                else:
                    near.append(('other', bb))
    return near

# ── Report ──
for rule in ['M3.b', 'M3.a', 'M1.b']:
    viols = violations.get(rule, [])
    print(f"\n{'='*70}")
    print(f"{rule}: {len(viols)} violations")
    print(f"{'='*70}")

    if rule.startswith('M3'):
        categories = {}
        for x, y, detail in viols:
            shapes = classify_m3_shape(x, y)
            types = sorted(set(t for t, _ in shapes))
            key = '+'.join(types) if types else 'unknown'
            categories.setdefault(key, []).append((x, y))

        print(f"\nBy category:")
        for cat, locs in sorted(categories.items(), key=lambda x: -len(x[1])):
            print(f"  {cat:40s}: {len(locs)}")
            for x, y in locs[:3]:
                print(f"    ({x/1e3:.1f}, {y/1e3:.1f})")
            if len(locs) > 3:
                print(f"    ... +{len(locs)-3} more")
    else:
        # M1.b — just list coordinates
        for x, y, detail in viols[:10]:
            print(f"  ({x/1e3:.1f}, {y/1e3:.1f})")
        if len(viols) > 10:
            print(f"  ... +{len(viols)-10} more")

# ── Also report M3.b gap measurements ──
print(f"\n{'='*70}")
print("M3.b: actual gap sizes at violation points")
print(f"{'='*70}")
for x, y, detail in violations.get('M3.b', [])[:10]:
    # Parse edge-pair to get gap size
    nums = [int(n) for n in re.findall(r'-?\d+', detail)]
    if len(nums) >= 4:
        # edge-pair: two edges, gap = distance
        dx = abs(nums[2] - nums[0]) if len(nums) >= 4 else 0
        dy = abs(nums[3] - nums[1]) if len(nums) >= 4 else 0
        gap = max(dx, dy)
        print(f"  ({x/1e3:.1f}, {y/1e3:.1f}): gap≈{gap}nm, raw={detail}")
