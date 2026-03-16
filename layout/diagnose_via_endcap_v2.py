#!/usr/bin/env python3
"""Trace the source of Via1/Via2 shapes at M2.c1/V2.c1 violation locations.

Check routing.json access points and power drops for matches.

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_via_endcap_v2.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)
li_m1 = layout.layer(8, 0)
li_m3 = layout.layer(30, 0)

with open('output/routing.json') as f:
    routing = json.load(f)

# Violation Via positions (nm)
VIOLS = [
    ('M2.c1 #1 + V2.c1', 197900, 171630, (197805, 171535, 197995, 171725)),
    ('M2.c1 #2', 67230, 240000, (67135, 239905, 67325, 240095)),
    ('M2.c1 #3', 149470, 72000, (149375, 71905, 149565, 72095)),
]

for label, cx, cy, via_rect in VIOLS:
    vx1, vy1, vx2, vy2 = via_rect
    via_cx = (vx1 + vx2) // 2
    via_cy = (vy1 + vy2) // 2
    print(f"\n{'='*70}")
    print(f"{label}: Via at ({vx1},{vy1};{vx2},{vy2}), center=({via_cx},{via_cy})")
    print(f"{'='*70}")

    # Check access points
    print("\n  Access points within 500nm:")
    for key, ap in routing.get('access_points', {}).items():
        ax, ay = ap['x'], ap['y']
        if abs(ax - via_cx) < 500 and abs(ay - via_cy) < 500:
            vp = ap.get('via_pad', {})
            print(f"    {key}: ({ax},{ay}) mode={ap.get('mode')}")
            if vp:
                for lyr, rect in vp.items():
                    print(f"      {lyr}: {rect} size={rect[2]-rect[0]}x{rect[3]-rect[1]}")

    # Check power drops
    print("\n  Power drops within 500nm:")
    for drop in routing.get('power', {}).get('drops', []):
        if 'x' in drop and 'y' in drop:
            dx, dy = drop['x'], drop['y']
            if abs(dx - via_cx) < 500 and abs(dy - via_cy) < 500:
                print(f"    {drop['inst']}.{drop['pin']}: ({dx},{dy}) type={drop['type']}")

    # Check signal routes for via1/via2 at this position
    print("\n  Signal route vias within 200nm:")
    for rname, rd in routing.get('signal_routes', {}).items():
        for seg in rd.get('segments', []):
            sx1, sy1, sx2, sy2, slyr = seg[:5]
            if slyr in ('via1', 'via2'):
                scx = (sx1 + sx2) // 2
                scy = (sy1 + sy2) // 2
                if abs(scx - via_cx) < 200 and abs(scy - via_cy) < 200:
                    print(f"    {rname}: via at ({scx},{scy}) layer={slyr}")

    # Probe ALL layers near the violation
    print(f"\n  All shapes within 300nm:")
    probe = kdb.Box(via_cx - 300, via_cy - 300, via_cx + 300, via_cy + 300)
    for lname, li in [('M1', li_m1), ('Via1', li_v1), ('M2', li_m2),
                       ('Via2', li_v2), ('M3', li_m3)]:
        for si in top.shapes(li).each():
            bb = si.bbox()
            if probe.overlaps(bb):
                print(f"    {lname}: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                      f"{bb.width()}x{bb.height()}")
        # Also subcells
        for inst in top.each_inst():
            cell = inst.cell
            for si in cell.shapes(li).each():
                bb = si.bbox().transformed(inst.trans)
                if probe.overlaps(bb):
                    print(f"    {lname}[{cell.name}]: ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                          f"{bb.width()}x{bb.height()}")

    # Check: is this via from a via_stack power drop?
    print(f"\n  Via_stack drops matching:")
    for drop in routing.get('power', {}).get('drops', []):
        if drop['type'] == 'via_stack':
            inst = drop['inst']
            pin = drop['pin']
            # Get AP position
            ap_key = f"{inst}.{pin}"
            ap = routing.get('access_points', {}).get(ap_key)
            if ap:
                ax, ay = ap['x'], ap['y']
                if abs(ax - via_cx) < 500 and abs(ay - via_cy) < 500:
                    print(f"    via_stack: {ap_key} at ({ax},{ay})")

    # Measure exact gap to nearest M2
    print(f"\n  Nearest M2 edges:")
    min_gap_x = float('inf')
    min_gap_y = float('inf')
    nearest_m2 = None
    for si in top.shapes(li_m2).each():
        bb = si.bbox()
        # X gap
        x_gap = max(vx1 - bb.right, bb.left - vx2)
        # Y gap
        y_gap = max(vy1 - bb.top, bb.bottom - vy2)

        if x_gap <= 0 and y_gap <= 0:
            # Overlapping
            continue
        elif x_gap <= 0:
            dist = y_gap
        elif y_gap <= 0:
            dist = x_gap
        else:
            import math
            dist = math.sqrt(x_gap**2 + y_gap**2)

        if dist < 200:
            print(f"    M2 ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()}: gap={dist:.0f}nm "
                  f"(x_gap={x_gap}, y_gap={y_gap})")
