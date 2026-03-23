#!/usr/bin/env python3
"""Power routing: TM1 buses + via stacks, collision-aware.

Reads soilz_routed.gds (with signal routes) and adds:
  1. TM1 horizontal VDD/GND buses
  2. Via stacks (TM1→TopVia1→M5→Via4→M4→Via3→M3→Via2→M2) at safe positions
  3. Avoids collision with existing signal route M3/M4/M5

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/route_power_v2.py
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
L_TV1 = (125, 0); L_TM1 = (126, 0)

# DRC (um)
VIA_SZ = 0.190;    VIA_H = VIA_SZ / 2
TV1_SZ = 0.420;    TV1_H = TV1_SZ / 2
TV1_ENC = 0.100    # M5 enclosure of TopVia1
TM1_ENC = 0.420    # TM1 enclosure of TopVia1
TM1_W = 2.400;     TM1_HW = TM1_W / 2
TM1_SP = 1.640     # TM1 min spacing
M5_W = 1.000;      M5_HW = M5_W / 2
PAD_HW = 0.190     # Metal pad half-width at via


def add_rect(cell, layer, x1, y1, x2, y2):
    cell.add(gdstk.rectangle((x1, y1), (x2, y2), layer=layer[0], datatype=layer[1]))


def add_via_stack(cell, cx, cy, from_layer='M2', to_layer='TM1'):
    """Add via stack from from_layer to to_layer. Returns list of (layer, shapely_box) shapes."""
    shapes = []
    stack = [
        ('M2', L_M2, L_V2, VIA_H, PAD_HW),
        ('M3', L_M3, L_V3, VIA_H, PAD_HW),
        ('M4', L_M4, L_V4, VIA_H, PAD_HW),
        ('M5', L_M5, L_TV1, TV1_H, TV1_H + TV1_ENC),
        ('TM1', L_TM1, None, None, TM1_HW),
    ]
    started = False
    for i, (name, metal_ly, via_ly, vh, mhw) in enumerate(stack):
        if name == from_layer:
            started = True
        if not started:
            continue
        # Metal pad
        add_rect(cell, metal_ly, cx - mhw, cy - mhw, cx + mhw, cy + mhw)
        shapes.append((metal_ly, sbox(cx - mhw, cy - mhw, cx + mhw, cy + mhw)))
        if name == to_layer:
            break
        # Via to next layer
        if via_ly:
            add_rect(cell, via_ly, cx - vh, cy - vh, cx + vh, cy + vh)
            shapes.append((via_ly, sbox(cx - vh, cy - vh, cx + vh, cy + vh)))
    return shapes


def load_obstacles(cell):
    """Load existing M3/M4/M5 shapes as obstacles."""
    obstacles = {}
    for lk in [L_M2, L_M3, L_M4, L_M5, L_V2, L_V3, L_V4]:
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
    return obstacles


def check_via_stack_collision(cx, cy, obstacles):
    """Check if via stack at (cx,cy) would collide with existing obstacles."""
    spacing = 0.250
    for lk, hw in [(L_M2, PAD_HW), (L_M3, PAD_HW), (L_M4, PAD_HW), (L_M5, TV1_H + TV1_ENC)]:
        shape = sbox(cx - hw, cy - hw, cx + hw, cy + hw)
        obs = obstacles.get(lk)
        if obs and not obs.is_empty:
            if shape.buffer(spacing).intersects(obs):
                return True
    return False


def main():
    print('=== Power Routing v2 ===\n')

    with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
        fp = json.load(f)

    lib = gdstk.read_gds(os.path.join(OUT_DIR, 'soilz_routed.gds'))
    cell = [c for c in lib.cells if c.name == 'tt_um_techhu_analog_trial'][0]
    cell.flatten()

    # Load obstacles from signal routes
    print('Loading obstacles...')
    obstacles = load_obstacles(cell)
    for lk, obs in obstacles.items():
        if obs and not obs.is_empty:
            print(f'  {lk}: obstacle loaded')

    # --- TM1 buses ---
    # c_fb TM1 plate: (133.5, 29.5) to (160.7, 56.7)
    cfb = fp['c_fb']
    cfb_tm1_top = cfb['y'] + cfb['h']   # 56.7
    cfb_tm1_bot = cfb['y']              # 29.5
    cfb_tm1_left = cfb['x']             # 133.5
    cfb_tm1_right = cfb['x'] + cfb['w'] # 160.7

    # Place buses above c_fb TM1 plate
    VDD_Y = cfb_tm1_top + TM1_SP + TM1_HW  # 56.7 + 1.64 + 1.2 = 59.54
    VDD_Y = round(VDD_Y * 2) / 2  # snap to 0.5um grid = 59.5
    GND_Y = VDD_Y + TM1_W + TM1_SP + 0.5  # extra margin for DRC
    GND_Y = round(GND_Y * 2) / 2  # 64.0

    print(f'\n  VDD TM1 bus: y={VDD_Y:.1f}um')
    print(f'  GND TM1 bus: y={GND_Y:.1f}um')

    # Digital TM1 stripes (from GDS probe)
    DIG_VPWR_X1 = 30.5;  DIG_VPWR_X2 = 32.7  # VDD stripe
    DIG_VGND_X1 = 36.7;  DIG_VGND_X2 = 38.9  # GND stripe

    BUS_X1 = 0
    BUS_X2 = 200  # full tile

    # Both buses need to notch BOTH digital stripes (they cross both)
    notch_margin = TM1_SP + 0.1  # 1.74um clearance (DRC needs > 1.64, not >=)

    def make_bus_segments(bus_y):
        """Create TM1 bus segments with notches at both digital stripes."""
        # Sort notch zones by x
        notches = [
            (DIG_VPWR_X1 - notch_margin, DIG_VPWR_X2 + notch_margin),
            (DIG_VGND_X1 - notch_margin, DIG_VGND_X2 + notch_margin),
        ]
        notches.sort()
        segs = []
        x = BUS_X1
        for nx1, nx2 in notches:
            if x < nx1 and (nx1 - x) > TM1_W:  # skip segments narrower than bus width
                segs.append((x, nx1))
            x = max(x, nx2)
        if x < BUS_X2:
            segs.append((x, BUS_X2))
        return segs, notches

    vdd_segs, vdd_notches = make_bus_segments(VDD_Y)
    for x1, x2 in vdd_segs:
        add_rect(cell, L_TM1, x1, VDD_Y - TM1_HW, x2, VDD_Y + TM1_HW)

    gnd_segs, gnd_notches = make_bus_segments(GND_Y)
    for x1, x2 in gnd_segs:
        add_rect(cell, L_TM1, x1, GND_Y - TM1_HW, x2, GND_Y + TM1_HW)

    print(f'  VDD: {len(vdd_segs)} segments, {len(vdd_notches)} notches')
    print(f'  GND: {len(gnd_segs)} segments, {len(gnd_notches)} notches')

    # --- M5 bridges under each notch ---
    tv1_hw = TV1_H
    m5_enc = TV1_H + TV1_ENC

    # M5 bridges connect left/right TM1 segments across digital stripe notches.
    # TopVia1 placed well inside TM1 segments (away from digital stripes).
    for bus_y, segs, label in [(VDD_Y, vdd_segs, 'VDD'), (GND_Y, gnd_segs, 'GND')]:
        if len(segs) >= 2:
            # TopVia1 positions: 3um inside each segment edge facing the gap
            tv1_left_x = segs[0][1] - 3.0   # 3um inside left segment right edge
            tv1_right_x = segs[1][0] + 3.0   # 3um inside right segment left edge
            # M5 bridge spans between the two TopVia1
            add_rect(cell, L_M5, tv1_left_x - m5_enc, bus_y - M5_HW,
                     tv1_right_x + m5_enc, bus_y + M5_HW)
            for bx in [tv1_left_x, tv1_right_x]:
                add_rect(cell, L_TV1, bx - tv1_hw, bus_y - tv1_hw, bx + tv1_hw, bus_y + tv1_hw)
                add_rect(cell, L_M5, bx - m5_enc, bus_y - m5_enc, bx + m5_enc, bus_y + m5_enc)
            print(f'  {label} M5 bridge: TopVia1 at x={tv1_left_x:.1f} and {tv1_right_x:.1f}')

    # --- Via stacks from TM1 down to M2 ---
    # Place at regular intervals, skip if collision with signal routes
    vdd_stacks = 0
    gnd_stacks = 0

    # Digital TM1 exclusion zones (via stack TM1 pad must not be within TM1_SP of stripes)
    tm1_exclusion = [
        (DIG_VPWR_X1 - TM1_SP - TM1_HW, DIG_VPWR_X2 + TM1_SP + TM1_HW),
        (DIG_VGND_X1 - TM1_SP - TM1_HW, DIG_VGND_X2 + TM1_SP + TM1_HW),
    ]

    print(f'\n  Placing via stacks (collision-aware)...')
    for x in range(15, 196, 10):  # every 10um
        x_f = float(x)
        # Skip if TM1 pad would be too close to digital TM1 stripes
        skip_tm1 = any(ex1 < x_f < ex2 for ex1, ex2 in tm1_exclusion)
        if skip_tm1:
            continue
        # VDD via stack
        if not check_via_stack_collision(x_f, VDD_Y, obstacles):
            add_via_stack(cell, x_f, VDD_Y)
            vdd_stacks += 1
        # GND via stack
        if not check_via_stack_collision(x_f, GND_Y, obstacles):
            add_via_stack(cell, x_f, GND_Y)
            gnd_stacks += 1

    print(f'  VDD: {vdd_stacks} via stacks')
    print(f'  GND: {gnd_stacks} via stacks')

    # --- Write output ---
    out_path = os.path.join(OUT_DIR, 'soilz_routed.gds')
    lib.write_gds(out_path)
    print(f'\n  Written to {out_path}')
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
