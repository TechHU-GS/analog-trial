#!/usr/bin/env python3
"""Diagnose gnd|mid_p|vdd extraction merger at FEOL level.

Scans GDS around mid_p device positions for:
1. NWell connectivity — does one NWell region span mid_p devices AND power taps?
2. Active layer bridging — does active cross NWell boundary?
3. Contact/tie connectivity — are there taps connecting well/substrate to mid_p metal?
4. Gate poly crossing unexpected active — phantom MOSFET creation?

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_midp_merger.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
ROUTING = 'output/routing.json'

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# Layer indices (from pdk.py)
li_activ = layout.layer(1, 0)   # ACTIV
li_gatpoly = layout.layer(5, 0) # GATPOLY
li_cont = layout.layer(6, 0)    # CONT (contact)
li_nsd = layout.layer(7, 0)     # NSD (n+ implant)
li_psd = layout.layer(14, 0)    # PSD (p+ implant)
li_nwell = layout.layer(31, 0)  # NWELL
li_m1 = layout.layer(8, 0)      # Metal1

with open(ROUTING) as f:
    routing = json.load(f)
with open('netlist.json') as f:
    netlist = json.load(f)

# Build pin→net map
pin_net = {}
for ne in netlist.get('nets', []):
    for pin in ne['pins']:
        pin_net[pin] = ne['name']

# mid_p device positions from routing.json access_points
mid_p_pins = ['Mp_load_p.D', 'Mp_load_p.G', 'Mp_load_n.G', 'Min_p.D']
print("=" * 70)
print("mid_p DEVICE POSITIONS")
print("=" * 70)
for pin in mid_p_pins:
    ap = routing.get('access_points', {}).get(pin, {})
    net = pin_net.get(pin, '?')
    pos = ap.get('pos', [0, 0])
    print(f"  {pin:20s}  net={net:10s}  pos=({pos[0]/1e3:.3f}, {pos[1]/1e3:.3f})µm")

# Define scan region around mid_p devices (generous bbox)
# From summary: mid_p devices at x≈38000-50000, y≈78000-92000
SCAN_XL = 35000  # nm
SCAN_YB = 75000
SCAN_XR = 55000
SCAN_YT = 95000
scan_box = kdb.Box(SCAN_XL, SCAN_YB, SCAN_XR, SCAN_YT)
scan_region = kdb.Region(scan_box)

print(f"\nScan region: ({SCAN_XL/1e3:.1f},{SCAN_YB/1e3:.1f})-({SCAN_XR/1e3:.1f},{SCAN_YT/1e3:.1f})µm")

# ─── 1. NWell analysis ───
print(f"\n{'=' * 70}")
print("1. NWELL ANALYSIS")
print(f"{'=' * 70}")

nw_all = kdb.Region(top.begin_shapes_rec(li_nwell))
nw_in_scan = nw_all & scan_region
nw_merged = nw_in_scan.merged()

print(f"\nNWell polygons in scan region: {nw_merged.count()}")
for i, poly in enumerate(nw_merged.each()):
    bb = poly.bbox()
    area = poly.area() / 1e6  # µm²
    print(f"  NW#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm "
          f"area={area:.1f}µm²")

# Check: does any single NWell polygon span both mid_p device area AND power taps?
# Power taps = ntap (n+ in NWell) connected to VDD
# Find tie cells in scan region
ties_in_scan = []
for tie in routing.get('ties', {}).get('ties', []):
    for layer_key, rects in tie.get('layers', {}).items():
        for r in rects:
            if r[2] > SCAN_XL and r[0] < SCAN_XR and r[3] > SCAN_YB and r[1] < SCAN_YT:
                ties_in_scan.append(tie)
                break
        else:
            continue
        break

print(f"\nTie cells in scan region: {len(ties_in_scan)}")
for tie in ties_in_scan:
    print(f"  {tie['id']:30s}  net={tie['net']:6s}  inst={tie.get('inst', '?')}")

# ─── 2. Active layer analysis ───
print(f"\n{'=' * 70}")
print("2. ACTIVE LAYER ANALYSIS")
print(f"{'=' * 70}")

activ_all = kdb.Region(top.begin_shapes_rec(li_activ))
activ_in_scan = activ_all & scan_region
activ_merged = activ_in_scan.merged()

# Classify active: inside NWell (PMOS/ntap) vs outside (NMOS/ptap)
activ_in_nw = activ_merged & nw_all  # active inside NWell
activ_out_nw = activ_merged - nw_all  # active outside NWell

print(f"\nActive in NWell (PMOS/ntap): {activ_in_nw.count()} polygons")
for i, poly in enumerate(activ_in_nw.each()):
    bb = poly.bbox()
    w = (bb.right - bb.left)
    h = (bb.top - bb.bottom)
    if w > 500 or h > 500:  # Only show significant shapes
        print(f"  AinNW#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm "
              f"({w}x{h}nm)")

print(f"\nActive outside NWell (NMOS/ptap): {activ_out_nw.count()} polygons")
for i, poly in enumerate(activ_out_nw.each()):
    bb = poly.bbox()
    w = (bb.right - bb.left)
    h = (bb.top - bb.bottom)
    if w > 500 or h > 500:
        print(f"  AoutNW#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm "
              f"({w}x{h}nm)")

# CRITICAL CHECK: Does any active polygon SPAN the NWell boundary?
# This would create a short between NWell (VDD) and substrate (GND)
activ_crossing = kdb.Region()
nw_edge = nw_all.edges()
for poly in activ_merged.each():
    poly_region = kdb.Region(poly)
    in_nw = poly_region & nw_all
    out_nw = poly_region - nw_all
    if not in_nw.is_empty() and not out_nw.is_empty():
        activ_crossing.insert(poly)

print(f"\n*** Active polygons crossing NWell boundary: {activ_crossing.count()} ***")
for i, poly in enumerate(activ_crossing.each()):
    bb = poly.bbox()
    print(f"  CROSSING#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm")
    in_nw = kdb.Region(poly) & nw_all
    out_nw = kdb.Region(poly) - nw_all
    for p in in_nw.each():
        b = p.bbox()
        print(f"    inside NWell:  ({b.left/1e3:.3f},{b.bottom/1e3:.3f})-({b.right/1e3:.3f},{b.top/1e3:.3f})")
    for p in out_nw.each():
        b = p.bbox()
        print(f"    outside NWell: ({b.left/1e3:.3f},{b.bottom/1e3:.3f})-({b.right/1e3:.3f},{b.top/1e3:.3f})")

# ─── 3. Gate poly analysis ───
print(f"\n{'=' * 70}")
print("3. GATE POLY ANALYSIS (phantom devices)")
print(f"{'=' * 70}")

gatpoly_all = kdb.Region(top.begin_shapes_rec(li_gatpoly))
gatpoly_in_scan = gatpoly_all & scan_region

# Find gate poly that crosses active
gate_on_activ = gatpoly_in_scan & activ_merged
print(f"\nGate poly overlapping active in scan: {gate_on_activ.count()} shapes")

# Check: does any gate poly cross an active that spans NWell boundary?
if not activ_crossing.is_empty():
    gate_on_crossing = gatpoly_in_scan & activ_crossing
    print(f"Gate poly on NWell-crossing active: {gate_on_crossing.count()} shapes")
    for i, poly in enumerate(gate_on_crossing.each()):
        bb = poly.bbox()
        print(f"  GateCross#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm")

# ─── 4. NSD/PSD implant analysis ───
print(f"\n{'=' * 70}")
print("4. IMPLANT ANALYSIS")
print(f"{'=' * 70}")

nsd_all = kdb.Region(top.begin_shapes_rec(li_nsd))
psd_all = kdb.Region(top.begin_shapes_rec(li_psd))
nsd_in_scan = nsd_all & scan_region
psd_in_scan = psd_all & scan_region

print(f"\nNSD (n+) in scan: {nsd_in_scan.merged().count()} polygons")
print(f"PSD (p+) in scan: {psd_in_scan.merged().count()} polygons")

# ntap = NSD inside NWell on active (n+ in well → VDD body contact)
# ptap = PSD outside NWell on active (p+ in substrate → GND body contact)
ntap_active = activ_in_nw & nsd_in_scan  # n+ active in NWell (ntap or NMOS s/d... wait)
# Actually: NMOS s/d = NSD on active OUTSIDE NWell
#           PMOS s/d = PSD on active INSIDE NWell
#           ntap = NSD on active INSIDE NWell
#           ptap = PSD on active OUTSIDE NWell

# So ntap and NMOS s/d both use NSD but differ by NWell presence
ntap_regions = activ_in_nw & nsd_in_scan   # NSD + active + NWell = ntap (VDD body tie)
ptap_regions = activ_out_nw & psd_in_scan   # PSD + active - NWell = ptap (GND body tie)

# NMOS s/d = NSD + active - NWell (no gate poly crossing)
nmos_sd = activ_out_nw & nsd_in_scan
# PMOS s/d = PSD + active + NWell (no gate poly crossing)
pmos_sd = activ_in_nw & psd_in_scan

print(f"\nntap (NSD+Active+NWell, VDD body): {ntap_regions.merged().count()} polygons")
print(f"ptap (PSD+Active-NWell, GND body): {ptap_regions.merged().count()} polygons")
print(f"NMOS s/d (NSD+Active-NWell): {nmos_sd.merged().count()} polygons")
print(f"PMOS s/d (PSD+Active+NWell): {pmos_sd.merged().count()} polygons")

# ─── 5. Contact analysis ───
print(f"\n{'=' * 70}")
print("5. CONTACT → M1 CONNECTIVITY near mid_p")
print(f"{'=' * 70}")

cont_all = kdb.Region(top.begin_shapes_rec(li_cont))
cont_in_scan = cont_all & scan_region
m1_all = kdb.Region(top.begin_shapes_rec(li_m1))
m1_in_scan = m1_all & scan_region

# Find contacts on ntap regions
cont_on_ntap = cont_in_scan & ntap_regions
cont_on_ptap = cont_in_scan & ptap_regions

print(f"\nContacts on ntap (VDD body ties): {cont_on_ntap.count()}")
print(f"Contacts on ptap (GND body ties): {cont_on_ptap.count()}")

# For each ntap contact, check which M1 polygon it connects to
# Then check if that M1 polygon also touches mid_p metal
print(f"\n--- ntap contacts and their M1 connections ---")
m1_merged = m1_in_scan.merged()
for i, cont in enumerate(cont_on_ntap.each()):
    cb = cont.bbox()
    cx = (cb.left + cb.right) // 2
    cy = (cb.bottom + cb.top) // 2
    # Find M1 polygon touching this contact
    cont_region = kdb.Region(cont)
    # Expand contact slightly to catch M1
    expanded = cont_region.sized(50)
    m1_touch = m1_merged & expanded
    if not m1_touch.is_empty():
        for m1p in m1_touch.each():
            mb = m1p.bbox()
            print(f"  ntap_cont#{i} ({cx/1e3:.3f},{cy/1e3:.3f})µm → "
                  f"M1 ({mb.left/1e3:.3f},{mb.bottom/1e3:.3f})-({mb.right/1e3:.3f},{mb.top/1e3:.3f})µm")

print(f"\n--- ptap contacts and their M1 connections ---")
for i, cont in enumerate(cont_on_ptap.each()):
    cb = cont.bbox()
    cx = (cb.left + cb.right) // 2
    cy = (cb.bottom + cb.top) // 2
    cont_region = kdb.Region(cont)
    expanded = cont_region.sized(50)
    m1_touch = m1_merged & expanded
    if not m1_touch.is_empty():
        for m1p in m1_touch.each():
            mb = m1p.bbox()
            print(f"  ptap_cont#{i} ({cx/1e3:.3f},{cy/1e3:.3f})µm → "
                  f"M1 ({mb.left/1e3:.3f},{mb.bottom/1e3:.3f})-({mb.right/1e3:.3f},{mb.top/1e3:.3f})µm")

# ─── 6. Specifically check mid_p AP positions ───
print(f"\n{'=' * 70}")
print("6. mid_p AP METAL vs WELL/TAP OVERLAP")
print(f"{'=' * 70}")

# Get mid_p M1 shapes from routing
mid_p_m1_probes = []
for pin in mid_p_pins:
    ap = routing.get('access_points', {}).get(pin, {})
    vp = ap.get('via_pad', {})
    if 'm1' in vp:
        r = vp['m1']
        mid_p_m1_probes.append((pin, r))
    stub = ap.get('m1_stub')
    if stub:
        mid_p_m1_probes.append((pin + '_stub', stub))

print(f"\nmid_p M1 shapes: {len(mid_p_m1_probes)}")
for name, r in mid_p_m1_probes:
    print(f"  {name:25s}: [{r[0]},{r[1]},{r[2]},{r[3]}]")
    rect_region = kdb.Region(kdb.Box(r[0], r[1], r[2], r[3]))
    # Check: does this M1 rect overlap with any M1 connected to ntap/ptap?
    m1_here = m1_merged & rect_region
    if not m1_here.is_empty():
        for mp in m1_here.each():
            # Does this M1 polygon also touch any ntap/ptap contact?
            mp_region = kdb.Region(mp)
            ntap_overlap = mp_region & cont_on_ntap.sized(50)
            ptap_overlap = mp_region & cont_on_ptap.sized(50)
            if not ntap_overlap.is_empty():
                print(f"    *** M1 ALSO CONNECTS TO NTAP (VDD) ***")
            if not ptap_overlap.is_empty():
                print(f"    *** M1 ALSO CONNECTS TO PTAP (GND) ***")

# ─── 7. Full-chip NWell merge check ───
print(f"\n{'=' * 70}")
print("7. FULL-CHIP NWELL MERGE ANALYSIS")
print(f"{'=' * 70}")

nw_full_merged = nw_all.merged()
print(f"\nFull-chip NWell merged polygons: {nw_full_merged.count()}")
for i, poly in enumerate(nw_full_merged.each()):
    bb = poly.bbox()
    area = poly.area() / 1e6
    print(f"  NW_FULL#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm  area={area:.1f}µm²")

# ─── 8. Check full-chip active crossing NWell boundary ───
print(f"\n{'=' * 70}")
print("8. FULL-CHIP ACTIVE CROSSING NWELL BOUNDARY")
print(f"{'=' * 70}")

activ_full = kdb.Region(top.begin_shapes_rec(li_activ)).merged()
activ_crossing_full = kdb.Region()
for poly in activ_full.each():
    poly_region = kdb.Region(poly)
    in_nw = poly_region & nw_all
    out_nw = poly_region - nw_all
    if not in_nw.is_empty() and not out_nw.is_empty():
        activ_crossing_full.insert(poly)

print(f"\nActive polygons crossing NWell boundary (full chip): {activ_crossing_full.count()}")
for i, poly in enumerate(activ_crossing_full.each()):
    bb = poly.bbox()
    w = bb.right - bb.left
    h = bb.top - bb.bottom
    print(f"  CROSS#{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm "
          f"({w}x{h}nm)")
    # Check if gate poly crosses this active
    poly_region = kdb.Region(poly)
    gate_here = gatpoly_all & poly_region
    if not gate_here.is_empty():
        for gp in gate_here.each():
            gb = gp.bbox()
            print(f"    GATE on crossing active: ({gb.left/1e3:.3f},{gb.bottom/1e3:.3f})-"
                  f"({gb.right/1e3:.3f},{gb.top/1e3:.3f})µm")

# ─── 9. M$29 hunt: find PMOS L=4u, all terminals merged ───
print(f"\n{'=' * 70}")
print("9. HUNT FOR M$29 (sg13_lv_pmos L=4u, all terminals gnd|mid_p|vdd)")
print(f"{'=' * 70}")

# M$29 is PMOS L=4u W=0.5u — gate length 4000nm is very long
# PMOS: PSD on active inside NWell, with GatPoly crossing
# Look for gate poly shapes of length ~4000nm crossing active inside NWell

print("\nSearching for ~4000nm gate poly segments on active inside NWell...")
gate_on_pmos_active = gatpoly_all & activ_in_nw
for i, poly in enumerate(gate_on_pmos_active.each()):
    bb = poly.bbox()
    w = bb.right - bb.left
    h = bb.top - bb.bottom
    gate_len = min(w, h)  # gate length = narrower dimension
    if 3500 < gate_len < 4500:  # ~4µm gate length
        print(f"  PMOS_GATE_4u #{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm ({w}x{h}nm) "
              f"gate_L={gate_len}nm")

# Also check for 4u gate on NMOS active (in case misidentified)
gate_on_nmos_active = gatpoly_all & activ_out_nw
print("\nSearching for ~4000nm gate poly segments on active outside NWell...")
for i, poly in enumerate(gate_on_nmos_active.each()):
    bb = poly.bbox()
    w = bb.right - bb.left
    h = bb.top - bb.bottom
    gate_len = min(w, h)
    if 3500 < gate_len < 4500:
        print(f"  NMOS_GATE_4u #{i}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
              f"({bb.right/1e3:.3f},{bb.top/1e3:.3f})µm ({w}x{h}nm) "
              f"gate_L={gate_len}nm")

print("\n\nDONE.")
