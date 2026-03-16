#!/usr/bin/env python3
"""Diagnose M3.b=4 violations: exact GDS shapes, source attribution, fix strategy.

For each M3.b violation from the R26c DRC lyrdb:
1. Parse edge-pair markers → find exact violation locations
2. Find ALL M3 shapes at each location in GDS
3. Cross-reference with routing.json to identify drawing source
4. Check m3_obs coverage (why _m3_rect_conflict missed it)
5. Determine if same-net or cross-net → fix strategy

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m3b.py
"""
import os, json, re, math
import xml.etree.ElementTree as ET
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# DRC constants
M3_MIN_S = 210
M3_MIN_W = 200
M3_WIDE_S = 210
VIA2_SZ = 190
VIA2_PAD_M3 = 380
VIA3_PAD = 380
M3_LYR = 2
M4_LYR = 3
UM = 1000  # nm per µm

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m3 = layout.layer(30, 0)
li_v2 = layout.layer(29, 0)
li_v3 = layout.layer(33, 0)

with open('output/routing.json') as f:
    routing = json.load(f)

# === 1. Parse M3.b edge-pairs from lyrdb ===
LYRDB = '/tmp/drc_r26c/ptat_vco_ptat_vco_full.lyrdb'
tree = ET.parse(LYRDB)
root = tree.getroot()

m3b_pairs = []  # list of ((e1x1,e1y1,e1x2,e1y2), (e2x1,...))
for item in root.iter('item'):
    cat = item.find('category')
    if cat is None or not cat.text:
        continue
    if "'M3.b'" not in cat.text and "M3.b" not in cat.text.split("'")[0]:
        # Check exact match
        if cat.text.strip() != "'M3.b'":
            continue
    vals = item.find('values')
    if vals is None:
        continue
    for v in vals:
        txt = v.text.strip() if v.text else ''
        m = re.match(r'edge-pair:\s*\(([^)]+)\)\|\(([^)]+)\)', txt)
        if not m:
            continue
        def parse_edge(s):
            p1, p2 = s.split(';')
            x1, y1 = [float(c) * UM for c in p1.split(',')]
            x2, y2 = [float(c) * UM for c in p2.split(',')]
            return (x1, y1, x2, y2)
        e1 = parse_edge(m.group(1))
        e2 = parse_edge(m.group(2))
        m3b_pairs.append((e1, e2, txt))

print(f"Found {len(m3b_pairs)} M3.b edge-pairs in lyrdb")

# === 2. Build m3_obs exactly as assemble_gds.py does ===
m3_obs = []  # (x1, y1, x2, y2, net)

# Signal route M3 segments
for net_name, route in routing.get('signal_routes', {}).items():
    for seg in route.get('segments', []):
        lyr = seg[4]
        if lyr == M3_LYR:
            x1, y1, x2, y2 = seg[:4]
            hw = M3_MIN_W // 2
            if x1 == x2:
                m3_obs.append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2), net_name))
            else:
                m3_obs.append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw, net_name))
        elif lyr == -3:
            hp3 = VIA3_PAD // 2
            m3_obs.append((seg[0] - hp3, seg[1] - hp3,
                           seg[0] + hp3, seg[1] + hp3, net_name))
        elif lyr == -2:
            hp3 = VIA2_PAD_M3 // 2
            m3_obs.append((seg[0] - hp3, seg[1] - hp3,
                           seg[0] + hp3, seg[1] + hp3, net_name))

# Power M3 rails
for rail_id, rail in routing.get('power', {}).get('rails', {}).items():
    rnet = rail.get('net', rail_id)
    hw = rail['width'] // 2
    m3_obs.append((rail['x1'], rail['y'] - hw, rail['x2'], rail['y'] + hw, rnet))

# Power M3 vbars
for drop in routing.get('power', {}).get('drops', []):
    _vb = drop.get('m3_vbar')
    if _vb:
        hw = M3_MIN_W // 2
        m3_obs.append((_vb[0] - hw, min(_vb[1], _vb[3]),
                       _vb[0] + hw, max(_vb[1], _vb[3]), drop['net']))

print(f"m3_obs: {len(m3_obs)} entries")

# === 3. Build complete M3 shape→net index from routing.json ===
# This maps GDS M3 rectangles back to their routing.json source
m3_shapes_routing = []  # (x1, y1, x2, y2, net, source_desc)

# Signal M3 wires
for net_name, route in routing.get('signal_routes', {}).items():
    for seg in route.get('segments', []):
        lyr = seg[4]
        if lyr == M3_LYR:
            x1, y1, x2, y2 = seg[:4]
            hw = M3_MIN_W // 2
            if x1 == x2:
                m3_shapes_routing.append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2),
                                          net_name, f'sig_wire_{net_name}'))
            else:
                m3_shapes_routing.append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw,
                                          net_name, f'sig_wire_{net_name}'))
        elif lyr == -2:
            hp = VIA2_PAD_M3 // 2
            m3_shapes_routing.append((seg[0] - hp, seg[1] - hp,
                                      seg[0] + hp, seg[1] + hp,
                                      net_name, f'sig_via2pad_{net_name}'))
        elif lyr == -3:
            hp = VIA3_PAD // 2
            m3_shapes_routing.append((seg[0] - hp, seg[1] - hp,
                                      seg[0] + hp, seg[1] + hp,
                                      net_name, f'sig_via3pad_{net_name}'))

# Power rails
for rid, rail in routing.get('power', {}).get('rails', {}).items():
    net = rail.get('net', rid)
    hw = rail['width'] // 2
    m3_shapes_routing.append((rail['x1'], rail['y'] - hw,
                               rail['x2'], rail['y'] + hw,
                               net, f'pwr_rail_{rid}'))

# Power vbars (FULL extent — actual GDS may be fragmented)
for drop in routing.get('power', {}).get('drops', []):
    vb = drop.get('m3_vbar')
    if vb:
        hw = M3_MIN_W // 2
        x = vb[0]
        vy1 = min(vb[1], vb[3])
        vy2 = max(vb[1], vb[3])
        m3_shapes_routing.append((x - hw, vy1, x + hw, vy2,
                                   drop['net'],
                                   f"pwr_vbar_{drop['inst']}.{drop['pin']}"))

# _add_missing_ap_via2 bbox stubs (simulate the function)
aps = routing.get('access_points', {})
via_stack_pins = set()
for drop in routing.get('power', {}).get('drops', []):
    if drop['type'] == 'via_stack':
        via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

ap_bbox_stubs = []  # (x1, y1, x2, y2, net, desc, ap_key, rx, ry)
for net_name, route in routing.get('signal_routes', {}).items():
    segs = route.get('segments', [])
    pins = route.get('pins', [])
    for pin_key in pins:
        if pin_key in via_stack_pins:
            continue
        ap = aps.get(pin_key)
        if not ap or not ap.get('via_pad') or 'm2' not in ap['via_pad']:
            continue
        ap_x, ap_y = ap['x'], ap['y']
        has_low = False
        for seg in segs:
            slyr = seg[4]
            if slyr in (0, 1, -1):
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if abs(px - ap_x) <= 500 and abs(py - ap_y) <= 500:
                        has_low = True
                        break
            if has_low:
                break
        if has_low:
            continue
        best_dist = float('inf')
        best_pos = None
        for seg in segs:
            slyr = seg[4]
            if slyr not in (M3_LYR, M4_LYR, -3):
                continue
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                dist = abs(px - ap_x) + abs(py - ap_y)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = (px, py)
        if not best_pos or best_dist > 500:
            continue
        rx, ry = best_pos
        _m3_hw = M3_MIN_W // 2
        _endcap = 50
        _via_hw = VIA2_SZ // 2
        if abs(ap_x - rx) > 10 or abs(ap_y - ry) > 10:
            _mbx1 = min(ap_x, rx) - _m3_hw
            _mby1 = min(ap_y, ry) - _m3_hw
            _mbx2 = max(ap_x, rx) + _m3_hw
            _mby2 = max(ap_y, ry) + _m3_hw
        else:
            _mbx1 = ap_x - _m3_hw
            _mby1 = ap_y - _m3_hw
            _mbx2 = ap_x + _m3_hw
            _mby2 = ap_y + _m3_hw
        _mbx1 = min(_mbx1, ap_x - _via_hw - _endcap)
        _mby1 = min(_mby1, ap_y - _via_hw - _endcap)
        _mbx2 = max(_mbx2, ap_x + _via_hw + _endcap)
        _mby2 = max(_mby2, ap_y + _via_hw + _endcap)
        mbx1 = (_mbx1 // 5) * 5
        mby1 = (_mby1 // 5) * 5
        mbx2 = ((_mbx2 + 4) // 5) * 5
        mby2 = ((_mby2 + 4) // 5) * 5
        m3_shapes_routing.append((mbx1, mby1, mbx2, mby2,
                                   net_name,
                                   f'ap_via2_bbox_{pin_key}'))
        ap_bbox_stubs.append((mbx1, mby1, mbx2, mby2, net_name,
                               f'ap_via2_bbox_{pin_key}', pin_key, rx, ry))


def find_routing_source(bb):
    """Find routing.json source for a GDS M3 shape."""
    x1, y1, x2, y2 = bb.left, bb.bottom, bb.right, bb.top
    best = None
    best_dist = float('inf')
    for rx1, ry1, rx2, ry2, rnet, rdesc in m3_shapes_routing:
        # Exact match
        if abs(x1 - rx1) < 15 and abs(y1 - ry1) < 15 and abs(x2 - rx2) < 15 and abs(y2 - ry2) < 15:
            return rnet, rdesc
        # Contained (GDS fragment of a larger routing shape)
        if rx1 <= x1 + 10 and ry1 <= y1 + 10 and rx2 >= x2 - 10 and ry2 >= y2 - 10:
            cx = (rx1 + rx2) / 2
            cy = (ry1 + ry2) / 2
            d = abs((x1+x2)/2 - cx) + abs((y1+y2)/2 - cy)
            if d < best_dist:
                best_dist = d
                best = (rnet, f'{rdesc} [fragment]')
    if best:
        return best
    # Check if it's a gap fill (exact 200nm dimension)
    w, h = x2 - x1, y2 - y1
    if w == M3_MIN_W or h == M3_MIN_W:
        return '?', f'gap_fill ({w}x{h})'
    return '?', f'UNKNOWN ({w}x{h})'


# === 4. Analyze each violation ===
for idx, (e1, e2, raw_text) in enumerate(m3b_pairs):
    # Violation center
    cx = (e1[0] + e1[2] + e2[0] + e2[2]) / 4
    cy = (e1[1] + e1[3] + e2[1] + e2[3]) / 4
    print(f"\n{'='*80}")
    print(f"M3.b #{idx+1}: center≈({cx:.0f},{cy:.0f}) = ({cx/UM:.3f},{cy/UM:.3f}) µm")
    print(f"  Edge1: ({e1[0]:.0f},{e1[1]:.0f};{e1[2]:.0f},{e1[3]:.0f})")
    print(f"  Edge2: ({e2[0]:.0f},{e2[1]:.0f};{e2[2]:.0f},{e2[3]:.0f})")
    print(f"  Raw: {raw_text}")
    print(f"{'='*80}")

    # Find ALL M3 shapes in GDS near this location
    probe = kdb.Box(int(cx) - 1500, int(cy) - 1500, int(cx) + 1500, int(cy) + 1500)
    gds_m3 = []
    for si in top.shapes(li_m3).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            gds_m3.append(('TOP', bb))
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(li_m3).each():
            bb = si.bbox().transformed(inst.trans)
            if probe.overlaps(bb):
                gds_m3.append((cell.name, bb))

    print(f"\n  GDS M3 shapes within 1.5µm ({len(gds_m3)}):")
    shape_info = []
    for src, bb in gds_m3:
        rnet, rdesc = find_routing_source(bb)
        shape_info.append((src, bb, rnet, rdesc))
        print(f"    [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()} net={rnet}")
        print(f"      → {rdesc}")

    # Find the TWO shapes causing the violation (closest to each edge)
    def edge_match(edge, bb, margin=50):
        """Check if edge is on the boundary of bb."""
        ex1, ey1, ex2, ey2 = edge
        # Vertical edge
        if abs(ex1 - ex2) < 1:
            x = ex1
            if abs(x - bb.left) < margin or abs(x - bb.right) < margin:
                if min(ey1, ey2) >= bb.bottom - margin and max(ey1, ey2) <= bb.top + margin:
                    return True
        # Horizontal edge
        if abs(ey1 - ey2) < 1:
            y = ey1
            if abs(y - bb.bottom) < margin or abs(y - bb.top) < margin:
                if min(ex1, ex2) >= bb.left - margin and max(ex1, ex2) <= bb.right + margin:
                    return True
        return False

    shape_a = None
    shape_b = None
    for i, (src, bb, rnet, rdesc) in enumerate(shape_info):
        if edge_match(e1, bb):
            shape_a = i
        if edge_match(e2, bb):
            shape_b = i
    # Fallback: closest to edge midpoints
    if shape_a is None:
        mx1 = (e1[0] + e1[2]) / 2
        my1 = (e1[1] + e1[3]) / 2
        best = min(range(len(shape_info)),
                   key=lambda i: abs((shape_info[i][1].left + shape_info[i][1].right)/2 - mx1) +
                                 abs((shape_info[i][1].bottom + shape_info[i][1].top)/2 - my1))
        shape_a = best
    if shape_b is None:
        mx2 = (e2[0] + e2[2]) / 2
        my2 = (e2[1] + e2[3]) / 2
        candidates = [i for i in range(len(shape_info)) if i != shape_a]
        if candidates:
            best = min(candidates,
                       key=lambda i: abs((shape_info[i][1].left + shape_info[i][1].right)/2 - mx2) +
                                     abs((shape_info[i][1].bottom + shape_info[i][1].top)/2 - my2))
            shape_b = best

    if shape_a is not None and shape_b is not None:
        _, bb_a, net_a, desc_a = shape_info[shape_a]
        _, bb_b, net_b, desc_b = shape_info[shape_b]
        x_gap = max(bb_a.left - bb_b.right, bb_b.left - bb_a.right)
        y_gap = max(bb_a.bottom - bb_b.top, bb_b.bottom - bb_a.top)
        if x_gap <= 0 and y_gap <= 0:
            gap = 0  # overlapping
        elif x_gap > 0 and y_gap > 0:
            gap = math.sqrt(x_gap**2 + y_gap**2)
        else:
            gap = max(x_gap, y_gap)

        print(f"\n  *** VIOLATION PAIR ***")
        print(f"  A: ({bb_a.left},{bb_a.bottom};{bb_a.right},{bb_a.top}) "
              f"{bb_a.width()}x{bb_a.height()} net={net_a}")
        print(f"     {desc_a}")
        print(f"  B: ({bb_b.left},{bb_b.bottom};{bb_b.right},{bb_b.top}) "
              f"{bb_b.width()}x{bb_b.height()} net={net_b}")
        print(f"     {desc_b}")
        print(f"  Gap: {gap:.0f}nm (x_gap={x_gap}, y_gap={y_gap})")
        print(f"  Same-net: {net_a == net_b}")

        # Check m3_obs coverage
        for label, bb, net, desc in [('A', bb_a, net_a, desc_a), ('B', bb_b, net_b, desc_b)]:
            in_obs = False
            for ox1, oy1, ox2, oy2, onet in m3_obs:
                if (abs(bb.left - ox1) < 20 and abs(bb.bottom - oy1) < 20 and
                    abs(bb.right - ox2) < 20 and abs(bb.top - oy2) < 20):
                    print(f"  {label} exact-match m3_obs: net={onet}")
                    in_obs = True
                    break
                if (ox1 <= bb.left + 10 and oy1 <= bb.bottom + 10 and
                    ox2 >= bb.right - 10 and oy2 >= bb.top - 10):
                    print(f"  {label} contained-in m3_obs: ({ox1},{oy1};{ox2},{oy2}) net={onet}")
                    in_obs = True
                    break
            if not in_obs:
                print(f"  {label} NOT in m3_obs → invisible to _m3_rect_conflict!")

        # Fix strategy
        if net_a == net_b:
            print(f"\n  FIX: Same-net → _fill_same_net_gaps should bridge this")
            print(f"  Check: are both shapes in _fill_same_net_gaps M3 collection?")
            # Check if shapes are in the gap fill collection
            for label, bb, desc in [('A', bb_a, desc_a), ('B', bb_b, desc_b)]:
                if 'ap_via2_bbox' in desc or 'UNKNOWN' in desc:
                    print(f"    {label}: {desc} → NOT collected by _fill_same_net_gaps")
                    print(f"    → Need to add this shape source to gap fill M3 collection")
                else:
                    print(f"    {label}: {desc} → should be in collection")
        else:
            print(f"\n  FIX: Cross-net → need to shrink/trim one shape")
            # Determine which shape to trim
            for label, bb, desc in [('A', bb_a, desc_a), ('B', bb_b, desc_b)]:
                if 'ap_via2_bbox' in desc:
                    print(f"    {label}: bbox stub from _add_missing_ap_via2 → can trim")
                    # Find the AP bbox stub info
                    for sbx1, sby1, sbx2, sby2, snet, sdesc, sap, srx, sry in ap_bbox_stubs:
                        if abs(sbx1 - bb.left) < 15 and abs(sby1 - bb.bottom) < 15:
                            print(f"      AP={sap} route_vtx=({srx},{sry})")
                            # How much to trim
                            other_bb = bb_b if label == 'A' else bb_a
                            if x_gap < 0 and y_gap > 0:
                                print(f"      Y gap={y_gap}: trim {'top' if other_bb.bottom > bb.top else 'bottom'}")
                            elif y_gap < 0 and x_gap > 0:
                                print(f"      X gap={x_gap}: trim {'right' if other_bb.left > bb.right else 'left'}")
                elif 'pwr_vbar' in desc:
                    print(f"    {label}: power vbar → should NOT trim (power integrity)")
                elif 'sig_wire' in desc:
                    print(f"    {label}: signal wire → can potentially reroute")
                elif 'gap_fill' in desc:
                    print(f"    {label}: gap fill → can trim/skip")

    # Check for Via2/Via3 at violation location
    probe_small = kdb.Box(int(cx) - 500, int(cy) - 500, int(cx) + 500, int(cy) + 500)
    v2_found = []
    for si in top.shapes(li_v2).each():
        bb = si.bbox()
        if probe_small.overlaps(bb):
            v2_found.append(bb)
    if v2_found:
        print(f"\n  Via2 shapes nearby: {len(v2_found)}")
        for bb in v2_found:
            print(f"    ({bb.left},{bb.bottom};{bb.right},{bb.top})")

print("\n\nDone.")
