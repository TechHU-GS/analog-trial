#!/usr/bin/env python3
"""Compare extracted vs reference SPICE netlists for LVS debugging.

Parses both files, compares device counts by type, identifies
net naming issues, and shows specific mismatches.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_lvs_diff.py
"""
import re, sys, os
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

EXT_FILE = '/tmp/lvs_test2/ptat_vco_extracted.cir'
REF_FILE = 'ptat_vco_lvs.spice'


def parse_spice(path, is_extracted=False):
    """Parse SPICE netlist, return dict of devices and nets."""
    devices = []
    nets = set()
    with open(path) as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        # MOSFET: M<name> D G S B <model> [params]
        m = re.match(r'^M\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(sg13_lv_[np]mos)\s+(.*)', line)
        if m:
            d, g, s, b, model, params = m.groups()
            # Extract W and L
            w_m = re.search(r'W=([\d.]+)u', params)
            l_m = re.search(r'L=([\d.]+)u', params)
            w = float(w_m.group(1)) if w_m else 0
            l = float(l_m.group(1)) if l_m else 0
            devices.append({
                'type': model,
                'D': d, 'G': g, 'S': s, 'B': b,
                'W': w, 'L': l,
                'line': line
            })
            for n in (d, g, s, b):
                nets.add(n)
            continue
        # Resistor: R<name> N1 N2 <model> [params]
        m = re.match(r'^R\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)', line)
        if m:
            n1, n2, model, params = m.groups()
            devices.append({
                'type': model,
                'N1': n1, 'N2': n2,
                'params': params,
                'line': line
            })
            nets.add(n1)
            nets.add(n2)

    return devices, nets


def main():
    ext_devs, ext_nets = parse_spice(EXT_FILE, is_extracted=True)
    ref_devs, ref_nets = parse_spice(REF_FILE)

    # Device counts by type
    ext_counts = defaultdict(int)
    ref_counts = defaultdict(int)
    for d in ext_devs:
        ext_counts[d['type']] += 1
    for d in ref_devs:
        ref_counts[d['type']] += 1

    all_types = sorted(set(list(ext_counts.keys()) + list(ref_counts.keys())))
    print("=== Device Count Comparison ===")
    print(f"{'Type':25s} {'Extracted':>10s} {'Reference':>10s} {'Delta':>8s}")
    for t in all_types:
        e = ext_counts[t]
        r = ref_counts[t]
        delta = e - r
        flag = '  <<<' if delta != 0 else ''
        print(f"{t:25s} {e:10d} {r:10d} {delta:+8d}{flag}")

    # Net comparison
    # Clean up extracted net names (remove backslash escapes)
    ext_clean = set()
    for n in ext_nets:
        ext_clean.add(n.replace('\\', ''))

    print(f"\n=== Net Comparison ===")
    print(f"Extracted nets: {len(ext_nets)}")
    print(f"Reference nets: {len(ref_nets)}")

    # Nets in reference but not extracted
    missing = ref_nets - ext_clean
    # Filter out subckt ports that are internal
    if missing:
        print(f"\nNets in REFERENCE but NOT in extracted ({len(missing)}):")
        for n in sorted(missing):
            print(f"  {n}")

    # Unnamed nets in extracted ($N)
    unnamed = sorted(n for n in ext_nets if n.startswith('$'))
    if unnamed:
        print(f"\nUnnamed nets in extracted: {len(unnamed)}")
        # Show which devices they connect to
        for un in unnamed[:20]:  # limit output
            devs_on_net = []
            for d in ext_devs:
                if d.get('D') == un or d.get('G') == un or d.get('S') == un:
                    devs_on_net.append(d['line'][:80])
                elif d.get('N1') == un or d.get('N2') == un:
                    devs_on_net.append(d['line'][:80])
            print(f"  {un}: {len(devs_on_net)} devices")
            for dl in devs_on_net[:3]:
                print(f"    {dl}")

    # Specific check: multi-finger devices in reference vs extracted
    print(f"\n=== Multi-Finger Device Analysis ===")
    # Group reference devices by (type, L, G, B) — same gate/bulk means same device
    ref_by_key = defaultdict(list)
    for d in ref_devs:
        if d['type'].startswith('sg13'):
            key = (d['type'], d['L'])
            ref_by_key[key].append(d)

    # Group extracted by (type, L, G, B)
    ext_by_key = defaultdict(list)
    for d in ext_devs:
        if d['type'].startswith('sg13'):
            key = (d['type'], d['L'])
            ext_by_key[key].append(d)

    for key in sorted(ref_by_key.keys()):
        r_list = ref_by_key[key]
        e_list = ext_by_key.get(key, [])
        r_total_w = sum(d['W'] for d in r_list)
        e_total_w = sum(d['W'] for d in e_list)
        if abs(r_total_w - e_total_w) > 0.01:
            print(f"  {key}: ref_W={r_total_w:.1f}u ({len(r_list)} devs)"
                  f" ext_W={e_total_w:.1f}u ({len(e_list)} devs)"
                  f" delta_W={e_total_w-r_total_w:+.1f}u")

    # Check gnd/tail merge
    print(f"\n=== Power Net Check ===")
    for net in ('gnd', 'tail', 'gnd|tail', 'vdd', 'vdd_vco'):
        count = sum(1 for n in ext_nets if n == net)
        print(f"  {net}: {'present' if count else 'ABSENT'} in extracted")

    # Check if 'tail' is separate or merged with 'gnd'
    tail_devs = [d for d in ext_devs
                 if any(d.get(p) == 'tail' for p in ('D','G','S','B','N1','N2'))]
    gnd_tail_devs = [d for d in ext_devs
                     if any(d.get(p) == 'gnd|tail' for p in ('D','G','S','B','N1','N2'))]
    print(f"  Devices on 'tail': {len(tail_devs)}")
    print(f"  Devices on 'gnd|tail': {len(gnd_tail_devs)}")

    # Show LVS report if available
    lvsdb = os.path.join(os.path.dirname(EXT_FILE), 'ptat_vco.lvsdb')
    if os.path.exists(lvsdb):
        print(f"\n=== LVS DB Summary ===")
        with open(lvsdb) as f:
            content = f.read()
        # Look for mismatch summary
        for pattern in [r'Netlists.*match', r'Pin mismatch', r'Net mismatch',
                       r'Device mismatch', r'not matched']:
            matches = re.findall(f'.*{pattern}.*', content, re.I)
            for m in matches[:5]:
                print(f"  {m.strip()[:100]}")


if __name__ == '__main__':
    main()
