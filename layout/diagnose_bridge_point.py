#!/usr/bin/env python3
"""Find the exact bridge point between VDD and GND by BFS from both sides.

For each shared polygon, trace which VDD-only polygon connects to it and
which GND-only polygon connects to it via a via.  The bridge is the
via that first connects a VDD-only region to a GND-only region.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_bridge_point.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_m3 = layout.layer(30, 0)
li_m4 = layout.layer(50, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)
li_v3 = layout.layer(49, 0)

print("Merging layers...")
layers = {
    'M1': (li_m1, kdb.Region(top.begin_shapes_rec(li_m1)).merged()),
    'M2': (li_m2, kdb.Region(top.begin_shapes_rec(li_m2)).merged()),
    'M3': (li_m3, kdb.Region(top.begin_shapes_rec(li_m3)).merged()),
    'M4': (li_m4, kdb.Region(top.begin_shapes_rec(li_m4)).merged()),
}
vias = {
    'V1': (li_v1, kdb.Region(top.begin_shapes_rec(li_v1)), 'M1', 'M2'),
    'V2': (li_v2, kdb.Region(top.begin_shapes_rec(li_v2)), 'M2', 'M3'),
    'V3': (li_v3, kdb.Region(top.begin_shapes_rec(li_v3)), 'M3', 'M4'),
}

# Build polygon lists with IDs
poly_db = {}  # (layer_name, idx) -> polygon
for lname, (li, region) in layers.items():
    for idx, poly in enumerate(region.each()):
        poly_db[(lname, idx)] = poly

# VDD probe: vdd_exc rail area
vdd_probe = kdb.Region(kdb.Box(50000, 82000, 51000, 83000))
gnd_probe = kdb.Region(kdb.Box(50000, 69000, 51000, 70000))

# BFS from VDD
print("BFS from VDD...")
vdd_set = set()  # (layer_name, idx)
vdd_queue = []
for lname, (li, region) in layers.items():
    probe = vdd_probe if lname == 'M3' else None
    if probe is None:
        continue
    for idx, poly in enumerate(region.each()):
        pr = kdb.Region(poly)
        if not (pr & probe).is_empty():
            key = (lname, idx)
            if key not in vdd_set:
                vdd_set.add(key)
                vdd_queue.append(key)

# BFS
while vdd_queue:
    cur = vdd_queue.pop(0)
    lname, idx = cur
    poly = poly_db[cur]
    pr = kdb.Region(poly)

    for vname, (vli, vreg, lo, hi) in vias.items():
        # Check vias on this polygon
        if lname == lo or lname == hi:
            v_on = vreg & pr
            if v_on.count() == 0:
                continue
            # Find connected polygon on the other layer
            other = hi if lname == lo else lo
            _, other_region = layers[other]
            for v in v_on.each():
                vb = v.bbox()
                cx = (vb.left + vb.right) // 2
                cy = (vb.top + vb.bottom) // 2
                vprobe = kdb.Region(kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50))
                for oidx, opoly in enumerate(other_region.each()):
                    okey = (other, oidx)
                    if okey in vdd_set:
                        continue
                    opr = kdb.Region(opoly)
                    if not (opr & vprobe).is_empty():
                        vdd_set.add(okey)
                        vdd_queue.append(okey)
                        break

print(f"  VDD reachable: {len(vdd_set)}")

# BFS from GND
print("BFS from GND...")
gnd_set = set()
gnd_parent = {}  # key -> (parent_key, via_name, via_cx, via_cy)
gnd_queue = []
for lname, (li, region) in layers.items():
    probe = gnd_probe if lname == 'M3' else None
    if probe is None:
        continue
    for idx, poly in enumerate(region.each()):
        pr = kdb.Region(poly)
        if not (pr & probe).is_empty():
            key = (lname, idx)
            if key not in gnd_set:
                gnd_set.add(key)
                gnd_queue.append(key)
                gnd_parent[key] = None

bridge_found = False
while gnd_queue and not bridge_found:
    cur = gnd_queue.pop(0)
    lname, idx = cur
    poly = poly_db[cur]
    pr = kdb.Region(poly)

    for vname, (vli, vreg, lo, hi) in vias.items():
        if lname == lo or lname == hi:
            v_on = vreg & pr
            if v_on.count() == 0:
                continue
            other = hi if lname == lo else lo
            _, other_region = layers[other]
            for v in v_on.each():
                vb = v.bbox()
                cx = (vb.left + vb.right) // 2
                cy = (vb.top + vb.bottom) // 2
                vprobe = kdb.Region(kdb.Box(cx - 50, cy - 50, cx + 50, cy + 50))
                for oidx, opoly in enumerate(other_region.each()):
                    okey = (other, oidx)
                    if okey in gnd_set:
                        continue
                    opr = kdb.Region(opoly)
                    if not (opr & vprobe).is_empty():
                        gnd_set.add(okey)
                        gnd_queue.append(okey)
                        gnd_parent[okey] = (cur, vname, cx, cy)

                        # Check if this is also in VDD
                        if okey in vdd_set:
                            bridge_found = True
                            obb = opoly.bbox()
                            print(f"\n*** BRIDGE FOUND ***")
                            print(f"  {other}#{oidx}: ({obb.left/1e3:.3f},{obb.bottom/1e3:.3f})-"
                                  f"({obb.right/1e3:.3f},{obb.top/1e3:.3f})")
                            print(f"  Via: {vname} at ({cx/1e3:.3f},{cy/1e3:.3f})")
                            print(f"  From GND-side {lname}#{idx}: ", end="")
                            pbb = poly.bbox()
                            print(f"({pbb.left/1e3:.3f},{pbb.bottom/1e3:.3f})-"
                                  f"({pbb.right/1e3:.3f},{pbb.top/1e3:.3f})")

                            # Trace back GND path
                            print(f"\n  GND path (back-trace):")
                            trace_key = cur
                            depth = 0
                            while trace_key is not None and depth < 20:
                                tl, ti = trace_key
                                tbb = poly_db[trace_key].bbox()
                                parent = gnd_parent.get(trace_key)
                                via_info = ""
                                if parent:
                                    _, pvn, pvx, pvy = parent
                                    via_info = f" via {pvn}@({pvx/1e3:.3f},{pvy/1e3:.3f})"
                                print(f"    {tl}#{ti}: ({tbb.left/1e3:.3f},{tbb.bottom/1e3:.3f})-"
                                      f"({tbb.right/1e3:.3f},{tbb.top/1e3:.3f}){via_info}")
                                trace_key = parent[0] if parent else None
                                depth += 1
                        if bridge_found:
                            break
                if bridge_found:
                    break
        if bridge_found:
            break

print(f"\n  GND reachable: {len(gnd_set)}")
shared = vdd_set & gnd_set
print(f"  Shared: {len(shared)}")

if not bridge_found:
    print("\nNo bridge found via BFS.")

print("\n\nDONE.")
