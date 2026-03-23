#!/usr/bin/env python3
"""Route PTAT core: 7 devices, MN2 ng=8.

Strategy (from vco_5stage pattern):
  D strips → M2 (m2_connect), S strips → M1, Gates → M2 (different y)
  S and D on DIFFERENT LAYERS so they don't cross.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_ptat_core.py
"""
import klayout.db as pya
import os, sys, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from build_module import build_module, box

OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
M1, M2, VIA1, CONT, POLY = (8,0), (10,0), (19,0), (6,0), (5,0)

def add_via1_m2(cell, ly, cx, cy):
    cell.shapes(ly.layer(*M1)).insert(box(cx-155, cy-155, cx+155, cy+155))
    cell.shapes(ly.layer(*VIA1)).insert(box(cx-95, cy-95, cx+95, cy+95))
    cell.shapes(ly.layer(*M2)).insert(box(cx-245, cy-155, cx+245, cy+155))

def scx(s): return (s[0]+s[1])//2
def scy(s): return (s[2]+s[3])//2

def m2_connect(cell, ly, l_m2, strips, bus_y):
    for s in strips:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),bus_y)-155,
                                     scx(s)+150, max(scy(s),bus_y)+155))
    if strips:
        cell.shapes(l_m2).insert(box(min(scx(s) for s in strips)-150, bus_y-155,
                                     max(scx(s) for s in strips)+150, bus_y+155))

def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('ptat_core', mods['ptat_core'])
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    nmos_top = max(D[n]['bbox'][3] for n in ['MN1','MN2'])
    pmos_bot = min(D[n]['bbox'][1] for n in ['PM3','PM4'])
    gap_mid = (nmos_top + pmos_bot) // 2
    dev_bot = min(d['bbox'][1] for d in devs)
    dev_top = max(d['bbox'][3] for d in devs)

    print(f'\n--- Routing PTAT core ---')
    print(f'  gap: nmos_top={nmos_top} pmos_bot={pmos_bot} mid={gap_mid}')

    # ─── 1. pmos_bias: PM_pdiode diode D↔G (M1 bridge) ───
    pd = D['PM_pdiode']['strips'][-1]
    pg = D['PM_pdiode']['gates'][0]
    pgx = (pg[0]+pg[1])//2
    cell.shapes(l_ct).insert(box(pgx-80, scy(pd)-80, pgx+80, scy(pd)+80))
    cell.shapes(l_m1).insert(box(min(scx(pd),pgx)-155, scy(pd)-155,
                                 max(scx(pd),pgx)+155, scy(pd)+155))
    print(f'  pmos_bias: diode at ({pgx/1000:.1f},{scy(pd)/1000:.1f})')

    # ─── 2. MN1 diode D↔G (M1 bridge + Contact) ───
    mn1_d = D['MN1']['strips'][-1]
    mn1_g = D['MN1']['gates'][0]
    mn1_gx = (mn1_g[0]+mn1_g[1])//2
    cell.shapes(l_ct).insert(box(mn1_gx-80, scy(mn1_d)-80, mn1_gx+80, scy(mn1_d)+80))
    cell.shapes(l_m1).insert(box(min(scx(mn1_d),mn1_gx)-155, scy(mn1_d)-155,
                                 max(scx(mn1_d),mn1_gx)+155, scy(mn1_d)+155))

    # ─── 3. net_c2: MN2 D strips → M2 bus (m2_connect pattern) ───
    mn2_d = [D['MN2']['strips'][i] for i in range(1, len(D['MN2']['strips']), 2)]
    c2_bus_y = gap_mid - 1000  # M2 bus in lower part of gap
    m2_connect(cell, ly, l_m2, mn2_d, c2_bus_y)
    # PM4.D also on net_c2
    pm4_d = D['PM4']['strips'][-1]
    add_via1_m2(cell, ly, scx(pm4_d), scy(pm4_d))
    cell.shapes(l_m2).insert(box(scx(pm4_d)-150, min(scy(pm4_d),c2_bus_y)-155,
                                 scx(pm4_d)+150, max(scy(pm4_d),c2_bus_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(mn2_d[-1]),scx(pm4_d))-150, c2_bus_y-155,
                                 max(scx(mn2_d[-1]),scx(pm4_d))+150, c2_bus_y+155))
    print(f'  net_c2: M2 y={c2_bus_y}')

    # ─── 4. net_c1: MN2 gates → M2 bus (different y from c2) ───
    mn2_gate_y = gap_mid  # M2 bus in middle of gap
    mn2_gate_xs = []
    for g in D['MN2']['gates']:
        gx = (g[0]+g[1])//2; gw = g[1]-g[0]
        cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, mn2_gate_y+150))
        cell.shapes(l_ct).insert(box(gx-80, mn2_gate_y-80, gx+80, mn2_gate_y+80))
        add_via1_m2(cell, ly, gx, mn2_gate_y)
        mn2_gate_xs.append(gx)
    # MN1 diode → Via1+M2 → gate bus
    add_via1_m2(cell, ly, scx(mn1_d), scy(mn1_d))
    cell.shapes(l_m2).insert(box(scx(mn1_d)-150, min(scy(mn1_d),mn2_gate_y)-155,
                                 scx(mn1_d)+150, max(scy(mn1_d),mn2_gate_y)+155))
    # PM3 diode + PM4/5/ref gates: M1 bus in PM area
    pm3_d = D['PM3']['strips'][-1]
    pm3_g = D['PM3']['gates'][0]
    pm3_gx = (pm3_g[0]+pm3_g[1])//2
    pm3_gw = pm3_g[1] - pm3_g[0]
    pm_gate_y = pmos_bot - 300  # M1 bus below PM devices
    # PM3 gate contact + diode
    cell.shapes(l_po).insert(box(pm3_gx-pm3_gw//2, pm_gate_y-150, pm3_gx+pm3_gw//2, pm3_g[2]))
    cell.shapes(l_ct).insert(box(pm3_gx-80, pm_gate_y-80, pm3_gx+80, pm_gate_y+80))
    cell.shapes(l_m1).insert(box(pm3_gx-155, pm_gate_y-155, pm3_gx+155, pm_gate_y+155))
    # PM3 diode D↔G via M1
    cell.shapes(l_m1).insert(box(min(scx(pm3_d),pm3_gx)-155, pm_gate_y-155,
                                 max(scx(pm3_d),pm3_gx)+155, pm_gate_y+155))
    cell.shapes(l_m1).insert(box(scx(pm3_d)-80, pm_gate_y+155, scx(pm3_d)+80, scy(pm3_d)))
    # PM4/5/ref gate contacts on same M1 bus
    pm_gate_xs = [pm3_gx]
    for pname in ['PM4', 'PM5', 'PM_ref']:
        pg_i = D[pname]['gates'][0]
        pgx_i = (pg_i[0]+pg_i[1])//2; pgw_i = pg_i[1]-pg_i[0]
        cell.shapes(l_po).insert(box(pgx_i-pgw_i//2, pm_gate_y-150, pgx_i+pgw_i//2, pg_i[2]))
        cell.shapes(l_ct).insert(box(pgx_i-80, pm_gate_y-80, pgx_i+80, pm_gate_y+80))
        cell.shapes(l_m1).insert(box(pgx_i-155, pm_gate_y-155, pgx_i+155, pm_gate_y+155))
        pm_gate_xs.append(pgx_i)
    cell.shapes(l_m1).insert(box(min(pm_gate_xs)-155, pm_gate_y-155,
                                 max(pm_gate_xs)+155, pm_gate_y+155))
    # Connect PM M1 bus to gate M2 bus via Via1 at PM3 x (outside c2 M2 x range)
    add_via1_m2(cell, ly, pm3_gx, pm_gate_y)
    cell.shapes(l_m2).insert(box(pm3_gx-150, min(pm_gate_y,mn2_gate_y)-155,
                                 pm3_gx+150, max(pm_gate_y,mn2_gate_y)+155))
    # Gate M2 bus spans MN2 gates + MN1 + PM3
    all_c1_x = mn2_gate_xs + [scx(mn1_d), pm3_gx]
    cell.shapes(l_m2).insert(box(min(all_c1_x)-150, mn2_gate_y-155,
                                 max(all_c1_x)+150, mn2_gate_y+155))
    print(f'  net_c1: M2 gate_bus y={mn2_gate_y}, PM M1 y={pm_gate_y}')

    # ─── 5. net_rptat: MN2 S strips → M1 (NOT M2!) ───
    # M1 stubs UP from S strips to M1 bus above device
    # M1 passes through M2 area harmlessly (different layer)
    mn2_s = [D['MN2']['strips'][i] for i in range(0, len(D['MN2']['strips']), 2)]
    rptat_y = gap_mid + 1000  # M1 bus in upper part of gap
    for s in mn2_s:
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, rptat_y+155))
    cell.shapes(l_m1).insert(box(min(scx(s) for s in mn2_s)-155, rptat_y-155,
                                 max(scx(s) for s in mn2_s)+155, rptat_y+155))
    print(f'  net_rptat: M1 y={rptat_y}')

    # ─── 6. GND: MN1.S ───
    gnd_y = dev_bot - 1500
    n_xmin = min(d['bbox'][0] for d in devs if d['type']=='nmos')
    n_xmax = max(d['bbox'][2] for d in devs if d['type']=='nmos')
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    mn1_s = D['MN1']['strips'][0]
    cell.shapes(l_m1).insert(box(scx(mn1_s)-80, gnd_y+155, scx(mn1_s)+80, mn1_s[2]))
    print(f'  gnd: M1 y={gnd_y}')

    # ─── 7. VDD: PM S strips ───
    vdd_y = dev_top + 500
    p_xmin = min(d['bbox'][0] for d in devs if d['type']=='pmos')
    p_xmax = max(d['bbox'][2] for d in devs if d['type']=='pmos')
    cell.shapes(l_m1).insert(box(p_xmin, vdd_y-155, p_xmax, vdd_y+500))
    for pname in ['PM3', 'PM4', 'PM5', 'PM_ref', 'PM_pdiode']:
        s = D[pname]['strips'][0]
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, vdd_y-155))
    print(f'  vdd: M1 y={vdd_y}')

    # ─── Write + DRC ───
    out = os.path.join(OUT_DIR, 'ptat_core.gds')
    ly.write(out)
    bb = cell.bbox()
    print(f'\n  Size: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')
    flat = ly.create_cell('_d'); flat.copy_tree(cell); flat.flatten(True)
    m1r = pya.Region(flat.begin_shapes_rec(ly.find_layer(*M1)))
    m2r = pya.Region(flat.begin_shapes_rec(ly.find_layer(*M2)))
    print(f'  Quick DRC: M1.b={m1r.space_check(180).count()} M1.a={m1r.width_check(160).count()}'
          f' M2.b={m2r.space_check(210).count()} M2.a={m2r.width_check(210).count()}')
    flat.delete()

if __name__ == '__main__':
    route()
    print('\n=== Done ===')
