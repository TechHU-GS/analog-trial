#!/usr/bin/env python3
"""Check M3/M4 connectivity to find gnd|mid_p|vdd merger path.

Traces connectivity through Via1→M2→Via2→M3→Via3→M4 to find where
mid_p metal merges with VDD/GND power.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m3m4_merge.py
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

# Load routing for net identification
with open('output/routing.json') as f:
    routing = json.load(f)
with open('netlist.json') as f:
    netlist = json.load(f)

pin_net = {}
for ne in netlist.get('nets', []):
    for pin in ne['pins']:
        pin_net[pin] = ne['name']

# ─── Build comprehensive net probe map for ALL layers ───
# mid_p probes: from AP positions
midp_probes = []
for pin_key in ['Mp_load_p.D', 'Mp_load_p.G', 'Mp_load_n.G', 'Min_p.D']:
    ap = routing.get('access_points', {}).get(pin_key, {})
    vp = ap.get('via_pad', {})
    for layer_key in ['m1', 'm2', 'm3', 'm4']:
        if layer_key in vp:
            r = vp[layer_key]
            midp_probes.append((pin_key, layer_key, r))
    for stub_key in ['m1_stub', 'm2_stub']:
        stub = ap.get(stub_key)
        if stub:
            midp_probes.append((pin_key, stub_key, stub))

# mid_p route segments
mid_p_route = routing.get('signal_routes', {}).get('mid_p', {})
if mid_p_route:
    for seg in mid_p_route.get('segments', []):
        if len(seg) >= 5:
            x1, y1, x2, y2, code = seg[:5]
            layer_names = {0: 'M1', 1: 'M2', 2: 'M3', 3: 'M4'}
            if code >= 0:
                midp_probes.append(('mid_p_wire', layer_names.get(code, f'L{code}'),
                                    [min(x1,x2)-150, min(y1,y2)-150,
                                     max(x1,x2)+150, max(y1,y2)+150]))

print("=" * 70)
print("mid_p PROBES (from routing.json)")
print("=" * 70)
for pin, layer, r in midp_probes:
    print(f"  {pin:20s} {layer:8s}: [{r[0]},{r[1]},{r[2]},{r[3]}]")

# ─── Full-chip merged regions ───
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()
m2_merged = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
m4_merged = kdb.Region(top.begin_shapes_rec(li_m4)).merged()
v1_all = kdb.Region(top.begin_shapes_rec(li_v1))
v2_all = kdb.Region(top.begin_shapes_rec(li_v2))
v3_all = kdb.Region(top.begin_shapes_rec(li_v3))

# ─── Trace: from mid_p M1 drain pad, flood up through via stack ───
print(f"\n{'=' * 70}")
print("TRACE: mid_p drain M1 → Via1 → M2 → Via2 → M3 → Via3 → M4")
print(f"{'=' * 70}")

# Start from mid_p drain M1 at Mp_load_p.D
drain_m1_probe = kdb.Region(kdb.Box(44800, 84000, 45300, 88000))

# Find M1 polygon containing drain
for poly in m1_merged.each():
    pr = kdb.Region(poly)
    if not (pr & drain_m1_probe).is_empty():
        bb = poly.bbox()
        print(f"\nDrain M1: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

        # Find Via1 on this M1 polygon
        v1_on_drain = v1_all & pr
        print(f"  Via1 on drain M1: {v1_on_drain.count()}")
        for v1 in v1_on_drain.each():
            vb = v1.bbox()
            print(f"    V1: ({vb.left/1e3:.3f},{vb.bottom/1e3:.3f})-"
                  f"({vb.right/1e3:.3f},{vb.top/1e3:.3f})")

            # Find M2 polygon at this Via1
            v1_region = kdb.Region(v1).sized(50)
            m2_at_v1 = m2_merged & v1_region
            for m2p in m2_at_v1.each():
                m2b = m2p.bbox()
                m2_full = kdb.Region()
                for m2q in m2_merged.each():
                    if not (kdb.Region(m2q) & kdb.Region(m2p)).is_empty():
                        m2_full.insert(m2q)
                        break
                # Actually just check the merged polygon
                m2r = kdb.Region(m2p)
                print(f"    M2: ({m2b.left/1e3:.3f},{m2b.bottom/1e3:.3f})-"
                      f"({m2b.right/1e3:.3f},{m2b.top/1e3:.3f})")

                # Find Via2 on this M2 polygon
                v2_on_m2 = v2_all & m2r
                print(f"    Via2 on this M2: {v2_on_m2.count()}")
                for v2 in v2_on_m2.each():
                    v2b = v2.bbox()
                    print(f"      V2: ({v2b.left/1e3:.3f},{v2b.bottom/1e3:.3f})-"
                          f"({v2b.right/1e3:.3f},{v2b.top/1e3:.3f})")

                    # Find M3 polygon at this Via2
                    v2_region = kdb.Region(v2).sized(50)
                    m3_at_v2 = m3_merged & v2_region
                    for m3p in m3_at_v2.each():
                        m3b = m3p.bbox()
                        m3_area = m3p.area() / 1e6
                        print(f"      M3: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                              f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) "
                              f"area={m3_area:.1f}µm²")

# ─── Do the same from source (VDD) ───
print(f"\n{'=' * 70}")
print("TRACE: VDD source M1 → Via1 → M2 → Via2 → M3")
print(f"{'=' * 70}")

source_m1_probe = kdb.Region(kdb.Box(40400, 84000, 40900, 88000))

for poly in m1_merged.each():
    pr = kdb.Region(poly)
    if not (pr & source_m1_probe).is_empty():
        bb = poly.bbox()
        print(f"\nSource M1: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})")

        v1_on_source = v1_all & pr
        print(f"  Via1 on source M1: {v1_on_source.count()}")
        for v1 in v1_on_source.each():
            vb = v1.bbox()
            print(f"    V1: ({vb.left/1e3:.3f},{vb.bottom/1e3:.3f})-"
                  f"({vb.right/1e3:.3f},{vb.top/1e3:.3f})")

            v1_region = kdb.Region(v1).sized(50)
            m2_at_v1 = m2_merged & v1_region
            for m2p in m2_at_v1.each():
                m2b = m2p.bbox()
                m2r = kdb.Region(m2p)
                print(f"    M2: ({m2b.left/1e3:.3f},{m2b.bottom/1e3:.3f})-"
                      f"({m2b.right/1e3:.3f},{m2b.top/1e3:.3f})")

                v2_on_m2 = v2_all & m2r
                print(f"    Via2 on this M2: {v2_on_m2.count()}")
                for v2 in v2_on_m2.each():
                    v2b = v2.bbox()
                    print(f"      V2: ({v2b.left/1e3:.3f},{v2b.bottom/1e3:.3f})-"
                          f"({v2b.right/1e3:.3f},{v2b.top/1e3:.3f})")

                    v2_region = kdb.Region(v2).sized(50)
                    m3_at_v2 = m3_merged & v2_region
                    for m3p in m3_at_v2.each():
                        m3b = m3p.bbox()
                        m3_area = m3p.area() / 1e6
                        print(f"      M3: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                              f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) "
                              f"area={m3_area:.1f}µm²")

# ─── Check if drain M3 and source M3 are same polygon ───
print(f"\n{'=' * 70}")
print("M3 MERGE CHECK: Are mid_p M3 and VDD M3 on same polygon?")
print(f"{'=' * 70}")

# Drain V1 at (44.945,87.395) → M2 → V2 → M3
# Source V1 at (40.565,84.215) → M2 → V2 → M3
# Let me check directly

drain_v1_probe = kdb.Region(kdb.Box(44900, 87300, 45200, 87700))
source_v1_probe = kdb.Region(kdb.Box(40400, 84100, 40900, 84500))

drain_m3_poly = None
source_m3_poly = None

# Trace drain path: M1 → V1 → M2 → V2 → M3
for m1p in m1_merged.each():
    m1r = kdb.Region(m1p)
    if (m1r & drain_v1_probe).is_empty():
        continue
    # Found drain M1, trace via1
    for v1 in (v1_all & m1r).each():
        v1r = kdb.Region(v1).sized(50)
        for m2p in (m2_merged & v1r).each():
            m2r = kdb.Region(m2p)
            for v2 in (v2_all & m2r).each():
                v2r = kdb.Region(v2).sized(50)
                for m3p in (m3_merged & v2r).each():
                    drain_m3_poly = m3p
                    m3b = m3p.bbox()
                    print(f"  Drain reaches M3: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                          f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) area={m3p.area()/1e6:.1f}µm²")

# Trace source path: M1 → V1 → M2 → V2 → M3
for m1p in m1_merged.each():
    m1r = kdb.Region(m1p)
    if (m1r & source_v1_probe).is_empty():
        continue
    for v1 in (v1_all & m1r).each():
        v1r = kdb.Region(v1).sized(50)
        for m2p in (m2_merged & v1r).each():
            m2r = kdb.Region(m2p)
            for v2 in (v2_all & m2r).each():
                v2r = kdb.Region(v2).sized(50)
                for m3p in (m3_merged & v2r).each():
                    source_m3_poly = m3p
                    m3b = m3p.bbox()
                    print(f"  Source reaches M3: ({m3b.left/1e3:.3f},{m3b.bottom/1e3:.3f})-"
                          f"({m3b.right/1e3:.3f},{m3b.top/1e3:.3f}) area={m3p.area()/1e6:.1f}µm²")

if drain_m3_poly is not None and source_m3_poly is not None:
    # Check if they're the same polygon
    dr = kdb.Region(drain_m3_poly)
    sr = kdb.Region(source_m3_poly)
    overlap = dr & sr
    if not overlap.is_empty():
        print(f"\n  *** M3 MERGE: DRAIN AND SOURCE REACH SAME M3 POLYGON! ***")
        print(f"  *** THIS IS THE mid_p ↔ vdd MERGER PATH! ***")
    else:
        print(f"\n  M3: drain and source on DIFFERENT M3 polygons (no merge)")

# ─── Also check all M3 merged polygons for size ───
print(f"\n{'=' * 70}")
print("LARGE M3 MERGED POLYGONS (area > 50µm²)")
print(f"{'=' * 70}")

for i, poly in enumerate(m3_merged.each()):
    area = poly.area() / 1e6
    if area > 50:
        bb = poly.bbox()
        print(f"  M3#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.1f}µm²")

        # Check what nets this might connect
        # Check if it overlaps with drain or source V2 positions
        pr = kdb.Region(poly)
        v2_on_poly = v2_all & pr
        print(f"    Via2 on this M3: {v2_on_poly.count()}")

# ─── Check M4 too ───
print(f"\n{'=' * 70}")
print("M4 MERGE CHECK in OTA region")
print(f"{'=' * 70}")

m4_scan = kdb.Box(38000, 78000, 55000, 95000)
m4_in_scan = m4_merged & kdb.Region(m4_scan)
print(f"\nM4 merged polygons in scan: {m4_in_scan.count()}")
for i, poly in enumerate(m4_in_scan.each()):
    bb = poly.bbox()
    area = poly.area() / 1e6
    if area > 1:  # Show significant M4
        print(f"  M4#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) area={area:.1f}µm²")

print("\n\nDONE.")
