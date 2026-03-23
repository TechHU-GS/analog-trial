#!/usr/bin/env python3
"""Generic module builder: reads module_devices.json, PCell instantiation + ties.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_module.py -rd module=bias_mn
    klayout -n sg13g2 -zz -r modular/build_module.py -rd module=all
"""

import klayout.db as pya
import os, sys, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
DEVICES_JSON = os.path.join(SCRIPT_DIR, 'module_devices.json')

# Layers
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
M1 = (8, 0)
PSD = (14, 0)
NWELL = (31, 0)


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def nm(um):
    return int(round(um * 1000))


def build_module(module_name, devices, ly=None, ntap_offset=500, ptap_offset=800):
    """Build a bare module (PCell placement + ties). Returns (layout, cell, device_info)."""
    if ly is None:
        ly = pya.Layout()
        ly.dbu = 0.001
    cell = ly.create_cell(module_name)

    print(f'\n=== Building {module_name} ({len(devices)} devices) ===')

    # ─── Step 1: Create PCells and place ───
    print('--- Step 1: PCell placement ---')
    pcell_cache = {}  # (type, W, L, ng) -> pcell
    device_info = []  # [{name, pcell, inst, strips, gates, abs_x, abs_y}, ...]

    for dev in devices:
        name = dev['name']
        typ = dev['type']  # nmos or pmos
        w = float(dev['W'])
        l = float(dev['L'])
        ng = int(dev['ng'])
        rx = nm(dev['rel_x'])
        ry = nm(dev['rel_y'])

        # Create or reuse PCell
        cache_key = (typ, w, l, ng)
        if cache_key not in pcell_cache:
            pcell_name = 'nmos' if typ == 'nmos' else 'pmos'
            pc = ly.create_cell(pcell_name, 'SG13_dev', {
                'l': l * 1e-6, 'w': w * 1e-6, 'ng': ng
            })
            if pc is None:
                print(f'  ERROR: PCell {pcell_name} W={w}u L={l}u ng={ng} returned None')
                continue
            pcell_cache[cache_key] = pc

        pc = pcell_cache[cache_key]
        bb = pc.bbox()

        # Place at relative position (bottom-left aligned)
        ox = rx - bb.left
        oy = ry - bb.bottom
        inst = cell.insert(pya.CellInstArray(pc.cell_index(),
                           pya.Trans(0, False, ox, oy)))

        # Probe strips and gates
        li_m1 = ly.find_layer(*M1)
        li_gat = ly.find_layer(*GATPOLY)
        strips = []
        if li_m1 is not None:
            for si in pc.begin_shapes_rec(li_m1):
                b = si.shape().bbox()
                if b.height() >= 400:
                    strips.append(b)
        strips.sort(key=lambda b: b.left)
        # Deduplicate (PCell hierarchy can produce identical shapes)
        deduped = []
        for s in strips:
            if not deduped or abs(s.left - deduped[-1].left) > 50:
                deduped.append(s)
        strips = deduped

        gates = []
        if li_gat is not None:
            for si in pc.begin_shapes_rec(li_gat):
                b = si.shape().bbox()
                if b.height() >= 400:
                    gates.append(b)
        gates.sort(key=lambda b: b.left)
        # Deduplicate gates too
        deduped_g = []
        for g in gates:
            if not deduped_g or abs(g.left - deduped_g[-1].left) > 50:
                deduped_g.append(g)
        gates = deduped_g

        # Calculate absolute strip/gate positions
        def to_abs(b):
            return (b.left + ox, b.right + ox, b.bottom + oy, b.top + oy)

        abs_strips = [to_abs(s) for s in strips]
        abs_gates = [to_abs(g) for g in gates]

        info = {
            'name': name, 'type': typ, 'W': w, 'L': l, 'ng': ng,
            'abs_x': rx, 'abs_y': ry,
            'bbox': (bb.left + ox, bb.bottom + oy, bb.right + ox, bb.top + oy),
            'strips': abs_strips, 'gates': abs_gates,
            'nets': dev.get('nets', {}),
        }
        device_info.append(info)
        print(f'  {name:15s} {typ} W={w} L={l} ng={ng} -> {len(strips)}S {len(gates)}G '
              f'@ ({rx/1000:.1f},{ry/1000:.1f})')

    # ─── Step 2: Add ties ───
    print('--- Step 2: Ties ---')
    l_act = ly.layer(*ACTIV)
    l_m1 = ly.layer(*M1)
    l_cont = ly.layer(*CONT)
    l_psd = ly.layer(*PSD)
    l_nw = ly.layer(*NWELL)

    # Separate NMOS and PMOS
    nmos_devs = [d for d in device_info if d['type'] == 'nmos']
    pmos_devs = [d for d in device_info if d['type'] == 'pmos']

    # ptap for NMOS: below the lowest NMOS device
    if nmos_devs:
        n_ymin = min(d['bbox'][1] for d in nmos_devs)
        n_xmin = min(d['bbox'][0] for d in nmos_devs)
        n_xmax = max(d['bbox'][2] for d in nmos_devs)
        ptap_y = n_ymin - ptap_offset
        # Place ptaps: one every 10um, at least 1
        ptap_positions = list(range(n_xmin, n_xmax + 1, 10000))
        if not ptap_positions:
            ptap_positions = [(n_xmin + n_xmax) // 2]
        for ptap_x in ptap_positions:
            cell.shapes(l_act).insert(box(ptap_x, ptap_y, ptap_x + 500, ptap_y + 500))
            cell.shapes(l_m1).insert(box(ptap_x, ptap_y, ptap_x + 500, ptap_y + 500))
            cell.shapes(l_psd).insert(box(ptap_x - 100, ptap_y - 100, ptap_x + 600, ptap_y + 600))
            cell.shapes(l_cont).insert(box(ptap_x + 170, ptap_y + 170, ptap_x + 330, ptap_y + 330))
        print(f'  ptaps: y={ptap_y/1000:.1f}um, {len(ptap_positions)} ties')

    # ntap for PMOS: above the highest PMOS device, with NWell
    if pmos_devs:
        p_ymax = max(d['bbox'][3] for d in pmos_devs)
        p_ymin = min(d['bbox'][1] for d in pmos_devs)
        p_xmin = min(d['bbox'][0] for d in pmos_devs)
        p_xmax = max(d['bbox'][2] for d in pmos_devs)
        ntap_y = p_ymax + ntap_offset
        # NWell covering all PMOS + ntaps
        nw_margin = 310
        cell.shapes(l_nw).insert(box(p_xmin - nw_margin, p_ymin - nw_margin,
                                     p_xmax + nw_margin, ntap_y + 600))
        # Place ntaps: one every 10um, at least 1
        ntap_positions = list(range(p_xmin, p_xmax + 1, 10000))
        if not ntap_positions:
            ntap_positions = [(p_xmin + p_xmax) // 2]
        for ntap_x in ntap_positions:
            cell.shapes(l_act).insert(box(ntap_x, ntap_y, ntap_x + 500, ntap_y + 500))
            cell.shapes(l_m1).insert(box(ntap_x, ntap_y, ntap_x + 500, ntap_y + 500))
            cell.shapes(l_cont).insert(box(ntap_x + 170, ntap_y + 170, ntap_x + 330, ntap_y + 330))
        print(f'  ntaps: y={ntap_y/1000:.1f}um, {len(ntap_positions)} ties')

    # ─── Output ───
    out_path = os.path.join(OUT_DIR, f'{module_name}.gds')
    ly.write(out_path)

    bb = cell.bbox()
    print(f'  Output: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um -> {out_path}')

    # Quick DRC
    flat = ly.create_cell('_drc_tmp')
    flat.copy_tree(cell)
    flat.flatten(True)
    li_m1 = ly.find_layer(*M1)
    m1r = pya.Region(flat.begin_shapes_rec(li_m1))
    m1s = m1r.space_check(180).count()
    m1w = m1r.width_check(160).count()
    print(f'  Quick DRC: M1.b={m1s} M1.a={m1w}')
    flat.delete()

    return ly, cell, device_info


if __name__ == '__main__':
    with open(DEVICES_JSON) as f:
        all_modules = json.load(f)

    # Module name via env var (klayout -rd doesn't work for Python)
    # Usage: MODULE=bias_cascode klayout -n sg13g2 -zz -r modular/build_module.py
    #    or: MODULE=all klayout ... (explicit all)
    module_name = os.environ.get('MODULE', '')
    if not module_name:
        print('Usage: MODULE=<name|all> klayout -n sg13g2 -zz -r modular/build_module.py')
        print(f'Available: {", ".join(sorted(all_modules.keys()))}')
        sys.exit(1)

    targets = list(all_modules.keys()) if module_name == 'all' else [module_name]

    for mod in targets:
        if mod not in all_modules:
            print(f'ERROR: module {mod} not in {DEVICES_JSON}')
            continue
        ly, cell, info = build_module(mod, all_modules[mod])

    print('\n=== Done ===')
