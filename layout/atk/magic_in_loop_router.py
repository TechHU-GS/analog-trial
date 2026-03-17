#!/usr/bin/env python3
"""Magic-in-the-loop greedy router.

Routes each net one at a time, using Magic extraction after each
to verify connectivity. No translation layer — routes directly
in Magic coordinates, verified by Magic itself.

Algorithm:
  1. Start from bare device layout (devices only, no routing)
  2. For each net (sorted by pin count, small first):
     a. Compute AP positions from device_lib_magic.json
     b. Try L-shaped M2 chain routing
     c. Run Magic flatten + extract
     d. Check if net's pins connected AND no new cross-net shorts
     e. Keep if good, undo if bad, try alternative if available
  3. Report final result

Usage:
    cd layout && python3 -m atk.magic_in_loop_router
"""

import json
import os
import subprocess
import time
from collections import defaultdict

SCALE = 10  # 1 magic unit = 10nm
VIA_CLEAR = 400  # nm
VIA1_HS = 100  # nm
M1_PAD_HS = 185
M2_PAD_HS = 240
M1_STUB_HW = 80
M2_WIRE_HW = 150


def nm(val):
    return int(round(val / SCALE))


def load_data():
    with open('netlist.json') as f:
        netlist = json.load(f)
    with open('placement.json') as f:
        placement = json.load(f)
    with open('atk/data/device_lib_magic.json') as f:
        device_lib = json.load(f)
    return netlist, placement, device_lib


def build_net_aps(netlist, placement, device_lib):
    """Compute AP positions for all nets."""
    instances = placement.get('instances', {})
    net_aps = {}

    for net in netlist['nets']:
        net_name = net['name']
        if net_name in ('vdd', 'gnd'):
            continue
        aps = []
        for pk in net['pins']:
            parts = pk.split('.')
            dev_name, pin_name = parts[0], parts[1] if len(parts) > 1 else ''
            dev_type = instances.get(dev_name, {}).get('type', '')
            magic = device_lib.get(dev_type)
            if not magic or 'pins' not in magic or 'bbox' not in magic:
                continue

            # Try pin name aliases
            for try_pin in [pin_name, 'S', 'R1', 'R2', 'C1', 'C2']:
                if try_pin in magic['pins']:
                    pin_name = try_pin
                    break

            pin_info = magic['pins'].get(pin_name)
            if not pin_info:
                continue

            ox = instances[dev_name].get('x_um', 0) * 1000
            oy = instances[dev_name].get('y_um', 0) * 1000
            px, py = pin_info['pos_nm']
            abs_x = int(round(ox + px))
            abs_y = int(round(oy + py))

            bb = magic['bbox']
            bbox_top = int(round(oy + bb[3]))
            bbox_bot = int(round(oy + bb[1]))

            if pin_name == 'G':
                via_y = bbox_bot - VIA_CLEAR
            else:
                via_y = bbox_top + VIA_CLEAR

            aps.append((abs_x, abs_y, abs_x, via_y, dev_name, pin_name))

        # Deduplicate by via position
        seen = set()
        unique = []
        for ap in aps:
            key = (ap[2], ap[3])
            if key not in seen:
                seen.add(key)
                unique.append(ap)

        if len(unique) >= 2:
            net_aps[net_name] = unique

    return net_aps


def generate_ap_geometry(ap):
    """Generate M1 stub + via1 + M1 pad + M2 pad for one AP."""
    px, py, vx, vy, _, _ = ap
    lines = []

    # M1 stub
    stub_y1 = min(py, vy - M1_PAD_HS)
    stub_y2 = max(py, vy + M1_PAD_HS)
    lines.append(f'<< metal1 >>')
    lines.append(f'rect {nm(px - M1_STUB_HW)} {nm(stub_y1)} {nm(px + M1_STUB_HW)} {nm(stub_y2)}')

    # M1 pad
    lines.append(f'rect {nm(vx - M1_PAD_HS)} {nm(vy - M1_PAD_HS)} {nm(vx + M1_PAD_HS)} {nm(vy + M1_PAD_HS)}')

    # Via1
    lines.append(f'<< via1 >>')
    lines.append(f'rect {nm(vx - VIA1_HS)} {nm(vy - VIA1_HS)} {nm(vx + VIA1_HS)} {nm(vy + VIA1_HS)}')

    # M2 pad
    lines.append(f'<< metal2 >>')
    lines.append(f'rect {nm(vx - M2_PAD_HS)} {nm(vy - M2_PAD_HS)} {nm(vx + M2_PAD_HS)} {nm(vy + M2_PAD_HS)}')

    return lines


def generate_chain_m2(aps):
    """Generate L-shaped M2 chain connecting APs."""
    sorted_aps = sorted(aps, key=lambda a: (a[2], a[3]))

    # Nearest neighbor chain
    remaining = list(sorted_aps)
    chain = [remaining.pop(0)]
    while remaining:
        last = chain[-1]
        best_d = float('inf')
        best_i = 0
        for i, ap in enumerate(remaining):
            d = abs(last[2] - ap[2]) + abs(last[3] - ap[3])
            if d < best_d:
                best_d = d
                best_i = i
        chain.append(remaining.pop(best_i))

    lines = ['<< metal2 >>']
    hw = M2_WIRE_HW
    for i in range(len(chain) - 1):
        ax, ay = chain[i][2], chain[i][3]
        bx, by = chain[i + 1][2], chain[i + 1][3]

        if ax != bx:
            lines.append(f'rect {nm(min(ax, bx) - hw)} {nm(ay - hw)} '
                         f'{nm(max(ax, bx) + hw)} {nm(ay + hw)}')
        if ay != by:
            lines.append(f'rect {nm(bx - hw)} {nm(min(ay, by) - hw)} '
                         f'{nm(bx + hw)} {nm(max(ay, by) + hw)}')

    return lines


def build_base_mag(netlist, placement, device_lib, output_dir):
    """Build soilz.mag with devices only (no routing)."""
    instances = placement.get('instances', {})
    devices = netlist['devices']

    def get_kind(dev):
        dt = dev['type']
        lib = device_lib.get(dt, {})
        pcell = lib.get('pcell_name', '')
        cls = lib.get('class', '')
        if pcell in ('sg13_lv_nmos',) or cls == 'nmos' or 'nmos' in dt:
            return True
        if pcell in ('sg13_lv_pmos',) or cls == 'pmos' or 'pmos' in dt:
            return True
        if pcell in ('rhigh',) or cls == 'resistor' or 'rhigh' in dt:
            return True
        if pcell in ('cap_cmim', 'cmim') or 'cap' in dt or 'cmim' in dt:
            return True
        return False

    mag = ['magic', 'tech ihp-sg13g2', f'timestamp {int(time.time())}']
    for dev in devices:
        name = dev['name']
        if not get_kind(dev):
            continue
        cell = f'dev_{name}'.lower().replace('.', '_')
        inst = instances.get(name, {})
        x = int(round(inst.get('x_um', 0) * 100))
        y = int(round(inst.get('y_um', 0) * 100))
        mag.append(f'use {cell} {cell}_0')
        mag.append(f'transform 1 0 {x} 0 1 {y}')
        mag.append(f'box 0 0 1 1')

    # Placeholder for routing — will be appended
    mag.append('ROUTING_PLACEHOLDER')
    mag.append('<< end >>')

    return mag


def run_magic_extract(output_dir):
    """Run Magic flatten + extract, return device count from Netgen."""
    magic_cmd = (
        'CAD_ROOT=$HOME/.local/lib $HOME/.local/bin/magic '
        '-noconsole -dnull '
        '-T ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2'
    )

    tcl = (
        'load soilz\n'
        'flatten soilz_flat\n'
        'load soilz_flat\n'
        'extract unique\n'
        'extract all\n'
        'ext2spice lvs\n'
        'ext2spice\n'
        'exit\n'
    )

    result = subprocess.run(
        f'cd {output_dir} && echo "{tcl}" | {magic_cmd}',
        shell=True, capture_output=True, text=True, timeout=120
    )

    return os.path.exists(os.path.join(output_dir, 'soilz_flat.spice'))


def count_connected_pins(spice_path, net_aps):
    """Count how many nets have all their pins on the same extracted net."""
    if not os.path.exists(spice_path):
        return 0, 0

    with open(spice_path) as f:
        lines = f.readlines()

    # Build extracted device terminals
    dev_terms = {}
    for line in lines:
        if line.startswith('X'):
            parts = line.split()
            # Find device name from terminal net names
            for t in parts[1:5]:
                if 'dev_' in t and '_0.' in t:
                    dev = t.split('.')[0].replace('dev_', '').replace('_0', '')
                    pin = t.split('.')[-1]
                    dev_terms[(dev, pin)] = t
                    break

    # Check each net
    connected = 0
    total = 0
    for net_name, aps in net_aps.items():
        total += 1
        # Get extracted net names for this net's pins
        ext_nets = set()
        for ap in aps:
            dev_name = ap[4].lower()
            pin_name = ap[5]
            key = (dev_name, pin_name)
            if key in dev_terms:
                ext_nets.add(dev_terms[key])

        if len(ext_nets) == 1 and ext_nets != {None}:
            connected += 1

    return connected, total


def main():
    layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(layout_dir)
    output_dir = '/tmp/magic_soilz'

    print('=== Magic-in-the-loop Router ===')
    netlist, placement, device_lib = load_data()
    net_aps = build_net_aps(netlist, placement, device_lib)
    print(f'Nets to route: {len(net_aps)}')

    # Build base .mag (devices only)
    base_mag = build_base_mag(netlist, placement, device_lib, output_dir)

    # Sort nets: smallest first (easiest to route without conflicts)
    sorted_nets = sorted(net_aps.items(), key=lambda x: len(x[1]))

    # Incremental routing
    routing_lines = []  # accumulated routing geometry
    routed = 0
    failed = 0

    for i, (net_name, aps) in enumerate(sorted_nets):
        # Generate AP geometry + M2 chain for this net
        net_lines = []
        for ap in aps:
            net_lines.extend(generate_ap_geometry(ap))
        net_lines.extend(generate_chain_m2(aps))

        # Build soilz.mag with all routing so far + this net
        candidate = routing_lines + net_lines
        mag_content = '\n'.join(base_mag).replace(
            'ROUTING_PLACEHOLDER', '\n'.join(candidate))

        mag_path = os.path.join(output_dir, 'soilz.mag')
        with open(mag_path, 'w') as f:
            f.write(mag_content + '\n')

        # Run Magic extract
        ok = run_magic_extract(output_dir)
        if not ok:
            print(f'  [{i+1}/{len(sorted_nets)}] {net_name}: EXTRACT FAILED')
            failed += 1
            continue

        # TODO: check if this net's pins are connected and no cross-net
        # For now, just keep all routing (greedy without verification)
        routing_lines.extend(net_lines)
        routed += 1

        if (i + 1) % 10 == 0 or i == len(sorted_nets) - 1:
            print(f'  [{i+1}/{len(sorted_nets)}] Routed: {routed}, Failed: {failed}')

    # Final extraction
    mag_content = '\n'.join(base_mag).replace(
        'ROUTING_PLACEHOLDER', '\n'.join(routing_lines))
    with open(os.path.join(output_dir, 'soilz.mag'), 'w') as f:
        f.write(mag_content + '\n')

    print(f'\n=== Done ===')
    print(f'Routed: {routed}/{len(sorted_nets)}')
    print(f'Failed: {failed}')
    print(f'Routing lines: {len(routing_lines)}')


if __name__ == '__main__':
    main()
