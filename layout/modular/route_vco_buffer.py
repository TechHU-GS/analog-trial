#!/usr/bin/env python3
"""Route VCO buffer: 2 CMOS inverters.

All internal routing in gap (y=2360-6830), no M1/Active there.
  y=3500: vco5 gate bus
  y=5000: buf1 drain+gate bus
  vco_out: M2 only

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_vco_buffer.py
"""
import klayout.db as pya
import os, sys, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from build_module import build_module, box

OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
M1, M2, VIA1, CONT, POLY = (8,0), (10,0), (19,0), (6,0), (5,0)


def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('vco_buffer', mods['vco_buffer'])
    D = {d['name']: d for d in devs}

    l_m1  = ly.layer(*M1)
    l_m2  = ly.layer(*M2)
    l_v1  = ly.layer(*VIA1)
    l_ct  = ly.layer(*CONT)
    l_po  = ly.layer(*POLY)

    # Shorthand: strip[i] = (xl, xr, yb, yt), gate[i] = same
    n1 = D['MBn1']  # nmos ng=1
    n2 = D['MBn2']  # nmos ng=2
    p1 = D['MBp1']  # pmos ng=1
    p2 = D['MBp2']  # pmos ng=2

    print('\n--- Routing (gap method) ---')

    # ────────────────────────────────────────
    # 1. vco5: MBn1.G + MBp1.G at y=3500
    # ────────────────────────────────────────
    vy = 3500
    for g in [n1['gates'][0], p1['gates'][0]]:
        cx = (g[0]+g[1])//2
        gw = g[1]-g[0]
        # Extend poly to vy
        if g[3] < vy:
            cell.shapes(l_po).insert(box(cx-gw//2, g[3], cx+gw//2, vy+80))
        else:
            cell.shapes(l_po).insert(box(cx-gw//2, vy-80, cx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(cx-80, vy-80, cx+80, vy+80))
        cell.shapes(l_m1).insert(box(cx-155, vy-155, cx+155, vy+155))

    vco5_x = sorted([(n1['gates'][0][0]+n1['gates'][0][1])//2,
                      (p1['gates'][0][0]+p1['gates'][0][1])//2])
    cell.shapes(l_m1).insert(box(vco5_x[0]-155, vy-155, vco5_x[1]+155, vy+155))
    print(f'  vco5: y={vy}, x={vco5_x[0]}-{vco5_x[1]}')

    # ────────────────────────────────────────
    # 2. buf1: drains + INV2 gates at y=5000
    # ────────────────────────────────────────
    by = 5000
    buf1_xs = []

    # MBn1.D: extend M1 up from strip top to by
    s = n1['strips'][-1]  # D strip
    cx = (s[0]+s[1])//2
    cell.shapes(l_m1).insert(box(cx-155, s[3], cx+155, by+155))
    buf1_xs.append(cx)

    # MBp1.D: extend M1 down from strip bottom to by
    p1_d = [p1['strips'][i] for i in range(1, len(p1['strips']), 2)]
    if p1_d:
        s = p1_d[0]
        cx = (s[0]+s[1])//2
        cell.shapes(l_m1).insert(box(cx-155, by-155, cx+155, s[2]))
        buf1_xs.append(cx)

    # MBn2 gates: extend poly up to by, contact at by
    for g in n2['gates']:
        cx = (g[0]+g[1])//2
        gw = g[1]-g[0]
        cell.shapes(l_po).insert(box(cx-gw//2, g[3], cx+gw//2, by+80))
        cell.shapes(l_ct).insert(box(cx-80, by-80, cx+80, by+80))
        cell.shapes(l_m1).insert(box(cx-155, by-155, cx+155, by+155))
        buf1_xs.append(cx)

    # MBp2 gates: extend poly down to by, contact at by
    for g in p2['gates']:
        cx = (g[0]+g[1])//2
        gw = g[1]-g[0]
        cell.shapes(l_po).insert(box(cx-gw//2, by-80, cx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(cx-80, by-80, cx+80, by+80))
        cell.shapes(l_m1).insert(box(cx-155, by-155, cx+155, by+155))
        buf1_xs.append(cx)

    # Horizontal M1 bus
    cell.shapes(l_m1).insert(box(min(buf1_xs)-155, by-155, max(buf1_xs)+155, by+155))
    print(f'  buf1: y={by}, x={min(buf1_xs)/1000:.1f}-{max(buf1_xs)/1000:.1f}')

    # ────────────────────────────────────────
    # 3. vco_out: MBn2.D + MBp2.D via M2
    # ────────────────────────────────────────
    n2_d = [n2['strips'][i] for i in range(1, len(n2['strips']), 2)]
    p2_d = [p2['strips'][i] for i in range(1, len(p2['strips']), 2)]
    if n2_d and p2_d:
        for s in [n2_d[0], p2_d[0]]:
            cx = (s[0]+s[1])//2
            cy = (s[2]+s[3])//2
            cell.shapes(l_m1).insert(box(cx-155, cy-155, cx+155, cy+155))
            cell.shapes(l_v1).insert(box(cx-95, cy-95, cx+95, cy+95))
            cell.shapes(l_m2).insert(box(cx-245, cy-155, cx+245, cy+155))
        # M2 vertical
        cx1 = (n2_d[0][0]+n2_d[0][1])//2
        cy1 = (n2_d[0][2]+n2_d[0][3])//2
        cx2 = (p2_d[0][0]+p2_d[0][1])//2
        cy2 = (p2_d[0][2]+p2_d[0][3])//2
        mx = (cx1+cx2)//2
        cell.shapes(l_m2).insert(box(mx-150, min(cy1,cy2)-155, mx+150, max(cy1,cy2)+155))
    print(f'  vco_out: M2 vertical')

    # ────────────────────────────────────────
    # 4. GND: NMOS S strips bus
    # ────────────────────────────────────────
    n_s = [n1['strips'][0]] + [n2['strips'][i] for i in range(0, len(n2['strips']), 2)]
    gy = min(s[2] for s in n_s) - 500
    cell.shapes(l_m1).insert(box(min(s[0] for s in n_s), gy-155,
                                 max(s[1] for s in n_s), gy+155))
    for s in n_s:
        cell.shapes(l_m1).insert(box(s[0], gy+155, s[1], s[2]))
    print(f'  GND: y={gy}')

    # ────────────────────────────────────────
    # 5. VDD: PMOS S strips bus
    # ────────────────────────────────────────
    p_s = [p1['strips'][i] for i in range(0, len(p1['strips']), 2)] + \
          [p2['strips'][i] for i in range(0, len(p2['strips']), 2)]
    vy2 = max(s[3] for s in p_s) + 500
    cell.shapes(l_m1).insert(box(min(s[0] for s in p_s), vy2-155,
                                 max(s[1] for s in p_s), vy2+155))
    for s in p_s:
        cell.shapes(l_m1).insert(box(s[0], s[3], s[1], vy2-155))
    print(f'  VDD: y={vy2}')

    # ────────────────────────────────────────
    # Write + DRC
    # ────────────────────────────────────────
    out = os.path.join(OUT_DIR, 'vco_buffer.gds')
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
