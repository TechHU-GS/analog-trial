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
import time

SCALE = 10  # 1 Magic unit = 10nm; our pipeline uses nm


def nm(val):
    return int(round(val / SCALE))


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
    VIA_HS = {-1: 95, -2: 95, -3: 95}
    LAYER_NAME = {0: 'metal1', 1: 'metal2', 2: 'metal3', 3: 'metal4',
                  -1: 'via1', -2: 'via2', -3: 'via3'}

    seg_count = 0
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

            if lyr >= 0:
                hw = WIRE_HW.get(lyr, 150)
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

    # AP via stacks
    ap_count = 0
    for pin_key, ap in routing.get('access_points', {}).items():
        px, py = ap['x'], ap['y']
        via_pad = ap.get('via_pad', {})
        emit_layer('via1')
        mag.append(f'rect {nm(px-95)} {nm(py-95)} {nm(px+95)} {nm(py+95)}')
        m1 = via_pad.get('m1')
        if m1:
            emit_layer('metal1')
            mag.append(f'rect {nm(m1[0])} {nm(m1[1])} {nm(m1[2])} {nm(m1[3])}')
        m2 = via_pad.get('m2')
        if m2:
            emit_layer('metal2')
            mag.append(f'rect {nm(m2[0])} {nm(m2[1])} {nm(m2[2])} {nm(m2[3])}')
        ap_count += 1

    mag.append('<< end >>')

    with open(os.path.join(output_dir, 'soilz.mag'), 'w') as f:
        f.write('\n'.join(mag) + '\n')

    # ═══ Phase C: Tcl script for DRC + extract ═══
    tcl_c = ['# Phase C: Load, DRC, Extract',
             'load soilz',
             'select top cell',
             'drc check',
             'drc catchup',
             'puts "DRC errors: [drc list count total]"',
             '',
             'extract unique',
             'extract all',
             'ext2spice lvs',
             'ext2spice hierarchy on',
             'ext2spice',
             'puts "SPICE: soilz.spice"',
             '',
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
           'echo "=== Results ==="',
           'wc -l soilz.spice 2>/dev/null || echo "No SPICE output"',
           'grep "sg13_lv\\|rhigh\\|cap_cmim" soilz.spice 2>/dev/null | wc -l',
           'echo "devices recognized"',
           'ls -la soilz_magic.gds 2>/dev/null || echo "No GDS"']

    with open(os.path.join(output_dir, 'run_magic.sh'), 'w') as f:
        f.write('\n'.join(run) + '\n')
    os.chmod(os.path.join(output_dir, 'run_magic.sh'), 0o755)

    print(f'  Output: {output_dir}')
    print(f'  Devices: {placed}')
    print(f'  Routing segments: {seg_count}')
    print(f'  Power drops: {drop_count}')
    print(f'  AP via stacks: {ap_count}')
    print(f'  soilz.mag: {len(mag)} lines')
    print(f'  Run: cd {output_dir} && bash run_magic.sh')


if __name__ == '__main__':
    generate()
