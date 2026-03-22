#!/usr/bin/env python3
"""Module-level netlist verification (mini-LVS).

Method:
  1. Read GDS → find M1 strips (PCell S/D) + gate poly
  2. Group strips into devices using gate positions
  3. Match GDS devices to netlist devices (by x-position order)
  4. Merge M1 → find M1-connected pin groups
  5. Find Via1 → merge M2 → find M2-bridged pin groups
  6. Compare connectivity against netlist.json expected nets

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/mini_lvs.py hbridge
    python3 modular/mini_lvs.py --all
"""

import klayout.db as pya
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

M1_LN = (8, 0)
M2_LN = (10, 0)
VIA1_LN = (19, 0)
POLY_LN = (5, 0)

STRIP_H_MIN = 800
GATE_W_MIN = 400
GATE_W_MAX = 5000

# Module → netlist device names (sorted by expected x-position in GDS)
MODULE_MAP = {
    'bias_mn': ['MN_diode', 'MN_pgen'],
    'chopper': ['Mchop1n', 'Mchop1p', 'Mchop2n', 'Mchop2p'],
    'dac_sw': ['Mdac_tg1n', 'Mdac_tg1p', 'Mdac_tg2n', 'Mdac_tg2p'],
    'sw': ['SW1n', 'SW1p', 'SW2n', 'SW2p', 'SW3n', 'SW3p'],
    'ota': ['Min_p', 'Mbias_d', 'Mp_load_p', 'Mtail', 'Min_n', 'Mp_load_n', 'M_bias_mir'],
    'comp': ['Mc_rst_dp', 'Mc_inp', 'Mc_lp1', 'Mc_rst_dn', 'Mc_ln1',
             'Mc_tail', 'Mc_inn', 'Mc_ln2', 'Mc_lp2', 'Mc_rst_op', 'Mc_rst_on'],
    'bias_cascode': ['PM_cas_ref', 'PM_mir1', 'PM_cas_diode', 'PM_mir2',
                     'PM_cas1', 'PM_mir3', 'PM_cas2', 'MN_cas_load', 'PM_cas3'],
    'hbridge': ['Mn1a', 'Mp1a', 'Mn1b', 'Mp1b', 'Mn2b', 'Mp2b', 'Mn2a', 'Mp2a'],
    'hbridge_drive': ['MS1', 'MS2', 'MS3', 'MS4'],
    'vco_buffer': ['MBn1', 'MBp1', 'MBn2', 'MBp2'],
    'ptat_core': ['PM3', 'PM4', 'PM5', 'PM_ref', 'PM_pdiode', 'MN1', 'MN2'],
    'nol': ['M_inv0_n', 'M_inv0_p', 'M_da1_p', 'M_da2_p', 'M_da1_n', 'M_da2_n',
            'M_na_p1', 'M_na_n1', 'M_na_p2', 'M_na_n2', 'M_ia_p', 'M_ia_n',
            'M_db1_n', 'M_db1_p', 'M_db2_n', 'M_db2_p',
            'M_nb_n1', 'M_nb_p1', 'M_nb_n2', 'M_nb_p2', 'M_ib_n', 'M_ib_p'],
}

# Devices with X-flip (S/D swapped vs normal left=S right=D)
MODULE_FLIPS = {
    'hbridge': {'Mn2a', 'Mn2b', 'Mp2a', 'Mp2b'},
}

# Power nets — disconnect is expected (deferred to assembly)
POWER_NETS = {'vdd', 'gnd', 'VDD', 'GND'}


def load_netlist():
    with open(os.path.join(LAYOUT_DIR, 'netlist.json')) as f:
        nj = json.load(f)
    devices = {d['name']: d for d in nj.get('devices', [])}
    nets = nj.get('nets', [])
    return devices, nets


def get_module_nets(module_name, nets):
    """Get nets with ≥2 module-internal S/D pins."""
    dev_names = set(MODULE_MAP.get(module_name, []))
    result = {}
    for net in nets:
        name = net.get('name', '')
        pins = net.get('pins', [])
        internal = [p for p in pins if p.split('.')[0] in dev_names]
        sd_internal = [p for p in internal if not p.endswith('.G')]
        if len(sd_internal) >= 2:
            result[name] = {'all': internal, 'sd': sd_internal}
    return result


def probe_gds(gds_path):
    ly = pya.Layout()
    ly.read(gds_path)
    cell = ly.top_cell()

    def get_region(ln, dt):
        li = ly.find_layer(ln, dt)
        return pya.Region(cell.begin_shapes_rec(li)) if li is not None else pya.Region()

    m1_all = get_region(*M1_LN)
    m2_all = get_region(*M2_LN)
    poly_all = get_region(*POLY_LN)
    via1_all = get_region(*VIA1_LN)

    strips = []
    for p in m1_all.each():
        b = p.bbox()
        if 140 <= b.width() <= 250 and b.height() >= STRIP_H_MIN:
            strips.append({
                'bbox': b, 'cx': (b.left + b.right) // 2, 'cy': (b.bottom + b.top) // 2,
                'x_range': (b.left, b.right), 'y_range': (b.bottom, b.top),
            })

    gates = []
    for p in poly_all.each():
        b = p.bbox()
        if GATE_W_MIN <= b.width() <= GATE_W_MAX and b.height() >= STRIP_H_MIN:
            gates.append({
                'bbox': b, 'cx': (b.left + b.right) // 2, 'cy': (b.bottom + b.top) // 2,
                'y_range': (b.bottom, b.top),
            })

    via1_pos = []
    for p in via1_all.each():
        b = p.bbox()
        via1_pos.append({'cx': (b.left + b.right) // 2, 'cy': (b.bottom + b.top) // 2})

    return strips, gates, m1_all.merged(), m2_all.merged(), via1_pos


def group_strips_to_devices(strips, gates, expected_count=0):
    """Pair strips into devices. If expected_count > 0, keep best N by overlap quality."""
    candidates = []
    for g in gates:
        gx1, gx2 = g['bbox'].left, g['bbox'].right
        gy1, gy2 = g['y_range']
        left = right = None
        for idx, s in enumerate(strips):
            sy1, sy2 = s['y_range']
            overlap = min(sy2, gy2) - max(sy1, gy1)
            if overlap < 500:
                continue
            if s['cx'] < gx1 and (left is None or s['cx'] > strips[left]['cx']):
                left = idx
            elif s['cx'] > gx2 and (right is None or s['cx'] < strips[right]['cx']):
                right = idx
        if left is not None and right is not None:
            # Quality: average y-overlap of gate with both strips
            ov_l = min(strips[left]['y_range'][1], gy2) - max(strips[left]['y_range'][0], gy1)
            ov_r = min(strips[right]['y_range'][1], gy2) - max(strips[right]['y_range'][0], gy1)
            quality = (ov_l + ov_r) / 2
            candidates.append({
                'si': (left, right), 'gate': g,
                'cx': (strips[left]['cx'] + strips[right]['cx']) // 2,
                'cy': g['cy'], 'quality': quality,
            })

    # Sort by quality (best first), then greedily pick non-overlapping strip pairs
    candidates.sort(key=lambda d: -d['quality'])
    devices = []
    used = set()
    for c in candidates:
        l, r = c['si']
        if l in used or r in used:
            continue
        devices.append(c)
        used.add(l)
        used.add(r)
        if expected_count > 0 and len(devices) >= expected_count:
            break
    return devices


def build_connectivity(strips, m1_merged, m2_merged, via1_pos):
    n = len(strips)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for rpoly in m1_merged.each():
        grp = [i for i, s in enumerate(strips) if rpoly.inside(pya.Point(s['cx'], s['cy']))]
        for i in range(1, len(grp)):
            union(grp[0], grp[i])

    # Match Via1 to strips via merged M1 regions (not direct coordinate overlap)
    # If Via1 and strip are in the same merged M1 region, they're connected
    strip_to_region = {}
    for ri, rpoly in enumerate(m1_merged.each()):
        for idx, s in enumerate(strips):
            if rpoly.inside(pya.Point(s['cx'], s['cy'])):
                strip_to_region[idx] = ri

    v1map = {}
    for vi, v in enumerate(via1_pos):
        vpt = pya.Point(v['cx'], v['cy'])
        for ri, rpoly in enumerate(m1_merged.each()):
            if rpoly.inside(vpt):
                # Find which strip is in this same region
                for idx, sr in strip_to_region.items():
                    if sr == ri:
                        v1map[vi] = idx
                        break
                break

    for rpoly in m2_merged.each():
        grp = [v1map[vi] for vi, v in enumerate(via1_pos)
               if vi in v1map and rpoly.inside(pya.Point(v['cx'], v['cy']))]
        for i in range(1, len(grp)):
            union(grp[0], grp[i])

    return find


def match_devices(gds_devices, module_name, strips):
    """Match GDS devices to netlist names by (cy, cx) sort order.
    Returns {strip_index: 'DevName.S/D'}."""
    nl_names = MODULE_MAP.get(module_name, [])
    sorted_devs = sorted(gds_devices, key=lambda d: (d['cx'], d['cy']))
    flips = MODULE_FLIPS.get(module_name, set())
    pin_map = {}
    for i, dev in enumerate(sorted_devs):
        name = nl_names[i] if i < len(nl_names) else f'dev{i}'
        si_l, si_r = dev['si']  # left strip, right strip
        if name in flips:
            pin_map[si_l] = f'{name}.D'  # flipped: left=D
            pin_map[si_r] = f'{name}.S'  # flipped: right=S
        else:
            pin_map[si_l] = f'{name}.S'
            pin_map[si_r] = f'{name}.D'
    return pin_map


def run_mini_lvs(module_name):
    gds_path = os.path.join(OUT_DIR, f'{module_name}.gds')
    if not os.path.exists(gds_path):
        return 1, [f'  ERROR: {gds_path} not found']

    report = []
    _, nl_nets = load_netlist()
    module_nets = get_module_nets(module_name, nl_nets)

    strips, gates, m1m, m2m, v1pos = probe_gds(gds_path)
    expected = len(MODULE_MAP.get(module_name, []))
    gds_devs = group_strips_to_devices(strips, gates, expected)
    report.append(f'  Strips={len(strips)} Gates={len(gates)} Via1={len(v1pos)} Devices={len(gds_devs)}/{expected}')

    if not gds_devs:
        return 1, report + ['  ERROR: no devices found']

    pin_map = match_devices(gds_devs, module_name, strips)
    find = build_connectivity(strips, m1m, m2m, v1pos)

    # Reverse map: pin_name → strip_index
    name_to_idx = {v: k for k, v in pin_map.items()}

    n_ok = n_disc = n_short = n_defer = 0

    # Check expected connections
    for net_name, info in sorted(module_nets.items()):
        sd_pins = info['sd']
        indices = [name_to_idx[p] for p in sd_pins if p in name_to_idx]
        if len(indices) < 2:
            continue
        roots = set(find(i) for i in indices)
        if len(roots) == 1:
            n_ok += 1
        elif net_name in POWER_NETS:
            n_defer += 1
        else:
            n_disc += 1
            report.append(f'  DISCONNECT: "{net_name}" — {sd_pins} in {len(roots)} groups')

    # Check for shorts between different nets
    net_roots = {}
    for net_name, info in module_nets.items():
        indices = [name_to_idx[p] for p in info['sd'] if p in name_to_idx]
        if indices:
            net_roots[net_name] = find(indices[0])

    checked = set()
    for n1, r1 in net_roots.items():
        for n2, r2 in net_roots.items():
            if n1 >= n2:
                continue
            pair = (n1, n2)
            if pair in checked:
                continue
            checked.add(pair)
            if r1 == r2:
                n_short += 1
                report.append(f'  SHORT: "{n1}" ↔ "{n2}"')

    report.insert(1, f'  Nets: {len(module_nets)} checked, {n_ok} OK, {n_disc} disconnect, {n_short} short')

    return n_disc + n_short, report


def main():
    if len(sys.argv) < 2 or sys.argv[1] == '--all':
        modules = list(MODULE_MAP.keys())
    else:
        modules = sys.argv[1:]

    print(f'=== Mini-LVS: {len(modules)} modules ===\n')
    results = {}
    for mod in modules:
        print(f'── {mod} ──')
        n_err, report = run_mini_lvs(mod)
        for line in report:
            print(line)
        results[mod] = n_err
        print()

    n_pass = sum(1 for v in results.values() if v == 0)
    print(f'=== Summary: {n_pass}/{len(results)} pass ===')
    for mod, errs in results.items():
        s = '✓' if errs == 0 else f'✗ ({errs} errors)'
        print(f'  {s} {mod}')


if __name__ == '__main__':
    main()
