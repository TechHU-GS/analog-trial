#!/usr/bin/env python3
"""Phase 3: Tie cell placement for latchup compliance.

Reads placement.json (Phase 2 output) + device_lib.json + tie_templates.json + netlist.json.
Computes tie cell positions, runs gate verification, writes ties.json.

Usage:
    cd /private/tmp/analog-trial/layout
    source ~/pdk/venv/bin/activate
    python solve_ties.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from atk.paths import PLACEMENT_JSON, NETLIST_JSON, DEVICE_LIB_JSON, TIES_JSON
from atk.tie import TiePlacer


def main():
    # Load inputs — all paths from atk.paths (single source of truth)
    with open(PLACEMENT_JSON) as f:
        placement = json.load(f)
    with open(DEVICE_LIB_JSON) as f:
        device_lib = json.load(f)
    with open(os.path.join(os.path.dirname(DEVICE_LIB_JSON), 'tie_templates.json')) as f:
        tie_templates = json.load(f)
    with open(NETLIST_JSON) as f:
        netlist = json.load(f)

    print('=' * 60)
    print('Phase 3: Tie Cell Placement')
    print('=' * 60)

    # Create placer and solve
    placer = TiePlacer(placement, device_lib, tie_templates, netlist)
    ties = placer.solve()

    # Print results
    ntap_count = sum(1 for t in ties if t['type'] == 'ntap')
    ptap_count = sum(1 for t in ties if t['type'] == 'ptap')
    print(f'\n  Ties placed: {len(ties)} ({ntap_count} ntap + {ptap_count} ptap)')

    print('\n  ntap (PMOS → NWell tie):')
    for t in sorted(ties, key=lambda x: x['device']):
        if t['type'] != 'ntap':
            continue
        cx, cy = t['center_nm']
        print(f'    {t["device"]:7s}: cx={cx/1000:.2f} cy={cy/1000:.2f} µm  '
              f'lu={t["lu_distance_nm"]}nm  cont={t["cont_config"]}  → {t["net"]}')

    print('\n  ptap (NMOS → substrate tie):')
    for t in sorted(ties, key=lambda x: x['device']):
        if t['type'] != 'ptap':
            continue
        cx, cy = t['center_nm']
        print(f'    {t["device"]:7s}: cx={cx/1000:.2f} cy={cy/1000:.2f} µm  '
              f'lu={t["lu_distance_nm"]}nm  → {t["net"]}')

    # NWell extensions
    print(f'\n  NWell extensions: {len(placer.nwell_extensions)}')
    for ext in placer.nwell_extensions:
        print(f'    {ext["tie_id"]}: width={ext["width_nm"]}nm net={ext["net"]}  '
              f'{"< 2990 OK" if ext["width_nm"] < 2990 else "NBULAY!"}')

    # Gate verification
    print('\n' + '=' * 60)
    print('Phase 3 Gate Verification')
    print('=' * 60)

    n_pass, n_total, errors = placer.verify()

    check_names = [
        'LU.a coverage (PMOS→ntap ≤ 20µm)',
        'LU.b coverage (NMOS→ptap ≤ 20µm)',
        'M1 conflict (tie M1 vs device M1 ≥ 180nm)',
        'nBuLay (NWell ext width < 2990nm)',
        'NWell bridge net isolation',
        'Tie side (ntap above PMOS, ptap below NMOS)',
        'Activ overlap (tie Activ vs device Activ)',
    ]
    # Re-run individual checks for detailed output
    placer_verify_detail(placer, check_names)

    print('\n' + '=' * 60)
    if errors:
        print(f'GATE FAILED: {n_pass}/{n_total} passed')
        for e in errors:
            print(f'  {e}')
        # Still write output for debugging
    else:
        print(f'GATE PASSED: {n_pass}/{n_total} ALL PASS')

    # Write ties.json
    data = placer.to_json()
    os.makedirs(os.path.dirname(TIES_JSON), exist_ok=True)

    with open(TIES_JSON, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    print(f'\n  Written: {TIES_JSON}')

    if errors:
        sys.exit(1)


def placer_verify_detail(placer, check_names):
    """Print detailed verification results."""
    from atk.tie.tie_placer import M1_MIN_S, NBULAY_THRESHOLD, NW_E
    from atk.pdk import UM

    ties = placer.ties
    instances = placer.instances
    constraints = placer.constraints

    # Check 1: LU.a
    print(f'\n[1/7] {check_names[0]}')
    max_lu = constraints['tie_reservation']['pmos_ntap']['max_distance_nm']
    pmos_types = set(constraints['tie_reservation']['pmos_ntap']['applies_to'])
    ntap_ties = {t['device']: t for t in ties if t['type'] == 'ntap'}
    for name in sorted(instances.keys()):
        if instances[name]['type'] not in pmos_types:
            continue
        t = ntap_ties.get(name)
        if t:
            status = 'OK' if t['lu_distance_nm'] <= max_lu else 'FAIL'
            print(f'  {status}: {name} lu={t["lu_distance_nm"]}nm <= {max_lu}nm')

    # Check 2: LU.b
    print(f'\n[2/7] {check_names[1]}')
    nmos_types = set(constraints['tie_reservation']['nmos_ptap']['applies_to'])
    ptap_ties = {t['device']: t for t in ties if t['type'] == 'ptap'}
    for name in sorted(instances.keys()):
        if instances[name]['type'] not in nmos_types:
            continue
        t = ptap_ties.get(name)
        if t:
            status = 'OK' if t['lu_distance_nm'] <= max_lu else 'FAIL'
            print(f'  {status}: {name} lu={t["lu_distance_nm"]}nm <= {max_lu}nm')

    # Check 3: M1 conflict
    print(f'\n[3/7] {check_names[2]}')
    conflict_count = 0
    for tie in ties:
        m1 = tie['m1_pad']
        inflated = [m1[0] - M1_MIN_S, m1[1] - M1_MIN_S,
                    m1[2] + M1_MIN_S, m1[3] + M1_MIN_S]
        conflicts = placer._check_m1_conflict(inflated, skip_device=tie['device'])
        if conflicts:
            for dev, rect in conflicts:
                print(f'  FAIL: {tie["id"]} ↔ {dev}')
            conflict_count += len(conflicts)
    if conflict_count == 0:
        print(f'  OK: {len(ties)} ties checked, 0 conflicts')

    # Check 4: nBuLay
    print(f'\n[4/7] {check_names[3]}')
    for ext in placer.nwell_extensions:
        status = 'OK' if ext['width_nm'] < NBULAY_THRESHOLD else 'FAIL'
        print(f'  {status}: {ext["tie_id"]} w={ext["width_nm"]}nm')

    # Check 5: NWell bridge net
    print(f'\n[5/7] {check_names[4]}')
    bridge_ok = True
    for ext in placer.nwell_extensions:
        for island in placer.nwell_islands:
            if island['net'] == ext['net']:
                continue
            ib = [round(v * UM) for v in island['bbox_um']]
            ib_ext = [ib[0] - NW_E, ib[1] - NW_E, ib[2] + NW_E, ib[3] + NW_E]
            ext_rect = ext['rect_nm']
            if (ext_rect[0] < ib_ext[2] and ext_rect[2] > ib_ext[0] and
                    ext_rect[1] < ib_ext[3] and ext_rect[3] > ib_ext[1]):
                print(f'  FAIL: {ext["tie_id"]}({ext["net"]}) ↔ {island["id"]}({island["net"]})')
                bridge_ok = False
    if bridge_ok:
        print(f'  OK: {len(placer.nwell_extensions)} NWell extensions, no cross-net overlap')

    # Check 6: Tie on correct side
    print(f'\n[6/7] {check_names[5]}')
    side_ok = True
    for tie in ties:
        inst = placer.instances[tie['device']]
        dev_cy = round(inst['y_um'] * UM) + round(inst['h_um'] * UM) // 2
        tie_cy = tie['center_nm'][1]
        correct = (tie['type'] == 'ntap' and tie_cy > dev_cy) or \
                  (tie['type'] == 'ptap' and tie_cy < dev_cy)
        if not correct:
            print(f'  FAIL: {tie["id"]} wrong side (tie_cy={tie_cy}, dev_cy={dev_cy})')
            side_ok = False
    if side_ok:
        print(f'  OK: {len(ties)} ties all on correct side of device')

    # Check 7: Activ overlap
    print(f'\n[7/7] {check_names[6]}')
    activ_ok = True
    for tie in ties:
        tie_act = tie['activ']
        for dev_name, act_shapes in placer._activ_obstacles.items():
            if dev_name == tie['device']:
                continue
            for s in act_shapes:
                if (tie_act[0] < s[2] and tie_act[2] > s[0] and
                        tie_act[1] < s[3] and tie_act[3] > s[1]):
                    print(f'  FAIL: {tie["id"]} overlaps {dev_name} activ {s}')
                    activ_ok = False
    if activ_ok:
        print(f'  OK: {len(ties)} ties, no Activ overlap with devices')


if __name__ == '__main__':
    main()
