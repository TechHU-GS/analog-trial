#!/usr/bin/env python3
"""For each DRC violation, probe the GDS to identify conflicting shapes.

Classifies shape pairs as: signal_wire, power_rail, power_vbar, via_pad, gap_fill, stub.
Cross-references with routing.json to label signal shapes by net.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_drc_shapes.py
"""
import os, re, json
import xml.etree.ElementTree as ET
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# ── Parse violations ──
LYRDB = '/tmp/drc_rout_eco/ptat_vco_ptat_vco_full.lyrdb'
tree = ET.parse(LYRDB)
root = tree.getroot()
items_elem = root.find('items')

def parse_viols(rule):
    """Return list of (cx_um, cy_um) for violations of given rule."""
    result = []
    for item in items_elem.findall('item'):
        cat = item.find('category').text.strip("'")
        if cat != rule:
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
                        coords.append((float(parts[i]), float(parts[i+1])))
                    except ValueError:
                        pass
            if coords:
                cx = sum(c[0] for c in coords) / len(coords)
                cy = sum(c[1] for c in coords) / len(coords)
                result.append((cx, cy))
    return result

# ── Load GDS ──
GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Layer map
LAYERS = {
    'M1': layout.layer(8, 0),
    'M2': layout.layer(10, 0),
    'M3': layout.layer(30, 0),
    'M4': layout.layer(50, 0),
}

# ── Load routing for signal shape identification ──
with open('output/routing.json') as f:
    routing = json.load(f)

# Build signal wire regions per layer
from atk.pdk import M1_SIG_W, M2_SIG_W, M3_MIN_W

WIRE_HW = {
    'M1': M1_SIG_W // 2,  # 150
    'M2': M2_SIG_W // 2,  # 150
    'M3': M1_SIG_W // 2,  # 150 (M3 signal = M1_SIG_W = 300)
    'M4': M1_SIG_W // 2,  # 150
}

# Build power rail Y positions (M3 rails are horizontal bars)
with open('placement.json') as f:
    placement = json.load(f)

def classify_shape(bb, layer_name):
    """Classify a shape by its geometry."""
    w = bb.width()
    h = bb.height()
    min_dim = min(w, h)
    max_dim = max(w, h)

    if layer_name == 'M3':
        if min_dim >= 2500:
            return 'power_rail'
        if min_dim <= 220 and max_dim > 2000:
            return 'power_vbar'
        if min_dim <= 220 and max_dim <= 600:
            return 'stub'
        if 350 <= min_dim <= 420 and 350 <= max_dim <= 420:
            return 'via_pad'
        if min_dim <= 320 and max_dim > 600:
            return 'signal_wire'
        return f'other({w}x{h}nm)'
    elif layer_name == 'M1':
        if min_dim <= 320 and max_dim > 500:
            return 'wire'
        if 340 <= min_dim <= 500:
            return 'pad'
        return f'other({w}x{h}nm)'
    elif layer_name == 'M4':
        if min_dim <= 320 and max_dim > 500:
            return 'signal_wire'
        if 350 <= min_dim <= 420:
            return 'via_pad'
        return f'other({w}x{h}nm)'
    elif layer_name == 'M2':
        if min_dim >= 2000:
            return 'power_drop'
        if min_dim <= 320 and max_dim > 500:
            return 'signal_wire'
        if 440 <= min_dim <= 520:
            return 'via_pad'
        return f'other({w}x{h}nm)'
    return 'unknown'

def probe_shapes(cx_um, cy_um, layer_name, radius_nm=500):
    """Find shapes near a violation coordinate."""
    li = LAYERS[layer_name]
    cx_nm = int(cx_um * 1000)
    cy_nm = int(cy_um * 1000)
    probe = kdb.Box(cx_nm - radius_nm, cy_nm - radius_nm,
                    cx_nm + radius_nm, cy_nm + radius_nm)
    shapes = []
    for si in top.begin_shapes_rec(li):
        bb = si.shape().bbox().transformed(si.trans())
        if probe.overlaps(bb):
            cls = classify_shape(bb, layer_name)
            shapes.append((cls, bb))
    return shapes

# ── Analyze each rule ──
for rule, layer_name in [('M3.b', 'M3'), ('M3.a', 'M3'), ('M1.b', 'M1'),
                          ('M4.b', 'M4'), ('M2.b', 'M2')]:
    viols = parse_viols(rule)
    print(f"\n{'='*70}")
    print(f"{rule}: {len(viols)} violations — shape pair analysis")
    print(f"{'='*70}")

    pair_types = {}
    for cx, cy in viols:
        shapes = probe_shapes(cx, cy, layer_name)
        types = sorted(set(t for t, _ in shapes))
        key = ' vs '.join(types[:2]) if len(types) >= 2 else (types[0] if types else 'no_shapes')
        pair_types.setdefault(key, []).append((cx, cy))

    for ptype, locs in sorted(pair_types.items(), key=lambda x: -len(x[1])):
        print(f"\n  {ptype}: {len(locs)} violations")
        for x, y in locs[:3]:
            shapes = probe_shapes(x, y, layer_name)
            shape_desc = []
            for cls, bb in shapes[:4]:
                shape_desc.append(f"{cls}({bb.left/1e3:.1f},{bb.bottom/1e3:.1f}-{bb.right/1e3:.1f},{bb.top/1e3:.1f})")
            print(f"    ({x:.1f}, {y:.1f}): {', '.join(shape_desc)}")
        if len(locs) > 3:
            print(f"    ... +{len(locs)-3} more")
