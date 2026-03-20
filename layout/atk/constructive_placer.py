#!/usr/bin/env python3
"""Constructive placer v2 — row-structure-aware, parameterized.

Understands NMOS/PMOS pairing, m/s-half bus strap gap, row alternation.
Designed for sweep/GA exploration.

Usage:
    python3 -m atk.constructive_placer --row-x-gap 3.0 --row-y-gap 5.0
"""

import json
import os
from copy import deepcopy


LAYOUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Zone assignment: which row_group bases go in which zone
# Row bases map to _p and _n suffixes (or standalone)
ZONE_ROWS = {
    'sigma_delta': [
        'chopper', 'ota_bias', 'ota_input', 'ota_p',
        'sd_res', 'dac_tg',
        'comp_in', 'comp_latch', 'comp_rst_p',
        'sr', 'sw_tg', 'hbridge', 'nol',
    ],
    'bias': [
        'ptat_mirror', 'bias_pdiode', 'vittoz', 'bias_nmos',
        'cas_mir', 'cas_dev', 'cas_load',
    ],
    'vco': [
        'vco_cs', 'vco_pu', 'vco_pd',
        'buf',
    ],
    'digital_left': [
        'tff_1I', 'tff_1Q', 'tff_2I', 'tff_2Q',
    ],
    'digital_right': [
        'tff_3', 'tff_4I', 'tff_4Q',
        'mux', 'dbuf',
    ],
    'passive': [
        'rptat', 'rout',
    ],
}

# Standalone devices (not in row_groups)
STANDALONE_DEVICES = {
    'C_fb': 'passive',
    'Cbyp_n': 'passive',
    'Cbyp_p': 'passive',
    'INV_iso_n': 'digital_left',
    'INV_iso_p': 'digital_left',
    'INV_isob_n': 'digital_left',
    'INV_isob_p': 'digital_left',
    'M_bias_mir': 'bias',
}

DEFAULT_PARAMS = {
    # Zone Y boundaries
    'z_sd_y': 50,       # sigma-delta zone Y start
    'z_bias_y': 125,    # bias zone Y start
    'z_vco_y': 155,     # VCO zone Y start
    'z_dig_y': 190,     # digital zone Y start
    'z_passive_y': 280, # passive zone Y start

    # X ranges
    'sd_x_min': 10, 'sd_x_max': 190,
    'bias_x_min': 10, 'bias_x_max': 190,
    'vco_x_min': 40, 'vco_x_max': 160,
    'dig_left_x_min': 15, 'dig_left_x_max': 75,
    'dig_right_x_min': 85, 'dig_right_x_max': 160,
    'passive_x_min': 10,

    # Spacing
    'row_x_gap': 3.0,      # X gap between devices in a row
    'bus_strap_gap': 3.5,   # gap between m-half and s-half
    'np_y_gap': 4.5,        # Y gap between NMOS and PMOS in a pair
    'pair_y_gap': 5.0,      # Y gap between row pairs
}


def _load_inputs():
    """Load netlist.json and device_lib.json."""
    with open(os.path.join(LAYOUT_DIR, 'netlist.json')) as f:
        netlist = json.load(f)
    with open(os.path.join(LAYOUT_DIR, 'atk', 'data', 'device_lib.json')) as f:
        device_lib = json.load(f)
    return netlist, device_lib


def _dev_size(dev_name, netlist, device_lib):
    """Get (w, h, type) for a device."""
    for dev in netlist.get('devices', []):
        if dev['name'] == dev_name:
            dt = dev['type']
            lib = device_lib.get(dt, {})
            return lib.get('w_um', 1.0), lib.get('h_um', 1.0), dt
    return 1.0, 1.0, '?'


def _place_row_devices(devs, dev_sizes, x_min, x_max, y, gap, bus_gap=0):
    """Place devices in a row with optional m/s-half split.

    For TFF rows: first half = m-devices, second half = s-devices,
    separated by bus_gap.
    """
    result = {}
    n = len(devs)
    if n == 0:
        return result

    # Detect m/s half split (TFF pattern: m1,m3,m7,m8 | s1,s3,s7,s8)
    has_ms_split = (n >= 4 and bus_gap > 0 and
                    any('_m' in d for d in devs) and
                    any('_s' in d for d in devs))

    if has_ms_split:
        m_devs = [d for d in devs if '_m' in d.split('.')[-1] or
                  (len(d) > 2 and d[-2] == 'm' and d[-1].isdigit()) or
                  '_m' in d]
        s_devs = [d for d in devs if d not in m_devs]

        # Fallback: split by half if naming doesn't work
        if not m_devs or not s_devs:
            mid = n // 2
            m_devs = devs[:mid]
            s_devs = devs[mid:]

        halves = [m_devs, s_devs]
    else:
        halves = [devs]

    # Place each half
    cur_x = x_min
    for hi, half in enumerate(halves):
        for dev_name in half:
            w, h, dt = dev_sizes[dev_name]
            result[dev_name] = {
                'x_um': round(cur_x, 2),
                'y_um': round(y, 2),
                'w_um': w, 'h_um': h, 'type': dt,
            }
            cur_x += w + gap

        if hi == 0 and len(halves) > 1:
            cur_x += bus_gap - gap  # extra gap for bus strap

    return result


def place(netlist, device_lib, params=None):
    """Construct placement from parameters."""
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)

    row_groups = netlist.get('constraints', {}).get('row_groups', {})

    # Build device size map
    dev_sizes = {}
    for dev in netlist.get('devices', []):
        name = dev['name']
        dt = dev['type']
        lib = device_lib.get(dt, {})
        dev_sizes[name] = (lib.get('w_um', 1.0), lib.get('h_um', 1.0), dt)

    instances = {}

    # --- Place each zone ---
    for zone_name, row_bases in ZONE_ROWS.items():
        # Determine zone parameters
        if zone_name == 'sigma_delta':
            cur_y = p['z_sd_y']
            x_min, x_max = p['sd_x_min'], p['sd_x_max']
        elif zone_name == 'bias':
            cur_y = p['z_bias_y']
            x_min, x_max = p['bias_x_min'], p['bias_x_max']
        elif zone_name == 'vco':
            cur_y = p['z_vco_y']
            x_min, x_max = p['vco_x_min'], p['vco_x_max']
        elif zone_name == 'digital_left':
            cur_y = p['z_dig_y']
            x_min, x_max = p['dig_left_x_min'], p['dig_left_x_max']
        elif zone_name == 'digital_right':
            cur_y = p['z_dig_y']
            x_min, x_max = p['dig_right_x_min'], p['dig_right_x_max']
        elif zone_name == 'passive':
            cur_y = p['z_passive_y']
            x_min, x_max = p['passive_x_min'], 190
        else:
            continue

        for row_base in row_bases:
            n_name = row_base + '_n'
            p_name = row_base + '_p'
            has_n = n_name in row_groups
            has_p = p_name in row_groups
            has_single = row_base in row_groups

            if has_n and has_p:
                # Paired NMOS/PMOS rows
                n_devs = row_groups[n_name].get('devices', [])
                p_devs = row_groups[p_name].get('devices', [])

                is_tff = 'tff' in row_base
                bus_gap = p['bus_strap_gap'] if is_tff else 0

                # NMOS row (bottom)
                n_placed = _place_row_devices(
                    n_devs, dev_sizes, x_min, x_max,
                    cur_y, p['row_x_gap'], bus_gap)
                instances.update(n_placed)

                n_h = max((dev_sizes.get(d, (0, 1, ''))[1] for d in n_devs),
                          default=1.36)
                cur_y += n_h + p['np_y_gap']

                # PMOS row (top)
                p_placed = _place_row_devices(
                    p_devs, dev_sizes, x_min, x_max,
                    cur_y, p['row_x_gap'], bus_gap)
                instances.update(p_placed)

                p_h = max((dev_sizes.get(d, (0, 1, ''))[1] for d in p_devs),
                          default=2.62)
                cur_y += p_h + p['pair_y_gap']

            elif has_single:
                # Unpaired row
                devs = row_groups[row_base].get('devices', [])
                placed = _place_row_devices(
                    devs, dev_sizes, x_min, x_max,
                    cur_y, p['row_x_gap'])
                instances.update(placed)

                max_h = max((dev_sizes.get(d, (0, 1, ''))[1] for d in devs),
                            default=1.0)
                cur_y += max_h + p['pair_y_gap']

    # --- Standalone devices ---
    for dev_name, zone in STANDALONE_DEVICES.items():
        if dev_name in instances:
            continue
        w, h, dt = dev_sizes.get(dev_name, (1, 1, '?'))
        if dt == '?':
            continue

        if zone == 'passive':
            # Place after other passives
            passive_x = max((instances[n]['x_um'] + instances[n]['w_um']
                             for n in instances
                             if instances[n]['y_um'] >= p['z_passive_y']),
                            default=p['passive_x_min'])
            instances[dev_name] = {
                'x_um': round(passive_x + 5, 2),
                'y_um': round(p['z_passive_y'], 2),
                'w_um': w, 'h_um': h, 'type': dt,
            }
        elif zone == 'digital_left':
            # Place near digital left, after main rows
            dig_y = max((instances[n]['y_um'] + instances[n]['h_um']
                         for n in instances
                         if p['dig_left_x_min'] <= instances[n]['x_um'] <= p['dig_left_x_max']
                         and instances[n]['y_um'] >= p['z_dig_y']),
                        default=p['z_dig_y'])
            instances[dev_name] = {
                'x_um': round(p['dig_left_x_min'], 2),
                'y_um': round(dig_y + 2, 2),
                'w_um': w, 'h_um': h, 'type': dt,
            }
        elif zone == 'bias':
            instances[dev_name] = {
                'x_um': round(p['bias_x_min'], 2),
                'y_um': round(p['z_bias_y'], 2),
                'w_um': w, 'h_um': h, 'type': dt,
            }

    # --- Build placement.json ---
    if not instances:
        return {'version': 2, 'solver_status': 'empty', 'instances': {},
                'bounding_box': {'w_um': 200, 'h_um': 300, 'area_um2': 60000},
                'nwell_islands': {}, 'tie_strips': {},
                'routing_channels': {}, 'hbt_halos': []}

    all_x = [i['x_um'] + i['w_um'] for i in instances.values()]
    all_y = [i['y_um'] + i['h_um'] for i in instances.values()]

    return {
        'version': 2,
        'solver_status': 'constructive',
        'instances': instances,
        'bounding_box': {
            'w_um': round(max(all_x) + 5, 2),
            'h_um': round(max(all_y) + 5, 2),
            'area_um2': round((max(all_x) + 5) * (max(all_y) + 5), 1),
        },
        'nwell_islands': {},
        'tie_strips': {},
        'routing_channels': {},
        'hbt_halos': [],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Constructive placer v2')
    parser.add_argument('--row-x-gap', type=float, default=3.0)
    parser.add_argument('--row-y-gap', type=float, default=5.0,
                        help='Y gap between row pairs')
    parser.add_argument('--np-y-gap', type=float, default=4.5,
                        help='Y gap between NMOS and PMOS in pair')
    parser.add_argument('--bus-gap', type=float, default=3.5,
                        help='Gap between m-half and s-half')
    parser.add_argument('--output', default='placement.json')
    args = parser.parse_args()

    netlist, device_lib = _load_inputs()

    params = {
        'row_x_gap': args.row_x_gap,
        'pair_y_gap': args.row_y_gap,
        'np_y_gap': args.np_y_gap,
        'bus_strap_gap': args.bus_gap,
    }

    placement = place(netlist, device_lib, params)

    out_path = os.path.join(LAYOUT_DIR, args.output)
    with open(out_path, 'w') as f:
        json.dump(placement, f, indent=2)

    n = len(placement['instances'])
    bb = placement['bounding_box']
    print(f'Placed {n} devices')
    print(f'Bounding box: {bb["w_um"]:.0f} x {bb["h_um"]:.0f} um')

    # Quick stats
    dig_prefixes = {
        'digital_left': ['T1I_', 'T1Q_', 'T2I_', 'T2Q_'],
        'digital_right': ['T3_', 'T4I_', 'T4Q_', 'MX', 'BUF', 'INV'],
    }
    for zone, prefixes in dig_prefixes.items():
        zone_devs = [name for name in placement['instances']
                     if any(name.startswith(pf) for pf in prefixes)]
        if zone_devs:
            xs = [placement['instances'][n]['x_um'] for n in zone_devs]
            ys = [placement['instances'][n]['y_um'] for n in zone_devs]
            print(f'  {zone}: {len(zone_devs)} devs, '
                  f'X={min(xs):.0f}-{max(xs):.0f}, Y={min(ys):.0f}-{max(ys):.0f}')

    print(f'Written: {out_path}')


if __name__ == '__main__':
    main()
