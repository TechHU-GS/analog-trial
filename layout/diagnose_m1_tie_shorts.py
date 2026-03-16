#!/usr/bin/env python3
"""Diagnose M1 shorts between signal AP M1 shapes and tie M1 bars.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m1_tie_shorts.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from atk.pdk import M1_MIN_S, VIA1_PAD_M1, VIA1_SZ, M1_THIN

ROUTING = 'output/routing.json'
TIES = 'output/ties.json'

with open(ROUTING) as f:
    routing = json.load(f)
with open(TIES) as f:
    ties = json.load(f)

# Build pin→net map
pin_net = {}
for net_type in ['signal_routes', 'pre_routes']:
    for net, route in routing.get(net_type, {}).items():
        for pin in route.get('pins', []):
            pin_net[pin] = net

# Build via_stack pins set (their AP M1 pads are not drawn)
via_stack_pins = set()
for drop in routing.get('power', {}).get('drops', []):
    if drop['type'] == 'via_stack':
        via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

# Collect signal AP M1 shapes
ap_m1_shapes = []  # (rect, net, key, kind)
for key, ap in routing.get('access_points', {}).items():
    if key in via_stack_pins:
        continue
    net = pin_net.get(key, '')
    if not net:
        continue
    # Skip power nets
    if net in ('vdd', 'gnd', 'vdd_vco'):
        continue
    skip_m1 = ap.get('mode') == 'gate_no_m1'
    vp = ap.get('via_pad', {})
    if 'm1' in vp and not skip_m1:
        ap_m1_shapes.append((vp['m1'], net, key, 'm1_pad'))
    if ap.get('m1_stub') and not skip_m1:
        ap_m1_shapes.append((ap['m1_stub'], net, key, 'm1_stub'))

# Collect tie M1 bars
tie_m1_bars = []  # (rect, net, tie_id)
for tie in ties.get('ties', []):
    for rect in tie.get('layers', {}).get('M1_8_0', []):
        tie_m1_bars.append((rect, tie['net'], tie['id']))

print(f"Signal AP M1 shapes: {len(ap_m1_shapes)}")
print(f"Tie M1 bars: {len(tie_m1_bars)}")
print()


def rects_touch_or_overlap(r1, r2):
    """Check if two rects touch (share edge) or overlap."""
    # Rects are [xl, yb, xr, yt]
    if r1[2] < r2[0] or r1[0] > r2[2]:  # no X overlap (strict)
        return False
    if r1[3] < r2[1] or r1[1] > r2[3]:  # no Y overlap (strict)
        return False
    return True


def overlap_area(r1, r2):
    """Return overlap area (0 if only touching)."""
    ox = max(0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    oy = max(0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    return ox * oy


def gap_between(r1, r2):
    """Return gap between two rects (negative = overlap)."""
    dx = max(r2[0] - r1[2], r1[0] - r2[2])
    dy = max(r2[1] - r1[3], r1[1] - r2[3])
    return max(dx, dy)


# Find all touching/overlapping pairs
shorts = []
for ap_rect, ap_net, ap_key, ap_kind in ap_m1_shapes:
    for tie_rect, tie_net, tie_id in tie_m1_bars:
        if rects_touch_or_overlap(ap_rect, tie_rect):
            g = gap_between(ap_rect, tie_rect)
            oa = overlap_area(ap_rect, tie_rect)
            shorts.append({
                'ap_key': ap_key,
                'ap_net': ap_net,
                'ap_kind': ap_kind,
                'ap_rect': ap_rect,
                'tie_id': tie_id,
                'tie_net': tie_net,
                'tie_rect': tie_rect,
                'gap': g,
                'overlap_area': oa,
            })

print(f"{'='*80}")
print(f"M1 SIGNAL-vs-TIE SHORTS: {len(shorts)}")
print(f"{'='*80}\n")

for i, s in enumerate(shorts):
    ar = s['ap_rect']
    tr = s['tie_rect']
    print(f"{i+1:3d}. {s['ap_key']:20s} ({s['ap_net']:10s}) {s['ap_kind']:8s}  <->  "
          f"{s['tie_id']:30s} ({s['tie_net']:4s})")
    print(f"     AP M1:  [{ar[0]:6d},{ar[1]:6d},{ar[2]:6d},{ar[3]:6d}]  "
          f"({ar[2]-ar[0]}x{ar[3]-ar[1]}nm)")
    print(f"     Tie M1: [{tr[0]:6d},{tr[1]:6d},{tr[2]:6d},{tr[3]:6d}]  "
          f"({tr[2]-tr[0]}x{tr[3]-tr[1]}nm)")
    print(f"     Gap: {s['gap']}nm, Overlap area: {s['overlap_area']}nm²")

    # Analyze overlap geometry
    if s['gap'] == 0:
        # Touching — find which edge
        if ar[3] == tr[1]:
            print(f"     Type: AP top touches Tie bottom (Y={ar[3]})")
        elif ar[1] == tr[3]:
            print(f"     Type: AP bottom touches Tie top (Y={ar[1]})")
        elif ar[2] == tr[0]:
            print(f"     Type: AP right touches Tie left (X={ar[2]})")
        elif ar[0] == tr[2]:
            print(f"     Type: AP left touches Tie right (X={ar[0]})")
        else:
            print(f"     Type: Corner touch")
    elif s['gap'] < 0:
        ox1 = max(ar[0], tr[0])
        oy1 = max(ar[1], tr[1])
        ox2 = min(ar[2], tr[2])
        oy2 = min(ar[3], tr[3])
        print(f"     Type: OVERLAP region [{ox1},{oy1},{ox2},{oy2}]"
              f" ({ox2-ox1}x{oy2-oy1}nm)")

    # Suggest fix: how much to trim AP M1 or tie M1
    needed_gap = M1_MIN_S  # 180nm
    trim_needed = needed_gap - max(0, s['gap'])
    print(f"     Need: {trim_needed}nm gap creation")

    # Check if AP M1 pad can be trimmed
    if s['ap_kind'] == 'm1_pad':
        # Pad is VIA1_PAD_M1 square, via1 is VIA1_SZ centered
        pad_h = ar[3] - ar[1]
        hp_m1 = VIA1_PAD_M1 // 2  # 185
        hs_v1 = VIA1_SZ // 2  # 95
        v1_enc = 50  # V1.c1 endcap enclosure
        min_edge = hs_v1 + v1_enc  # 145nm from via center to pad edge
        max_trim = hp_m1 - min_edge  # 185 - 145 = 40nm
        print(f"     AP pad trim room: {max_trim}nm (pad_half={hp_m1}, "
              f"min_edge={min_edge})")
    elif s['ap_kind'] == 'm1_stub':
        stub_w = ar[2] - ar[0]
        stub_h = ar[3] - ar[1]
        print(f"     AP stub: {stub_w}x{stub_h}nm (M1_THIN={M1_THIN})")

    # Check tie bar dimensions
    tie_w = tr[2] - tr[0]
    tie_h = tr[3] - tr[1]
    print(f"     Tie bar: {tie_w}x{tie_h}nm")
    print()

# Summary: group by net pair
print(f"\n{'='*80}")
print("SUMMARY BY NET PAIR")
print(f"{'='*80}")
pairs = {}
for s in shorts:
    pair = (s['ap_net'], s['tie_net'])
    pairs.setdefault(pair, []).append(s)

for (ap_net, tie_net), items in sorted(pairs.items()):
    keys = [f"{s['ap_key']}({s['ap_kind']})" for s in items]
    print(f"  {ap_net:12s} <-> {tie_net:4s}: {len(items)} shorts")
    for k in keys:
        print(f"    {k}")
