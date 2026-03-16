#!/usr/bin/env python3
"""Compare extracted vs reference netlists for LVS device matching.

Parses both SPICE netlists and compares device counts by (model, L, W).
Also lists individual devices to help identify multi-finger splitting.
"""
import re
import sys
from collections import Counter, defaultdict

def parse_spice_devices(filepath):
    """Parse SPICE netlist, return list of (name, model, params_dict)."""
    devices = []
    with open(filepath) as f:
        lines = f.readlines()

    # Join continuation lines
    joined = []
    for line in lines:
        line = line.rstrip('\n')
        if line.startswith('+') and joined:
            joined[-1] += ' ' + line[1:].strip()
        else:
            joined.append(line)

    for line in joined:
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue

        # MOSFET: Mname n1 n2 n3 n4 model params...
        m = re.match(r'^M(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)', line)
        if m:
            name = m.group(1)
            model = m.group(6)
            param_str = m.group(7)
            params = {}
            for pm in re.finditer(r'(\w+)=([\d.]+\w*)', param_str):
                params[pm.group(1)] = pm.group(2)
            devices.append(('M', name, model, params))
            continue

        # Resistor: Rname n1 n2 model params...
        m = re.match(r'^R(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)', line)
        if m:
            name = m.group(1)
            model = m.group(4)
            param_str = m.group(5)
            params = {}
            for pm in re.finditer(r'(\w+)=([\d.]+\w*)', param_str):
                params[pm.group(1)] = pm.group(2)
            devices.append(('R', name, model, params))
            continue

    return devices


def normalize_param(val):
    """Normalize parameter value: '2u' -> '2u', '2.0u' -> '2u'."""
    m = re.match(r'^([\d.]+)(.*)', val)
    if m:
        num = float(m.group(1))
        suffix = m.group(2)
        if num == int(num):
            return f"{int(num)}{suffix}"
        return f"{num}{suffix}"
    return val


def device_key(dev):
    """Return (prefix, model, L, W) tuple for comparison."""
    prefix, name, model, params = dev
    L = normalize_param(params.get('L', params.get('l', '?')))
    W = normalize_param(params.get('W', params.get('w', '?')))
    return (prefix, model, L, W)


# Parse both
ext_file = sys.argv[1] if len(sys.argv) > 1 else '/tmp/lvs_run4/ptat_vco_extracted.cir'
ref_file = sys.argv[2] if len(sys.argv) > 2 else 'ptat_vco_lvs.spice'

print(f"Extracted: {ext_file}")
print(f"Reference: {ref_file}")

ext_devs = parse_spice_devices(ext_file)
ref_devs = parse_spice_devices(ref_file)

print(f"\nExtracted: {len(ext_devs)} devices")
print(f"Reference: {len(ref_devs)} devices")

# Count by (prefix, model, L, W)
ext_counts = Counter()
ref_counts = Counter()

for d in ext_devs:
    ext_counts[device_key(d)] += 1
for d in ref_devs:
    ref_counts[device_key(d)] += 1

# All keys
all_keys = sorted(set(ext_counts.keys()) | set(ref_counts.keys()))

print(f"\n{'Key':<50} {'Ext':>5} {'Ref':>5} {'Diff':>6}")
print("-" * 70)

total_ext = 0
total_ref = 0
mismatches = []
for k in all_keys:
    e = ext_counts[k]
    r = ref_counts[k]
    total_ext += e
    total_ref += r
    diff = e - r
    marker = " ***" if diff != 0 else ""
    label = f"{k[0]} {k[1]} L={k[2]} W={k[3]}"
    print(f"{label:<50} {e:>5} {r:>5} {diff:>+6}{marker}")
    if diff != 0:
        mismatches.append((k, e, r, diff))

print("-" * 70)
print(f"{'TOTAL':<50} {total_ext:>5} {total_ref:>5} {total_ext-total_ref:>+6}")

if mismatches:
    print(f"\n{len(mismatches)} mismatched categories:")
    net_diff = sum(abs(d) for _, _, _, d in mismatches)
    print(f"  Total absolute diff: {net_diff}")

    # Group by model to see patterns
    print(f"\n--- NMOS mismatches ---")
    for k, e, r, d in mismatches:
        if 'nmos' in k[1]:
            print(f"  {k[1]} L={k[2]} W={k[3]}: ext={e} ref={r} ({d:+d})")

    print(f"\n--- PMOS mismatches ---")
    for k, e, r, d in mismatches:
        if 'pmos' in k[1]:
            print(f"  {k[1]} L={k[2]} W={k[3]}: ext={e} ref={r} ({d:+d})")

    print(f"\n--- Resistor mismatches ---")
    for k, e, r, d in mismatches:
        if k[0] == 'R':
            print(f"  {k[1]} L={k[2]} W={k[3]}: ext={e} ref={r} ({d:+d})")
else:
    print("\nALL MATCH!")

# Also list individual ext devices for mismatched categories
if mismatches:
    print(f"\n=== Individual devices in mismatched categories ===")
    mismatch_keys = {k for k, _, _, _ in mismatches}

    print("\n--- Extracted ---")
    for d in ext_devs:
        k = device_key(d)
        if k in mismatch_keys:
            prefix, name, model, params = d
            print(f"  {prefix}{name}: {model} {' '.join(f'{pk}={pv}' for pk,pv in params.items())}")

    print("\n--- Reference ---")
    for d in ref_devs:
        k = device_key(d)
        if k in mismatch_keys:
            prefix, name, model, params = d
            print(f"  {prefix}{name}: {model} {' '.join(f'{pk}={pv}' for pk,pv in params.items())}")
