#!/usr/bin/env python3
"""Route dac_sw: 2 transmission gates for DAC output selection.

TG1: Mdac_tg1n + Mdac_tg1p — dac_hi ↔ dac_out
TG2: Mdac_tg2n + Mdac_tg2p — dac_lo ↔ dac_out

Nets:
  dac_out: all S (4 strips)
  dac_hi:  TG1 D (2 strips)
  dac_lo:  TG2 D (2 strips)
  lat_q:   Mdac_tg1n.G + Mdac_tg2p.G
  lat_qb:  Mdac_tg1p.G + Mdac_tg2n.G
  gnd:     NMOS body (ptap)
  vdd:     PMOS body (ntap)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_dac_sw.py
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
def gcx(d): return (d['gates'][0][0]+d['gates'][0][1])//2 if d['gates'] else None


def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('dac_sw', mods['dac_sw'])
    D = {d['name']: d for d in devs}

    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    print('\n--- Routing dac_sw ---')

    # Layout: NMOS(short) and PMOS(tall) side by side at y=0
    # NMOS top ≈ 2.36, PMOS top ≈ 4.62
    nmos_top = max(D[n]['bbox'][3] for n in ['Mdac_tg1n','Mdac_tg2n'])
    pmos_top = max(D[n]['bbox'][3] for n in ['Mdac_tg1p','Mdac_tg2p'])
    dev_bot = min(d['bbox'][1] for d in devs)
    all_xmax = max(d['bbox'][2] for d in devs)

    # ─── 1. dac_out: all S strips via M2 bus above devices ───
    s_strips = [D[n]['strips'][0] for n in ['Mdac_tg1n','Mdac_tg1p','Mdac_tg2n','Mdac_tg2p']]
    dac_out_y = pmos_top + 2500  # above gates and ntap
    for s in s_strips:
        cx = scx(s)
        cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)  # Via1 at strip level only
        cell.shapes(l_m2).insert(box(cx-150, min(cy,dac_out_y)-155, cx+150, max(cy,dac_out_y)+155))
    sx1 = min(scx(s) for s in s_strips)
    sx2 = max(scx(s) for s in s_strips)
    cell.shapes(l_m2).insert(box(sx1-150, dac_out_y-155, sx2+150, dac_out_y+155))
    print(f'  dac_out: M2 y={dac_out_y}')

    # ─── 2. dac_hi: TG1 D strips via M2 bus below devices ───
    d_tg1 = [D['Mdac_tg1n']['strips'][-1], D['Mdac_tg1p']['strips'][-1]]
    dac_hi_y = dev_bot - 1500  # well below to avoid GND bus
    for s in d_tg1:
        cx = scx(s)
        cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,dac_hi_y)-155, cx+150, max(cy,dac_hi_y)+155))
    dx1 = min(scx(s) for s in d_tg1)
    dx2 = max(scx(s) for s in d_tg1)
    cell.shapes(l_m2).insert(box(dx1-150, dac_hi_y-155, dx2+150, dac_hi_y+155))
    print(f'  dac_hi: M2 y={dac_hi_y}')

    # ─── 3. dac_lo: TG2 D strips via M2 bus below devices ───
    d_tg2 = [D['Mdac_tg2n']['strips'][-1], D['Mdac_tg2p']['strips'][-1]]
    dac_lo_y = dev_bot - 2000  # below dac_hi
    for s in d_tg2:
        cx = scx(s)
        cy = scy(s)
        add_via1_m2(cell, ly, cx, cy)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,dac_lo_y)-155, cx+150, max(cy,dac_lo_y)+155))
    dx1 = min(scx(s) for s in d_tg2)
    dx2 = max(scx(s) for s in d_tg2)
    cell.shapes(l_m2).insert(box(dx1-150, dac_lo_y-155, dx2+150, dac_lo_y+155))
    print(f'  dac_lo: M2 y={dac_lo_y}')

    # ─── 4. Gate routing: lat_q and lat_qb ───
    # lat_q: Mdac_tg1n.G + Mdac_tg2p.G (staggered y for Cnt.b)
    # lat_qb: Mdac_tg1p.G + Mdac_tg2n.G
    # Gates ABOVE ntap+VDD area to avoid M1 overlap
    gate_y1 = pmos_top + 1500  # lat_q (above ntap)
    gate_y2 = pmos_top + 2000  # lat_qb

    for gates_pair, gy, label in [
        (['Mdac_tg1n', 'Mdac_tg2p'], gate_y1, 'lat_q'),
        (['Mdac_tg1p', 'Mdac_tg2n'], gate_y2, 'lat_qb'),
    ]:
        gate_xs = []
        for dev_name in gates_pair:
            g = D[dev_name]['gates'][0]
            gx = (g[0]+g[1])//2
            gw = g[1]-g[0]
            if g[3] < gy:
                cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, gy+250))
            else:
                cell.shapes(l_po).insert(box(gx-gw//2, gy-250, gx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gx-80, gy-80, gx+80, gy+80))
            cell.shapes(l_m1).insert(box(gx-155, gy-155, gx+155, gy+155))
            gate_xs.append(gx)
        cell.shapes(l_m1).insert(box(min(gate_xs)-155, gy-155, max(gate_xs)+155, gy+155))
        print(f'  {label}: M1 y={gy}')

    # ─── 5. GND: ptap connection ───
    gnd_y = dev_bot - 800
    n_xmin = min(D[n]['bbox'][0] for n in ['Mdac_tg1n','Mdac_tg2n'])
    n_xmax = max(D[n]['bbox'][2] for n in ['Mdac_tg1n','Mdac_tg2n'])
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    print(f'  gnd: M1 y={gnd_y}')

    # ─── 6. VDD: ntap connection ───
    vdd_y = pmos_top + 500  # ntap is placed by build_module above PMOS
    # Extend VDD bus to ntap
    p_xmin = min(D[n]['bbox'][0] for n in ['Mdac_tg1p','Mdac_tg2p'])
    p_xmax = max(D[n]['bbox'][2] for n in ['Mdac_tg1p','Mdac_tg2p'])
    ntap_y = pmos_top + 500  # matches build_module
    cell.shapes(l_m1).insert(box(p_xmin, ntap_y-155, p_xmax, ntap_y+500))
    print(f'  vdd: M1 y={ntap_y}')

    # ─── Write + DRC ───
    out = os.path.join(OUT_DIR, 'dac_sw.gds')
    ly.write(out)
    bb = cell.bbox()
    print(f'\n  Size: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    flat = ly.create_cell('_d')
    flat.copy_tree(cell)
    flat.flatten(True)
    m1r = pya.Region(flat.begin_shapes_rec(ly.find_layer(*M1)))
    m2r = pya.Region(flat.begin_shapes_rec(ly.find_layer(*M2)))
    print(f'  Quick DRC: M1.b={m1r.space_check(180).count()} M1.a={m1r.width_check(160).count()}'
          f' M2.b={m2r.space_check(210).count()} M2.a={m2r.width_check(210).count()}')
    flat.delete()


if __name__ == '__main__':
    route()
    print('\n=== Done ===')
