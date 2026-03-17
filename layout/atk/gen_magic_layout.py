#!/usr/bin/env python3
"""Generate Magic layout from placement/routing JSON data.

Two-phase approach (getcell doesn't work in batch mode):
  Phase A: Magic Tcl creates device subcells (.mag files)
  Phase B: Python writes soilz.mag (use statements + metal geometry)
  Phase C: Magic Tcl loads soilz, runs DRC + extract + ext2spice + GDS

Usage:
    cd layout && python3 -m atk.gen_magic_layout
    cd /tmp/magic_soilz && bash run_magic.sh
"""

import json
import os
import re
import time

SCALE = 10  # 1 Magic unit = 10nm; our pipeline uses nm


def nm(val):
    return int(round(val / SCALE))


def _build_smart_filter(netlist, placement, device_lib_magic_path=None):
    """Build data structures for smart routing filter.

    Uses device_lib_magic.json bboxes (centered on PCell origin) for accurate
    overlap detection in Magic coordinate system.

    Returns (device_bboxes, net_devices) where:
      device_bboxes: dict dev_name → (x1_nm, y1_nm, x2_nm, y2_nm)
      net_devices:   dict net_name → set of device names on that net
    """
    instances = placement.get('instances', {})

    # Load Magic device bboxes if available
    magic_lib = {}
    if device_lib_magic_path and os.path.exists(device_lib_magic_path):
        with open(device_lib_magic_path) as f:
            magic_lib = json.load(f)

    # Device bboxes in nm — use Magic centered bbox + placement origin
    device_bboxes = {}
    for name, inst in instances.items():
        dev_type = inst.get('type', '')
        x = int(round(inst.get('x_um', 0) * 1000))  # PCell origin in nm
        y = int(round(inst.get('y_um', 0) * 1000))

        magic_info = magic_lib.get(dev_type)
        if magic_info and 'bbox' in magic_info:
            bb = magic_info['bbox']  # [x1, y1, x2, y2] centered on origin
            device_bboxes[name] = (x + bb[0], y + bb[1], x + bb[2], y + bb[3])
        else:
            # Fallback to placement w/h
            w = int(round(inst.get('w_um', 0) * 1000))
            h = int(round(inst.get('h_um', 0) * 1000))
            if w > 0 and h > 0:
                device_bboxes[name] = (x, y, x + w, y + h)

    # Net → set of device names
    net_devices = {}
    for net in netlist.get('nets', []):
        devs = set()
        for pin in net.get('pins', []):
            dev_name = pin.split('.')[0]
            devs.add(dev_name)
        net_devices[net['name']] = devs

    return device_bboxes, net_devices


def _seg_overlaps_wrong_device(seg_bbox, net_name, device_bboxes, net_devices):
    """Check if segment bbox overlaps any device NOT on net_name."""
    allowed = net_devices.get(net_name, set())
    sx1, sy1, sx2, sy2 = seg_bbox
    for dev_name, (dx1, dy1, dx2, dy2) in device_bboxes.items():
        if dev_name in allowed:
            continue
        if sx2 > dx1 and sx1 < dx2 and sy2 > dy1 and sy1 < dy2:
            return True
    return False


def convert_spice_for_netgen(input_path, output_path):
    """Convert Magic ext2spice output (X-format) to Netgen-compatible M/R/C format.

    Magic ext2spice outputs X (subcircuit) instances with S,G,D,B pin order.
    Netgen expects M (MOSFET) with D,G,S,B order for proper device recognition.
    """
    with open(input_path) as f:
        lines = f.readlines()

    out = []
    stats = {'nmos': 0, 'pmos': 0, 'rhigh': 0, 'cap': 0}

    for line in lines:
        if not line.startswith('X'):
            out.append(line)
            continue

        parts = line.split()
        inst_num = parts[0][1:]

        if 'sg13_lv_nmos' in parts or 'sg13_lv_pmos' in parts:
            model = 'sg13_lv_nmos' if 'sg13_lv_nmos' in parts else 'sg13_lv_pmos'
            s, g, d, b = parts[1], parts[2], parts[3], parts[4]
            w_val = l_val = ''
            for p in parts:
                if p.startswith('w='):
                    w_val = p.split('=')[1]
                elif p.startswith('l='):
                    l_val = p.split('=')[1]
            out.append(f'M{inst_num} {d} {g} {s} {b} {model} W={w_val} L={l_val}\n')
            stats['nmos' if model == 'sg13_lv_nmos' else 'pmos'] += 1

        elif 'rhigh' in parts:
            pin_a, pin_b = parts[1], parts[2]
            w_val = l_val = ''
            for p in parts:
                if p.startswith('w='):
                    w_val = p.split('=')[1]
                elif p.startswith('l='):
                    l_val = p.split('=')[1]
            out.append(f'R{inst_num} {pin_a} {pin_b} rhigh W={w_val} L={l_val}\n')
            stats['rhigh'] += 1

        elif 'cap_cmim' in parts:
            pin1, pin2 = parts[1], parts[2]
            w_val = l_val = ''
            for p in parts:
                if p.startswith('w='):
                    w_val = p.split('=')[1]
                elif p.startswith('l='):
                    l_val = p.split('=')[1]
            out.append(f'C{inst_num} {pin1} {pin2} cap_cmim W={w_val} L={l_val}\n')
            stats['cap'] += 1
        else:
            out.append(line)

    with open(output_path, 'w') as f:
        f.writelines(out)

    return stats


def generate(netlist_path='netlist.json',
             placement_path='placement.json',
             routing_path='output/routing.json',
             device_lib_path='atk/data/device_lib.json',
             output_dir='/tmp/magic_soilz'):

    with open(netlist_path) as f:
        netlist = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)
    with open(routing_path) as f:
        routing = json.load(f)
    with open(device_lib_path) as f:
        device_lib = json.load(f)

    os.makedirs(output_dir, exist_ok=True)
    devices = netlist['devices']
    instances = placement.get('instances', {})

    # ═══ Device type → Magic PCell ═══
    def get_pcell(dev):
        dtype = dev['type']
        lib = device_lib.get(dtype, {})
        pcell = lib.get('pcell_name', '')
        cls = lib.get('class', '')
        params = lib.get('params', {})
        if pcell in ('sg13_lv_nmos',) or cls == 'nmos' or 'nmos' in dtype:
            return 'nmos', params
        elif pcell in ('sg13_lv_pmos',) or cls == 'pmos' or 'pmos' in dtype:
            return 'pmos', params
        elif pcell in ('rhigh',) or cls == 'resistor' or 'rhigh' in dtype:
            return 'rhigh', params
        elif pcell in ('cap_cmim', 'cmim') or 'cap' in dtype or 'cmim' in dtype:
            return 'cap_cmim', params
        return None, params

    # ═══ Phase A: Tcl script for device subcells ═══
    tcl_a = ['# Phase A: Create device subcells',
             'source /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.tcl',
             '']

    cell_map = {}  # dev_name → cell_name
    for dev in devices:
        name = dev['name']
        kind, params = get_pcell(dev)
        if not kind:
            tcl_a.append(f'# SKIP: {name} ({dev["type"]})')
            continue

        cell_name = f'dev_{name}'.lower().replace('.', '_')
        cell_map[name] = cell_name

        tcl_a.append(f'load {cell_name} -force')
        w = params.get('w', 0.5)
        l = params.get('l', 0.13)

        if kind == 'nmos':
            nf = params.get('nf', 1)
            m = params.get('m', 1)
            tcl_a.append(f'sg13g2::sg13_lv_nmos_draw [dict merge '
                         f'[sg13g2::sg13_lv_nmos_defaults] '
                         f'{{w {w} l {l} nf {nf} m {m}}}]')
        elif kind == 'pmos':
            nf = params.get('nf', 1)
            m = params.get('m', 1)
            tcl_a.append(f'sg13g2::sg13_lv_pmos_draw [dict merge '
                         f'[sg13g2::sg13_lv_pmos_defaults] '
                         f'{{w {w} l {l} nf {nf} m {m}}}]')
        elif kind == 'rhigh':
            b = params.get('b', 1)
            tcl_a.append(f'sg13g2::rhigh_draw [dict merge '
                         f'[sg13g2::rhigh_defaults] '
                         f'{{w {w} l {l} b {b}}}]')
        elif kind == 'cap_cmim':
            tcl_a.append(f'sg13g2::cap_cmim_draw [dict merge '
                         f'[sg13g2::cap_cmim_defaults] '
                         f'{{w {w} l {l}}}]')

        tcl_a.append(f'save {cell_name}')
        tcl_a.append('')

    tcl_a.append(f'puts "Created {len(cell_map)} device subcells"')
    tcl_a.append('exit')

    with open(os.path.join(output_dir, 'phase_a.tcl'), 'w') as f:
        f.write('\n'.join(tcl_a) + '\n')

    # ═══ Phase B: Write soilz.mag directly ═══
    mag = ['magic', 'tech ihp-sg13g2', f'timestamp {int(time.time())}']

    # Use statements for device placement
    placed = 0
    for dev in devices:
        name = dev['name']
        cell_name = cell_map.get(name)
        if not cell_name:
            continue
        inst = instances.get(name, {})
        x = int(round(inst.get('x_um', inst.get('x', 0)) * 100))
        y = int(round(inst.get('y_um', inst.get('y', 0)) * 100))
        inst_name = f'{cell_name}_0'
        # .mag format: use + transform + box on separate lines
        mag.append(f'use {cell_name} {inst_name}')
        mag.append(f'transform 1 0 {x} 0 1 {y}')
        mag.append(f'box 0 0 1 1')
        placed += 1

    # Metal routing
    WIRE_HW = {0: 150, 1: 150, 2: 150, 3: 150}  # nm
    VIA_HS = {-1: 100, -2: 100, -3: 100}  # 100nm → 200nm via, avoids 180nm rounding
    LAYER_NAME = {0: 'metal1', 1: 'metal2', 2: 'metal3', 3: 'metal4',
                  -1: 'via1', -2: 'via2', -3: 'via3'}

    # Smart routing filter: skip segments overlapping wrong-device bboxes
    magic_lib_path = os.path.join(os.path.dirname(device_lib_path),
                                  'device_lib_magic.json')
    dev_bboxes, net_devs = _build_smart_filter(netlist, placement,
                                               magic_lib_path)

    seg_count = 0
    seg_filtered = 0
    current_layer = None

    def emit_layer(layer_name):
        nonlocal current_layer
        if layer_name != current_layer:
            mag.append(f'<< {layer_name} >>')
            current_layer = layer_name

    # Signal routing
    for net_name, route in routing.get('signal_routes', {}).items():
        for seg in route.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, lyr = seg[:5]
            layer_name = LAYER_NAME.get(lyr)
            if not layer_name:
                continue

            # Compute segment bbox for smart filter check
            if lyr >= 0:
                hw = WIRE_HW.get(lyr, 150)
                if x1 == x2:
                    seg_bbox = (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
                else:
                    seg_bbox = (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)
            else:
                hs = VIA_HS.get(lyr, 95)
                seg_bbox = (x1 - hs, y1 - hs, x1 + hs, y1 + hs)

            # Skip segment if it overlaps a device NOT on this net
            if _seg_overlaps_wrong_device(seg_bbox, net_name,
                                          dev_bboxes, net_devs):
                seg_filtered += 1
                continue

            if lyr >= 0:
                if x1 == x2:
                    emit_layer(layer_name)
                    mag.append(f'rect {nm(x1-hw)} {nm(min(y1,y2))} '
                               f'{nm(x1+hw)} {nm(max(y1,y2))}')
                else:
                    emit_layer(layer_name)
                    mag.append(f'rect {nm(min(x1,x2))} {nm(y1-hw)} '
                               f'{nm(max(x1,x2))} {nm(y1+hw)}')
            else:
                hs = VIA_HS.get(lyr, 95)
                emit_layer(layer_name)
                mag.append(f'rect {nm(x1-hs)} {nm(y1-hs)} '
                           f'{nm(x1+hs)} {nm(y1+hs)}')
            seg_count += 1

    # Power rails (M3)
    for rail_name, rail in routing.get('power', {}).get('rails', {}).items():
        y = rail['y']
        x1, x2 = rail['x1'], rail['x2']
        hw = rail['width'] // 2
        emit_layer('metal3')
        mag.append(f'rect {nm(min(x1,x2))} {nm(y-hw)} '
                   f'{nm(max(x1,x2))} {nm(y+hw)}')

    # Power drops (M3 vbars + via stacks)
    drop_count = 0
    for drop in routing.get('power', {}).get('drops', []):
        vbar = drop.get('m3_vbar')
        if vbar:
            vx1, vy1, vx2, vy2 = vbar
            vhw = 100
            emit_layer('metal3')
            if vx1 == vx2:
                mag.append(f'rect {nm(vx1-vhw)} {nm(min(vy1,vy2))} '
                           f'{nm(vx1+vhw)} {nm(max(vy1,vy2))}')
            else:
                mag.append(f'rect {nm(min(vx1,vx2))} {nm(vy1-vhw)} '
                           f'{nm(max(vx1,vx2))} {nm(vy1+vhw)}')
            drop_count += 1
        vx = drop.get('via_x')
        vy = drop.get('via_y')
        if vx and vy:
            for via in ['via1', 'via2']:
                emit_layer(via)
                mag.append(f'rect {nm(vx-95)} {nm(vy-95)} '
                           f'{nm(vx+95)} {nm(vy+95)}')

    # AP via stacks + M1 stubs connecting device pins to AP via locations
    ap_count = 0
    stub_count = 0
    for pin_key, ap in routing.get('access_points', {}).items():
        px, py = ap['x'], ap['y']
        via_pad = ap.get('via_pad', {})
        if via_pad:
            emit_layer('via1')
            mag.append(f'rect {nm(px-100)} {nm(py-100)} {nm(px+100)} {nm(py+100)}')
            m1 = via_pad.get('m1')
            if m1:
                emit_layer('metal1')
                mag.append(f'rect {nm(m1[0])} {nm(m1[1])} {nm(m1[2])} {nm(m1[3])}')
            m2 = via_pad.get('m2')
            if m2:
                emit_layer('metal2')
                mag.append(f'rect {nm(m2[0])} {nm(m2[1])} {nm(m2[2])} {nm(m2[3])}')
        # M1 stub: bridges device pin M1 to AP via1 M1 pad
        m1_stub = ap.get('m1_stub')
        if m1_stub:
            emit_layer('metal1')
            mag.append(f'rect {nm(m1_stub[0])} {nm(m1_stub[1])} '
                       f'{nm(m1_stub[2])} {nm(m1_stub[3])}')
            stub_count += 1
        # M2 stub: for m2_below mode (bridges via M2 pad to PCell M2)
        m2_stub = ap.get('m2_stub')
        if m2_stub:
            emit_layer('metal2')
            mag.append(f'rect {nm(m2_stub[0])} {nm(m2_stub[1])} '
                       f'{nm(m2_stub[2])} {nm(m2_stub[3])}')
        ap_count += 1

    mag.append('<< end >>')

    with open(os.path.join(output_dir, 'soilz.mag'), 'w') as f:
        f.write('\n'.join(mag) + '\n')

    # ═══ Phase C: Tcl script for DRC + flat extract (for Netgen LVS) ═══
    tcl_c = ['# Phase C: Load, flatten, DRC, Extract',
             'load soilz',
             'select top cell',
             '',
             '# Flatten for clean extraction',
             'flatten soilz_flat',
             'load soilz_flat',
             'select top cell',
             '',
             'drc check',
             'drc catchup',
             'puts "DRC errors: [drc list count total]"',
             '',
             'extract unique',
             'extract all',
             'ext2spice lvs',
             'ext2spice',
             'puts "SPICE: soilz_flat.spice"',
             '',
             '# Also write GDS from hierarchical cell',
             'load soilz',
             'gds write soilz_magic.gds',
             'puts "GDS: soilz_magic.gds"',
             'puts "=== DONE ==="',
             'exit']

    with open(os.path.join(output_dir, 'phase_c.tcl'), 'w') as f:
        f.write('\n'.join(tcl_c) + '\n')

    # ═══ Run script ═══
    magic_cmd = ('CAD_ROOT=$HOME/.local/lib $HOME/.local/bin/magic '
                 '-noconsole -dnull '
                 '-T ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2')

    ref_spice = os.path.abspath('soilz_lvs.spice')
    setup_tcl = os.path.expanduser(
        '~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/netgen/ihp-sg13g2_setup.tcl')
    netgen_cmd = '~/.local/lib/netgen/tcl/netgenexec'

    run = ['#!/bin/bash',
           'set -e',
           f'cd {output_dir}',
           '',
           'echo "=== Phase A: Device subcells ==="',
           f'{magic_cmd} < phase_a.tcl 2>&1 | tail -3',
           '',
           'echo "=== Phase B: soilz.mag written by Python ==="',
           f'echo "  $(wc -l < soilz.mag) lines"',
           '',
           'echo "=== Phase C: DRC + Extract ==="',
           f'{magic_cmd} < phase_c.tcl 2>&1 | grep -E "DRC|SPICE|GDS|DONE|Extracting|error"',
           '',
           'echo "=== Phase D: SPICE conversion (X→M format) ==="',
           f'python3 -c "',
           f'import sys; sys.path.insert(0, \\"{os.path.abspath(".")}\\");',
           f'from atk.gen_magic_layout import convert_spice_for_netgen;',
           f's = convert_spice_for_netgen(\\"soilz_flat.spice\\", \\"soilz_netgen.spice\\");',
           f'print(f\\"  Converted: {{s}}\\")',
           f'"',
           '',
           'echo "=== Phase E: Netgen LVS ==="',
           f'echo "source ~/.local/lib/netgen/tcl/netgen.tcl',
           f'set setup_file {setup_tcl}',
           f'lvs {{soilz_netgen.spice soilz_flat}} {{{ref_spice} soilz}} \\$setup_file comp.out',
           f'quit" | {netgen_cmd} 2>&1 | grep -E "Merged|Mismatch|instances|Number of|Final|Result"',
           '',
           'echo "=== Results ==="',
           'wc -l soilz_flat.spice 2>/dev/null || echo "No SPICE output"',
           'grep -c "sg13_lv\\|rhigh\\|cap_cmim" soilz_flat.spice 2>/dev/null || echo 0',
           'echo "devices extracted"',
           'ls -la soilz_magic.gds 2>/dev/null || echo "No GDS"']

    with open(os.path.join(output_dir, 'run_magic.sh'), 'w') as f:
        f.write('\n'.join(run) + '\n')
    os.chmod(os.path.join(output_dir, 'run_magic.sh'), 0o755)

    print(f'  Output: {output_dir}')
    print(f'  Devices: {placed}')
    print(f'  Routing: {seg_count} segments ({seg_filtered} filtered by smart filter)')
    print(f'  Power drops: {drop_count}')
    print(f'  AP via stacks: {ap_count}')
    print(f'  soilz.mag: {len(mag)} lines')
    print(f'  Run: cd {output_dir} && bash run_magic.sh')


if __name__ == '__main__':
    generate()
