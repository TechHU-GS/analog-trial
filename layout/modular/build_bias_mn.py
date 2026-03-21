#!/usr/bin/env python3
"""Build BIAS MN module with complete routing.

Circuit:
    MN_diode: S=gnd, D=nmos_bias, G=nmos_bias (diode-connected)
    MN_pgen:  S=gnd, G=nmos_bias, D=pmos_bias

Layout (existing bias_mn.gds):
    MN_diode (left):  Activ (0.00,0.18)-(2.68,1.18), S strip x=0.07-0.23, D strip x=2.45-2.61
    MN_pgen  (right): Activ (5.68,0.18)-(8.36,1.18), S strip x=5.75-5.91, D strip x=8.13-8.29
    Ptap ties: left (0-0.50), right (6.0-6.50) at y=-1.50 to -1.00

Routing plan:
    1. GND bus: M1 bar connecting ptap ties + source strip extensions
    2. Gate poly extensions (500nm below active)
    3. Gate contacts + M1 pads
    4. Diode connection: M1 bridge from MN_diode.D to gate contact
    5. nmos_bias M2 route: Via1+M2 connecting MN_diode diode to MN_pgen gate
    6. pmos_bias: MN_pgen.D strip (leave as-is for assembly)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_bias_mn.py
"""

import klayout.db as pya
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Layer definitions (IHP SG13G2)
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
M1 = (8, 0)
M2 = (10, 0)
PSD = (14, 0)
VIA1 = (19, 0)

# DRC rule values (nm)
M1_MIN_W = 160
M1_MIN_S = 180
M2_MIN_W = 210
M2_MIN_S = 210
GAT_D = 70      # poly enclosure of contact
CNT_A = 160     # contact size
CNT_C = 70      # M1 enclosure of contact
VIA1_SIZE = 190  # Via1 size
VIA1_M1_ENC = 60  # M1 enclosure of Via1


def nm(um_val):
    """Convert um to nm (integer for KLayout)."""
    return int(round(um_val * 1000))


def box(x1, y1, x2, y2):
    """Create Box from nm coordinates."""
    return pya.Box(x1, y1, x2, y2)


def build():
    # Load existing bias_mn.gds (has PCells + ties)
    ly = pya.Layout()
    ly.dbu = 0.001
    gds_path = os.path.join(OUT_DIR, 'bias_mn.gds')
    ly.read(gds_path)
    cell = ly.top_cell()

    # Get/create layers
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_via1 = ly.layer(*VIA1)
    l_poly = ly.layer(*GATPOLY)
    l_cont = ly.layer(*CONT)

    print('=== Building BIAS MN routing ===')
    bb = cell.bbox()
    print(f'  Input: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    # ─── Step 1: GND source bus ───
    print('\n--- Step 1: GND source bus ---')

    # M1 GND bar connecting both ptap ties
    cell.shapes(l_m1).insert(box(0, -1500, 6500, -1000))

    # Source strip extensions down to GND bar
    cell.shapes(l_m1).insert(box(70, -1000, 230, 180))     # MN_diode.S
    cell.shapes(l_m1).insert(box(5750, -1000, 5910, 180))  # MN_pgen.S

    print('  GND bar: (0,-1.50)-(6.50,-1.00)')
    print('  Source ext MN_diode: (0.07,-1.00)-(0.23,0.18)')
    print('  Source ext MN_pgen: (5.75,-1.00)-(5.91,0.18)')

    # ─── Step 2: Gate poly extensions ───
    print('\n--- Step 2: Gate poly extensions ---')

    # Extend GatPoly 500nm below existing (existing ends at y=0)
    cell.shapes(l_poly).insert(box(340, -500, 2340, 0))    # MN_diode
    cell.shapes(l_poly).insert(box(6020, -500, 8020, 0))   # MN_pgen

    print('  MN_diode poly ext: (0.34,-0.50)-(2.34,0.00)')
    print('  MN_pgen poly ext: (6.02,-0.50)-(8.02,0.00)')

    # ─── Step 3: Gate contacts + M1 pads ───
    print('\n--- Step 3: Gate contacts + M1 pads ---')

    # MN_diode gate contact (on poly extension, centered)
    # Contact: 160x160nm at center of poly X, y≈-250nm
    cont_d_x = 1240  # center of poly (340+2340)/2 - 80
    cont_d_y = -330
    cell.shapes(l_cont).insert(box(cont_d_x, cont_d_y,
                                   cont_d_x + CNT_A, cont_d_y + CNT_A))
    # M1 pad: 310x310nm, centered on contact
    pad_d_x = cont_d_x - CNT_C  # 1240 - 70 = 1170... let me recalculate
    # Contact: (1240, -330, 1400, -170). M1 pad enclosure 75nm all sides:
    pad_d = box(1240 - 75, -330 - 75, 1400 + 75, -170 + 75)  # (1165,-405,1475,-95)
    cell.shapes(l_m1).insert(pad_d)

    print(f'  MN_diode gate Cont: ({cont_d_x/1000:.3f},{cont_d_y/1000:.3f})')
    print(f'  MN_diode gate M1 pad: {pad_d}')

    # MN_pgen gate contact
    cont_p_x = 6920
    cont_p_y = -330
    cell.shapes(l_cont).insert(box(cont_p_x, cont_p_y,
                                   cont_p_x + CNT_A, cont_p_y + CNT_A))
    pad_p = box(6920 - 75, -330 - 75, 7080 + 75, -170 + 75)  # (6845,-405,7155,-95)
    cell.shapes(l_m1).insert(pad_p)

    print(f'  MN_pgen gate Cont: ({cont_p_x/1000:.3f},{cont_p_y/1000:.3f})')
    print(f'  MN_pgen gate M1 pad: {pad_p}')

    # ─── Step 4: Diode connection (MN_diode.D ↔ G via M1) ───
    print('\n--- Step 4: Diode connection ---')

    # Extend drain strip down and bridge to gate contact pad
    # Drain strip is at (2450, 180)-(2610, 1180)
    # Gate M1 pad is at (1165, -405)-(1475, -95)
    # Bridge: horizontal M1 from gate pad right edge to drain strip, at gate pad Y
    cell.shapes(l_m1).insert(box(1165, -405, 2610, -95))  # horizontal bridge
    cell.shapes(l_m1).insert(box(2450, -95, 2610, 180))   # drain extension to bridge

    print('  M1 bridge: (1.165,-0.405)-(2.610,-0.095)')
    print('  Drain ext: (2.450,-0.095)-(2.610,0.180)')

    # ─── Step 5: nmos_bias M2 route ───
    print('\n--- Step 5: nmos_bias M2 route ---')

    # Via1 on diode bridge (connects to M2)
    # Place at center of bridge, y centered at -250
    via1_d_x = 1900
    via1_d_y = -345
    cell.shapes(l_via1).insert(box(via1_d_x, via1_d_y,
                                   via1_d_x + VIA1_SIZE, via1_d_y + VIA1_SIZE))
    print(f'  Via1 on bridge: ({via1_d_x/1000:.3f},{via1_d_y/1000:.3f})')

    # Via1 on MN_pgen gate pad
    via1_p_x = 6920
    via1_p_y = -345
    cell.shapes(l_via1).insert(box(via1_p_x, via1_p_y,
                                   via1_p_x + VIA1_SIZE, via1_p_y + VIA1_SIZE))
    print(f'  Via1 on MN_pgen gate: ({via1_p_x/1000:.3f},{via1_p_y/1000:.3f})')

    # M2 route connecting both Via1s
    # Via1_1: (1900,-345)-(2090,-155), Via1_2: (6920,-345)-(7110,-155)
    # M2: 300nm wide bar covering both
    m2_y1 = -345 - 55   # 55nm enclosure below Via1
    m2_y2 = -155 + 55   # 55nm enclosure above Via1
    m2_x1 = 1900 - 100  # 100nm enclosure left of Via1_1
    m2_x2 = 7110 + 100  # 100nm enclosure right of Via1_2
    cell.shapes(l_m2).insert(box(m2_x1, m2_y1, m2_x2, m2_y2))

    print(f'  M2 nmos_bias: ({m2_x1/1000:.3f},{m2_y1/1000:.3f})-({m2_x2/1000:.3f},{m2_y2/1000:.3f})')
    print(f'  M2 width: {(m2_y2-m2_y1)/1000:.3f}um')

    # ─── Output ───
    out_path = os.path.join(OUT_DIR, 'bias_mn.gds')
    ly.write(out_path)

    bb = cell.bbox()
    print(f'\n  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')
    print(f'  Written: {out_path}')

    # Quick M1 DRC checks
    li_m1 = ly.find_layer(*M1)
    m1_region = pya.Region(cell.begin_shapes_rec(li_m1))
    m1b = m1_region.space_check(M1_MIN_S)
    m1a = m1_region.width_check(M1_MIN_W)
    print(f'\n  Quick DRC: M1.b(space)={m1b.count()}, M1.a(width)={m1a.count()}')

    li_m2 = ly.find_layer(*M2)
    if li_m2 is not None:
        m2_region = pya.Region(cell.begin_shapes_rec(li_m2))
        m2b = m2_region.space_check(M2_MIN_S)
        m2a = m2_region.width_check(M2_MIN_W)
        print(f'  Quick DRC: M2.b(space)={m2b.count()}, M2.a(width)={m2a.count()}')

    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
