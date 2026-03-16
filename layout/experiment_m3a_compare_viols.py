#!/usr/bin/env python3
"""Compare M3.a violation coordinates between baseline and 2-case patch.

Check if the 2 patched cases eliminated their original violations and
created new ones (L-corner), or if the original violations persisted.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_compare_viols.py
"""
import os, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import xml.etree.ElementTree as ET

def parse_m3a_viols(lyrdb_path):
    tree = ET.parse(lyrdb_path)
    root = tree.getroot()
    items = root.find('items')
    viols = []
    for item in items.findall('item'):
        cat = item.find('category').text.strip("'")
        if cat != 'M3.a':
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
                viols.append((cx, cy, text[:100]))
    return viols

# Baseline and patched DRC reports
baseline_viols = parse_m3a_viols('/tmp/drc_rout_eco/ptat_vco_ptat_vco_full.lyrdb')
patched_viols = parse_m3a_viols('/tmp/drc_m3a_2case/exp_m3a_2case_ptat_vco_full.lyrdb')

# Target locations
targets = [(87350, 217000, 'Case A'), (41470, 62630, 'Case B')]
RADIUS = 1000  # nm

print("="*80)
print(f"BASELINE M3.a violations near targets ({len(baseline_viols)} total):")
print("="*80)
for tx, ty, name in targets:
    near = [(cx, cy, d) for cx, cy, d in baseline_viols
            if abs(cx - tx) < RADIUS and abs(cy - ty) < RADIUS]
    print(f"\n  {name} via2@({tx},{ty}): {len(near)} violations")
    for cx, cy, d in near:
        print(f"    ({cx:.0f}, {cy:.0f}) {d[:80]}")

print(f"\n{'='*80}")
print(f"PATCHED M3.a violations near targets ({len(patched_viols)} total):")
print("="*80)
for tx, ty, name in targets:
    near = [(cx, cy, d) for cx, cy, d in patched_viols
            if abs(cx - tx) < RADIUS and abs(cy - ty) < RADIUS]
    print(f"\n  {name} via2@({tx},{ty}): {len(near)} violations")
    for cx, cy, d in near:
        print(f"    ({cx:.0f}, {cy:.0f}) {d[:80]}")

# Diff: which violations disappeared and which appeared?
def viol_key(cx, cy, resolution=50):
    """Round coordinates to group similar violations."""
    return (round(cx / resolution) * resolution, round(cy / resolution) * resolution)

baseline_set = set(viol_key(cx, cy) for cx, cy, _ in baseline_viols)
patched_set = set(viol_key(cx, cy) for cx, cy, _ in patched_viols)

disappeared = baseline_set - patched_set
appeared = patched_set - baseline_set
unchanged = baseline_set & patched_set

print(f"\n{'='*80}")
print("DIFF ANALYSIS (50nm resolution):")
print(f"{'='*80}")
print(f"  Baseline unique locations: {len(baseline_set)}")
print(f"  Patched unique locations:  {len(patched_set)}")
print(f"  Disappeared: {len(disappeared)}")
print(f"  Appeared:    {len(appeared)}")
print(f"  Unchanged:   {len(unchanged)}")

if disappeared:
    print("\n  DISAPPEARED violations:")
    for cx, cy in sorted(disappeared):
        near_target = ""
        for tx, ty, name in targets:
            if abs(cx - tx) < RADIUS and abs(cy - ty) < RADIUS:
                near_target = f" ← {name}"
        print(f"    ({cx}, {cy}){near_target}")

if appeared:
    print("\n  NEW violations:")
    for cx, cy in sorted(appeared):
        near_target = ""
        for tx, ty, name in targets:
            if abs(cx - tx) < RADIUS and abs(cy - ty) < RADIUS:
                near_target = f" ← {name}"
        print(f"    ({cx}, {cy}){near_target}")
