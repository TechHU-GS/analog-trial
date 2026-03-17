#!/usr/bin/env python3
"""Direct net router for Magic layout — no ATK dependency.

Reads netlist.json, placement.json, device_lib_magic.json.
Generates routing geometry (M1 stubs + via1 + M2 pads + M2 wires)
directly in Magic coordinates.

Strategy per net:
  - 2-pin: L-shaped M2 wire between the two APs
  - N-pin: horizontal M2 bus at median Y, vertical M2 drops to each AP
  - Power (vdd/gnd): M3 horizontal rails + M3 vertical drops + via2 stacks

Each AP = via1 + M1 pad + M2 pad + M1 stub (from device pin to via1).
AP positions computed from device_lib_magic.json pin positions + clearance.

Usage:
    cd layout && python3 -m atk.magic_net_router
"""

import json
import os

SCALE = 10  # 1 magic unit = 10nm

# Geometry constants (nm)
VIA1_HS = 100       # via1 half-size (100nm → 200nm, above 190nm min)
M1_PAD_HS = 185     # M1 pad half-size for via1 enclosure
M2_PAD_HS = 240     # M2 pad half-size for via1 enclosure
M1_STUB_HW = 80     # M1 stub half-width (thin to avoid gate shorts)
M2_WIRE_HW = 150    # M2 wire half-width
M3_WIRE_HW = 200    # M3 wire half-width
VIA_CLEAR = 400     # clearance from device bbox to via1 center


def nm(val):
    """Convert nm to Magic units."""
    return int(round(val / SCALE))


def load_data(layout_dir='.'):
    """Load netlist, placement, and device lib."""
    with open(os.path.join(layout_dir, 'netlist.json')) as f:
        netlist = json.load(f)
    with open(os.path.join(layout_dir, 'placement.json')) as f:
        placement = json.load(f)
    with open(os.path.join(layout_dir, 'atk', 'data', 'device_lib_magic.json')) as f:
        device_lib = json.load(f)
    return netlist, placement, device_lib


def compute_pin_positions(netlist, placement, device_lib):
    """Compute absolute pin positions in nm for all devices."""
    instances = placement.get('instances', {})
    pin_pos = {}  # (dev_name, pin_name) → (x_nm, y_nm)

    for dev in netlist.get('devices', []):
        name = dev['name']
        dev_type = dev['type']
        inst = instances.get(name, {})
        magic_info = device_lib.get(dev_type)
        if not magic_info or 'pins' not in magic_info:
            continue

        # Magic: placement position IS PCell origin
        ox = inst.get('x_um', 0) * 1000  # → nm
        oy = inst.get('y_um', 0) * 1000

        for pin_name, pin_info in magic_info['pins'].items():
            px, py = pin_info['pos_nm']
            pin_pos[(name, pin_name)] = (int(round(ox + px)), int(round(oy + py)))

    return pin_pos


def compute_device_bboxes(netlist, placement, device_lib):
    """Compute absolute device bboxes in nm."""
    instances = placement.get('instances', {})
    bboxes = {}  # dev_name → (x1, y1, x2, y2)

    for dev in netlist.get('devices', []):
        name = dev['name']
        dev_type = dev['type']
        inst = instances.get(name, {})
        magic_info = device_lib.get(dev_type)
        if not magic_info or 'bbox' not in magic_info:
            continue

        ox = inst.get('x_um', 0) * 1000
        oy = inst.get('y_um', 0) * 1000
        bb = magic_info['bbox']
        bboxes[name] = (
            int(round(ox + bb[0])), int(round(oy + bb[1])),
            int(round(ox + bb[2])), int(round(oy + bb[3]))
        )

    return bboxes


def compute_ap_position(pin_pos, bbox, pin_name, dev_name):
    """Compute access point position (above or below device bbox)."""
    px, py = pin_pos
    x1, y1, x2, y2 = bbox

    # Gate pins: AP below bbox
    if pin_name == 'G':
        via_y = y1 - VIA_CLEAR
    # Source/drain: AP above bbox
    else:
        via_y = y2 + VIA_CLEAR

    return (px, via_y)


def generate_routing(netlist, placement, device_lib):
    """Generate all routing geometry.

    Returns dict of magic_layer → list of (x1, y1, x2, y2) in nm.
    """
    pin_pos = compute_pin_positions(netlist, placement, device_lib)
    bboxes = compute_device_bboxes(netlist, placement, device_lib)

    # Build net → list of (dev_name, pin_name) mapping
    net_pins = {}
    for net in netlist.get('nets', []):
        net_name = net['name']
        pins = []
        for pin_key in net.get('pins', []):
            parts = pin_key.split('.')
            dev_name = parts[0]
            pin_name = parts[1] if len(parts) > 1 else ''
            if (dev_name, pin_name) in pin_pos and dev_name in bboxes:
                pins.append((dev_name, pin_name))
            # Try aliases (S1→S, S2→S, PLUS→R1, MINUS→R2)
            elif pin_name in ('S1', 'S2') and (dev_name, 'S') in pin_pos:
                pins.append((dev_name, 'S'))
            elif pin_name == 'PLUS' and (dev_name, 'R1') in pin_pos:
                pins.append((dev_name, 'R1'))
            elif pin_name == 'MINUS' and (dev_name, 'R2') in pin_pos:
                pins.append((dev_name, 'R2'))
        net_pins[net_name] = pins

    # Generate geometry per layer
    rects = {
        'metal1': [],
        'via1': [],
        'metal2': [],
        'metal3': [],
        'via2': [],
    }

    power_nets = {'vdd', 'gnd'}
    routed_nets = 0
    total_pins_connected = 0

    for net_name, pins in net_pins.items():
        if len(pins) < 2:
            continue

        # Compute AP positions for each pin
        aps = []  # (px, py, via_x, via_y, dev_name, pin_name)
        for dev_name, pin_name in pins:
            pp = pin_pos[(dev_name, pin_name)]
            bb = bboxes[dev_name]
            via_x, via_y = compute_ap_position(pp, bb, pin_name, dev_name)
            aps.append((pp[0], pp[1], via_x, via_y, dev_name, pin_name))

        # Deduplicate APs at same position (S1/S2 aliases)
        seen = set()
        unique_aps = []
        for ap in aps:
            key = (ap[2], ap[3])  # via position
            if key not in seen:
                seen.add(key)
                unique_aps.append(ap)
        aps = unique_aps

        if len(aps) < 2:
            continue

        is_power = net_name in power_nets

        # === Draw AP structures (M1 stub + via1 + M1 pad + M2 pad) ===
        for px, py, vx, vy, dn, pn in aps:
            # M1 stub: from device pin to via position
            stub_x1 = px - M1_STUB_HW
            stub_x2 = px + M1_STUB_HW
            stub_y1 = min(py, vy - M1_PAD_HS)
            stub_y2 = max(py, vy + M1_PAD_HS)
            rects['metal1'].append((stub_x1, stub_y1, stub_x2, stub_y2))

            # Via1
            rects['via1'].append((vx - VIA1_HS, vy - VIA1_HS,
                                  vx + VIA1_HS, vy + VIA1_HS))

            # M1 pad (via1 enclosure)
            rects['metal1'].append((vx - M1_PAD_HS, vy - M1_PAD_HS,
                                    vx + M1_PAD_HS, vy + M1_PAD_HS))

            # M2 pad (via1 enclosure)
            rects['metal2'].append((vx - M2_PAD_HS, vy - M2_PAD_HS,
                                    vx + M2_PAD_HS, vy + M2_PAD_HS))

            total_pins_connected += 1

        # === Route between APs ===
        if is_power:
            _route_power(aps, rects)
        else:
            _route_signal(aps, rects)

        routed_nets += 1

    return rects, routed_nets, total_pins_connected


def _route_signal(aps, rects):
    """Route a signal net: M2 bus at median Y + vertical M2 drops."""
    if len(aps) < 2:
        return

    # Sort by X for bus routing
    sorted_aps = sorted(aps, key=lambda a: a[2])  # sort by via_x

    if len(aps) == 2:
        # 2-pin net: L-shaped M2 wire
        a, b = sorted_aps
        ax, ay = a[2], a[3]
        bx, by = b[2], b[3]

        # Horizontal M2
        rects['metal2'].append((
            min(ax, bx) - M2_WIRE_HW, ay - M2_WIRE_HW,
            max(ax, bx) + M2_WIRE_HW, ay + M2_WIRE_HW
        ))
        # Vertical M2 (if needed)
        if ay != by:
            rects['metal2'].append((
                bx - M2_WIRE_HW, min(ay, by) - M2_WIRE_HW,
                bx + M2_WIRE_HW, max(ay, by) + M2_WIRE_HW
            ))
    else:
        # N-pin net: horizontal M2 bus at median Y + vertical drops
        via_ys = [a[3] for a in sorted_aps]
        bus_y = sorted(via_ys)[len(via_ys) // 2]

        # Horizontal M2 bus
        x_min = sorted_aps[0][2]
        x_max = sorted_aps[-1][2]
        rects['metal2'].append((
            x_min - M2_WIRE_HW, bus_y - M2_WIRE_HW,
            x_max + M2_WIRE_HW, bus_y + M2_WIRE_HW
        ))

        # Vertical M2 drops from each AP to bus
        for ap in sorted_aps:
            vx, vy = ap[2], ap[3]
            if vy != bus_y:
                rects['metal2'].append((
                    vx - M2_WIRE_HW, min(vy, bus_y) - M2_WIRE_HW,
                    vx + M2_WIRE_HW, max(vy, bus_y) + M2_WIRE_HW
                ))


def _route_power(aps, rects):
    """Route a power net: M3 bus + via2 stacks."""
    sorted_aps = sorted(aps, key=lambda a: a[2])
    via_ys = [a[3] for a in sorted_aps]
    bus_y = sorted(via_ys)[len(via_ys) // 2]

    x_min = sorted_aps[0][2]
    x_max = sorted_aps[-1][2]

    # M3 horizontal bus
    rects['metal3'].append((
        x_min - M3_WIRE_HW, bus_y - M3_WIRE_HW,
        x_max + M3_WIRE_HW, bus_y + M3_WIRE_HW
    ))

    for ap in sorted_aps:
        vx, vy = ap[2], ap[3]

        # M3 vertical drop to bus
        if vy != bus_y:
            rects['metal3'].append((
                vx - M3_WIRE_HW, min(vy, bus_y) - M3_WIRE_HW,
                vx + M3_WIRE_HW, max(vy, bus_y) + M3_WIRE_HW
            ))

        # Via2 at AP
        rects['via2'].append((vx - VIA1_HS, vy - VIA1_HS,
                              vx + VIA1_HS, vy + VIA1_HS))

        # M3 pad at AP
        rects['metal3'].append((vx - M2_PAD_HS, vy - M2_PAD_HS,
                                vx + M2_PAD_HS, vy + M2_PAD_HS))


def write_to_mag(rects, output_path):
    """Write routing geometry to a .mag snippet (for insertion into soilz.mag)."""
    lines = []
    # Order: metal1 first, then via1, then metal2, then via2, then metal3
    layer_order = ['metal1', 'via1', 'metal2', 'via2', 'metal3']

    for layer in layer_order:
        layer_rects = rects.get(layer, [])
        if not layer_rects:
            continue
        lines.append(f'<< {layer} >>')
        for x1, y1, x2, y2 in layer_rects:
            lines.append(f'rect {nm(x1)} {nm(y1)} {nm(x2)} {nm(y2)}')

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    return len(lines)


def main():
    layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(layout_dir)

    netlist, placement, device_lib = load_data()
    rects, routed_nets, pins_connected = generate_routing(
        netlist, placement, device_lib)

    total_rects = sum(len(r) for r in rects.values())
    print(f'  Routed nets: {routed_nets}')
    print(f'  Pins connected: {pins_connected}')
    print(f'  Total rects: {total_rects}')
    for layer, r in rects.items():
        if r:
            print(f'    {layer}: {len(r)}')

    # Write routing snippet
    snippet_path = '/tmp/magic_soilz/routing_snippet.mag'
    line_count = write_to_mag(rects, snippet_path)
    print(f'  Written: {snippet_path} ({line_count} lines)')

    # Also write as JSON for debugging
    json_path = '/tmp/magic_soilz/routing_direct.json'
    with open(json_path, 'w') as f:
        json.dump({
            'routed_nets': routed_nets,
            'pins_connected': pins_connected,
            'rects': {k: v for k, v in rects.items() if v},
        }, f)
    print(f'  JSON: {json_path}')


if __name__ == '__main__':
    main()
