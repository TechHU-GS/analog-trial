#!/usr/bin/env python3
"""Trace gnd↔tail short — Phase 4: check if tie cell M1 is on same merged
polygon as tail label. Also check Substrate(40/0) connectivity.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short4.py
"""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

L = {
    'M1':   layout.layer(8, 0),
    'Cont': layout.layer(6, 0),
    'Activ': layout.layer(1, 0),
    'NW':   layout.layer(31, 0),
    'Sub':  layout.layer(40, 0),
    'pSD':  layout.layer(14, 0),
    'nSD':  layout.layer(7, 0),
    'GP':   layout.layer(5, 0),
}

m1_merged = kdb.Region(top.begin_shapes_rec(L['M1'])).merged()
m1_polys = list(m1_merged.each())
print(f"Total merged M1 polygons: {len(m1_polys)}")

# Find which merged polygon contains a given point
def find_poly_idx(x, y, expand=20):
    probe = kdb.Region(kdb.Box(x - expand, y - expand, x + expand, y + expand))
    for idx, poly in enumerate(m1_polys):
        if not (kdb.Region(poly) & probe).is_empty():
            return idx
    return -1

# Tail label position
tail_idx = find_poly_idx(45550, 75750)
print(f"\nTail label at (45.550, 75.750) → M1 polygon #{tail_idx}")
if tail_idx >= 0:
    bb = m1_polys[tail_idx].bbox()
    print(f"  bbox: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
          f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

# Check each tie cell candidate center
tie_centers = [
    (41620, 70830, "tie_a"),
    (46000, 70830, "tie_b"),
    (40590, 77330, "tie_c"),
    (42970, 77330, "tie_d"),
    (45350, 77330, "tie_e"),
    (40320, 70830, "tie_f"),
]

print("\n=== Tie cell M1 polygon assignment ===")
for cx, cy, name in tie_centers:
    idx = find_poly_idx(cx, cy)
    same = "*** SAME AS TAIL ***" if idx == tail_idx else ""
    print(f"  {name} at ({cx/1e3:.3f},{cy/1e3:.3f}) → M1#{idx} {same}")

# Check if the tail merged polygon actually includes these tie cells
# by testing point-in-polygon
tail_poly = m1_polys[tail_idx] if tail_idx >= 0 else None
if tail_poly:
    print(f"\n=== Point-in-polygon test for tail M1 ===")
    for cx, cy, name in tie_centers:
        # KLayout point-in-polygon: use inside() method
        pt = kdb.Point(cx, cy)
        inside = tail_poly.inside(pt)
        print(f"  {name} ({cx/1e3:.3f},{cy/1e3:.3f}): inside={inside}")

# Check Substrate (40/0) shapes near tail region
print("\n=== Substrate (40/0) in tail region ===")
sub_region = kdb.Region(top.begin_shapes_rec(L['Sub']))
tail_probe = kdb.Region(kdb.Box(35000, 68000, 50000, 83000))
sub_in_tail = sub_region & tail_probe
print(f"  {sub_in_tail.count()} shapes")
for p in sub_in_tail.each():
    bb = p.bbox()
    print(f"  ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})"
          f"-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
          f" {bb.width()/1e3:.1f}x{bb.height()/1e3:.1f}")

# Check what the tail M1 polygon looks like (dump edges to understand shape)
if tail_poly:
    print(f"\n=== Tail M1 polygon details ===")
    print(f"  Area: {tail_poly.area()/1e6:.3f} µm²")
    print(f"  Perimeter: {tail_poly.perimeter()/1e3:.1f} µm")
    num_points = tail_poly.num_points()
    print(f"  Points: {num_points}")
    # For complex polygons, show simplified outline
    if num_points > 50:
        print(f"  (too many points to list, showing bbox only)")
    else:
        for i, pt in enumerate(tail_poly.each_point_hull()):
            print(f"    ({pt.x/1e3:.3f}, {pt.y/1e3:.3f})")

# Find ALL M1 polygons that overlap the Substrate region
# These would be candidates for substrate connections
print("\n=== M1 polygons overlapping Substrate(40/0) ===")
for p in sub_in_tail.each():
    sub_bb = p.bbox()
    sub_probe = kdb.Region(p)
    for idx, m1p in enumerate(m1_polys):
        overlap = kdb.Region(m1p) & sub_probe
        if not overlap.is_empty():
            m1bb = m1p.bbox()
            same = "*** TAIL ***" if idx == tail_idx else ""
            print(f"  Sub ({sub_bb.left/1e3:.1f},{sub_bb.bottom/1e3:.1f})"
                  f"-({sub_bb.right/1e3:.1f},{sub_bb.top/1e3:.1f})"
                  f" → M1#{idx} ({m1bb.left/1e3:.1f},{m1bb.bottom/1e3:.1f})"
                  f"-({m1bb.right/1e3:.1f},{m1bb.top/1e3:.1f}) {same}")

# Check Contact(6/0) → Active(1/0) in substrate area for tail M1
print("\n=== Contact + Active + Substrate check for tail M1 polygon ===")
cont_region = kdb.Region(top.begin_shapes_rec(L['Cont']))
activ_region = kdb.Region(top.begin_shapes_rec(L['Activ']))
nw_region = kdb.Region(top.begin_shapes_rec(L['NW']))
gp_region = kdb.Region(top.begin_shapes_rec(L['GP']))

# Find contacts on the tail M1 polygon
if tail_poly:
    tail_region = kdb.Region(tail_poly)
    contacts_on_tail = cont_region & tail_region
    print(f"  Contacts on tail M1: {contacts_on_tail.count()}")

    # For each contact, check if it's on:
    # - Active in substrate (no NWell) = ptap candidate
    # - Active under GatePoly = MOSFET S/D
    for c in contacts_on_tail.each():
        cbb = c.bbox()
        cx, cy = (cbb.left + cbb.right) // 2, (cbb.bottom + cbb.top) // 2
        pt_probe = kdb.Region(kdb.Box(cx - 20, cy - 20, cx + 20, cy + 20))

        on_activ = not (activ_region & pt_probe).is_empty()
        on_nw = not (nw_region & pt_probe).is_empty()
        on_sub = not (sub_region & pt_probe).is_empty()
        on_gp = not (gp_region & pt_probe).is_empty()
        on_psd = not (kdb.Region(top.begin_shapes_rec(L['pSD'])) & pt_probe).is_empty()

        if on_activ and on_sub and not on_nw and not on_gp:
            print(f"  *** PTAP-LIKE: Contact at ({cx/1e3:.3f},{cy/1e3:.3f})"
                  f" Activ={on_activ} Sub={on_sub} NW={on_nw} GP={on_gp} pSD={on_psd}")
        elif on_activ and on_sub and not on_nw:
            print(f"  Sub+Activ: Contact at ({cx/1e3:.3f},{cy/1e3:.3f})"
                  f" Activ={on_activ} Sub={on_sub} NW={on_nw} GP={on_gp} pSD={on_psd}")
