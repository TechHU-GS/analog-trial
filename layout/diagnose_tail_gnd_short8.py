#!/usr/bin/env python3
"""Phase 8: Identify the bridge M2#565 and M1#611 — what created them?

The short path is:
  tail M1#610 → Via1 → M2#473 → Via1 → M1#611 → Via1 → M2#565 → Via2 → M3#1(gnd)

Questions:
1. What is M2#565? Is it a power drop M2 pad?
2. What is M1#611? Why does it include both tail routing and gnd drop area?
3. Where exactly is the Via1 that connects M1#611 to M2#565?
4. Where is the Via2 that connects M2#565 to M3#1(gnd)?
5. What routing/power data created these shapes?

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_tail_gnd_short8.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

def get_region(layer, dt):
    li = layout.layer(layer, dt)
    return kdb.Region(top.begin_shapes_rec(li))

m1 = get_region(8, 0).merged()
m2 = get_region(10, 0).merged()
m3 = get_region(30, 0).merged()
v1 = get_region(19, 0)
v2 = get_region(29, 0)

m1_polys = list(m1.each())
m2_polys = list(m2.each())
m3_polys = list(m3.each())

# ── Identify the bridge shapes ──
print("="*60)
print("Bridge analysis: M2#565 and M1#611")
print("="*60)

# M2#565
m2_565 = m2_polys[565]
bb = m2_565.bbox()
print(f"\nM2#565: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
print(f"  Size: {bb.width()/1e3:.3f} x {bb.height()/1e3:.3f} µm")
print(f"  Area: {m2_565.area()/1e6:.3f} µm²")
print(f"  Points: {m2_565.num_points()}")
if m2_565.num_points() <= 10:
    for pt in m2_565.each_point_hull():
        print(f"    ({pt.x/1e3:.3f}, {pt.y/1e3:.3f})")

# M1#611
m1_611 = m1_polys[611]
bb = m1_611.bbox()
print(f"\nM1#611: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
print(f"  Size: {bb.width()/1e3:.3f} x {bb.height()/1e3:.3f} µm")
print(f"  Area: {m1_611.area()/1e6:.3f} µm²")
print(f"  Points: {m1_611.num_points()}")
if m1_611.num_points() <= 50:
    for pt in m1_611.each_point_hull():
        print(f"    ({pt.x/1e3:.3f}, {pt.y/1e3:.3f})")

# ── Find Via1 connecting M1#611 to M2#565 ──
print(f"\n--- Via1 between M1#611 and M2#565 ---")
m2_565_r = kdb.Region(m2_565)
m1_611_r = kdb.Region(m1_611)

v1_on_m2_565 = v1 & m2_565_r.sized(10)
print(f"Via1 on M2#565: {v1_on_m2_565.count()}")
for v in v1_on_m2_565.each():
    vbb = v.bbox()
    vc = ((vbb.left+vbb.right)//2, (vbb.bottom+vbb.top)//2)
    # Check if this Via1 is also on M1#611
    vprobe = kdb.Region(kdb.Box(vc[0]-20, vc[1]-20, vc[0]+20, vc[1]+20))
    on_m1_611 = not (m1_611_r & vprobe).is_empty()
    print(f"  Via1 at ({vc[0]/1e3:.3f},{vc[1]/1e3:.3f}) on_M1#611={on_m1_611}")

# ── Find Via2 connecting M2#565 to M3#1(gnd) ──
print(f"\n--- Via2 between M2#565 and M3#1(gnd) ---")
v2_on_m2_565 = v2 & m2_565_r.sized(10)
print(f"Via2 on M2#565: {v2_on_m2_565.count()}")
for v in v2_on_m2_565.each():
    vbb = v.bbox()
    vc = ((vbb.left+vbb.right)//2, (vbb.bottom+vbb.top)//2)
    print(f"  Via2 at ({vc[0]/1e3:.3f},{vc[1]/1e3:.3f})")

# ── Find ALL Via1 on M1#611 to understand its connectivity ──
print(f"\n--- All Via1 on M1#611 ---")
v1_on_611 = v1 & m1_611_r
print(f"Total Via1: {v1_on_611.count()}")
for v in v1_on_611.each():
    vbb = v.bbox()
    vc = ((vbb.left+vbb.right)//2, (vbb.bottom+vbb.top)//2)
    # Find which M2 this connects to
    vprobe = kdb.Region(kdb.Box(vc[0]-20, vc[1]-20, vc[0]+20, vc[1]+20))
    for m2_idx, m2p in enumerate(m2_polys):
        if not (kdb.Region(m2p) & vprobe).is_empty():
            m2bb = m2p.bbox()
            print(f"  Via1 at ({vc[0]/1e3:.3f},{vc[1]/1e3:.3f}) → M2#{m2_idx} "
                  f"({m2bb.left/1e3:.3f},{m2bb.bottom/1e3:.3f})-"
                  f"({m2bb.right/1e3:.3f},{m2bb.top/1e3:.3f})")
            break

# ── Check routing data for the bridge location ──
print(f"\n{'='*60}")
print("Routing data check")
print("="*60)

with open('output/routing_optimized.json') as f:
    routing = json.load(f)

# Check what signal routes pass through the M2#565 area
m2_565_bb = m2_565.bbox()
probe_xl, probe_yb = m2_565_bb.left - 200, m2_565_bb.bottom - 200
probe_xr, probe_yt = m2_565_bb.right + 200, m2_565_bb.top + 200

print(f"\nSignal routes near M2#565 ({m2_565_bb.left/1e3:.3f},{m2_565_bb.bottom/1e3:.3f}):")
for net_name, route in routing.get('signal_routes', {}).items():
    for seg in route.get('segments', []):
        x0, y0, x1, y1, layer = seg[:5]
        # Check if segment overlaps probe area
        sxl, sxr = min(x0, x1), max(x0, x1)
        syb, syt = min(y0, y1), max(y0, y1)
        if sxr >= probe_xl and sxl <= probe_xr and syt >= probe_yb and syb <= probe_yt:
            layer_names = {0: 'M1', 1: 'M2', 2: 'M3', 3: 'M4'}
            ln = layer_names.get(layer, f'L{layer}')
            print(f"  {net_name}: {ln} ({x0/1e3:.3f},{y0/1e3:.3f})-({x1/1e3:.3f},{y1/1e3:.3f})")

# Check power drops near M2#565
print(f"\nPower drops near M2#565:")
power = routing.get('power', {})
for drop in power.get('drops', []):
    dx, dy = drop.get('x', 0), drop.get('y', 0)
    if abs(dx - (m2_565_bb.left + m2_565_bb.right)//2) < 1000 and \
       abs(dy - (m2_565_bb.bottom + m2_565_bb.top)//2) < 1000:
        print(f"  {drop.get('net','?')} drop at ({dx/1e3:.3f},{dy/1e3:.3f})")
        via_stack = drop.get('via_stack', {})
        for k, v in via_stack.items():
            print(f"    {k}: ({v[0]/1e3:.3f},{v[1]/1e3:.3f})-({v[2]/1e3:.3f},{v[3]/1e3:.3f})")

# ── Check what's at M1#611 in terms of device connections ──
print(f"\n{'='*60}")
print("Device connections to M1#611")
print("="*60)

# Find Contacts on M1#611
cont = get_region(6, 0)
cont_on_611 = cont & m1_611_r
print(f"Contacts on M1#611: {cont_on_611.count()}")

# Find Active regions under those contacts
activ = get_region(1, 0)
nwell = get_region(31, 0)
gatpoly = get_region(5, 0)
psd = get_region(14, 0)

# For each contact, classify what it connects to
for c in cont_on_611.each():
    cbb = c.bbox()
    cx, cy = (cbb.left + cbb.right) // 2, (cbb.bottom + cbb.top) // 2
    cprobe = kdb.Region(kdb.Box(cx - 20, cy - 20, cx + 20, cy + 20))

    on_activ = not (activ & cprobe).is_empty()
    on_nw = not (nwell & cprobe).is_empty()
    on_gp = not (gatpoly & cprobe).is_empty()
    on_psd = not (psd & cprobe).is_empty()

    if on_activ and not on_gp:
        kind = "ptap" if (on_psd and not on_nw) else "ntap" if (not on_psd and on_nw) else "S/D"
        print(f"  Contact ({cx/1e3:.3f},{cy/1e3:.3f}): {kind} "
              f"(activ={on_activ} nw={on_nw} gp={on_gp} psd={on_psd})")

# ── Check M1#610 (tail) shape details near M1#611 boundary ──
print(f"\n--- M1#610 (tail) and M1#611 proximity ---")
m1_610 = m1_polys[610]
bb610 = m1_610.bbox()
bb611 = m1_611.bbox()
print(f"M1#610 bbox: ({bb610.left/1e3:.3f},{bb610.bottom/1e3:.3f})-({bb610.right/1e3:.3f},{bb610.top/1e3:.3f})")
print(f"M1#611 bbox: ({bb611.left/1e3:.3f},{bb611.bottom/1e3:.3f})-({bb611.right/1e3:.3f},{bb611.top/1e3:.3f})")
gap_x = max(0, max(bb611.left - bb610.right, bb610.left - bb611.right))
gap_y = max(0, max(bb611.bottom - bb610.top, bb610.bottom - bb611.top))
print(f"Gap: x={gap_x/1e3:.3f}µm, y={gap_y/1e3:.3f}µm")

# ── Check what created M2#565 — is it from assemble_gds power drops? ──
print(f"\n{'='*60}")
print("Checking assemble_gds power drop code")
print("="*60)

# The 480x480nm M2 shape is VIA2_PAD size from pdk.py
# Check if this is a known power drop position
vbars = power.get('vbars', [])
for vb in vbars:
    vx = vb.get('x', 0)
    net = vb.get('net', '?')
    # Check drops on this vbar
    for drop in power.get('drops', []):
        if drop.get('net') == net and abs(drop.get('x', 0) - vx) < 500:
            dx, dy = drop.get('x', 0), drop.get('y', 0)
            if abs(dx - (m2_565_bb.left + m2_565_bb.right)//2) < 500 and \
               abs(dy - (m2_565_bb.bottom + m2_565_bb.top)//2) < 500:
                print(f"  MATCH: vbar net={net} x={vx/1e3:.3f}, "
                      f"drop at ({dx/1e3:.3f},{dy/1e3:.3f})")

# Also: search ALL drops for this position
print(f"\nAll drops within 2µm of M2#565 center:")
cx565 = (m2_565_bb.left + m2_565_bb.right) // 2
cy565 = (m2_565_bb.bottom + m2_565_bb.top) // 2
for drop in power.get('drops', []):
    dx, dy = drop.get('x', 0), drop.get('y', 0)
    if abs(dx - cx565) < 2000 and abs(dy - cy565) < 2000:
        print(f"  {drop.get('net','?')} at ({dx/1e3:.3f},{dy/1e3:.3f}) "
              f"dist=({abs(dx-cx565)/1e3:.3f},{abs(dy-cy565)/1e3:.3f})")

# Check access_points too
print(f"\nAccess points within 2µm of M2#565 center:")
for pin_key, ap in routing.get('access_points', {}).items():
    apx, apy = ap.get('x', 0), ap.get('y', 0)
    if abs(apx - cx565) < 2000 and abs(apy - cy565) < 2000:
        print(f"  {pin_key}: ({apx/1e3:.3f},{apy/1e3:.3f})")
        if ap.get('via_pad'):
            for k, v in ap['via_pad'].items():
                print(f"    via_pad {k}: ({v[0]/1e3:.3f},{v[1]/1e3:.3f})-({v[2]/1e3:.3f},{v[3]/1e3:.3f})")
