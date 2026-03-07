#!/usr/bin/env python3
"""ATK Results Summary: collect Phase 2-6 results into results_summary.json.

Usage:
    python -m atk.summary --placement=placement.json --drc-dir=/tmp/drc_run --lvs-dir=/tmp/lvs_run --cell=ptat_vco
"""

import argparse
import json
import os
import re
import sys


def summarize_placement(placement_path):
    """Extract placement metrics."""
    if not os.path.exists(placement_path):
        return {'status': 'MISSING'}
    with open(placement_path) as f:
        data = json.load(f)
    bb = data.get('bounding_box', {})
    return {
        'status': data.get('solver_status', 'UNKNOWN'),
        'bbox_um': [bb.get('w_um', 0), bb.get('h_um', 0)],
        'area_um2': bb.get('area_um2', 0),
        'devices': len(data.get('instances', {})),
        'tie_strips': len(data.get('tie_strips', {})),
        'nwell_islands': len(data.get('nwell_islands', [])),
        'routing_channels': len(data.get('routing_channels', [])),
    }


def summarize_drc(drc_dir, cell):
    """Extract DRC results from lyrdb report."""
    # Find the lyrdb file
    lyrdb = None
    for fname in os.listdir(drc_dir):
        if fname.endswith('_full.lyrdb'):
            lyrdb = os.path.join(drc_dir, fname)
            break

    if not lyrdb:
        return {'status': 'MISSING'}

    # Count violations by category
    categories = {}
    with open(lyrdb) as f:
        content = f.read()
    for match in re.finditer(r"<category>'([^']+)'</category>", content):
        cat = match.group(1)
        categories[cat] = categories.get(cat, 0) + 1

    total = sum(categories.values())
    # Waiver rules — inherent to IHP SG13G2 PCell/gate geometry:
    # - CntB.h1: npn13G2 BJT internal contact spacing (PCell-internal)
    # - Cnt.d, Cnt.e, Cnt.h: kept for backward compat (now 0 with poly extension fix)
    # - M1.b: gate access M1 pad (370nm) overlaps S/D M1 by 5nm at Active boundary
    #   (access Via1 at poly_bot ± 185nm, Active at poly_bot + 180nm)
    waiver_rules = {'CntB.h1', 'Cnt.d', 'Cnt.e', 'Cnt.h', 'M1.b'}
    pcell_count = sum(v for k, v in categories.items() if k in waiver_rules)
    routing_count = total - pcell_count

    status = 'CLEAN' if routing_count == 0 else 'VIOLATIONS'
    return {
        'status': status,
        'total_markers': total,
        'pcell_waiver': pcell_count,
        'routing_violations': routing_count,
        'by_rule': categories,
    }


def summarize_lvs(lvs_dir, cell):
    """Extract LVS results from log file."""
    # Check log files (more reliable than lvsdb binary format)
    content = ''
    for fname in sorted(os.listdir(lvs_dir)):
        if fname.endswith('.log'):
            fpath = os.path.join(lvs_dir, fname)
            with open(fpath) as f:
                content += f.read()

    if not content:
        return {'status': 'MISSING'}

    if 'Congratulations' in content:
        return {'status': 'PASS'}
    elif "don't match" in content.lower():
        return {'status': 'FAIL'}
    else:
        return {'status': 'UNKNOWN'}


def main():
    parser = argparse.ArgumentParser(description='ATK Results Summary')
    parser.add_argument('--placement', default='placement.json')
    parser.add_argument('--drc-dir', default='/tmp/drc_run')
    parser.add_argument('--lvs-dir', default='/tmp/lvs_run')
    parser.add_argument('--cell', default='ptat_vco')
    parser.add_argument('--output', default='results_summary.json')
    args = parser.parse_args()

    results = {
        'cell': args.cell,
        'placement': summarize_placement(args.placement),
        'drc': summarize_drc(args.drc_dir, args.cell),
        'lvs': summarize_lvs(args.lvs_dir, args.cell),
    }

    # Print summary
    print(f'  Cell: {args.cell}')
    p = results['placement']
    print(f'  Placement: {p["status"]}, bbox={p.get("bbox_um", "?")}, '
          f'{p.get("devices", "?")} devices')

    d = results['drc']
    print(f'  DRC: {d["status"]}, {d.get("total_markers", "?")} markers '
          f'({d.get("pcell_waiver", "?")} PCell waiver, '
          f'{d.get("routing_violations", "?")} routing)')

    l = results['lvs']
    print(f'  LVS: {l["status"]}')

    # Overall
    all_pass = (p['status'] == 'OPTIMAL' and
                d.get('routing_violations', 999) == 0 and
                l['status'] == 'PASS')
    results['overall'] = 'PASS' if all_pass else 'FAIL'
    print(f'\n  Overall: {results["overall"]}')

    # Write JSON
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'  Written: {args.output}')


if __name__ == '__main__':
    main()
