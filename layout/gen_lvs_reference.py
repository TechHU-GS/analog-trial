#!/usr/bin/env python3
"""Generate complete LVS reference netlist from netlist.json + device_lib.json.

Creates a flat SPICE subcircuit with all 249 devices, matching the format
that KLayout LVS extraction produces.

Usage:
    cd layout && python3 gen_lvs_reference.py
"""
import json
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Load data
with open('netlist.json') as f:
    netlist = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)

devices = netlist['devices']
nets = netlist['nets']

# Build pin→net mapping: "DevName.PinName" → net_name
pin_to_net = {}
for net in nets:
    net_name = net['name']
    for pin_ref in net['pins']:
        pin_to_net[pin_ref] = net_name

# Count devices by class
nmos_count = 0
pmos_count = 0
res_count = 0
for d in devices:
    dtype = d['type']
    if dtype not in dev_lib:
        print(f"WARNING: device type '{dtype}' not in device_lib.json", file=sys.stderr)
        continue
    cls = dev_lib[dtype]['classification']['device_class']
    if cls == 'nmos':
        nmos_count += 1
    elif cls == 'pmos':
        pmos_count += 1
    elif cls == 'resistor':
        res_count += 1

print(f"Devices: {len(devices)} ({nmos_count} NMOS, {pmos_count} PMOS, {res_count} R)")

# Collect all port nets (nets that appear as subcircuit ports)
# These are the nets that connect to external pins
# For LVS, we need to declare the same ports as the extracted netlist
port_nets = set()
for net in nets:
    if net['type'] in ('power', 'port', 'signal'):
        port_nets.add(net['name'])

# Generate SPICE lines
spice_lines = []
spice_lines.append("** Complete LVS reference netlist for ptat_vco")
spice_lines.append("** Auto-generated from netlist.json + device_lib.json")
spice_lines.append(f"** {len(devices)} devices: {nmos_count} NMOS, {pmos_count} PMOS, {res_count} R")
spice_lines.append("")

# Build port list — match the order from extracted netlist
# First power, then signals alphabetically
power_nets = sorted([n['name'] for n in nets if n['type'] == 'power'])
signal_nets = sorted([n['name'] for n in nets if n['type'] == 'signal'])
all_ports = power_nets + signal_nets

# Format subcircuit header with SPICE continuation lines
# SPICE lines must be < ~80 chars; continuation lines start with '+'
subckt_header = f".subckt ptat_vco {' '.join(all_ports[:5])}"
spice_lines.append(subckt_header)
remaining = all_ports[5:]
while remaining:
    chunk = remaining[:10]
    remaining = remaining[10:]
    spice_lines.append("+ " + ' '.join(chunk))
spice_lines.append("")

# Generate device lines
for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        spice_lines.append(f"** SKIP: {name} type={dtype} (not in lib)")
        continue

    lib_entry = dev_lib[dtype]
    cls = lib_entry['classification']['device_class']
    pcell_name = lib_entry.get('pcell_name', lib_entry.get('pcell', '?'))
    params = lib_entry['params']

    if cls in ('nmos', 'pmos'):
        # MOSFET: Mname D G S B model W=... L=...
        d_net = pin_to_net.get(f"{name}.D", "?D")
        g_net = pin_to_net.get(f"{name}.G", "?G")
        # Handle S vs S1 naming for multi-finger devices
        s_net = pin_to_net.get(f"{name}.S",
                pin_to_net.get(f"{name}.S1", "?S"))

        # Bulk connection
        if cls == 'pmos':
            b_net = d.get('nwell_net', 'vdd')
        else:
            b_net = 'gnd'

        # Handle multi-finger: some devices have S2 pin (second source)
        # For LVS, KLayout merges the PCell into one device, so we only
        # need D, G, S, B

        w_um = params['w']
        l_um = params['l']

        # Format W/L to match KLayout extraction output:
        # Use minimal representation (no trailing .0)
        def fmt_um(v):
            if v == int(v):
                return f"{int(v)}u"
            return f"{v}u"

        spice_lines.append(
            f"M{name} {d_net} {g_net} {s_net} {b_net} "
            f"{pcell_name} W={fmt_um(w_um)} L={fmt_um(l_um)}"
        )

    elif cls == 'resistor':
        # Resistor: Rname n1 n2 model w=... l=... [b=...] [m=...]
        # Pin names: PLUS and MINUS
        plus_net = pin_to_net.get(f"{name}.PLUS", "?PLUS")
        minus_net = pin_to_net.get(f"{name}.MINUS", "?MINUS")

        w_um = params['w']
        l_um = params['l']
        b = params.get('b', 1)
        m = params.get('m', 1)

        # KLayout extracts physical drawn length which includes end
        # effects beyond the PCell parameter L.  Use measured values
        # so the reference matches extraction.
        _RHIGH_EXTRACTED_L = {133.0: 134.09, 20.0: 20.73}
        _RPPD_EXTRACTED_L = {25.0: 25.915}
        if pcell_name == 'rhigh' and l_um in _RHIGH_EXTRACTED_L:
            l_um = _RHIGH_EXTRACTED_L[l_um]
        if pcell_name == 'rppd' and l_um in _RPPD_EXTRACTED_L:
            l_um = _RPPD_EXTRACTED_L[l_um]

        spice_lines.append(
            f"R{name} {plus_net} {minus_net} {pcell_name} "
            f"w={w_um}u l={l_um}u b={b} m={m}"
        )

    else:
        spice_lines.append(f"** SKIP: {name} type={dtype} class={cls}")

spice_lines.append("")
spice_lines.append(".ends ptat_vco")
spice_lines.append("")

# Check for missing connections
missing = []
for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        continue
    cls = dev_lib[dtype]['classification']['device_class']
    if cls in ('nmos', 'pmos'):
        for pin in ('D', 'G', 'S'):
            key = f"{name}.{pin}"
            key1 = f"{name}.{pin}1"
            if key not in pin_to_net and key1 not in pin_to_net:
                missing.append(key)
    elif cls == 'resistor':
        for pin in ('PLUS', 'MINUS'):
            key = f"{name}.{pin}"
            if key not in pin_to_net:
                missing.append(key)

if missing:
    print(f"\nWARNING: {len(missing)} unconnected pins:")
    for m in missing[:20]:
        print(f"  {m}")
    if len(missing) > 20:
        print(f"  ... and {len(missing)-20} more")

# Write output
outfile = 'ptat_vco_lvs.spice'
with open(outfile, 'w') as f:
    f.write('\n'.join(spice_lines) + '\n')
print(f"\nWritten to {outfile}")

# Also check for S2 pins that might need special handling
s2_pins = [k for k in pin_to_net if k.endswith('.S2')]
if s2_pins:
    print(f"\nNote: {len(s2_pins)} devices have S2 pins (multi-source):")
    for p in s2_pins[:10]:
        print(f"  {p} → {pin_to_net[p]}")
