#!/usr/bin/env python3
"""Route OTA: 5T OTA + bias. 3 bands.

Band 1 (y=0):   Mbias_d (ng=1) + Mtail (ng=2)
Band 2 (y=6.5): Min_p (ng=4) + Min_n (ng=4) — diff pair
Band 3 (y=11.5): Mp_load_p + Mp_load_n (ng=1)

Nets:
  bias_n:   Mbias_d.D/G + Mtail.G (diode + gate)
  tail:     Mtail.D + Min_p.S + Min_n.S
  mid_p:    Min_p.D + Mp_load_p.D/G + Mp_load_n.G
  ota_out:  Min_n.D + Mp_load_n.D
  vref_ota: Min_p.G (external)
  sum_n:    Min_n.G (external)
  gnd:      Mbias_d.S + Mtail.S
  vdd:      Mp_load_p.S + Mp_load_n.S

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_ota.py
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
    ly, cell, devs = build_module('ota', mods['ota'])
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    # Band boundaries
    band1_top = max(D[n]['bbox'][3] for n in ['Mbias_d','Mtail'])
    band2_bot = min(D[n]['bbox'][1] for n in ['Min_p','Min_n'])
    band2_top = max(D[n]['bbox'][3] for n in ['Min_p','Min_n'])
    band3_bot = min(D[n]['bbox'][1] for n in ['Mp_load_p','Mp_load_n'])
    band3_top = max(D[n]['bbox'][3] for n in ['Mp_load_p','Mp_load_n'])
    dev_bot = min(d['bbox'][1] for d in devs)

    gap1_mid = (band1_top + band2_bot) // 2
    gap2_mid = (band2_top + band3_bot) // 2

    print(f'\n--- Routing OTA ---')
    print(f'  Gap1: {band1_top}-{band2_bot} (mid={gap1_mid})')
    print(f'  Gap2: {band2_top}-{band3_bot} (mid={gap2_mid})')

    # ─── 1. bias_n: Mbias_d diode + Mtail.G ───
    # Mbias_d.D strip + gate contact → M1 bridge (diode)
    bias_d = D['Mbias_d']['strips'][-1]  # D strip
    bias_g = D['Mbias_d']['gates'][0]
    bias_gcx = (bias_g[0]+bias_g[1])//2
    # M1 bridge D↔G + Contact on gate
    cell.shapes(l_ct).insert(box(bias_gcx-80, scy(bias_d)-80, bias_gcx+80, scy(bias_d)+80))
    cell.shapes(l_m1).insert(box(min(scx(bias_d),bias_gcx)-155, scy(bias_d)-155,
                                 max(scx(bias_d),bias_gcx)+155, scy(bias_d)+155))

    # Mtail.G: extend gate to gap1 for bias_n connection
    bias_n_y = gap1_mid - 500
    for g in D['Mtail']['gates']:
        gx = (g[0]+g[1])//2; gw = g[1]-g[0]
        cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, bias_n_y+250))
        cell.shapes(l_ct).insert(box(gx-80, bias_n_y-80, gx+80, bias_n_y+80))
        cell.shapes(l_m1).insert(box(gx-155, bias_n_y-155, gx+155, bias_n_y+155))

    # M1 bus connecting bias_d diode to Mtail gates
    mtail_g_xs = [(g[0]+g[1])//2 for g in D['Mtail']['gates']]
    all_bias_x = [scx(bias_d), bias_gcx] + mtail_g_xs
    cell.shapes(l_m1).insert(box(min(all_bias_x)-155, bias_n_y-155,
                                 max(all_bias_x)+155, bias_n_y+155))
    # Vertical from diode bridge to bus
    cell.shapes(l_m1).insert(box(scx(bias_d)-155, scy(bias_d)+155,
                                 scx(bias_d)+155, bias_n_y-155))
    print(f'  bias_n: y={bias_n_y}')

    # ─── 2. tail: Mtail.D + Min_p.S + Min_n.S ───
    tail_y = gap1_mid + 500  # in gap1, above bias_n

    # Mtail D strip(s)
    mtail_d = [D['Mtail']['strips'][i] for i in range(1, len(D['Mtail']['strips']), 2)]
    for s in mtail_d:
        add_via1_m2(cell, ly, scx(s), scy(s))

    # Min_p S strips (even indices)
    minp_s = [D['Min_p']['strips'][i] for i in range(0, len(D['Min_p']['strips']), 2)]
    for s in minp_s:
        add_via1_m2(cell, ly, scx(s), scy(s))

    # Min_n S strips
    minn_s = [D['Min_n']['strips'][i] for i in range(0, len(D['Min_n']['strips']), 2)]
    for s in minn_s:
        add_via1_m2(cell, ly, scx(s), scy(s))

    # M2 bus for tail at gap1
    all_tail = mtail_d + minp_s + minn_s
    tail_bus_y = tail_y
    # Via1+M2 at bus level for each strip, M2 vertical from strip to bus
    for s in all_tail:
        cx = scx(s); cy = scy(s)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,tail_bus_y)-155, cx+150, max(cy,tail_bus_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in all_tail)-150, tail_bus_y-155,
                                 max(scx(s) for s in all_tail)+150, tail_bus_y+155))
    print(f'  tail: M2 y={tail_bus_y}')

    # ─── 3. mid_p: Min_p.D + Mp_load_p.D/G + Mp_load_n.G ───
    midp_y = gap2_mid - 800  # in gap2

    # Min_p D strips
    minp_d = [D['Min_p']['strips'][i] for i in range(1, len(D['Min_p']['strips']), 2)]
    for s in minp_d:
        add_via1_m2(cell, ly, scx(s), scy(s))

    # Mp_load_p.D
    p_load_p_d = D['Mp_load_p']['strips'][-1]
    add_via1_m2(cell, ly, scx(p_load_p_d), scy(p_load_p_d))

    # M2 verticals + bus
    midp_strips = minp_d + [p_load_p_d]
    for s in midp_strips:
        cx = scx(s); cy = scy(s)
        cell.shapes(l_m2).insert(box(cx-150, min(cy,midp_y)-155, cx+150, max(cy,midp_y)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in midp_strips)-150, midp_y-155,
                                 max(scx(s) for s in midp_strips)+150, midp_y+155))

    # Mp_load_p.G + Mp_load_n.G: gate contacts → connect to mid_p via M1
    midp_gate_y = midp_y + 600  # 600 > 310+210 ensures M2.b spacing
    for dn in ['Mp_load_p', 'Mp_load_n']:
        g = D[dn]['gates'][0]
        gx = (g[0]+g[1])//2; gw = g[1]-g[0]
        cell.shapes(l_po).insert(box(gx-gw//2, midp_gate_y-250, gx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(gx-80, midp_gate_y-80, gx+80, midp_gate_y+80))
        cell.shapes(l_m1).insert(box(gx-155, midp_gate_y-155, gx+155, midp_gate_y+155))

    # Mp_load_p diode: gate contacts connect to D via M1
    plp_gx = (D['Mp_load_p']['gates'][0][0]+D['Mp_load_p']['gates'][0][1])//2
    pln_gx = (D['Mp_load_n']['gates'][0][0]+D['Mp_load_n']['gates'][0][1])//2
    cell.shapes(l_m1).insert(box(min(plp_gx,pln_gx)-155, midp_gate_y-155,
                                 max(plp_gx,pln_gx)+155, midp_gate_y+155))

    # Connect gate bus to mid_p M2 via Via1
    add_via1_m2(cell, ly, plp_gx, midp_gate_y)
    cell.shapes(l_m2).insert(box(plp_gx-150, min(midp_y,midp_gate_y)-155,
                                 plp_gx+150, max(midp_y,midp_gate_y)+155))
    print(f'  mid_p: M2 y={midp_y}, gates y={midp_gate_y}')

    # ─── 4. ota_out: Min_n.D + Mp_load_n.D ───
    otaout_y = gap2_mid + 400  # in gap2, above mid_p

    minn_d = [D['Min_n']['strips'][i] for i in range(1, len(D['Min_n']['strips']), 2)]
    p_load_n_d = D['Mp_load_n']['strips'][-1]

    for s in minn_d + [p_load_n_d]:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),otaout_y)-155,
                                     scx(s)+150, max(scy(s),otaout_y)+155))
    otaout_strips = minn_d + [p_load_n_d]
    cell.shapes(l_m2).insert(box(min(scx(s) for s in otaout_strips)-150, otaout_y-155,
                                 max(scx(s) for s in otaout_strips)+150, otaout_y+155))
    print(f'  ota_out: M2 y={otaout_y}')

    # ─── 5. vref_ota + sum_n: diff pair gate contacts ───
    # Route below diff pair (in gap1, different y from tail/bias)
    vref_y = band2_bot - 300
    sumn_y = band2_bot - 700

    for gates, gy, label in [(D['Min_p']['gates'], vref_y, 'vref_ota'),
                              (D['Min_n']['gates'], sumn_y, 'sum_n')]:
        gate_xs = []
        for g in gates:
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, gy-250, gx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gx-80, gy-80, gx+80, gy+80))
            cell.shapes(l_m1).insert(box(gx-155, gy-155, gx+155, gy+155))
            gate_xs.append(gx)
        cell.shapes(l_m1).insert(box(min(gate_xs)-155, gy-155, max(gate_xs)+155, gy+155))
        print(f'  {label}: M1 y={gy}')

    # ─── 6. GND + VDD ───
    gnd_y = dev_bot - 800
    n_xmin = min(D[n]['bbox'][0] for n in ['Mbias_d','Mtail'])
    n_xmax = max(D[n]['bbox'][2] for n in ['Mbias_d','Mtail'])
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    # GND S strip extensions
    for dn in ['Mbias_d', 'Mtail']:
        s = D[dn]['strips'][0]
        cell.shapes(l_m1).insert(box(scx(s)-80, gnd_y+155, scx(s)+80, s[2]))
    # Mtail extra S strips
    for i in range(2, len(D['Mtail']['strips']), 2):
        s = D['Mtail']['strips'][i]
        cell.shapes(l_m1).insert(box(scx(s)-80, gnd_y+155, scx(s)+80, s[2]))
    print(f'  gnd: M1 y={gnd_y}')

    vdd_y = band3_top + 500
    p_xmin = min(D[n]['bbox'][0] for n in ['Mp_load_p','Mp_load_n'])
    p_xmax = max(D[n]['bbox'][2] for n in ['Mp_load_p','Mp_load_n'])
    cell.shapes(l_m1).insert(box(p_xmin, vdd_y-155, p_xmax, vdd_y+500))
    for dn in ['Mp_load_p', 'Mp_load_n']:
        s = D[dn]['strips'][0]
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, vdd_y-155))
    print(f'  vdd: M1 y={vdd_y}')

    # Write + DRC
    out = os.path.join(OUT_DIR, 'ota.gds')
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
