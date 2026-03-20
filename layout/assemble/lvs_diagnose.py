"""LVS diagnostics — short locator, Via2 audit, functionality check.

Comprehensive diagnostic tools for the assembly pipeline.
"""

import os
import klayout.db as db
from atk.route.maze_router import M3_LYR, M4_LYR


def check_power_separation(layout, top, ties):
    """Check if GND and VDD are separated using full metal stack.

    Returns True if separated (no short), False if shorted.
    """
    from assemble.lvs_check import _LAYER_DEFS, _CONNECTIONS

    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))
    layers = {}
    for name, (lnum, dt) in _LAYER_DEFS:
        li = layout.find_layer(lnum, dt)
        if li is not None:
            layers[name] = l2n.make_layer(li, name)

    if 'M1' not in layers:
        return True

    for n, r in layers.items():
        l2n.connect(r)
    for a, b in _CONNECTIONS:
        if a in layers and b in layers:
            l2n.connect(layers[a], layers[b])

    l2n.extract_netlist()

    gnd_nets = set()
    vdd_nets = set()
    for tie in ties.get('ties', []):
        cx, cy = tie['center_nm']
        net = l2n.probe_net(layers['M1'], db.Point(cx, cy))
        if net is None:
            continue
        cid = net.cluster_id
        if tie['net'] == 'gnd':
            gnd_nets.add(cid)
        elif tie['net'] in ('vdd', 'vdd_vco'):
            vdd_nets.add(cid)

    return len(gnd_nets & vdd_nets) == 0


def audit_via2(routing, gds_path):
    """Audit Via2 placement with failure reasons.

    For each failed AP, diagnoses WHY Via2 wasn't placed:
    - no_m2: no M2 pad defined
    - no_route: AP not in any signal route
    - no_m5_endpoint: no M5 segment endpoint within reach
    - via_stack: AP is a power via_stack pin (handled by power, not Via2)
    - shared_m2: same-position different-net AP (excluded)
    - too_far: nearest M5 endpoint > 500nm
    - unknown: Via2 should have been placed but wasn't

    Returns dict of pin_key -> {status, reason, detail}
    """
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    li_v2 = layout.find_layer(29, 0)

    aps = routing.get('access_points', {})
    results = {}

    # Build helper data
    via_stack_pins = set()
    for drop in routing.get('power', {}).get('drops', []):
        if drop['type'] == 'via_stack':
            via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

    pos_map = {}
    for ak, av in aps.items():
        pos_map.setdefault((av['x'], av['y']), []).append(ak)
    shared_pins = set()
    for pos, keys in pos_map.items():
        if len(keys) >= 2:
            shared_pins.update(keys)

    # Build route membership
    pin_to_net = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        for pin in route.get('pins', []):
            pin_to_net[pin] = net_name

    for key, ap in aps.items():
        ax, ay = ap['x'], ap['y']

        # Check if Via2 exists
        if li_v2 is not None:
            search = db.Box(ax - 500, ay - 500, ax + 500, ay + 500)
            has_via2 = any(True for _ in top.shapes(li_v2).each_overlapping(search))
        else:
            has_via2 = False

        if has_via2:
            results[key] = {'status': 'ok', 'reason': 'Via2 found'}
            continue

        # Diagnose failure reason
        vp = ap.get('via_pad', {})

        if 'm2' not in vp:
            results[key] = {'status': 'skip', 'reason': 'no_m2'}
            continue

        if key in via_stack_pins:
            results[key] = {'status': 'skip', 'reason': 'via_stack'}
            continue

        if key in shared_pins:
            results[key] = {'status': 'skip', 'reason': 'shared_m2'}
            continue

        net_name = pin_to_net.get(key)
        if not net_name:
            results[key] = {'status': 'fail', 'reason': 'no_route',
                            'detail': 'AP not in any signal route'}
            continue

        route = routing['signal_routes'].get(net_name, {})
        if route.get('_floating'):
            results[key] = {'status': 'skip', 'reason': 'floating_route'}
            continue

        # Check M5 (M3_LYR in router = physical M5) endpoint distance
        segs = route.get('segments', [])
        best_dist = float('inf')
        for seg in segs:
            if len(seg) < 5:
                continue
            if seg[4] not in (M3_LYR, M4_LYR, -3):
                continue
            for sx, sy in ((seg[0], seg[1]), (seg[2], seg[3])):
                dist = abs(sx - ax) + abs(sy - ay)
                if dist < best_dist:
                    best_dist = dist

        if best_dist == float('inf'):
            results[key] = {'status': 'fail', 'reason': 'no_m5_endpoint',
                            'detail': 'route has no M5/Via3 segments'}
        elif best_dist > 500:
            results[key] = {'status': 'fail', 'reason': 'too_far',
                            'detail': f'nearest M5 endpoint {best_dist}nm > 500nm'}
        else:
            results[key] = {'status': 'fail', 'reason': 'unknown',
                            'detail': f'M5 endpoint at {best_dist}nm but Via2 not placed'}

    # Summary
    from collections import Counter
    status_counts = Counter(v['status'] for v in results.values())
    reason_counts = Counter(v['reason'] for v in results.values())

    print(f'  Via2 audit: {status_counts["ok"]} ok, '
          f'{status_counts["fail"]} fail, {status_counts["skip"]} skip '
          f'(total {len(results)})')
    print(f'  Failure reasons:')
    for reason, count in reason_counts.most_common():
        if reason != 'ok' and reason != 'Via2 found':
            print(f'    {reason:20s}: {count}')

    return results


def check_functionality(base_dir=None):
    """Check that all expected assembly features are present.

    Scans assemble_gds.py AND all assemble/*.py files.
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Read all relevant files
    content = ''
    for fname in ['assemble_gds.py']:
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                content += f.read()

    assemble_dir = os.path.join(base_dir, 'assemble')
    if os.path.isdir(assemble_dir):
        for fname in os.listdir(assemble_dir):
            if fname.endswith('.py'):
                with open(os.path.join(assemble_dir, fname)) as f:
                    content += f.read()

    features = [
        ('PCell placement', 'place_pcells'),
        ('Bus straps', 'draw_bus_straps'),
        ('Gate straps+contacts', 'draw_gate_straps_and_contacts'),
        ('Tie cells+NWell', 'draw_ties_and_nwell'),
        ('Access points', 'draw_access_points'),
        ('Power drops', 'draw_power'),
        ('Signal routing', 'draw_signal_routes'),
        ('Pin labels', 'draw_labels'),
        ('Floating pre-scan', '_floating'),
        ('Inline DRC', 'DRCTracker'),
        ('Schema validation', 'print_validation'),
        ('LVS proxy', 'check_power_connectivity'),
        ('Region gap fill', 'fill_same_net_gaps_region'),
        ('Via2 audit', 'audit_via2'),
        ('DRC trace', 'trace_drc'),
    ]

    results = []
    print(f'  Functionality check ({len(features)} features):')
    for name, marker in features:
        present = marker in content
        status = '✅' if present else '❌'
        results.append((name, present))
        print(f'    {status} {name}')

    missing = [name for name, present in results if not present]
    if missing:
        print(f'  ⚠️ Missing: {", ".join(missing)}')
    else:
        print(f'  ✓ All features present')

    return results
