#!/usr/bin/env python3
"""Compare device pin connections between reference and extracted SPICE.

Parses both netlists, matches devices by (model, W, L), and shows
which pins differ. Focus on finding cascade root causes.

Usage:
    cd layout && python3 diagnose_pin_compare.py
"""
import os
import re
import sys
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

REF_FILE = 'ptat_vco_lvs.spice'
EXT_FILE = '/tmp/lvs_r32d/ptat_vco_extracted.cir'


def parse_spice(path):
    """Parse flat SPICE into list of device dicts."""
    devices = []
    with open(path) as f:
        lines = f.readlines()

    # Join continuation lines
    joined = []
    for line in lines:
        line = line.rstrip('\n')
        if line.startswith('+'):
            if joined:
                joined[-1] += ' ' + line[1:].strip()
            continue
        joined.append(line)

    for line in joined:
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue

        parts = line.split()
        if not parts:
            continue

        name = parts[0]
        if name.startswith('M') or name.startswith('m'):
            # MOSFET: Mname D G S B model [params...]
            if len(parts) < 6:
                continue
            d_net = parts[1]
            g_net = parts[2]
            s_net = parts[3]
            b_net = parts[4]
            model = parts[5]

            # Parse W and L from remaining params
            w = l = None
            for p in parts[6:]:
                if p.upper().startswith('W='):
                    w = p.split('=')[1].rstrip('u')
                elif p.upper().startswith('L='):
                    l = p.split('=')[1].rstrip('u')

            devices.append({
                'name': name,
                'type': 'mosfet',
                'model': model,
                'pins': {'D': d_net, 'G': g_net, 'S': s_net, 'B': b_net},
                'W': w, 'L': l,
                'key': f"{model}_W{w}_L{l}",
            })

        elif name.startswith('R') or name.startswith('r'):
            # Resistor: Rname n1 n2 model [params...]
            if len(parts) < 4:
                continue
            plus_net = parts[1]
            minus_net = parts[2]
            model = parts[3]

            w = l = b = m = None
            for p in parts[4:]:
                kv = p.split('=')
                if len(kv) == 2:
                    if kv[0].lower() == 'w':
                        w = kv[1].rstrip('u')
                    elif kv[0].lower() == 'l':
                        l = kv[1].rstrip('u')
                    elif kv[0].lower() == 'b':
                        b = kv[1]
                    elif kv[0].lower() == 'm':
                        m = kv[1]

            devices.append({
                'name': name,
                'type': 'resistor',
                'model': model,
                'pins': {'PLUS': plus_net, 'MINUS': minus_net},
                'W': w, 'L': l,
                'key': f"{model}_W{w}_L{l}",
            })

    return devices


# ── Parse both netlists ─────────────────────────────────────────────────

ref_devs = parse_spice(REF_FILE)
ext_devs = parse_spice(EXT_FILE)

print(f"Reference: {len(ref_devs)} devices from {REF_FILE}")
print(f"Extracted: {len(ext_devs)} devices from {EXT_FILE}")
print()

# ── Match devices by (model, W, L) ─────────────────────────────────────

# Group by key
ref_by_key = defaultdict(list)
ext_by_key = defaultdict(list)

for d in ref_devs:
    ref_by_key[d['key']].append(d)
for d in ext_devs:
    ext_by_key[d['key']].append(d)

# Report key distribution
print("=" * 70)
print("DEVICE KEY MATCHING")
print("=" * 70)

all_keys = sorted(set(list(ref_by_key.keys()) + list(ext_by_key.keys())))
unmatched_keys = []
for key in all_keys:
    r_count = len(ref_by_key.get(key, []))
    e_count = len(ext_by_key.get(key, []))
    if r_count != e_count:
        unmatched_keys.append((key, r_count, e_count))
        print(f"  MISMATCH {key}: ref={r_count}, ext={e_count}")

if not unmatched_keys:
    print("  All device keys match in count!")
print()

# ── For each device key, compare pin connections ────────────────────────

# Strategy: for keys with count=1 on both sides, direct comparison.
# For keys with count>1, try to match by common pins.

print("=" * 70)
print("PIN CONNECTION COMPARISON (single-instance devices)")
print("=" * 70)

# Collect all port names (nets that appear in both extracted and reference .subckt)
# These should be named the same. For internal nets, we need topology matching.
# For now, focus on port nets which should have matching names.

# Read port list from extracted
ext_ports = set()
with open(EXT_FILE) as f:
    in_subckt = False
    for line in f:
        line = line.strip()
        if line.startswith('.SUBCKT'):
            parts = line.split()[2:]
            ext_ports.update(parts)
            in_subckt = True
        elif in_subckt and line.startswith('+'):
            ext_ports.update(line.strip().lstrip('+ ').split())
        elif in_subckt:
            in_subckt = False

# Read port list from reference
ref_ports = set()
with open(REF_FILE) as f:
    in_subckt = False
    for line in f:
        line = line.strip()
        if line.startswith('.subckt'):
            parts = line.split()[2:]
            ref_ports.update(parts)
            in_subckt = True
        elif in_subckt and line.startswith('+'):
            ref_ports.update(line.strip().lstrip('+ ').split())
        elif in_subckt:
            in_subckt = False

# Common ports (should be the same since we matched them)
# Note: KLayout ports are UPPERCASE, reference are lowercase
common_ports = set()
for p in ext_ports:
    if p.lower() in {rp.lower() for rp in ref_ports}:
        common_ports.add(p.lower())

print(f"Common port nets: {len(common_ports)}")
print()

# For single-instance device keys, compare pin nets using common ports
pin_diff_summary = defaultdict(list)  # net_name -> [(device, pin, ref_val, ext_val)]

single_keys = [k for k in all_keys
               if len(ref_by_key.get(k, [])) == 1 and len(ext_by_key.get(k, [])) == 1]

print(f"Single-instance device keys: {len(single_keys)}")
print()

for key in sorted(single_keys):
    rd = ref_by_key[key][0]
    ed = ext_by_key[key][0]

    diffs = []
    for pin in sorted(rd['pins'].keys()):
        r_net = rd['pins'].get(pin, '?')
        e_net = ed['pins'].get(pin, '?')

        # Normalize: ref uses lowercase, extracted uses mixed
        r_lower = r_net.lower()
        e_lower = e_net.lower()

        # Both are port nets?
        r_is_port = r_lower in common_ports
        e_is_port = e_lower in common_ports

        if r_is_port and e_is_port:
            # Both are port nets — must match
            if r_lower != e_lower:
                diffs.append((pin, r_net, e_net, 'PORT_MISMATCH'))
                pin_diff_summary[f"port:{r_lower}→{e_lower}"].append(
                    (rd['name'], pin))
        elif r_is_port and not e_is_port:
            # Ref has port, extracted has internal — missing connection
            diffs.append((pin, r_net, e_net, 'REF_PORT_EXT_INTERNAL'))
            pin_diff_summary[f"missing_port:{r_lower}"].append(
                (rd['name'], pin))
        elif not r_is_port and e_is_port:
            # Ref has internal, extracted has port — extra connection
            diffs.append((pin, r_net, e_net, 'REF_INTERNAL_EXT_PORT'))
            pin_diff_summary[f"extra_port:{e_lower}"].append(
                (rd['name'], pin))
        # else: both internal — can't compare by name

    if diffs:
        print(f"  {rd['name']:20s} ({key}):")
        for pin, r_net, e_net, dtype in diffs:
            print(f"    {pin}: ref={r_net:20s} ext={e_net:20s} [{dtype}]")

# ── Summary: most common pin differences ────────────────────────────────

print()
print("=" * 70)
print("PIN DIFFERENCE SUMMARY (grouped by difference type)")
print("=" * 70)

for diff_key in sorted(pin_diff_summary.keys(),
                        key=lambda k: -len(pin_diff_summary[k])):
    devs = pin_diff_summary[diff_key]
    dev_names = [f"{d}:{p}" for d, p in devs]
    print(f"  {diff_key}: {len(devs)} devices")
    for dn in dev_names[:5]:
        print(f"    {dn}")
    if len(dev_names) > 5:
        print(f"    ... and {len(dev_names)-5} more")

# ── VDD/GND bulk connection analysis ───────────────────────────────────

print()
print("=" * 70)
print("BULK CONNECTION ANALYSIS")
print("=" * 70)

# For all MOSFETs: compare bulk connections
# PMOS bulk should be vdd (or specific nwell_net)
# NMOS bulk should be gnd

ref_bulk = defaultdict(int)
ext_bulk = defaultdict(int)

for d in ref_devs:
    if d['type'] == 'mosfet':
        b = d['pins']['B'].lower()
        ref_bulk[b] += 1
for d in ext_devs:
    if d['type'] == 'mosfet':
        b = d['pins']['B'].lower()
        ext_bulk[b] += 1

print("Reference bulk nets:")
for net, count in sorted(ref_bulk.items(), key=lambda x: -x[1]):
    print(f"  {net}: {count} devices")

print("Extracted bulk nets:")
for net, count in sorted(ext_bulk.items(), key=lambda x: -x[1]):
    print(f"  {net}: {count} devices")

# Check for PMOS with non-vdd bulk in extracted
print()
print("Extracted PMOS with non-vdd bulk:")
for d in ext_devs:
    if d['type'] == 'mosfet' and 'pmos' in d['model'].lower():
        b = d['pins']['B'].lower()
        if b != 'vdd':
            print(f"  {d['name']}: B={d['pins']['B']} "
                  f"(D={d['pins']['D']}, G={d['pins']['G']}, S={d['pins']['S']})")

print()
print("Extracted NMOS with non-gnd bulk:")
for d in ext_devs:
    if d['type'] == 'mosfet' and 'nmos' in d['model'].lower():
        b = d['pins']['B'].lower()
        if b != 'gnd':
            print(f"  {d['name']}: B={d['pins']['B']} "
                  f"(D={d['pins']['D']}, G={d['pins']['G']}, S={d['pins']['S']})")

# ── Multi-instance keys: show distribution ──────────────────────────────

print()
print("=" * 70)
print("MULTI-INSTANCE DEVICE KEYS (count > 1)")
print("=" * 70)

multi_keys = [k for k in all_keys
              if len(ref_by_key.get(k, [])) > 1 or len(ext_by_key.get(k, [])) > 1]

for key in sorted(multi_keys):
    rds = ref_by_key.get(key, [])
    eds = ext_by_key.get(key, [])
    print(f"  {key}: ref={len(rds)}, ext={len(eds)}")

    # For port nets only, show what pins connect to
    if len(rds) <= 5:
        for rd in rds:
            port_pins = {p: n for p, n in rd['pins'].items()
                         if n.lower() in common_ports}
            if port_pins:
                print(f"    ref {rd['name']}: {port_pins}")
