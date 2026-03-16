#!/usr/bin/env python3
"""Diagnose ALL 70 DRC violations: extract coordinates, probe shapes, classify.

For each violation:
1. Parse location from lyrdb
2. Probe GDS shapes at that location on the relevant layer
3. Check if inside a subcell instance or only in top cell
4. Report shape dimensions, likely origin (PCell vs assembly vs routing)

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_drc70.py
"""
import os, re, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import xml.etree.ElementTree as ET
import glob

# ---------- Config ----------
GDS_PATH = 'output/ptat_vco.gds'
LYRDB_PATTERN = '/tmp/drc_main_r17/*_full.lyrdb'

# Layer numbers (IHP SG13G2)
LAYER_MAP = {
    'M1': (8, 0),   # Metal1
    'M2': (10, 0),  # Metal2
    'M3': (30, 0),  # Metal3
    'M4': (50, 0),  # Metal4
    'Via1': (19, 0),
    'Via2': (29, 0),
    'Via3': (49, 0),
    'Cont': (6, 0),
    'GatPoly': (5, 0),
    'NWell': (31, 0),
    'Activ': (1, 0),
    'SalBlock': (28, 0),
    'ContBar': (35, 0),
    'Rppd': (57, 0),   # guess — need to verify
}

# Which layers to probe for each rule
RULE_PROBE_LAYERS = {
    'M1.b': ['M1'],          # M1 spacing
    'M1.d': ['M1'],          # M1 min area
    'M2.b': ['M2'],          # M2 spacing
    'M2.c1': ['M2', 'Via1'], # M2 enclosure of Via1
    'M3.b': ['M3'],          # M3 spacing
    'NW.b1': ['NWell'],      # NWell spacing
    'Cnt.d': ['Cont', 'GatPoly'],  # GatPoly enclosure of Cont
    'CntB.b2': ['ContBar', 'Cont'],  # ContBar space to Cont
    'Rhi.d': ['SalBlock', 'Cont'],   # SalBlock space to Cont (Rhigh)
    'V2.c1': ['Via2', 'M2'],   # M2 enclosure of Via2
    'Rppd.c': ['SalBlock', 'Cont'],  # SalBlock space to Cont (Rppd)
}

# ---------- Load GDS ----------
print("Loading GDS...")
layout = kdb.Layout()
layout.read(GDS_PATH)
top = layout.top_cell()

# Build layer indices
li = {}
for name, (ln, dt) in LAYER_MAP.items():
    li[name] = layout.layer(ln, dt)

# ---------- Parse lyrdb ----------
print("Parsing DRC violations...")
lyrdbs = glob.glob(LYRDB_PATTERN)
if not lyrdbs:
    print("ERROR: No lyrdb found")
    sys.exit(1)

tree = ET.parse(lyrdbs[0])
root = tree.getroot()
items_el = root.find('items')

violations = []
for item in items_el.findall('item'):
    cat = item.find('category').text.strip("'")
    vals = item.find('values')
    for v in vals.findall('value'):
        text = v.text or ''
        pairs = re.findall(r'\(([^)]+)\)', text)
        coords_nm = []
        for p in pairs:
            parts = p.replace(';', ',').split(',')
            try:
                for i in range(0, len(parts) - 1, 2):
                    coords_nm.append((float(parts[i]) * 1000,
                                      float(parts[i + 1]) * 1000))
            except (ValueError, IndexError):
                pass
        if coords_nm:
            cx = sum(c[0] for c in coords_nm) / len(coords_nm)
            cy = sum(c[1] for c in coords_nm) / len(coords_nm)
            violations.append({
                'rule': cat,
                'cx': cx, 'cy': cy,
                'coords': coords_nm,
                'raw': text[:120],
            })

print(f"Total violations parsed: {len(violations)}")

# ---------- Probe helpers ----------
def probe_shapes(layer_name, cx, cy, radius=500):
    """Find shapes on layer near (cx, cy) in nm. Returns list of (bbox, w, h, cell_name)."""
    if layer_name not in li:
        return []
    layer_idx = li[layer_name]
    probe = kdb.Box(int(cx - radius), int(cy - radius),
                    int(cx + radius), int(cy + radius))
    results = []

    # Top cell direct shapes
    for si in top.shapes(layer_idx).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            results.append({
                'bbox': (bb.left, bb.bottom, bb.right, bb.top),
                'w': bb.width(), 'h': bb.height(),
                'cell': 'TOP',
            })

    # Recursive: check subcell instances
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(layer_idx).each():
            # Transform shape bbox to top-cell coordinates
            bb = trans * si.bbox()
            if probe.overlaps(bb):
                results.append({
                    'bbox': (bb.left, bb.bottom, bb.right, bb.top),
                    'w': bb.width(), 'h': bb.height(),
                    'cell': cell.name,
                })

    return results

def probe_subcell_instances(cx, cy, radius=500):
    """Find subcell instances whose bbox contains the probe point."""
    probe_pt = kdb.Point(int(cx), int(cy))
    results = []
    for inst in top.each_inst():
        bb = inst.bbox()
        if bb.contains(probe_pt):
            results.append({
                'cell': inst.cell.name,
                'bbox': (bb.left, bb.bottom, bb.right, bb.top),
                'w': bb.width(), 'h': bb.height(),
            })
    return results


# ---------- Analyze each violation ----------
print("\n" + "=" * 100)
print("VIOLATION ANALYSIS — FACTS ONLY (no assumptions)")
print("=" * 100)

# Group by rule
from collections import defaultdict
by_rule = defaultdict(list)
for v in violations:
    by_rule[v['rule']].append(v)

for rule in sorted(by_rule.keys()):
    viols = by_rule[rule]
    print(f"\n{'─' * 100}")
    print(f"RULE: {rule} — {len(viols)} violations")
    print(f"{'─' * 100}")

    probe_layers = RULE_PROBE_LAYERS.get(rule, [])

    for i, v in enumerate(viols):
        cx, cy = v['cx'], v['cy']
        print(f"\n  [{i+1}] centroid=({cx:.0f}, {cy:.0f})")
        print(f"      raw: {v['raw']}")

        # Check if inside design area
        if cy < 0 or cx < 0:
            print(f"      ⚠ OUTSIDE DESIGN AREA (negative coordinates)")

        # Probe subcell instances at this location
        subcells = probe_subcell_instances(cx, cy)
        if subcells:
            for sc in subcells:
                print(f"      SUBCELL: '{sc['cell']}' bbox=({sc['bbox'][0]},{sc['bbox'][1]};{sc['bbox'][2]},{sc['bbox'][3]}) {sc['w']}×{sc['h']}nm")
        else:
            print(f"      NO SUBCELL at this location (top-cell shapes only)")

        # Probe shapes on relevant layers
        for layer_name in probe_layers:
            shapes = probe_shapes(layer_name, cx, cy, radius=800)
            if shapes:
                print(f"      {layer_name} shapes ({len(shapes)}):")
                for s in shapes[:10]:  # limit output
                    print(f"        {s['cell']:20s} ({s['bbox'][0]},{s['bbox'][1]};{s['bbox'][2]},{s['bbox'][3]}) {s['w']}×{s['h']}nm")
            else:
                print(f"      {layer_name} shapes: NONE within 800nm")

# ---------- Summary ----------
print(f"\n{'=' * 100}")
print("SUMMARY BY LOCATION PATTERN")
print(f"{'=' * 100}")

# Cluster violations by proximity
def cluster_viols(viols, threshold=2000):
    """Cluster violations within threshold nm of each other."""
    clusters = []
    used = set()
    for i, v in enumerate(viols):
        if i in used:
            continue
        cluster = [v]
        used.add(i)
        for j, v2 in enumerate(viols):
            if j in used:
                continue
            if abs(v['cx'] - v2['cx']) < threshold and abs(v['cy'] - v2['cy']) < threshold:
                cluster.append(v2)
                used.add(j)
        clusters.append(cluster)
    return clusters

for rule in sorted(by_rule.keys()):
    viols = by_rule[rule]
    clusters = cluster_viols(viols)
    print(f"\n  {rule} ({len(viols)} viols) → {len(clusters)} clusters:")
    for ci, cluster in enumerate(clusters):
        cx_avg = sum(v['cx'] for v in cluster) / len(cluster)
        cy_avg = sum(v['cy'] for v in cluster) / len(cluster)
        in_subcell = set()
        for v in cluster:
            subcells = probe_subcell_instances(v['cx'], v['cy'])
            for sc in subcells:
                in_subcell.add(sc['cell'])
        subcell_str = ', '.join(in_subcell) if in_subcell else 'TOP-ONLY'
        print(f"    cluster {ci}: {len(cluster)} viols near ({cx_avg:.0f},{cy_avg:.0f}) — {subcell_str}")
