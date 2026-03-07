#!/usr/bin/env python3
"""Validate LLM-generated netlist.json for completeness and consistency.

Checks:
1. All device names in nets
2. All pin references valid per device_lib
3. row_groups covers all devices
4. power_topology drops covers all power pins
5. routing_order covers all signal nets
6. pin_access covers all device_type/pin combos
7. tie_config covers all PMOS types
8. No dangling net references

Usage:
    cd /private/tmp/analog-trial/layout
    source ~/pdk/venv/bin/activate
    python -m atk.spice.validate [netlist.json] [device_lib.json]
"""

import json
import sys
from collections import defaultdict


def validate(netlist_path='netlist.json', device_lib_path='atk/data/device_lib.json'):
    """Validate netlist.json against device_lib.json. Returns (ok, errors, warnings)."""
    with open(netlist_path) as f:
        nl = json.load(f)
    with open(device_lib_path) as f:
        dlib = json.load(f)

    errors = []
    warnings = []

    devices = nl.get('devices', [])
    nets = nl.get('nets', [])
    constraints = nl.get('constraints', {})

    dev_names = {d['name'] for d in devices}
    dev_types = {d['name']: d['type'] for d in devices}
    net_names = {n['name'] for n in nets}

    # --- 1. All device types exist in device_lib ---
    for d in devices:
        if d['type'] not in dlib:
            errors.append(f"Device {d['name']}: type '{d['type']}' not in device_lib.json")

    # --- 2. All pin references valid ---
    lib_pins = {}
    for dtype, dinfo in dlib.items():
        pins_dict = dinfo.get('pins', {})
        lib_pins[dtype] = set(pins_dict.keys())

    for net in nets:
        for pin_ref in net.get('pins', []):
            parts = pin_ref.split('.')
            if len(parts) != 2:
                errors.append(f"Net {net['name']}: invalid pin ref '{pin_ref}' (expected DEVICE.PIN)")
                continue
            dev_name, pin_name = parts
            if dev_name not in dev_names:
                errors.append(f"Net {net['name']}: device '{dev_name}' not in devices list")
                continue
            dtype = dev_types[dev_name]
            if dtype in lib_pins and pin_name not in lib_pins[dtype]:
                errors.append(f"Net {net['name']}: pin '{pin_name}' not in {dtype} pins {lib_pins[dtype]}")

    # --- 3. row_groups covers all devices ---
    row_groups = constraints.get('row_groups', {})
    devices_in_rows = set()
    for rn, rd in row_groups.items():
        for d in rd.get('devices', []):
            if d not in dev_names:
                errors.append(f"row_groups.{rn}: device '{d}' not in devices list")
            devices_in_rows.add(d)

    missing_from_rows = dev_names - devices_in_rows
    if missing_from_rows:
        errors.append(f"row_groups missing devices: {sorted(missing_from_rows)}")

    extra_in_rows = devices_in_rows - dev_names
    if extra_in_rows:
        errors.append(f"row_groups has unknown devices: {sorted(extra_in_rows)}")

    # --- 4. power_topology drops cover all power pins ---
    pt = constraints.get('power_topology', {})
    drops = pt.get('drops', [])
    drop_pins = {(d['inst'], d['pin']) for d in drops}

    power_nets = [n for n in nets if n.get('type') == 'power']
    power_pin_refs = set()
    for net in power_nets:
        for pin_ref in net.get('pins', []):
            parts = pin_ref.split('.')
            if len(parts) == 2:
                power_pin_refs.add((parts[0], parts[1]))

    missing_drops = power_pin_refs - drop_pins
    if missing_drops:
        errors.append(f"power_topology.drops missing {len(missing_drops)} power pins: "
                       f"{sorted(missing_drops)[:5]}{'...' if len(missing_drops) > 5 else ''}")

    extra_drops = drop_pins - power_pin_refs
    if extra_drops:
        warnings.append(f"power_topology.drops has {len(extra_drops)} extra pins: "
                        f"{sorted(extra_drops)[:5]}")

    # --- 5. routing_order covers all signal nets ---
    routing_order = constraints.get('routing_order', [])
    signal_nets = {n['name'] for n in nets if n.get('type') == 'signal'}

    missing_routes = signal_nets - set(routing_order)
    if missing_routes:
        errors.append(f"routing_order missing signal nets: {sorted(missing_routes)}")

    extra_routes = set(routing_order) - signal_nets
    if extra_routes:
        warnings.append(f"routing_order has unknown nets: {sorted(extra_routes)}")

    # --- 6. pin_access covers all device types and pins ---
    pin_access = constraints.get('pin_access', {})
    # Collect all (type, pin) pairs from nets
    used_type_pins = defaultdict(set)
    for net in nets:
        for pin_ref in net.get('pins', []):
            parts = pin_ref.split('.')
            if len(parts) == 2:
                dtype = dev_types.get(parts[0])
                if dtype:
                    used_type_pins[dtype].add(parts[1])

    for dtype, pins_used in used_type_pins.items():
        if dtype.startswith('_'):
            continue
        pa = pin_access.get(dtype, {})
        if isinstance(pa, dict):
            # Skip _note keys
            pa_pins = {k for k in pa if not k.startswith('_')}
            missing_pa = pins_used - pa_pins
            if missing_pa:
                errors.append(f"pin_access.{dtype} missing pins: {sorted(missing_pa)}")

    # --- 7. tie_config covers all PMOS types ---
    tie_config = constraints.get('tie_config', {})
    tie_res = constraints.get('tie_reservation', {})
    pmos_types = set(tie_res.get('pmos_ntap', {}).get('applies_to', []))
    for ptype in pmos_types:
        if ptype not in tie_config and not ptype.startswith('_'):
            errors.append(f"tie_config missing PMOS type: {ptype}")

    # --- 8. NWell consistency ---
    nwell_islands = constraints.get('well_aware_spacing', {}).get('nwell_islands', [])
    nwell_devs = set()
    for island in nwell_islands:
        for d in island.get('devices', []):
            if d not in dev_names:
                errors.append(f"nwell_island '{island['id']}': device '{d}' not in devices")
            nwell_devs.add(d)

    for d in devices:
        if d.get('has_nwell') and d['name'] not in nwell_devs:
            warnings.append(f"Device {d['name']} has_nwell=true but not in any nwell_island")

    # --- 9. Each device appears in exactly one row ---
    dev_row_count = defaultdict(list)
    for rn, rd in row_groups.items():
        for d in rd.get('devices', []):
            dev_row_count[d].append(rn)
    for d, rows in dev_row_count.items():
        if len(rows) > 1:
            errors.append(f"Device {d} in multiple rows: {rows}")

    # --- 10. Isolation zone devices exist ---
    isolation = constraints.get('isolation', {})
    for zone in isolation.get('zones', []):
        for d in zone.get('devices', []):
            if d not in dev_names:
                errors.append(f"isolation zone '{zone['name']}': device '{d}' not in devices")

    # --- 11. Matching groups reference valid devices ---
    matching = constraints.get('matching', {})
    for mg in matching.get('match_groups', []):
        for d in mg.get('devices', []):
            if d not in dev_names:
                errors.append(f"matching.match_groups: device '{d}' not in devices")

    # --- 12. x_align, y_align, x_order reference valid entities ---
    for xa in constraints.get('x_align', []):
        for d in xa:
            if d not in dev_names:
                errors.append(f"x_align: device '{d}' not in devices")

    for ya in constraints.get('y_align', []):
        for rn in ya:
            if rn not in row_groups:
                errors.append(f"y_align: row '{rn}' not in row_groups")

    for xo in constraints.get('x_order', []):
        for key in ('a', 'b'):
            if xo[key] not in dev_names:
                errors.append(f"x_order: device '{xo[key]}' not in devices")

    ok = len(errors) == 0
    return ok, errors, warnings


def main():
    netlist = sys.argv[1] if len(sys.argv) > 1 else 'netlist.json'
    devlib = sys.argv[2] if len(sys.argv) > 2 else 'atk/data/device_lib.json'

    print(f'Validating {netlist} against {devlib}...')
    ok, errors, warnings = validate(netlist, devlib)

    if warnings:
        print(f'\n  Warnings ({len(warnings)}):')
        for w in warnings:
            print(f'    ⚠ {w}')

    if errors:
        print(f'\n  Errors ({len(errors)}):')
        for e in errors:
            print(f'    ✗ {e}')
        print(f'\n  FAIL: {len(errors)} error(s)')
        sys.exit(1)
    else:
        print(f'\n  PASS: 0 errors, {len(warnings)} warning(s)')


if __name__ == '__main__':
    main()
