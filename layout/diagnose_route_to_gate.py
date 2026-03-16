#!/usr/bin/env python3
"""Check routing paths: does the route for each net actually reach each gate pin?

For each failing gate, traces the full route (all layers) and finds the
closest route segment to the gate pin. Reports whether the route reaches
the pin, and if not, where it stops.

Usage:
    cd layout && python3 diagnose_route_to_gate.py
"""
import os
import json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LAYER_NAMES = {-3: 'via3', -2: 'via2', -1: 'via1', 0: '???',
               1: 'M1', 2: 'M2', 3: 'M3', 4: 'M4'}

with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing['access_points']
sroutes = routing['signal_routes']

# For each net, check if routes reach all its gate pins
print("=" * 80)
print("ROUTE-TO-GATE REACHABILITY CHECK")
print("=" * 80)
print()

# Collect all gate pins per net
net_gate_pins = defaultdict(list)  # net -> [(pin_name, x, y, mode)]
for net_name, route in sroutes.items():
    for pin_name in route['pins']:
        if '.G' in pin_name:
            ap = aps.get(pin_name)
            if ap:
                net_gate_pins[net_name].append(
                    (pin_name, ap['x'], ap['y'], ap.get('mode', '?')))

# Statistics
total_gates = 0
reached_m1 = 0
reached_other = 0
not_reached = 0
gap_5nm_count = 0

# Check each net's routes
for net_name in sorted(net_gate_pins.keys()):
    gate_pins = net_gate_pins[net_name]
    if not gate_pins:
        continue

    route = sroutes[net_name]
    segments = route['segments']

    for pin_name, px, py, mode in gate_pins:
        total_gates += 1

        # Find closest segment endpoint to this pin
        best_dist = 999999
        best_seg = None
        best_layer = None
        best_endpoint = None

        for seg in segments:
            x1, y1, x2, y2, lyr = seg
            # Check both endpoints
            for ex, ey in [(x1, y1), (x2, y2)]:
                dist = abs(ex - px) + abs(ey - py)  # Manhattan
                if dist < best_dist:
                    best_dist = dist
                    best_seg = seg
                    best_layer = lyr
                    best_endpoint = (ex, ey)

        # Also check if any segment PASSES THROUGH the pin
        # (wire centerline is within half-width of pin)
        HW = 150  # M1 half-width
        passes_through = False
        pass_layer = None
        for seg in segments:
            x1, y1, x2, y2, lyr = seg
            if lyr < 0:
                continue  # Skip vias for pass-through check
            if x1 == x2:  # vertical wire
                if abs(x1 - px) <= HW and min(y1, y2) <= py <= max(y1, y2):
                    passes_through = True
                    pass_layer = lyr
                    break
            elif y1 == y2:  # horizontal wire
                if abs(y1 - py) <= HW and min(x1, x2) <= px <= max(x1, x2):
                    passes_through = True
                    pass_layer = lyr
                    break

        # Check via at pin position
        has_via_at_pin = False
        via_layer = None
        for seg in segments:
            x1, y1, x2, y2, lyr = seg
            if lyr < 0:  # via
                if abs(x1 - px) <= 200 and abs(y1 - py) <= 200:
                    has_via_at_pin = True
                    via_layer = lyr
                    break

        # Classify
        if passes_through and pass_layer == 1:
            status = "M1_THROUGH"
            reached_m1 += 1
        elif best_dist <= 5:
            status = f"ENDPOINT_AT_PIN ({LAYER_NAMES.get(best_layer, '?')})"
            if best_layer == 1:
                reached_m1 += 1
            else:
                reached_other += 1
        elif best_dist <= 200 and has_via_at_pin:
            status = f"VIA_NEAR_PIN ({LAYER_NAMES.get(via_layer, '?')})"
            reached_other += 1
        elif best_dist <= 200:
            if best_layer == 1:
                status = f"M1_NEAR gap={best_dist}nm"
                gap_5nm_count += 1
            else:
                status = f"NEAR_{LAYER_NAMES.get(best_layer, '?')} gap={best_dist}nm"
            not_reached += 1
        else:
            status = f"FAR gap={best_dist}nm layer={LAYER_NAMES.get(best_layer, '?')}"
            not_reached += 1

        # Only print failing/interesting cases
        if 'M1_THROUGH' not in status and 'ENDPOINT_AT_PIN' not in status:
            print(f"  {pin_name:20s} ({net_name:15s}) mode={mode:7s}"
                  f" → {status}")
            if best_seg:
                print(f"    closest seg: ({best_seg[0]},{best_seg[1]})"
                      f"→({best_seg[2]},{best_seg[3]})"
                      f" [{LAYER_NAMES.get(best_seg[4], '?')}]"
                      f" endpoint=({best_endpoint[0]},{best_endpoint[1]})")

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"  Total gate pins in routed nets: {total_gates}")
print(f"  Route reaches pin on M1:        {reached_m1}")
print(f"  Route reaches pin on other:     {reached_other}")
print(f"  Route doesn't reach pin:        {not_reached}")
print(f"    of which near-miss (≤200nm):  {gap_5nm_count}")
print()

# ── Deep dive: WHY don't routes reach gates? ──────────────────────────

print("=" * 80)
print("ROUTE SEGMENT ANALYSIS FOR UNREACHED GATES")
print("=" * 80)
print()

# For gates that aren't reached, show all segments of the net
# and the gate pin position
unreached_examples = []
for net_name in sorted(net_gate_pins.keys()):
    gate_pins = net_gate_pins[net_name]
    route = sroutes[net_name]
    segments = route['segments']

    for pin_name, px, py, mode in gate_pins:
        best_dist = 999999
        for seg in segments:
            x1, y1, x2, y2, lyr = seg
            for ex, ey in [(x1, y1), (x2, y2)]:
                dist = abs(ex - px) + abs(ey - py)
                if dist < best_dist:
                    best_dist = dist

        if best_dist > 200 and len(unreached_examples) < 5:
            unreached_examples.append(
                (pin_name, net_name, px, py, mode, best_dist, segments))

for pin_name, net_name, px, py, mode, dist, segments in unreached_examples:
    print(f"─── {pin_name} ({net_name}) pin=({px},{py}) nearest={dist}nm ───")
    print(f"  All pins: {sroutes[net_name]['pins']}")
    print(f"  All {len(segments)} segments:")
    for seg in segments:
        lyr = LAYER_NAMES.get(seg[4], '?')
        print(f"    ({seg[0]:6d},{seg[1]:6d}) → ({seg[2]:6d},{seg[3]:6d})"
              f" [{lyr:4s}]")
    # Show pin positions for all pins in this net
    print(f"  Pin positions:")
    for p in sroutes[net_name]['pins']:
        ap = aps.get(p)
        if ap:
            print(f"    {p:20s} ({ap['x']:6d},{ap['y']:6d}) mode={ap['mode']}")
    print()
