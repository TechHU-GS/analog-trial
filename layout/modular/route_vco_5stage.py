#!/usr/bin/env python3
"""Route VCO 5-stage ring oscillator. 20 devices, 4 rows × 5 stages.

Row 1 (y=0):   Mnb1-5 (NMOS bias ng=8)
Row 2 (y=4):   Mpd1-5 (NMOS pull-down ng=1)
Row 3 (y=7.5): Mpu1-5 (PMOS pull-up ng=1)
Row 4 (y=12):  Mpb1-5 (PMOS bias ng=8)

Per stage: nbX=Mnb.D+Mpd.S, nsX=Mpb.D+Mpu.S, vcoX=Mpd.D+Mpu.D

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_vco_5stage.py
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
    """Connect strips via M2 verticals to bus at bus_y."""
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
    ly, cell, devs = build_module('vco_5stage', mods['vco_5stage'])
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    # Row boundaries
    r1_top = max(D[f'Mnb{i}']['bbox'][3] for i in range(1,6))
    r2_bot = min(D[f'Mpd{i}']['bbox'][1] for i in range(1,6))
    r2_top = max(D[f'Mpd{i}']['bbox'][3] for i in range(1,6))
    r3_bot = min(D[f'Mpu{i}']['bbox'][1] for i in range(1,6))
    r3_top = max(D[f'Mpu{i}']['bbox'][3] for i in range(1,6))
    r4_bot = min(D[f'Mpb{i}']['bbox'][1] for i in range(1,6))
    r4_top = max(D[f'Mpb{i}']['bbox'][3] for i in range(1,6))
    dev_bot = min(d['bbox'][1] for d in devs)

    g12 = (r1_top + r2_bot) // 2
    g23 = (r2_top + r3_bot) // 2
    g34 = (r3_top + r4_bot) // 2

    print(f'\n--- Routing VCO 5-stage ---')

    # ─── Per-stage routing ───
    for i in range(1, 6):
        mnb = D[f'Mnb{i}']
        mpd = D[f'Mpd{i}']
        mpu = D[f'Mpu{i}']
        mpb = D[f'Mpb{i}']

        # nbX: Mnb.D + Mpd.S (gap12)
        mnb_d = [mnb['strips'][j] for j in range(1, len(mnb['strips']), 2)]
        mpd_s = [mpd['strips'][0]]  # S strip
        nb_y = g12  # same y — stages at different x, no overlap
        m2_connect(cell, ly, l_m2, mnb_d + mpd_s, nb_y)
        # ng=8 extra D strips for Mnb
        for j in range(1, len(mnb_d)):
            add_via1_m2(cell, ly, scx(mnb_d[j]), scy(mnb_d[j]))

        # nsX: Mpb.D + Mpu.S (gap34)
        mpb_d = [mpb['strips'][j] for j in range(1, len(mpb['strips']), 2)]
        mpu_s = [mpu['strips'][0]]
        ns_y = g34  # same y — stages at different x
        m2_connect(cell, ly, l_m2, mpb_d + mpu_s, ns_y)
        for j in range(1, len(mpb_d)):
            add_via1_m2(cell, ly, scx(mpb_d[j]), scy(mpb_d[j]))

        # vcoX: Mpd.D + Mpu.D (gap23)
        mpd_d = [mpd['strips'][-1]]
        mpu_d = [mpu['strips'][-1]]
        vco_y = g23
        m2_connect(cell, ly, l_m2, mpd_d + mpu_d, vco_y)

        print(f'  stage{i}: nb@{nb_y} ns@{ns_y} vco@{vco_y}')

    # ─── Global nets ───

    # nmos_bias: all Mnb gates — poly bridge per device (below Active) + 1 Contact each
    bias_n_y = dev_bot - 500
    all_bias_n_x = []
    for i in range(1, 6):
        gates = D[f'Mnb{i}']['gates']
        if not gates: continue
        # Poly bridge below Active connecting all gate bars
        g_xmin = min(g[0] for g in gates)
        g_xmax = max(g[1] for g in gates)
        g_bot = min(g[2] for g in gates)
        cell.shapes(l_po).insert(box(g_xmin, bias_n_y-250, g_xmax, g_bot))  # bridge
        # Extend each gate bar down to bridge
        for g in gates:
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, bias_n_y-250, gx+gw//2, g[2]))
        # Single Contact + M1 pad on bridge
        bridge_cx = (g_xmin + g_xmax) // 2
        cell.shapes(l_ct).insert(box(bridge_cx-80, bias_n_y-80, bridge_cx+80, bias_n_y+80))
        cell.shapes(l_m1).insert(box(bridge_cx-155, bias_n_y-155, bridge_cx+155, bias_n_y+155))
        all_bias_n_x.append(bridge_cx)
    cell.shapes(l_m1).insert(box(min(all_bias_n_x)-155, bias_n_y-155,
                                 max(all_bias_n_x)+155, bias_n_y+155))
    print(f'  nmos_bias: M1 y={bias_n_y}')

    # pmos_bias: all Mpb gates — poly bridge per device (above Active) + 1 Contact each
    bias_p_y = r4_top + 1500
    all_bias_p_x = []
    for i in range(1, 6):
        gates = D[f'Mpb{i}']['gates']
        if not gates: continue
        g_xmin = min(g[0] for g in gates)
        g_xmax = max(g[1] for g in gates)
        g_top = max(g[3] for g in gates)
        cell.shapes(l_po).insert(box(g_xmin, g_top, g_xmax, bias_p_y+250))
        for g in gates:
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, bias_p_y+250))
        bridge_cx = (g_xmin + g_xmax) // 2
        cell.shapes(l_ct).insert(box(bridge_cx-80, bias_p_y-80, bridge_cx+80, bias_p_y+80))
        cell.shapes(l_m1).insert(box(bridge_cx-155, bias_p_y-155, bridge_cx+155, bias_p_y+155))
        all_bias_p_x.append(bridge_cx)
    cell.shapes(l_m1).insert(box(min(all_bias_p_x)-155, bias_p_y-155,
                                 max(all_bias_p_x)+155, bias_p_y+155))
    print(f'  pmos_bias: M1 y={bias_p_y}')

    # GND: Mnb S strips
    gnd_y = dev_bot - 1000
    n_xmin = min(d['bbox'][0] for d in devs if d['type']=='nmos')
    n_xmax = max(d['bbox'][2] for d in devs if d['type']=='nmos')
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    print(f'  gnd: M1 y={gnd_y}')

    # VDD: Mpb S strips + ntap
    vdd_y = r4_top + 500
    p_xmin = min(d['bbox'][0] for d in devs if d['type']=='pmos')
    p_xmax = max(d['bbox'][2] for d in devs if d['type']=='pmos')
    cell.shapes(l_m1).insert(box(p_xmin, vdd_y-155, p_xmax, vdd_y+500))
    for i in range(1, 6):
        for j in range(0, len(D[f'Mpb{i}']['strips']), 2):
            s = D[f'Mpb{i}']['strips'][j]
            cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, vdd_y-155))
    print(f'  vdd: M1 y={vdd_y}')

    # Write + DRC
    out = os.path.join(OUT_DIR, 'vco_5stage.gds')
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
