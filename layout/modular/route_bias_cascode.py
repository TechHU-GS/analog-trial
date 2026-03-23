#!/usr/bin/env python3
"""Route bias_cascode: 9 devices in 3 bands.

Band layout:
  y=0:  MN_cas_load (NMOS, vcas diode)
  y=6:  PM_cas_diode + PM_cas1/2/3 (cascode PMOS)
  y=14: PM_cas_ref + PM_mir1/2/3 (mirror PMOS)

Nets:
  vcas:    MN_cas_load.D/G + PM_cas_diode.D/G + PM_cas1/2/3.G
  cas_ref: PM_cas_diode.S + PM_cas_ref.D
  cas1:    PM_cas1.S + PM_mir1.D
  cas2:    PM_cas2.S + PM_mir2.D
  cas3:    PM_cas3.S + PM_mir3.D
  net_c1:  PM_cas_ref.G + PM_mir1/2/3.G (external gate bias)
  vdd:     PM_cas_ref.S + PM_mir1/2/3.S
  gnd:     MN_cas_load.S
  src1/2/3: PM_cas1/2/3.D (external outputs)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/route_bias_cascode.py
"""
import klayout.db as pya
import os, sys, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from build_module import build_module, box

OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
M1, M2, VIA1, CONT, POLY = (8,0), (10,0), (19,0), (6,0), (5,0)


def add_via1_m2(cell, ly, cx, cy):
    """Add Via1+M1 pad+M2 pad at (cx, cy) nm."""
    cell.shapes(ly.layer(*M1)).insert(box(cx-155, cy-155, cx+155, cy+155))
    cell.shapes(ly.layer(*VIA1)).insert(box(cx-95, cy-95, cx+95, cy+95))
    cell.shapes(ly.layer(*M2)).insert(box(cx-245, cy-155, cx+245, cy+155))


def route():
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    ly, cell, devs = build_module('bias_cascode', mods['bias_cascode'])
    D = {d['name']: d for d in devs}

    l_m1 = ly.layer(*M1)
    l_m2 = ly.layer(*M2)
    l_v1 = ly.layer(*VIA1)
    l_ct = ly.layer(*CONT)
    l_po = ly.layer(*POLY)

    # Identify gap zones
    # Band 1 (NMOS): MN_cas_load only
    nmos_top = D['MN_cas_load']['bbox'][3]
    # Band 2 (cascode PMOS): y=6000 area
    cas_bot = min(D[n]['bbox'][1] for n in ['PM_cas_diode','PM_cas1','PM_cas2','PM_cas3'])
    cas_top = max(D[n]['bbox'][3] for n in ['PM_cas_diode','PM_cas1','PM_cas2','PM_cas3'])
    # Band 3 (mirror PMOS): y=14000 area
    mir_bot = min(D[n]['bbox'][1] for n in ['PM_cas_ref','PM_mir1','PM_mir2','PM_mir3'])
    mir_top = max(D[n]['bbox'][3] for n in ['PM_cas_ref','PM_mir1','PM_mir2','PM_mir3'])

    gap1_mid = (nmos_top + cas_bot) // 2   # between NMOS and cascode
    gap2_mid = (cas_top + mir_bot) // 2     # between cascode and mirror

    print(f'\n--- Routing bias_cascode ---')
    print(f'  Gap1: y={nmos_top}-{cas_bot} (mid={gap1_mid})')
    print(f'  Gap2: y={cas_top}-{mir_bot} (mid={gap2_mid})')

    # ─── Helper: get S/D strip centers ───
    def strip_s(d):
        """First S strip center (x, y)."""
        s = d['strips'][0] if d['strips'] else None
        return ((s[0]+s[1])//2, (s[2]+s[3])//2) if s else None

    def strip_d(d):
        """First D strip center (x, y)."""
        strips = d['strips']
        d_list = [strips[i] for i in range(1, len(strips), 2)]
        return ((d_list[0][0]+d_list[0][1])//2, (d_list[0][2]+d_list[0][3])//2) if d_list else None

    def gate_cx(d):
        """First gate center x."""
        return (d['gates'][0][0]+d['gates'][0][1])//2 if d['gates'] else None

    # ─── 1. cas_ref, cas1, cas2, cas3: cascode.S ↔ mirror.D via M2 vertical ───
    print('\n  --- Cascode-Mirror M2 verticals ---')
    cas_mir_pairs = [
        ('PM_cas_diode', 'PM_cas_ref', 'cas_ref'),
        ('PM_cas1', 'PM_mir1', 'cas1'),
        ('PM_cas2', 'PM_mir2', 'cas2'),
        ('PM_cas3', 'PM_mir3', 'cas3'),
    ]

    # Route each pair: M2 vertical on each strip, M1 horizontal in gap2
    # Put cas routes at BOTTOM of gap2, net_c1 gate bus at TOP (avoid crossing)
    gap2_routes_y = cas_top + 500  # start just above cascode row
    for idx, (cas_name, mir_name, net_name) in enumerate(cas_mir_pairs):
        cas_s = strip_s(D[cas_name])
        mir_d = strip_d(D[mir_name])
        if not cas_s or not mir_d:
            print(f'  {net_name}: SKIP (missing strip)')
            continue

        # Via1+M2 on cascode S strip
        add_via1_m2(cell, ly, cas_s[0], cas_s[1])
        # Via1+M2 on mirror D strip
        add_via1_m2(cell, ly, mir_d[0], mir_d[1])

        # M2 vertical from cascode S up to gap2
        route_y = gap2_routes_y + idx * 500  # staggered y for each route
        cell.shapes(l_m2).insert(box(cas_s[0]-150, cas_s[1]-155, cas_s[0]+150, route_y+155))
        # Via1 at top of M2 → M1
        add_via1_m2(cell, ly, cas_s[0], route_y)

        # M2 vertical from mirror D down to gap2
        cell.shapes(l_m2).insert(box(mir_d[0]-150, route_y-155, mir_d[0]+150, mir_d[1]+155))
        # Via1 at bottom of M2 → M1
        add_via1_m2(cell, ly, mir_d[0], route_y)

        # M1 horizontal in gap2 connecting the two Via1s
        cell.shapes(l_m1).insert(box(min(cas_s[0], mir_d[0])-155, route_y-155,
                                     max(cas_s[0], mir_d[0])+155, route_y+155))

        print(f'  {net_name}: {cas_name}.S({cas_s[0]}) → M1@y={route_y} → {mir_name}.D({mir_d[0]})')

    # ─── 2. vcas: MN_cas_load.D/G + PM_cas_diode.D/G + PM_cas1/2/3.G ───
    print('\n  --- vcas ---')
    # MN_cas_load now has 2S 1G (after strip threshold fix)
    # Diode: G=D=vcas, S=gnd
    mn_gate = D['MN_cas_load']['gates']
    mn_d = strip_d(D['MN_cas_load'])  # D strip for vcas
    mn_s = strip_s(D['MN_cas_load'])  # S strip for GND
    cas_diode_d = strip_d(D['PM_cas_diode'])

    # MN_cas_load.D → vcas: M1 bridge + Contact on gate (diode connection)
    if mn_d and mn_gate:
        mn_dcx, mn_dcy = mn_d
        mn_gcx_local = gate_cx(D['MN_cas_load'])
        # M1 horizontal bridge at D strip y level
        cell.shapes(l_m1).insert(box(min(mn_dcx, mn_gcx_local)-155, mn_dcy-155,
                                     max(mn_dcx, mn_gcx_local)+155, mn_dcy+155))
        # Contact on gate poly at bridge position (connects M1 bridge to GatPoly)
        cell.shapes(l_ct).insert(box(mn_gcx_local-80, mn_dcy-80, mn_gcx_local+80, mn_dcy+80))
        print(f'  vcas diode MN: D({mn_dcx}) ↔ G({mn_gcx_local}) M1+Cont bridge')

    # MN_cas_load.S → GND: extend S strip to ptap
    if mn_s:
        mn_scx, mn_scy = mn_s
        ptap_y = D['MN_cas_load']['bbox'][1] - 800
        cell.shapes(l_m1).insert(box(mn_scx-80, ptap_y, mn_scx+80, mn_scy))
        print(f'  GND: MN_cas_load.S({mn_scx}) → ptap y={ptap_y}')

    if mn_gate and cas_diode_d:
        # MN gate center
        mn_gcx = gate_cx(D['MN_cas_load'])
        # PM_cas_diode.D center
        cd_cx, cd_cy = cas_diode_d

        # Extend MN gate poly up into gap1, add Contact
        g = mn_gate[0]
        gw = g[1] - g[0]
        mn_cont_y = gap1_mid
        cell.shapes(l_po).insert(box(mn_gcx-gw//2, g[3], mn_gcx+gw//2, mn_cont_y+250))
        cell.shapes(l_ct).insert(box(mn_gcx-80, mn_cont_y-80, mn_gcx+80, mn_cont_y+80))
        cell.shapes(l_m1).insert(box(mn_gcx-155, mn_cont_y-155, mn_gcx+155, mn_cont_y+155))

        # Via1 on MN gate M1 → M2
        add_via1_m2(cell, ly, mn_gcx, mn_cont_y)

        # Via1 on PM_cas_diode.D → M2
        add_via1_m2(cell, ly, cd_cx, cd_cy)

        # M2 vertical/L-shape connecting MN gate to PM_cas_diode.D
        cell.shapes(l_m2).insert(box(mn_gcx-150, mn_cont_y-155, mn_gcx+150, cd_cy+155))
        if abs(mn_gcx - cd_cx) > 300:
            cell.shapes(l_m2).insert(box(min(mn_gcx,cd_cx)-150, cd_cy-155,
                                         max(mn_gcx,cd_cx)+150, cd_cy+155))
        print(f'  vcas: MN_cas_load.G({mn_gcx}) → PM_cas_diode.D({cd_cx}) M2')

    # PM_cas_diode.G (diode: G=D, need Contact on gate connecting to D)
    cd_gate = D['PM_cas_diode']['gates']
    if cd_gate and cas_diode_d:
        g = cd_gate[0]
        gcx = (g[0]+g[1])//2
        gw = g[1]-g[0]
        # Extend gate down into gap2 area between cas and mir
        cont_y = g[2] - 300  # just below gate bottom
        cell.shapes(l_po).insert(box(gcx-gw//2, cont_y-250, gcx+gw//2, g[2]))
        cell.shapes(l_ct).insert(box(gcx-80, cont_y-80, gcx+80, cont_y+80))
        cell.shapes(l_m1).insert(box(gcx-155, cont_y-155, gcx+155, cont_y+155))
        # M1 bridge from gate contact to D strip (diode connection)
        cd_cx = cas_diode_d[0]
        cell.shapes(l_m1).insert(box(min(gcx,cd_cx)-155, cont_y-155,
                                     max(gcx,cd_cx)+155, cont_y+155))
        print(f'  vcas diode: PM_cas_diode.G({gcx}) ↔ D({cd_cx}) M1')

    # PM_cas1/2/3.G: gate bus for vcas
    # All cascode gates should connect to vcas
    vcas_gate_y = gap1_mid + 500  # in gap1, above MN connection
    vcas_gate_xs = []
    for cas_name in ['PM_cas_diode', 'PM_cas1', 'PM_cas2', 'PM_cas3']:
        gates = D[cas_name]['gates']
        for g in gates:
            gcx = (g[0]+g[1])//2
            gw = g[1]-g[0]
            # Extend gate down into gap1
            cell.shapes(l_po).insert(box(gcx-gw//2, vcas_gate_y-250, gcx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gcx-80, vcas_gate_y-80, gcx+80, vcas_gate_y+80))
            cell.shapes(l_m1).insert(box(gcx-155, vcas_gate_y-155, gcx+155, vcas_gate_y+155))
            vcas_gate_xs.append(gcx)

    if vcas_gate_xs:
        # M1 horizontal bus connecting all vcas gate contacts
        cell.shapes(l_m1).insert(box(min(vcas_gate_xs)-155, vcas_gate_y-155,
                                     max(vcas_gate_xs)+155, vcas_gate_y+155))
        # Connect MN vcas (via M2 above) to this gate bus
        # Via1 from gate bus to M2
        bus_via_x = vcas_gate_xs[0]  # leftmost gate = PM_cas_diode gate
        add_via1_m2(cell, ly, bus_via_x, vcas_gate_y)
        print(f'  vcas gate bus: y={vcas_gate_y}, x={min(vcas_gate_xs)}-{max(vcas_gate_xs)}')

    # ─── 3. net_c1: PM_cas_ref.G + PM_mir1/2/3.G (gate bus in gap2) ───
    print('\n  --- net_c1 gate bus ---')
    c1_gate_y = mir_bot - 500  # top of gap2, away from cas M1 routes
    c1_xs = []
    for mir_name in ['PM_cas_ref', 'PM_mir1', 'PM_mir2', 'PM_mir3']:
        gates = D[mir_name]['gates']
        for g in gates:
            gcx = (g[0]+g[1])//2
            gw = g[1]-g[0]
            cell.shapes(l_po).insert(box(gcx-gw//2, c1_gate_y-250, gcx+gw//2, g[2]))
            cell.shapes(l_ct).insert(box(gcx-80, c1_gate_y-80, gcx+80, c1_gate_y+80))
            cell.shapes(l_m1).insert(box(gcx-155, c1_gate_y-155, gcx+155, c1_gate_y+155))
            c1_xs.append(gcx)

    if c1_xs:
        cell.shapes(l_m1).insert(box(min(c1_xs)-155, c1_gate_y-155,
                                     max(c1_xs)+155, c1_gate_y+155))
        print(f'  net_c1: y={c1_gate_y}, x={min(c1_xs)}-{max(c1_xs)}')

    # ─── 4. vdd: mirror S strips bus ───
    print('\n  --- VDD bus ---')
    vdd_strips = []
    for mir_name in ['PM_cas_ref', 'PM_mir1', 'PM_mir2', 'PM_mir3']:
        s = strip_s(D[mir_name])
        if s:
            vdd_strips.append(s)
    # Additional S strips for ng=2 devices
    for mir_name in ['PM_mir3']:
        strips = D[mir_name]['strips']
        for i in range(2, len(strips), 2):
            s = strips[i]
            vdd_strips.append(((s[0]+s[1])//2, (s[2]+s[3])//2))

    if vdd_strips:
        vdd_y = mir_top + 500
        cell.shapes(l_m1).insert(box(min(s[0] for s in vdd_strips)-155, vdd_y-155,
                                     max(s[0] for s in vdd_strips)+155, vdd_y+155))
        for sx, sy in vdd_strips:
            # Extend S strip to VDD bus
            cell.shapes(l_m1).insert(box(sx-80, sy, sx+80, vdd_y-155))
        # Extend to ntap
        ntap_y = mir_top + 500
        cell.shapes(l_m1).insert(box(min(s[0] for s in vdd_strips)-155, vdd_y-155,
                                     max(s[0] for s in vdd_strips)+155, ntap_y+500))
        print(f'  VDD: y={vdd_y}')

    # ─── 5. GND: MN_cas_load.S ───
    print('\n  --- GND ---')
    # MN_cas_load has 0 strips (W=0.5 too small), connect via ptap
    # The ptap is already placed by build_module
    print(f'  GND: connected via ptap')

    # ─── Write + DRC ───
    out = os.path.join(OUT_DIR, 'bias_cascode.gds')
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
