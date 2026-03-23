#!/usr/bin/env python3
"""Module connectivity checker using Region merging across layers.

Checks M1, M2 (via Via1), and GatPoly (via Contact) connectivity.
Reports OK/OPEN/SHORT for each expected net.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/check_nets.py -rd module=vco_buffer
"""
import klayout.db as pya
import os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Expected netlists: {net: [(device, terminal), ...]}
# Terminal: S, D, G (probed on M1 for S/D, GatPoly for G)
NETLISTS = {
    'vco_buffer': {
        'buf1':    [('MBn1','D'), ('MBp1','D'), ('MBn2','G'), ('MBp2','G')],
        'vco_out': [('MBn2','D'), ('MBp2','D')],
        'vco5':    [('MBn1','G'), ('MBp1','G')],
        'GND':     [('MBn1','S'), ('MBn2','S')],
        'VDD':     [('MBp1','S'), ('MBp2','S')],
    },
    'bias_mn': {
        'nmos_bias': [('MN_diode','D'), ('MN_diode','G'), ('MN_pgen','G')],
        'pmos_bias': [('MN_pgen','D')],
        'GND':       [('MN_diode','S'), ('MN_pgen','S')],
    },
    'bias_cascode': {
        'vcas':    [('PM_cas_diode','D'), ('PM_cas_diode','G'),
                    ('PM_cas1','G'), ('PM_cas2','G'), ('PM_cas3','G')],
        'cas_ref': [('PM_cas_diode','S'), ('PM_cas_ref','D')],
        'cas1':    [('PM_cas1','S'), ('PM_mir1','D')],
        'cas2':    [('PM_cas2','S'), ('PM_mir2','D')],
        'cas3':    [('PM_cas3','S'), ('PM_mir3','D')],
        'net_c1':  [('PM_cas_ref','G'), ('PM_mir1','G'), ('PM_mir2','G'), ('PM_mir3','G')],
        'vdd':     [('PM_cas_ref','S'), ('PM_mir1','S'), ('PM_mir2','S'), ('PM_mir3','S')],
    },
    'hbridge': {
        'n1_mid':    [('Mn1a','D'), ('Mn1b','S')],
        'n2_mid':    [('Mn2a','D'), ('Mn2b','S')],
        'lat_q':     [('Mn1b','D'), ('Mp1a','D'), ('Mp1b','D'), ('Mn2b','G'), ('Mp2b','G')],
        'lat_qb':    [('Mn2b','D'), ('Mp2a','D'), ('Mp2b','D'), ('Mn1b','G'), ('Mp1b','G')],
        'comp_outp': [('Mn1a','G'), ('Mp1a','G')],
        'comp_outn': [('Mn2a','G'), ('Mp2a','G')],
        'gnd':       [('Mn1a','S'), ('Mn2a','S')],
        'vdd':       [('Mp1a','S'), ('Mp1b','S'), ('Mp2a','S'), ('Mp2b','S')],
    },
    'chopper': {
        'chop_out': [('Mchop1n','S'), ('Mchop1p','S'), ('Mchop2n','S'), ('Mchop2p','S')],
        'sens_p':   [('Mchop1n','D'), ('Mchop1p','D')],
        'sens_n':   [('Mchop2n','D'), ('Mchop2p','D')],
        'f_exc':    [('Mchop1n','G'), ('Mchop2p','G')],
        'f_exc_b':  [('Mchop1p','G'), ('Mchop2n','G')],
    },
    'dac_sw': {
        'dac_out': [('Mdac_tg1n','S'), ('Mdac_tg1p','S'), ('Mdac_tg2n','S'), ('Mdac_tg2p','S')],
        'dac_hi':  [('Mdac_tg1n','D'), ('Mdac_tg1p','D')],
        'dac_lo':  [('Mdac_tg2n','D'), ('Mdac_tg2p','D')],
        'lat_q':   [('Mdac_tg1n','G'), ('Mdac_tg2p','G')],
        'lat_qb':  [('Mdac_tg1p','G'), ('Mdac_tg2n','G')],
    },
    'hbridge_drive': {
        'probe_p':  [('MS1','S'), ('MS2','S')],
        'probe_n':  [('MS3','S'), ('MS4','S')],
        'exc_out':  [('MS1','D'), ('MS3','D')],
        'gnd':      [('MS2','D'), ('MS4','D')],
        'phi_p':    [('MS1','G'), ('MS4','G')],
        'phi_n':    [('MS2','G'), ('MS3','G')],
    },
}


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[a] = b


def get_probe_points(module_name):
    """Get terminal probe coordinates from PCell geometry.
    Returns {(dev, term): (x_nm, y_nm, 'M1'|'GatPoly'), ...}
    """
    import json
    with open(os.path.join(SCRIPT_DIR, 'module_devices.json')) as f:
        mods = json.load(f)
    if module_name not in mods:
        return {}

    tmp = pya.Layout()
    tmp.dbu = 0.001
    probes = {}
    cache = {}

    for dev in mods[module_name]:
        name, typ = dev['name'], dev['type']
        w, l, ng = float(dev['W']), float(dev['L']), int(dev['ng'])
        rx, ry = int(round(dev['rel_x'] * 1000)), int(round(dev['rel_y'] * 1000))

        key = (typ, w, l, ng)
        if key not in cache:
            pc = tmp.create_cell('nmos' if typ == 'nmos' else 'pmos', 'SG13_dev',
                                 {'l': l*1e-6, 'w': w*1e-6, 'ng': ng})
            if pc is None:
                continue
            cache[key] = pc
        pc = cache[key]
        bb = pc.bbox()
        ox, oy = rx - bb.left, ry - bb.bottom

        # M1 strips (deduped)
        li = tmp.find_layer(8, 0)
        strips = sorted([si.shape().bbox() for si in pc.begin_shapes_rec(li)
                         if si.shape().bbox().height() > 500], key=lambda b: b.left)
        deduped = []
        for s in strips:
            if not deduped or abs(s.left - deduped[-1].left) > 50:
                deduped.append(s)

        s_list = [deduped[i] for i in range(0, len(deduped), 2)]
        d_list = [deduped[i] for i in range(1, len(deduped), 2)]

        if s_list:
            s = s_list[0]
            probes[(name, 'S')] = ((s.left+s.right)//2 + ox, (s.bottom+s.top)//2 + oy, 'M1')
        if d_list:
            s = d_list[0]
            probes[(name, 'D')] = ((s.left+s.right)//2 + ox, (s.bottom+s.top)//2 + oy, 'M1')

        # Gates (deduped)
        li_g = tmp.find_layer(5, 0)
        gates = sorted([si.shape().bbox() for si in pc.begin_shapes_rec(li_g)
                        if si.shape().bbox().height() > 500], key=lambda b: b.left)
        deduped_g = []
        for g in gates:
            if not deduped_g or abs(g.left - deduped_g[-1].left) > 50:
                deduped_g.append(g)
        if deduped_g:
            g = deduped_g[0]
            probes[(name, 'G')] = ((g.left+g.right)//2 + ox, (g.bottom+g.top)//2 + oy, 'GatPoly')

    return probes


def check_module(module_name):
    if module_name not in NETLISTS:
        print(f'No netlist for {module_name}. Available: {list(NETLISTS.keys())}')
        return False

    expected = NETLISTS[module_name]
    gds = os.path.join(OUT_DIR, f'{module_name}.gds')

    ly = pya.Layout()
    ly.read(gds)
    cell = ly.top_cell()
    cell.flatten(True)

    # Get merged regions per layer
    def get_regions(ln, dt):
        li = ly.find_layer(ln, dt)
        if li is None:
            return []
        return list(pya.Region(cell.begin_shapes_rec(li)).merged().each())

    m1_polys = get_regions(8, 0)
    m2_polys = get_regions(10, 0)
    gp_polys = get_regions(5, 0)
    v1_polys = get_regions(19, 0)
    ct_polys = get_regions(6, 0)

    # Build unified connectivity with union-find
    # Each polygon gets a unique ID: (layer, index)
    uf = UnionFind()

    # Via1 connects M1 to M2
    for v in v1_polys:
        vr = pya.Region(v)
        m1_hits = [('M1', i) for i, p in enumerate(m1_polys) if not (pya.Region(p) & vr).is_empty()]
        m2_hits = [('M2', i) for i, p in enumerate(m2_polys) if not (pya.Region(p) & vr).is_empty()]
        all_hits = m1_hits + m2_hits
        for j in range(1, len(all_hits)):
            uf.union(all_hits[0], all_hits[j])

    # Contact connects GatPoly to M1
    for c in ct_polys:
        cr = pya.Region(c)
        m1_hits = [('M1', i) for i, p in enumerate(m1_polys) if not (pya.Region(p) & cr).is_empty()]
        gp_hits = [('GP', i) for i, p in enumerate(gp_polys) if not (pya.Region(p) & cr).is_empty()]
        all_hits = m1_hits + gp_hits
        for j in range(1, len(all_hits)):
            uf.union(all_hits[0], all_hits[j])

    # Get probe points
    probes = get_probe_points(module_name)

    print(f'\n=== Connectivity: {module_name} ===')

    # For each probe point, find which polygon it's inside
    def find_net(x_nm, y_nm, layer):
        pt = pya.Point(x_nm, y_nm)
        if layer == 'M1':
            for i, p in enumerate(m1_polys):
                if p.inside(pt):
                    return uf.find(('M1', i))
        elif layer == 'GatPoly':
            for i, p in enumerate(gp_polys):
                if p.inside(pt):
                    return uf.find(('GP', i))
        return None

    terminal_nets = {}
    for (dev, term), (x, y, layer) in probes.items():
        terminal_nets[(dev, term)] = find_net(x, y, layer)

    # Report
    print(f'  {"Net":12s} {"Status":8s} Terminals')
    print(f'  {"-"*65}')

    all_ok = True
    short_check = {}

    for net_name, terminals in expected.items():
        ids = set()
        details = []
        for dev, term in terminals:
            nid = terminal_nets.get((dev, term))
            tag = '?' if nid is None else str(nid)
            details.append(f'{dev}.{term}={tag}')
            if nid is not None:
                ids.add(nid)
                short_check.setdefault(nid, set()).add(net_name)

        has_none = any(terminal_nets.get((d, t)) is None for d, t in terminals)
        if has_none:
            status = '? PROBE'
            all_ok = False
        elif len(ids) == 1:
            status = '✅ OK'
        else:
            status = '❌ OPEN'
            all_ok = False
        print(f'  {net_name:12s} {status:8s} {", ".join(details)}')

    shorts = [(nid, nets) for nid, nets in short_check.items() if len(nets) > 1]
    if shorts:
        print(f'\n  ⚠️ SHORTS:')
        for nid, nets in shorts:
            print(f'    {nid} shared by: {", ".join(sorted(nets))}')
        all_ok = False

    print(f'\n  {"✅ ALL NETS OK" if all_ok else "❌ ISSUES FOUND"}')
    return all_ok


if __name__ == '__main__':
    module = os.environ.get('MODULE', 'vco_buffer')
    check_module(module)
