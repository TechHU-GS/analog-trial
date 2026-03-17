#!/usr/bin/env python3
"""LVS Diagnostic: structured analysis of .lvsdb cross-reference.

Reads a KLayout .lvsdb file and outputs a comprehensive JSON report
for automated iteration. Designed to be called after each pipeline run.

Output: output/lvs_report.json (or --output path)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.diagnose_lvs [--lvsdb PATH] [--output PATH]
"""

import argparse
import json
import os
import sys
import klayout.db as kdb


def _get_terminal_nets(device, terminal_names):
    """Get terminal net names for a device."""
    terms = {}
    dc = device.device_class()
    for tname in terminal_names:
        try:
            net = device.net_for_terminal(tname)
            terms[tname] = net.name if net else None
        except RuntimeError:
            pass
    # Also try terminal definitions from class
    if not terms:
        try:
            for tid in range(10):  # max 10 terminals
                td = dc.terminal_definition(tid)
                net = device.net_for_terminal(td.name)
                terms[td.name] = net.name if net else None
        except (RuntimeError, Exception):
            pass
    return terms


def diagnose(lvsdb_path, netlist_path=None):
    """Parse .lvsdb and return structured report dict."""

    db = kdb.LayoutVsSchematic()
    db.read(lvsdb_path)
    xref = db.xref()

    Match = kdb.NetlistCrossReference.Match
    Mismatch = kdb.NetlistCrossReference.Mismatch
    NoMatch = kdb.NetlistCrossReference.NoMatch

    report = {'lvsdb': lvsdb_path}

    for cr in xref.each_circuit_pair():
        ref_c = cr.first()
        ext_c = cr.second()
        report['ref_circuit'] = ref_c.name if ref_c else None
        report['ext_circuit'] = ext_c.name if ext_c else None

        # ── Devices ──
        dev_matched = []
        dev_ref_only = []
        dev_ext_only = []

        mos_terms = ['S', 'G', 'D', 'B']
        res_terms_a = ['A', 'B']

        for dp in xref.each_device_pair(cr):
            rd = dp.first()
            ed = dp.second()
            st = dp.status()

            if rd and ed:
                dev_matched.append({
                    'ref': rd.expanded_name(),
                    'ext': ed.expanded_name(),
                    'class': rd.device_class().name,
                })
            elif rd and not ed:
                cls = rd.device_class().name
                tnames = res_terms_a if 'rhigh' in cls.lower() or 'rppd' in cls.lower() else mos_terms
                terms = _get_terminal_nets(rd, tnames)
                entry = {'name': rd.expanded_name(), 'class': cls, 'terminals': terms}
                # Check PMOS bulk
                if 'pmos' in cls.lower():
                    b = terms.get('B', '')
                    entry['bulk_ok'] = b and 'vdd' in (b or '').lower()
                dev_ref_only.append(entry)
            elif ed and not rd:
                cls = ed.device_class().name
                tnames = res_terms_a if 'rhigh' in cls.upper() or 'rppd' in cls.upper() else mos_terms
                terms = _get_terminal_nets(ed, tnames)
                entry = {'name': ed.expanded_name(), 'class': cls, 'terminals': terms}
                if 'pmos' in cls.lower() or 'PMOS' in cls:
                    b = terms.get('B', '')
                    entry['bulk_ok'] = b and 'VDD' in (b or '').upper()
                dev_ext_only.append(entry)

        report['devices'] = {
            'matched': len(dev_matched),
            'ref_only': dev_ref_only,
            'ext_only': dev_ext_only,
            'ref_only_count': len(dev_ref_only),
            'ext_only_count': len(dev_ext_only),
        }

        # PMOS bulk summary
        ref_pmos = [d for d in dev_ref_only if 'pmos' in d['class'].lower()]
        wrong_bulk = [d for d in ref_pmos if not d.get('bulk_ok', True)]
        report['pmos_bulk'] = {
            'ref_only_pmos': len(ref_pmos),
            'wrong_bulk': [{'name': d['name'], 'bulk': d['terminals'].get('B')}
                           for d in wrong_bulk],
            'correct_bulk_unmatched': len(ref_pmos) - len(wrong_bulk),
        }

        # Device class breakdown
        from collections import Counter
        ref_cls = Counter(d['class'] for d in dev_ref_only)
        ext_cls = Counter(d['class'] for d in dev_ext_only)
        report['device_classes'] = {
            'ref_only': dict(ref_cls),
            'ext_only': dict(ext_cls),
        }

        # ── Nets ──
        net_matched = []
        net_ref_only = []
        net_ext_only = []
        comma_merges = []

        for np_item in xref.each_net_pair(cr):
            rn = np_item.first()
            en = np_item.second()
            st = np_item.status()

            rname = rn.name if rn else None
            ename = en.name if en else None

            if rn and en:
                net_matched.append({'ref': rname, 'ext': ename})
            elif rn and not en:
                net_ref_only.append(rname)
                if rname and ',' in rname:
                    comma_merges.append(rname)
            elif en and not rn:
                net_ext_only.append(ename)

        ref_named = [n for n in net_ref_only if n and not n.startswith('$')]
        ref_anon = [n for n in net_ref_only if n and n.startswith('$')]
        ext_named = [n for n in net_ext_only if n and not n.startswith('$')]

        report['nets'] = {
            'matched': len(net_matched),
            'ref_only': len(net_ref_only),
            'ext_only': len(net_ext_only),
            'ref_only_named': sorted(ref_named),
            'ref_only_anon_count': len(ref_anon),
            'ext_only_named': sorted(ext_named),
            'comma_merges': comma_merges,
            'matched_pairs': net_matched,
        }

        # ── Pins ──
        pin_matched = pin_mm = 0
        for pp in xref.each_pin_pair(cr):
            if pp.status() == Match:
                pin_matched += 1
            else:
                pin_mm += 1
        report['pins'] = {'matched': pin_matched, 'mismatched': pin_mm}

        # ── Summary ──
        total_unmatched = len(net_ref_only) + len(net_ext_only)
        report['summary'] = {
            'devices_matched': len(dev_matched),
            'devices_unmatched': len(dev_ref_only) + len(dev_ext_only),
            'nets_matched': len(net_matched),
            'nets_unmatched': total_unmatched,
            'comma_merges': len(comma_merges),
            'wrong_bulk_pmos': len(wrong_bulk),
            'pins_matched': pin_matched,
            'pins_mismatched': pin_mm,
        }

        break  # only one circuit pair

    return report


def main():
    parser = argparse.ArgumentParser(description='LVS Diagnostic Report')
    parser.add_argument('--lvsdb', default='/tmp/lvs_run/soilz.lvsdb',
                        help='Path to .lvsdb file')
    parser.add_argument('--output', default='output/lvs_report.json',
                        help='Output JSON path')
    args = parser.parse_args()

    if not os.path.exists(args.lvsdb):
        print(f'  ERROR: {args.lvsdb} not found')
        sys.exit(1)

    report = diagnose(args.lvsdb)

    # Write JSON
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)

    # Print summary
    s = report['summary']
    print(f'  === LVS Diagnostic ===')
    print(f'  Devices: {s["devices_matched"]} matched, '
          f'{s["devices_unmatched"]} unmatched')
    print(f'  Nets:    {s["nets_matched"]} matched, '
          f'{s["nets_unmatched"]} unmatched')
    print(f'  Comma merges: {s["comma_merges"]}')
    if report.get('nets', {}).get('comma_merges'):
        for cm in report['nets']['comma_merges']:
            print(f'    {cm}')
    print(f'  Wrong-bulk PMOS: {s["wrong_bulk_pmos"]}')
    print(f'  Pins: {s["pins_matched"]} matched, {s["pins_mismatched"]} mismatched')
    print(f'  Written: {args.output}')


if __name__ == '__main__':
    main()
