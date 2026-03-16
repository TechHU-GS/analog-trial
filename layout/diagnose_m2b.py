#!/usr/bin/env python3
"""Diagnose M2.b=2 violations: exact shapes, origins, and fix options.

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m2b.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)
li_m3 = layout.layer(30, 0)

with open('output/routing.json') as f:
    routing = json.load(f)

M2_MIN_S = 210  # M2.b spacing

# === Violation #1: MBn2.D vs MBp2.G area ===
print("=" * 70)
print("M2.b Violation #1: MBn2.D vs MBp2.G region")
print("=" * 70)

probe1 = kdb.Box(196500, 170500, 199000, 172500)
print("\n  ALL M2 shapes in region (196500-199000, 170500-172500):")
m2_shapes1 = []
for si in top.shapes(li_m2).each():
    bb = si.bbox()
    if probe1.overlaps(bb):
        print(f"    M2 TOP: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()}")
        m2_shapes1.append(('TOP', bb))
for inst in top.each_inst():
    cell = inst.cell
    for si in cell.shapes(li_m2).each():
        bb = si.bbox().transformed(inst.trans)
        if probe1.overlaps(bb):
            print(f"    M2 [{cell.name}]: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()}")
            m2_shapes1.append((cell.name, bb))

print("\n  Via1 shapes in same region:")
for si in top.shapes(li_v1).each():
    bb = si.bbox()
    if probe1.overlaps(bb):
        print(f"    V1 TOP: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
for inst in top.each_inst():
    cell = inst.cell
    for si in cell.shapes(li_v1).each():
        bb = si.bbox().transformed(inst.trans)
        if probe1.overlaps(bb):
            print(f"    V1 [{cell.name}]: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

# Check routing.json for APs near this location
print("\n  Access points within 1um of (197900, 171630):")
for key, ap in routing.get('access_points', {}).items():
    ax, ay = ap['x'], ap['y']
    if abs(ax - 197900) < 1000 and abs(ay - 171630) < 1000:
        vp = ap.get('via_pad', {})
        print(f"    {key}: ({ax},{ay}) mode={ap.get('mode')}")
        for lyr, rect in vp.items():
            print(f"      {lyr}: ({rect[0]},{rect[1]};{rect[2]},{rect[3]}) "
                  f"{rect[2]-rect[0]}x{rect[3]-rect[1]}")
        if ap.get('m2_stub'):
            s = ap['m2_stub']
            print(f"      m2_stub: ({s[0]},{s[1]};{s[2]},{s[3]}) "
                  f"{s[2]-s[0]}x{s[3]-s[1]}")

# M2 pairs with gap < 210nm
print("\n  M2 pairs with gap < M2.b (210nm) in this region:")
for i in range(len(m2_shapes1)):
    for j in range(i+1, len(m2_shapes1)):
        a_src, a = m2_shapes1[i]
        b_src, b = m2_shapes1[j]
        x_gap = max(a.left - b.right, b.left - a.right)
        y_gap = max(a.bottom - b.top, b.bottom - a.top)
        if x_gap <= 0 and y_gap <= 0:
            continue  # overlapping
        gap = max(x_gap, y_gap) if min(x_gap, y_gap) <= 0 else -1
        if 0 < gap < M2_MIN_S:
            print(f"    GAP={gap}nm")
            print(f"      A [{a_src}]: ({a.left},{a.bottom};{a.right},{a.top}) "
                  f"{a.width()}x{a.height()}")
            print(f"      B [{b_src}]: ({b.left},{b.bottom};{b.right},{b.top}) "
                  f"{b.width()}x{b.height()}")


# === Violation #2: Power M2 underpasses near (46000, 76000) ===
print("\n" + "=" * 70)
print("M2.b Violation #2: Power M2 underpasses near (46000, 76000)")
print("=" * 70)

probe2 = kdb.Box(44000, 74000, 48000, 78000)
print("\n  ALL M2 shapes in region (44000-48000, 74000-78000):")
m2_shapes2 = []
for si in top.shapes(li_m2).each():
    bb = si.bbox()
    if probe2.overlaps(bb):
        print(f"    M2 TOP: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()}")
        m2_shapes2.append(('TOP', bb))
for inst in top.each_inst():
    cell = inst.cell
    for si in cell.shapes(li_m2).each():
        bb = si.bbox().transformed(inst.trans)
        if probe2.overlaps(bb):
            print(f"    M2 [{cell.name}]: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()}")
            m2_shapes2.append((cell.name, bb))

print("\n  Via2 shapes in same region:")
for si in top.shapes(li_v2).each():
    bb = si.bbox()
    if probe2.overlaps(bb):
        print(f"    V2 TOP: ({bb.left},{bb.bottom};{bb.right},{bb.top})")
for inst in top.each_inst():
    cell = inst.cell
    for si in cell.shapes(li_v2).each():
        bb = si.bbox().transformed(inst.trans)
        if probe2.overlaps(bb):
            print(f"    V2 [{cell.name}]: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

print("\n  Via1 shapes in same region:")
for si in top.shapes(li_v1).each():
    bb = si.bbox()
    if probe2.overlaps(bb):
        print(f"    V1 TOP: ({bb.left},{bb.bottom};{bb.right},{bb.top})")

# Check routing.json for APs near this location
print("\n  Access points within 2um of (46000, 76000):")
for key, ap in routing.get('access_points', {}).items():
    ax, ay = ap['x'], ap['y']
    if abs(ax - 46000) < 2000 and abs(ay - 76000) < 2000:
        vp = ap.get('via_pad', {})
        print(f"    {key}: ({ax},{ay}) mode={ap.get('mode')}")
        for lyr, rect in vp.items():
            print(f"      {lyr}: ({rect[0]},{rect[1]};{rect[2]},{rect[3]}) "
                  f"{rect[2]-rect[0]}x{rect[3]-rect[1]}")

# Check power drops near this location
print("\n  Power drops within 2um of (46000, 76000):")
for drop in routing.get('power', {}).get('drops', []):
    if 'via1_pos' in drop:
        v1 = drop['via1_pos']
        if abs(v1[0] - 46000) < 2000 and abs(v1[1] - 76000) < 2000:
            print(f"    {drop['inst']}.{drop['pin']}: via1=({v1[0]},{v1[1]}) "
                  f"type={drop['type']} net={drop.get('net', '?')}")
            if 'm3_vbar' in drop:
                vb = drop['m3_vbar']
                print(f"      m3_vbar: x={vb['x']}, y={vb['y1']}..{vb['y2']}")
            if 'm2_jog' in drop:
                jog = drop['m2_jog']
                print(f"      m2_jog: ({jog[0]},{jog[1]};{jog[2]},{jog[3]})")

# M2 pairs with gap < 210nm in region 2
print("\n  M2 pairs with gap < M2.b (210nm) in this region:")
for i in range(len(m2_shapes2)):
    for j in range(i+1, len(m2_shapes2)):
        a_src, a = m2_shapes2[i]
        b_src, b = m2_shapes2[j]
        x_gap = max(a.left - b.right, b.left - a.right)
        y_gap = max(a.bottom - b.top, b.bottom - a.top)
        if x_gap <= 0 and y_gap <= 0:
            continue  # overlapping
        gap = max(x_gap, y_gap) if min(x_gap, y_gap) <= 0 else -1
        if 0 < gap < M2_MIN_S:
            print(f"    GAP={gap}nm")
            print(f"      A [{a_src}]: ({a.left},{a.bottom};{a.right},{a.top}) "
                  f"{a.width()}x{a.height()}")
            print(f"      B [{b_src}]: ({b.left},{b.bottom};{b.right},{b.top}) "
                  f"{b.width()}x{b.height()}")

# Also check signal routes near violation 2
print("\n  Signal route M2 segments near (46000, 76000):")
for rname, rd in routing.get('signal_routes', {}).items():
    for seg in rd.get('segments', []):
        if len(seg) >= 5 and seg[4] == 1:  # M2
            sx1, sy1, sx2, sy2 = seg[:4]
            if (min(sx1,sx2) < 48000 and max(sx1,sx2) > 44000
                    and min(sy1,sy2) < 78000 and max(sy1,sy2) > 74000):
                print(f"    {rname}: ({sx1},{sy1})-({sx2},{sy2}) M2")

print("\nDone.")
