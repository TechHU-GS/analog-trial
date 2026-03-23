#!/usr/bin/env python3
"""Route hbridge (SR latch): 8 devices, cross-coupled.

Nets:
  n1_mid:    Mn1a.D + Mn1b.S (M1 bridge)
  n2_mid:    Mn2a.D + Mn2b.S (M1 bridge)
  lat_q:     Mn1b.D + Mp1a.D + Mp1b.D + Mn2b.G + Mp2b.G
  lat_qb:    Mn2b.D + Mp2a.D + Mp2b.D + Mn1b.G + Mp1b.G
  comp_outp: Mn1a.G + Mp1a.G
  comp_outn: Mn2a.G + Mp2a.G
  gnd:       Mn1a.S + Mn2a.S
  vdd:       Mp1a.S + Mp1b.S + Mp2a.S + Mp2b.S

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_hbridge.py
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


def scx(strip):
    return (strip[0]+strip[1])//2

def scy(strip):
    return (strip[2]+strip[3])//2

def gcx(dev):
    return (dev['gates'][0][0]+dev['gates'][0][1])//2 if dev['gates'] else None


def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('hbridge', mods['hbridge'])
    D = {d['name']: d for d in devs}

    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    nmos_top = max(D[n]['bbox'][3] for n in ['Mn1a','Mn1b','Mn2a','Mn2b'])
    pmos_bot = min(D[n]['bbox'][1] for n in ['Mp1a','Mp1b','Mp2a','Mp2b'])
    pmos_top = max(D[n]['bbox'][3] for n in ['Mp1a','Mp1b','Mp2a','Mp2b'])

    print('\n--- Routing hbridge ---')

    # ─── 1. n1_mid: Mn1a.D ↔ Mn1b.S (M1 bridge) ───
    n1a_d = D['Mn1a']['strips'][-1]  # D strip
    n1b_s = D['Mn1b']['strips'][0]   # S strip
    bridge_y = (scy(n1a_d) + scy(n1b_s)) // 2
    cell.shapes(l_m1).insert(box(scx(n1a_d)-80, bridge_y-155,
                                 scx(n1b_s)+80, bridge_y+155))
    print(f'  n1_mid: M1 bridge x={scx(n1a_d)}-{scx(n1b_s)}')

    # ─── 2. n2_mid: Mn2a.D ↔ Mn2b.S (M1 bridge) ───
    n2a_d = D['Mn2a']['strips'][-1]
    n2b_s = D['Mn2b']['strips'][0]
    cell.shapes(l_m1).insert(box(scx(n2a_d)-80, bridge_y-155,
                                 scx(n2b_s)+80, bridge_y+155))
    print(f'  n2_mid: M1 bridge x={scx(n2a_d)}-{scx(n2b_s)}')

    # ─── 3. lat_q: Mn1b.D + Mp1a.D + Mp1b.D via M2 ───
    # + cross-coupling to Mn2b.G + Mp2b.G
    n1b_d = D['Mn1b']['strips'][-1]
    p1a_d = D['Mp1a']['strips'][-1]  # D = strip[1] (odd)
    p1b_d = D['Mp1b']['strips'][-1]

    # Via1 on drain strips
    add_via1_m2(cell, ly, scx(n1b_d), scy(n1b_d))
    add_via1_m2(cell, ly, scx(p1a_d), scy(p1a_d))
    add_via1_m2(cell, ly, scx(p1b_d), scy(p1b_d))

    # M2 verticals connecting NMOS D to PMOS D
    for pd in [p1a_d, p1b_d]:
        mx = (scx(n1b_d) + scx(pd)) // 2
        cell.shapes(l_m2).insert(box(min(scx(n1b_d),scx(pd))-150, scy(n1b_d)-155,
                                     max(scx(n1b_d),scx(pd))+150, scy(pd)+155))

    # M2 horizontal connecting Mp1a.D and Mp1b.D
    cell.shapes(l_m2).insert(box(min(scx(p1a_d),scx(p1b_d))-150, scy(p1a_d)-155,
                                 max(scx(p1a_d),scx(p1b_d))+150, scy(p1a_d)+155))

    # lat_q cross-coupling: connect to Mn2b.G + Mp2b.G via M1 in gap
    lat_q_y = nmos_top + 1200  # moved up to avoid Cnt.b with comp_outp contacts
    # Via1 from lat_q M2 to M1 at lat_q_y
    lat_q_via_x = scx(n1b_d)
    add_via1_m2(cell, ly, lat_q_via_x, lat_q_y)
    cell.shapes(l_m2).insert(box(lat_q_via_x-150, scy(n1b_d)-155,
                                 lat_q_via_x+150, lat_q_y+155))

    # Gate contacts for Mn2b and Mp2b at lat_q_y
    for dev_name in ['Mn2b', 'Mp2b']:
        g = D[dev_name]['gates'][0]
        gx = (g[0]+g[1])//2
        gw = g[1]-g[0]
        if g[3] < lat_q_y:
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, lat_q_y+250))
        else:
            cell.shapes(l_po).insert(box(gx-gw//2, lat_q_y-250, gx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(gx-80, lat_q_y-80, gx+80, lat_q_y+80))
        cell.shapes(l_m1).insert(box(gx-155, lat_q_y-155, gx+155, lat_q_y+155))

    # M1 horizontal bus for lat_q cross-coupling
    all_lat_q_x = [lat_q_via_x, gcx(D['Mn2b']), gcx(D['Mp2b'])]
    cell.shapes(l_m1).insert(box(min(all_lat_q_x)-155, lat_q_y-155,
                                 max(all_lat_q_x)+155, lat_q_y+155))
    print(f'  lat_q: M2 drains + M1 cross-coupling y={lat_q_y}')

    # ─── 4. lat_qb: Mn2b.D + Mp2a.D + Mp2b.D + Mn1b.G + Mp1b.G ───
    n2b_d = D['Mn2b']['strips'][-1]
    p2a_d = D['Mp2a']['strips'][-1]
    p2b_d = D['Mp2b']['strips'][-1]

    add_via1_m2(cell, ly, scx(n2b_d), scy(n2b_d))
    add_via1_m2(cell, ly, scx(p2a_d), scy(p2a_d))
    add_via1_m2(cell, ly, scx(p2b_d), scy(p2b_d))

    for pd in [p2a_d, p2b_d]:
        cell.shapes(l_m2).insert(box(min(scx(n2b_d),scx(pd))-150, scy(n2b_d)-155,
                                     max(scx(n2b_d),scx(pd))+150, scy(pd)+155))
    cell.shapes(l_m2).insert(box(min(scx(p2a_d),scx(p2b_d))-150, scy(p2a_d)-155,
                                 max(scx(p2a_d),scx(p2b_d))+150, scy(p2a_d)+155))

    lat_qb_y = nmos_top + 1800  # above lat_q with spacing
    lat_qb_via_x = scx(n2b_d)
    add_via1_m2(cell, ly, lat_qb_via_x, lat_qb_y)
    cell.shapes(l_m2).insert(box(lat_qb_via_x-150, scy(n2b_d)-155,
                                 lat_qb_via_x+150, lat_qb_y+155))

    # Stagger Mn1b/Mp1b contacts (gates only 80nm apart in x)
    lat_qb_y_n = lat_qb_y
    lat_qb_y_p = lat_qb_y + 500
    for dev_name, cy in [('Mn1b', lat_qb_y_n), ('Mp1b', lat_qb_y_p)]:
        g = D[dev_name]['gates'][0]
        gx = (g[0]+g[1])//2
        gw = g[1]-g[0]
        if g[3] < cy:
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, cy+250))
        else:
            cell.shapes(l_po).insert(box(gx-gw//2, cy-250, gx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(gx-80, cy-80, gx+80, cy+80))
        cell.shapes(l_m1).insert(box(gx-155, cy-155, gx+155, cy+155))

    # Connect: Via1(right) → M1 vertical up → M1 horizontal → gate contacts(left)
    mn1b_gx = gcx(D['Mn1b'])
    mp1b_gx = gcx(D['Mp1b'])
    # Via1 vertical from y_n to y_p
    cell.shapes(l_m1).insert(box(lat_qb_via_x-155, lat_qb_y_n-155, lat_qb_via_x+155, lat_qb_y_p+155))
    # Mn1b gate vertical from y_n to y_p
    cell.shapes(l_m1).insert(box(mn1b_gx-155, lat_qb_y_n-155, mn1b_gx+155, lat_qb_y_p+155))
    # Horizontal at y_p connecting all
    cell.shapes(l_m1).insert(box(min(lat_qb_via_x, mn1b_gx, mp1b_gx)-155, lat_qb_y_p-155,
                                 max(lat_qb_via_x, mn1b_gx, mp1b_gx)+155, lat_qb_y_p+155))
    print(f'  lat_qb: M2 drains + M1 cross-coupling y={lat_qb_y}')

    # ─── 5. comp_outp: Mn1a.G + Mp1a.G (staggered y to avoid Cnt.b) ───
    def add_gate_bus_staggered(nmos_name, pmos_name, y_n, y_p, label):
        """Add gate bus with staggered contacts for NMOS/PMOS to avoid Cnt.b."""
        for dev_name, cy in [(nmos_name, y_n), (pmos_name, y_p)]:
            g = D[dev_name]['gates'][0]
            gx = (g[0]+g[1])//2
            gw = g[1]-g[0]
            if g[3] < cy:
                cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, cy+250))
            else:
                cell.shapes(l_po).insert(box(gx-gw//2, cy-250, gx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gx-80, cy-80, gx+80, cy+80))
            cell.shapes(l_m1).insert(box(gx-155, cy-155, gx+155, cy+155))
        # L-shape M1 bus connecting staggered contacts
        nx = gcx(D[nmos_name])
        px = gcx(D[pmos_name])
        cell.shapes(l_m1).insert(box(nx-155, y_n-155, nx+155, y_p+155))  # vertical
        cell.shapes(l_m1).insert(box(min(nx,px)-155, y_p-155, max(nx,px)+155, y_p+155))  # horizontal
        print(f'  {label}: y_n={y_n}, y_p={y_p}')

    add_gate_bus_staggered('Mn1a', 'Mp1a', nmos_top+300, nmos_top+700, 'comp_outp')

    # ─── 6. comp_outn: Mn2a.G + Mp2a.G ───
    add_gate_bus_staggered('Mn2a', 'Mp2a', nmos_top+300, nmos_top+700, 'comp_outn')

    # ─── 7. GND: Mn1a.S + Mn2a.S ───
    gnd_y = min(D[n]['bbox'][1] for n in ['Mn1a','Mn2a']) - 800
    gnd_strips = [D['Mn1a']['strips'][0], D['Mn2a']['strips'][0]]
    for s in gnd_strips:
        cell.shapes(l_m1).insert(box(scx(s)-80, gnd_y, scx(s)+80, s[2]))
    cell.shapes(l_m1).insert(box(min(scx(s) for s in gnd_strips)-155, gnd_y-155,
                                 max(scx(s) for s in gnd_strips)+155, gnd_y+155))
    print(f'  gnd: y={gnd_y}')

    # ─── 8. VDD: all PMOS S + ntap ───
    vdd_strips = []
    for pn in ['Mp1a','Mp1b','Mp2a','Mp2b']:
        vdd_strips.append(D[pn]['strips'][0])  # S = strip[0]
    vdd_y = pmos_top + 500
    cell.shapes(l_m1).insert(box(min(scx(s) for s in vdd_strips)-155, vdd_y-155,
                                 max(scx(s) for s in vdd_strips)+155, vdd_y+500))
    for s in vdd_strips:
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, vdd_y-155))
    print(f'  vdd: y={vdd_y}')

    # ─── Write + DRC ───
    out = os.path.join(OUT_DIR, 'hbridge.gds')
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
