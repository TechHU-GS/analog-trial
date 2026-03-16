#!/usr/bin/env python3
"""Diagnose M2.c1 (3) and V2.c1 (1) violations — Via endcap on M2.

M2.c1: Via1 M2 endcap enclosure (V1.c1 = 50nm)
V2.c1: Via2 M2 endcap enclosure (V2.c1 = 50nm)

For each violation:
1. Parse exact edge-pair from lyrdb
2. Probe Via1/Via2 and M2 shapes at that location
3. Measure actual endcap vs required
4. Identify which M2 shape is the problem (AP pad, vbar, underpass, etc.)
5. Classify as TOP-cell or subcell

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_via_endcap.py
"""
import os, re, math
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
import xml.etree.ElementTree as ET
import glob

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)
li_m3 = layout.layer(30, 0)

# Parse lyrdb
lyrdbs = glob.glob('/tmp/drc_r21_fix/*_full.lyrdb')
tree = ET.parse(lyrdbs[0])
root = tree.getroot()

def parse_coords(text):
    """Parse edge-pair/polygon coordinates from lyrdb text (µm → nm)."""
    pairs = re.findall(r'\(([^)]+)\)', text)
    coords = []
    for p in pairs:
        parts = p.replace(';', ',').split(',')
        for i in range(0, len(parts)-1, 2):
            try:
                coords.append((float(parts[i])*1000, float(parts[i+1])*1000))
            except ValueError:
                pass
    return coords

def probe_shapes(layer_idx, layer_name, cx, cy, radius=1000):
    """Find all shapes on layer near (cx, cy)."""
    probe = kdb.Box(int(cx - radius), int(cy - radius),
                    int(cx + radius), int(cy + radius))
    results = []
    # TOP cell
    for si in top.shapes(layer_idx).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            results.append(('TOP', bb))
    # Subcells
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(layer_idx).each():
            bb = si.bbox().transformed(inst.trans)
            if probe.overlaps(bb):
                results.append((cell.name, bb))
    return results

def measure_endcap(via_bb, m2_bb):
    """Measure minimum endcap of via within M2 shape.
    Returns (left_enc, right_enc, bottom_enc, top_enc) or None if no overlap."""
    # Check overlap
    if (via_bb.right <= m2_bb.left or via_bb.left >= m2_bb.right or
        via_bb.top <= m2_bb.bottom or via_bb.bottom >= m2_bb.top):
        return None
    return (
        via_bb.left - m2_bb.left,     # left enclosure
        m2_bb.right - via_bb.right,   # right enclosure
        via_bb.bottom - m2_bb.bottom, # bottom enclosure
        m2_bb.top - via_bb.top,       # top enclosure
    )

# Process violations
for rule in ('M2.c1', 'V2.c1'):
    via_layer = li_v1 if rule == 'M2.c1' else li_v2
    via_name = 'Via1' if rule == 'M2.c1' else 'Via2'
    req_endcap = 50  # nm (V1.c1 = V2.c1 = 50nm)

    print(f"\n{'='*80}")
    print(f"{rule}: {via_name} M2 endcap enclosure (required: {req_endcap}nm)")
    print(f"{'='*80}")

    viol_count = 0
    for item in root.find('items').findall('item'):
        cat = item.find('category')
        if cat is None:
            continue
        cn = cat.text.strip().strip("'")
        if cn != rule:
            continue
        vals = item.find('values')
        if vals is None:
            continue
        for v in vals.findall('value'):
            text = v.text or ''
            viol_count += 1
            coords = parse_coords(text)
            if not coords:
                print(f"\n  #{viol_count}: {text[:100]} (no coords parsed)")
                continue

            cx = sum(c[0] for c in coords) / len(coords)
            cy = sum(c[1] for c in coords) / len(coords)
            print(f"\n  #{viol_count}: center=({cx:.0f},{cy:.0f})")
            print(f"    Raw: {text[:120]}")

            # Probe via shapes
            vias = probe_shapes(via_layer, via_name, cx, cy, 500)
            print(f"\n    {via_name} shapes nearby:")
            for src, bb in vias:
                print(f"      [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                      f"{bb.width()}x{bb.height()}")

            # Probe M2 shapes
            m2s = probe_shapes(li_m2, 'M2', cx, cy, 500)
            print(f"\n    M2 shapes nearby:")
            for src, bb in m2s:
                print(f"      [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                      f"{bb.width()}x{bb.height()}")

            # Measure endcap for each via-M2 pair
            print(f"\n    Endcap analysis:")
            for v_src, v_bb in vias:
                for m_src, m_bb in m2s:
                    enc = measure_endcap(v_bb, m_bb)
                    if enc is None:
                        continue
                    l, r, b, t = enc
                    min_enc = min(l, r, b, t)
                    endcap = min(b, t)  # endcap = along via length direction
                    side = min(l, r)    # side enclosure
                    marker = ""
                    if endcap < req_endcap:
                        marker = f" ← ENDCAP VIOLATION (need +{req_endcap - endcap}nm)"
                    if side < 5:  # V1.c/V2.c = 5nm side enclosure
                        marker += f" ← SIDE VIOLATION"
                    print(f"      {via_name}[{v_src}] in M2[{m_src}]: "
                          f"L={l} R={r} B={b} T={t} "
                          f"(min_endcap={endcap}, min_side={side}){marker}")

            # Also check M3 (for V2.c1 context)
            if rule == 'V2.c1':
                m3s = probe_shapes(li_m3, 'M3', cx, cy, 500)
                print(f"\n    M3 shapes nearby:")
                for src, bb in m3s:
                    print(f"      [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                          f"{bb.width()}x{bb.height()}")

    print(f"\n  Total {rule} violations: {viol_count}")
