#!/usr/bin/env python3
"""Trace gnd↔tail short — Phase 3: dump ALL layers at tie cell locations.

The small 0.3×0.3µm active squares in the tail M1 region look like tie cells.
Check ALL GDS layers at these positions to determine if they're ptap (→ gnd short).

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short3.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# The small active squares found in the tail M1 region
tie_candidates = [
    (41470, 70680, 41770, 70980),
    (45850, 70680, 46150, 70980),
    (40440, 77180, 40740, 77480),
    (42820, 77180, 43120, 77480),
    (45200, 77180, 45500, 77480),
    (40170, 70680, 40470, 70980),
]

# Enumerate ALL layers in the GDS
layer_infos = []
for li in layout.layer_indices():
    info = layout.get_info(li)
    layer_infos.append((li, info.layer, info.datatype, str(info)))

layer_infos.sort(key=lambda x: (x[1], x[2]))

print(f"GDS has {len(layer_infos)} layers")

# For each tie candidate, check which layers have shapes there
for xl, yb, xr, yt in tie_candidates:
    cx = (xl + xr) // 2
    cy = (yb + yt) // 2
    probe = kdb.Region(kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50))

    print(f"\n=== Tie candidate at ({xl/1e3:.3f},{yb/1e3:.3f})"
          f"-({xr/1e3:.3f},{yt/1e3:.3f}) ===")

    for li, layer, datatype, info_str in layer_infos:
        region = kdb.Region(top.begin_shapes_rec(li))
        overlap = region & probe
        if not overlap.is_empty():
            for p in overlap.each():
                bb = p.bbox()
                print(f"  Layer {layer}/{datatype} ({info_str}): "
                      f"({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                      f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
                      f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

# Also check: what does the IHP LVS script use for ptap?
# From the LVS script source, ptap1 extraction uses:
# ptap1 = psd & activ (active with p+ implant, in p-substrate)
# where psd = layer 6/0 in IHP SG13G2
print("\n\n=== IHP SG13G2 ptap check with layer 6/0 (pSD) ===")
li_psd = layout.layer(6, 0)
li_activ = layout.layer(1, 0)
li_nwell = layout.layer(31, 0)
li_gatpoly = layout.layer(5, 0)
li_cont = layout.layer(6, 0)  # Contact is also 6/0? No...
li_m1 = layout.layer(8, 0)

# Get regions
psd_region = kdb.Region(top.begin_shapes_rec(li_psd))
activ_region = kdb.Region(top.begin_shapes_rec(li_activ))
nwell_region = kdb.Region(top.begin_shapes_rec(li_nwell))
gatpoly_region = kdb.Region(top.begin_shapes_rec(li_gatpoly))
m1_region = kdb.Region(top.begin_shapes_rec(li_m1)).merged()

# ptap active = activ & pSD - NWell - GatPoly
ptap_activ = (activ_region & psd_region) - nwell_region - gatpoly_region

# Check in tail M1 region
TAIL_BB = kdb.Box(38470, 70680, 46185, 80145)
tail_probe = kdb.Region(TAIL_BB)

ptap_in_tail = ptap_activ & tail_probe
print(f"ptap (layer 6/0 pSD) in tail region: {ptap_in_tail.count()} shapes")
for p in ptap_in_tail.each():
    bb = p.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
          f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Also check with other possible pSD layers
for psd_layer, psd_dt in [(6, 0), (14, 0), (7, 0), (13, 0), (3, 0)]:
    li = layout.layer(psd_layer, psd_dt)
    region = kdb.Region(top.begin_shapes_rec(li))
    ptap_test = (activ_region & region) - nwell_region - gatpoly_region
    ptap_in = ptap_test & tail_probe
    if not ptap_in.is_empty():
        print(f"\n  ptap with pSD layer {psd_layer}/{psd_dt}: {ptap_in.count()} shapes")
        for p in ptap_in.each():
            bb = p.bbox()
            print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
                  f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Check the tail M1 polygon — is it touching any ptap contact M1?
print("\n=== ptap Contact → M1 connection check ===")
# For IHP, Contact layer is (19,0)? No, that's Via1.
# In IHP SG13G2: Cont = (6,0) is the contact layer
# Wait, let me check by looking at what layers are present

# Actually let me just check all layers overlapping ptap positions
for p in ptap_in_tail.each():
    bb = p.bbox()
    probe = kdb.Region(kdb.Box(bb.left - 100, bb.bottom - 100,
                               bb.right + 100, bb.top + 100))
    # Check M1
    m1_at_ptap = m1_region & probe
    if not m1_at_ptap.is_empty():
        for mp in m1_at_ptap.each():
            mbb = mp.bbox()
            print(f"  M1 at ptap ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f}): "
                  f"({mbb.left/1e3:.3f},{mbb.bottom/1e3:.3f})"
                  f"-({mbb.right/1e3:.3f},{mbb.top/1e3:.3f})"
                  f" — SAME as tail M1? ", end="")
            # Check if this M1 is the tail M1 polygon
            tail_m1_probe = kdb.Region(kdb.Box(45500, 75700, 45600, 75800))
            same_poly = kdb.Region(mp) & tail_m1_probe
            if not same_poly.is_empty():
                print("YES — THIS IS THE SHORT!")
            else:
                # Check if they're the same merged polygon
                # by checking if the M1 at ptap and the tail label
                # are on the same merged M1 component
                print("No (different M1 polygon)")
