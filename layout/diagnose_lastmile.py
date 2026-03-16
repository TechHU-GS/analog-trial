#!/usr/bin/env python3
"""Last-mile audit: for every gate pin, measure the gap between routing
backbone and the gate access point.

Outputs:
  1. Per-pin detail: net, AP, nearest same-net segment on each layer, gap
  2. Summary table bucketed by gap size
  3. Module breakdown

Usage:
    cd layout && python3 diagnose_lastmile.py
"""
import os, json, sys
from collections import defaultdict, Counter

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Layer encoding (matches maze router / routing.json) ─────────────
M1, M2, M3, M4 = 0, 1, 2, 3
VIA1, VIA2, VIA3 = -1, -2, -3
LYR_NAME = {VIA3: 'Via3', VIA2: 'Via2', VIA1: 'Via1',
             M1: 'M1', M2: 'M2', M3: 'M3', M4: 'M4'}

M1_SIG_W = 300
M1_HW = M1_SIG_W // 2

# ── Load routing data ───────────────────────────────────────────────
with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing['access_points']
sroutes = routing['signal_routes']

# ── Identify functional module from device name ─────────────────────
def module_of(pin_name):
    """Extract module prefix from pin name like 'MBn2.G' -> 'MB'."""
    dev = pin_name.split('.')[0]
    # Strip leading 'M' (MOSFET prefix)
    core = dev[1:] if dev.startswith('M') else dev
    # Common prefixes
    for pfx in ['TFF', 'BUF', 'INV', 'chop', 'mux', 'comp', 'Bp', 'Bn',
                 'pb', 'nb', 'xcur', 'bias', 'ref', 'osc', 'ring',
                 'PM', 'NM', 'Xfi', 'Xdi', 'fi_', 'di_']:
        if core.startswith(pfx):
            return pfx
    # Fallback: first 2-3 alphabetic chars
    alpha = ''
    for c in core:
        if c.isalpha():
            alpha += c
        else:
            break
    return alpha[:3] if alpha else '???'


# ── Per-pin analysis ────────────────────────────────────────────────
results = []  # list of dicts

for net_name, route in sroutes.items():
    segs = route.get('segments', [])
    pins = route.get('pins', [])

    for pin_key in pins:
        if '.G' not in pin_key:
            continue
        ap = aps.get(pin_key)
        if not ap:
            continue
        ap_x, ap_y = ap['x'], ap['y']
        mode = ap.get('mode', '?')
        via_pad = ap.get('via_pad', {})
        m1_pad = via_pad.get('m1')
        m2_pad = via_pad.get('m2')

        # ── Find nearest same-net segment on each metal layer ───────
        nearest = {}  # layer -> (dist, endpoint_x, endpoint_y, seg)

        for seg in segs:
            lyr = seg[4]
            if lyr < 0:
                # For vias, treat as point
                vx, vy = seg[0], seg[1]
                d = abs(vx - ap_x) + abs(vy - ap_y)
                if lyr not in nearest or d < nearest[lyr][0]:
                    nearest[lyr] = (d, vx, vy, seg)
            else:
                # For wires, check both endpoints AND pass-through
                for ex, ey in [(seg[0], seg[1]), (seg[2], seg[3])]:
                    d = abs(ex - ap_x) + abs(ey - ap_y)
                    if lyr not in nearest or d < nearest[lyr][0]:
                        nearest[lyr] = (d, ex, ey, seg)

                # Pass-through check (wire centerline passes over AP)
                x1, y1, x2, y2 = seg[:4]
                hw = M1_HW  # approximate for all layers
                if x1 == x2:  # vertical
                    if abs(x1 - ap_x) <= hw and min(y1, y2) <= ap_y <= max(y1, y2):
                        if lyr not in nearest or 0 < nearest[lyr][0]:
                            nearest[lyr] = (0, ap_x, ap_y, seg)
                elif y1 == y2:  # horizontal
                    if abs(y1 - ap_y) <= hw and min(x1, x2) <= ap_x <= max(x1, x2):
                        if lyr not in nearest or 0 < nearest[lyr][0]:
                            nearest[lyr] = (0, ap_x, ap_y, seg)

        # ── Check M1 overlap with gate PCell pad ────────────────────
        m1_connected = False
        if M1 in nearest:
            m1_dist = nearest[M1][0]
            if m1_dist == 0:
                m1_connected = True
            elif m1_pad and m1_dist < 500:
                # Check if any M1 segment endpoint is within the M1 pad bbox
                ex, ey = nearest[M1][1], nearest[M1][2]
                if (ex + M1_HW > m1_pad[0] and ex - M1_HW < m1_pad[2]
                        and ey + M1_HW > m1_pad[1] and ey - M1_HW < m1_pad[3]):
                    m1_connected = True

        # ── Determine connectivity level ────────────────────────────
        has_via1 = VIA1 in nearest and nearest[VIA1][0] < 300
        has_m2 = M2 in nearest
        has_via2 = VIA2 in nearest
        has_m3 = M3 in nearest
        has_m4 = M4 in nearest

        if m1_connected:
            level = 'M1_OK'
        elif M1 in nearest and nearest[M1][0] < 500:
            level = 'M1_NEAR'
        elif has_via1:
            level = 'VIA1_ONLY'
        elif has_m2 and nearest[M2][0] < 500:
            level = 'M2_NEAR'
        elif has_m3 or has_m4:
            level = 'UPPER_ONLY'
        else:
            level = 'NO_ROUTE'

        # ── Measure gap: distance from nearest segment (any layer) to AP ──
        all_dists = [(lyr, info[0]) for lyr, info in nearest.items()]
        all_dists.sort(key=lambda x: x[1])

        # Gap = distance from nearest metal (M1 or M2) segment to AP
        m1_gap = nearest[M1][0] if M1 in nearest else float('inf')
        m2_gap = nearest[M2][0] if M2 in nearest else float('inf')
        m3_gap = nearest[M3][0] if M3 in nearest else float('inf')
        m4_gap = nearest[M4][0] if M4 in nearest else float('inf')
        via1_gap = nearest[VIA1][0] if VIA1 in nearest else float('inf')

        # The "last-mile gap" = distance from nearest low-layer (M1/Via1/M2)
        # route to the gate AP. If none, use nearest upper layer.
        low_gap = min(m1_gap, via1_gap, m2_gap)
        any_gap = min(low_gap, m3_gap, m4_gap)

        # Nearest upper-layer segment (the "backbone end")
        backbone_gap = min(m3_gap, m4_gap)
        backbone_lyr = None
        if m3_gap <= m4_gap and M3 in nearest:
            backbone_lyr = M3
        elif M4 in nearest:
            backbone_lyr = M4

        results.append({
            'pin': pin_key,
            'net': net_name,
            'ap_x': ap_x,
            'ap_y': ap_y,
            'mode': mode,
            'module': module_of(pin_key),
            'level': level,
            'm1_gap': m1_gap,
            'm2_gap': m2_gap,
            'm3_gap': m3_gap,
            'm4_gap': m4_gap,
            'via1_gap': via1_gap,
            'low_gap': low_gap,
            'backbone_gap': backbone_gap,
            'backbone_lyr': backbone_lyr,
            'any_gap': any_gap,
            'nearest': nearest,
        })

# ── Sort by level severity then gap ─────────────────────────────────
level_order = {'M1_OK': 0, 'M1_NEAR': 1, 'VIA1_ONLY': 2, 'M2_NEAR': 3,
               'UPPER_ONLY': 4, 'NO_ROUTE': 5}
results.sort(key=lambda r: (level_order.get(r['level'], 9), -r['any_gap']))

# ── Print detail for non-M1_OK pins ────────────────────────────────
print("=" * 90)
print("LAST-MILE AUDIT: Gate Pin Reachability")
print("=" * 90)
print()

level_counts = Counter(r['level'] for r in results)
for lvl in ['M1_OK', 'M1_NEAR', 'VIA1_ONLY', 'M2_NEAR', 'UPPER_ONLY', 'NO_ROUTE']:
    print(f"  {lvl:12s}: {level_counts.get(lvl, 0):4d} gate pins")
print(f"  {'TOTAL':12s}: {len(results):4d}")
print()

# Detail for non-OK pins
print("=" * 90)
print("DETAIL: Non-M1_OK gate pins")
print("=" * 90)
non_ok = [r for r in results if r['level'] != 'M1_OK']
for r in non_ok:
    backbone_str = f"{LYR_NAME.get(r['backbone_lyr'], '?')}@{r['backbone_gap']:.0f}nm" if r['backbone_lyr'] else "none"
    print(f"  {r['pin']:22s} net={r['net']:15s} mod={r['module']:5s}"
          f"  level={r['level']:11s}"
          f"  M1={r['m1_gap']:>7.0f}  M2={r['m2_gap']:>7.0f}"
          f"  Via1={r['via1_gap']:>7.0f}  backbone={backbone_str}")
print()

# ── Gap bucket analysis (for UPPER_ONLY and NO_ROUTE pins) ─────────
print("=" * 90)
print("GAP BUCKET TABLE (pins needing last-mile bridge)")
print("=" * 90)
print()

problem_pins = [r for r in results if r['level'] in ('UPPER_ONLY', 'NO_ROUTE', 'M2_NEAR')]

# Use backbone_gap for UPPER_ONLY, m2_gap for M2_NEAR
def effective_gap(r):
    if r['level'] == 'NO_ROUTE':
        return float('inf')
    if r['level'] == 'M2_NEAR':
        return r['m2_gap']
    return r['backbone_gap']

buckets = {
    '<500nm': [], '500nm-2um': [], '2um-10um': [],
    '10um-50um': [], '>50um': [], 'inf': []
}
for r in problem_pins:
    g = effective_gap(r)
    if g == float('inf'):
        buckets['inf'].append(r)
    elif g < 500:
        buckets['<500nm'].append(r)
    elif g < 2000:
        buckets['500nm-2um'].append(r)
    elif g < 10000:
        buckets['2um-10um'].append(r)
    elif g < 50000:
        buckets['10um-50um'].append(r)
    else:
        buckets['>50um'].append(r)

print(f"{'Gap bucket':<15} {'Pins':>5} {'Nets':>5}  {'Likely fix'}")
print(f"{'-'*15} {'-'*5} {'-'*5}  {'-'*40}")
for bucket_name in ['<500nm', '500nm-2um', '2um-10um', '10um-50um', '>50um', 'inf']:
    pins = buckets[bucket_name]
    nets = len(set(r['net'] for r in pins))
    if bucket_name == '<500nm':
        fix = 'assemble_gds M3 bridge extension'
    elif bucket_name == '500nm-2um':
        fix = 'short M3/M2 bridge (may fit)'
    elif bucket_name in ('2um-10um', '10um-50um'):
        fix = 'router issue — needs re-route'
    elif bucket_name == '>50um':
        fix = 'router never routed this pin'
    else:
        fix = 'no route segments at all'
    print(f"  {bucket_name:<13} {len(pins):>5} {nets:>5}  {fix}")
print()

# ── Module breakdown ────────────────────────────────────────────────
print("=" * 90)
print("MODULE BREAKDOWN (UPPER_ONLY + NO_ROUTE pins)")
print("=" * 90)
print()

mod_pins = defaultdict(list)
for r in problem_pins:
    mod_pins[r['module']].append(r)

print(f"{'Module':<8} {'Pins':>5}  {'Nets':>5}  {'Avg gap':>10}  {'Example pin'}")
print(f"{'-'*8} {'-'*5}  {'-'*5}  {'-'*10}  {'-'*30}")
for mod in sorted(mod_pins, key=lambda m: -len(mod_pins[m])):
    pins = mod_pins[mod]
    nets = len(set(r['net'] for r in pins))
    gaps = [effective_gap(r) for r in pins if effective_gap(r) != float('inf')]
    avg_gap = sum(gaps) / len(gaps) if gaps else float('inf')
    example = pins[0]['pin']
    avg_str = f"{avg_gap:.0f}nm" if avg_gap != float('inf') else "inf"
    print(f"  {mod:<6} {len(pins):>5}  {nets:>5}  {avg_str:>10}  {example}")
print()

# ── Cross-check with LVS fragmented nets ────────────────────────────
# Load the fragmented nets list for cross-reference
print("=" * 90)
print("CROSS-CHECK: Fragmented nets with UPPER_ONLY gate pins")
print("=" * 90)
print()

# Which nets have problem gate pins?
problem_nets = set(r['net'] for r in problem_pins)
ok_nets = set(r['net'] for r in results if r['level'] == 'M1_OK') - problem_nets
mixed_nets = set(r['net'] for r in results if r['level'] == 'M1_OK') & problem_nets

print(f"  Nets with ALL gate pins M1-connected:  {len(ok_nets)}")
print(f"  Nets with SOME gate pins disconnected:  {len(mixed_nets)}")
print(f"  Nets with ALL gate pins disconnected:   {len(problem_nets - mixed_nets)}")
print()

# Show mixed nets (most interesting — some pins connected, some not)
if mixed_nets:
    print("  Mixed nets (some gate pins OK, some not):")
    for net in sorted(mixed_nets):
        ok_pins = [r['pin'] for r in results if r['net'] == net and r['level'] == 'M1_OK']
        bad_pins = [r for r in results if r['net'] == net and r['level'] != 'M1_OK']
        print(f"    {net:15s}: {len(ok_pins)} OK, {len(bad_pins)} disconnected")
        for r in bad_pins:
            g = effective_gap(r)
            g_str = f"{g:.0f}nm" if g != float('inf') else "inf"
            print(f"      {r['pin']:20s} level={r['level']:11s} gap={g_str}")
    print()

# ── Final: which nets' gate pins are ALL M1-connected? ──────────────
print("=" * 90)
print("NETS WITH ALL GATE PINS M1-CONNECTED (should NOT appear in LVS gate fragmentation)")
print("=" * 90)
print()
for net in sorted(ok_nets):
    pin_names = [r['pin'] for r in results if r['net'] == net]
    print(f"  {net:15s}: {', '.join(pin_names)}")
