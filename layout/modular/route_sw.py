#!/usr/bin/env python3
"""Route sw: 3 TG current source switches. Same 2-row TG pattern.

TG1: SW1n+SW1p — src1 ↔ exc_out, gates sel0/sel0b
TG2: SW2n+SW2p — src2 ↔ exc_out, gates sel1/sel1b
TG3: SW3n+SW3p — src3 ↔ exc_out, gates sel2/sel2b

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_sw.py
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
    ly, cell, devs = build_module('sw', mods['sw'])
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    nmos_names = ['SW1n','SW2n','SW3n']
    pmos_names = ['SW1p','SW2p','SW3p']
    nmos_top = max(D[n]['bbox'][3] for n in nmos_names)
    pmos_top = max(D[n]['bbox'][3] for n in pmos_names)
    dev_bot = min(d['bbox'][1] for d in devs)

    print('\n--- Routing sw ---')

    # 1. exc_out: all S strips via M2 bus above
    s_strips = [D[n]['strips'][0] for n in nmos_names + pmos_names]
    exc_out_y = pmos_top + 2500
    for s in s_strips:
        cx = scx(s); cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,exc_out_y)-155, cx+150, max(cy,exc_out_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in s_strips)-150, exc_out_y-155,
                                 max(scx(s) for s in s_strips)+150, exc_out_y+155))
    print(f'  exc_out: M2 y={exc_out_y}')

    # 2. src1/2/3: TG D strips via M2 buses below (staggered y)
    for idx, (nn, pn, label) in enumerate([('SW1n','SW1p','src1'),('SW2n','SW2p','src2'),('SW3n','SW3p','src3')]):
        d_strips = [D[nn]['strips'][-1], D[pn]['strips'][-1]]
        src_y = dev_bot - 1500 - idx * 500
        for s in d_strips:
            cx = scx(s); cy = scy(s)
            add_via1_m2(cell, ly, cx, cy)
            cell.shapes(l_m2).insert(box(cx-150, min(cy,src_y)-155, cx+150, max(cy,src_y)+155))
        cell.shapes(l_m2).insert(box(min(scx(s) for s in d_strips)-150, src_y-155,
                                     max(scx(s) for s in d_strips)+150, src_y+155))
        print(f'  {label}: M2 y={src_y}')

    # 3. Gate routing above ntap (6 gate signals, staggered)
    # SW3 gates route BELOW NMOS (avoid ntap at x≈12)
    gate_pairs = [
        (['SW1n'], 'sel0', pmos_top + 1500),
        (['SW1p'], 'sel0b', pmos_top + 1900),
        (['SW2n'], 'sel1', pmos_top + 2300),
        (['SW2p'], 'sel1b', pmos_top + 2700),
        (['SW3n'], 'sel2', dev_bot - 2800),   # below, away from GND/src buses
        (['SW3p'], 'sel2b', dev_bot - 3200),
    ]
    for dev_names, label, gy in gate_pairs:
        gate_xs = []
        for dn in dev_names:
            g = D[dn]['gates'][0]
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            if g[3] < gy:
                cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, gy+250))
            else:
                cell.shapes(l_po).insert(box(gx-gw//2, gy-250, gx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gx-80, gy-80, gx+80, gy+80))
            cell.shapes(l_m1).insert(box(gx-155, gy-155, gx+155, gy+155))
            gate_xs.append(gx)
        if len(gate_xs) > 1:
            cell.shapes(l_m1).insert(box(min(gate_xs)-155, gy-155, max(gate_xs)+155, gy+155))
        print(f'  {label}: M1 y={gy}')

    # 4. GND + VDD
    n_xmin = min(D[n]['bbox'][0] for n in nmos_names)
    n_xmax = max(D[n]['bbox'][2] for n in nmos_names)
    gnd_y = dev_bot - 800
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    print(f'  gnd: M1 y={gnd_y}')

    p_xmin = min(D[n]['bbox'][0] for n in pmos_names)
    p_xmax = max(D[n]['bbox'][2] for n in pmos_names)
    ntap_y = pmos_top + 500
    cell.shapes(l_m1).insert(box(p_xmin, ntap_y-155, p_xmax, ntap_y+500))
    print(f'  vdd: M1 y={ntap_y}')

    # Write + DRC
    out = os.path.join(OUT_DIR, 'sw.gds')
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
