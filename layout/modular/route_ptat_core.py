#!/usr/bin/env python3
"""Route PTAT core: 7 devices, MN2 ng=8.

Row 0 (y=0):    PM_pdiode (pmos diode)
Row 1 (y=7):    MN1 (ng=1) + MN2 (ng=8)
Row 2 (y=11.5): PM3 + PM4
Row 3 (y=13.5): PM5 + PM_ref

Nets:
  net_c1:    MN1.D/G + MN2.G + PM3.D/G + PM4.G + PM5.G + PM_ref.G
  net_c2:    MN2.D + PM4.D
  net_rptat: MN2.S (external)
  vptat:     PM5.D (external)
  nmos_bias: PM_ref.D (external)
  pmos_bias: PM_pdiode.D/G (diode, external)
  gnd:       MN1.S
  vdd:       PM S strips

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

def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('ptat_core', mods['ptat_core'], ptap_offset=2500)
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    # Key y positions
    nmos_top = max(D[n]['bbox'][3] for n in ['MN1','MN2'])
    pmos_bot = min(D[n]['bbox'][1] for n in ['PM3','PM4'])
    gap_mid = (nmos_top + pmos_bot) // 2  # ~10430
    dev_bot = min(d['bbox'][1] for d in devs)
    dev_top = max(d['bbox'][3] for d in devs)

    print(f'\n--- Routing PTAT core ---')
    print(f'  gap: nmos_top={nmos_top} pmos_bot={pmos_bot} mid={gap_mid}')

    # ─── 1. pmos_bias: PM_pdiode diode (D=G) ───
    pd = D['PM_pdiode']['strips'][-1]  # D strip
    pg = D['PM_pdiode']['gates'][0]
    pgx = (pg[0]+pg[1])//2
    # Contact on gate, M1 bridge D↔G
    cell.shapes(l_ct).insert(box(pgx-80, scy(pd)-80, pgx+80, scy(pd)+80))
    cell.shapes(l_m1).insert(box(min(scx(pd),pgx)-155, scy(pd)-155,
                                 max(scx(pd),pgx)+155, scy(pd)+155))
    print(f'  pmos_bias: PM_pdiode diode at ({pgx},{scy(pd)})')

    # ─── 2. MN1 diode (net_c1 local) ───
    mn1_d = D['MN1']['strips'][-1]
    mn1_g = D['MN1']['gates'][0]
    mn1_gx = (mn1_g[0]+mn1_g[1])//2
    cell.shapes(l_ct).insert(box(mn1_gx-80, scy(mn1_d)-80, mn1_gx+80, scy(mn1_d)+80))
    cell.shapes(l_m1).insert(box(min(scx(mn1_d),mn1_gx)-155, scy(mn1_d)-155,
                                 max(scx(mn1_d),mn1_gx)+155, scy(mn1_d)+155))
    print(f'  MN1 diode: at ({mn1_gx},{scy(mn1_d)})')

    # ─── 3. MN2 gates (net_c1): individual contacts above Active ───
    mn2_gate_y = nmos_top + 500  # above MN2 Active, below gap mid
    mn2_gate_xs = []
    for g in D['MN2']['gates']:
        gx = (g[0]+g[1])//2; gw = g[1]-g[0]
        cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, mn2_gate_y+150))
        cell.shapes(l_ct).insert(box(gx-80, mn2_gate_y-80, gx+80, mn2_gate_y+80))
        add_via1_m2(cell, ly, gx, mn2_gate_y)
        mn2_gate_xs.append(gx)
    # M2 bus connecting all MN2 gate Via1s
    cell.shapes(l_m2).insert(box(min(mn2_gate_xs)-150, mn2_gate_y-155,
                                 max(mn2_gate_xs)+150, mn2_gate_y+155))
    print(f'  MN2 gates: M2 y={mn2_gate_y} ({len(mn2_gate_xs)} contacts)')

    # ─── 4. PM3 diode (net_c1 local) ───
    pm3_d = D['PM3']['strips'][-1]
    pm3_g = D['PM3']['gates'][0]
    pm3_gx = (pm3_g[0]+pm3_g[1])//2
    # Gate contact below PM3 Active
    pm3_cont_y = D['PM3']['bbox'][1] - 300
    pm3_gw = pm3_g[1] - pm3_g[0]
    cell.shapes(l_po).insert(box(pm3_gx-pm3_gw//2, pm3_cont_y-150, pm3_gx+pm3_gw//2, pm3_g[2]))
    cell.shapes(l_ct).insert(box(pm3_gx-80, pm3_cont_y-80, pm3_gx+80, pm3_cont_y+80))
    cell.shapes(l_m1).insert(box(pm3_gx-155, pm3_cont_y-155, pm3_gx+155, pm3_cont_y+155))
    # M1 bridge D↔G for diode
    add_via1_m2(cell, ly, scx(pm3_d), scy(pm3_d))
    add_via1_m2(cell, ly, pm3_gx, pm3_cont_y)
    cell.shapes(l_m2).insert(box(min(scx(pm3_d),pm3_gx)-150, min(scy(pm3_d),pm3_cont_y)-155,
                                 max(scx(pm3_d),pm3_gx)+150, max(scy(pm3_d),pm3_cont_y)+155))
    print(f'  PM3 diode: gate at ({pm3_gx},{pm3_cont_y})')

    # ─── 5. PM4/PM5/PM_ref gate contacts (net_c1) ───
    for pname in ['PM4', 'PM5', 'PM_ref']:
        pg = D[pname]['gates'][0]
        pgx = (pg[0]+pg[1])//2; pgw = pg[1]-pg[0]
        cont_y = D[pname]['bbox'][1] - 300
        cell.shapes(l_po).insert(box(pgx-pgw//2, cont_y-150, pgx+pgw//2, pg[2]))
        cell.shapes(l_ct).insert(box(pgx-80, cont_y-80, pgx+80, cont_y+80))
        cell.shapes(l_m1).insert(box(pgx-155, cont_y-155, pgx+155, cont_y+155))

    # ─── 6. net_c1 global bus: connect MN1 diode + MN2 gates + PM3 diode + PM4/5/ref gates ───
    # Use M2 at mn2_gate_y level (already has MN2 gates)
    # Add Via1 for MN1 diode → M2
    add_via1_m2(cell, ly, scx(mn1_d), scy(mn1_d))
    # M2 vertical from MN1 to mn2_gate_y
    cell.shapes(l_m2).insert(box(scx(mn1_d)-150, min(scy(mn1_d), mn2_gate_y)-155,
                                 scx(mn1_d)+150, max(scy(mn1_d), mn2_gate_y)+155))
    # Connect PM gate contacts to net_c1 via M2
    # PM3 already has Via1 from diode connection
    # PM4 gate: Via1 + M2 vertical to mn2_gate_y
    for pname in ['PM4', 'PM5', 'PM_ref']:
        pg = D[pname]['gates'][0]
        pgx = (pg[0]+pg[1])//2
        cont_y = D[pname]['bbox'][1] - 300
        add_via1_m2(cell, ly, pgx, cont_y)
        cell.shapes(l_m2).insert(box(pgx-150, min(cont_y, mn2_gate_y)-155,
                                     pgx+150, max(cont_y, mn2_gate_y)+155))
    # Extend MN2 gate M2 bus to cover PM3 and PM4/ref gate Via1 positions
    all_c1_x = mn2_gate_xs + [scx(mn1_d), pm3_gx,
                               (D['PM4']['gates'][0][0]+D['PM4']['gates'][0][1])//2,
                               (D['PM5']['gates'][0][0]+D['PM5']['gates'][0][1])//2,
                               (D['PM_ref']['gates'][0][0]+D['PM_ref']['gates'][0][1])//2]
    cell.shapes(l_m2).insert(box(min(all_c1_x)-150, mn2_gate_y-155,
                                 max(all_c1_x)+150, mn2_gate_y+155))
    print(f'  net_c1: M2 bus y={mn2_gate_y}, x={min(all_c1_x)/1000:.1f}-{max(all_c1_x)/1000:.1f}')

    # ─── 7. net_c2: MN2.D + PM4.D ───
    # ALL M1 — no M2 vertical crossing other M2 buses
    mn2_d = [D['MN2']['strips'][i] for i in range(1, len(D['MN2']['strips']), 2)]
    pm4_d = D['PM4']['strips'][-1]
    c2_m1_y = nmos_top + 200
    # M1 stubs from D strips to M1 bus
    for s in mn2_d:
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, c2_m1_y+155))
    cell.shapes(l_m1).insert(box(min(scx(s) for s in mn2_d)-155, c2_m1_y-155,
                                 max(scx(s) for s in mn2_d)+155, c2_m1_y+155))
    # M1 vertical from rightmost D strip bus to PM4.D level
    rd = mn2_d[-1]
    pm4_d_y = scy(pm4_d)
    cell.shapes(l_m1).insert(box(scx(rd)-80, c2_m1_y+155, scx(rd)+80, pm4_d_y))
    # M1 horizontal to PM4.D strip
    cell.shapes(l_m1).insert(box(min(scx(rd),scx(pm4_d))-155, pm4_d_y-155,
                                 max(scx(rd),scx(pm4_d))+155, pm4_d_y+155))
    print(f'  net_c2: M1 only, y={c2_m1_y}')

    # ─── 7b. net_rptat: MN2 S strips — M1 below MN2, no M2 (avoid gate M2 crossing) ───
    mn2_s = [D['MN2']['strips'][i] for i in range(0, len(D['MN2']['strips']), 2)]
    rptat_y = D['MN2']['bbox'][1] - 500  # below MN2 (7000), above ptap (5500)
    n_xmin_all = min(d['bbox'][0] for d in devs if d['type']=='nmos')
    n_xmax_all = max(d['bbox'][2] for d in devs if d['type']=='nmos')
    ptap_edges_ptat = [(n_xmin_all + k*10000, n_xmin_all + k*10000 + 500)
                       for k in range(int((n_xmax_all - n_xmin_all) / 10000) + 1)]
    for s in mn2_s:
        sx = scx(s)
        sl, sr = sx - 80, sx + 80
        for pl, pr in ptap_edges_ptat:
            if 0 < sl - pr < 180: sl = pl
            elif 0 < pl - sr < 180: sr = pr
        cell.shapes(l_m1).insert(box(sl, rptat_y-155, sr, s[2]))
    cell.shapes(l_m1).insert(box(min(scx(s) for s in mn2_s)-155, rptat_y-155,
                                 max(scx(s) for s in mn2_s)+155, rptat_y+155))
    print(f'  net_rptat: M1 y={rptat_y}')

    # ─── 8. GND: MN1.S ───
    gnd_y = dev_bot - 1000
    n_xmin = min(d['bbox'][0] for d in devs if d['type']=='nmos')
    n_xmax = max(d['bbox'][2] for d in devs if d['type']=='nmos')
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+500))
    # MN1 S strip to GND
    mn1_s = D['MN1']['strips'][0]
    cell.shapes(l_m1).insert(box(scx(mn1_s)-80, gnd_y+500, scx(mn1_s)+80, mn1_s[2]))
    # MN2 S strips to GND (net_rptat — NOT GND! MN2.S = net_rptat)
    # Only MN1.S connects to GND
    print(f'  gnd: M1 y={gnd_y}')

    # ─── 9. VDD: PM S strips ───
    vdd_y = dev_top + 500
    p_xmin = min(d['bbox'][0] for d in devs if d['type']=='pmos')
    p_xmax = max(d['bbox'][2] for d in devs if d['type']=='pmos')
    cell.shapes(l_m1).insert(box(p_xmin, vdd_y-155, p_xmax, vdd_y+500))
    for pname in ['PM3', 'PM4', 'PM5', 'PM_ref']:
        s = D[pname]['strips'][0]  # S strip
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, vdd_y-155))
    # PM_pdiode VDD: use M2 (M1 stub would cross ptap at y=6.2)
    ppd_s = D['PM_pdiode']['strips'][0]
    add_via1_m2(cell, ly, scx(ppd_s), scy(ppd_s))
    cell.shapes(l_m2).insert(box(scx(ppd_s)-150, scy(ppd_s)-155,
                                 scx(ppd_s)+150, vdd_y+155))
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
