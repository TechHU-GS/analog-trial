#!/usr/bin/env python3
"""Trace gnd↔tail short — Phase 6: DEFINITIVE check.

Use KLayout's LayoutToNetlist to extract connectivity and find
which net the tail label position is on, and whether it connects to gnd.

If that's too complex, fall back to: find ALL ptap M1 shapes,
check which merged M1 polygon each is on, and if any matches tail's polygon.

Also check: does the tail M1 polygon touch any Substrate(40/0) shape?
Does the M1 label placement itself bridge two nets?

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short6.py
"""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

def get_region(layer, dt):
    li = layout.layer(layer, dt)
    return kdb.Region(top.begin_shapes_rec(li))

# ── Compute ptap exactly as IHP LVS ──
activ = get_region(1, 0)
psd_drw = get_region(14, 0)
nwell_drw = get_region(31, 0)
gatpoly = get_region(5, 0)
cont_drw = get_region(6, 0)
m1 = get_region(8, 0).merged()

pactiv = activ & psd_drw
bb = top.bbox()
CHIP = kdb.Region(bb)
pwell = CHIP - nwell_drw
ptap = (pactiv & pwell) - gatpoly

print(f"ptap: {ptap.count()} shapes total")

# ── Build ptap M1 connection map ──
# ptap → cont_drw → metal1
# For each ptap shape, find Contacts that overlap, then find M1 that overlaps those contacts.
m1_polys = list(m1.each())

# Find tail M1 polygon
tail_probe = kdb.Region(kdb.Box(45500, 75700, 45600, 75800))
tail_poly_idx = -1
for idx, poly in enumerate(m1_polys):
    if not (kdb.Region(poly) & tail_probe).is_empty():
        tail_poly_idx = idx
        break
print(f"Tail M1 polygon: #{tail_poly_idx}")
if tail_poly_idx >= 0:
    tbb = m1_polys[tail_poly_idx].bbox()
    print(f"  bbox: ({tbb.left/1e3:.3f},{tbb.bottom/1e3:.3f})-({tbb.right/1e3:.3f},{tbb.top/1e3:.3f})")

# For each ptap shape, trace Contact → M1 → which polygon index
print(f"\n=== ptap → Contact → M1 mapping ===")
ptap_on_tail = []
for p_idx, ptap_shape in enumerate(ptap.each()):
    ptap_r = kdb.Region(ptap_shape)
    # Find contacts overlapping this ptap
    contacts = cont_drw & ptap_r
    if contacts.is_empty():
        continue
    # Find M1 overlapping these contacts
    m1_at_contacts = m1 & contacts.sized(10)  # 10nm tolerance
    if m1_at_contacts.is_empty():
        continue

    # Which merged polygon?
    for m1_shape in m1_at_contacts.each():
        m1_center = kdb.Point(
            (m1_shape.bbox().left + m1_shape.bbox().right) // 2,
            (m1_shape.bbox().bottom + m1_shape.bbox().top) // 2)
        probe = kdb.Region(kdb.Box(m1_center.x - 20, m1_center.y - 20,
                                   m1_center.x + 20, m1_center.y + 20))
        for m_idx, m_poly in enumerate(m1_polys):
            if not (kdb.Region(m_poly) & probe).is_empty():
                ptbb = ptap_shape.bbox()
                mbb = m_poly.bbox()
                same = "*** ON TAIL M1 ***" if m_idx == tail_poly_idx else ""
                if same or m_idx == tail_poly_idx:
                    print(f"  ptap ({ptbb.left/1e3:.1f},{ptbb.bottom/1e3:.1f})-"
                          f"({ptbb.right/1e3:.1f},{ptbb.top/1e3:.1f})"
                          f" → M1#{m_idx} {same}")
                    ptap_on_tail.append((ptbb, m_idx))
                break

if ptap_on_tail:
    print(f"\n*** FOUND {len(ptap_on_tail)} ptap(s) on tail M1 polygon ***")
    print("This is the gnd/tail short!")
else:
    print("\nNo ptap on tail M1 polygon via Contact→M1 path")
    # Check ALL ptap polygons and their M1 more broadly
    print("\nChecking ptap → M1 for ALL ptap (not just contact-connected):")
    for ptap_shape in ptap.each():
        ptap_r = kdb.Region(ptap_shape)
        ptbb = ptap_shape.bbox()
        # Check if ptap bbox overlaps tail M1 polygon bbox
        if (ptbb.right > tbb.left and ptbb.left < tbb.right and
            ptbb.top > tbb.bottom and ptbb.bottom < tbb.top):
            print(f"  ptap ({ptbb.left/1e3:.3f},{ptbb.bottom/1e3:.3f})-"
                  f"({ptbb.right/1e3:.3f},{ptbb.top/1e3:.3f})"
                  f" overlaps tail M1 bbox!")

# ── Alternative: check if tail M1 has ANY path to pwell/substrate ──
# The IHP LVS connects: pwell ↔ ptap ↔ cont_drw ↔ metal1_con
# If metal1_con includes ALL M1 (not just ptap M1), then ANY M1 shape
# that has a Contact to Active would connect to... no, contacts are layer-specific.

# Actually, let me check: what is metal1_con vs metal1_drw?
# In the IHP LVS layers_definitions.lvs:
# metal1_con = get_polygons(8, 0)  (M1 shapes)
# metal1_text = labels(8, 25)  (M1 labels)
# The connect chain is:
# ptap → cont_drw → metal1_con
# nsd_fet → cont_drw → metal1_con
# So Contact connects BOTH ptap and nsd_fet to M1.
# But ptap and nsd_fet are different layers — Contact only creates
# connections between layers it overlaps.

print("\n=== Cross-checking with routing data ===")
import json
with open('output/routing_optimized.json') as f:
    routing = json.load(f)

# Find all access points for 'tail' pins
route = routing['signal_routes'].get('tail', {})
pins = route.get('pins', [])
aps = routing.get('access_points', {})
print(f"tail pins: {pins}")
for pin in pins:
    ap = aps.get(pin, {})
    if ap:
        print(f"  {pin}: pos=({ap['x']/1e3:.3f},{ap['y']/1e3:.3f})")
        if ap.get('via_pad'):
            vp = ap['via_pad']
            for k, r in vp.items():
                print(f"    via_pad {k}: ({r[0]/1e3:.3f},{r[1]/1e3:.3f})-({r[2]/1e3:.3f},{r[3]/1e3:.3f})")
        if ap.get('m1_stub'):
            s = ap['m1_stub']
            print(f"    m1_stub: ({s[0]/1e3:.3f},{s[1]/1e3:.3f})-({s[2]/1e3:.3f},{s[3]/1e3:.3f})")

# Check: do any tail AP M1 stubs reach outside the tail area and touch gnd M1?
print("\n=== Checking tail AP M1 stubs for gnd M1 overlap ===")
gnd_route = routing['signal_routes'].get('gnd')
if gnd_route:
    print("gnd is a signal route!")
else:
    # gnd is power. Check if any tail M1 stub overlaps power drop M1
    print("gnd is power net, checking drops:")
    drops = routing.get('power', {}).get('drops', [])
    tail_m1_r = kdb.Region(m1_polys[tail_poly_idx]) if tail_poly_idx >= 0 else kdb.Region()
    for drop in drops:
        if drop.get('net') == 'gnd':
            # Check if drop has via_stack with M1
            via_stack = drop.get('via_stack')
            if via_stack:
                for layer_key, rect in via_stack.items():
                    if 'M1' in layer_key or 'm1' in layer_key:
                        drop_r = kdb.Region(kdb.Box(*rect))
                        overlap = tail_m1_r & drop_r
                        if not overlap.is_empty():
                            print(f"  *** OVERLAP: gnd drop M1 at ({rect[0]/1e3:.3f},{rect[1]/1e3:.3f})"
                                  f" touches tail M1! ***")

# ── Final check: is there a Substrate(40/0) shape that connects M1 to substrate? ──
sub = get_region(40, 0)
sub_on_tail = sub & kdb.Region(m1_polys[tail_poly_idx]) if tail_poly_idx >= 0 else kdb.Region()
print(f"\nSubstrate(40/0) overlapping tail M1: {sub_on_tail.count()} shapes")

# ── Check gnd label position — is gnd M3 label on an M3 shape
# that connects (via Via2) to an M2 that connects (via Via1) to the tail M1? ──
print("\n=== Tracing gnd → tail reverse path ===")
# The gnd M3 labels are on M3 rails. These connect to M2 via Via2 drops.
# If any M2 drop from a gnd rail connects (via Via1) to the tail M1 polygon,
# that's the bridge.
m2 = get_region(10, 0).merged()
v1 = get_region(19, 0)
v2 = get_region(29, 0)

# Find Via1 on the tail M1 polygon
v1_on_tail = v1 & tail_m1_r if tail_poly_idx >= 0 else kdb.Region()
print(f"Via1 on tail M1: {v1_on_tail.count()}")

# Find M2 touching those Via1
m2_from_tail = m2 & v1_on_tail.sized(10)
print(f"M2 connected to tail via Via1: {m2_from_tail.count()}")

# For each tail-connected M2, check if it also has Via2 connecting to M3 (gnd)
for m2p in m2_from_tail.each():
    m2bb = m2p.bbox()
    m2r = kdb.Region(m2p)
    v2_on_m2 = v2 & m2r.sized(10)
    if not v2_on_m2.is_empty():
        print(f"  M2 ({m2bb.left/1e3:.3f},{m2bb.bottom/1e3:.3f})-"
              f"({m2bb.right/1e3:.3f},{m2bb.top/1e3:.3f})"
              f" has {v2_on_m2.count()} Via2!")
        # Check if Via2 connects to gnd M3
        m3 = get_region(30, 0)
        m3_from_v2 = m3 & v2_on_m2.sized(10)
        for m3p in m3_from_v2.each():
            m3bb = m3p.bbox()
            # Is this M3 on a gnd rail?
            for lbl_shape in top.shapes(layout.layer(30, 25)).each():
                if lbl_shape.is_text() and lbl_shape.text.string == 'gnd':
                    lbl_pt = kdb.Point(lbl_shape.text.x, lbl_shape.text.y)
                    lbl_probe = kdb.Region(kdb.Box(lbl_pt.x - 50, lbl_pt.y - 50,
                                                    lbl_pt.x + 50, lbl_pt.y + 50))
                    if not (kdb.Region(m3p) & lbl_probe).is_empty():
                        print(f"    *** M3 connects to gnd label at"
                              f" ({lbl_pt.x/1e3:.3f},{lbl_pt.y/1e3:.3f})! ***")
                        print(f"    M3 shape: ({m3bb.left/1e3:.3f},{m3bb.bottom/1e3:.3f})-"
                              f"({m3bb.right/1e3:.3f},{m3bb.top/1e3:.3f})")
                        print(f"    PATH: tail M1 → Via1 → M2 → Via2 → M3 (gnd)")
