#!/usr/bin/env python3
"""Diagnose remaining M2.b violations: classify each by type, net, gap, pad status.

Run on the CURRENT GDS (after fix_m2b_postprocess.py):
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m2b_remaining.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
ROUTING = 'output/routing.json'

# Constants
M2_MIN_S = 210
VIA1_PAD = 480
VIA1_SZ = 190
M2_SIG_W = 300
GRID = 5

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)

# --- Load routing data for net attribution ---
with open(ROUTING) as f:
    routing = json.load(f)

# Build M2 shape → net map from routing.json
hw = M2_SIG_W // 2  # 150nm
M2_LYR = 1
m2_net_shapes = []  # (xl, yb, xr, yt, net, kind)

for net_type in ['signal_routes', 'pre_routes']:
    for net, route in routing.get(net_type, {}).items():
        for seg in route.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, code = seg[:5]
            if code == M2_LYR:
                if y1 == y2 and x1 != x2:
                    xl, xr = min(x1, x2), max(x1, x2)
                    m2_net_shapes.append((xl, y1 - hw, xr, y1 + hw, net, 'H-wire'))
                elif x1 == x2 and y1 != y2:
                    yb, yt = min(y1, y2), max(y1, y2)
                    m2_net_shapes.append((x1 - hw, yb, x1 + hw, yt, net, 'V-wire'))
            elif code < 0:
                via_layer = -code
                if via_layer == 1:
                    hp = VIA1_PAD // 2
                    m2_net_shapes.append((x1 - hp, y1 - hp, x1 + hp, y1 + hp, net, 'Via1-pad'))

# AP pads
for key, ap in routing.get('access_points', {}).items():
    vp = ap.get('via_pad', {})
    m2 = vp.get('m2')
    if m2:
        # Find which net uses this AP
        ap_net = None
        for net_type in ['signal_routes', 'pre_routes']:
            for net, route in routing.get(net_type, {}).items():
                if key in route.get('pins', []):
                    ap_net = net
                    break
            if ap_net:
                break
        m2_net_shapes.append((m2[0], m2[1], m2[2], m2[3], ap_net or f'AP:{key}', 'AP-pad'))

# Power M2 shapes
power = routing.get('power', {})
for drop in power.get('drops', []):
    net_name = drop.get('net', '?')
    for shape in drop.get('m2_shapes', []):
        m2_net_shapes.append((shape[0], shape[1], shape[2], shape[3],
                             f'PWR:{net_name}', 'pwr-drop'))
    m2_up = drop.get('m2_underpass')
    if m2_up:
        m2_net_shapes.append((m2_up[0], m2_up[1], m2_up[2], m2_up[3],
                             f'PWR:{net_name}', 'pwr-underpass'))

# --- Via1 positions ---
via1_positions = set()
for si in top.begin_shapes_rec(li_v1):
    box = si.shape().bbox().transformed(si.trans())
    cx = (box.left + box.right) // 2
    cy = (box.top + box.bottom) // 2
    via1_positions.add((cx, cy))

# --- Collect actual M2 shapes from GDS (unmerged, top-level) ---
gds_m2_shapes = []  # (box, is_via_pad, via_pos_or_None, current_w, current_h)
for si in top.each_shape(li_m2):
    box = si.bbox()
    w, h = box.width(), box.height()
    cx = (box.left + box.right) // 2
    cy = (box.top + box.bottom) // 2
    is_pad = False
    vpos = None
    for vx, vy in via1_positions:
        if abs(cx - vx) <= 10 and abs(cy - vy) <= 10:
            is_pad = True
            vpos = (vx, vy)
            break
    gds_m2_shapes.append((box, is_pad, vpos, w, h))


def find_net(mx, my, radius=500):
    """Find the net name for an M2 shape near (mx, my)."""
    best = None
    best_d = radius
    for xl, yb, xr, yt, net, kind in m2_net_shapes:
        if xl - radius <= mx <= xr + radius and yb - radius <= my <= yt + radius:
            d = max(0, max(xl - mx, mx - xr)) + max(0, max(yb - my, my - yt))
            if d < best_d:
                best_d = d
                best = (net, kind)
    return best


def find_gds_shape(mx, my, expand=100):
    """Find the actual GDS M2 shape containing or nearest to (mx, my).

    Uses bbox containment with expansion, not center distance.
    """
    best = None
    best_d = 99999
    for box, is_pad, vpos, w, h in gds_m2_shapes:
        # Check if point is within expanded bbox
        if (box.left - expand <= mx <= box.right + expand and
                box.bottom - expand <= my <= box.top + expand):
            # Distance from point to bbox center
            cx = (box.left + box.right) // 2
            cy = (box.top + box.bottom) // 2
            d = abs(cx - mx) + abs(cy - my)
            if d < best_d:
                best_d = d
                best = (box, is_pad, vpos, w, h)
    return best


# --- Find M2.b violations ---
m2_region = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
violations = m2_region.space_check(M2_MIN_S)

print(f"=== M2.b Remaining Violations: {violations.count()} ===\n")
print(f"{'#':>3} {'Location':>22} {'Gap':>6} {'Type':>10} {'Net':>15}  "
      f"{'Shape1':>30}  {'Shape2':>30}  {'Pad trim room':>15}")
print("=" * 145)

buckets = {'pad-pad': [], 'pad-wire': [], 'wire-wire': [], 'pad-pwr': [],
           'wire-pwr': [], 'other': []}

for vi, ep in enumerate(violations.each()):
    e1, e2 = ep.first, ep.second

    e1_mx = (e1.p1.x + e1.p2.x) // 2
    e1_my = (e1.p1.y + e1.p2.y) // 2
    e2_mx = (e2.p1.x + e2.p2.x) // 2
    e2_my = (e2.p1.y + e2.p2.y) // 2

    # Gap
    e1_is_h = abs(e1.p2.x - e1.p1.x) > abs(e1.p2.y - e1.p1.y)
    if e1_is_h:
        gap = abs(e1_my - e2_my)
    else:
        gap = abs(e1_mx - e2_mx)

    shortfall = M2_MIN_S - gap

    # Net attribution
    n1 = find_net(e1_mx, e1_my)
    n2 = find_net(e2_mx, e2_my)
    net1 = n1[0] if n1 else '?'
    kind1 = n1[1] if n1 else '?'
    net2 = n2[0] if n2 else '?'
    kind2 = n2[1] if n2 else '?'
    same_net = (net1 == net2) and net1 != '?'

    # GDS shape info (actual pad dimensions after trimming)
    g1 = find_gds_shape(e1_mx, e1_my)
    g2 = find_gds_shape(e2_mx, e2_my)

    def shape_desc(g, kind):
        if g is None:
            return f'{kind}(?)'
        box, is_pad, vpos, w, h = g
        if is_pad:
            return f'pad {w}x{h}'
        return f'{kind} {w}x{h}'

    def trim_room(g):
        """How much more can this pad be trimmed (per side)?"""
        if g is None:
            return '-'
        box, is_pad, vpos, w, h = g
        if not is_pad:
            return 'n/a(wire)'
        # Current minimum dimension
        min_dim = min(w, h)
        room = min_dim - 400  # conservative floor
        if room <= 0:
            return '0(at floor)'
        # Also check via enclosure
        if vpos:
            vx, vy = vpos
            encs = [vpos[0] - VIA1_SZ // 2 - box.left,
                    box.right - vpos[0] - VIA1_SZ // 2,
                    vpos[1] - VIA1_SZ // 2 - box.bottom,
                    box.top - vpos[1] - VIA1_SZ // 2]
            min_enc = min(encs)
            enc_room = min_enc - 50  # V1_END_ENC
            room = min(room, enc_room)
        if room <= 0:
            return '0(enc limit)'
        return f'{room}nm'

    s1_desc = shape_desc(g1, kind1)
    s2_desc = shape_desc(g2, kind2)
    t1 = trim_room(g1)
    t2 = trim_room(g2)

    # Classify
    is_pad1 = g1 and g1[1]
    is_pad2 = g2 and g2[1]
    is_pwr1 = net1.startswith('PWR:')
    is_pwr2 = net2.startswith('PWR:')

    if is_pad1 and is_pad2:
        vtype = 'pad-pad'
    elif is_pad1 or is_pad2:
        if is_pwr1 or is_pwr2:
            vtype = 'pad-pwr'
        else:
            vtype = 'pad-wire'
    elif is_pwr1 or is_pwr2:
        vtype = 'wire-pwr'
    else:
        vtype = 'wire-wire'

    net_rel = 'SAME' if same_net else 'CROSS'
    loc = f'({(e1_mx+e2_mx)/2e3:.3f},{(e1_my+e2_my)/2e3:.3f})'

    print(f'{vi+1:3d} {loc:>22} {gap:5d}nm {vtype:>10} {net_rel:>5} '
          f'{net1:>12}  {s1_desc:>25}  {s2_desc:>25}  '
          f'trim1={t1}, trim2={t2}')

    buckets[vtype].append({
        'vi': vi + 1,
        'gap': gap,
        'shortfall': shortfall,
        'same_net': same_net,
        'net1': net1, 'net2': net2,
        'kind1': kind1, 'kind2': kind2,
        'trim1': t1, 'trim2': t2,
    })

# Summary
print(f"\n{'='*60}")
print("SUMMARY BY TYPE:")
for vtype, items in sorted(buckets.items()):
    if not items:
        continue
    gaps = [it['shortfall'] for it in items]
    same = sum(1 for it in items if it['same_net'])
    cross = len(items) - same
    fixable = sum(1 for it in items
                  if it['trim1'] not in ('n/a(wire)', '-', '0(at floor)', '0(enc limit)')
                  or it['trim2'] not in ('n/a(wire)', '-', '0(at floor)', '0(enc limit)'))
    print(f"  {vtype:12s}: {len(items):2d} violations "
          f"(same={same}, cross={cross}, "
          f"shortfall={min(gaps)}~{max(gaps)}nm, "
          f"pad-trimmable={fixable})")

total_trimmable = sum(
    1 for vtype, items in buckets.items()
    for it in items
    if it['trim1'] not in ('n/a(wire)', '-', '0(at floor)', '0(enc limit)')
    or it['trim2'] not in ('n/a(wire)', '-', '0(at floor)', '0(enc limit)')
)
print(f"\nTotal M2.b: {violations.count()}")
print(f"Potentially trimmable (at least one pad with room): {total_trimmable}")
print(f"At geometric limit (no pad room): {violations.count() - total_trimmable}")
