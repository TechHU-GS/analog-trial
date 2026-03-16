#!/usr/bin/env python3
"""Diagnose rppd extraction issue: find contacts overlapping SalBlock.

The LVS log says: "No. of ports exist for rppd is 46, should be 2"
This means 46 contact positions overlap the rppd SalBlock marker.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_rppd.py
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# IHP SG13G2 layers
li_salblock = layout.layer(28, 0)  # SalBlock
li_cont = layout.layer(6, 0)      # Contact
li_m1 = layout.layer(8, 0)        # Metal1
li_gatpoly = layout.layer(5, 0)   # GatPoly
li_polyres = layout.layer(128, 0) # PolyRes marker
li_psd = layout.layer(14, 0)      # pSD (p+ implant)
li_extblock = layout.layer(111, 0) # EXTBlock

# Get SalBlock and Contact regions
salblock = kdb.Region(top.begin_shapes_rec(li_salblock))
contacts = kdb.Region(top.begin_shapes_rec(li_cont))
polyres = kdb.Region(top.begin_shapes_rec(li_polyres))
gatpoly = kdb.Region(top.begin_shapes_rec(li_gatpoly))

print(f"SalBlock: {salblock.count()} shapes")
print(f"Contacts: {contacts.count()} shapes")
print(f"PolyRes:  {polyres.count()} shapes")

# SalBlock merged polygons
salblock_merged = salblock.merged()
print(f"\nSalBlock merged: {salblock_merged.count()} polygons")
for i, poly in enumerate(salblock_merged.each()):
    bb = poly.bbox()
    area = poly.area() / 1e6
    print(f"  #{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.1f}µm²")

# Find contacts that overlap with SalBlock
overlap = contacts & salblock
print(f"\nContacts overlapping SalBlock: {overlap.count()}")
for i, c in enumerate(overlap.each()):
    cb = c.bbox()
    print(f"  #{i}: ({cb.left/1e3:.3f},{cb.bottom/1e3:.3f})-"
          f"({cb.right/1e3:.3f},{cb.top/1e3:.3f})")

# Also check PolyRes marker
polyres_merged = polyres.merged()
print(f"\nPolyRes merged: {polyres_merged.count()} polygons")
for i, poly in enumerate(polyres_merged.each()):
    bb = poly.bbox()
    area = poly.area() / 1e6
    print(f"  #{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.1f}µm²")

# For each SalBlock polygon, list overlapping contacts
print("\n=== Per-SalBlock-polygon contact analysis ===")
for i, sb_poly in enumerate(salblock_merged.each()):
    sb_region = kdb.Region(sb_poly)
    sb_contacts = contacts & sb_region
    bb = sb_poly.bbox()
    print(f"\nSalBlock #{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
    print(f"  Overlapping contacts: {sb_contacts.count()}")
    if sb_contacts.count() <= 50:
        for j, c in enumerate(sb_contacts.each()):
            cb = c.bbox()
            print(f"    #{j}: ({cb.left/1e3:.3f},{cb.bottom/1e3:.3f})-"
                  f"({cb.right/1e3:.3f},{cb.top/1e3:.3f})")

# Check GatPoly overlapping PolyRes (the real issue)
print("\n=== GatPoly vs PolyRes analysis ===")
for i, pr_poly in enumerate(polyres_merged.each()):
    pr_region = kdb.Region(pr_poly)
    bb = pr_poly.bbox()
    print(f"\nPolyRes #{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

    # Find GatPoly shapes that overlap
    gp_overlap = gatpoly & pr_region
    print(f"  GatPoly shapes overlapping: {gp_overlap.count()}")

    if gp_overlap.count() <= 60:
        for j, gp in enumerate(gp_overlap.each()):
            gb = gp.bbox()
            print(f"    GP#{j}: ({gb.left/1e3:.3f},{gb.bottom/1e3:.3f})-"
                  f"({gb.right/1e3:.3f},{gb.top/1e3:.3f})")

# Focus on the rppd PolyRes (#3)
print("\n=== rppd PolyRes (#3) detail ===")
rppd_pr = list(polyres_merged.each())[3]
rppd_bb = rppd_pr.bbox()
print(f"rppd PolyRes: ({rppd_bb.left/1e3:.3f},{rppd_bb.bottom/1e3:.3f})-"
      f"({rppd_bb.right/1e3:.3f},{rppd_bb.top/1e3:.3f})")

# Get all GatPoly in this area (broader than PolyRes)
probe = kdb.Region(kdb.Box(rppd_bb.left - 2000, rppd_bb.bottom - 2000,
                            rppd_bb.right + 2000, rppd_bb.top + 2000))
gp_nearby = kdb.Region(top.begin_shapes_rec(li_gatpoly)) & probe
print(f"GatPoly shapes within 2µm of rppd PolyRes: {gp_nearby.count()}")

# Check which ones are INSIDE the PolyRes
gp_inside = gp_nearby & kdb.Region(rppd_pr)
print(f"GatPoly shapes INSIDE rppd PolyRes: {gp_inside.count()}")
for j, gp in enumerate(gp_inside.each()):
    gb = gp.bbox()
    print(f"  GP#{j}: ({gb.left/1e3:.3f},{gb.bottom/1e3:.3f})-"
          f"({gb.right/1e3:.3f},{gb.top/1e3:.3f}) "
          f"size={gb.width()/1e3:.3f}x{gb.height()/1e3:.3f}µm")

print("\nDONE")
