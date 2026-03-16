#!/usr/bin/env python3
"""Check salblock/extblock at PM3/PM4 positions in OUTPUT GDS (after flatten+clip).

Replicates the PDK LVS derivation chain at PM3/PM4 to see why they're still not extracted.
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Layer indices
li_activ = layout.layer(1, 0)
li_gatpoly = layout.layer(5, 0)
li_psd = layout.layer(14, 0)
li_nwell = layout.layer(31, 0)
li_salblock = layout.layer(28, 0)
li_extblock = layout.layer(111, 0)
li_polyres = layout.layer(128, 0)

# Probe: PM3/PM4 mirror island area
probe = kdb.Box(36000, 153000, 41000, 157000)

print("=" * 70)
print(f"Layers in probe area x=36-41, y=153-157 µm (PM3/PM4 mirror island)")
print("=" * 70)

for name, li in [('Activ', li_activ), ('GatPoly', li_gatpoly), ('pSD', li_psd),
                  ('NWell', li_nwell), ('SalBlock', li_salblock), ('EXTBlock', li_extblock),
                  ('PolyRes', li_polyres)]:
    region = kdb.Region()
    for si in top.begin_shapes_rec(li):
        bb = si.shape().bbox().transformed(si.trans())
        if probe.overlaps(bb):
            if si.shape().is_polygon():
                region.insert(si.shape().polygon.transformed(si.trans()))
            elif si.shape().is_box():
                region.insert(si.shape().box.transformed(si.trans()))
    region = region.merged()
    if region.is_empty():
        print(f"\n{name} ({li}): EMPTY (none in probe)")
    else:
        print(f"\n{name} ({li}): {region.size()} shapes, area={region.area()/1e6:.2f} µm²")
        for poly in region.each():
            bb = poly.bbox()
            print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                  f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

# Now replicate the actual LVS derivation chain
print(f"\n{'=' * 70}")
print("Replicating LVS derivation chain for PM3/PM4")
print("=" * 70)

# Get full-chip layers
activ_all = kdb.Region(top.begin_shapes_rec(li_activ)).merged()
gatpoly_all = kdb.Region(top.begin_shapes_rec(li_gatpoly)).merged()
psd_all = kdb.Region(top.begin_shapes_rec(li_psd)).merged()
nwell_all = kdb.Region(top.begin_shapes_rec(li_nwell)).merged()
salblock_all = kdb.Region(top.begin_shapes_rec(li_salblock)).merged()
extblock_all = kdb.Region(top.begin_shapes_rec(li_extblock)).merged()

# Derivation chain
pactiv = activ_all & psd_all  # pSD-covered Activ
tgate = (gatpoly_all & activ_all)  # gate = poly AND activ (ignoring res_mk for now)
pgate = pactiv & tgate  # PMOS gate
psd_fet = (pactiv & nwell_all).interacting(pgate) - pgate  # PMOS S/D (before salblock)
psd_sal = psd_fet - salblock_all  # S/D after removing salblock

# Probe the results
probe_r = kdb.Region(probe)
print(f"\npactiv in probe: {(pactiv & probe_r).size()} shapes, area={(pactiv & probe_r).area()/1e6:.2f} µm²")
for poly in (pactiv & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

print(f"\npgate in probe: {(pgate & probe_r).size()} shapes, area={(pgate & probe_r).area()/1e6:.2f} µm²")
for poly in (pgate & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

print(f"\npsd_fet (before salblock) in probe: {(psd_fet & probe_r).size()} shapes, area={(psd_fet & probe_r).area()/1e6:.2f} µm²")
for poly in (psd_fet & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

print(f"\nsalblock in probe: {(salblock_all & probe_r).size()} shapes, area={(salblock_all & probe_r).area()/1e6:.2f} µm²")
for poly in (salblock_all & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

print(f"\nextblock in probe: {(extblock_all & probe_r).size()} shapes, area={(extblock_all & probe_r).area()/1e6:.2f} µm²")
for poly in (extblock_all & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

print(f"\npsd_sal (after salblock removal) in probe: {(psd_sal & probe_r).size()} shapes, area={(psd_sal & probe_r).area()/1e6:.2f} µm²")
for poly in (psd_sal & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Also check extblock
psd_sal2 = psd_sal - extblock_all  # some derivations also subtract extblock
print(f"\npsd_sal2 (after extblock too) in probe: {(psd_sal2 & probe_r).size()} shapes, area={(psd_sal2 & probe_r).area()/1e6:.2f} µm²")

# Check: what is the mos_exclude overlay?
# mos_exclude = pwell_block.join(nsd_drw).join(trans_drw).join(emwind_drw).join(emwihv_drw)
#              .join(salblock_drw).join(extblock_drw).join(polyres_drw).join(res_drw)
#              .join(activ_mask).join(recog_diode).join(recog_esd).join(ind_drw)
#              .join(ind_pin).join(substrate_drw).join(nsd_block).join(gatpoly_filler)
li_substrate = layout.layer(40, 0)
substrate_all = kdb.Region(top.begin_shapes_rec(li_substrate)).merged()
print(f"\nsubstrate_drw in probe: {(substrate_all & probe_r).size()} shapes, area={(substrate_all & probe_r).area()/1e6:.2f} µm²")
for poly in (substrate_all & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

polyres_all = kdb.Region(top.begin_shapes_rec(li_polyres)).merged()
print(f"\npolyres_drw in probe: {(polyres_all & probe_r).size()} shapes, area={(polyres_all & probe_r).area()/1e6:.2f} µm²")
for poly in (polyres_all & probe_r).each():
    bb = poly.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# CRITICAL: Check res_mk (layer 52/0 is recognized as PolyRes marker)
# Actually the rppd uses specific marking layers. Let's check ALL layers at PM3/PM4
print(f"\n{'=' * 70}")
print("All non-empty layers in probe area:")
print("=" * 70)
for li_idx in range(layout.layers()):
    li_info = layout.get_info(li_idx)
    r = kdb.Region()
    for si in top.begin_shapes_rec(li_idx):
        bb = si.shape().bbox().transformed(si.trans())
        if probe.overlaps(bb):
            if si.shape().is_box():
                r.insert(si.shape().box.transformed(si.trans()))
            elif si.shape().is_polygon():
                r.insert(si.shape().polygon.transformed(si.trans()))
    if not r.is_empty():
        r = r.merged()
        print(f"  ({li_info.layer}/{li_info.datatype}): {r.size()} shapes, area={r.area()/1e6:.2f} µm²")
        for poly in r.each():
            bb = poly.bbox()
            print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                  f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")
