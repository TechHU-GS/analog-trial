#!/usr/bin/env python3
"""For each M2.b violation: is the conflict at a wire endpoint (trimmable)
or along the wire body (needs reroute/shift)?

Also checks: could trimming the wire endpoint to remove X/Y overlap
with the pad fix a body-alongside violation?"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb
import xml.etree.ElementTree as ET
from atk.pdk import M2_MIN_S, M2_SIG_W, VIA1_PAD, M2_MIN_W

GDS = 'output/ptat_vco.gds'
LYRDB = '/tmp/drc_verify_now/ptat_vco_ptat_vco_full.lyrdb'

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m2 = layout.layer(10, 0)

hw = M2_SIG_W // 2  # 150nm

# Collect all unmerged M2 shapes
all_m2 = []
for si in top.begin_shapes_rec(li_m2):
    box = si.shape().bbox().transformed(si.trans())
    all_m2.append((box.left, box.bottom, box.right, box.top))

# Parse violations
tree = ET.parse(LYRDB)
root = tree.getroot()
items_el = root.find('items')
viols = []
for item in items_el.findall('item'):
    cat = item.find('category').text.strip().strip("'\"")
    if cat != 'M2.b':
        continue
    values = item.find('values')
    if values is None:
        continue
    for v in values.findall('value'):
        if v.text:
            viols.append(v.text.strip())
            break

def find_shape_at_edge(ex, ey, edge_coord, is_vert):
    """Find the unmerged M2 shape whose edge is at edge_coord."""
    best = None
    best_dist = 9999999
    for s in all_m2:
        sl, sb, sr, st = s
        # Check if shape contains/is near the edge midpoint
        if sl - 200 <= ex <= sr + 200 and sb - 200 <= ey <= st + 200:
            if is_vert:
                if abs(sl - edge_coord) <= 5 or abs(sr - edge_coord) <= 5:
                    d = abs((sl+sr)//2 - ex) + abs((sb+st)//2 - ey)
                    if d < best_dist:
                        best = s
                        best_dist = d
            else:
                if abs(sb - edge_coord) <= 5 or abs(st - edge_coord) <= 5:
                    d = abs((sl+sr)//2 - ex) + abs((sb+st)//2 - ey)
                    if d < best_dist:
                        best = s
                        best_dist = d
    return best

def classify(s):
    if s is None:
        return '?'
    w = s[2] - s[0]
    h = s[3] - s[1]
    if 470 <= w <= 490 and 470 <= h <= 490:
        return 'AP_PAD'
    if w == 200 and h > 500:
        return 'VBAR'
    if h == 200 and w > 500:
        return 'HBAR'
    if w == 300 or h == 300:
        return 'WIRE'
    if w == 160 or h == 160:
        return 'WIRE_N'
    return f'({w}x{h})'

def is_wire(s):
    if s is None:
        return False
    w = s[2] - s[0]
    h = s[3] - s[1]
    return w == 300 or h == 300 or w == 160 or h == 160

def is_pad(s):
    if s is None:
        return False
    w = s[2] - s[0]
    h = s[3] - s[1]
    return 470 <= w <= 490 and 470 <= h <= 490

print(f"M2.b Trimability Analysis ({len(viols)} violations)")
print(f"M2_MIN_S={M2_MIN_S}nm, wire hw={hw}nm")
print("=" * 70)

ep_trimmable = 0
body_alongside = 0
power_shift = 0
unfixable = 0

for vi, coords in enumerate(viols):
    parts = coords.replace('edge-pair: ', '').replace('(', '').replace(')', '')
    sep = '|' if '|' in parts else '/'
    sides = parts.split(sep)

    edges = []
    for side in sides:
        pts = side.strip().split(';')
        edge_pts = []
        for pt in pts:
            xy = pt.split(',')
            edge_pts.append((int(float(xy[0]) * 1000), int(float(xy[1]) * 1000)))
        edges.append(edge_pts)

    e1, e2 = edges[0], edges[1]
    e1_dx = abs(e1[0][0] - e1[1][0])
    e1_dy = abs(e1[0][1] - e1[1][1])
    e1_vert = e1_dy > e1_dx
    e1_coord = e1[0][0] if e1_vert else e1[0][1]
    e1_mx = (e1[0][0] + e1[1][0]) // 2
    e1_my = (e1[0][1] + e1[1][1]) // 2

    e2_dx = abs(e2[0][0] - e2[1][0])
    e2_dy = abs(e2[0][1] - e2[1][1])
    e2_vert = e2_dy > e2_dx
    e2_coord = e2[0][0] if e2_vert else e2[0][1]
    e2_mx = (e2[0][0] + e2[1][0]) // 2
    e2_my = (e2[0][1] + e2[1][1]) // 2

    gap = abs(e1_coord - e2_coord)
    needed = max(0, M2_MIN_S - gap)

    s1 = find_shape_at_edge(e1_mx, e1_my, e1_coord, e1_vert)
    s2 = find_shape_at_edge(e2_mx, e2_my, e2_coord, e2_vert)

    t1 = classify(s1)
    t2 = classify(s2)

    # Determine if the violation edge is at a wire ENDPOINT or BODY
    # For an H-wire [xl, y, xr, y]: left/right edges are endpoints, top/bottom are body
    # For a V-wire [x, yl, x, yh]: top/bottom edges are endpoints, left/right are body
    fix_type = 'UNKNOWN'

    wire_s = s1 if is_wire(s1) else (s2 if is_wire(s2) else None)
    pad_s = s1 if is_pad(s1) else (s2 if is_pad(s2) else None)

    if wire_s is not None:
        wl, wb, wr, wt = wire_s
        ww, wh = wr - wl, wt - wb
        is_h_wire = ww > wh  # horizontal wire

        if is_h_wire:
            # H-wire: left edge=wl, right edge=wr are endpoints
            # Violation edge: if vertical at x=wl or x=wr → endpoint
            wire_edge = e1_coord if (s1 == wire_s and e1_vert) else \
                        e2_coord if (s2 == wire_s and e2_vert) else None

            if wire_edge is not None:
                if abs(wire_edge - wl) <= 5 or abs(wire_edge - wr) <= 5:
                    fix_type = f'ENDPOINT_TRIM (+{needed}nm)'
                    ep_trimmable += 1
                else:
                    fix_type = f'BODY_ALONGSIDE'
                    body_alongside += 1
            else:
                # Horizontal edge of H-wire = body alongside
                # But check: can trimming endpoint remove X overlap with pad?
                if pad_s:
                    pl, pb, pr, pt = pad_s
                    # Overlap in X
                    x_overlap_l = max(wl, pl)
                    x_overlap_r = min(wr, pr)
                    if x_overlap_r > x_overlap_l:
                        # There IS X overlap. Can we trim an endpoint to remove it?
                        trim_right = wr - pl + 5  # trim right endpoint left past pad left edge
                        trim_left = pr - wl + 5   # trim left endpoint right past pad right edge
                        remaining_r = (wr - trim_right) - wl if trim_right > 0 else ww
                        remaining_l = wr - (wl + trim_left) if trim_left > 0 else ww
                        if trim_right <= 280 and remaining_r >= M2_MIN_W:
                            fix_type = f'BODY→EP_TRIM_R (-{trim_right}nm from right)'
                            ep_trimmable += 1
                        elif trim_left <= 280 and remaining_l >= M2_MIN_W:
                            fix_type = f'BODY→EP_TRIM_L (-{trim_left}nm from left)'
                            ep_trimmable += 1
                        else:
                            fix_type = f'BODY_NO_TRIM (need {min(trim_right,trim_left)}nm > 280 max)'
                            body_alongside += 1
                    else:
                        fix_type = 'BODY_ALONGSIDE (no X overlap???)'
                        body_alongside += 1
                else:
                    fix_type = 'BODY_ALONGSIDE'
                    body_alongside += 1
        else:
            # V-wire: bottom=wb, top=wt are endpoints; left=wl, right=wr are body
            wire_edge = e1_coord if (s1 == wire_s and not e1_vert) else \
                        e2_coord if (s2 == wire_s and not e2_vert) else None

            if wire_edge is not None:
                if abs(wire_edge - wb) <= 5 or abs(wire_edge - wt) <= 5:
                    fix_type = f'ENDPOINT_TRIM (+{needed}nm)'
                    ep_trimmable += 1
                else:
                    fix_type = f'BODY_ALONGSIDE'
                    body_alongside += 1
            else:
                # Vertical edge of V-wire = body alongside
                if pad_s:
                    pl, pb, pr, pt = pad_s
                    y_overlap_b = max(wb, pb)
                    y_overlap_t = min(wt, pt)
                    if y_overlap_t > y_overlap_b:
                        trim_top = wt - pb + 5
                        trim_bot = pt - wb + 5
                        remaining_t = (wt - trim_top) - wb if trim_top > 0 else wh
                        remaining_b = wt - (wb + trim_bot) if trim_bot > 0 else wh
                        if trim_top <= 280 and remaining_t >= M2_MIN_W:
                            fix_type = f'BODY→EP_TRIM_T (-{trim_top}nm from top)'
                            ep_trimmable += 1
                        elif trim_bot <= 280 and remaining_b >= M2_MIN_W:
                            fix_type = f'BODY→EP_TRIM_B (-{trim_bot}nm from bottom)'
                            ep_trimmable += 1
                        else:
                            fix_type = f'BODY_NO_TRIM (need {min(trim_top,trim_bot)}nm > 280 max)'
                            body_alongside += 1
                    else:
                        fix_type = 'BODY_ALONGSIDE (no Y overlap???)'
                        body_alongside += 1
                else:
                    fix_type = 'BODY_ALONGSIDE'
                    body_alongside += 1
    elif t1 in ('VBAR', 'HBAR') or t2 in ('VBAR', 'HBAR'):
        fix_type = f'POWER_SHIFT (+{needed}nm)'
        power_shift += 1
    elif t1 == 'AP_PAD' and t2 == 'AP_PAD':
        fix_type = 'UNFIXABLE (pad vs pad)'
        unfixable += 1
    else:
        fix_type = f'UNKNOWN ({t1} vs {t2})'

    print(f"\nV{vi+1}: gap={gap}nm, need +{needed}nm  [{t1} vs {t2}]")
    if s1:
        print(f"  S1: [{s1[0]/1e3:.3f},{s1[1]/1e3:.3f}]-[{s1[2]/1e3:.3f},{s1[3]/1e3:.3f}]")
    if s2:
        print(f"  S2: [{s2[0]/1e3:.3f},{s2[1]/1e3:.3f}]-[{s2[2]/1e3:.3f},{s2[3]/1e3:.3f}]")
    print(f"  >> {fix_type}")

print(f"\n{'='*70}")
print(f"SUMMARY:")
print(f"  Endpoint trimmable:  {ep_trimmable}")
print(f"  Body alongside:      {body_alongside}")
print(f"  Power drop shift:    {power_shift}")
print(f"  Unfixable:           {unfixable}")
print(f"  Total:               {ep_trimmable + body_alongside + power_shift + unfixable}")
