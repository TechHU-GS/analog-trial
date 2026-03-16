#!/usr/bin/env python3
"""Check which M2.b violations have trimmable (non-via, non-junction) endpoints."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from atk.pdk import M2_MIN_S, M2_SIG_W, VIA1_PAD

ROUTING = 'output/routing.json'
with open(ROUTING) as f:
    routing = json.load(f)

hw = M2_SIG_W // 2  # 150nm
M2_LYR = 1

# Collect all M2 wire segments with their nets
m2_wires = []  # (xl, ylo, xr, yhi, net, seg_ref, is_h)
for net, route in {**routing.get('signal_routes', {}), **routing.get('pre_routes', {})}.items():
    for seg in route.get('segments', []):
        if len(seg) < 5 or seg[4] != M2_LYR:
            continue
        x1, y1, x2, y2 = seg[:4]
        if y1 == y2 and x1 != x2:  # H-wire
            xl, xr = min(x1, x2), max(x1, x2)
            m2_wires.append((xl, y1-hw, xr, y1+hw, net, (xl, y1, xr, y1), True))
        elif x1 == x2 and y1 != y2:  # V-wire
            ylo, yhi = min(y1, y2), max(y1, y2)
            m2_wires.append((x1-hw, ylo, x1+hw, yhi, net, (x1, ylo, x1, yhi), False))

# Collect via positions
via_pos = set()
for net, route in {**routing.get('signal_routes', {}), **routing.get('pre_routes', {})}.items():
    for seg in route.get('segments', []):
        if len(seg) < 5:
            continue
        if seg[4] < 0:  # Via
            via_pos.add((seg[0], seg[1]))

# Collect M2 endpoint counts for junction detection
from collections import defaultdict
m2_ep_count = defaultdict(lambda: defaultdict(int))
for net, route in {**routing.get('signal_routes', {}), **routing.get('pre_routes', {})}.items():
    for seg in route.get('segments', []):
        if len(seg) < 5 or seg[4] != M2_LYR:
            continue
        m2_ep_count[net][(seg[0], seg[1])] += 1
        m2_ep_count[net][(seg[2], seg[3])] += 1

# The 8 "trimmable" violations from previous diagnostic
# Format: (wire_shape_approx, pad_shape, trim_endpoint, trim_amount, vi_num)
violations = [
    # V4: H-wire left endpoint
    (67600, 239750, 69350, 240050, 'H', 'left', 80, 4),
    # V5: V-wire bottom endpoint
    (58350, 217150, 58650, 219250, 'V', 'bottom', 95, 5),
    # V7: H-wire right endpoint
    (81950, 179550, 83000, 179850, 'H', 'right', 215, 7),
    # V8: V-wire top endpoint
    (96150, 216100, 96450, 216800, 'V', 'top', 45, 8),
    # V9: V-wire bottom endpoint
    (97200, 217150, 97500, 219250, 'V', 'bottom', 95, 9),
    # V10: V-wire bottom endpoint
    (58350, 202100, 58650, 204200, 'V', 'bottom', 145, 10),
    # V14: V-wire bottom endpoint
    (153550, 72250, 153850, 74000, 'V', 'bottom', 200, 14),
    # V15: H-wire left endpoint
    (46950, 69300, 47650, 69600, 'H', 'left', 175, 15),
]

print("M2.b Via/Junction Check for Trimmable Violations")
print("=" * 70)

for sl, sb, sr, st, orient, trim_end, trim_amt, vnum in violations:
    # Find matching wire in routing
    cx = (sl + sr) // 2
    cy = (sb + st) // 2

    best_wire = None
    best_dist = 999999
    for wl, wb2, wr, wt, wnet, wseg, wh in m2_wires:
        d = abs((wl+wr)//2 - cx) + abs((wb2+wt)//2 - cy)
        if d < best_dist and abs(wr-wl-(sr-sl)) < 50 and abs(wt-wb2-(st-sb)) < 50:
            best_dist = d
            best_wire = (wl, wb2, wr, wt, wnet, wseg, wh)

    if best_wire is None:
        print(f"\nV{vnum}: NO matching wire found!")
        continue

    wl, wb2, wr, wt, wnet, wseg, wh = best_wire

    # Determine the trim endpoint coordinates
    if orient == 'H':
        if trim_end == 'left':
            ep = (wseg[0], wseg[1])  # (xl, y)
        else:
            ep = (wseg[2], wseg[1])  # (xr, y)
    else:  # V
        if trim_end == 'bottom':
            ep = (wseg[0], wseg[1])  # (x, ylo)
        else:
            ep = (wseg[0], wseg[3])  # (x, yhi)

    is_via = ep in via_pos
    is_junc = m2_ep_count[wnet][ep] > 1

    status = []
    if is_via:
        status.append('VIA ✗')
    if is_junc:
        status.append('JUNCTION ✗')
    if not is_via and not is_junc:
        status.append('FREE ✓')

    can_trim = not is_via and not is_junc
    max_trim = 0 if is_via else (0 if is_junc else 280)

    print(f"\nV{vnum}: {orient}-wire, trim {trim_end} by {trim_amt}nm")
    print(f"  Net: {wnet}")
    print(f"  Wire: [{wl/1e3:.3f},{wb2/1e3:.3f}]-[{wr/1e3:.3f},{wt/1e3:.3f}]")
    print(f"  Endpoint: ({ep[0]/1e3:.3f}, {ep[1]/1e3:.3f})")
    print(f"  Status: {', '.join(status)} (max_trim={max_trim}nm, need={trim_amt}nm)")
    if can_trim:
        if trim_amt <= max_trim:
            print(f"  >> CAN FIX ✓")
        else:
            print(f"  >> TRIM TOO LARGE ({trim_amt} > {max_trim})")
    else:
        print(f"  >> CANNOT TRIM")
