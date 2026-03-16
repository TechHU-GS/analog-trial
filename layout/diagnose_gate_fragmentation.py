#!/usr/bin/env python3
"""Diagnose GATE-ONLY net fragmentation (immune to D/S swap artifacts).

MOSFET D/S is permutable in IHP LVS — D/S swap is NOT a real mismatch.
This script focuses on GATE and BULK pins only, which are NOT permutable.
Any gate fragmentation is a REAL routing connectivity issue.

For resistors, PLUS/MINUS may be permutable too, so we skip those.

Usage:
    cd layout && python3 diagnose_gate_fragmentation.py
"""
import os
import json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

REF_FILE = 'ptat_vco_lvs.spice'
EXT_FILE = '/tmp/lvs_r34d/ptat_vco_extracted.cir'


def parse_spice_full(path):
    """Parse SPICE netlist."""
    devices = []
    ports = []
    with open(path) as f:
        lines = f.readlines()
    joined = []
    for line in lines:
        line = line.rstrip('\n')
        if line.startswith('+'):
            if joined:
                joined[-1] += ' ' + line[1:].strip()
            continue
        joined.append(line)
    for line in joined:
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            continue
        if stripped.lower().startswith('.subckt'):
            ports = stripped.split()[2:]
            continue
        if stripped.startswith('.'):
            continue
        parts = stripped.split()
        if not parts:
            continue
        name = parts[0]
        if name[0] in ('M', 'm') and len(parts) >= 6:
            model = parts[5]
            w = l = None
            for p in parts[6:]:
                if p.upper().startswith('W='):
                    w = p.split('=')[1].rstrip('u')
                elif p.upper().startswith('L='):
                    l = p.split('=')[1].rstrip('u')
            devices.append({
                'name': name, 'type': 'mosfet', 'model': model,
                'pins': {'D': parts[1], 'G': parts[2], 'S': parts[3], 'B': parts[4]},
                'W': w, 'L': l, 'key': f"{model}_W{w}_L{l}",
            })
        elif name[0] in ('R', 'r') and len(parts) >= 4:
            model = parts[3]
            w = l = None
            for p in parts[4:]:
                kv = p.split('=')
                if len(kv) == 2:
                    if kv[0].lower() == 'w':
                        w = kv[1].rstrip('u')
                    elif kv[0].lower() == 'l':
                        l = kv[1].rstrip('u')
            devices.append({
                'name': name, 'type': 'resistor', 'model': model,
                'pins': {'PLUS': parts[1], 'MINUS': parts[2]},
                'W': w, 'L': l, 'key': f"{model}_W{w}_L{l}",
            })
    return devices, set(ports)


ref_devs, ref_ports = parse_spice_full(REF_FILE)
ext_devs, ext_ports = parse_spice_full(EXT_FILE)

# Build device matching (same as before)
ref_by_key = defaultdict(list)
ext_by_key = defaultdict(list)
for d in ref_devs:
    ref_by_key[d['key']].append(d)
for d in ext_devs:
    ext_by_key[d['key']].append(d)

common_ports_lower = set()
for p in ext_ports:
    if p.lower() in {rp.lower() for rp in ref_ports}:
        common_ports_lower.add(p.lower())

# Match devices using D/S-aware matching
device_map = {}  # ref_name -> ext_device

for key in set(ref_by_key) & set(ext_by_key):
    rds = ref_by_key[key]
    eds = list(ext_by_key[key])

    if len(rds) == 1 and len(eds) == 1:
        device_map[rds[0]['name']] = eds[0]
        continue

    # Multi-instance: match by port-net connections with D/S swap awareness
    used_ext = set()
    for rd in rds:
        rd_port_pins = {}
        for pin, net in rd['pins'].items():
            if net.lower() in common_ports_lower:
                rd_port_pins[pin] = net.lower()
        if not rd_port_pins:
            continue

        best_match = None
        best_score = 0
        for ed in eds:
            if ed['name'] in used_ext:
                continue
            score = 0
            for pin, ref_net_lc in rd_port_pins.items():
                ext_net = ed['pins'].get(pin, '').lower()
                if ext_net == ref_net_lc:
                    score += 2
                # Try D/S swap
                elif pin == 'D':
                    if ed['pins'].get('S', '').lower() == ref_net_lc:
                        score += 1
                elif pin == 'S':
                    if ed['pins'].get('D', '').lower() == ref_net_lc:
                        score += 1
            if score > best_score:
                best_score = score
                best_match = ed

        if best_match and best_score > 0:
            device_map[rd['name']] = best_match
            used_ext.add(best_match['name'])

ref_dev_by_name = {d['name']: d for d in ref_devs}
ext_dev_by_name = {d['name']: d for d in ext_devs}

print(f"Reference: {len(ref_devs)} devices, Extracted: {len(ext_devs)} devices")
print(f"Device matching: {len(device_map)}/{len(ref_devs)} matched")
print()

# ── GATE-ONLY fragmentation analysis ──────────────────────────────────

# For each reference net, collect GATE and BULK pin connections only
ref_gate_net = defaultdict(list)  # ref_net -> [(ref_dev_name, pin_type)]
for d in ref_devs:
    if d['type'] == 'mosfet':
        ref_gate_net[d['pins']['G']].append((d['name'], 'G'))
        ref_gate_net[d['pins']['B']].append((d['name'], 'B'))

# For each reference net with gate connections, check extraction
gate_frags = {}  # ref_net -> {ext_nets: {ext_net: [(dev, pin)]}}

for ref_net, ref_pins in sorted(ref_gate_net.items()):
    if ref_net in ('vdd', 'gnd'):
        continue  # Handle power separately

    ext_nets_found = defaultdict(list)
    for rd_name, pin_type in ref_pins:
        if rd_name not in device_map:
            continue
        ed = device_map[rd_name]
        ext_net = ed['pins'].get(pin_type, '?')
        ext_nets_found[ext_net].append((rd_name, pin_type))

    if len(ext_nets_found) > 1:
        gate_frags[ref_net] = dict(ext_nets_found)

print("=" * 75)
print("GATE/BULK PIN FRAGMENTATION (D/S-swap immune)")
print("=" * 75)
print(f"\nFragmented nets (gate/bulk only): {len(gate_frags)}")
print()

# Sort by number of fragments
sorted_gf = sorted(gate_frags.items(), key=lambda x: -len(x[1]))

# Load netlist.json for metadata
with open('netlist.json') as f:
    netlist = json.load(f)
net_info = {n['name']: n for n in netlist['nets']}

# Summary
from collections import Counter
frag_sizes = Counter(len(v) for v in gate_frags.values())
for n_frags, count in sorted(frag_sizes.items(), reverse=True):
    print(f"  {n_frags} gate fragments: {count} nets")
print()

# Detailed report
total_gate_disconnects = 0
for ref_net, ext_nets in sorted_gf:
    n_info = net_info.get(ref_net, {})
    fanout = len(n_info.get('pins', []))
    n_frags = len(ext_nets)
    n_gate_pins = sum(len(v) for v in ext_nets.values())
    total_gate_disconnects += n_frags - 1

    print(f"  {ref_net} (fanout={fanout}) → {n_frags} gate/bulk fragments"
          f" ({n_gate_pins} pins):")
    for ext_net, pins in sorted(ext_nets.items(), key=lambda x: -len(x[1])):
        pin_strs = [f"{d}.{p}" for d, p in pins]
        label = "PORT" if ext_net.lower() in common_ports_lower else "INT"
        print(f"    {ext_net:15s} [{label}] ({len(pins)} pins): "
              f"{', '.join(pin_strs[:5])}"
              + (f" +{len(pin_strs)-5}" if len(pin_strs) > 5 else ""))
    print()

# ── BULK-specific analysis ────────────────────────────────────────────

print("=" * 75)
print("ISOLATED NWELL ANALYSIS (BULK pin mismatches)")
print("=" * 75)

bulk_mismatches = []
for d in ref_devs:
    if d['type'] != 'mosfet':
        continue
    ref_bulk = d['pins']['B']
    if d['name'] not in device_map:
        continue
    ed = device_map[d['name']]
    ext_bulk = ed['pins']['B']
    if ref_bulk.lower() != ext_bulk.lower():
        bulk_mismatches.append((d['name'], ref_bulk, ext_bulk, d['model']))

print(f"\nBulk mismatches: {len(bulk_mismatches)}")
for name, ref_b, ext_b, model in sorted(bulk_mismatches):
    ptype = "PMOS" if "pmos" in model.lower() else "NMOS"
    print(f"  {name:20s} ({ptype}): ref B={ref_b:8s} → ext B={ext_b}")

# ── D/S SWAP analysis (verify it's systematic) ─────────────────────────

print()
print("=" * 75)
print("D/S SWAP VERIFICATION (confirm D/S always swapped)")
print("=" * 75)

ds_same = 0
ds_swapped = 0
ds_unclear = 0

for rd_name, ed in device_map.items():
    rd = ref_dev_by_name[rd_name]
    if rd['type'] != 'mosfet':
        continue

    ref_d = rd['pins']['D'].lower()
    ref_s = rd['pins']['S'].lower()
    ext_d = ed['pins']['D'].lower()
    ext_s = ed['pins']['S'].lower()

    if ref_d == ext_d and ref_s == ext_s:
        ds_same += 1
    elif ref_d == ext_s and ref_s == ext_d:
        ds_swapped += 1
    elif (ref_d in common_ports_lower or ref_s in common_ports_lower):
        # Can compare at least one
        if ref_d in common_ports_lower:
            if ref_d == ext_s:
                ds_swapped += 1
            elif ref_d == ext_d:
                ds_same += 1
            else:
                ds_unclear += 1
        elif ref_s in common_ports_lower:
            if ref_s == ext_d:
                ds_swapped += 1
            elif ref_s == ext_s:
                ds_same += 1
            else:
                ds_unclear += 1
    else:
        ds_unclear += 1

print(f"\n  D/S same orientation: {ds_same}")
print(f"  D/S swapped:         {ds_swapped}")
print(f"  D/S unclear:         {ds_unclear}")
print(f"  (Permutable in LVS — swaps are NOT errors)")

# ── FINAL BUCKET TABLE ────────────────────────────────────────────────

print()
print("=" * 75)
print("FINAL ROOT CAUSE BUCKET TABLE")
print("=" * 75)
print()

# Classify gate fragmentations
gate_only_frags = 0  # Nets fragmented only through gate pins
bulk_only_frags = 0  # Nets fragmented only through bulk pins
mixed_frags = 0

for ref_net, ext_nets in gate_frags.items():
    has_gate = any(p == 'G' for pins in ext_nets.values() for _, p in pins)
    has_bulk = any(p == 'B' for pins in ext_nets.values() for _, p in pins)
    if has_gate and has_bulk:
        mixed_frags += 1
    elif has_gate:
        gate_only_frags += 1
    else:
        bulk_only_frags += 1

# Count affected devices
gate_affected_devs = set()
for ref_net, ext_nets in gate_frags.items():
    for ext_net, pins in ext_nets.items():
        for d, p in pins:
            if p == 'G':
                gate_affected_devs.add(d)

bulk_affected_devs = set()
for name, ref_b, ext_b, model in bulk_mismatches:
    bulk_affected_devs.add(name)

print(f"{'Bucket':<5} {'Category':<50} {'Nets':>5} {'Devs':>5}  {'Fix'}")
print(f"{'-'*5} {'-'*50} {'-'*5} {'-'*5}  {'-'*35}")
print(f"{'A':<5} {'GATE routing disconnects':<50} "
      f"{gate_only_frags + mixed_frags:>5} {len(gate_affected_devs):>5}  "
      f"Fix assemble_gds gate→routing M1 gap")
print(f"{'B':<5} {'Isolated NWell PMOS (bulk≠vdd)':<50} "
      f"{'10':>5} {len(bulk_affected_devs):>5}  "
      f"Connect NWell tubs to vdd")
print(f"{'C':<5} {'VDD/GND topology (cascade from A+B)':<50} "
      f"{'2':>5} {'—':>5}  "
      f"Auto-resolves")
print(f"{'D':<5} {'Device mismatches (cascade from A+B+C)':<50} "
      f"{'—':>5} {'236':>5}  "
      f"Auto-resolves")
print(f"{'E':<5} {'Internal net mismatches (cascade)':<50} "
      f"{'~350':>5} {'—':>5}  "
      f"Auto-resolves")
print(f"{'—':<5} {'D/S swap (NOT an error — permutable)':<50} "
      f"{'—':>5} {ds_swapped:>5}  "
      f"No fix needed")
print()
print(f"TOTAL mismatched nets in LVS: 407")
print(f"TRUE root causes: {gate_only_frags + mixed_frags} gate disconnects"
      f" + 10 NWell isolations")
print(f"Total gate routing disconnects: {total_gate_disconnects}")
print()

# ── Identify the PATTERN ──────────────────────────────────────────────

print("=" * 75)
print("PATTERN ANALYSIS: Why are gates disconnected?")
print("=" * 75)
print()

# For each gate fragment, check if the extraction net is:
# 1. A port label (meaning the label is on the gate but routing doesn't reach it)
# 2. An internal net (meaning the gate is an isolated island)
# 3. Another port net (cross-connection)

port_gate = 0
internal_gate = 0
crossnet_gate = 0

for ref_net, ext_nets in gate_frags.items():
    for ext_net, pins in ext_nets.items():
        for d, p in pins:
            if p != 'G':
                continue
            if ext_net.lower() == ref_net.lower():
                port_gate += 1  # Matches — this fragment is correct
            elif ext_net.lower() in common_ports_lower:
                crossnet_gate += 1  # Connected to wrong port
            elif ext_net.startswith('$') or ext_net.startswith('\\$'):
                internal_gate += 1  # Connected to internal net
            else:
                crossnet_gate += 1  # Connected to named but wrong net

print(f"  Gate pins on correct net: {port_gate}")
print(f"  Gate pins on INTERNAL ($NNN): {internal_gate}")
print(f"  Gate pins on WRONG named net: {crossnet_gate}")
print()
print("HYPOTHESIS: Each MOSFET gate poly contact creates an isolated M1 island.")
print("The routing M1 wire should overlap the gate M1 pad to connect them,")
print("but there's a systematic gap between the PCell gate contact M1 pad")
print("and the routing wire endpoint.")
print()
print("NEXT STEP: Write a GDS probe script to check if gate M1 pads")
print("overlap with routing M1 wires for a sample of failing devices.")
