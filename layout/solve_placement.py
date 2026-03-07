#!/usr/bin/env python3
"""CP-SAT placement solver for PTAT+VCO layout.

Phase 2: reads ALL constraints from netlist.json + device_lib.json.
No hardcoded device sizes or instance lists.

Usage:
    cd /private/tmp/analog-trial/layout
    source ~/pdk/venv/bin/activate
    python solve_placement.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from atk.place import ConstraintPlacer
from atk.pdk import channel_width, UM, PLACE_GAP_1T


def load_inputs():
    """Load netlist.json and device_lib.json, build solver device dict."""
    with open('netlist.json') as f:
        nl = json.load(f)
    with open('atk/data/device_lib.json') as f:
        dlib = json.load(f)

    solver_devs = {}
    for d in nl['devices']:
        lib = dlib[d['type']]
        bbox = lib['bbox']
        solver_devs[d['name']] = {
            'w': (bbox[2] - bbox[0]) / 1000.0,
            'h': (bbox[3] - bbox[1]) / 1000.0,
            'type': d['type'],
            'has_nwell': d['has_nwell'],
            'nwell_net': d['nwell_net'],
        }
    # HBT halo: inflate effective size for substrate contact ring reservation
    hbt_halo = nl['constraints']['drc_spacing'].get('hbt_halo_um', 0.0)
    if hbt_halo > 0:
        for d in nl['devices']:
            if d['type'].startswith('hbt_'):
                name = d['name']
                solver_devs[name] = dict(solver_devs[name])
                solver_devs[name]['w'] += 2 * hbt_halo
                solver_devs[name]['h'] += 2 * hbt_halo

    return nl, dlib, solver_devs


def solve():
    """Build CP-SAT model from netlist.json constraints, solve."""
    nl, dlib, solver_devs = load_inputs()
    c = nl['constraints']

    placer = ConstraintPlacer(solver_devs, grid=0.10)
    placer.setup(max_width=120.0, max_height=100.0)

    # 1. Row groups
    for row_name, row_def in c['row_groups'].items():
        gap = row_def.get('gap_um', PLACE_GAP_1T / UM)
        placer.add_row(row_name, row_def['devices'], gap=gap)

    # 2. Tie strip reservation (PMOS→ntap above, NMOS→ptap below)
    tie = c['tie_reservation']
    ntap_h = tie['pmos_ntap']['keepout_h_nm'] / 1000.0
    ptap_h = tie['nmos_ptap']['keepout_h_nm'] / 1000.0
    pmos_types = set(tie['pmos_ntap']['applies_to'])
    nmos_types = set(tie['nmos_ptap']['applies_to'])
    for rn, rd in c['row_groups'].items():
        first_type = solver_devs[rd['devices'][0]]['type']
        if first_type in pmos_types:
            placer.add_tie_strip(rn, 'above', ntap_h)
        if first_type in nmos_types:
            placer.add_tie_strip(rn, 'below', ptap_h)

    # 3. Routing channels (row spacing with halos applied internally)
    for ch in c['routing_channels']['row_channels']:
        placer.add_row_spacing(ch['above'], ch['below'], n_tracks=ch['n_tracks'])

    # 4. NWell island spacing
    ws = c['well_aware_spacing']
    placer.add_nwell_spacing(ws['nwell_islands'], ws['inter_island_min_nm'] / 1000.0)

    # 5. Matching: equal spacing + symmetry + adjacency
    for mg in c['matching']['match_groups']:
        placer.add_equal_spacing(mg['devices'])
    for sym in c['matching']['symmetry']:
        placer.add_symmetry_y(sym['devices'][0], sym['devices'][1])
        placer.add_adjacent(sym['devices'][0], sym['devices'][1], sym['max_distance_um'])
    for kc in c['matching']['keep_close']:
        placer.add_adjacent(kc['devices'][0], kc['devices'][1], kc['max_distance_um'])

    # 6. Y alignment (row names)
    for ya in c['y_align']:
        for i in range(len(ya) - 1):
            placer.add_same_y(ya[i], ya[i + 1])

    # 7. X alignment (device columns)
    for xa in c['x_align']:
        for i in range(len(xa) - 1):
            placer.add_x_align(xa[i], xa[i + 1], max_offset_um=1.0)

    # 8. X ordering
    for xo in c['x_order']:
        placer.add_x_order(xo['a'], xo['b'], min_gap_um=xo['min_gap_um'])

    # 9. Electrical proximity: VCO inverter pairing (MPu↔MPd drain-drain)
    if 'electrical_proximity' in c:
        ep = c['electrical_proximity']
        for pair in ep.get('inverter_pairs', []):
            placer.add_y_range(pair['pu'], pair['pd'], pair['max_dy_um'])
        for pair in ep.get('bias_pairs', []):
            placer.add_y_range(pair['inv'], pair['bias'], pair['max_dy_um'])
        # supply_entry: Riso near NWell_A — handled by row placement (y_align + x_order)

    # 10. HBT extra spacing (wider gap for CntB.h1, halo already inflated in load_inputs)
    hbt_devs = [d['name'] for d in nl['devices'] if d['type'].startswith('hbt_')]
    others = [d['name'] for d in nl['devices'] if not d['type'].startswith('hbt_')]
    hbt_pairs = [(h, o) for h in hbt_devs for o in others]
    placer._add_no_overlap_pairs(hbt_pairs, c['drc_spacing']['hbt_gap_nm'] / 1000.0)

    # 11. Global no-overlap (default gap)
    placer.add_no_overlap(min_gap_um=c['drc_spacing']['default_gap_nm'] / 1000.0)

    # 12. Isolation zones (if defined)
    if 'isolation' in c:
        iso = c['isolation']
        zones = {z['name']: z['devices'] for z in iso.get('zones', [])}
        min_gaps = iso.get('min_zone_gap', [])
        if zones and min_gaps:
            placer.add_zone_isolation(zones, min_gaps)

    # 13. Wirelength-aware objective + edge keepout
    # Build device_pins map from device_lib for HPWL computation
    signal_nets = [n for n in nl['nets'] if n['type'] == 'signal']
    device_pins = {}
    for d in nl['devices']:
        lib = dlib.get(d['type'], {})
        pins = lib.get('pins', {})
        bbox = lib.get('bbox', [0, 0, 0, 0])
        ox = bbox[0] / 1000.0  # nm → µm offset
        for pin_name, pin_info in pins.items():
            pos = pin_info.get('pos_nm', [0, 0])
            # Pin position relative to device placement origin (µm)
            device_pins[(d['name'], pin_name)] = (
                (pos[0] - bbox[0]) / 1000.0,
                (pos[1] - bbox[1]) / 1000.0,
            )

    if signal_nets and device_pins:
        placer.set_nets(signal_nets, device_pins)
        wl_weight = c.get('wirelength_weight', 0.5)
        placer.minimize_area_and_wirelength(wl_weight=wl_weight)
    else:
        placer.minimize_area()

    if 'edge_keepout' in c:
        placer.add_edge_keepout(c['edge_keepout']['margin_um'])

    # 13. Solve (WORKFLOW.md: seed=42, 60s, 1 worker)
    print('=== CP-SAT Placement Solver (Phase 2) ===')
    placer.print_summary()
    print()
    result = placer.solve(time_limit=60.0)

    return result, nl, solver_devs, c


def build_placement_json(result, nl, solver_devs, constraints):
    """Build enriched placement.json from solver result + netlist constraints."""
    c = constraints
    hbt_halo = c['drc_spacing'].get('hbt_halo_um', 0.0)
    hbt_names = {d['name'] for d in nl['devices'] if d['type'].startswith('hbt_')}

    # De-inflate HBT: solver placed inflated box at (x,y), real device at (x+halo, y+halo)
    real_result = {}
    real_devs = {}
    for name, (x, y) in result.items():
        if name in hbt_names and hbt_halo > 0:
            real_result[name] = (x + hbt_halo, y + hbt_halo)
            real_devs[name] = dict(solver_devs[name])
            real_devs[name]['w'] -= 2 * hbt_halo
            real_devs[name]['h'] -= 2 * hbt_halo
        else:
            real_result[name] = (x, y)
            real_devs[name] = solver_devs[name]

    # Bounding box (includes edge keepout margin on all sides)
    edge_margin = c.get('edge_keepout', {}).get('margin_um', 0.0)
    max_x = max(x + solver_devs[n]['w'] for n, (x, y) in result.items()) + edge_margin
    max_y = max(y + solver_devs[n]['h'] for n, (x, y) in result.items()) + edge_margin

    # Instances (real device positions/sizes)
    instances = {}
    for name, (x, y) in real_result.items():
        instances[name] = {
            'x_um': round(x, 2),
            'y_um': round(y, 2),
            'type': real_devs[name]['type'],
            'w_um': round(real_devs[name]['w'], 2),
            'h_um': round(real_devs[name]['h'], 2),
        }
    # HBT halos (for visualization)
    hbt_halos = {}
    if hbt_halo > 0:
        for name in hbt_names:
            x, y = result[name]
            hbt_halos[name] = {
                'x_um': round(x, 2), 'y_um': round(y, 2),
                'w_um': round(solver_devs[name]['w'], 2),
                'h_um': round(solver_devs[name]['h'], 2),
                'halo_um': hbt_halo,
            }

    # Tie strips (computed from row Y positions + device heights)
    tie = c['tie_reservation']
    pmos_types = set(tie['pmos_ntap']['applies_to'])
    nmos_types = set(tie['nmos_ptap']['applies_to'])
    tie_strips = {}
    for rn, rd in c['row_groups'].items():
        devs_in_row = rd['devices']
        if not devs_in_row:
            continue
        first_type = solver_devs[devs_in_row[0]]['type']
        row_y = result[devs_in_row[0]][1]
        row_h = max(solver_devs[d]['h'] for d in devs_in_row)

        if first_type in pmos_types:
            ntap_h = tie['pmos_ntap']['keepout_h_nm'] / 1000.0
            nwell_net = solver_devs[devs_in_row[0]].get('nwell_net', 'vdd')
            tie_strips[f'{rn}_ntap'] = {
                'y_um': round(row_y + row_h, 2),
                'h_um': round(ntap_h, 2),
                'type': 'ntap',
                'net': nwell_net,
                'row': rn,
            }
        if first_type in nmos_types:
            ptap_h = tie['nmos_ptap']['keepout_h_nm'] / 1000.0
            tie_strips[f'{rn}_ptap'] = {
                'y_um': round(row_y - ptap_h, 2),
                'h_um': round(ptap_h, 2),
                'type': 'ptap',
                'net': 'gnd',
                'row': rn,
            }

    # NWell islands with computed bboxes (use real device positions, not inflated)
    nwell_islands = []
    for island in c['well_aware_spacing']['nwell_islands']:
        devs = [d for d in island['devices'] if d in real_result]
        if not devs:
            continue
        x1 = min(real_result[d][0] for d in devs)
        y1 = min(real_result[d][1] for d in devs)
        x2 = max(real_result[d][0] + real_devs[d]['w'] for d in devs)
        y2 = max(real_result[d][1] + real_devs[d]['h'] for d in devs)
        nwell_islands.append({
            'id': island['id'],
            'net': island['net'],
            'devices': island['devices'],
            'bbox_um': [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
        })

    # Routing channels with computed Y positions
    routing_channels = []
    for ch in c['routing_channels']['row_channels']:
        above_row = ch['above']
        below_row = ch['below']
        below_devs = c['row_groups'][below_row]['devices']
        above_devs = c['row_groups'][above_row]['devices']
        if below_devs and above_devs:
            below_top = max(
                result[d][1] + solver_devs[d]['h'] for d in below_devs)
            above_bot = min(result[d][1] for d in above_devs)
            routing_channels.append({
                'above': above_row,
                'below': below_row,
                'y_um': round(below_top, 2),
                'h_um': round(above_bot - below_top, 2),
                'n_tracks': ch['n_tracks'],
            })

    data = {
        'version': '2.1',
        'solver_status': 'OPTIMAL',
        'bounding_box': {
            'w_um': round(max_x, 2),
            'h_um': round(max_y, 2),
            'area_um2': round(max_x * max_y, 0),
        },
        'instances': instances,
        'tie_strips': tie_strips,
        'nwell_islands': nwell_islands,
        'routing_channels': routing_channels,
        'hbt_halos': hbt_halos,
    }
    return data


def main():
    result, nl, solver_devs, constraints = solve()

    if result is None:
        print('\nPlacement FAILED — check constraints')
        sys.exit(1)

    # Print coordinates
    print('\n  Device placements (x, y in µm):')
    for name in sorted(result.keys()):
        x, y = result[name]
        dev = solver_devs[name]
        print(f'    {name:10s}  ({x:6.2f}, {y:6.2f})  {dev["w"]:.2f}x{dev["h"]:.2f}')

    # Build enriched placement.json
    data = build_placement_json(result, nl, solver_devs, constraints)

    # Write output — canonical path from atk.paths
    from atk.paths import PLACEMENT_JSON
    with open(PLACEMENT_JSON, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    print(f'\n  Written: {PLACEMENT_JSON}')
    print(f'  Bounding box: {data["bounding_box"]["w_um"]:.1f} x {data["bounding_box"]["h_um"]:.1f} µm')
    print(f'  Tie strips: {len(data["tie_strips"])}')
    print(f'  NWell islands: {len(data["nwell_islands"])}')
    print(f'  Routing channels: {len(data["routing_channels"])}')


if __name__ == '__main__':
    main()
