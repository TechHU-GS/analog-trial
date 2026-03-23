#!/usr/bin/env python3
"""Build BIAS MN module — PCell instantiation + routing.

Circuit:
    MN_diode: S=gnd, D=nmos_bias, G=nmos_bias (diode-connected)
    MN_pgen:  S=gnd, G=nmos_bias, D=pmos_bias

Uses IHP SG13G2 PCell API (not flat GDS extraction).
Device params from sim/_soilz_full.sp:
    MN_diode: sg13_lv_nmos W=1u L=2u ng=1
    MN_pgen:  sg13_lv_nmos W=1u L=2u ng=1

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_bias_mn.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Layer definitions (IHP SG13G2)
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
M1 = (8, 0)
PSD = (14, 0)
M2 = (10, 0)
VIA1 = (19, 0)

# DRC rule values (nm)
M1_MIN_W = 160
M1_MIN_S = 180
M2_MIN_W = 210
M2_MIN_S = 210
CNT_A = 160
VIA1_SIZE = 190


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def probe_strips(pcell, ly, layer_pair):
    """Find S/D strip bboxes in PCell (tall M1 rectangles), sorted by x."""
    li = ly.find_layer(*layer_pair)
    if li is None:
        return []
    strips = []
    for si in pcell.begin_shapes_rec(li):
        b = si.shape().bbox()
        if b.height() > 500:  # S/D strips are tall
            strips.append(b)
    strips.sort(key=lambda b: b.left)
    return strips


def probe_gates(pcell, ly):
    """Find gate poly bboxes in PCell (tall poly crossing active), sorted by x."""
    li = ly.find_layer(*GATPOLY)
    if li is None:
        return []
    gates = []
    for si in pcell.begin_shapes_rec(li):
        b = si.shape().bbox()
        if b.height() > 500:
            gates.append(b)
    gates.sort(key=lambda b: b.left)
    return gates


def build():
    print('=== Building BIAS MN (PCell instantiation) ===')

    ly = pya.Layout()
    ly.dbu = 0.001
    cell = ly.create_cell('bias_mn')

    # ─── Step 1: Create NMOS PCell ───
    print('\n--- Step 1: PCell creation ---')
    pcell = ly.create_cell("nmos", "SG13_dev", {
        "l": 2e-6,   # L=2um
        "w": 1e-6,   # W=1um
        "ng": 1
    })

    bb = pcell.bbox()
    print(f'  PCell bbox: ({bb.left},{bb.bottom})-({bb.right},{bb.top})')
    print(f'  PCell size: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um')

    # Probe PCell geometry
    m1_strips = probe_strips(pcell, ly, M1)
    gates = probe_gates(pcell, ly)
    print(f'  M1 strips: {len(m1_strips)}')
    for i, s in enumerate(m1_strips):
        print(f'    [{i}] ({s.left},{s.bottom})-({s.right},{s.top})')
    print(f'  Gate polys: {len(gates)}')
    for i, g in enumerate(gates):
        print(f'    [{i}] ({g.left},{g.bottom})-({g.right},{g.top})')

    if len(m1_strips) < 2 or len(gates) < 1:
        print('  ERROR: PCell geometry unexpected, aborting')
        return None

    # S = leftmost strip, D = rightmost strip, G = gate
    s_strip = m1_strips[0]
    d_strip = m1_strips[-1]
    gate = gates[0]

    # ─── Step 2: Place devices ───
    print('\n--- Step 2: Place MN_diode + MN_pgen ---')

    # Offset to place PCell origin at (0,0) relative to its bottom-left
    ox = -bb.left
    oy = -bb.bottom

    gap = 3000  # nm gap between devices
    x_pgen = bb.width() + gap  # x offset for second device

    cell.insert(pya.CellInstArray(pcell.cell_index(),
                pya.Trans(0, False, ox, oy)))
    cell.insert(pya.CellInstArray(pcell.cell_index(),
                pya.Trans(0, False, ox + x_pgen, oy)))

    # Absolute coordinates helper
    def abs_d(rel_box):
        """Absolute coords for MN_diode (first instance)."""
        return (rel_box.left + ox, rel_box.right + ox,
                rel_box.bottom + oy, rel_box.top + oy)

    def abs_p(rel_box):
        """Absolute coords for MN_pgen (second instance)."""
        return (rel_box.left + ox + x_pgen, rel_box.right + ox + x_pgen,
                rel_box.bottom + oy, rel_box.top + oy)

    sd = abs_d(s_strip)  # MN_diode source (xl, xr, yb, yt)
    dd = abs_d(d_strip)  # MN_diode drain
    gd = abs_d(gate)     # MN_diode gate

    sp = abs_p(s_strip)  # MN_pgen source
    dp = abs_p(d_strip)  # MN_pgen drain
    gp = abs_p(gate)     # MN_pgen gate

    print(f'  MN_diode: S=x({sd[0]}-{sd[1]}), D=x({dd[0]}-{dd[1]}), G=x({gd[0]}-{gd[1]})')
    print(f'  MN_pgen:  S=x({sp[0]}-{sp[1]}), D=x({dp[0]}-{dp[1]}), G=x({gp[0]}-{gp[1]})')

    # ─── Step 3: Ptap ties + GND bus ───
    print('\n--- Step 3: Ptap ties + GND bus ---')
    l_m1 = ly.layer(*M1)
    l_activ = ly.layer(*ACTIV)
    l_cont = ly.layer(*CONT)
    l_psd = ly.layer(*PSD)
    l_poly = ly.layer(*GATPOLY)
    l_m2 = ly.layer(*M2)
    l_via1 = ly.layer(*VIA1)

    total_w = bb.width() + x_pgen  # full module width
    ptap_y1 = -1500
    ptap_y2 = -1000

    # GND M1 bus
    cell.shapes(l_m1).insert(box(0, ptap_y1, total_w, ptap_y2))
    print(f'  GND bus: (0,{ptap_y1})-({total_w},{ptap_y2})')

    # Two ptap ties (centered under each device)
    dev_cx_d = (sd[0] + dd[1]) // 2  # center of MN_diode
    dev_cx_p = (sp[0] + dp[1]) // 2  # center of MN_pgen
    for ptap_cx in [dev_cx_d, dev_cx_p]:
        cell.shapes(l_activ).insert(box(ptap_cx - 250, ptap_y1, ptap_cx + 250, ptap_y2))
        cell.shapes(l_m1).insert(box(ptap_cx - 250, ptap_y1, ptap_cx + 250, ptap_y2))
        cell.shapes(l_psd).insert(box(ptap_cx - 350, ptap_y1 - 100, ptap_cx + 350, ptap_y2 + 100))
        cell.shapes(l_cont).insert(box(ptap_cx - 80, (ptap_y1 + ptap_y2) // 2 - 80,
                                       ptap_cx + 80, (ptap_y1 + ptap_y2) // 2 + 80))

    # Source strip extensions down to GND bar
    cell.shapes(l_m1).insert(box(sd[0], ptap_y2, sd[1], sd[2]))  # MN_diode.S
    cell.shapes(l_m1).insert(box(sp[0], ptap_y2, sp[1], sp[2]))  # MN_pgen.S
    print(f'  Source ext MN_diode: x=({sd[0]}-{sd[1]})')
    print(f'  Source ext MN_pgen: x=({sp[0]}-{sp[1]})')

    # ─── Step 4: Gate poly extensions + contacts ───
    print('\n--- Step 4: Gate contacts ---')

    gate_bot = gd[2]  # bottom of gate poly (abs)
    ext_bot = gate_bot - 500  # extend 500nm down
    gate_w = gate.width()
    gcx_d = (gd[0] + gd[1]) // 2  # gate center x for MN_diode
    gcx_p = (gp[0] + gp[1]) // 2  # gate center x for MN_pgen

    # Poly extensions
    cell.shapes(l_poly).insert(box(gcx_d - gate_w // 2, ext_bot, gcx_d + gate_w // 2, gate_bot))
    cell.shapes(l_poly).insert(box(gcx_p - gate_w // 2, ext_bot, gcx_p + gate_w // 2, gate_bot))

    # Gate contacts + M1 pads
    cont_cy = ext_bot + 250  # center of contact in extension
    for gcx in [gcx_d, gcx_p]:
        cell.shapes(l_cont).insert(box(gcx - 80, cont_cy - 80, gcx + 80, cont_cy + 80))
        cell.shapes(l_m1).insert(box(gcx - 155, cont_cy - 155, gcx + 155, cont_cy + 155))
    print(f'  Gate contacts at y≈{cont_cy}, MN_diode x={gcx_d}, MN_pgen x={gcx_p}')

    # ─── Step 5: Diode connection (MN_diode.D ↔ G via M1) ───
    print('\n--- Step 5: Diode connection ---')
    pad_y1 = cont_cy - 155
    pad_y2 = cont_cy + 155
    # M1 bridge from gate pad to drain strip
    cell.shapes(l_m1).insert(box(gcx_d - 155, pad_y1, dd[1], pad_y2))
    # Drain strip extension down to bridge
    cell.shapes(l_m1).insert(box(dd[0], pad_y2, dd[1], dd[2]))
    print(f'  M1 bridge: ({gcx_d - 155},{pad_y1})-({dd[1]},{pad_y2})')

    # ─── Step 6: nmos_bias M2 route ───
    print('\n--- Step 6: nmos_bias M2 route ---')

    # Via1 on diode bridge (between gate and drain)
    via1_d_x = (gcx_d + dd[0]) // 2 - VIA1_SIZE // 2
    via1_y = cont_cy - VIA1_SIZE // 2
    cell.shapes(l_via1).insert(box(via1_d_x, via1_y,
                                   via1_d_x + VIA1_SIZE, via1_y + VIA1_SIZE))

    # Via1 on MN_pgen gate pad
    via1_p_x = gcx_p - VIA1_SIZE // 2
    cell.shapes(l_via1).insert(box(via1_p_x, via1_y,
                                   via1_p_x + VIA1_SIZE, via1_y + VIA1_SIZE))

    # M2 route connecting both Via1s
    m2_enc = 55  # M2 enclosure of Via1
    m2_y1 = via1_y - m2_enc
    m2_y2 = via1_y + VIA1_SIZE + m2_enc
    m2_x1 = via1_d_x - 100
    m2_x2 = via1_p_x + VIA1_SIZE + 100
    cell.shapes(l_m2).insert(box(m2_x1, m2_y1, m2_x2, m2_y2))
    print(f'  Via1 diode: x={via1_d_x}, Via1 pgen: x={via1_p_x}')
    print(f'  M2 nmos_bias: ({m2_x1},{m2_y1})-({m2_x2},{m2_y2})')
    print(f'  M2 width: {(m2_y2 - m2_y1)/1000:.3f}um')

    # ─── Step 7: Net labels (for LVS port matching) ───
    print('\n--- Step 7: Net labels ---')
    # GND on M1 bus
    cell.shapes(l_m1).insert(pya.Text('gnd', pya.Trans(total_w // 2, (ptap_y1 + ptap_y2) // 2)))
    # nmos_bias on M2 route
    cell.shapes(l_m2).insert(pya.Text('nmos_bias', pya.Trans((m2_x1 + m2_x2) // 2, (m2_y1 + m2_y2) // 2)))
    # pmos_bias on MN_pgen drain strip (M1)
    cell.shapes(l_m1).insert(pya.Text('pmos_bias', pya.Trans((dp[0] + dp[1]) // 2, (dp[2] + dp[3]) // 2)))
    print('  Labels: gnd(M1), nmos_bias(M2), pmos_bias(M1)')

    # ─── Output ───
    out_path = os.path.join(OUT_DIR, 'bias_mn.gds')
    ly.write(out_path)

    bb_out = cell.bbox()
    print(f'\n  Output: {bb_out.width()/1000:.1f}x{bb_out.height()/1000:.1f}um')
    print(f'  Written: {out_path}')

    # ─── Quick DRC (on flattened copy) ───
    flat = ly.create_cell('_drc_check')
    flat.copy_tree(cell)
    flat.flatten(True)

    li_m1 = ly.find_layer(*M1)
    m1_region = pya.Region(flat.begin_shapes_rec(li_m1))
    print(f'\n  Quick DRC: M1.b(space)={m1_region.space_check(M1_MIN_S).count()}'
          f', M1.a(width)={m1_region.width_check(M1_MIN_W).count()}')

    li_m2 = ly.find_layer(*M2)
    if li_m2 is not None:
        m2_region = pya.Region(flat.begin_shapes_rec(li_m2))
        print(f'  Quick DRC: M2.b(space)={m2_region.space_check(M2_MIN_S).count()}'
              f', M2.a(width)={m2_region.width_check(M2_MIN_W).count()}')

    flat.delete()
    return out_path


if __name__ == '__main__':
    build()
    print('\n=== Done ===')
