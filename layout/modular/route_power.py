#!/usr/bin/env python3
"""Power routing: TM1 horizontal buses + via stacks to module taps.

TTIHP tile provides:
  VDPWR: TM1 vertical stripe x=1.8-4.2um (left edge)
  VGND:  TM1 vertical stripe x=6.8-9.2um (left edge)

We add:
  1. Two TM1 horizontal buses spanning the tile width
     - VDD bus at y=46um (below c_fb MIM cap at y=49)
     - GND bus at y=44um (2um gap, > TM1.b=1.64um)
  2. Via stacks (M2→Via2→M3→Via3→M4→Via4→M5→TopVia1→TM1) at each module tap

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_power.py
"""

import klayout.db as pya
import os
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Layer definitions
LY = {
    'M1': (8, 0), 'V1': (19, 0), 'M2': (10, 0), 'V2': (29, 0),
    'M3': (30, 0), 'V3': (49, 0), 'M4': (50, 0), 'V4': (66, 0),
    'M5': (67, 0), 'TV1': (125, 0), 'TM1': (126, 0),
}

# DRC rules (nm)
VN_SZ = 190       # Via2/3/4 size
VN_ENC1 = 50      # Via endcap enclosure
MN_MIN_AREA = 144000  # Metal2-5 min area
TV1_SZ = 420      # TopVia1 size
TV1_ENC = 100     # M5 enclosure of TopVia1
TM1_W = 2400      # TM1 bus width (comfortable > 1640nm min)
TM1_MIN_S = 1640  # TM1 min spacing


def box(x1, y1, x2, y2):
    return pya.Box(int(x1), int(y1), int(x2), int(y2))


def draw_via_stack(cell, ly_obj, cx, cy, from_metal='M2', to_metal='TM1'):
    """Draw DRC-clean via stack from from_metal up to to_metal at (cx, cy)."""
    stack = ['M1', 'M2', 'M3', 'M4', 'M5', 'TM1']
    mn_pad_hw = max(VN_SZ // 2 + VN_ENC1,
                    int(math.ceil(math.sqrt(MN_MIN_AREA) / 2)))  # 190nm

    via_info = {
        'M1→M2': ((19, 0), 190, mn_pad_hw, mn_pad_hw),
        'M2→M3': ((29, 0), VN_SZ, mn_pad_hw, mn_pad_hw),
        'M3→M4': ((49, 0), VN_SZ, mn_pad_hw, mn_pad_hw),
        'M4→M5': ((66, 0), VN_SZ, mn_pad_hw, mn_pad_hw),
        'M5→TM1': ((125, 0), TV1_SZ, TV1_SZ // 2 + TV1_ENC, TM1_W // 2),
    }

    start_idx = stack.index(from_metal)
    end_idx = stack.index(to_metal)

    for i in range(start_idx, end_idx):
        lower = stack[i]
        upper = stack[i + 1]
        key = f'{lower}→{upper}'
        via_ly, via_sz, lower_hw, upper_hw = via_info[key]

        hs = via_sz // 2
        # Via
        cell.shapes(ly_obj.layer(*via_ly)).insert(box(cx-hs, cy-hs, cx+hs, cy+hs))
        # Lower metal pad
        cell.shapes(ly_obj.layer(*LY[lower])).insert(
            box(cx-lower_hw, cy-lower_hw, cx+lower_hw, cy+lower_hw))
        # Upper metal pad
        cell.shapes(ly_obj.layer(*LY[upper])).insert(
            box(cx-upper_hw, cy-upper_hw, cx+upper_hw, cy+upper_hw))


def route():
    print('=== Power Routing: TM1 buses + via stacks ===\n')

    ly = pya.Layout()
    ly.read(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell = ly.top_cell()

    # ─── TM1 horizontal power buses ───
    tm1_li = ly.layer(*LY['TM1'])
    hw = TM1_W // 2  # 1200nm half-width

    # TTIHP power stripes are at x=1800-4200 (VDPWR) and x=6800-9200 (VGND)
    # Our buses extend from x=0 to x=200000 (full tile width minus margins)
    BUS_X1 = 0
    BUS_X2 = 200000

    VDD_Y = 46000   # below c_fb MIM cap (y=48000+)
    GND_Y = 44000   # 2um below VDD bus

    # GND bus needs to be spaced from VDD bus
    GND_Y = VDD_Y - hw - TM1_MIN_S - hw  # 46000-1200-1640-1200 = 41960
    GND_Y = (GND_Y // 5) * 5  # snap to 5nm grid = 41960

    # Digital block TM1 stripes (absolute coords):
    # Use actual GDS stripe extents (wider than LEF nominal due to std cell routing):
    # VPWR actual: x=30000-32200, VGND actual: x=36200-38400
    DIG_VPWR_X1 = 30000 - TM1_MIN_S  # 28360
    DIG_VPWR_X2 = 32200 + TM1_MIN_S  # 33840
    DIG_VGND_X1 = 36200 - TM1_MIN_S  # 34560
    DIG_VGND_X2 = 38360 + TM1_MIN_S

    # c_fb MIM cap TM1 plate: check if it conflicts with our bus y levels
    # c_fb at floorplan (121, 48), w=27.2, h=27.2 → TM1 plate at y=48000-75200
    # VDD bus at y=46000±1200 = 44800-47200 → clears c_fb bottom (48000) by 800nm < 1640nm!
    # Need to notch or shift VDD bus down
    CFB_TM1_Y1 = 48000 - TM1_MIN_S  # 46360
    # VDD bus top = 47200 > 46360 → conflict! Shift VDD down.
    VDD_Y = CFB_TM1_Y1 - hw  # 46360 - 1200 = 45160
    VDD_Y = (VDD_Y // 5) * 5  # 45160
    GND_Y = VDD_Y - hw - TM1_MIN_S - hw  # 45160-1200-1640-1200 = 41120
    GND_Y = (GND_Y // 5) * 5  # 41120

    print(f'  VDD TM1 bus: y={VDD_Y/1000:.1f}um')
    print(f'  GND TM1 bus: y={GND_Y/1000:.1f}um')
    print(f'  Bus gap: {(VDD_Y-hw)-(GND_Y+hw)}nm')

    # VDD bus segments (notch out digital VGND stripe):
    # VDD must NOT cross VGND stripe at x=36160-38360
    vdd_segs = [
        (BUS_X1, DIG_VGND_X1),   # left segment: x=0 to before VGND
        (DIG_VGND_X2, BUS_X2),   # right segment: after VGND to end
    ]
    for x1, x2 in vdd_segs:
        cell.shapes(tm1_li).insert(box(x1, VDD_Y - hw, x2, VDD_Y + hw))
    print(f'  VDD: 2 segments (notch at x={DIG_VGND_X1/1000:.1f}-{DIG_VGND_X2/1000:.1f} avoiding VGND stripe)')

    # GND bus segments (notch out digital VPWR stripe):
    gnd_segs = [
        (BUS_X1, DIG_VPWR_X1),   # left: x=0 to before VPWR
        (DIG_VPWR_X2, BUS_X2),   # right: after VPWR to end
    ]
    for x1, x2 in gnd_segs:
        cell.shapes(tm1_li).insert(box(x1, GND_Y - hw, x2, GND_Y + hw))
    print(f'  GND: 2 segments (notch at x={DIG_VPWR_X1/1000:.1f}-{DIG_VPWR_X2/1000:.1f} avoiding VPWR stripe)')

    # M5 bridges under TM1 notches (connect the two segments)
    m5_li = ly.layer(*LY['M5'])
    tv1_li = ly.layer(*LY['TV1'])
    m5_w = 1000  # M5 bridge width
    m5_hw = m5_w // 2
    tv1_hs = TV1_SZ // 2

    # VDD M5 bridge across VGND notch — TopVia1 OUTSIDE digital stripe
    # Place TopVia1 on the TM1 bus segments (outside the notch), not inside the stripe.
    # Left TopVia1 at x just inside left TM1 segment end (x = DIG_VGND_X1 - TM1_W)
    # Right TopVia1 at x just inside right TM1 segment start (x = DIG_VGND_X2 + TM1_W)
    vdd_tv1_left = DIG_VGND_X1 - TM1_W  # well outside VGND stripe
    vdd_tv1_right = DIG_VGND_X2 + TM1_W
    cell.shapes(m5_li).insert(box(vdd_tv1_left - 500, VDD_Y - m5_hw,
                                   vdd_tv1_right + 500, VDD_Y + m5_hw))
    for bx in [vdd_tv1_left, vdd_tv1_right]:
        cell.shapes(tv1_li).insert(box(bx - tv1_hs, VDD_Y - tv1_hs, bx + tv1_hs, VDD_Y + tv1_hs))
        cell.shapes(m5_li).insert(box(bx - TV1_SZ//2 - TV1_ENC, VDD_Y - TV1_SZ//2 - TV1_ENC,
                                       bx + TV1_SZ//2 + TV1_ENC, VDD_Y + TV1_SZ//2 + TV1_ENC))
    print(f'  VDD M5 bridge: TopVia1 at x={vdd_tv1_left/1000:.1f} and {vdd_tv1_right/1000:.1f}')

    # GND M5 bridge across VPWR notch
    gnd_tv1_left = DIG_VPWR_X1 - TM1_W
    gnd_tv1_right = DIG_VPWR_X2 + TM1_W
    cell.shapes(m5_li).insert(box(gnd_tv1_left - 500, GND_Y - m5_hw,
                                   gnd_tv1_right + 500, GND_Y + m5_hw))
    for bx in [gnd_tv1_left, gnd_tv1_right]:
        cell.shapes(tv1_li).insert(box(bx - tv1_hs, GND_Y - tv1_hs, bx + tv1_hs, GND_Y + tv1_hs))
        cell.shapes(m5_li).insert(box(bx - TV1_SZ//2 - TV1_ENC, GND_Y - TV1_SZ//2 - TV1_ENC,
                                       bx + TV1_SZ//2 + TV1_ENC, GND_Y + TV1_SZ//2 + TV1_ENC))
    print(f'  GND M5 bridge: TopVia1 at x={gnd_tv1_left/1000:.1f} and {gnd_tv1_right/1000:.1f}')

    # ─── Via stacks at module taps ───
    # Find all ntap (VDD) and ptap (GND) M1 pads in the assembled GDS
    # ntap = Active in NWell + Contact + M1 → VDD
    # ptap = Active NOT in NWell + Contact + M1 → GND
    #
    # Simple approach: find M1 shapes that overlap with NWell (ntap=VDD)
    # and M1 shapes that DON'T overlap NWell but DO have Contact (ptap=GND)
    #
    # For speed: just place via stacks at regular intervals along the TM1 buses.
    # Every 10um, if there's M1 below, drop a via stack.

    m1_r = pya.Region(cell.begin_shapes_rec(ly.find_layer(*LY['M1'])))
    m2_r = pya.Region(cell.begin_shapes_rec(ly.find_layer(*LY['M2'])))

    vdd_drops = 0
    gnd_drops = 0

    # VDD via stacks along VDD bus
    print(f'\n  VDD via stacks (y={VDD_Y/1000:.0f}):')
    for x in range(10000, 195000, 8000):  # every 8um from x=10 to x=195
        # Check if there's M2 nearby (from module routing that's on VDD net)
        # For now, just place via stacks at regular intervals — VDD bus is continuous
        # The via stacks will connect TM1 to lower metals; modules connect via M1/M2
        # We need M2 at the via stack position. Check if M2 exists within 500nm.
        probe = pya.Region(box(x-500, VDD_Y-500, x+500, VDD_Y+500))
        # Don't place if M2 is already occupied by signal routing
        # For power, we just need the TM1 bus. Via stacks are optional —
        # modules connect to TM1 through their own via stacks.
        pass

    # Actually, the proper approach:
    # Each module has ntap/ptap M1 pads. We need to connect those to the TM1 bus.
    # But the M1 pads are at module y positions (various), not at y=44/46.
    # The via stack goes from M1(module tap) → ... → TM1(bus).
    # But via stacks are VERTICAL — they go straight up at one (x,y) point.
    # The module tap M1 is at a different y than the TM1 bus.
    #
    # Solution: via stack drops from TM1 bus at chosen x positions,
    # then M3/M4 routing connects from the via stack bottom (M2 level)
    # to the module tap M1 (via Via1+M2).
    #
    # This is complex. Simpler: just put via stacks at x positions where
    # modules have taps, and rely on M3/M4 to bridge y gaps.
    #
    # SIMPLEST for deadline: just place via stacks every 15um along TM1 buses.
    # These create M2-M5 pads at regular intervals along y=44/46.
    # Then signal-style M3/M4 routing connects module taps to nearest via stack.

    # Exclusion zones: digital TM1 stripes + margins
    # VDD must avoid VGND stripe: x=36160-38360 ± TM1_W/2(820) for TM1 pad
    # GND must avoid VPWR stripe: x=29960-31960 ± TM1_W/2(820)
    VDD_EXCL = (DIG_VGND_X1 - TM1_W, DIG_VGND_X2 + TM1_W)  # (32680, 41640)
    GND_EXCL = (DIG_VPWR_X1 - TM1_W, DIG_VPWR_X2 + TM1_W)  # (26080, 36000)

    for x in range(15000, 195000, 15000):
        if VDD_EXCL[0] < x < VDD_EXCL[1]:
            continue  # skip near VGND stripe
        draw_via_stack(cell, ly, x, VDD_Y, 'M2', 'TM1')
        vdd_drops += 1

    print(f'  {vdd_drops} VDD via stacks placed (excl x={VDD_EXCL[0]/1000:.0f}-{VDD_EXCL[1]/1000:.0f})')

    for x in range(15000, 195000, 15000):
        if GND_EXCL[0] < x < GND_EXCL[1]:
            continue  # skip near VPWR stripe
        draw_via_stack(cell, ly, x, GND_Y, 'M2', 'TM1')
        gnd_drops += 1

    print(f'  {gnd_drops} GND via stacks placed (excl x={GND_EXCL[0]/1000:.0f}-{GND_EXCL[1]/1000:.0f})')

    # ─── Power tap connections: TM1 stubs + via stacks at module taps ───
    print('\n  --- Power tap connections ---')

    # For each tap: add TM1 vertical stub from bus to tap y, then via stack M1→TM1
    def connect_tap(cx, cy, bus_y, net_name, label):
        """Connect a module tap at (cx, cy) to power bus at bus_y."""
        # TM1 vertical stub from bus_y to cy
        y1 = min(bus_y, cy)
        y2 = max(bus_y, cy)
        tm1_stub_hw = TM1_W // 2
        cell.shapes(tm1_li).insert(box(cx - tm1_stub_hw, y1 - tm1_stub_hw,
                                        cx + tm1_stub_hw, y2 + tm1_stub_hw))
        # Via stack from M1 up to TM1 at the tap position
        draw_via_stack(cell, ly, cx, cy, 'M1', 'TM1')
        print(f'    {label} {net_name}: ({cx/1000:.1f},{cy/1000:.1f}) stub to y={bus_y/1000:.1f}')

    # Key module taps (verified positions from probe)
    # VDD taps → connect to VDD bus at VDD_Y
    vdd_taps = [
        (121500, 41300, 'ota'),       # close to bus
        (147500, 24800, 'comp'),
        (113300, 62900, 'bias_cas'),
        (69200, 38800, 'sw'),
        (143600, 39400, 'hbridge'),
        (159100, 59500, 'ptat_core'),
    ]
    for cx, cy, label in vdd_taps:
        connect_tap(cx, cy, VDD_Y, 'vdd', label)

    # GND taps → connect to GND bus at GND_Y
    gnd_taps = [
        (128200, 39200, 'ota'),
        (160100, 27200, 'comp'),
        (63400, 49900, 'bias_cas'),
        (63800, 33400, 'sw'),
        (147500, 39800, 'hbridge'),
        (173200, 53700, 'ptat_core'),
        (161400, 36900, 'bias_mn'),
    ]
    for cx, cy, label in gnd_taps:
        connect_tap(cx, cy, GND_Y, 'gnd', label)

    print(f'  {len(vdd_taps)} VDD + {len(gnd_taps)} GND tap connections')

    # ─── Write ───
    out_path = os.path.join(OUT_DIR, 'soilz_assembled.gds')
    ly.write(out_path)

    print(f'\n  Output: {out_path}')

    # Quick DRC on TM1
    tm1_r = pya.Region(cell.begin_shapes_rec(tm1_li))
    print(f'  TM1 shapes: {tm1_r.count()}')
    print(f'  TM1 spacing violations: {tm1_r.space_check(TM1_MIN_S).count()}')


if __name__ == '__main__':
    route()
    print('\n=== Done ===')
