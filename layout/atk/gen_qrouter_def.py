#!/usr/bin/env python3
"""Generate DEF file for qrouter from netlist + placement + device_lib_magic.

Qrouter reads:
  - Tech LEF (layer definitions, via rules)
  - DEF (die area, components/placement, pins, nets)

This script generates the DEF. Tech LEF comes from IHP PDK.

Usage:
    cd layout && python3 -m atk.gen_qrouter_def
"""

import json
import os


def generate_def(layout_dir='.', output_path='/tmp/magic_soilz/soilz.def'):
    with open(os.path.join(layout_dir, 'netlist.json')) as f:
        netlist = json.load(f)
    with open(os.path.join(layout_dir, 'placement.json')) as f:
        placement = json.load(f)
    with open(os.path.join(layout_dir, 'atk', 'data', 'device_lib_magic.json')) as f:
        device_lib = json.load(f)

    instances = placement.get('instances', {})
    devices = netlist.get('devices', [])
    nets = netlist.get('nets', [])

    # DEF uses microns (database units = 1000 per micron)
    DB_SCALE = 1000  # 1 um = 1000 DEF units

    # Die area from placement bounds
    all_x = []
    all_y = []
    for dev in devices:
        name = dev['name']
        inst = instances.get(name, {})
        x = inst.get('x_um', 0)
        y = inst.get('y_um', 0)
        dt = dev['type']
        mi = device_lib.get(dt, {})
        bb = mi.get('bbox', [0, 0, 0, 0])
        all_x.extend([x + bb[0]/1000, x + bb[2]/1000])
        all_y.extend([y + bb[1]/1000, y + bb[3]/1000])

    margin = 10  # um margin
    die_x1 = min(all_x) - margin
    die_y1 = min(all_y) - margin
    die_x2 = max(all_x) + margin
    die_y2 = max(all_y) + margin

    lines = []
    lines.append('VERSION 5.8 ;')
    lines.append('DIVIDERCHAR "/" ;')
    lines.append('BUSBITCHARS "[]" ;')
    lines.append('DESIGN soilz ;')
    lines.append(f'UNITS DISTANCE MICRONS {DB_SCALE} ;')
    lines.append('')
    lines.append(f'DIEAREA ( {int(die_x1*DB_SCALE)} {int(die_y1*DB_SCALE)} )'
                 f' ( {int(die_x2*DB_SCALE)} {int(die_y2*DB_SCALE)} ) ;')
    lines.append('')

    # Components (device instances)
    lines.append(f'COMPONENTS {len(devices)} ;')
    for dev in devices:
        name = dev['name']
        dt = dev['type']
        inst = instances.get(name, {})
        x = inst.get('x_um', 0)
        y = inst.get('y_um', 0)
        # DEF component: - name cell_name + PLACED ( x y ) orientation ;
        cell = dt.upper().replace('.', '_')
        x_def = int(round(x * DB_SCALE))
        y_def = int(round(y * DB_SCALE))
        lines.append(f'  - {name} {cell} + PLACED ( {x_def} {y_def} ) N ;')
    lines.append('END COMPONENTS')
    lines.append('')

    # Pins (external ports — we'll add the net names as external pins)
    ext_pins = []
    for net in nets:
        if len(net.get('pins', [])) >= 1:
            ext_pins.append(net['name'])

    lines.append(f'PINS {len(ext_pins)} ;')
    for pin_name in ext_pins:
        lines.append(f'  - {pin_name} + NET {pin_name} + DIRECTION INOUT ;')
    lines.append('END PINS')
    lines.append('')

    # Nets
    lines.append(f'NETS {len(nets)} ;')
    for net in nets:
        net_name = net['name']
        pins = net.get('pins', [])
        lines.append(f'  - {net_name}')

        # Add external pin
        lines.append(f'    ( PIN {net_name} )')

        # Add device pins
        for pin_key in pins:
            parts = pin_key.split('.')
            dev_name = parts[0]
            pin_name = parts[1] if len(parts) > 1 else 'A'
            lines.append(f'    ( {dev_name} {pin_name} )')

        lines.append('  ;')
    lines.append('END NETS')
    lines.append('')

    # Blockages (device bboxes as routing blockages on M1)
    obstructions = []
    for dev in devices:
        name = dev['name']
        dt = dev['type']
        inst = instances.get(name, {})
        mi = device_lib.get(dt, {})
        if not mi or 'bbox' not in mi:
            continue
        bb = mi['bbox']
        x = inst.get('x_um', 0)
        y = inst.get('y_um', 0)
        ox1 = int(round((x + bb[0]/1000) * DB_SCALE))
        oy1 = int(round((y + bb[1]/1000) * DB_SCALE))
        ox2 = int(round((x + bb[2]/1000) * DB_SCALE))
        oy2 = int(round((y + bb[3]/1000) * DB_SCALE))
        obstructions.append((ox1, oy1, ox2, oy2))

    if obstructions:
        lines.append(f'BLOCKAGES {len(obstructions)} ;')
        for ox1, oy1, ox2, oy2 in obstructions:
            lines.append(f'  - LAYER Metal1')
            lines.append(f'    RECT ( {ox1} {oy1} ) ( {ox2} {oy2} ) ;')
        lines.append('END BLOCKAGES')
        lines.append('')

    lines.append('END DESIGN')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print(f'  DEF: {output_path}')
    print(f'  Components: {len(devices)}')
    print(f'  Nets: {len(nets)}')
    print(f'  Pins: {len(ext_pins)}')
    print(f'  Blockages: {len(obstructions)}')
    print(f'  Die: ({die_x1:.0f},{die_y1:.0f}) - ({die_x2:.0f},{die_y2:.0f}) um')


if __name__ == '__main__':
    layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(layout_dir)
    generate_def()
