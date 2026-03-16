#!/usr/bin/env python3
"""Detailed analysis of ng=2 device splitting.

Check M1 connectivity within each nmos_buf2 PCell to understand
why some split (S1/S2 on different M1 polygons) and some don't.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_split_detail.py
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

m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
cont_all = kdb.Region(top.begin_shapes_rec(li_cont))
gp_all = kdb.Region(top.begin_shapes_rec(li_gatpoly))
activ_all = kdb.Region(top.begin_shapes_rec(li_activ))

# All nmos_buf2 devices
buf2_devices = ['BN2', 'MS1', 'MS2', 'MS3', 'MS4', 'Mc_tail', 'Mc_inp', 'Mc_inn']

# Also check key ng>1 devices
all_ng_devices = {
    'BN2': 'nmos_buf2', 'MS1': 'nmos_buf2', 'MS2': 'nmos_buf2',
    'MS3': 'nmos_buf2', 'MS4': 'nmos_buf2',
    'Mc_tail': 'nmos_buf2', 'Mc_inp': 'nmos_buf2', 'Mc_inn': 'nmos_buf2',
    'Mpb1': 'pmos_cs8', 'Mnb1': 'nmos_bias8',
    'MN2': 'nmos_vittoz8',
    'Min_p': 'nmos_ota_input', 'Min_n': 'nmos_ota_input',
    'PM_cas3': 'pmos_cas4',
    'Mtail': 'nmos_ota_tail',
    'PM3': 'pmos_mirror', 'PM4': 'pmos_mirror',
    'PM_ref': 'pmos_mirror', 'PM5': 'pmos_mirror',
}

for name, dtype in all_ng_devices.items():
    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)
    inst = placement['instances'].get(name)
    if not inst:
        print(f"\n{name} ({dtype} ng={ng}): NOT IN PLACEMENT")
        continue

    x_nm = int(inst['x_um'] * 1000)
    y_nm = int(inst['y_um'] * 1000)
    w_nm = int(inst['w_um'] * 1000)
    h_nm = int(inst['h_um'] * 1000)
    rot = inst.get('rotation', 0)

    if rot in (90, 270):
        bbox = kdb.Box(x_nm, y_nm, x_nm + h_nm, y_nm + w_nm)
    else:
        bbox = kdb.Box(x_nm, y_nm, x_nm + w_nm, y_nm + h_nm)

    probe = kdb.Region(bbox)
    probe_ext = kdb.Region(kdb.Box(bbox.left - 200, bbox.bottom - 200,
                                    bbox.right + 200, bbox.top + 200))

    # M1 shapes overlapping device bbox
    m1_in_dev = m1_merged & probe_ext
    # GatePoly shapes
    gp_in_dev = gp_all & probe
    # Contacts
    cont_in_dev = cont_all & probe
    # Active
    act_in_dev = activ_all & probe

    # For each M1 polygon, check which contacts it touches
    m1_list = list(m1_in_dev.each())
    cont_list = list(cont_in_dev.each())

    print(f"\n{'='*70}")
    print(f"{name} ({dtype} ng={ng} W={lib['params']['w']} L={lib['params']['l']})")
    print(f"  Placement: ({x_nm/1e3:.3f},{y_nm/1e3:.3f}) rot={rot}")
    print(f"  BBox: ({bbox.left/1e3:.3f},{bbox.bottom/1e3:.3f})-({bbox.right/1e3:.3f},{bbox.top/1e3:.3f})")
    print(f"  GatePoly: {gp_in_dev.count()}, Contacts: {len(cont_list)}, Activ: {act_in_dev.count()}, M1: {len(m1_list)}")

    # Show gate poly positions
    if gp_in_dev.count() <= 12:
        for i, gp in enumerate(gp_in_dev.each()):
            gb = gp.bbox()
            print(f"    GP#{i}: ({gb.left/1e3:.3f},{gb.bottom/1e3:.3f})-({gb.right/1e3:.3f},{gb.top/1e3:.3f})")

    # Show M1 polygons and which contacts they touch
    for i, m1 in enumerate(m1_list):
        mb = m1.bbox()
        m1r = kdb.Region(m1)
        touching_conts = (kdb.Region(c) for c in cont_list)
        touch_count = sum(1 for c in cont_list if not (kdb.Region(c) & m1r).is_empty())
        print(f"    M1#{i}: ({mb.left/1e3:.3f},{mb.bottom/1e3:.3f})-({mb.right/1e3:.3f},{mb.top/1e3:.3f}) "
              f"size={mb.width()/1e3:.3f}x{mb.height()/1e3:.3f} contacts={touch_count}")
