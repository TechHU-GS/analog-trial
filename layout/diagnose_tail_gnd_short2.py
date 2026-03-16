#!/usr/bin/env python3
"""Trace gnd↔tail short — Phase 2: check M1 overlap with ptap/tie/device shapes.

The tail M1 merged polygon is at (38.470,70.680)-(46.185,80.145).
This script checks what else is in that M1 polygon region and whether
a ptap/ntap or tie cell M1 bar connects tail to substrate (gnd).

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short2.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
sys.path.insert(0, '.')

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Layer map
L = {
    'M1':     layout.layer(8, 0),
    'V1':     layout.layer(19, 0),
    'M2':     layout.layer(10, 0),
    'Activ':  layout.layer(1, 0),    # Active area
    'NW':     layout.layer(31, 0),   # NWell
    'PSDM':   layout.layer(14, 0),   # pSD (p+ implant) — ptap marker
    'NSDM':   layout.layer(18, 0),   # nSD (n+ implant) — ntap marker
    'GatPoly': layout.layer(5, 0),   # Gate poly
    'CONT':   layout.layer(6, 0),    # Contact (Activ→M1)
}

# Tail M1 polygon region
TAIL_BB = kdb.Box(38470, 70680, 46185, 80145)
tail_probe = kdb.Region(TAIL_BB)

print("=== Shapes overlapping tail M1 polygon ===")
print(f"Tail M1 bbox: ({TAIL_BB.left/1e3:.3f},{TAIL_BB.bottom/1e3:.3f})"
      f"-({TAIL_BB.right/1e3:.3f},{TAIL_BB.top/1e3:.3f})")

for lyr_name, li in L.items():
    region = kdb.Region(top.begin_shapes_rec(li))
    overlap = region & tail_probe
    if not overlap.is_empty():
        count = overlap.count()
        print(f"\n  {lyr_name}: {count} shapes in tail region")
        if count <= 20:
            for p in overlap.each():
                bb = p.bbox()
                print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
                      f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

# Check: ptap = Activ + pSD (no NWell, no GatPoly)
# These connect active to substrate (gnd)
print("\n=== ptap check (Activ ∩ PSDM - GatPoly - NWell) in tail region ===")
activ = kdb.Region(top.begin_shapes_rec(L['Activ']))
psdm = kdb.Region(top.begin_shapes_rec(L['PSDM']))
nw = kdb.Region(top.begin_shapes_rec(L['NW']))
gatpoly = kdb.Region(top.begin_shapes_rec(L['GatPoly']))
cont = kdb.Region(top.begin_shapes_rec(L['CONT']))

ptap_activ = (activ & psdm) - nw  # ptap: p+ active NOT in NWell
ptap_in_tail = ptap_activ & tail_probe
if not ptap_in_tail.is_empty():
    print(f"  FOUND ptap active in tail region: {ptap_in_tail.count()} shapes")
    for p in ptap_in_tail.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
    # Check if contacts connect this ptap to M1
    ptap_contacts = cont & ptap_in_tail
    if not ptap_contacts.is_empty():
        print(f"  ptap contacts: {ptap_contacts.count()}")
        for p in ptap_contacts.each():
            bb = p.bbox()
            print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                  f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
        print("\n  *** THIS IS THE SHORT: ptap contact connects substrate (gnd)"
              " to tail M1 polygon ***")
else:
    print("  No ptap active in tail region")

# Also check ntap (NWell + nSD + Activ — connects NWell to vdd)
print("\n=== ntap check (Activ ∩ NSDM ∩ NWell) in tail region ===")
nsdm = kdb.Region(top.begin_shapes_rec(L['NSDM']))
ntap_activ = activ & nsdm & nw
ntap_in_tail = ntap_activ & tail_probe
if not ntap_in_tail.is_empty():
    print(f"  FOUND ntap active in tail region: {ntap_in_tail.count()} shapes")
else:
    print("  No ntap active in tail region")

# Check: what devices are in this area?
print("\n=== Device identification in tail M1 region ===")
# MOSFET = GatPoly over Activ
mosfet_gates = gatpoly & activ & tail_probe
if not mosfet_gates.is_empty():
    print(f"  MOSFET gates: {mosfet_gates.count()}")
    for p in mosfet_gates.each():
        bb = p.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
              f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" W≈{bb.height()/1e3:.1f}u L≈{bb.width()/1e3:.1f}u")

# Check placement.json for devices in this area
with open('placement.json') as f:
    placement = json.load(f)

print("\n=== Placed instances near tail region ===")
for iname, idata in placement['instances'].items():
    ix = idata.get('x_um', 0) * 1000  # convert µm→nm
    iy = idata.get('y_um', 0) * 1000
    # Check if instance center is in/near the tail region
    if (TAIL_BB.left - 5000 <= ix <= TAIL_BB.right + 5000 and
        TAIL_BB.bottom - 5000 <= iy <= TAIL_BB.top + 5000):
        dtype = idata.get('type', '?')
        print(f"  {iname} ({dtype}): ({ix/1e3:.3f}, {iy/1e3:.3f}) µm")

# Show the RAW (unmerged) M1 shapes in the tail region to understand
# which shapes contribute to the merged polygon
print("\n=== Raw M1 shapes in tail region ===")
m1_raw = kdb.Region(top.begin_shapes_rec(L['M1']))
m1_raw_in_tail = m1_raw & tail_probe
print(f"  {m1_raw_in_tail.count()} raw M1 shapes:")
for p in m1_raw_in_tail.each():
    bb = p.bbox()
    print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
          f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
          f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")
