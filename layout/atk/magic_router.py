#!/usr/bin/env python3
"""Simple Manhattan router in Magic coordinates.

Reads netlist.json for connectivity, device .mag files for pin positions,
placement.json for device origins. Generates routing as .mag rectangles.

Routing strategy:
  - 2-pin nets: L-shaped M1/M2 wire + via
  - Multi-pin nets: chain nearest neighbors
  - Power nets: horizontal M3 rails + vertical M3 drops + via stacks
  - All routing on M2 (horizontal) + M1 (vertical) + Via1

Usage:
    cd layout && python3 -m atk.magic_router
"""

import json
import os
import re
from collections import defaultdict


def load_magic_pins(mag_dir):
    """Read pin positions from all device .mag files."""
    pin_map = {}  # cell_name → {pin: (x, y)}
    for fn in os.listdir(mag_dir):
        if fn.startswith('dev_') and fn.endswith('.mag'):
            cell = fn[:-4]
            pins = {}
            with open(os.path.join(mag_dir, fn)) as f:
                for line in f:
                    m = re.match(
                        r'rlabel\s+\S+\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+\d+\s+(\S+)',
                        line)
                    if m:
                        x = (int(m.group(1)) + int(m.group(3))) // 2
                        y = (int(m.group(2)) + int(m.group(4))) // 2
                        pins[m.group(5)] = (x, y)
            pin_map[cell] = pins
    return pin_map


def get_abs_pins(netlist, placement, pin_map):
    """Get absolute Magic coordinates for each net's pins."""
    net_pins = defaultdict(list)  # net_name → [(x, y, dev.pin)]

    # Build pin→net map from netlist
    pin_to_net = {}
    for net in netlist['nets']:
        for pin_key in net['pins']:
            pin_to_net[pin_key] = net['name']

    instances = placement['instances']
    pin_name_map = {'PLUS': 'R1', 'MINUS': 'R2'}
    pin_name_map2 = {'PLUS': 'C1', 'MINUS': 'C2'}

    for dev in netlist['devices']:
        name = dev['name']
        cell = f'dev_{name}'.lower().replace('.', '_')
        magic_pins = pin_map.get(cell, {})
        inst = instances.get(name, {})
        ox = int(round(inst.get('x_um', 0) * 100))
        oy = int(round(inst.get('y_um', 0) * 100))

        for pin_key in pin_to_net:
            if not pin_key.startswith(f'{name}.'):
                continue
            pin_name = pin_key.split('.', 1)[1]

            # Map pin names
            mpin = pin_name
            if mpin not in magic_pins:
                mpin = pin_name_map.get(pin_name, pin_name)
            if mpin not in magic_pins:
                mpin = pin_name_map2.get(pin_name, pin_name)
            if mpin not in magic_pins and pin_name in ('S1', 'S2'):
                mpin = 'S'

            if mpin not in magic_pins:
                continue

            mpx, mpy = magic_pins[mpin]
            abs_x = ox + mpx
            abs_y = oy + mpy
            net_name = pin_to_net[pin_key]
            net_pins[net_name].append((abs_x, abs_y, pin_key))

    return net_pins


def route_net(pins, is_power=False):
    """Route a set of pins. Returns list of (layer, x1, y1, x2, y2).

    Strategy: horizontal M2 bus at median Y, vertical M1 drops from each pin.
    Each pin gets M1 pad + via1 + M2 pad to connect device contact to M2 bus.
    """
    if len(pins) < 2:
        return []

    segments = []
    sorted_pins = sorted(pins, key=lambda p: (p[0], p[1]))

    if is_power:
        # Power: M3 horizontal bus + M3 vertical drops
        ys = [p[1] for p in sorted_pins]
        bus_y = sorted(ys)[len(ys) // 2]  # median Y
        x_min = min(p[0] for p in sorted_pins)
        x_max = max(p[0] for p in sorted_pins)
        # Horizontal M3 bus
        if x_min != x_max:
            segments.append(('metal3', x_min, bus_y, x_max, bus_y))
        # Vertical M3 drops to each pin
        for x, y, _ in sorted_pins:
            if y != bus_y:
                segments.append(('metal3', x, min(y, bus_y), x, max(y, bus_y)))
        # Via2 at each pin to connect M2 device pad to M3
        for x, y, _ in sorted_pins:
            segments.append(('via2', x, y, x, y))
            segments.append(('metal2', x, y, x, y))
            segments.append(('metal3', x, y, x, y))
    else:
        # Signal: horizontal M2 bus + vertical M1 drops + via1 at each pin
        ys = [p[1] for p in sorted_pins]
        bus_y = sorted(ys)[len(ys) // 2]  # median Y for bus

        x_min = min(p[0] for p in sorted_pins)
        x_max = max(p[0] for p in sorted_pins)

        # Horizontal M2 bus spanning all pins
        if x_min != x_max:
            segments.append(('metal2', x_min, bus_y, x_max, bus_y))

        # For each pin: M1 vertical drop + via1 + M2 pad
        for x, y, _ in sorted_pins:
            # M1 pad at device pin (overlaps ndiffc/pdiffc contact)
            segments.append(('metal1', x, y, x, y))
            # Via1 at pin
            segments.append(('via1', x, y, x, y))
            # M2 pad at pin
            segments.append(('metal2', x, y, x, y))

            # If pin Y differs from bus Y, draw vertical M2 to reach bus
            if y != bus_y:
                segments.append(('metal2', x, min(y, bus_y), x, max(y, bus_y)))

    return segments


def generate_mag(net_pins, power_nets):
    """Generate routing section for soilz.mag."""
    lines = []
    current_layer = None

    # Wire half-widths in Magic units
    HW = {'metal1': 16, 'metal2': 15, 'metal3': 15, 'metal4': 15}
    VIA_HS = {'via1': 10, 'via2': 10, 'via3': 10}

    seg_count = 0

    for net_name, pins in net_pins.items():
        is_power = net_name in power_nets
        segments = route_net(pins, is_power)

        for layer, x1, y1, x2, y2 in segments:
            if layer != current_layer:
                lines.append(f'<< {layer} >>')
                current_layer = layer

            if layer in VIA_HS:
                hs = VIA_HS[layer]
                lines.append(f'rect {x1-hs} {y1-hs} {x1+hs} {y1+hs}')
            else:
                hw = HW.get(layer, 15)
                if x1 == x2:  # point or vertical
                    lines.append(f'rect {x1-hw} {min(y1,y2)-hw} '
                                 f'{x1+hw} {max(y1,y2)+hw}')
                elif y1 == y2:  # horizontal
                    lines.append(f'rect {min(x1,x2)-hw} {y1-hw} '
                                 f'{max(x1,x2)+hw} {y1+hw}')
                else:  # diagonal (shouldn't happen)
                    lines.append(f'rect {min(x1,x2)-hw} {min(y1,y2)-hw} '
                                 f'{max(x1,x2)+hw} {max(y1,y2)+hw}')
            seg_count += 1

    return lines, seg_count


def main(netlist_path='netlist.json',
         placement_path='placement.json',
         mag_dir='/tmp/magic_soilz',
         output_mag='/tmp/magic_soilz/soilz.mag'):

    with open(netlist_path) as f:
        netlist = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)

    pin_map = load_magic_pins(mag_dir)
    print(f'  Loaded {len(pin_map)} device subcells')

    net_pins = get_abs_pins(netlist, placement, pin_map)
    print(f'  Nets with pins: {len(net_pins)}')
    print(f'  Total pin connections: {sum(len(v) for v in net_pins.values())}')

    power_nets = {'vdd', 'gnd'}

    # Generate routing
    routing_lines, seg_count = generate_mag(net_pins, power_nets)
    print(f'  Routing segments: {seg_count}')

    # Read existing soilz.mag (has device use statements)
    base_lines = []
    with open(output_mag) as f:
        for line in f:
            l = line.rstrip()
            if l == '<< end >>':
                break
            # Keep only use/transform/box lines (device placement)
            # Remove old routing metal
            if (l.startswith('use ') or l.startswith('transform ') or
                    l.startswith('box ') or l in ('magic', '') or
                    l.startswith('tech ') or l.startswith('timestamp ')):
                base_lines.append(l)
            elif l.startswith('<< ') and 'metal' not in l and 'via' not in l:
                base_lines.append(l)
            elif l.startswith('rect ') and base_lines and '<< metal' not in base_lines[-1]:
                # Keep non-metal rects (unlikely but safe)
                pass

    # Rebuild: device placement + new routing
    final = base_lines + [''] + routing_lines + ['<< end >>']

    with open(output_mag, 'w') as f:
        f.write('\n'.join(final) + '\n')

    print(f'  Written: {output_mag} ({len(final)} lines)')


if __name__ == '__main__':
    main()
