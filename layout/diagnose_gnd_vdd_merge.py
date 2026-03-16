#!/usr/bin/env python3
"""Find where GND and VDD merge in the extracted layout.

Traces connectivity from known GND and VDD points,
identifies shared polygons on each metal layer.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_gnd_vdd_merge.py
"""
import os, sys
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

# Pre-compute merged regions
print("Loading and merging layers...")
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
m4_merged = kdb.Region(top.begin_shapes_rec(li_m4)).merged()
v1_all = kdb.Region(top.begin_shapes_rec(li_v1))
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))
v3_all = kdb.Region(top.begin_shapes_rec(li_v3))

m1_polys = list(m1_merged.each())
m2_polys = list(m2_merged.each())
m3_polys = list(m3_merged.each())
m4_polys = list(m4_merged.each())

print(f"M1: {len(m1_polys)}, M2: {len(m2_polys)}, M3: {len(m3_polys)}, M4: {len(m4_polys)}")


def poly_id(poly):
    bb = poly.bbox()
    return (bb.left, bb.bottom, bb.right, bb.top)


def find_merged_poly(polys, probe_box):
    probe = kdb.Region(probe_box)
    for poly in polys:
        pr = kdb.Region(poly)
        if not (pr & probe).is_empty():
            return poly
    return None


def flood_fill(start_probes, label):
    """Full flood-fill from multiple start points through entire via stack.

    Returns sets of polygon IDs per layer.
    Uses iterative BFS to find ALL connected polygons.
    """
    print(f"\n{'=' * 70}")
    print(f"FLOOD-FILL from {label}")
    print(f"{'=' * 70}")

    m1_set = set()
    m2_set = set()
    m3_set = set()
    m4_set = set()

    # Queues: (layer_name, poly)
    m1_queue = []
    m2_queue = []
    m3_queue = []
    m4_queue = []

    # Seed from probes
    for probe in start_probes:
        for layer_name, polys, queue, pset in [
            ("M1", m1_polys, m1_queue, m1_set),
            ("M2", m2_polys, m2_queue, m2_set),
            ("M3", m3_polys, m3_queue, m3_set),
            ("M4", m4_polys, m4_queue, m4_set),
        ]:
            p = find_merged_poly(polys, probe)
            if p is not None:
                pid = poly_id(p)
                if pid not in pset:
                    pset.add(pid)
                    queue.append(p)

    # BFS iteration
    iteration = 0
    while m1_queue or m2_queue or m3_queue or m4_queue:
        iteration += 1
        if iteration > 500:
            print("  BFS iteration limit reached!")
            break

        # M1 → Via1 → M2
        new_m1 = m1_queue[:]
        m1_queue.clear()
        for m1p in new_m1:
            m1r = kdb.Region(m1p)
            for v1 in (v1_all & m1r).each():
                v1b = v1.bbox()
                center = kdb.Box(v1b.left + 20, v1b.bottom + 20,
                                 v1b.right - 20, v1b.top - 20)
                m2p = find_merged_poly(m2_polys, center)
                if m2p is not None:
                    pid = poly_id(m2p)
                    if pid not in m2_set:
                        m2_set.add(pid)
                        m2_queue.append(m2p)

        # M2 → Via1 → M1
        # M2 → Via2 → M3
        new_m2 = m2_queue[:]
        m2_queue.clear()
        for m2p in new_m2:
            m2r = kdb.Region(m2p)
            # Via1 → M1
            for v1 in (v1_all & m2r).each():
                v1b = v1.bbox()
                center = kdb.Box(v1b.left + 20, v1b.bottom + 20,
                                 v1b.right - 20, v1b.top - 20)
                m1p = find_merged_poly(m1_polys, center)
                if m1p is not None:
                    pid = poly_id(m1p)
                    if pid not in m1_set:
                        m1_set.add(pid)
                        m1_queue.append(m1p)
            # Via2 → M3
            for v2 in (v2_all & m2r).each():
                v2b = v2.bbox()
                center = kdb.Box(v2b.left + 20, v2b.bottom + 20,
                                 v2b.right - 20, v2b.top - 20)
                m3p = find_merged_poly(m3_polys, center)
                if m3p is not None:
                    pid = poly_id(m3p)
                    if pid not in m3_set:
                        m3_set.add(pid)
                        m3_queue.append(m3p)

        # M3 → Via2 → M2
        # M3 → Via3 → M4
        new_m3 = m3_queue[:]
        m3_queue.clear()
        for m3p in new_m3:
            m3r = kdb.Region(m3p)
            # Via2 → M2
            for v2 in (v2_all & m3r).each():
                v2b = v2.bbox()
                center = kdb.Box(v2b.left + 20, v2b.bottom + 20,
                                 v2b.right - 20, v2b.top - 20)
                m2p = find_merged_poly(m2_polys, center)
                if m2p is not None:
                    pid = poly_id(m2p)
                    if pid not in m2_set:
                        m2_set.add(pid)
                        m2_queue.append(m2p)
            # Via3 → M4
            for v3 in (v3_all & m3r).each():
                v3b = v3.bbox()
                center = kdb.Box(v3b.left + 20, v3b.bottom + 20,
                                 v3b.right - 20, v3b.top - 20)
                m4p = find_merged_poly(m4_polys, center)
                if m4p is not None:
                    pid = poly_id(m4p)
                    if pid not in m4_set:
                        m4_set.add(pid)
                        m4_queue.append(m4p)

        # M4 → Via3 → M3
        new_m4 = m4_queue[:]
        m4_queue.clear()
        for m4p in new_m4:
            m4r = kdb.Region(m4p)
            for v3 in (v3_all & m4r).each():
                v3b = v3.bbox()
                center = kdb.Box(v3b.left + 20, v3b.bottom + 20,
                                 v3b.right - 20, v3b.top - 20)
                m3p = find_merged_poly(m3_polys, center)
                if m3p is not None:
                    pid = poly_id(m3p)
                    if pid not in m3_set:
                        m3_set.add(pid)
                        m3_queue.append(m3p)

    print(f"  Summary: M1={len(m1_set)}, M2={len(m2_set)}, M3={len(m3_set)}, M4={len(m4_set)}")
    return m1_set, m2_set, m3_set, m4_set


# ─── VDD probes: known VDD source contacts ───
# Mp_load_p.S source strip at x≈40.66
vdd_probes = [
    kdb.Box(40500, 84000, 40800, 85000),   # Mp_load_p.S (VDD source in OTA)
]

# ─── GND probes: known GND contacts ───
# Use Mc_tail.S GND via1 at (45120,98180) as reliable GND probe
gnd_probes = [
    kdb.Box(45000, 98000, 45300, 98300),   # Mc_tail.S source (GND)
]

vdd_m1, vdd_m2, vdd_m3, vdd_m4 = flood_fill(vdd_probes, "VDD (Mp_load_p.S)")
gnd_m1, gnd_m2, gnd_m3, gnd_m4 = flood_fill(gnd_probes, "GND (ptap)")

# ─── Find merge points ───
print(f"\n{'=' * 70}")
print("GND ↔ VDD MERGE CHECK")
print(f"{'=' * 70}")

for layer_name, vdd_set, gnd_set in [
    ("M1", vdd_m1, gnd_m1),
    ("M2", vdd_m2, gnd_m2),
    ("M3", vdd_m3, gnd_m3),
    ("M4", vdd_m4, gnd_m4),
]:
    common = vdd_set & gnd_set
    if common:
        print(f"\n  *** {layer_name} MERGE: VDD and GND share {len(common)} polygon(s)! ***")
        for pid in sorted(common):
            area = 0
            # Find the polygon to compute area
            for poly in (m1_polys if layer_name == "M1" else
                        m2_polys if layer_name == "M2" else
                        m3_polys if layer_name == "M3" else m4_polys):
                if poly_id(poly) == pid:
                    area = poly.area() / 1e6
                    break
            print(f"    ({pid[0]/1e3:.3f},{pid[1]/1e3:.3f})-"
                  f"({pid[2]/1e3:.3f},{pid[3]/1e3:.3f}) area={area:.1f}µm²")
    else:
        print(f"  {layer_name}: no merge (VDD={len(vdd_set)}, GND={len(gnd_set)})")

print("\n\nDONE.")
