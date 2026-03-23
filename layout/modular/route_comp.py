#!/usr/bin/env python3
"""Route comp: StrongARM, staircase 2-column layout.

Each column: vertically stacked devices with x offset per row.
Routing: M2 L-shape between adjacent rows, M1 gate buses.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_comp.py
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

def m2_pair(cell, ly, l_m2, s1, s2, bus_y):
    """Connect two strips via M2 L-shape through bus_y."""
    cx1, cy1 = scx(s1), scy(s1)
    cx2, cy2 = scx(s2), scy(s2)
    add_via1_m2(cell, ly, cx1, cy1)
    add_via1_m2(cell, ly, cx2, cy2)
    # Vertical from each strip to bus_y
    cell.shapes(l_m2).insert(box(cx1-150, min(cy1,bus_y)-155, cx1+150, max(cy1,bus_y)+155))
    cell.shapes(l_m2).insert(box(cx2-150, min(cy2,bus_y)-155, cx2+150, max(cy2,bus_y)+155))
    # Horizontal bus connecting
    cell.shapes(l_m2).insert(box(min(cx1,cx2)-150, bus_y-155, max(cx1,cx2)+150, bus_y+155))

def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('comp', mods['comp'])
    D = {d['name']: d for d in devs}
    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    pmos_top = max(d['bbox'][3] for d in devs if d['type']=='pmos')
    dev_bot = min(d['bbox'][1] for d in devs)

    print('\n--- Routing comp (staircase) ---')

    # Gap y between each pair of adjacent devices
    def gap_y(d1, d2):
        return (D[d1]['bbox'][3] + D[d2]['bbox'][1]) // 2

    # ── Column 1 routing ──

    # 1. c_tail: tail.D ↔ inp.S (adjacent rows)
    g01 = gap_y('Mc_tail', 'Mc_inp')
    tail_d = [D['Mc_tail']['strips'][i] for i in range(1, len(D['Mc_tail']['strips']), 2)]
    inp_s = [D['Mc_inp']['strips'][i] for i in range(0, len(D['Mc_inp']['strips']), 2)]
    for td in tail_d:
        for ins in inp_s:
            pass  # connect all via M2 bus
    ct_strips = tail_d + inp_s
    for s in ct_strips:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),g01)-155, scx(s)+150, max(scy(s),g01)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in ct_strips)-150, g01-155,
                                 max(scx(s) for s in ct_strips)+150, g01+155))
    # Also connect inn.S from column 2
    inn_s = [D['Mc_inn']['strips'][i] for i in range(0, len(D['Mc_inn']['strips']), 2)]
    for s in inn_s:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),g01)-155, scx(s)+150, max(scy(s),g01)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in ct_strips+inn_s)-150, g01-155,
                                 max(scx(s) for s in ct_strips+inn_s)+150, g01+155))
    print(f'  c_tail: M2 y={g01}')

    # 2. c_di_p: inp.D + ln1.S + rst_dp.D
    g12 = gap_y('Mc_inp', 'Mc_ln1')
    g_rst_dp = gap_y('Mc_lp1', 'Mc_rst_dp')  # gap above lp1
    inp_d = [D['Mc_inp']['strips'][i] for i in range(1, len(D['Mc_inp']['strips']), 2)]
    ln1_s = [D['Mc_ln1']['strips'][0]]
    rst_dp_d = [D['Mc_rst_dp']['strips'][-1]]
    cdip_strips = inp_d + ln1_s + rst_dp_d
    for s in cdip_strips:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),g12)-155, scx(s)+150, max(scy(s),g12)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in cdip_strips)-150, g12-155,
                                 max(scx(s) for s in cdip_strips)+150, g12+155))
    print(f'  c_di_p: M2 y={g12}')

    # 3. c_di_n: inn.D + ln2.S + rst_dn.D (column 2)
    g12_c2 = gap_y('Mc_inn', 'Mc_ln2')
    inn_d = [D['Mc_inn']['strips'][i] for i in range(1, len(D['Mc_inn']['strips']), 2)]
    ln2_s = [D['Mc_ln2']['strips'][0]]
    rst_dn_d = [D['Mc_rst_dn']['strips'][-1]]
    cdin_strips = inn_d + ln2_s + rst_dn_d
    for s in cdin_strips:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),g12_c2)-155, scx(s)+150, max(scy(s),g12_c2)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in cdin_strips)-150, g12_c2-155,
                                 max(scx(s) for s in cdin_strips)+150, g12_c2+155))
    print(f'  c_di_n: M2 y={g12_c2}')

    # 4. comp_outp: ln1.D + lp1.D + rst_op.D (column 1)
    g23 = gap_y('Mc_ln1', 'Mc_lp1')
    coutp_strips = [D['Mc_ln1']['strips'][-1], D['Mc_lp1']['strips'][-1],
                    D['Mc_rst_op']['strips'][-1]]
    for s in coutp_strips:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),g23)-155, scx(s)+150, max(scy(s),g23)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in coutp_strips)-150, g23-155,
                                 max(scx(s) for s in coutp_strips)+150, g23+155))
    # Cross-coupling gates: ln2.G + lp2.G (column 2)
    coutp_gy = g23 + 500
    for dn in ['Mc_ln2', 'Mc_lp2']:
        g = D[dn]['gates'][0]; gx=(g[0]+g[1])//2; gw=g[1]-g[0]
        if g[3] < coutp_gy:
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, coutp_gy+250))
        else:
            cell.shapes(l_po).insert(box(gx-gw//2, coutp_gy-250, gx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(gx-80, coutp_gy-80, gx+80, coutp_gy+80))
        cell.shapes(l_m1).insert(box(gx-155, coutp_gy-155, gx+155, coutp_gy+155))
    cg = [(D[n]['gates'][0][0]+D[n]['gates'][0][1])//2 for n in ['Mc_ln2','Mc_lp2']]
    cell.shapes(l_m1).insert(box(min(cg)-155, coutp_gy-155, max(cg)+155, coutp_gy+155))
    # Connect gate bus to drain M2 via cross-column M2
    add_via1_m2(cell, ly, cg[0], coutp_gy)
    # M2 horizontal from column 2 gates to column 1 drains
    coutp_drain_x = max(scx(s) for s in coutp_strips)
    cell.shapes(l_m2).insert(box(min(coutp_drain_x, cg[0])-150, g23-155,
                                 max(coutp_drain_x, cg[0])+150, coutp_gy+155))
    print(f'  comp_outp: M2 y={g23}, gates y={coutp_gy}')

    # 5. comp_outn: ln2.D + lp2.D + rst_on.D (column 2)
    g23_c2 = gap_y('Mc_ln2', 'Mc_lp2')
    coutn_strips = [D['Mc_ln2']['strips'][-1], D['Mc_lp2']['strips'][-1],
                    D['Mc_rst_on']['strips'][-1]]
    for s in coutn_strips:
        add_via1_m2(cell, ly, scx(s), scy(s))
        cell.shapes(l_m2).insert(box(scx(s)-150, min(scy(s),g23_c2)-155, scx(s)+150, max(scy(s),g23_c2)+155))
    cell.shapes(l_m2).insert(box(min(scx(s) for s in coutn_strips)-150, g23_c2-155,
                                 max(scx(s) for s in coutn_strips)+150, g23_c2+155))
    coutn_gy = g23_c2 + 500
    for dn in ['Mc_ln1', 'Mc_lp1']:
        g = D[dn]['gates'][0]; gx=(g[0]+g[1])//2; gw=g[1]-g[0]
        if g[3] < coutn_gy:
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, coutn_gy+250))
        else:
            cell.shapes(l_po).insert(box(gx-gw//2, coutn_gy-250, gx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(gx-80, coutn_gy-80, gx+80, coutn_gy+80))
        cell.shapes(l_m1).insert(box(gx-155, coutn_gy-155, gx+155, coutn_gy+155))
    cg2 = [(D[n]['gates'][0][0]+D[n]['gates'][0][1])//2 for n in ['Mc_ln1','Mc_lp1']]
    cell.shapes(l_m1).insert(box(min(cg2)-155, coutn_gy-155, max(cg2)+155, coutn_gy+155))
    add_via1_m2(cell, ly, cg2[0], coutn_gy)
    coutn_drain_x = max(scx(s) for s in coutn_strips)
    cell.shapes(l_m2).insert(box(min(coutn_drain_x, cg2[0])-150, g23_c2-155,
                                 max(coutn_drain_x, cg2[0])+150, coutn_gy+155))
    print(f'  comp_outn: M2 y={g23_c2}, gates y={coutn_gy}')

    # 6. comp_clk: tail.G + all rst gates — M1 above PMOS
    clk_y = pmos_top + 1500
    clk_xs = []
    for dn in ['Mc_tail', 'Mc_rst_dp', 'Mc_rst_dn', 'Mc_rst_op', 'Mc_rst_on']:
        for g in D[dn]['gates']:
            gx=(g[0]+g[1])//2; gw=g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, g[3], gx+gw//2, clk_y+250))
            cell.shapes(l_ct).insert(box(gx-80, clk_y-80, gx+80, clk_y+80))
            cell.shapes(l_m1).insert(box(gx-155, clk_y-155, gx+155, clk_y+155))
            clk_xs.append(gx)
    cell.shapes(l_m1).insert(box(min(clk_xs)-155, clk_y-155, max(clk_xs)+155, clk_y+155))
    print(f'  comp_clk: M1 y={clk_y}')

    # 7. ota_out + vref_comp: diff pair gates below devices
    ota_gy = dev_bot - 500
    vref_gy = dev_bot - 1000
    for gates, gy, label in [(D['Mc_inp']['gates'], ota_gy, 'ota_out'),
                              (D['Mc_inn']['gates'], vref_gy, 'vref_comp')]:
        gxs = []
        for g in gates:
            gx=(g[0]+g[1])//2; gw=g[1]-g[0]
            cell.shapes(l_po).insert(box(gx-gw//2, gy-250, gx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gx-80, gy-80, gx+80, gy+80))
            cell.shapes(l_m1).insert(box(gx-155, gy-155, gx+155, gy+155))
            gxs.append(gx)
        cell.shapes(l_m1).insert(box(min(gxs)-155, gy-155, max(gxs)+155, gy+155))
        print(f'  {label}: M1 y={gy}')

    # 8. GND + VDD
    gnd_y = dev_bot - 1500
    n_xmin = min(d['bbox'][0] for d in devs if d['type']=='nmos')
    n_xmax = max(d['bbox'][2] for d in devs if d['type']=='nmos')
    cell.shapes(l_m1).insert(box(n_xmin, gnd_y-155, n_xmax, gnd_y+155))
    for dn in ['Mc_tail']:
        for i in range(0, len(D[dn]['strips']), 2):
            s = D[dn]['strips'][i]
            cell.shapes(l_m1).insert(box(scx(s)-80, gnd_y+155, scx(s)+80, s[2]))
    print(f'  gnd: M1 y={gnd_y}')

    vdd_y = pmos_top + 500
    p_xmin = min(d['bbox'][0] for d in devs if d['type']=='pmos')
    p_xmax = max(d['bbox'][2] for d in devs if d['type']=='pmos')
    cell.shapes(l_m1).insert(box(p_xmin, vdd_y-155, p_xmax, vdd_y+500))
    for dn in ['Mc_lp1','Mc_lp2','Mc_rst_dp','Mc_rst_dn','Mc_rst_op','Mc_rst_on']:
        s = D[dn]['strips'][0]
        cell.shapes(l_m1).insert(box(scx(s)-80, s[3], scx(s)+80, vdd_y-155))
    print(f'  vdd: M1 y={vdd_y}')

    # Write + DRC
    out = os.path.join(OUT_DIR, 'comp.gds')
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
