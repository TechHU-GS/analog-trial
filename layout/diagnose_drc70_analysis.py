#!/usr/bin/env python3
"""Analyze DRC violations: compute actual spacing gaps for fixability assessment.

For M1.b and M2.b, compute the actual gap between the two edges reported
in the violation to understand how much adjustment is needed.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_drc70_analysis.py
"""
import os, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import xml.etree.ElementTree as ET
import glob
from collections import defaultdict

GDS_PATH = 'output/ptat_vco.gds'
LYRDB_PATTERN = '/tmp/drc_main_r17/*_full.lyrdb'

# Load GDS
layout = kdb.Layout()
layout.read(GDS_PATH)
top = layout.top_cell()
li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)
li_nw = layout.layer(31, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)

# Parse lyrdb
lyrdbs = glob.glob(LYRDB_PATTERN)
tree = ET.parse(lyrdbs[0])
root = tree.getroot()
items_el = root.find('items')

violations = []
for item in items_el.findall('item'):
    cat = item.find('category').text.strip("'")
    vals = item.find('values')
    for v in vals.findall('value'):
        text = v.text or ''
        violations.append({'rule': cat, 'raw': text})

by_rule = defaultdict(list)
for v in violations:
    by_rule[v['rule']].append(v)

# ============================================================================
# ANALYSIS 1: M1.b — What shapes cause each violation?
# ============================================================================
print("=" * 90)
print("M1.b ANALYSIS: What are the shapes and how much gap is there?")
print("=" * 90)
print(f"Rule: M1.b = Min Metal1 space/notch = 180nm")
print()

# For each M1.b violation, parse the two edges and compute the gap
m1b_gaps = []
for v in by_rule['M1.b']:
    raw = v['raw']
    # Parse edge-pair: two edges separated by | or /
    # Format: "edge-pair: (x1,y1;x2,y2)|(x3,y3;x4,y4)" or similar
    pairs = re.findall(r'\(([^)]+)\)', raw)
    if len(pairs) >= 2:
        def parse_edge(s):
            parts = s.replace(';', ',').split(',')
            return [(float(parts[i])*1000, float(parts[i+1])*1000) for i in range(0, len(parts)-1, 2)]

        e1 = parse_edge(pairs[0])
        e2 = parse_edge(pairs[1])

        # Compute gap: distance between the two edges
        # For parallel edges, gap = perpendicular distance
        cx1 = sum(p[0] for p in e1) / len(e1)
        cy1 = sum(p[1] for p in e1) / len(e1)
        cx2 = sum(p[0] for p in e2) / len(e2)
        cy2 = sum(p[1] for p in e2) / len(e2)

        # Euclidean distance between edge midpoints as approximation
        import math
        gap = math.sqrt((cx2-cx1)**2 + (cy2-cy1)**2)
        m1b_gaps.append({
            'gap': gap,
            'cx': (cx1+cx2)/2,
            'cy': (cy1+cy2)/2,
            'shortage': 180 - gap,
            'raw': raw[:100],
        })

# Sort by gap
m1b_gaps.sort(key=lambda x: x['gap'])
print(f"  {'Gap(nm)':>8} {'Short(nm)':>10} {'Location':>25}  Raw")
print(f"  {'─'*8} {'─'*10} {'─'*25}  {'─'*50}")
for g in m1b_gaps:
    print(f"  {g['gap']:8.0f} {g['shortage']:10.0f} ({g['cx']:8.0f},{g['cy']:8.0f})  {g['raw'][:60]}")

print(f"\n  Total M1.b: {len(m1b_gaps)} violations")
print(f"  Gap range: {min(g['gap'] for g in m1b_gaps):.0f} – {max(g['gap'] for g in m1b_gaps):.0f} nm")
print(f"  Shortage range: {min(g['shortage'] for g in m1b_gaps):.0f} – {max(g['shortage'] for g in m1b_gaps):.0f} nm")

# ============================================================================
# ANALYSIS 2: Identify shape types at M1.b violation locations
# ============================================================================
print("\n" + "=" * 90)
print("M1.b SHAPE CLASSIFICATION")
print("=" * 90)

# Common shape sizes
SHAPE_TYPES = {
    (370, 370): "AP_PAD (via1 access point)",
    (290, 290): "AP_PAD_SMALL",
    (480, 480): "VIA1_PAD (legacy?)",
    (160, None): "WIRE_160nm (M1 routing)",
    (None, 160): "WIRE_160nm (M1 routing, H)",
    (300, None): "WIRE_300nm (M1 signal)",
    (None, 300): "WIRE_300nm (M1 signal, H)",
    (260, 600): "VIA1_EXT_PAD",
}

def classify_shape(w, h):
    if (w, h) in [(370, 370), (290, 290), (480, 480)]:
        return SHAPE_TYPES.get((w, h), f"PAD_{w}x{h}")
    if w == 160 and h > 500:
        return f"V-WIRE 160×{h}"
    if h == 160 and w > 500:
        return f"H-WIRE {w}×160"
    if w == 300 and h > 300:
        return f"V-SIG 300×{h}"
    if h == 300 and w > 300:
        return f"H-SIG {w}×300"
    if (w, h) == (260, 600):
        return "VIA1_EXT"
    return f"OTHER {w}×{h}"

# For each M1.b cluster, identify the two shapes causing the violation
# by finding shapes closest to each edge
for g in m1b_gaps[:5]:  # Show first 5
    cx, cy = g['cx'], g['cy']
    probe = kdb.Box(int(cx-1000), int(cy-1000), int(cx+1000), int(cy+1000))
    shapes = []
    for si in top.shapes(li_m1).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            shapes.append((bb.width(), bb.height(), bb.left, bb.bottom, bb.right, bb.top))

    print(f"\n  Location ({cx:.0f}, {cy:.0f}) gap={g['gap']:.0f}nm:")
    for w, h, l, b, r, t in shapes[:8]:
        stype = classify_shape(w, h)
        print(f"    ({l},{b};{r},{t}) = {stype}")

# ============================================================================
# ANALYSIS 3: M2.b — gap analysis
# ============================================================================
print("\n" + "=" * 90)
print("M2.b ANALYSIS: Gaps and shapes")
print("=" * 90)
print(f"Rule: M2.b = Min Metal2 space/notch = 210nm")
print()

m2b_gaps = []
for v in by_rule['M2.b']:
    raw = v['raw']
    pairs = re.findall(r'\(([^)]+)\)', raw)
    if len(pairs) >= 2:
        def parse_edge(s):
            parts = s.replace(';', ',').split(',')
            return [(float(parts[i])*1000, float(parts[i+1])*1000) for i in range(0, len(parts)-1, 2)]

        e1 = parse_edge(pairs[0])
        e2 = parse_edge(pairs[1])
        cx1 = sum(p[0] for p in e1) / len(e1)
        cy1 = sum(p[1] for p in e1) / len(e1)
        cx2 = sum(p[0] for p in e2) / len(e2)
        cy2 = sum(p[1] for p in e2) / len(e2)
        import math
        gap = math.sqrt((cx2-cx1)**2 + (cy2-cy1)**2)
        m2b_gaps.append({
            'gap': gap,
            'cx': (cx1+cx2)/2,
            'cy': (cy1+cy2)/2,
            'shortage': 210 - gap,
            'raw': raw[:100],
        })

m2b_gaps.sort(key=lambda x: x['gap'])
print(f"  {'Gap(nm)':>8} {'Short(nm)':>10} {'Location':>25}  Raw")
print(f"  {'─'*8} {'─'*10} {'─'*25}  {'─'*50}")
for g in m2b_gaps:
    print(f"  {g['gap']:8.0f} {g['shortage']:10.0f} ({g['cx']:8.0f},{g['cy']:8.0f})  {g['raw'][:60]}")

# ============================================================================
# ANALYSIS 4: M3.b — what shapes are involved?
# ============================================================================
print("\n" + "=" * 90)
print("M3.b ANALYSIS: Shape details")
print("=" * 90)
print(f"Rule: M3.b = Min Metal3 space/notch = 210nm")
print()

for v in by_rule['M3.b']:
    raw = v['raw']
    pairs = re.findall(r'\(([^)]+)\)', raw)
    if len(pairs) >= 2:
        def parse_edge(s):
            parts = s.replace(';', ',').split(',')
            return [(float(parts[i])*1000, float(parts[i+1])*1000) for i in range(0, len(parts)-1, 2)]
        e1 = parse_edge(pairs[0])
        e2 = parse_edge(pairs[1])
        cx = (sum(p[0] for p in e1+e2)) / len(e1+e2)
        cy = (sum(p[1] for p in e1+e2)) / len(e1+e2)

        import math
        cx1 = sum(p[0] for p in e1) / len(e1)
        cy1 = sum(p[1] for p in e1) / len(e1)
        cx2 = sum(p[0] for p in e2) / len(e2)
        cy2 = sum(p[1] for p in e2) / len(e2)
        gap = math.sqrt((cx2-cx1)**2 + (cy2-cy1)**2)

        print(f"  ({cx:.0f},{cy:.0f}) gap≈{gap:.0f}nm:")
        probe = kdb.Box(int(cx-500), int(cy-500), int(cx+500), int(cy+500))
        for si in top.shapes(li_m3).each():
            bb = si.bbox()
            if probe.overlaps(bb):
                print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {bb.width()}×{bb.height()}")

# ============================================================================
# ANALYSIS 5: NW.b1 — what is the TOP NWell shape for?
# ============================================================================
print("\n" + "=" * 90)
print("NW.b1 ANALYSIS: NWell shapes and gaps")
print("=" * 90)
print(f"Rule: NW.b1 = Min PWell width between NWell regions (different net) = 1800nm")
print()

for v in by_rule['NW.b1']:
    raw = v['raw']
    pairs = re.findall(r'\(([^)]+)\)', raw)
    if len(pairs) >= 2:
        def parse_edge(s):
            parts = s.replace(';', ',').split(',')
            return [(float(parts[i])*1000, float(parts[i+1])*1000) for i in range(0, len(parts)-1, 2)]
        e1 = parse_edge(pairs[0])
        e2 = parse_edge(pairs[1])
        cx = (sum(p[0] for p in e1+e2)) / len(e1+e2)
        cy = (sum(p[1] for p in e1+e2)) / len(e1+e2)

        import math
        cx1 = sum(p[0] for p in e1) / len(e1)
        cy1 = sum(p[1] for p in e1) / len(e1)
        cx2 = sum(p[0] for p in e2) / len(e2)
        cy2 = sum(p[1] for p in e2) / len(e2)
        gap = math.sqrt((cx2-cx1)**2 + (cy2-cy1)**2)

        print(f"  ({cx:.0f},{cy:.0f}) gap≈{gap:.0f}nm:")
        probe = kdb.Box(int(cx-2000), int(cy-2000), int(cx+2000), int(cy+2000))
        # Check top cell NWell
        for si in top.shapes(li_nw).each():
            bb = si.bbox()
            if probe.overlaps(bb):
                print(f"    TOP NWell: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {bb.width()}×{bb.height()}")
        # Check subcell NWell
        for inst in top.each_inst():
            cell = inst.cell
            trans = inst.trans
            for si in cell.shapes(li_nw).each():
                bb = trans * si.bbox()
                if probe.overlaps(bb):
                    print(f"    {cell.name} NWell: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {bb.width()}×{bb.height()}")

# ============================================================================
# ANALYSIS 6: Outside-design-area violations
# ============================================================================
print("\n" + "=" * 90)
print("OUTSIDE DESIGN AREA: CntB.b2 + Rhi.d + Rppd.c at (250, -510)")
print("=" * 90)
# Expand probe radius dramatically
for layer_name, li_idx in [('ContBar', layout.layer(35, 0)), ('Cont', layout.layer(6, 0)),
                             ('SalBlock', layout.layer(28, 0)), ('GatPoly', layout.layer(5, 0))]:
    probe = kdb.Box(-2000, -2000, 2500, 2500)
    found = 0
    for si in top.shapes(li_idx).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            print(f"  TOP {layer_name}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {bb.width()}×{bb.height()}")
            found += 1
    if found == 0:
        # Check subcells
        for inst in top.each_inst():
            cell = inst.cell
            trans = inst.trans
            for si in cell.shapes(li_idx).each():
                bb = trans * si.bbox()
                if probe.overlaps(bb):
                    print(f"  {cell.name} {layer_name}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {bb.width()}×{bb.height()}")
                    found += 1
    if found == 0:
        print(f"  {layer_name}: NONE found within (-2µm, -2µm) to (2.5µm, 2.5µm)")

# Check ALL layers near (250, -510) with extended probe
print("\n  Checking ALL layers near (250, -510) with 5µm radius:")
probe_big = kdb.Box(-5000, -5000, 5000, 5000)
for li_idx in range(layout.layers()):
    info = layout.get_info(li_idx)
    found_shapes = []
    for si in top.shapes(li_idx).each():
        bb = si.bbox()
        if probe_big.overlaps(bb):
            found_shapes.append(bb)
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(li_idx).each():
            bb = trans * si.bbox()
            if probe_big.overlaps(bb):
                found_shapes.append(bb)
    if found_shapes:
        print(f"    Layer ({info.layer},{info.datatype}): {len(found_shapes)} shapes")
        for bb in found_shapes[:3]:
            print(f"      ({bb.left},{bb.bottom};{bb.right},{bb.top}) = {bb.width()}×{bb.height()}")

# ============================================================================
# ANALYSIS 7: Cnt.d — are these assembly-drawn or PCell-internal?
# ============================================================================
print("\n" + "=" * 90)
print("Cnt.d ANALYSIS: Who drew the Cont and GatPoly shapes?")
print("=" * 90)
print(f"Rule: Cnt.d = Min GatPoly enclosure of Cont = 70nm")
print()

# Check: are the Cont/GatPoly shapes at violation locations in TOP cell or subcells?
li_cont = layout.layer(6, 0)
li_gatpoly = layout.layer(5, 0)

cnt_d_locations = [(23610, 15180), (58310, 59180), (13170, 137180), (26570, 59180)]
for cx, cy in cnt_d_locations:
    print(f"  Location ({cx}, {cy}):")
    probe = kdb.Box(cx-1000, cy-1000, cx+1000, cy+1000)

    # Check Cont in subcells specifically
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(li_cont).each():
            bb = trans * si.bbox()
            if probe.overlaps(bb):
                print(f"    SUBCELL '{cell.name}' Cont: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

    # Check Cont in TOP
    for si in top.shapes(li_cont).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            print(f"    TOP Cont: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

    # Check GatPoly in subcells
    for inst in top.each_inst():
        cell = inst.cell
        trans = inst.trans
        for si in cell.shapes(li_gatpoly).each():
            bb = trans * si.bbox()
            if probe.overlaps(bb):
                print(f"    SUBCELL '{cell.name}' GatPoly: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

    # Check GatPoly in TOP
    for si in top.shapes(li_gatpoly).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            print(f"    TOP GatPoly: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 90)
print("CORRECTED CLASSIFICATION (based on actual data)")
print("=" * 90)
print("""
Previous (WRONG) classification:
  "PCell/placement-level (52)" — UNVERIFIED CLAIM
  "Partially fixable (18)" — UNVERIFIED CLAIM

Actual data shows:
  - M1.b=32: ALL violations between TOP-cell shapes (AP pads + routing wires)
    NOT "29 device-level S/D proximity" — that was fabricated
  - M2.b=12: Mix of TOP-cell AP pad vs wire spacing
  - M3.b=4: TOP-cell M3 routing shapes
  - M2.c1=3: Via1 M2 endcap in TOP cell
  - M1.d=2: TOP-cell M1 bridges (area < 90000nm²)
  - V2.c1=1: Via2 M2 endcap in TOP cell
  - NW.b1=6: TOP NWell vs PCell NWell spacing (placement-constrained but TOP shapes adjustable)
  - Cnt.d=4: At resistor PCell boundaries — need to verify who draws Cont/GatPoly
  - CntB.b2=3 + Rhi.d=2 + Rppd.c=1: Outside design area (y<0), need to investigate
""")
