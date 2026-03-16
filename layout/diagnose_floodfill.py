#!/usr/bin/env python3
"""Flood-fill connectivity from mid_p drain and VDD source, checking M3/M4 merge.

Proper approach: for each Via, find the FULL merged polygon that contains it,
then check ALL vias on that full polygon.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_floodfill.py
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
li_cont = layout.layer(6, 0)

# Pre-compute merged regions
print("Loading and merging layers...")
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
m4_merged = kdb.Region(top.begin_shapes_rec(li_m4)).merged()
v1_all = kdb.Region(top.begin_shapes_rec(li_v1))
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))
v3_all = kdb.Region(top.begin_shapes_rec(li_v3))
cont_all = kdb.Region(top.begin_shapes_rec(li_cont))

# Index merged polygons for quick lookup
m1_polys = list(m1_merged.each())
m2_polys = list(m2_merged.each())
m3_polys = list(m3_merged.each())
m4_polys = list(m4_merged.each())

print(f"M1: {len(m1_polys)}, M2: {len(m2_polys)}, M3: {len(m3_polys)}, M4: {len(m4_polys)}")


def find_merged_poly(polys, probe_box):
    """Find the full merged polygon containing the probe point."""
    probe = kdb.Region(probe_box)
    for poly in polys:
        pr = kdb.Region(poly)
        if not (pr & probe).is_empty():
            return poly
    return None


def poly_id(poly):
    """Create a hashable ID for a polygon."""
    bb = poly.bbox()
    return (bb.left, bb.bottom, bb.right, bb.top)


def flood_up(start_m1_probe, label):
    """Flood-fill upward from M1 through via stack. Returns sets of polygon IDs per layer."""
    print(f"\n{'=' * 70}")
    print(f"FLOOD-FILL UP from {label}")
    print(f"{'=' * 70}")

    # Find starting M1 polygon
    m1_poly = find_merged_poly(m1_polys, start_m1_probe)
    if m1_poly is None:
        print("  No M1 polygon found!")
        return {}, {}, {}, {}

    bb = m1_poly.bbox()
    print(f"  M1: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

    m1_set = {poly_id(m1_poly)}
    m2_set = set()
    m3_set = set()
    m4_set = set()

    # M1 → Via1 → M2
    m1r = kdb.Region(m1_poly)
    v1_on_m1 = v1_all & m1r
    print(f"  Via1 on M1: {v1_on_m1.count()}")
    for v1 in v1_on_m1.each():
        v1b = v1.bbox()
        v1_center = kdb.Box(v1b.left + 20, v1b.bottom + 20, v1b.right - 20, v1b.top - 20)
        m2_poly = find_merged_poly(m2_polys, v1_center)
        if m2_poly is not None:
            pid = poly_id(m2_poly)
            if pid not in m2_set:
                m2_set.add(pid)
                m2b = m2_poly.bbox()
                m2_area = m2_poly.area() / 1e6
                print(f"    → M2: ({m2b.left/1e3:.3f},{m2b.bottom/1e3:.3f})-"
                      f"({m2b.right/1e3:.3f},{m2b.top/1e3:.3f}) area={m2_area:.2f}µm²")

                # M2 → Via2 → M3
                m2r = kdb.Region(m2_poly)
                v2_on_m2 = v2_all & m2r
                if v2_on_m2.count() > 0:
                    print(f"      Via2 on M2: {v2_on_m2.count()}")
                for v2 in v2_on_m2.each():
                    v2b = v2.bbox()
                    v2_center = kdb.Box(v2b.left + 20, v2b.bottom + 20, v2b.right - 20, v2b.top - 20)
                    m3_poly = find_merged_poly(m3_polys, v2_center)
                    if m3_poly is not None:
                        pid3 = poly_id(m3_poly)
                        if pid3 not in m3_set:
                            m3_set.add(pid3)
                            m3b = m3_poly.bbox()
                            m3_area = m3_poly.area() / 1e6
                            print(f"      → M3: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                                  f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) area={m3_area:.1f}µm²")

                            # M3 → Via3 → M4
                            m3r = kdb.Region(m3_poly)
                            v3_on_m3 = v3_all & m3r
                            if v3_on_m3.count() > 0:
                                print(f"        Via3 on M3: {v3_on_m3.count()}")
                            for v3 in v3_on_m3.each():
                                v3b = v3.bbox()
                                v3_center = kdb.Box(v3b.left + 20, v3b.bottom + 20,
                                                    v3b.right - 20, v3b.top - 20)
                                m4_poly = find_merged_poly(m4_polys, v3_center)
                                if m4_poly is not None:
                                    pid4 = poly_id(m4_poly)
                                    if pid4 not in m4_set:
                                        m4_set.add(pid4)
                                        m4b = m4_poly.bbox()
                                        print(f"        → M4: ({m4b.left/1e3:.3f},{m4b.bottom/1e3:.3f})-"
                                              f"({m4b.right/1e3:.3f},{m4b.top/1e3:.3f})")

    print(f"\n  Summary: M1={len(m1_set)}, M2={len(m2_set)}, M3={len(m3_set)}, M4={len(m4_set)}")
    return m1_set, m2_set, m3_set, m4_set


# ─── Flood from mid_p drain ───
drain_probe = kdb.Box(44900, 85000, 45200, 86000)
drain_m1, drain_m2, drain_m3, drain_m4 = flood_up(drain_probe, "mid_p DRAIN (Mp_load_p.D)")

# ─── Flood from VDD source ───
source_probe = kdb.Box(40500, 85000, 40800, 86000)
source_m1, source_m2, source_m3, source_m4 = flood_up(source_probe, "VDD SOURCE (Mp_load_p.S)")

# ─── Also check mid_p gate ───
gate_probe = kdb.Box(42700, 82000, 43000, 82200)
gate_m1, gate_m2, gate_m3, gate_m4 = flood_up(gate_probe, "mid_p GATE (Mp_load_p.G)")

# ─── Also check Min_p.D ───
minp_probe = kdb.Box(38100, 79000, 38400, 80000)
minp_m1, minp_m2, minp_m3, minp_m4 = flood_up(minp_probe, "mid_p DRAIN (Min_p.D)")

# ─── Check for overlaps ───
print(f"\n{'=' * 70}")
print("MERGE CHECK")
print(f"{'=' * 70}")

for layer_name, drain_set, source_set in [
    ("M1", drain_m1, source_m1),
    ("M2", drain_m2, source_m2),
    ("M3", drain_m3, source_m3),
    ("M4", drain_m4, source_m4),
]:
    common = drain_set & source_set
    if common:
        print(f"\n  *** {layer_name} MERGE: drain and source share {len(common)} polygon(s)! ***")
        for pid in common:
            print(f"    ({pid[0]/1e3:.3f},{pid[1]/1e3:.3f})-({pid[2]/1e3:.3f},{pid[3]/1e3:.3f})")
    else:
        print(f"  {layer_name}: no merge (drain={len(drain_set)}, source={len(source_set)})")

# Check gate-source merge
for layer_name, gate_set, source_set in [
    ("M1", gate_m1, source_m1),
    ("M2", gate_m2, source_m2),
    ("M3", gate_m3, source_m3),
    ("M4", gate_m4, source_m4),
]:
    common = gate_set & source_set
    if common:
        print(f"\n  *** {layer_name} MERGE: gate and source share {len(common)} polygon(s)! ***")
        for pid in common:
            print(f"    ({pid[0]/1e3:.3f},{pid[1]/1e3:.3f})-({pid[2]/1e3:.3f},{pid[3]/1e3:.3f})")

# Check Min_p drain-source merge
for layer_name, minp_set, source_set in [
    ("M1", minp_m1, source_m1),
    ("M2", minp_m2, source_m2),
    ("M3", minp_m3, source_m3),
    ("M4", minp_m4, source_m4),
]:
    common = minp_set & source_set
    if common:
        print(f"\n  *** {layer_name} MERGE: Min_p.D and VDD source share {len(common)} polygon(s)! ***")
        for pid in common:
            print(f"    ({pid[0]/1e3:.3f},{pid[1]/1e3:.3f})-({pid[2]/1e3:.3f},{pid[3]/1e3:.3f})")

# ─── Also: check all mid_p sets against GND ───
# Find GND by tracing from a ptap contact
print(f"\n{'=' * 70}")
print("FLOOD from GND (ptap at y≈87.3)")
print(f"{'=' * 70}")
gnd_probe = kdb.Box(42000, 87200, 42300, 87500)
gnd_m1, gnd_m2, gnd_m3, gnd_m4 = flood_up(gnd_probe, "GND PTAP")

for layer_name, drain_set, gnd_set in [
    ("M1", drain_m1, gnd_m1),
    ("M2", drain_m2, gnd_m2),
    ("M3", drain_m3, gnd_m3),
    ("M4", drain_m4, gnd_m4),
]:
    common = drain_set & gnd_set
    if common:
        print(f"\n  *** {layer_name} MERGE: drain and GND share {len(common)} polygon(s)! ***")
        for pid in common:
            print(f"    ({pid[0]/1e3:.3f},{pid[1]/1e3:.3f})-({pid[2]/1e3:.3f},{pid[3]/1e3:.3f})")

print("\n\nDONE.")
