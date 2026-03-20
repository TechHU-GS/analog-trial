#!/usr/bin/env python3
"""LVS diagnostic loop — integrated merge detection, categorization, tracking.

Connects the full LVS feedback chain:
  L2N merge detection → Via2 audit → KLayout LVS cross-reference → categorized report

Usage:
    python3 -m atk.lvs_loop \\
        --gds output/soilz.gds \\
        --routing output/routing.json \\
        --ties output/ties.json \\
        --placement placement.json \\
        [--lvs-report output/lvs_report.json] \\
        [--output output/lvs_diagnostic.json] \\
        [--prev output/lvs_diagnostic_prev.json]

Categories:
    same_device_dg  — D/G of same MOSFET share M1 cluster (bus strap gap issue)
    power_signal    — signal net shares cluster with GND/VDD
    cross_device    — different devices' pins share cluster (M1 bridge)
    substrate       — merge in KLayout LVS but NOT in L2N (NWell/diffusion)
    via2_failure    — AP can't get Via2 (too_far / no_route / M3 conflict)
    fragmentation   — power net split into multiple clusters
"""

import argparse
import json
import os
from collections import Counter, defaultdict


# ── Metal layer definitions (same as lvs_check.py) ──
_LAYER_DEFS = [
    ('M1',  (8, 0)),   ('M2',  (10, 0)),  ('M3',  (30, 0)),
    ('M4',  (50, 0)),  ('M5',  (67, 0)),  ('TM1', (126, 0)),
    ('Via1', (19, 0)), ('Via2', (29, 0)),  ('Via3', (49, 0)),
    ('Via4', (66, 0)), ('TV1',  (125, 0)),
]
_CONNECTIONS = [
    ('Via1', 'M1'), ('Via1', 'M2'),
    ('Via2', 'M2'), ('Via2', 'M3'),
    ('Via3', 'M3'), ('Via3', 'M4'),
    ('Via4', 'M4'), ('Via4', 'M5'),
    ('TV1',  'M5'), ('TV1',  'TM1'),
]


def _build_l2n(layout, top):
    """Build LayoutToNetlist with full metal stack."""
    import klayout.db as db
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))
    layers = {}
    for name, (lnum, dt) in _LAYER_DEFS:
        li = layout.find_layer(lnum, dt)
        if li is not None:
            layers[name] = l2n.make_layer(li, name)
    for region in layers.values():
        l2n.connect(region)
    for a, b in _CONNECTIONS:
        if a in layers and b in layers:
            l2n.connect(layers[a], layers[b])
    l2n.extract_netlist()
    return l2n, layers


def _build_l2n_lower(layout, top):
    """Build L2N with M1+Via1+M2 only (for M2 cluster safety check)."""
    import klayout.db as db
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))
    layers = {}
    for name, (lnum, dt) in [('M1', (8, 0)), ('Via1', (19, 0)), ('M2', (10, 0))]:
        li = layout.find_layer(lnum, dt)
        if li is not None:
            layers[name] = l2n.make_layer(li, name)
    for region in layers.values():
        l2n.connect(region)
    if 'Via1' in layers and 'M1' in layers:
        l2n.connect(layers['Via1'], layers['M1'])
    if 'Via1' in layers and 'M2' in layers:
        l2n.connect(layers['Via1'], layers['M2'])
    l2n.extract_netlist()
    return l2n, layers


def detect_merges(gds_path, routing, ties):
    """Detect metal merges using full-stack L2N.

    Returns:
        merge_pairs: list of {net_a, net_b, category, devices, cluster_id, bbox}
        power_frag: {gnd_clusters, vdd_clusters, shared}
        ap_clusters: {pin_key: cluster_id}
    """
    import klayout.db as db
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    # ── Full-stack L2N for merge detection ──
    l2n, layers = _build_l2n(layout, top)

    # Build pin→net map
    pin_net = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        for pin in route.get('pins', []):
            pin_net[pin] = net_name
    for net_name, route in routing.get('pre_routes', {}).items():
        for pin in route.get('pins', []):
            pin_net[pin] = net_name

    # Probe APs on M1
    aps = routing.get('access_points', {})
    cluster_pins = {}  # cluster_id -> [(pin_key, net, x, y)]
    ap_clusters = {}   # pin_key -> cluster_id

    probe_layer = layers.get('M1')
    if not probe_layer:
        return [], {}, {}

    for key, ap in aps.items():
        net = pin_net.get(key)
        if not net:
            continue
        ax, ay = ap['x'], ap['y']
        net_obj = l2n.probe_net(probe_layer, db.Point(ax, ay))
        if net_obj is not None:
            cid = net_obj.cluster_id
            cluster_pins.setdefault(cid, []).append((key, net, ax, ay))
            ap_clusters[key] = cid

    # Probe power (ties)
    gnd_clusters = set()
    vdd_clusters = set()
    for tie in ties.get('ties', []):
        cx, cy = tie['center_nm']
        net_obj = l2n.probe_net(probe_layer, db.Point(cx, cy))
        if net_obj is not None:
            cid = net_obj.cluster_id
            if tie['net'] == 'gnd':
                gnd_clusters.add(cid)
            elif tie['net'] in ('vdd', 'vdd_vco'):
                vdd_clusters.add(cid)

    # ── Find merge pairs ──
    merge_pairs = []
    seen_pairs = set()

    for cid, pins in cluster_pins.items():
        nets = set(n for _, n, _, _ in pins)
        if len(nets) <= 1:
            continue

        # Categorize
        devices = set()
        for key, _, _, _ in pins:
            dev = key.rsplit('.', 1)[0] if '.' in key else key
            devices.add(dev)

        # Check if same-device D/G
        pin_types = defaultdict(set)  # device -> set of pin types (D, G, S)
        for key, net, _, _ in pins:
            if '.' in key:
                dev, pin_type = key.rsplit('.', 1)
                pin_types[dev].add(pin_type)

        is_same_device_dg = any(
            'D' in ptypes and 'G' in ptypes
            for ptypes in pin_types.values()
        )

        # Check power involvement
        is_power = cid in gnd_clusters or cid in vdd_clusters

        # Determine category
        if is_power:
            category = 'power_signal'
        elif is_same_device_dg and len(devices) <= 2:
            category = 'same_device_dg'
        else:
            category = 'cross_device'

        # Build bbox
        xs = [x for _, _, x, _ in pins]
        ys = [y for _, _, _, y in pins]
        bbox = (min(xs), min(ys), max(xs), max(ys))

        # Record unique net pairs
        net_list = sorted(nets)
        for i in range(len(net_list)):
            for j in range(i + 1, len(net_list)):
                pair_key = (net_list[i], net_list[j])
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    merge_pairs.append({
                        'net_a': net_list[i],
                        'net_b': net_list[j],
                        'category': category,
                        'cluster_id': cid,
                        'devices': sorted(devices),
                        'pins': [(k, n) for k, n, _, _ in pins],
                        'bbox_nm': bbox,
                    })

    power_frag = {
        'gnd_clusters': len(gnd_clusters),
        'vdd_clusters': len(vdd_clusters),
        'gnd_vdd_shared': len(gnd_clusters & vdd_clusters),
    }

    return merge_pairs, power_frag, ap_clusters


def audit_via2(routing, gds_path):
    """Run Via2 audit (delegates to lvs_diagnose)."""
    try:
        from assemble.lvs_diagnose import audit_via2 as _audit
        return _audit(routing, gds_path)
    except Exception as e:
        print(f'  Via2 audit failed: {e}')
        return {}


def detect_l2n_safe_pins(gds_path, routing):
    """Find APs safe for expanded Via2 M3 search using M1+Via1+M2 L2N."""
    import klayout.db as db
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    l2n, layers = _build_l2n_lower(layout, top)

    pin_net = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        for pin in route.get('pins', []):
            pin_net[pin] = net_name

    aps = routing.get('access_points', {})
    cluster_pins = {}
    for key, ap in aps.items():
        net = pin_net.get(key)
        if not net:
            continue
        net_obj = l2n.probe_net(layers['M2'], db.Point(ap['x'], ap['y']))
        if net_obj is not None:
            cluster_pins.setdefault(net_obj.cluster_id, []).append((key, net))

    safe = set()
    unsafe = set()
    for cid, pins in cluster_pins.items():
        nets = set(n for _, n in pins)
        target = safe if len(nets) == 1 else unsafe
        for key, _ in pins:
            target.add(key)

    return safe, unsafe


def cross_reference_lvs(merge_pairs, lvs_report):
    """Cross-reference L2N merges with KLayout LVS results."""
    if not lvs_report:
        return

    klvs_merges = lvs_report.get('nets', {}).get('comma_merges', [])
    if not klvs_merges:
        klvs_merges = []

    # Build set of KLayout LVS merge net pairs
    klvs_pairs = set()
    for merge_str in klvs_merges:
        nets = merge_str.split(',') if isinstance(merge_str, str) else merge_str
        for i in range(len(nets)):
            for j in range(i + 1, len(nets)):
                klvs_pairs.add((min(nets[i], nets[j]), max(nets[i], nets[j])))

    # Check which L2N merges are confirmed by KLayout LVS
    for mp in merge_pairs:
        pair = (min(mp['net_a'], mp['net_b']), max(mp['net_a'], mp['net_b']))
        mp['klvs_confirmed'] = pair in klvs_pairs

    # Find KLayout LVS merges NOT detected by L2N (substrate merges)
    l2n_pairs = set()
    for mp in merge_pairs:
        l2n_pairs.add((min(mp['net_a'], mp['net_b']),
                        max(mp['net_a'], mp['net_b'])))

    substrate_merges = []
    for pair in klvs_pairs:
        if pair not in l2n_pairs:
            substrate_merges.append({
                'net_a': pair[0],
                'net_b': pair[1],
                'category': 'substrate',
                'note': 'KLayout LVS merge not detected by metal-only L2N',
            })

    return substrate_merges


def run_diagnostic(gds_path, routing_path, ties_path, placement_path,
                   lvs_report_path=None, output_path=None, prev_path=None):
    """Run the full LVS diagnostic loop."""
    # ── Load data ──
    with open(routing_path) as f:
        routing = json.load(f)
    with open(ties_path) as f:
        ties = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)

    lvs_report = None
    if lvs_report_path and os.path.exists(lvs_report_path):
        with open(lvs_report_path) as f:
            lvs_report = json.load(f)

    prev = None
    if prev_path and os.path.exists(prev_path):
        with open(prev_path) as f:
            prev = json.load(f)

    print(f'\n{"=" * 65}')
    print(f' LVS Diagnostic Loop')
    print(f' GDS: {gds_path}')
    print(f'{"=" * 65}')

    # ═══ 1. Metal merge detection (L2N) ═══
    print(f'\n{"=" * 65}')
    print(f' 1. METAL MERGE DETECTION (L2N)')
    print(f'{"=" * 65}')

    merge_pairs, power_frag, ap_clusters = detect_merges(
        gds_path, routing, ties)

    by_category = Counter(mp['category'] for mp in merge_pairs)
    print(f'\n  Found {len(merge_pairs)} merge pairs:')
    for cat, cnt in by_category.most_common():
        print(f'    {cat:20s}: {cnt}')

    print(f'\n  Power fragmentation:')
    print(f'    GND: {power_frag["gnd_clusters"]} clusters')
    print(f'    VDD: {power_frag["vdd_clusters"]} clusters')
    print(f'    Shared: {power_frag["gnd_vdd_shared"]}')

    # Detail per category
    for cat in ['same_device_dg', 'power_signal', 'cross_device']:
        cat_merges = [mp for mp in merge_pairs if mp['category'] == cat]
        if not cat_merges:
            continue
        print(f'\n  [{cat}] ({len(cat_merges)} pairs):')
        for mp in cat_merges[:15]:
            devs = ', '.join(mp['devices'][:3])
            bx = mp['bbox_nm']
            loc = f'({bx[0]/1000:.0f},{bx[1]/1000:.0f})'
            print(f'    {mp["net_a"]:15s} ↔ {mp["net_b"]:15s}  '
                  f'{devs:30s} {loc}')
        if len(cat_merges) > 15:
            print(f'    ... +{len(cat_merges) - 15} more')

    # ═══ 2. Via2 audit ═══
    print(f'\n{"=" * 65}')
    print(f' 2. VIA2 AUDIT')
    print(f'{"=" * 65}')

    via2_results = audit_via2(routing, gds_path)

    via2_reasons = Counter(v['reason'] for v in via2_results.values())
    via2_ok = via2_reasons.pop('Via2 found', 0)
    via2_fail = sum(c for r, c in via2_reasons.items()
                    if r not in ('via_stack', 'shared_m2'))
    via2_skip = via2_reasons.get('via_stack', 0) + via2_reasons.get('shared_m2', 0)

    print(f'\n  Via2: {via2_ok} ok, {via2_fail} fail, {via2_skip} skip')
    print(f'  Success rate: {100 * via2_ok / max(1, via2_ok + via2_fail):.0f}%')
    for reason, count in sorted(via2_reasons.items(), key=lambda x: -x[1]):
        if reason in ('via_stack', 'shared_m2'):
            continue
        print(f'    {reason:20s}: {count}')

    # ═══ 3. L2N safe pin analysis ═══
    print(f'\n{"=" * 65}')
    print(f' 3. L2N SAFE PIN ANALYSIS (M2 cluster)')
    print(f'{"=" * 65}')

    safe_pins, unsafe_pins = detect_l2n_safe_pins(gds_path, routing)
    print(f'\n  Safe (single-net M2 cluster):  {len(safe_pins)}')
    print(f'  Unsafe (mixed-net M2 cluster): {len(unsafe_pins)}')

    # ═══ 4. KLayout LVS cross-reference ═══
    substrate_merges = []
    if lvs_report:
        print(f'\n{"=" * 65}')
        print(f' 4. KLAYOUT LVS CROSS-REFERENCE')
        print(f'{"=" * 65}')

        summary = lvs_report.get('summary', {})
        print(f'\n  Devices matched: {summary.get("devices_matched", "?")}')
        print(f'  Nets matched:    {summary.get("nets_matched", "?")}')
        print(f'  Comma merges:    {summary.get("comma_merges", "?")}')
        print(f'  Wrong-bulk:      {summary.get("wrong_bulk_pmos", "?")}')

        substrate_merges = cross_reference_lvs(merge_pairs, lvs_report) or []

        # Reclassify: L2N merges NOT confirmed by KLayout = false positive
        confirmed = 0
        for mp in merge_pairs:
            if mp.get('klvs_confirmed'):
                confirmed += 1
            else:
                mp['category'] = 'l2n_only'  # demote to false positive
        unconfirmed = len(merge_pairs) - confirmed

        print(f'\n  L2N merges confirmed by KLayout LVS: {confirmed} (real)')
        print(f'  L2N merges NOT in KLayout LVS:       {unconfirmed} '
              f'(demoted to l2n_only)')

        # Group substrate merges by comma merge group
        klvs_raw = lvs_report.get('nets', {}).get('comma_merges', [])
        print(f'\n  KLayout LVS comma merge groups:')
        for merge_str in klvs_raw:
            nets = merge_str.split(',') if isinstance(merge_str, str) else merge_str
            n_metal = sum(1 for mp in merge_pairs
                          if mp.get('klvs_confirmed')
                          and {mp['net_a'], mp['net_b']} <= set(nets))
            tag = 'METAL' if n_metal > 0 else 'SUBSTRATE'
            preview = ','.join(nets[:6])
            if len(nets) > 6:
                preview += f'...+{len(nets) - 6}'
            print(f'    [{tag:9s}] {len(nets):2d} nets: {preview}')

    # ═══ 5. Categorized action plan ═══
    print(f'\n{"=" * 65}')
    print(f' 5. CATEGORIZED ACTION PLAN')
    print(f'{"=" * 65}')

    # Recount after reclassification
    all_categories = defaultdict(list)
    for mp in merge_pairs:
        all_categories[mp['category']].append(mp)
    for sm in substrate_merges:
        all_categories['substrate'].append(sm)

    actions = {
        'substrate': (
            'Fix NWell/diffusion connectivity — merge through substrate.',
            'Invisible to metal-only L2N. Check NWell island boundaries, '
            'tie cell placement, and substrate connectivity.'
        ),
        'same_device_dg': (
            'CONFIRMED metal merge: D/G of same MOSFET share metal.',
            'Bus strap or AP M1 bridges D and G. Check gap cutting and '
            'AP M1 pad placement near gate contacts.'
        ),
        'power_signal': (
            'CONFIRMED metal merge: signal touches GND/VDD metal.',
            'Check power drops, M3 vbars, bus strap M1 for unintended '
            'overlap with signal shapes.'
        ),
        'cross_device': (
            'CONFIRMED metal merge: different devices share metal.',
            'Check bus strap gaps between devices.'
        ),
        'via2_failure': (
            'Improve Via2 success rate.',
            f'L2N-safe pins can use expanded M3 search. '
            f'{len(safe_pins)} safe, {len(unsafe_pins)} unsafe.'
        ),
        'l2n_only': (
            'L2N false positive — no action needed.',
            'Normal MOSFET D/G proximity. Device extraction separates them.'
        ),
    }

    # Real issues first, false positives last
    priority = 0
    for cat in ['substrate', 'same_device_dg', 'power_signal',
                'cross_device', 'via2_failure', 'l2n_only']:
        items = all_categories.get(cat, [])
        if not items and cat != 'via2_failure':
            continue
        priority += 1
        action, detail = actions.get(cat, ('Unknown', ''))
        count = len(items) if cat != 'via2_failure' else via2_fail
        tag = ''
        if cat == 'l2n_only':
            tag = ' [no action]'
        elif cat in ('same_device_dg', 'power_signal', 'cross_device'):
            tag = ' [KLayout confirmed]'
        print(f'\n  P{priority}. [{cat}] — {count} issues{tag}')
        print(f'      {action}')
        print(f'      {detail}')

    # ═══ 6. Diff with previous run ═══
    if prev:
        print(f'\n{"=" * 65}')
        print(f' 6. DIFF vs PREVIOUS RUN')
        print(f'{"=" * 65}')

        prev_pairs = set()
        for mp in prev.get('merge_pairs', []):
            prev_pairs.add((mp['net_a'], mp['net_b']))
        curr_pairs = set()
        for mp in merge_pairs:
            curr_pairs.add((mp['net_a'], mp['net_b']))

        resolved = prev_pairs - curr_pairs
        new = curr_pairs - prev_pairs
        unchanged = prev_pairs & curr_pairs

        print(f'\n  Resolved:  {len(resolved)}')
        for a, b in sorted(resolved):
            print(f'    ✅ {a} ↔ {b}')
        print(f'  New:       {len(new)}')
        for a, b in sorted(new):
            print(f'    ❌ {a} ↔ {b}')
        print(f'  Unchanged: {len(unchanged)}')

        prev_via2 = prev.get('via2_ok', 0)
        print(f'\n  Via2: {prev_via2} → {via2_ok} '
              f'({"+" if via2_ok >= prev_via2 else ""}{via2_ok - prev_via2})')

        prev_matched = prev.get('devices_matched', 0)
        curr_matched = summary.get('devices_matched', 0) if lvs_report else '?'
        print(f'  Devices matched: {prev_matched} → {curr_matched}')

    # ═══ Save report ═══
    report = {
        'gds': gds_path,
        'merge_pairs': merge_pairs,
        'merge_by_category': dict(by_category),
        'substrate_merges': substrate_merges,
        'power_fragmentation': power_frag,
        'via2_ok': via2_ok,
        'via2_fail': via2_fail,
        'via2_reasons': dict(via2_reasons),
        'l2n_safe_pins': len(safe_pins),
        'l2n_unsafe_pins': len(unsafe_pins),
    }
    if lvs_report:
        report['devices_matched'] = summary.get('devices_matched', 0)
        report['comma_merges'] = summary.get('comma_merges', 0)
        report['wrong_bulk'] = summary.get('wrong_bulk_pmos', 0)

    if output_path:
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f'\n  Saved: {output_path}')

    return report


def main():
    parser = argparse.ArgumentParser(
        description='LVS diagnostic loop — integrated merge detection and tracking')
    parser.add_argument('--gds', required=True, help='GDS file')
    parser.add_argument('--routing', required=True, help='routing.json')
    parser.add_argument('--ties', required=True, help='ties.json')
    parser.add_argument('--placement', required=True, help='placement.json')
    parser.add_argument('--lvs-report', default=None, help='lvs_report.json')
    parser.add_argument('--output', default=None, help='Output JSON')
    parser.add_argument('--prev', default=None, help='Previous diagnostic JSON for diff')
    args = parser.parse_args()
    run_diagnostic(args.gds, args.routing, args.ties, args.placement,
                   args.lvs_report, args.output, args.prev)


if __name__ == '__main__':
    main()
