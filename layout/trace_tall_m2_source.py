#!/usr/bin/env python3
"""Trace origin of tall M2 shapes by recomputing bridge/underpass M2 bars.

Reads routing.json and replicates the logic of:
  1. _draw_rail_bridges() — M2 vbar between same-net rails
  2. Power drop via_stack M2 underpass — M2 vbar bridging rail gaps

Then compares to the 44 UNKNOWN 480x3800nm shapes found in GDS.
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, '.')
from atk.pdk import (
    M2_SIG_W, VIA1_PAD, VIA2_PAD, VIA2_PAD_M3, M3_MIN_W,
    MAZE_GRID, M2_MIN_S,
)
from atk.route.maze_router import M2_LYR

ROUTING = 'output/routing.json'

with open(ROUTING) as f:
    data = json.load(f)

all_rails = data.get('power', {}).get('rails', {})

# Collect M2 signal segs (for conflict check replication)
m2_signal_segs = []
for net, rd in data.get('signal_routes', {}).items():
    for seg in rd.get('segments', []):
        if len(seg) >= 5 and seg[4] == M2_LYR:
            m2_signal_segs.append((seg[0], seg[1], seg[2], seg[3]))

# ── 1. Replicate _draw_rail_bridges() M2 shapes ──
print("=== _draw_rail_bridges() M2 shapes ===\n")
net_rails = defaultdict(list)
for rail_id, rail in all_rails.items():
    net = rail.get('net', rail_id)
    net_rails[net].append((rail_id, rail))

bridge_m2 = []
net_idx = 0
for net, rail_list in sorted(net_rails.items()):
    if len(rail_list) < 2:
        continue
    rail_list.sort(key=lambda r: r[1]['y'])
    for i in range(len(rail_list) - 1):
        rid1, r1 = rail_list[i]
        rid2, r2 = rail_list[i + 1]
        y1, y2 = r1['y'], r2['y']
        base_x = r1['x1'] + 1500
        bridge_x = base_x + net_idx * 2000

        hp = VIA2_PAD // 2
        has_conflict = False
        for sx1, sy1, sx2, sy2 in m2_signal_segs:
            sw = M2_SIG_W // 2
            seg_x1 = min(sx1, sx2) - sw
            seg_x2 = max(sx1, sx2) + sw
            seg_y1 = min(sy1, sy2)
            seg_y2 = max(sy1, sy2)
            if (bridge_x - hp < seg_x2 and bridge_x + hp > seg_x1 and
                    seg_y1 < y2 and seg_y2 > y1):
                has_conflict = True
                break
        if has_conflict:
            bridge_x = r1['x2'] - 1500 - net_idx * 2000

        # Via2 pads (480x480 each)
        bridge_m2.append(('rail_bridge_v2pad', net, bridge_x - hp, y1 - hp, bridge_x + hp, y1 + hp))
        bridge_m2.append(('rail_bridge_v2pad', net, bridge_x - hp, y2 - hp, bridge_x + hp, y2 + hp))
        # M2 vbar
        hw = VIA2_PAD // 2
        x1b = bridge_x - hw
        y1b = min(y1, y2)
        x2b = bridge_x + hw
        y2b = max(y1, y2)
        w = x2b - x1b
        h = y2b - y1b
        bridge_m2.append(('rail_bridge_vbar', net, x1b, y1b, x2b, y2b))
        print(f"  rail_bridge: {net} x={bridge_x} y={y1}-{y2}  size={w}x{h}nm"
              f"  {rid1}<->{rid2}")
    net_idx += 1

# ── 2. Replicate power drop via_stack M2 underpass shapes ──
print("\n=== Power drop via_stack M2 underpass shapes ===\n")
drop_m2 = []
for drop in data.get('power', {}).get('drops', []):
    if drop.get('strategy') != 'via_stack':
        continue
    drop_net = drop['net']
    inst = drop['inst']
    pin = drop['pin']
    pin_x = drop.get('via1_pos', [0, 0])[0]
    pin_y = drop.get('via1_pos', [0, 0])[1]

    # Replicate excl zone logic
    m3_vbar = drop.get('m3_vbar')
    if not m3_vbar:
        continue
    vbar_y1 = min(m3_vbar[1], m3_vbar[3])
    vbar_y2 = max(m3_vbar[1], m3_vbar[3])

    # Build exclusion zones (other-net rails)
    excl = []
    margin = VIA2_PAD_M3 // 2 + M2_MIN_S  # extra margin
    for rn, rl in all_rails.items():
        rnet = rl.get('net', rn)
        if rnet == drop_net:
            continue
        ry = rl['y']
        rw = rl.get('width', 0) // 2
        ey1 = ry - rw - margin
        ey2 = ry + rw + margin
        if ey1 < vbar_y2 and ey2 > vbar_y1:
            excl.append((max(ey1, vbar_y1), min(ey2, vbar_y2)))
    excl.sort()

    # Build gap_entries
    seg_y1 = vbar_y1
    gap_entries = []
    for ey1, ey2 in excl:
        if ey1 > seg_y1:
            pass  # M3 segment
        gap_entries.append((max(seg_y1, ey1), ey2))
        seg_y1 = max(seg_y1, ey2)

    # Process each gap → M2 underpass
    hp_m2 = VIA2_PAD // 2
    for gy1, gy2 in gap_entries:
        bridge_x = pin_x
        has_conflict = False
        for sx1, sy1, sx2, sy2 in m2_signal_segs:
            sw = M2_SIG_W // 2
            if sx1 == sx2:
                if ((sx1 - sw) < bridge_x + hp_m2
                        and (sx1 + sw) > bridge_x - hp_m2):
                    slo, shi = min(sy1, sy2), max(sy1, sy2)
                    if slo < gy2 and shi > gy1:
                        has_conflict = True
                        break
            elif sy1 == sy2:
                if gy1 < sy1 < gy2:
                    slo_x = min(sx1, sx2)
                    shi_x = max(sx1, sx2)
                    if ((slo_x - sw) < bridge_x + hp_m2
                            and (shi_x + sw) > bridge_x - hp_m2):
                        has_conflict = True
                        break
        if has_conflict:
            bridge_x = pin_x - 1600

        # Via2 pads
        drop_m2.append(('drop_underpass_v2pad', drop_net, bridge_x - hp_m2, gy1 - hp_m2, bridge_x + hp_m2, gy1 + hp_m2))
        drop_m2.append(('drop_underpass_v2pad', drop_net, bridge_x - hp_m2, gy2 - hp_m2, bridge_x + hp_m2, gy2 + hp_m2))
        # M2 vbar
        hw = VIA2_PAD // 2
        x1b = bridge_x - hw
        y1b = min(gy1, gy2)
        x2b = bridge_x + hw
        y2b = max(gy1, gy2)
        w = x2b - x1b
        h = y2b - y1b
        drop_m2.append(('drop_underpass_vbar', drop_net, x1b, y1b, x2b, y2b))
        print(f"  drop_underpass: {drop_net} {inst}.{pin} x={bridge_x} y={gy1}-{gy2}"
              f"  size={w}x{h}nm  conflict={has_conflict}")

# ── 3. Summary of tall shapes ──
print("\n=== All computed M2 shapes >1000nm tall ===\n")
all_computed = bridge_m2 + drop_m2
tall = [(tag, net, x1, y1, x2, y2) for tag, net, x1, y1, x2, y2 in all_computed
        if (y2 - y1) > 1000]
tall.sort(key=lambda s: (s[3], s[2]))
for tag, net, x1, y1, x2, y2 in tall:
    w = x2 - x1
    h = y2 - y1
    print(f"  {tag:25s} {net:12s} ({x1},{y1})-({x2},{y2})  {w}x{h}nm")

print(f"\nTotal tall M2 shapes (>1000nm): {len(tall)}")
print(f"Total rail bridge M2 shapes: {len(bridge_m2)}")
print(f"Total drop underpass M2 shapes: {len(drop_m2)}")
