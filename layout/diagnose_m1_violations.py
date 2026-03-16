#!/usr/bin/env python3
"""Diagnose ALL M1 DRC violations (M1.a, M1.b, M1.d) at once.

For each violation:
1. Parse exact coordinates from DRC lyrdb
2. Find all M1 shapes at that location (top cell + subcells)
3. Identify source: AP pad, signal wire, gap fill, tie bar, gate contact
4. Match to net via routing.json
5. Classify root cause and propose fix strategy

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_violations.py
"""
import os, json, math
from collections import defaultdict
import xml.etree.ElementTree as ET
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# ── DRC constants ──
M1_MIN_W    = 160     # M1.a
M1_MIN_S    = 180     # M1.b
M1_MIN_AREA = 90000   # M1.d (nm²)
VIA1_GDS_M1 = 310     # Shrunk M1 pad
VIA1_PAD_M1 = 370     # Router M1 pad
M1_SIG_W    = 300     # Signal wire width
VIA1_SZ     = 190     # Via1 size

# ── Load GDS ──
layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_v1 = layout.layer(19, 0)
li_m2 = layout.layer(10, 0)

# ── Load routing ──
with open('output/routing.json') as f:
    routing = json.load(f)

# ── Parse DRC lyrdb ──
LYRDB = '/tmp/drc_r23d/ptat_vco_ptat_vco_full.lyrdb'
tree = ET.parse(LYRDB)
root = tree.getroot()

violations = []  # (rule, type, coords_nm)
for item in root.iter('item'):
    cat = item.find('category')
    if cat is None or 'M1.' not in cat.text:
        continue
    rule = cat.text.strip().strip("'")
    vals = item.find('values')
    if vals is None:
        continue
    for v in vals.findall('value'):
        txt = v.text.strip()
        if txt.startswith('edge-pair:'):
            # Parse: edge-pair: (x1,y1;x2,y2)|(x3,y3;x4,y4)
            parts = txt.replace('edge-pair:', '').strip()
            edges = parts.split('|')
            coords = []
            for e in edges:
                e = e.strip().strip('(').strip(')')
                for pt in e.split(';'):
                    x, y = pt.split(',')
                    coords.extend([float(x) * 1000, float(y) * 1000])  # µm→nm
            # Center of all points
            xs = [coords[i] for i in range(0, len(coords), 2)]
            ys = [coords[i] for i in range(1, len(coords), 2)]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            violations.append((rule, 'edge-pair', cx, cy, txt))
        elif txt.startswith('polygon:'):
            # Parse: polygon: (x1,y1;x2,y2;x3,y3;x4,y4)
            coords_str = txt.replace('polygon:', '').strip().strip('(').strip(')')
            pts = coords_str.split(';')
            xs = [float(p.split(',')[0]) * 1000 for p in pts]
            ys = [float(p.split(',')[1]) * 1000 for p in pts]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            violations.append((rule, 'polygon', cx, cy, txt))

print(f'Parsed {len(violations)} M1 violations from DRC lyrdb\n')

# ── Build net index ──
pin_to_net = {}
for rd_name in ('signal_routes', 'pre_routes'):
    for net, rd in routing.get(rd_name, {}).items():
        for pk in rd.get('pins', []):
            pin_to_net[pk] = net

# Build AP index: (cx,cy) → (key, net, ap_data)
ap_index = {}
for key, ap in routing.get('access_points', {}).items():
    net = pin_to_net.get(key, '?')
    ap_index[(ap['x'], ap['y'])] = (key, net, ap)

# Build M1 wire index from signal routes
m1_wires = []  # (x1,y1,x2,y2,net,box)
hw = M1_SIG_W // 2
for rd_name in ('signal_routes', 'pre_routes'):
    for net, rd in routing.get(rd_name, {}).items():
        for seg in rd.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == 0:  # M1
                if x1 == x2:  # vertical
                    box = (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
                else:  # horizontal
                    box = (min(x1, x2) - hw, y1 - hw, max(x1, x2) + hw, y1 + hw)
                m1_wires.append((x1, y1, x2, y2, net, box))

# Build via1 index from signal routes
via1_positions = []  # (cx, cy, net)
for rd_name in ('signal_routes', 'pre_routes'):
    for net, rd in routing.get(rd_name, {}).items():
        for seg in rd.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            if lyr == -1:  # via1
                via1_positions.append((x1, y1, net))


def find_shapes(layer_idx, cx, cy, radius=500):
    """Find all shapes on layer near (cx, cy)."""
    probe = kdb.Box(int(cx - radius), int(cy - radius),
                    int(cx + radius), int(cy + radius))
    results = []
    for si in top.shapes(layer_idx).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            results.append(('TOP', bb))
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(layer_idx).each():
            bb = si.bbox().transformed(inst.trans)
            if probe.overlaps(bb):
                results.append((cell.name, bb))
    return results


def identify_m1_shape(bb, cx, cy):
    """Identify what kind of M1 shape this is."""
    w = bb.width()
    h = bb.height()

    # Check if it's an AP pad (square ~310nm or ~370nm)
    if abs(w - VIA1_GDS_M1) < 10 and abs(h - VIA1_GDS_M1) < 10:
        return 'AP_PAD_310'
    if abs(w - VIA1_PAD_M1) < 10 and abs(h - VIA1_PAD_M1) < 10:
        return 'AP_PAD_370'

    # Check if it's a signal wire (300nm wide)
    if abs(w - M1_SIG_W) < 10 or abs(h - M1_SIG_W) < 10:
        if w > h:
            return f'H_WIRE_{w}x{h}'
        else:
            return f'V_WIRE_{w}x{h}'

    # Check if it's a thin stub (160nm)
    if w == 160 or h == 160:
        return f'THIN_STUB_{w}x{h}'

    # Generic
    return f'SHAPE_{w}x{h}'


def find_net_for_m1(bb):
    """Try to find which net an M1 shape belongs to."""
    scx = (bb.left + bb.right) // 2
    scy = (bb.bottom + bb.top) // 2

    # Check AP pads
    for (ax, ay), (key, net, ap) in ap_index.items():
        vp = ap.get('via_pad', {})
        if 'm1' in vp:
            m1r = vp['m1']
            m1cx = (m1r[0] + m1r[2]) // 2
            m1cy = (m1r[1] + m1r[3]) // 2
            if abs(m1cx - scx) < 200 and abs(m1cy - scy) < 200:
                return net, key

    # Check wire segments
    for wx1, wy1, wx2, wy2, wnet, wbox in m1_wires:
        if (abs(wbox[0] - bb.left) < 10 and abs(wbox[1] - bb.bottom) < 10 and
            abs(wbox[2] - bb.right) < 10 and abs(wbox[3] - bb.top) < 10):
            return wnet, 'wire'
        # Check if shape center is within wire
        if wbox[0] <= scx <= wbox[2] and wbox[1] <= scy <= wbox[3]:
            return wnet, 'wire_overlap'

    # Check via1 positions
    hp = VIA1_GDS_M1 // 2
    for vx, vy, vnet in via1_positions:
        if abs(vx - scx) < hp + 10 and abs(vy - scy) < hp + 10:
            return vnet, 'via1_pad'

    return '?', '?'


# ── Cluster violations by location ──
clusters = []
used = set()
for i, (rule, vtype, cx, cy, raw) in enumerate(violations):
    if i in used:
        continue
    cluster = [(rule, vtype, cx, cy, raw)]
    used.add(i)
    for j, (r2, t2, cx2, cy2, raw2) in enumerate(violations):
        if j in used:
            continue
        if abs(cx - cx2) < 2000 and abs(cy - cy2) < 2000:
            cluster.append((r2, t2, cx2, cy2, raw2))
            used.add(j)
    clusters.append(cluster)

print(f'Clustered into {len(clusters)} location groups\n')

# ── Analyze each cluster ──
for ci, cluster in enumerate(clusters):
    rules = defaultdict(int)
    for rule, *_ in cluster:
        rules[rule] += 1
    rule_str = ' + '.join(f'{r}×{n}' for r, n in sorted(rules.items()))

    # Cluster center
    cx = sum(c[2] for c in cluster) / len(cluster)
    cy = sum(c[3] for c in cluster) / len(cluster)

    print(f"{'='*80}")
    print(f'CLUSTER {ci+1}: {rule_str} at ~({cx:.0f}, {cy:.0f}) nm')
    print(f"{'='*80}")

    for rule, vtype, vx, vy, raw in cluster:
        print(f'\n  {rule} ({vtype}): {raw}')

    # Find all M1 shapes nearby
    m1_shapes = find_shapes(li_m1, cx, cy, 1500)
    v1_shapes = find_shapes(li_v1, cx, cy, 1500)

    print(f'\n  M1 shapes within 1.5µm ({len(m1_shapes)}):')
    shape_info = []
    for src, bb in m1_shapes:
        kind = identify_m1_shape(bb, cx, cy)
        net, origin = find_net_for_m1(bb)
        area = bb.width() * bb.height()
        dist = math.sqrt((bb.center().x - cx)**2 + (bb.center().y - cy)**2)
        shape_info.append((src, bb, kind, net, origin, area, dist))
        area_ok = '✓' if area >= M1_MIN_AREA else f'AREA={area}<{M1_MIN_AREA}'
        print(f'    [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) '
              f'{bb.width()}x{bb.height()} {kind} net={net} [{origin}] {area_ok}')

    print(f'\n  Via1 shapes within 1.5µm ({len(v1_shapes)}):')
    for src, bb in v1_shapes:
        print(f'    [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) '
              f'{bb.width()}x{bb.height()}')

    # Find nearby APs
    print(f'\n  Access points within 2µm:')
    for (ax, ay), (key, net, ap) in ap_index.items():
        if abs(ax - cx) < 2000 and abs(ay - cy) < 2000:
            mode = ap.get('mode', '?')
            vp = ap.get('via_pad', {})
            m1r = vp.get('m1', [])
            m1_str = f' m1={m1r}' if m1r else ''
            print(f'    {key}: ({ax},{ay}) mode={mode} net={net}{m1_str}')

    # Spacing analysis: find all M1 shape pairs with gaps
    print(f'\n  === Spacing analysis ===')
    all_boxes = [(src, bb, find_net_for_m1(bb)[0]) for src, bb in m1_shapes]
    for i, (s1, b1, n1) in enumerate(all_boxes):
        for j, (s2, b2, n2) in enumerate(all_boxes):
            if j <= i:
                continue
            x_gap = max(b1.left - b2.right, b2.left - b1.right)
            y_gap = max(b1.bottom - b2.top, b2.bottom - b1.top)

            # Only report close pairs
            if x_gap > M1_MIN_S * 2 or y_gap > M1_MIN_S * 2:
                continue

            same_net = n1 == n2 and n1 != '?'
            if x_gap >= 0 and y_gap < 0:
                # X-separated, Y-overlapping
                if 0 < x_gap < M1_MIN_S:
                    status = 'NOTCH' if same_net else 'SPACING_VIOL'
                    print(f'    {status}: x_gap={x_gap}nm (<{M1_MIN_S}) '
                          f'net1={n1} net2={n2}')
                    print(f'      shape1: ({b1.left},{b1.bottom};{b1.right},{b1.top}) '
                          f'{b1.width()}x{b1.height()} [{s1}]')
                    print(f'      shape2: ({b2.left},{b2.bottom};{b2.right},{b2.top}) '
                          f'{b2.width()}x{b2.height()} [{s2}]')
            elif y_gap >= 0 and x_gap < 0:
                # Y-separated, X-overlapping
                if 0 < y_gap < M1_MIN_S:
                    status = 'NOTCH' if same_net else 'SPACING_VIOL'
                    print(f'    {status}: y_gap={y_gap}nm (<{M1_MIN_S}) '
                          f'net1={n1} net2={n2}')
                    print(f'      shape1: ({b1.left},{b1.bottom};{b1.right},{b1.top}) '
                          f'{b1.width()}x{b1.height()} [{s1}]')
                    print(f'      shape2: ({b2.left},{b2.bottom};{b2.right},{b2.top}) '
                          f'{b2.width()}x{b2.height()} [{s2}]')

    # Wire protrusion analysis for M1.a
    if 'M1.a' in rules:
        print(f'\n  === M1.a width analysis ===')
        # Check for concave notch: one M1 shape overlapping another
        # creating a feature < M1_MIN_W
        for s1, b1, n1 in all_boxes:
            for s2, b2, n2 in all_boxes:
                if b1 == b2:
                    continue
                if n1 != n2 and n1 != '?' and n2 != '?':
                    continue
                # Check overlap
                ox = min(b1.right, b2.right) - max(b1.left, b2.left)
                oy = min(b1.top, b2.top) - max(b1.bottom, b2.bottom)
                if ox > 0 and oy > 0:
                    # Overlapping shapes — check if overlap creates notch
                    # Wire wider than pad → protrusion
                    if b1.right > b2.right:
                        prot_w = b1.right - b2.right
                        if 0 < prot_w < M1_MIN_W:
                            print(f'    RIGHT protrusion {prot_w}nm < {M1_MIN_W}: '
                                  f'({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}] '
                                  f'past ({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}]')
                    if b2.right > b1.right:
                        prot_w = b2.right - b1.right
                        if 0 < prot_w < M1_MIN_W:
                            print(f'    RIGHT protrusion {prot_w}nm < {M1_MIN_W}: '
                                  f'({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}] '
                                  f'past ({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}]')
                    if b1.top > b2.top:
                        prot_h = b1.top - b2.top
                        if 0 < prot_h < M1_MIN_W:
                            print(f'    TOP protrusion {prot_h}nm < {M1_MIN_W}: '
                                  f'({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}] '
                                  f'past ({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}]')
                    if b2.top > b1.top:
                        prot_h = b2.top - b1.top
                        if 0 < prot_h < M1_MIN_W:
                            print(f'    TOP protrusion {prot_h}nm < {M1_MIN_W}: '
                                  f'({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}] '
                                  f'past ({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}]')
                    if b1.left < b2.left:
                        prot_w = b2.left - b1.left
                        if 0 < prot_w < M1_MIN_W:
                            print(f'    LEFT protrusion {prot_w}nm < {M1_MIN_W}: '
                                  f'({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}] '
                                  f'past ({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}]')
                    if b2.left < b1.left:
                        prot_w = b1.left - b2.left
                        if 0 < prot_w < M1_MIN_W:
                            print(f'    LEFT protrusion {prot_w}nm < {M1_MIN_W}: '
                                  f'({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}] '
                                  f'past ({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}]')
                    if b1.bottom < b2.bottom:
                        prot_h = b2.bottom - b1.bottom
                        if 0 < prot_h < M1_MIN_W:
                            print(f'    BOTTOM protrusion {prot_h}nm < {M1_MIN_W}: '
                                  f'({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}] '
                                  f'past ({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}]')
                    if b2.bottom < b1.bottom:
                        prot_h = b1.bottom - b2.bottom
                        if 0 < prot_h < M1_MIN_W:
                            print(f'    BOTTOM protrusion {prot_h}nm < {M1_MIN_W}: '
                                  f'({b2.left},{b2.bottom};{b2.right},{b2.top}) [{s2}] '
                                  f'past ({b1.left},{b1.bottom};{b1.right},{b1.top}) [{s1}]')

    # Area analysis for M1.d
    if 'M1.d' in rules:
        print(f'\n  === M1.d area analysis ===')
        for src, bb, net, origin, area in [(s, b, n, o, a)
                for s, b, _, n, o, a, _ in shape_info]:
            if area < M1_MIN_AREA:
                w, h = bb.width(), bb.height()
                need_w = math.ceil(M1_MIN_AREA / h) if h >= M1_MIN_W else M1_MIN_W
                need_h = math.ceil(M1_MIN_AREA / w) if w >= M1_MIN_W else M1_MIN_W
                print(f'    UNDERSIZED: ({bb.left},{bb.bottom};{bb.right},{bb.top}) '
                      f'{w}x{h}={area}nm² net={net} [{src}]')
                print(f'      Fix: extend to {need_w}x{h} or {w}x{need_h} '
                      f'(need {M1_MIN_AREA}nm²)')
                # Check what's around it — can we extend safely?
                for s2, b2, n2 in all_boxes:
                    if b2 == bb:
                        continue
                    x_gap = max(bb.left - b2.right, b2.left - bb.right)
                    y_gap = max(bb.bottom - b2.top, b2.bottom - bb.top)
                    # Report nearby shapes that constrain extension
                    if -100 < x_gap < 500 or -100 < y_gap < 500:
                        same = 'SAME' if n2 == net else 'CROSS'
                        print(f'      nearby [{s2}] ({b2.left},{b2.bottom};'
                              f'{b2.right},{b2.top}) {b2.width()}x{b2.height()} '
                              f'net={n2} {same} x_gap={x_gap} y_gap={y_gap}')

    # Fix strategy summary
    print(f'\n  === Fix strategy ===')
    if 'M1.a' in rules:
        print(f'  M1.a: Concave notch at wire-pad junction. Options:')
        print(f'    1. Clip wire endpoint to align with pad edge (shrink wire overshoot)')
        print(f'    2. Extend pad to cover wire overshoot (may cause M1.b to neighbor)')
        print(f'    3. Fill notch with rectangle ≥ {M1_MIN_W}nm in each dimension')
    if 'M1.b' in rules:
        print(f'  M1.b: Spacing < {M1_MIN_S}nm. Options:')
        print(f'    1. If same-net notch: fill gap')
        print(f'    2. If cross-net spacing: shrink one shape or jog wire')
        print(f'    3. Move AP pad center (requires route adjustment)')
    if 'M1.d' in rules:
        print(f'  M1.d: Area < {M1_MIN_AREA}nm². Options:')
        print(f'    1. Extend bridge in safe direction')
        print(f'    2. Widen bridge (if narrow stub)')
        print(f'    3. Merge with adjacent same-net shape')

print('\n\nDone.')
