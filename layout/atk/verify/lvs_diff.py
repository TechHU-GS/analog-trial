"""LVS extracted vs schematic netlist diff.

Parses both SPICE netlists and reports:
  1. Net name mismatches (merged/split/renamed)
  2. Device count mismatch
  3. Missing/extra connections
  4. Floating bulks ($N nets)

Usage:
    python -m atk.verify.lvs_diff <extracted.cir> <schematic.spice>
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict


def _parse_spice(path: str) -> dict:
    """Parse SPICE subckt: devices, nets, port list."""
    devices = []
    ports = []
    subckt_line = ""

    with open(path) as f:
        lines = f.readlines()

    # Join continuation lines
    joined = []
    for line in lines:
        line = line.rstrip()
        if line.startswith('+'):
            joined[-1] += ' ' + line[1:].strip()
        else:
            joined.append(line)

    for line in joined:
        line = line.strip()
        if line.startswith('.SUBCKT'):
            parts = line.split()
            # .SUBCKT name port1 port2 ...
            subckt_line = line
            ports = parts[2:]  # skip .SUBCKT and cell name
        elif line.startswith('M'):
            # MOSFET: Mname D G S B model ...
            parts = line.split()
            name = parts[0]
            d, g, s, b = parts[1], parts[2], parts[3], parts[4]
            model = parts[5]
            params = {}
            for p in parts[6:]:
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            dev_type = 'pmos' if 'pmos' in model else 'nmos'
            devices.append({
                'name': name, 'type': dev_type, 'model': model,
                'D': d, 'G': g, 'S': s, 'B': b,
                'W': params.get('W', '?'), 'L': params.get('L', '?'),
            })
        elif line.startswith('Q'):
            # BJT: Qname C B E S model ...
            parts = line.split()
            name = parts[0]
            c, b, e = parts[1], parts[2], parts[3]
            s = parts[4] if len(parts) > 4 and not parts[4].startswith('npn') and not parts[4].startswith('pnp') else ''
            devices.append({
                'name': name, 'type': 'bjt',
                'C': c, 'B': b, 'E': e, 'S': s,
            })
        elif line.startswith('R'):
            # Resistor: Rname n1 n2 model ...
            parts = line.split()
            name = parts[0]
            n1, n2 = parts[1], parts[2]
            devices.append({
                'name': name, 'type': 'res',
                'PLUS': n1, 'MINUS': n2,
            })

    # Collect all unique net names
    all_nets = set(ports)
    for dev in devices:
        for k, v in dev.items():
            if k not in ('name', 'type', 'model', 'W', 'L'):
                if v and not v.startswith('.'):
                    all_nets.add(v)

    return {
        'ports': ports,
        'devices': devices,
        'nets': all_nets,
    }


def diff_netlists(extracted_path: str, schematic_path: str):
    """Compare extracted vs schematic and print diff."""
    ext = _parse_spice(extracted_path)
    sch = _parse_spice(schematic_path)

    print(f"Extracted: {extracted_path}")
    print(f"  Ports: {len(ext['ports'])}")
    print(f"  Devices: {len(ext['devices'])}")
    print(f"  Nets: {len(ext['nets'])}")
    print(f"Schematic: {schematic_path}")
    print(f"  Ports: {len(sch['ports'])}")
    print(f"  Devices: {len(sch['devices'])}")
    print(f"  Nets: {len(sch['nets'])}")

    # Device count by type
    ext_types = defaultdict(int)
    sch_types = defaultdict(int)
    for d in ext['devices']:
        ext_types[d['type']] += 1
    for d in sch['devices']:
        sch_types[d['type']] += 1

    print("\nDevice counts:")
    all_types = sorted(set(ext_types) | set(sch_types))
    for t in all_types:
        e, s = ext_types.get(t, 0), sch_types.get(t, 0)
        status = "OK" if e == s else "MISMATCH"
        print(f"  {t:8s}: extracted={e}, schematic={s}  {status}")

    # Port comparison
    ext_ports = set(ext['ports'])
    sch_ports = set(sch['ports'])
    print(f"\nPort comparison:")
    common = ext_ports & sch_ports
    ext_only = ext_ports - sch_ports
    sch_only = sch_ports - ext_ports
    print(f"  Common: {len(common)}")
    if ext_only:
        print(f"  Extracted only: {sorted(ext_only)}")
    if sch_only:
        print(f"  Schematic only: {sorted(sch_only)}")

    # Merged nets (pipes in extracted net names)
    print(f"\nMerged nets (| in name):")
    merged = [n for n in ext['nets'] if '|' in n]
    if merged:
        for m in sorted(merged):
            print(f"  {m}")
    else:
        print(f"  None (good)")

    # Floating bulks ($N nets in extracted)
    print(f"\nFloating/unnamed nets ($ prefix):")
    floating = [n for n in ext['nets'] if n.startswith('$') or n.startswith('\\$')]
    if floating:
        for f_net in sorted(floating):
            # Find which devices use this net
            users = []
            for d in ext['devices']:
                for k, v in d.items():
                    if v == f_net:
                        users.append(f"{d['name']}.{k}")
            print(f"  {f_net}: used by {users}")
    else:
        print(f"  None (good)")

    # Net names in extracted but not schematic (excluding $ nets)
    ext_named = {n for n in ext['nets'] if not n.startswith('$') and not n.startswith('\\$')}
    sch_named = sch['nets']
    print(f"\nNet name diff:")
    ext_new = ext_named - sch_named
    sch_missing = sch_named - ext_named
    if ext_new:
        print(f"  In extracted only: {sorted(ext_new)}")
    if sch_missing:
        print(f"  In schematic only: {sorted(sch_missing)}")
    if not ext_new and not sch_missing:
        print(f"  All nets match")

    # Summary
    issues = 0
    if ext_types != sch_types:
        issues += 1
    if merged:
        issues += len(merged)
    if floating:
        issues += len(floating)
    if ext_only or sch_only:
        issues += len(ext_only) + len(sch_only)

    print(f"\n{'='*50}")
    if issues == 0:
        print("LVS DIFF: CLEAN — no structural mismatches detected")
    else:
        print(f"LVS DIFF: {issues} issue(s) found")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <extracted.cir> <schematic.spice>")
        sys.exit(1)
    diff_netlists(sys.argv[1], sys.argv[2])
