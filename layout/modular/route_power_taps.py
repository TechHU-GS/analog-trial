#!/usr/bin/env python3
"""Power last mile: connect TM1 bus via stacks to module ntap/ptap.

For each module, drops M4-V from the power bus y to near the module,
then via stack down to M1 to connect to ntap (VDD) or ptap (GND).

Run AFTER route_power_v2.py.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/route_power_taps.py
"""
import json
import os
import gdstk
from shapely.geometry import box as sbox, Polygon
from shapely.ops import unary_union

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
os.chdir(os.path.dirname(SCRIPT_DIR))

# Layers
L_M1 = (8, 0);  L_V1 = (19, 0);  L_M2 = (10, 0)
L_V2 = (29, 0); L_M3 = (30, 0);  L_V3 = (49, 0)
L_M4 = (50, 0); L_V4 = (66, 0);  L_M5 = (67, 0)

# Sizes (um)
VIA_SZ = 0.190; VIA_H = VIA_SZ / 2
V1_SZ = 0.190;  V1_H = V1_SZ / 2
PAD_HW = 0.155  # M1/M2 pad half-width at via
M4_HW = 0.100   # M4 half-width
M3_HW = 0.100   # M3 half-width

VDD_Y = 59.5
GND_Y = 64.0


def add_rect(cell, layer, x1, y1, x2, y2):
    cell.add(gdstk.rectangle((min(x1,x2), min(y1,y2)), (max(x1,x2), max(y1,y2)),
             layer=layer[0], datatype=layer[1]))


def add_power_drop(cell, x, bus_y, tap_y, obstacles):
    """Drop M4-V from bus_y to tap_y at x, then via stack to M1.
    Returns True if placed, False if collision."""
    # Check M4-V collision along vertical segment
    y1, y2 = min(bus_y, tap_y), max(bus_y, tap_y)
    m4_shape = sbox(x - M4_HW - 0.25, y1, x + M4_HW + 0.25, y2)
    obs_m4 = obstacles.get(L_M4)
    if obs_m4 and not obs_m4.is_empty and m4_shape.intersects(obs_m4):
        return False
    # Check M2/M3 collision at tap landing point (NOT M1 — we want M1 overlap with taps)
    spacing = 0.250
    for lk in [L_M2, L_M3]:
        pad = sbox(x - PAD_HW, tap_y - PAD_HW, x + PAD_HW, tap_y + PAD_HW)
        obs = obstacles.get(lk)
        if obs and not obs.is_empty and pad.buffer(spacing).intersects(obs):
            return False

    # M4 vertical from bus_y to tap_y
    add_rect(cell, L_M4, x - M4_HW, y1, x + M4_HW, y2)

    # At bus_y: Via3 to connect to existing M3 pad from power via stack
    add_rect(cell, L_V3, x - VIA_H, bus_y - VIA_H, x + VIA_H, bus_y + VIA_H)
    add_rect(cell, L_M3, x - PAD_HW, bus_y - PAD_HW, x + PAD_HW, bus_y + PAD_HW)
    add_rect(cell, L_M4, x - PAD_HW, bus_y - PAD_HW, x + PAD_HW, bus_y + PAD_HW)

    # At tap_y: Via3 → M3 → Via2 → M2 → Via1 → M1
    add_rect(cell, L_V3, x - VIA_H, tap_y - VIA_H, x + VIA_H, tap_y + VIA_H)
    add_rect(cell, L_M3, x - PAD_HW, tap_y - PAD_HW, x + PAD_HW, tap_y + PAD_HW)
    add_rect(cell, L_M4, x - PAD_HW, tap_y - PAD_HW, x + PAD_HW, tap_y + PAD_HW)
    add_rect(cell, L_V2, x - VIA_H, tap_y - VIA_H, x + VIA_H, tap_y + VIA_H)
    add_rect(cell, L_M2, x - PAD_HW, tap_y - PAD_HW, x + PAD_HW, tap_y + PAD_HW)
    add_rect(cell, L_V1, x - V1_H, tap_y - V1_H, x + V1_H, tap_y + V1_H)
    add_rect(cell, L_M1, x - PAD_HW, tap_y - PAD_HW, x + PAD_HW, tap_y + PAD_HW)

    return True


def main():
    print('=== Power Last Mile: TM1 bus → module taps ===\n')

    with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
        fp = json.load(f)

    lib = gdstk.read_gds(os.path.join(OUT_DIR, 'soilz_routed.gds'))
    cell = [c for c in lib.cells if c.name == 'tt_um_techhu_analog_trial'][0]
    cell.flatten()

    # Load obstacles for all relevant layers
    obstacles = {}
    for lk in [L_M1, L_M2, L_M3, L_M4]:
        polys = []
        for p in cell.polygons:
            if p.layer == lk[0] and p.datatype == lk[1]:
                try:
                    pg = Polygon(p.points)
                    if pg.is_valid:
                        polys.append(pg)
                except:
                    pass
        obstacles[lk] = unary_union(polys) if polys else None
        if polys:
            print(f'  {lk}: {len(polys)} obstacles')

    # Module tap targets: (module, net, tap_y, preferred_x_range)
    # ntap (VDD) near module top, ptap (GND) near module bottom
    # Use module boundaries to estimate tap positions
    mods = ['bias_mn', 'bias_cascode', 'chopper', 'comp', 'dac_sw', 'hbridge',
            'hbridge_drive', 'ota', 'ptat_core', 'sw', 'vco_5stage', 'vco_buffer']

    vdd_count = 0
    gnd_count = 0

    for mod in mods:
        d = fp[mod]
        mx1, my1, mw, mh = d['x'], d['y'], d['w'], d['h']
        mcx = mx1 + mw / 2

        # VDD tap: near module top (ntap at top of module)
        vdd_tap_y = my1 + mh - 0.5  # 0.5um from top edge
        # GND tap: near module bottom (ptap at bottom)
        gnd_tap_y = my1 + 0.5  # 0.5um from bottom edge

        # Try multiple x positions near module center
        placed_vdd = False
        placed_gnd = False
        for x_off in [0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8, -10, 10, -12, 12, -15, 15, -20, 20]:
            x = mcx + x_off
            if x < mx1 or x > mx1 + mw:
                continue
            if not placed_vdd and add_power_drop(cell, x, VDD_Y, vdd_tap_y, obstacles):
                placed_vdd = True
                vdd_count += 1
                # Update obstacles
                y1, y2 = min(VDD_Y, vdd_tap_y), max(VDD_Y, vdd_tap_y)
                new_m4 = sbox(x - M4_HW, y1, x + M4_HW, y2)
                if obstacles[L_M4]:
                    obstacles[L_M4] = unary_union([obstacles[L_M4], new_m4])
                else:
                    obstacles[L_M4] = new_m4

            if not placed_gnd and add_power_drop(cell, x + 1, GND_Y, gnd_tap_y, obstacles):
                placed_gnd = True
                gnd_count += 1
                y1, y2 = min(GND_Y, gnd_tap_y), max(GND_Y, gnd_tap_y)
                new_m4 = sbox(x + 1 - M4_HW, y1, x + 1 + M4_HW, y2)
                if obstacles[L_M4]:
                    obstacles[L_M4] = unary_union([obstacles[L_M4], new_m4])
                else:
                    obstacles[L_M4] = new_m4

            if placed_vdd and placed_gnd:
                break

        status_v = '✓' if placed_vdd else '✗'
        status_g = '✓' if placed_gnd else '✗'
        print(f'  {mod:16s} VDD{status_v} GND{status_g}')

    print(f'\n  VDD taps: {vdd_count}/{len(mods)}')
    print(f'  GND taps: {gnd_count}/{len(mods)}')

    out_path = os.path.join(OUT_DIR, 'soilz_routed.gds')
    lib.write_gds(out_path)
    print(f'  Written to {out_path}')
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
