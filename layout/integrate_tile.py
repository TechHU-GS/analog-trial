"""TTIHP 26a Analog Tile Integration for ptat_vco.

Wraps the bare ptat_vco layout into a 1x2 tile (202.08 x 313.74 um) with:
  - prBoundary
  - Power stripes (VDPWR/VGND on TopMetal1)
  - Analog pin pads (ua[0]=vco_out, ua[1]=vptat on TopMetal1)
  - Via stacks from M2 signal endpoints up to TopMetal1
  - Digital pin stubs (Metal4, top edge)
  - Pin labels on all ports

Usage:
    klayout -n sg13g2 -zz -r integrate_tile.py
"""

import pya
import os

# ══════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════

CELL_NAME = 'tt_um_techhu_analog_trial'
SUBCELL_NAME = 'ptat_vco'

# Tile dimensions (nm)
TILE_W = 202080
TILE_H = 313740

# ptat_vco placement offset within tile (nm)
# Place so vco_out (local x=65500) lands near ua[0] (x=191040)
# x_offset = 191040 - 65500 = 125540 → round to 125000
# y_offset = 10000 (above bottom analog pins at y=0..2000)
SUBCELL_X = 125000
SUBCELL_Y = 10000

# ── Layer definitions (GDS layer, datatype) ──
LY_M1        = (8, 0)
LY_M1_PIN    = (8, 2)
LY_M1_LABEL  = (8, 1)
LY_M2        = (10, 0)
LY_M2_PIN    = (10, 2)
LY_M2_LABEL  = (10, 1)
LY_V2        = (29, 0)     # Via2: M2↔M3
LY_M3        = (30, 0)
LY_M3_LABEL  = (30, 1)
LY_V3        = (49, 0)     # Via3: M3↔M4
LY_M4        = (50, 0)
LY_M4_PIN    = (50, 2)
LY_M4_LABEL  = (50, 1)
LY_V4        = (66, 0)     # Via4: M4↔M5
LY_M5        = (67, 0)
LY_M5_LABEL  = (67, 1)
LY_TV1       = (125, 0)    # TopVia1: M5↔TopMetal1
LY_TM1       = (126, 0)    # TopMetal1
LY_TM1_PIN   = (126, 2)
LY_TM1_LABEL = (126, 1)
LY_BOUNDARY  = (189, 4)    # prBoundary.boundary

# ── DRC rules (nm) ──
# Via2/3/4 (same rules: via2_4 section)
VN_SZ    = 190      # Vn_a: via size
VN_ENC   = 5        # Vn_c: min metal enclosure (one side)
VN_ENC1  = 50       # Vn_c1: min metal enclosure (opposite side)

# Metal 2-5 (same rules: metal2_5 section)
MN_MIN_W = 200      # Mn_a: min width
MN_MIN_AREA = 144000 # Mn_d: min area (nm²) → pad ≥ 380×380 nm

# TopVia1
TV1_SZ   = 420      # TV1_a: via size
TV1_ENC  = 100      # TV1_c: metal enclosure (M5 side, from DRC)

# TopMetal1
TM1_MIN_W = 1640    # TM1_a: min width
TM1_MIN_S = 1640    # TM1_b: min spacing

# ── Power stripe parameters ──
PWR_STRIPE_W = 2400     # 2.4 um wide (>2.1 um requirement)
PWR_STRIPE_Y0 = 5000    # start 5 um from bottom
PWR_STRIPE_Y1 = 308000  # end 308 um from bottom
VDPWR_X = 3000          # VDPWR center x (3 um from left edge)
VGND_X  = 8000          # VGND center x (8 um from left edge)

# ── Analog pin definitions (from tt_analog_1x2.def) ──
# ua[n] center coordinates and pad size
UA_PINS = {
    0: {'x': 191040, 'y': 1000, 'hw': 875, 'hh': 1000},  # (190165,0)→(191915,2000)
    1: {'x': 166560, 'y': 1000, 'hw': 875, 'hh': 1000},
    2: {'x': 142080, 'y': 1000, 'hw': 875, 'hh': 1000},
    3: {'x': 117600, 'y': 1000, 'hw': 875, 'hh': 1000},
    4: {'x': 93120,  'y': 1000, 'hw': 875, 'hh': 1000},
    5: {'x': 68640,  'y': 1000, 'hw': 875, 'hh': 1000},
    6: {'x': 44160,  'y': 1000, 'hw': 875, 'hh': 1000},
    7: {'x': 19680,  'y': 1000, 'hw': 875, 'hh': 1000},
}

# ptat_vco signal endpoints (local coordinates, from routing.json)
# vco_out: last segment endpoint at (65500, 30600) on M2 (layer_idx=1)
# vptat:   last segment endpoint at (38550, 39350) on M2 (layer_idx=0 → M1 actually)
# Actually from routing.json segments: [x1,y1,x2,y2,layer]
# vco_out: [65500, 29550, 65500, 30600, 1] → M2, endpoint (65500, 30600)
# vptat:   [38550, 40750, 38550, 39350, 0] → M1, connects at (38550, 39350)
# vptat signal also has Rout.PLUS access point which is on M2 via access system
# For via stack, we need M2 landing → use a nearby M2 point or create one

# Signal connection points (global coordinates after subcell placement)
ANALOG_SIGNALS = {
    'ua[0]': {
        'net': 'vco_out',
        'local_x': 65500,   # M2 endpoint in ptat_vco
        'local_y': 30600,
        'start_layer': 'M2',
        'ua_idx': 0,
    },
    'ua[1]': {
        'net': 'vptat',
        'local_x': 38550,   # endpoint in ptat_vco
        'local_y': 40750,   # top of the segment (closer to M2 access)
        'start_layer': 'M1',
        'ua_idx': 1,
    },
}

# ── Digital pin definitions (Metal4, top edge, from DEF) ──
DIGITAL_PINS = [
    # (name, x_center, y_center)
    ('clk',       187200, 313240),
    ('ena',       191040, 313240),
    ('rst_n',     183360, 313240),
    ('ui_in[0]',  179520, 313240),
    ('ui_in[1]',  175680, 313240),
    ('ui_in[2]',  171840, 313240),
    ('ui_in[3]',  168000, 313240),
    ('ui_in[4]',  164160, 313240),
    ('ui_in[5]',  160320, 313240),
    ('ui_in[6]',  156480, 313240),
    ('ui_in[7]',  152640, 313240),
    ('uo_out[0]', 118080, 313240),
    ('uo_out[1]', 114240, 313240),
    ('uo_out[2]', 110400, 313240),
    ('uo_out[3]', 106560, 313240),
    ('uo_out[4]', 102720, 313240),
    ('uo_out[5]', 98880,  313240),
    ('uo_out[6]', 95040,  313240),
    ('uo_out[7]', 91200,  313240),
    ('uio_in[0]', 148800, 313240),
    ('uio_in[1]', 144960, 313240),
    ('uio_in[2]', 141120, 313240),
    ('uio_in[3]', 137280, 313240),
    ('uio_in[4]', 133440, 313240),
    ('uio_in[5]', 129600, 313240),
    ('uio_in[6]', 125760, 313240),
    ('uio_in[7]', 121920, 313240),
    ('uio_out[0]', 87360, 313240),
    ('uio_out[1]', 83520, 313240),
    ('uio_out[2]', 79680, 313240),
    ('uio_out[3]', 75840, 313240),
    ('uio_out[4]', 72000, 313240),
    ('uio_out[5]', 68160, 313240),
    ('uio_out[6]', 64320, 313240),
    ('uio_out[7]', 60480, 313240),
    ('uio_oe[0]', 56640,  313240),
    ('uio_oe[1]', 52800,  313240),
    ('uio_oe[2]', 48960,  313240),
    ('uio_oe[3]', 45120,  313240),
    ('uio_oe[4]', 41280,  313240),
    ('uio_oe[5]', 37440,  313240),
    ('uio_oe[6]', 33600,  313240),
    ('uio_oe[7]', 29760,  313240),
]
DIGITAL_PIN_HW = 150   # half-width of Metal4 pin rectangle
DIGITAL_PIN_HH = 500   # half-height

# ══════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════

def box(x1, y1, x2, y2):
    """Create a KLayout DBox (in nm, using database units)."""
    return pya.Box(x1, y1, x2, y2)


def draw_via_stack(cell, layout, cx, cy, from_metal, to_metal='TM1'):
    """Draw a DRC-clean via stack from from_metal up to to_metal at (cx, cy).

    Supported: M1, M2, M3, M4, M5, TM1
    Draws via + metal pads at each transition.
    """
    # Metal layer sequence
    stack = ['M1', 'M2', 'M3', 'M4', 'M5', 'TM1']
    # Pad half-width must satisfy both enclosure and min area
    import math
    mn_pad_hw = max(VN_SZ // 2 + VN_ENC1,
                    int(math.ceil(math.sqrt(MN_MIN_AREA) / 2)))  # 190 nm
    via_info = {
        # (via_layer, via_sz, lower_pad_hw, upper_pad_hw)
        'M1→M2': (LY_M2, 0, 0, 0),  # skip — Via1 not needed here
        'M2→M3': (LY_V2, VN_SZ, mn_pad_hw, mn_pad_hw),
        'M3→M4': (LY_V3, VN_SZ, mn_pad_hw, mn_pad_hw),
        'M4→M5': (LY_V4, VN_SZ, mn_pad_hw, mn_pad_hw),
        'M5→TM1': (LY_TV1, TV1_SZ, TV1_SZ // 2 + TV1_ENC, TM1_MIN_W // 2),
    }
    metal_layers = {
        'M1': LY_M1, 'M2': LY_M2, 'M3': LY_M3,
        'M4': LY_M4, 'M5': LY_M5, 'TM1': LY_TM1,
    }

    start_idx = stack.index(from_metal)
    end_idx = stack.index(to_metal)

    for i in range(start_idx, end_idx):
        lower = stack[i]
        upper = stack[i + 1]
        key = f'{lower}→{upper}'
        via_ly, via_sz, lower_hw, upper_hw = via_info[key]

        if via_sz == 0:
            continue  # skip non-existent transitions

        hs = via_sz // 2
        # Draw via
        li_via = layout.layer(*via_ly)
        cell.shapes(li_via).insert(box(cx - hs, cy - hs, cx + hs, cy + hs))

        # Draw lower metal pad
        li_lower = layout.layer(*metal_layers[lower])
        cell.shapes(li_lower).insert(box(cx - lower_hw, cy - lower_hw,
                                         cx + lower_hw, cy + lower_hw))

        # Draw upper metal pad
        li_upper = layout.layer(*metal_layers[upper])
        cell.shapes(li_upper).insert(box(cx - upper_hw, cy - upper_hw,
                                         cx + upper_hw, cy + upper_hw))


def add_label(cell, layout, layer_tuple, x, y, text):
    """Add a text label on the given layer at (x, y)."""
    li = layout.layer(*layer_tuple)
    cell.shapes(li).insert(pya.Text(text, pya.Trans(pya.Point(x, y))))


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    subcell_gds = os.path.join(script_dir, 'output', 'ptat_vco.gds')
    output_gds = os.path.join(script_dir, '..', 'gds', CELL_NAME + '.gds')

    layout = pya.Layout()
    layout.dbu = 0.001  # 1 nm database unit

    top = layout.create_cell(CELL_NAME)

    # ═══ 1. prBoundary ═══
    li_bnd = layout.layer(*LY_BOUNDARY)
    top.shapes(li_bnd).insert(box(0, 0, TILE_W, TILE_H))
    print(f'  prBoundary: {TILE_W/1000:.2f} x {TILE_H/1000:.2f} um')

    # ═══ 2. Load and place ptat_vco subcell ═══
    sub_layout = pya.Layout()
    sub_layout.read(subcell_gds)
    sub_top = sub_layout.top_cell()

    # Merge subcell into our layout
    sub_cell = layout.create_cell(SUBCELL_NAME)
    sub_cell.copy_tree(sub_top)

    # Strip invalid layers (PCell artifacts not in TTIHP precheck whitelist)
    INVALID_LAYERS = [(33, 0), (26, 0), (51, 0), (1, 20)]
    for ly, dt in INVALID_LAYERS:
        li_inv = layout.layer(ly, dt)
        for cell_idx in range(layout.cells()):
            c = layout.cell(cell_idx)
            c.shapes(li_inv).clear()
    print(f'  Stripped {len(INVALID_LAYERS)} invalid PCell layers')

    # Place subcell instance
    trans = pya.Trans(pya.Point(SUBCELL_X, SUBCELL_Y))
    top.insert(pya.CellInstArray(sub_cell.cell_index(), trans))
    print(f'  Placed {SUBCELL_NAME} at ({SUBCELL_X/1000:.1f}, {SUBCELL_Y/1000:.1f}) um')

    # ═══ 3. Power stripes on TopMetal1 ═══
    li_tm1 = layout.layer(*LY_TM1)
    hw = PWR_STRIPE_W // 2

    # VDPWR stripe
    top.shapes(li_tm1).insert(box(VDPWR_X - hw, PWR_STRIPE_Y0,
                                   VDPWR_X + hw, PWR_STRIPE_Y1))
    add_label(top, layout, LY_TM1_LABEL, VDPWR_X, (PWR_STRIPE_Y0 + PWR_STRIPE_Y1) // 2, 'VDPWR')

    # VGND stripe
    top.shapes(li_tm1).insert(box(VGND_X - hw, PWR_STRIPE_Y0,
                                   VGND_X + hw, PWR_STRIPE_Y1))
    add_label(top, layout, LY_TM1_LABEL, VGND_X, (PWR_STRIPE_Y0 + PWR_STRIPE_Y1) // 2, 'VGND')

    print(f'  Power stripes: VDPWR@x={VDPWR_X/1000:.1f}um, VGND@x={VGND_X/1000:.1f}um, w={PWR_STRIPE_W/1000:.1f}um')

    # ═══ 4. Power via stacks (TopMetal1 → M3) ═══
    # ptat_vco has M3 power rails; we need to connect TopMetal1 stripes down to them
    # vdd rail is at y≈31.7 um (local) → global y = 31700 + SUBCELL_Y = 41700
    # gnd rail is at y≈14.2 um (local) → global y = 14200 + SUBCELL_Y = 24200
    # The power stripes are at x=3000 and x=8000 — far left of ptat_vco (x=125000)
    # We need M3 horizontal routing from the stripe via stack to the ptat_vco M3 rail
    #
    # Simpler approach: extend ptat_vco's existing M3 power rails leftward to reach
    # the power stripe x positions, then drop via stacks at the intersection.
    #
    # From routing.json, the ptat_vco power rails:
    #   vdd (M3) y≈31700 local → 41700 global, extends from x≈0 to ~67000 local
    #   gnd_0 (M3) y≈14200 local → 24200 global
    #   gnd_1 (M3) y≈45000 local → 55000 global
    #
    # The leftmost extent of ptat_vco is at SUBCELL_X = 125000.
    # We need M3 wires from VDPWR_X (3000) to SUBCELL_X (125000) at the rail y heights.

    # VDD connection: M3 horizontal wire from VDPWR stripe to ptat_vco
    li_m3 = layout.layer(*LY_M3)
    vdd_global_y = 31700 + SUBCELL_Y  # ~41700 nm
    m3_rail_hw = 200  # M3 half-width (400nm rail, >= 200nm min)
    top.shapes(li_m3).insert(box(VDPWR_X - hw, vdd_global_y - m3_rail_hw,
                                  SUBCELL_X + 2000, vdd_global_y + m3_rail_hw))
    # Via stack at VDPWR stripe: M3 → TM1
    draw_via_stack(top, layout, VDPWR_X, vdd_global_y, 'M3', 'TM1')
    print(f'  VDPWR→vdd: via stack at ({VDPWR_X/1000:.1f}, {vdd_global_y/1000:.1f}) um')

    # GND connection: M3 horizontal wire from VGND stripe to ptat_vco
    gnd_global_y = 14200 + SUBCELL_Y  # ~24200 nm
    top.shapes(li_m3).insert(box(VGND_X - hw, gnd_global_y - m3_rail_hw,
                                  SUBCELL_X + 2000, gnd_global_y + m3_rail_hw))
    draw_via_stack(top, layout, VGND_X, gnd_global_y, 'M3', 'TM1')
    print(f'  VGND→gnd: via stack at ({VGND_X/1000:.1f}, {gnd_global_y/1000:.1f}) um')

    # ═══ 5. Analog pin connections (M2 → TopMetal1) ═══
    for ua_name, sig in ANALOG_SIGNALS.items():
        ua_idx = sig['ua_idx']
        ua = UA_PINS[ua_idx]

        # Global coordinates of signal endpoint in ptat_vco
        gx = sig['local_x'] + SUBCELL_X
        gy = sig['local_y'] + SUBCELL_Y

        # Draw via stack at signal endpoint: M2 → TopMetal1
        start = sig['start_layer']
        draw_via_stack(top, layout, gx, gy, start, 'TM1')

        # TopMetal1 routing from via stack to ua pad
        # Route: horizontal on TopMetal1 from (gx, gy) to (ua_x, gy),
        # then vertical from (ua_x, gy) to (ua_x, ua_y)
        ua_x = ua['x']
        ua_y = ua['y']
        tm1_hw = TM1_MIN_W // 2  # 820 nm half-width

        # Horizontal segment on TopMetal1
        x_min = min(gx, ua_x)
        x_max = max(gx, ua_x)
        top.shapes(li_tm1).insert(box(x_min - tm1_hw, gy - tm1_hw,
                                       x_max + tm1_hw, gy + tm1_hw))

        # Vertical segment on TopMetal1 (from gy down to ua_y)
        y_min = min(gy, ua_y)
        y_max = max(gy, ua_y)
        top.shapes(li_tm1).insert(box(ua_x - tm1_hw, y_min - tm1_hw,
                                       ua_x + tm1_hw, y_max + tm1_hw))

        # Analog pin pad (must cover the required rectangle)
        top.shapes(li_tm1).insert(box(ua_x - ua['hw'], ua_y - ua['hh'],
                                       ua_x + ua['hw'], ua_y + ua['hh']))

        # Pin marker on TopMetal1.pin
        li_tm1_pin = layout.layer(*LY_TM1_PIN)
        top.shapes(li_tm1_pin).insert(box(ua_x - ua['hw'], ua_y - ua['hh'],
                                           ua_x + ua['hw'], ua_y + ua['hh']))

        # Label
        add_label(top, layout, LY_TM1_LABEL, ua_x, ua_y, ua_name)

        print(f'  {ua_name} ({sig["net"]}): via@({gx/1000:.1f},{gy/1000:.1f}) → pad@({ua_x/1000:.1f},{ua_y/1000:.1f}) um')

    # ═══ 6. Digital pin stubs (Metal4, top edge) ═══
    li_m4 = layout.layer(*LY_M4)
    li_m4_pin = layout.layer(*LY_M4_PIN)
    for name, cx, cy in DIGITAL_PINS:
        # Metal4 drawing rectangle
        top.shapes(li_m4).insert(box(cx - DIGITAL_PIN_HW, cy - DIGITAL_PIN_HH,
                                      cx + DIGITAL_PIN_HW, cy + DIGITAL_PIN_HH))
        # Metal4 pin marker
        top.shapes(li_m4_pin).insert(box(cx - DIGITAL_PIN_HW, cy - DIGITAL_PIN_HH,
                                          cx + DIGITAL_PIN_HW, cy + DIGITAL_PIN_HH))
        # Label
        add_label(top, layout, LY_M4_LABEL, cx, cy, name)

    print(f'  Digital pins: {len(DIGITAL_PINS)} stubs on Metal4 @ y={313240/1000:.1f} um')

    # ═══ 7. VDPWR/VGND pin markers ═══
    # Pin marker must cover full stripe (precheck: within 10um of top AND bottom)
    li_tm1_pin = layout.layer(*LY_TM1_PIN)
    for name, px in [('VDPWR', VDPWR_X), ('VGND', VGND_X)]:
        top.shapes(li_tm1_pin).insert(box(px - hw, PWR_STRIPE_Y0,
                                           px + hw, PWR_STRIPE_Y1))

    # ═══ 8. Write output ═══
    os.makedirs(os.path.dirname(output_gds), exist_ok=True)
    layout.write(output_gds)
    print(f'\n  Written: {output_gds}')


if __name__ == '__main__':
    main()
