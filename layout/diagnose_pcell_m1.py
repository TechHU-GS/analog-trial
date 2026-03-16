#!/usr/bin/env python3
"""Check PCell internal M1 structure for multi-finger devices.

For each ng>1 PCell, examine what M1 shapes are inside the PCell bbox
vs what's added by routing. Determine if S1/S2 (or D1/D2) contacts
need external M1 bridging.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_pcell_m1.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

with open('placement.json') as f:
    placement = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_cont = layout.layer(6, 0)
li_gatpoly = layout.layer(5, 0)
li_activ = layout.layer(1, 0)

# Get NON-MERGED M1 shapes (to see individual PCell shapes vs routing shapes)
m1_shapes = []
for si in top.begin_shapes_rec(li_m1):
    m1_shapes.append(si.shape().polygon.transformed(si.trans()))

print(f"Total M1 shapes (unmerged): {len(m1_shapes)}")

# Focus on one nmos_buf2 device to understand PCell M1 structure
focus_devices = ['MS1', 'Mc_tail', 'Mnb1', 'Mpb1']

for devname in focus_devices:
    inst = placement['instances'].get(devname)
    if not inst:
        print(f"\n{devname}: NOT IN PLACEMENT")
        continue

    dtype = inst['type']
    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)

    x_nm = int(inst['x_um'] * 1000)
    y_nm = int(inst['y_um'] * 1000)
    w_nm = int(inst['w_um'] * 1000)
    h_nm = int(inst['h_um'] * 1000)
    rot = inst.get('rotation', 0)

    if rot in (90, 270):
        bbox = kdb.Box(x_nm, y_nm, x_nm + h_nm, y_nm + w_nm)
    else:
        bbox = kdb.Box(x_nm, y_nm, x_nm + w_nm, y_nm + h_nm)

    print(f"\n{'='*70}")
    print(f"{devname} ({dtype} ng={ng} W={lib['params']['w']} L={lib['params']['l']})")
    print(f"  BBox: ({bbox.left/1e3:.3f},{bbox.bottom/1e3:.3f})-({bbox.right/1e3:.3f},{bbox.top/1e3:.3f})")

    # Find M1 shapes INSIDE the device bbox
    probe = kdb.Region(bbox)
    m1_inside = []
    m1_overlap = []
    for poly in m1_shapes:
        pr = kdb.Region(poly)
        overlap = pr & probe
        if not overlap.is_empty():
            pb = poly.bbox()
            # Is it fully inside or partially overlapping?
            fully_inside = (pb.left >= bbox.left and pb.right <= bbox.right and
                          pb.bottom >= bbox.bottom and pb.top <= bbox.top)
            m1_overlap.append((poly, fully_inside))

    print(f"  M1 shapes touching bbox: {len(m1_overlap)}")
    for i, (poly, inside) in enumerate(m1_overlap):
        pb = poly.bbox()
        tag = "INSIDE" if inside else "OVERLAP"
        print(f"    M1#{i}: ({pb.left/1e3:.3f},{pb.bottom/1e3:.3f})-({pb.right/1e3:.3f},{pb.top/1e3:.3f}) "
              f"size={pb.width()/1e3:.3f}x{pb.height()/1e3:.3f}µm [{tag}]")

    # Find contacts inside device
    cont_region = kdb.Region(top.begin_shapes_rec(li_cont)) & probe
    # Find gate poly inside device
    gp_region = kdb.Region(top.begin_shapes_rec(li_gatpoly)) & probe
    # Find active inside device
    act_region = kdb.Region(top.begin_shapes_rec(li_activ)) & probe

    print(f"  Contacts: {cont_region.count()}")
    print(f"  GatePoly: {gp_region.count()}")
    print(f"  Active: {act_region.count()}")

    # For ng=2, identify which contacts are S1, D (shared), S2
    if ng == 2 and gp_region.count() == 2:
        gp_list = sorted(gp_region.each(), key=lambda p: p.bbox().left)
        gp1_bb = gp_list[0].bbox()
        gp2_bb = gp_list[1].bbox()

        print(f"\n  Gate poly positions:")
        print(f"    GP1: x={gp1_bb.left/1e3:.3f}-{gp1_bb.right/1e3:.3f}")
        print(f"    GP2: x={gp2_bb.left/1e3:.3f}-{gp2_bb.right/1e3:.3f}")
        print(f"    S1 region: x < {gp1_bb.left/1e3:.3f}")
        print(f"    D_shared region: x = {gp1_bb.right/1e3:.3f}-{gp2_bb.left/1e3:.3f}")
        print(f"    S2 region: x > {gp2_bb.right/1e3:.3f}")

        # Find contacts in each region
        for region_name, x_start, x_end in [
            ("S1", bbox.left, gp1_bb.left),
            ("D_shared", gp1_bb.right, gp2_bb.left),
            ("S2", gp2_bb.right, bbox.right)
        ]:
            region_box = kdb.Region(kdb.Box(x_start, bbox.bottom, x_end, bbox.top))
            region_conts = cont_region & region_box
            # Find M1 shapes touching these contacts
            m1_merged_here = kdb.Region()
            for poly, _ in m1_overlap:
                pr = kdb.Region(poly)
                if not (pr & region_box).is_empty():
                    m1_merged_here.insert(poly)
            m1_merged_here = m1_merged_here.merged()

            print(f"    {region_name}: {region_conts.count()} contacts, "
                  f"{m1_merged_here.count()} M1 polygon(s)")
            for m1p in m1_merged_here.each():
                mb = m1p.bbox()
                print(f"      M1: ({mb.left/1e3:.3f},{mb.bottom/1e3:.3f})-({mb.right/1e3:.3f},{mb.top/1e3:.3f})")
