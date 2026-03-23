#!/usr/bin/env python3
"""Route hbridge_drive: 4 NMOS multiplexer switches (all ng=2).

MS1: D=exc_out, G=phi_p, S=probe_p
MS2: D=gnd,     G=phi_n, S=probe_p
MS3: D=exc_out, G=phi_n, S=probe_n
MS4: D=gnd,     G=phi_p, S=probe_n

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_hbridge_drive.py
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


def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('hbridge_drive', mods['hbridge_drive'])
    D = {d['name']: d for d in devs}

    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    print('\n--- Routing hbridge_drive ---')

    # All devices are NMOS at y=0, single row
    # Each ng=2: strips[0]=S, strips[1]=D, strips[2]=S
    def get_sds(name):
        strips = D[name]['strips']
        s_list = [strips[i] for i in range(0, len(strips), 2)]
        d_list = [strips[i] for i in range(1, len(strips), 2)]
        return s_list, d_list

    ms1_s, ms1_d = get_sds('MS1')
    ms2_s, ms2_d = get_sds('MS2')
    ms3_s, ms3_d = get_sds('MS3')
    ms4_s, ms4_d = get_sds('MS4')

    nmos_top = max(d['bbox'][3] for d in devs)
    nmos_bot = min(d['bbox'][1] for d in devs)

    # No internal S strip M2 bus (M2 horizontal at strip level crosses D strip → short)
    # Each S strip connects directly to cross-device M2 bus via individual M2 vertical

    # ─── 1. Cross-device nets via M2 buses ───
    # probe_p: MS1.S + MS2.S — M2 bus above devices
    # probe_n: MS3.S + MS4.S — M2 bus above devices
    # exc_out: MS1.D + MS3.D — M2 bus below devices
    # gnd: MS2.D + MS4.D — connected to ptap below

    # Y positions: gates just above device, M2 buses well above gates
    # Gate buses at nmos_top+300 and +800, M2 buses at +1500 and +2000
    y_above_1 = nmos_top + 1500  # probe_p M2
    y_above_2 = nmos_top + 2000  # probe_n M2
    y_below = nmos_bot - 1500  # far below GND bus (-800) to avoid M1 pad overlap

    # probe_p: MS1.S + MS2.S (M2 at y_above)
    pp_strips = ms1_s + ms2_s  # all S strips from both
    pp_y = y_above_1
    for s in pp_strips:
        cx = (s[0]+s[1])//2
        scy = (s[2]+s[3])//2
        add_via1_m2(cell, ly, cx, scy)   # Via1 at strip level only
        cell.shapes(l_m2).insert(box(cx-150, min(scy, pp_y)-155, cx+150, max(scy, pp_y)+155))
    pp_x1 = min((s[0]+s[1])//2 for s in pp_strips)
    pp_x2 = max((s[0]+s[1])//2 for s in pp_strips)
    cell.shapes(l_m2).insert(box(pp_x1-150, pp_y-155, pp_x2+150, pp_y+155))
    print(f'  probe_p: M2 y={pp_y}')

    # probe_n: MS3.S + MS4.S (M2 at y_above + 500)
    pn_strips = ms3_s + ms4_s
    pn_y = y_above_2
    for s in pn_strips:
        cx = (s[0]+s[1])//2
        scy = (s[2]+s[3])//2
        add_via1_m2(cell, ly, cx, scy)
        cell.shapes(l_m2).insert(box(cx-150, min(scy, pn_y)-155, cx+150, max(scy, pn_y)+155))
    pn_x1 = min((s[0]+s[1])//2 for s in pn_strips)
    pn_x2 = max((s[0]+s[1])//2 for s in pn_strips)
    cell.shapes(l_m2).insert(box(pn_x1-150, pn_y-155, pn_x2+150, pn_y+155))
    print(f'  probe_n: M2 y={pn_y}')

    # exc_out: MS1.D + MS3.D (M2 at y_below)
    eo_strips = ms1_d + ms3_d
    eo_y = y_below
    for s in eo_strips:
        cx = (s[0]+s[1])//2
        scy = (s[2]+s[3])//2
        add_via1_m2(cell, ly, cx, scy)
        cell.shapes(l_m2).insert(box(cx-150, min(scy, eo_y)-155, cx+150, max(scy, eo_y)+155))
    eo_x1 = min((s[0]+s[1])//2 for s in eo_strips)
    eo_x2 = max((s[0]+s[1])//2 for s in eo_strips)
    cell.shapes(l_m2).insert(box(eo_x1-150, eo_y-155, eo_x2+150, eo_y+155))
    print(f'  exc_out: M2 y={eo_y}')

    # gnd: MS2.D + MS4.D — extend D strips to ptap via M1
    gnd_y = nmos_bot - 800  # ptap level
    gnd_strips = ms2_d + ms4_d
    for s in gnd_strips:
        cx = (s[0]+s[1])//2
        cell.shapes(l_m1).insert(box(cx-80, gnd_y, cx+80, s[2]))
    # M1 bus connecting all GND strips + ptap
    all_gnd_x = [(s[0]+s[1])//2 for s in gnd_strips]
    cell.shapes(l_m1).insert(box(min(all_gnd_x)-155, gnd_y-155, max(all_gnd_x)+155, gnd_y+155))
    print(f'  gnd: M1 y={gnd_y}')

    # ─── 3. Gate routing ───
    # phi_p: MS1.G + MS4.G
    # phi_n: MS2.G + MS3.G
    gate_y = nmos_top + 300  # just above device
    phi_p_gates = D['MS1']['gates'] + D['MS4']['gates']
    phi_n_gates = D['MS2']['gates'] + D['MS3']['gates']

    for gates, name, gy in [(phi_p_gates, 'phi_p', gate_y),
                             (phi_n_gates, 'phi_n', gate_y + 500)]:
        gate_xs = []
        for g in gates:
            gcx = (g[0]+g[1])//2
            gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gcx-gw//2, g[3], gcx+gw//2, gy+250))
            cell.shapes(l_ct).insert(box(gcx-80, gy-80, gcx+80, gy+80))
            cell.shapes(l_m1).insert(box(gcx-155, gy-155, gcx+155, gy+155))
            gate_xs.append(gcx)
        cell.shapes(l_m1).insert(box(min(gate_xs)-155, gy-155, max(gate_xs)+155, gy+155))
        print(f'  {name}: M1 y={gy}')

    # ─── Write + DRC ───
    out = os.path.join(OUT_DIR, 'hbridge_drive.gds')
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
