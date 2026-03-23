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
    ly, cell, devs = build_module('vco_5stage', mods['vco_5stage'], ntap_offset=1500)
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

    # ─── Ring feedback: vco{i} → next stage Mpd/Mpu gates ───
    y_lo = r2_top + 500   # 5860
    y_hi = r3_bot - 500   # 7000
    ring = [(1,2,'lo'), (2,3,'mid'), (3,4,'lo'), (4,5,'mid'), (5,1,'hi')]

    for src, dst, level in ring:
        y_ring = y_lo if level == 'lo' else (g23 if level == 'mid' else y_hi)

        # Source: tap vco M2 bus
        vco_cx = scx(D[f'Mpd{src}']['strips'][-1])
        if level == 'mid':
            # Via1 directly on vco M2 bus at g23
            add_via1_m2(cell, ly, vco_cx, g23)
        else:
            # M2 vertical from vco bus to y_ring, Via1 at y_ring (no M1 at g23)
            cell.shapes(l_m2).insert(box(vco_cx-150, min(g23, y_ring)-155,
                                         vco_cx+150, max(g23, y_ring)+155))
            add_via1_m2(cell, ly, vco_cx, y_ring)

        # Destination gate contacts
        mpd_g = D[f'Mpd{dst}']['gates'][0]
        mpu_g = D[f'Mpu{dst}']['gates'][0]
        gate_cx = (mpd_g[0] + mpd_g[1]) // 2
        gw = mpd_g[1] - mpd_g[0]

        # Poly extensions: Mpd up, Mpu down — meet at y_ring
        cell.shapes(l_po).insert(box(gate_cx-gw//2, mpd_g[3], gate_cx+gw//2, y_ring+80))
        cell.shapes(l_po).insert(box(gate_cx-gw//2, y_ring-80, gate_cx+gw//2, mpu_g[2]))

        # Contact + M1 pad at gate junction
        cell.shapes(l_ct).insert(box(gate_cx-80, y_ring-80, gate_cx+80, y_ring+80))
        cell.shapes(l_m1).insert(box(gate_cx-155, y_ring-155, gate_cx+155, y_ring+155))

        # M1 horizontal from vco source to gate contacts
        x_lo = min(vco_cx, gate_cx)
        x_hi = max(vco_cx, gate_cx)
        cell.shapes(l_m1).insert(box(x_lo-155, y_ring-155, x_hi+155, y_ring+155))

        print(f'  ring vco{src}->S{dst}: y={y_ring} ({level})')

    # ─── Global nets ───

    # nmos_bias: all Mnb gates — poly bridge ABOVE Active (same pattern as pmos_bias)
    bias_n_y = g12 - 500  # in gap between Mnb and Mpd
    all_bias_n_x = []
    for i in range(1, 6):
        gates = D[f'Mnb{i}']['gates']
        if not gates: continue
        g_xmin = min(g[0] for g in gates)
        g_xmax = max(g[1] for g in gates)
        g_top = max(g[3] for g in gates)
        cell.shapes(l_po).insert(box(g_xmin, g_top, g_xmax, bias_n_y+250))
        for g in gates:
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, bias_n_y+250))
        # Single Contact + M1 pad on bridge
        bridge_cx = (g_xmin + g_xmax) // 2
        cell.shapes(l_ct).insert(box(bridge_cx-80, bias_n_y-80, bridge_cx+80, bias_n_y+80))
        cell.shapes(l_m1).insert(box(bridge_cx-155, bias_n_y-155, bridge_cx+155, bias_n_y+155))
        all_bias_n_x.append(bridge_cx)
    cell.shapes(l_m1).insert(box(min(all_bias_n_x)-155, bias_n_y-155,
                                 max(all_bias_n_x)+155, bias_n_y+155))
    print(f'  nmos_bias: M1 y={bias_n_y}')

    # pmos_bias: individual Contact + Via1 + M2 bus (M1 pads between VDD stubs in x)
    bias_p_y = max(g[3] for g in D['Mpb1']['gates']) + 500  # plenty of room (ntap now at +1500)
    all_bias_p_x = []
    for i in range(1, 6):
        gates = D[f'Mpb{i}']['gates']
        if not gates: continue
        for g in gates:
            gx = (g[0]+g[1])//2; gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, bias_p_y+150))
            cell.shapes(l_ct).insert(box(gx-80, bias_p_y-80, gx+80, bias_p_y+80))
            add_via1_m2(cell, ly, gx, bias_p_y)
            all_bias_p_x.append(gx)
    # M2 bus (not M1 — M1 would conflict with VDD stubs)
    cell.shapes(l_m2).insert(box(min(all_bias_p_x)-150, bias_p_y-155,
                                 max(all_bias_p_x)+150, bias_p_y+155))
    print(f'  pmos_bias: M2 y={bias_p_y} ({len(all_bias_p_x)} contacts)')

    # GND: Mnb S strips
    gnd_y = dev_bot - 1000
    n_xmin = min(d['bbox'][0] for d in devs if d['type']=='nmos')
    n_xmax = max(d['bbox'][2] for d in devs if d['type']=='nmos')
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+500))
    # Stubs from GND bus to Mnb S strip bottoms (widen near ptap to merge)
    ptap_edges = [(310 + k*10000, 810 + k*10000) for k in range(11)]
    for i in range(1, 6):
        for j in range(0, len(D[f'Mnb{i}']['strips']), 2):
            s = D[f'Mnb{i}']['strips'][j]
            sx = scx(s)
            sl, sr = sx - 80, sx + 80
            for pl, pr in ptap_edges:
                if 0 < sl - pr < 180:
                    sl = pl
                elif 0 < pl - sr < 180:
                    sr = pr
            cell.shapes(l_m1).insert(box(sl, gnd_y+155, sr, s[2]))
    print(f'  gnd: M1 y={gnd_y}')

    # VDD: Mpb S strips + ntap
    vdd_y = r4_top + 1500  # match ntap at +1500
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
