#!/usr/bin/env python3
"""Route chopper: 2 TG for chopper modulation. Same pattern as dac_sw.

TG1: Mchop1n + Mchop1p — sens_p ↔ chop_out
TG2: Mchop2n + Mchop2p — sens_n ↔ chop_out

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_chopper.py
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
    ly, cell, devs = build_module('chopper', mods['chopper'])
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    nmos_top = max(D[n]['bbox'][3] for n in ['Mchop1n','Mchop2n'])
    pmos_top = max(D[n]['bbox'][3] for n in ['Mchop1p','Mchop2p'])
    dev_bot = min(d['bbox'][1] for d in devs)

    print('\n--- Routing chopper ---')

    # 1. chop_out: all S strips via M2 bus above
    s_strips = [D[n]['strips'][0] for n in ['Mchop1n','Mchop1p','Mchop2n','Mchop2p']]
    chop_out_y = pmos_top + 2500
    for s in s_strips:
        cx = scx(s); cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,chop_out_y)-155, cx+150, max(cy,chop_out_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in s_strips)-150, chop_out_y-155,
                                 max(scx(s) for s in s_strips)+150, chop_out_y+155))
    print(f'  chop_out: M2 y={chop_out_y}')

    # 2. sens_p: TG1 D strips via M2 bus below
    d_tg1 = [D['Mchop1n']['strips'][-1], D['Mchop1p']['strips'][-1]]
    sens_p_y = dev_bot - 1500
    for s in d_tg1:
        cx = scx(s); cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,sens_p_y)-155, cx+150, max(cy,sens_p_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in d_tg1)-150, sens_p_y-155,
                                 max(scx(s) for s in d_tg1)+150, sens_p_y+155))
    print(f'  sens_p: M2 y={sens_p_y}')

    # 3. sens_n: TG2 D strips via M2 bus below
    d_tg2 = [D['Mchop2n']['strips'][-1], D['Mchop2p']['strips'][-1]]
    sens_n_y = dev_bot - 2000
    for s in d_tg2:
        cx = scx(s); cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,sens_n_y)-155, cx+150, max(cy,sens_n_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in d_tg2)-150, sens_n_y-155,
                                 max(scx(s) for s in d_tg2)+150, sens_n_y+155))
    print(f'  sens_n: M2 y={sens_n_y}')

    # 4. Gate routing above ntap
    gate_y1 = pmos_top + 1500  # f_exc
    gate_y2 = pmos_top + 2000  # f_exc_b
    for gates_pair, gy, label in [
        (['Mchop1n', 'Mchop2p'], gate_y1, 'f_exc'),
        (['Mchop1p', 'Mchop2n'], gate_y2, 'f_exc_b'),
    ]:
        gate_xs = []
        for dn in gates_pair:
            g = D[dn]['gates'][0]
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            if g[3] < gy:
                cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, gy+250))
            else:
                cell.shapes(l_po).insert(box(gx-gw//2, gy-250, gx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gx-80, gy-80, gx+80, gy+80))
            cell.shapes(l_m1).insert(box(gx-155, gy-155, gx+155, gy+155))
            gate_xs.append(gx)
        cell.shapes(l_m1).insert(box(min(gate_xs)-155, gy-155, max(gate_xs)+155, gy+155))
        print(f'  {label}: M1 y={gy}')

    # 5. GND + VDD
    n_xmin = min(D[n]['bbox'][0] for n in ['Mchop1n','Mchop2n'])
    n_xmax = max(D[n]['bbox'][2] for n in ['Mchop1n','Mchop2n'])
    gnd_y = dev_bot - 800
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    print(f'  gnd: M1 y={gnd_y}')

    p_xmin = min(D[n]['bbox'][0] for n in ['Mchop1p','Mchop2p'])
    p_xmax = max(D[n]['bbox'][2] for n in ['Mchop1p','Mchop2p'])
    ntap_y = pmos_top + 500
    cell.shapes(l_m1).insert(box(p_xmin, ntap_y-155, p_xmax, ntap_y+500))
    print(f'  vdd: M1 y={ntap_y}')

    # Write + DRC
    out = os.path.join(OUT_DIR, 'chopper.gds')
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
