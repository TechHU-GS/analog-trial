#!/usr/bin/env python3
"""Reproduce IHP SG13G2 Gat.a1 DRC check exactly.

Derivation chain (from ihp-sg13g2.drc):
  pwell_allowed = CHIP - pwell_block(46,21)
  digisub_gap   = digisub(60,0) edge ring
  pwell         = pwell_allowed - nwell(31,0) - digisub_gap
  nactiv        = activ(1,0) - (psd(14,0) | nsd_block(7,21))
  nact_fet      = nactiv & pwell
  ngate         = nact_fet & gatpoly(5,0)
  ngate_lv      = ngate - thickgateox(32,0)

Gat.a1: ngate_lv.edges.inside_part(activ).width(0.13µm, euclidian)
"""
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
Gat_a1 = 130  # nm

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Get layers
def get_layer(ln, dt):
    li = layout.find_layer(ln, dt)
    if li is None:
        print(f"  Layer ({ln},{dt}): NOT FOUND — returning empty")
        return kdb.Region()
    return kdb.Region(top.begin_shapes_rec(li))

activ = get_layer(1, 0)
gatpoly = get_layer(5, 0)
psd = get_layer(14, 0)
nsd_block = get_layer(7, 21)
nwell = get_layer(31, 0)
thickgateox = get_layer(32, 0)
pwell_block = get_layer(46, 21)
digisub = get_layer(60, 0)

# Derive pwell
chip = kdb.Region(top.bbox())
pwell_allowed = chip - pwell_block
digisub_gap = digisub - digisub.sized(-1)  # 1nm edge ring
pwell = pwell_allowed - nwell - digisub_gap

# Derive ngate_lv
nactiv = activ - (psd + nsd_block)
nact_fet = nactiv & pwell
ngate = nact_fet & gatpoly
ngate_lv = ngate - thickgateox

print(f"Layer counts:")
print(f"  activ:       {activ.count()} shapes")
print(f"  gatpoly:     {gatpoly.count()} shapes")
print(f"  psd:         {psd.count()} shapes")
print(f"  nsd_block:   {nsd_block.count()} shapes")
print(f"  nwell:       {nwell.count()} shapes")
print(f"  thickgateox: {thickgateox.count()} shapes")
print(f"  pwell_block: {pwell_block.count()} shapes")
print(f"  digisub:     {digisub.count()} shapes")
print(f"  nactiv:      {nactiv.count()} shapes")
print(f"  nact_fet:    {nact_fet.count()} shapes")
print(f"  ngate:       {ngate.count()} shapes")
print(f"  ngate_lv:    {ngate_lv.count()} shapes")

# The DRC check: ngate_lv.edges.inside_part(activ).width(Gat_a1)
ngate_edges = ngate_lv.edges()
inside_edges = ngate_edges.inside_part(activ)

print(f"\n  ngate_lv edges:  {ngate_edges.count()}")
print(f"  inside_part(activ): {inside_edges.count()}")

# Run width check
violations = inside_edges.width_check(Gat_a1)  # Returns EdgePairs

print(f"\nGat.a1 violations (width < {Gat_a1}nm): {violations.count()}")
print("=" * 70)

for i, ep in enumerate(violations.each()):
    e1 = ep.first
    e2 = ep.second
    # Compute gap
    dx = abs(e1.p1.x + e1.p2.x - e2.p1.x - e2.p2.x) // 2
    dy = abs(e1.p1.y + e1.p2.y - e2.p1.y - e2.p2.y) // 2
    gap = max(dx, dy) if min(dx, dy) < 10 else (dx**2 + dy**2)**0.5

    print(f"\nV{i+1}: gap≈{gap:.0f}nm")
    print(f"  E1: ({e1.p1.x/1e3:.3f},{e1.p1.y/1e3:.3f})-({e1.p2.x/1e3:.3f},{e1.p2.y/1e3:.3f})")
    print(f"  E2: ({e2.p1.x/1e3:.3f},{e2.p1.y/1e3:.3f})-({e2.p2.x/1e3:.3f},{e2.p2.y/1e3:.3f})")

    # Find what ngate shapes are at this location
    mx = (e1.p1.x + e1.p2.x + e2.p1.x + e2.p2.x) // 4
    my = (e1.p1.y + e1.p2.y + e2.p1.y + e2.p2.y) // 4
    probe = kdb.Region(kdb.Box(mx - 2000, my - 2000, mx + 2000, my + 2000))

    # Show ngate shapes near violation
    nearby_ngate = ngate_lv & probe
    print(f"  Nearby ngate_lv shapes:")
    for p in nearby_ngate.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}]"
              f" ({b.width()}x{b.height()}nm)")

    # Show gatpoly shapes near violation
    nearby_poly = gatpoly & probe
    print(f"  Nearby gatpoly shapes:")
    for p in nearby_poly.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}]"
              f" ({b.width()}x{b.height()}nm)")

    # Show activ shapes near violation
    nearby_activ = activ & probe
    print(f"  Nearby activ shapes:")
    for p in nearby_activ.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}]"
              f" ({b.width()}x{b.height()}nm)")

    # Check: which cell is this in?
    li_poly = layout.layer(5, 0)
    search = kdb.Box(mx - 500, my - 500, mx + 500, my + 500)
    print(f"  Source cells (gatpoly near violation):")
    for si in top.begin_shapes_rec_overlapping(li_poly, search):
        cell_name = layout.cell(si.cell_index()).name
        box = si.shape().bbox().transformed(si.trans())
        print(f"    {cell_name}: [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
              f"[{box.right/1e3:.3f},{box.top/1e3:.3f}] ({box.width()}x{box.height()}nm)")

# Deep dive: what creates the 120nm strip?
print("\n" + "=" * 70)
print("ROOT CAUSE ANALYSIS")
print("=" * 70)

for i, ep in enumerate(violations.each()):
    e1 = ep.first
    e2 = ep.second
    mx = (e1.p1.x + e1.p2.x + e2.p1.x + e2.p2.x) // 4
    my = (e1.p1.y + e1.p2.y + e2.p1.y + e2.p2.y) // 4

    # Wider probe to see context
    probe = kdb.Region(kdb.Box(mx - 5000, my - 5000, mx + 5000, my + 5000))

    print(f"\nAround violation V{i+1} (center {mx/1e3:.3f}, {my/1e3:.3f}):")

    # Step-by-step derivation
    local_activ = activ & probe
    local_psd = psd & probe
    local_nwell = nwell & probe
    local_gatpoly = gatpoly & probe
    local_nactiv = nactiv & probe
    local_pwell = pwell & probe
    local_nact_fet = nact_fet & probe
    local_ngate = ngate & probe
    local_ngate_lv = ngate_lv & probe

    print(f"\n  activ shapes:")
    for p in local_activ.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  psd shapes:")
    for p in local_psd.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  nwell shapes:")
    for p in local_nwell.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  nactiv (activ - psd):")
    for p in local_nactiv.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  pwell:")
    for p in local_pwell.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  nact_fet (nactiv & pwell):")
    for p in local_nact_fet.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  gatpoly:")
    for p in local_gatpoly.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  ngate (nact_fet & gatpoly):")
    for p in local_ngate.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")

    print(f"\n  ngate_lv:")
    for p in local_ngate_lv.each():
        b = p.bbox()
        print(f"    [{b.left/1e3:.3f},{b.bottom/1e3:.3f}]-[{b.right/1e3:.3f},{b.top/1e3:.3f}] ({b.width()}x{b.height()}nm)")
