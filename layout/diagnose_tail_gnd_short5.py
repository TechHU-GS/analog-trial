#!/usr/bin/env python3
"""Trace gnd↔tail short — Phase 5: replicate IHP LVS derivation.

Computes nsd_ptap_abutt exactly as the IHP LVS does, then checks if
any abutment exists within the tail M1 polygon.

Also checks ptap → pwell → nsd_fet connectivity path.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short5.py
"""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

def get_region(layer, dt):
    li = layout.layer(layer, dt)
    return kdb.Region(top.begin_shapes_rec(li))

# ── Raw layers ──
activ = get_region(1, 0)
gatpoly = get_region(5, 0)
psd_drw = get_region(14, 0)
nwell_drw = get_region(31, 0)
cont_drw = get_region(6, 0)
m1 = get_region(8, 0).merged()

# ── IHP LVS derivations (from general_derivations.lvs) ──
# nactiv = activ.not(psd_drw.join(nsd_block))
# (ignoring nsd_block as we likely don't have it)
nactiv = activ - psd_drw
# pactiv = activ.and(psd_drw)
pactiv = activ & psd_drw

# CHIP = entire bounding box
bb = top.bbox()
CHIP = kdb.Region(bb)

# pwell = CHIP.not(nwell_drw)  (simplified, ignoring pwell_block/digisub)
pwell = CHIP - nwell_drw

# tgate = gatpoly (simplified — full derivation includes salblock etc.)
tgate = gatpoly

# ngate = nactiv.and(tgate)
ngate = nactiv & tgate

# nsd_fet = nactiv.not(nwell_drw).interacting(ngate).not(ngate)
nsd_fet = (nactiv - nwell_drw).interacting(ngate) - ngate

# ptap = pactiv.and(pwell).not(ptap1_mk).not(recog_diode).not(gatpoly)
# (ptap1_mk needs substrate_drw.and(pwell).interacting("sub!" label) — likely empty)
ptap = (pactiv & pwell) - gatpoly

# nsd_sal = nsd_fet (ignoring salblock)
nsd_sal = nsd_fet
ptap_sal = ptap

print(f"nactiv: {nactiv.count()} shapes")
print(f"pactiv: {pactiv.count()} shapes")
print(f"nsd_fet: {nsd_fet.count()} shapes")
print(f"ptap: {ptap.count()} shapes")

# ── nsd_ptap_abutt = shared edges ──
# nsd_ptap_abutt = nsd_sal.edges.and(ptap_sal.edges).extended(:in => 1.nm, :out => 1.nm)
nsd_edges = nsd_sal.edges()
ptap_edges = ptap_sal.edges()
shared_edges = nsd_edges & ptap_edges  # edges in common

print(f"\nnsd_sal edges: {nsd_edges.count()}")
print(f"ptap_sal edges: {ptap_edges.count()}")
print(f"Shared edges (nsd_ptap_abutt before extend): {shared_edges.count()}")

if shared_edges.count() > 0:
    # Convert shared edges to region by extending 1nm each side
    nsd_ptap_abutt = shared_edges.extended(1, 1, 0, 0)  # in, out, begin, end
    print(f"nsd_ptap_abutt shapes: {nsd_ptap_abutt.count()}")

    # Show the abutment locations
    print("\n=== nsd_ptap_abutt locations ===")
    for e in shared_edges.each():
        p1, p2 = e.p1, e.p2
        print(f"  ({p1.x/1e3:.3f},{p1.y/1e3:.3f})-({p2.x/1e3:.3f},{p2.y/1e3:.3f})")

    # Check if any abutment is in the tail M1 polygon area
    tail_probe = kdb.Region(kdb.Box(38470, 70680, 46185, 80145))
    abutt_in_tail = kdb.Region(nsd_ptap_abutt) & tail_probe
    if not abutt_in_tail.is_empty():
        print(f"\n*** ABUTMENT IN TAIL M1 AREA: {abutt_in_tail.count()} ***")
        for p in abutt_in_tail.each():
            bb = p.bbox()
            print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
    else:
        print("\nNo abutment in tail M1 area")
else:
    print("\nNo shared edges — no nsd_ptap_abutt")

# ── Also check: ptap regions near tail area ──
print("\n=== ptap regions in wider OTA area ===")
ota_probe = kdb.Region(kdb.Box(30000, 65000, 55000, 85000))
ptap_in_ota = ptap & ota_probe
print(f"ptap in OTA area: {ptap_in_ota.count()} shapes")
for p in ptap_in_ota.each():
    bb = p.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
          f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

# ── Check nsd_fet near tail area ──
print("\n=== nsd_fet regions in OTA area ===")
nsd_in_ota = nsd_fet & ota_probe
print(f"nsd_fet in OTA area: {nsd_in_ota.count()} shapes")
for p in nsd_in_ota.each():
    bb = p.bbox()
    # Only show if near a ptap
    for pt in ptap_in_ota.each():
        ptbb = pt.bbox()
        dist_x = max(0, max(bb.left - ptbb.right, ptbb.left - bb.right))
        dist_y = max(0, max(bb.bottom - ptbb.top, ptbb.bottom - bb.top))
        if dist_x < 500 and dist_y < 500:  # within 500nm
            print(f"  nsd_fet ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
                  f" near ptap ({ptbb.left/1e3:.3f},{ptbb.bottom/1e3:.3f})-"
                  f"({ptbb.right/1e3:.3f},{ptbb.top/1e3:.3f})"
                  f" dist=({dist_x/1e3:.3f},{dist_y/1e3:.3f})")
            break

# ── For completeness: check pwell_sub connectivity ──
# pwell connects everything not in NWell. If two nsd_fet regions in different
# NMOSes are both in pwell, and ptap connects to pwell, then:
# gnd-ptap → pwell → (bulk of ALL NMOS) → but NOT to S/D
# The gnd|tail short must come from nsd_ptap_abutt or from M1 short
print("\n=== Summary ===")
print(f"If nsd_ptap_abutt exists in tail area: tail(nsd_fet) → ptap → pwell → gnd")
print(f"If NO abutment: the short must be through M1/metal connectivity")
