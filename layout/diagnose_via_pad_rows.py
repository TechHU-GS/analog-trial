#!/usr/bin/env python3
"""Identify power-signal via pad pairs with M2 gap < 210nm.

Groups violations by device row Y position to guide +10nm placement experiment.
Reads routing.json (power drops + signal routes + access points).
"""

import json
import sys
from collections import defaultdict, Counter

with open('output/routing.json') as f:
    routing = json.load(f)
with open('placement.json') as f:
    placement = json.load(f)

HP = 240  # VIA1_PAD // 2 = 480 // 2
MIN_S = 210  # M2.b minimum spacing

# ── Collect power via M2 pads ──────────────────────────────────
power_vias = []  # (cx, cy, net, label)
for drop in routing['power']['drops']:
    net = drop['net']
    inst = drop['inst']
    pin = drop['pin']
    # via_stack has via1_pos at device level; via_access has via_x/via_y
    if drop['type'] == 'via_stack':
        vx, vy = drop['via1_pos']
    else:  # via_access
        vx, vy = drop['via_x'], drop['via_y']
    power_vias.append((vx, vy, net, f'{inst}.{pin}'))
    # Also add via2 position (M2↔M3 via, has M2 pad too)
    if 'via2_pos' in drop:
        v2x, v2y = drop['via2_pos']
        if (v2x, v2y) != (vx, vy):
            power_vias.append((v2x, v2y, net, f'{inst}.{pin}_v2'))
    # M2 jog/vbar creates M2 wire that can also violate
    # (handled separately if needed)

print(f'Power vias: {len(power_vias)}')

# ── Collect signal via M2 pads ─────────────────────────────────
# Signal vias come from: 1) access point via pads, 2) route vias (layer=-2 = via1)
signal_vias = []  # (cx, cy, net, label)

# From access points (all pins that are routed)
routed_nets = set(routing['signal_routes'].keys())
routed_pins = set()
for net_name, route in routing['signal_routes'].items():
    for pin in route['pins']:
        routed_pins.add(pin)

for ap_name, ap in routing['access_points'].items():
    if ap_name not in routed_pins:
        continue
    # Find which net this pin belongs to
    net_for_pin = None
    for net_name, route in routing['signal_routes'].items():
        if ap_name in route['pins']:
            net_for_pin = net_name
            break
    if net_for_pin is None:
        continue
    vp = ap.get('via_pad')
    if vp and 'm2' in vp:
        m2 = vp['m2']
        cx = (m2[0] + m2[2]) // 2
        cy = (m2[1] + m2[3]) // 2
        signal_vias.append((cx, cy, net_for_pin, ap_name))

# From route segments (via1 = layer -2, connects M1↔M2)
for net_name, route in routing['signal_routes'].items():
    for seg in route['segments']:
        if seg[4] == -2:  # via1
            signal_vias.append((seg[0], seg[1], net_name, f'{net_name}_via'))

print(f'Signal vias: {len(signal_vias)}')

# ── Find violating pairs ──────────────────────────────────────
pairs = []
for px, py, pnet, plabel in power_vias:
    p_rect = (px - HP, py - HP, px + HP, py + HP)
    for sx, sy, snet, slabel in signal_vias:
        s_rect = (sx - HP, sy - HP, sx + HP, sy + HP)
        # Edge-to-edge gap
        x_gap = max(p_rect[0] - s_rect[2], s_rect[0] - p_rect[2])
        y_gap = max(p_rect[1] - s_rect[3], s_rect[1] - p_rect[3])
        # Overlap in X, gap in Y
        if x_gap < 0 and 0 < y_gap < MIN_S:
            pairs.append({
                'gap': y_gap, 'axis': 'Y',
                'pwr': (px, py, pnet, plabel),
                'sig': (sx, sy, snet, slabel),
                'overlap': -x_gap,
            })
        # Overlap in Y, gap in X
        elif y_gap < 0 and 0 < x_gap < MIN_S:
            pairs.append({
                'gap': x_gap, 'axis': 'X',
                'pwr': (px, py, pnet, plabel),
                'sig': (sx, sy, snet, slabel),
                'overlap': -y_gap,
            })

print(f'\nViolating pairs (gap < {MIN_S}nm): {len(pairs)}')
print(f'  Y-axis gaps: {sum(1 for p in pairs if p["axis"]=="Y")}')
print(f'  X-axis gaps: {sum(1 for p in pairs if p["axis"]=="X")}')

# ── Gap distribution ──────────────────────────────────────────
gap_hist = Counter()
for p in pairs:
    gap_hist[p['gap']] += 1
print(f'\nGap distribution:')
for gap, cnt in sorted(gap_hist.items()):
    print(f'  {gap:4d}nm: {cnt:3d} {"<<<" if gap == 200 else ""}')

# ── Group by Y row ────────────────────────────────────────────
# Quantize Y positions to find device rows
def row_key(y, quantum=500):
    """Quantize Y to nearest 0.5µm (500nm) row."""
    return round(y / quantum) * quantum

row_violations = defaultdict(list)
for p in pairs:
    py = p['pwr'][1]
    sy = p['sig'][1]
    # Use midpoint Y as row indicator
    mid_y = (py + sy) // 2
    rk = row_key(mid_y)
    row_violations[rk].append(p)

print(f'\n{"="*70}')
print(f'VIOLATIONS BY ROW Y POSITION')
print(f'{"="*70}')
for rk in sorted(row_violations.keys()):
    viols = row_violations[rk]
    gaps = [v['gap'] for v in viols]
    print(f'\nRow Y≈{rk/1000:.1f}µm: {len(viols)} violations (gaps: {sorted(set(gaps))}nm)')
    # Show device pairs
    seen = set()
    for v in viols:
        key = (v['pwr'][3], v['sig'][3])
        if key in seen:
            continue
        seen.add(key)
        print(f'  {v["pwr"][3]:20s} ({v["pwr"][2]:>4s}) ↔ {v["sig"][3]:20s} ({v["sig"][2]:>12s})  '
              f'gap={v["gap"]}nm axis={v["axis"]} overlap={v["overlap"]}nm')

# ── Map to placement rows ─────────────────────────────────────
print(f'\n{"="*70}')
print(f'DEVICE ROW MAPPING')
print(f'{"="*70}')

# Group devices by Y position
dev_by_y = defaultdict(list)
for name, inst in placement['instances'].items():
    y_nm = round(inst['y_um'] * 1000)
    rk = row_key(y_nm, quantum=500)
    dev_by_y[rk].append((name, y_nm, inst.get('h_um', 0)))

# For each violation row, find which placement rows are involved
for rk in sorted(row_violations.keys()):
    viols = row_violations[rk]
    if not viols:
        continue
    # Collect all device names from power and signal labels
    pwr_devs = set()
    sig_devs = set()
    for v in viols:
        plabel = v['pwr'][3]
        slabel = v['sig'][3]
        if '.' in plabel:
            pwr_devs.add(plabel.split('.')[0])
        if '.' in slabel:
            sig_devs.add(slabel.split('.')[0])

    # Find Y positions of these devices
    pwr_ys = []
    sig_ys = []
    for d in pwr_devs:
        if d in placement['instances']:
            pwr_ys.append(placement['instances'][d]['y_um'])
    for d in sig_devs:
        if d in placement['instances']:
            sig_ys.append(placement['instances'][d]['y_um'])

    if pwr_ys and sig_ys:
        py_avg = sum(pwr_ys) / len(pwr_ys)
        sy_avg = sum(sig_ys) / len(sig_ys)
        dy = abs(py_avg - sy_avg)
        print(f'\nRow Y≈{rk/1000:.1f}µm ({len(viols)} viols):')
        print(f'  Power devices: {sorted(pwr_devs)} → Y≈{py_avg:.1f}µm')
        print(f'  Signal devices: {sorted(sig_devs)} → Y≈{sy_avg:.1f}µm')
        print(f'  Row ΔY = {dy:.2f}µm')
        print(f'  FIX: shift {"upper" if py_avg > sy_avg else "lower"} row +10nm '
              f'(would increase gap from {min(v["gap"] for v in viols)}nm to {min(v["gap"] for v in viols)+10}nm)')

# ── Summary: top hotspot rows ─────────────────────────────────
print(f'\n{"="*70}')
print(f'TOP HOTSPOT ROWS (sorted by violation count)')
print(f'{"="*70}')
ranked = sorted(row_violations.items(), key=lambda x: -len(x[1]))
for rk, viols in ranked[:15]:
    gaps = [v['gap'] for v in viols]
    print(f'  Y≈{rk/1000:6.1f}µm: {len(viols):3d} viols, gaps={sorted(set(gaps))}nm')
