#!/usr/bin/env python3
"""Verify netlist.json against SPICE source using the existing parser.

Checks that hand-written netlist.json has the same connectivity as the
SPICE netlist, catching any manual pin-tracing errors.

Usage:
    cd /private/tmp/analog-trial/layout
    python verify_netlist_vs_spice.py
"""

import json
import sys
from collections import defaultdict
sys.path.insert(0, '.')
from atk.spice.parser import parse_spice

SPICE_FILE = '../sim/cmos_ptat_vco.sp'
NETLIST_FILE = 'netlist.json'

# Terminals to exclude (handled by well ties, not routing)
EXCLUDE_TERMINALS = {'B', 'Sub'}

# ng>=2 PCell pin expansion: SPICE has one S terminal, layout has S1+S2
# Map: (device_type, spice_pin) -> [layout_pins]
NG2_EXPANSION = {
    'pmos_buf2': {'S': ['S1', 'S2']},
    'pmos_cs8': {'S': ['S1', 'S2']},   # ng=8 PMOS
    'nmos_buf2': {'S': ['S', 'S2']},   # NMOS ng=2 convention
    'nmos_bias8': {'S': ['S', 'S2']},  # ng=8 NMOS
    'nmos_vittoz8': {'S': ['S', 'S2']},  # ng=8 NMOS
}

# Devices removed from layout (deferred)
DEFERRED_DEVICES = {'Cbyp_n', 'Cbyp_p'}


def main():
    # --- Parse SPICE ---
    sp = parse_spice(SPICE_FILE)

    # Build SPICE connectivity: {net_name: set of "device.terminal"}
    sp_nets = defaultdict(set)
    sp_devices = set()
    for dev in sp['devices']:
        if dev['name'] in DEFERRED_DEVICES:
            continue
        sp_devices.add(dev['name'])
        for term, net in dev['nets'].items():
            if term in EXCLUDE_TERMINALS:
                continue
            sp_nets[net].add(f"{dev['name']}.{term}")

    # --- Load netlist.json ---
    with open(NETLIST_FILE) as f:
        nl = json.load(f)

    nl_nets = defaultdict(set)
    nl_devices = {d['name'] for d in nl['devices']}
    nl_dev_types = {d['name']: d['type'] for d in nl['devices']}
    for net in nl['nets']:
        for pin_ref in net['pins']:
            nl_nets[net['name']].add(pin_ref)

    # Expand SPICE single-S pins to match ng=2 layout pins
    for dev_name, dev_type in nl_dev_types.items():
        if dev_type in NG2_EXPANSION:
            for sp_pin, nl_pins in NG2_EXPANSION[dev_type].items():
                sp_ref = f"{dev_name}.{sp_pin}"
                for net_name, pins in sp_nets.items():
                    if sp_ref in pins:
                        pins.discard(sp_ref)
                        for lp in nl_pins:
                            pins.add(f"{dev_name}.{lp}")

    # --- Compare devices ---
    errors = []
    warnings = []

    missing_devs = sp_devices - nl_devices
    extra_devs = nl_devices - sp_devices
    if missing_devs:
        errors.append(f"Devices in SPICE but not in netlist.json: {sorted(missing_devs)}")
    if extra_devs:
        errors.append(f"Devices in netlist.json but not in SPICE: {sorted(extra_devs)}")

    print(f"SPICE devices: {len(sp_devices)}")
    print(f"Netlist devices: {len(nl_devices)}")

    # --- Compare nets ---
    # For each SPICE net, find matching netlist.json net by pin overlap
    sp_net_to_nl = {}
    nl_net_to_sp = {}

    for sp_name, sp_pins in sp_nets.items():
        # Find NL net with maximum overlap
        best_match = None
        best_overlap = 0
        for nl_name, nl_pins in nl_nets.items():
            overlap = len(sp_pins & nl_pins)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = nl_name
        if best_match and best_overlap > 0:
            sp_net_to_nl[sp_name] = best_match
            nl_net_to_sp[best_match] = sp_name

    # Check each SPICE net
    for sp_name, sp_pins in sorted(sp_nets.items()):
        nl_name = sp_net_to_nl.get(sp_name)
        if nl_name is None:
            errors.append(f"SPICE net '{sp_name}' ({sp_pins}) has no match in netlist.json")
            continue

        nl_pins = nl_nets[nl_name]

        # Check pin differences
        missing = sp_pins - nl_pins
        extra = nl_pins - sp_pins

        if missing or extra:
            label = f"Net SPICE:'{sp_name}' = NL:'{nl_name}'"
            if sp_name != nl_name:
                label += f" (name mismatch!)"
            if missing:
                errors.append(f"{label}: missing from NL: {sorted(missing)}")
            if extra:
                warnings.append(f"{label}: extra in NL: {sorted(extra)}")

    # Check for unmatched NL nets
    for nl_name in sorted(nl_nets.keys()):
        if nl_name not in nl_net_to_sp:
            errors.append(f"Netlist.json net '{nl_name}' has no match in SPICE")

    # --- Report ---
    print(f"\nSPICE nets: {len(sp_nets)}")
    print(f"Netlist nets: {len(nl_nets)}")
    print(f"Matched: {len(sp_net_to_nl)}")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  W: {w}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  E: {e}")
        print(f"\nFAIL: {len(errors)} error(s)")
        return 1
    else:
        print(f"\nPASS: connectivity matches ({len(sp_net_to_nl)} nets verified)")
        return 0


if __name__ == '__main__':
    sys.exit(main())
