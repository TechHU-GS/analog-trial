#!/usr/bin/env python3
"""Geometric diagnostic: comprehensive DRC + LVS analysis using klayout.db.

Analyzes soilz.gds without running external tools. Uses Region operations
for DRC pre-checks and LayoutToNetlist for connectivity analysis.

Output: output/diagnostic_report.json + console summary

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.diagnose_geometric
"""

import json
import time
import klayout.db as db
from .pdk import (
    METAL1, METAL2, METAL3, METAL4,
    VIA1, VIA2, VIA3, CONT,
    NWELL, ACTIV, GATPOLY, PSD, NSD,
    M1_MIN_S, M2_MIN_S, M3_MIN_S, M4_MIN_S,
    M1_MIN_W, M2_MIN_W, M3_MIN_W, M4_MIN_W,
    M1_MIN_AREA, M2_MIN_AREA, M3_MIN_AREA, M4_MIN_AREA,
    VIA2_PAD_M3,
)
from .paths import ROUTING_JSON


def _bbox(poly):
    b = poly.bbox()
    return [b.left, b.bottom, b.right, b.top]


def _edge_pair_info(ep):
    """Extract edge pair info for DRC violations."""
    e1, e2 = ep.first, ep.second
    return {
        'p1': [e1.p1.x, e1.p1.y, e1.p2.x, e1.p2.y],
        'p2': [e2.p1.x, e2.p1.y, e2.p2.x, e2.p2.y],
    }


def diagnose(gds_path='output/soilz.gds'):
    t0 = time.time()
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    print(f'  Loaded {gds_path} in {time.time()-t0:.2f}s')

    # ── Extract all metal/via regions (merged) ──
    def region(lyr):
        return db.Region(top.begin_shapes_rec(layout.layer(*lyr))).merged()

    m1 = region(METAL1)
    m2 = region(METAL2)
    m3 = region(METAL3)
    m4 = region(METAL4)
    v1 = region(VIA1)
    v2 = region(VIA2)
    v3 = region(VIA3)
    nw = region(NWELL)
    print(f'  Regions extracted in {time.time()-t0:.2f}s')
    print(f'    M1={m1.count()} M2={m2.count()} M3={m3.count()} M4={m4.count()}')
    print(f'    V1={v1.count()} V2={v2.count()} V3={v3.count()}')

    report = {'gds': gds_path, 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}

    # ═══════════════════════════════════════════════════
    # 1. DRC GEOMETRIC ANALYSIS
    # ═══════════════════════════════════════════════════
    print('\n  === DRC Geometric Analysis ===')
    drc = {}

    # ── Min area checks ──
    for name, rgn, min_area in [
        ('M1.d', m1, M1_MIN_AREA),
        ('M2.d', m2, M2_MIN_AREA),
        ('M3.d', m3, M3_MIN_AREA),
        ('M4.d', m4, M4_MIN_AREA),
    ]:
        violations = []
        for poly in rgn.each():
            area = poly.area()  # in nm² (dbu=0.001)
            if area < min_area:
                bb = poly.bbox()
                w = bb.width()
                h = bb.height()
                # Compute fix: extend shorter dimension to meet min area
                if w <= h:
                    needed_w = (min_area + h - 1) // h
                    fix = {'axis': 'x', 'current': w, 'needed': needed_w,
                           'extend': needed_w - w}
                else:
                    needed_h = (min_area + w - 1) // w
                    fix = {'axis': 'y', 'current': h, 'needed': needed_h,
                           'extend': needed_h - h}
                violations.append({
                    'bbox': _bbox(poly), 'area': area,
                    'deficit': min_area - area, 'fix': fix
                })
        if violations:
            drc[name] = violations
            print(f'    {name}: {len(violations)} violations')

    # ── Spacing checks ──
    for name, rgn, min_s in [
        ('M1.b', m1, M1_MIN_S),
        ('M2.b', m2, M2_MIN_S),
        ('M3.b', m3, M3_MIN_S),
        ('M4.b', m4, M4_MIN_S),
    ]:
        edge_pairs = rgn.space_check(min_s)
        violations = []
        for ep in edge_pairs.each():
            info = _edge_pair_info(ep)
            d = ep.distance()
            info['distance'] = d
            info['deficit'] = min_s - d
            violations.append(info)
        if violations:
            drc[name] = violations
            print(f'    {name}: {len(violations)} spacing violations '
                  f'(min deficit={min(v["deficit"] for v in violations)}nm, '
                  f'max deficit={max(v["deficit"] for v in violations)}nm)')

    # ── Width checks ──
    for name, rgn, min_w in [
        ('M1.a', m1, M1_MIN_W),
        ('M2.a', m2, M2_MIN_W),
        ('M3.a', m3, M3_MIN_W),
        ('M4.a', m4, M4_MIN_W),
    ]:
        edge_pairs = rgn.width_check(min_w)
        violations = []
        for ep in edge_pairs.each():
            info = _edge_pair_info(ep)
            info['distance'] = ep.distance()
            violations.append(info)
        if violations:
            drc[name] = violations
            print(f'    {name}: {len(violations)} width violations')

    report['drc'] = {k: {'count': len(v), 'violations': v[:20],
                         'truncated': len(v) > 20}
                     for k, v in drc.items()}

    # ═══════════════════════════════════════════════════
    # 2. COMMA MERGE ANALYSIS
    # ═══════════════════════════════════════════════════
    print('\n  === Comma Merge Analysis ===')

    # Load routing data for net→pin mapping
    with open(ROUTING_JSON) as f:
        routing = json.load(f)

    ap_data = routing.get('access_points', {})

    # Build per-net M2 seed regions from APs
    net_m2_seeds = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        seeds = db.Region()
        for pin_key in route.get('pins', []):
            ap = ap_data.get(pin_key)
            if not ap:
                continue
            m2_pad = ap.get('via_pad', {}).get('m2')
            if m2_pad:
                seeds.insert(db.Box(*m2_pad))
        if not seeds.is_empty():
            net_m2_seeds[net_name] = seeds

    # Known merged pairs (from LVS)
    merge_pairs = [
        ('buf1', 'vco5'),
        ('da1', 'f_exc_b'),
        ('ns5', 'vco_out'),
    ]

    merges = []
    for net_a, net_b in merge_pairs:
        result = {'nets': [net_a, net_b], 'shorts': []}

        # Find same-net regions for each net via flooding
        seed_a = net_m2_seeds.get(net_a, db.Region())
        seed_b = net_m2_seeds.get(net_b, db.Region())

        if seed_a.is_empty() or seed_b.is_empty():
            result['status'] = 'seed_missing'
            merges.append(result)
            continue

        # Flood fill on M2 to find connected shapes
        m2_net_a = m2.interacting(seed_a)
        m2_net_b = m2.interacting(seed_b)

        # Check M2 overlap
        m2_overlap = m2_net_a & m2_net_b
        if not m2_overlap.is_empty():
            for poly in m2_overlap.each():
                result['shorts'].append({
                    'layer': 'M2', 'bbox': _bbox(poly),
                    'area': poly.area()
                })

        # Check M1 overlap (flood from M2 via Via1)
        m1_net_a = m1.interacting(v1.interacting(m2_net_a))
        m1_net_b = m1.interacting(v1.interacting(m2_net_b))
        m1_overlap = m1_net_a & m1_net_b
        if not m1_overlap.is_empty():
            for poly in m1_overlap.each():
                result['shorts'].append({
                    'layer': 'M1', 'bbox': _bbox(poly),
                    'area': poly.area()
                })

        # Check M3 overlap (flood from M2 via Via2)
        m3_net_a = m3.interacting(v2.interacting(m2_net_a))
        m3_net_b = m3.interacting(v2.interacting(m2_net_b))
        m3_overlap = m3_net_a & m3_net_b
        if not m3_overlap.is_empty():
            for poly in m3_overlap.each():
                result['shorts'].append({
                    'layer': 'M3', 'bbox': _bbox(poly),
                    'area': poly.area()
                })

        result['status'] = 'found' if result['shorts'] else 'no_direct_overlap'
        merges.append(result)

        if result['shorts']:
            for s in result['shorts']:
                print(f'    {net_a}↔{net_b}: {s["layer"]} overlap at {s["bbox"]}')
        else:
            print(f'    {net_a}↔{net_b}: no direct M1/M2/M3 overlap — '
                  f'may be indirect via Region merge')

    report['merges'] = merges

    # ═══════════════════════════════════════════════════
    # 3. NET FRAGMENTATION ANALYSIS (L2N)
    # ═══════════════════════════════════════════════════
    print('\n  === Net Fragmentation Analysis (L2N) ===')

    # Build L2N for BEOL connectivity
    t_l2n = time.time()
    dss = db.DeepShapeStore()
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top,
                                                        layout.layer(*METAL1)))

    # Register conductor layers
    m1_l = l2n.make_layer(layout.layer(*METAL1), "M1")
    m2_l = l2n.make_layer(layout.layer(*METAL2), "M2")
    m3_l = l2n.make_layer(layout.layer(*METAL3), "M3")
    m4_l = l2n.make_layer(layout.layer(*METAL4), "M4")

    # Register via layers
    v1_l = l2n.make_layer(layout.layer(*VIA1), "Via1")
    v2_l = l2n.make_layer(layout.layer(*VIA2), "Via2")
    v3_l = l2n.make_layer(layout.layer(*VIA3), "Via3")
    ct_l = l2n.make_layer(layout.layer(*CONT), "Cont")

    # Also need FEOL for device recognition (optional for BEOL-only)
    gp_l = l2n.make_layer(layout.layer(*GATPOLY), "GatPoly")

    # Intra-layer connectivity (shapes touching = same net)
    l2n.connect(m1_l)
    l2n.connect(m2_l)
    l2n.connect(m3_l)
    l2n.connect(m4_l)
    l2n.connect(gp_l)

    # Inter-layer connectivity (via connects adjacent metals)
    l2n.connect(gp_l, ct_l)
    l2n.connect(ct_l, m1_l)
    l2n.connect(m1_l, v1_l)
    l2n.connect(v1_l, m2_l)
    l2n.connect(m2_l, v2_l)
    l2n.connect(v2_l, m3_l)
    l2n.connect(m3_l, v3_l)
    l2n.connect(v3_l, m4_l)

    l2n.extract_netlist()
    print(f'    L2N extracted in {time.time()-t_l2n:.2f}s')

    # Probe each AP to find which L2N net it belongs to
    fragmentation = {}
    total_pins = 0
    fragmented_nets = 0

    for net_name, route in routing.get('signal_routes', {}).items():
        pins = route.get('pins', [])
        if not pins:
            continue

        clusters = {}  # net_id → [pin_keys]
        no_net_pins = []

        for pin_key in pins:
            ap = ap_data.get(pin_key)
            if not ap:
                no_net_pins.append(pin_key)
                continue

            px, py = ap['x'], ap['y']
            total_pins += 1

            # Probe on M1 (AP is at M1 level)
            net = l2n.probe_net(m1_l, db.DPoint(px / 1000.0, py / 1000.0))
            if net is None:
                # Try M2
                net = l2n.probe_net(m2_l, db.DPoint(px / 1000.0, py / 1000.0))

            if net is not None:
                nid = net.circuit_net().net().id() if hasattr(net, 'circuit_net') else id(net)
                clusters.setdefault(nid, []).append(pin_key)
            else:
                no_net_pins.append(pin_key)

        n_clusters = len(clusters)
        if n_clusters > 1 or no_net_pins:
            fragmented_nets += 1
            fragmentation[net_name] = {
                'total_pins': len(pins),
                'clusters': n_clusters,
                'cluster_sizes': [len(v) for v in clusters.values()],
                'no_net_pins': no_net_pins,
            }

    print(f'    Probed {total_pins} pins across {len(routing.get("signal_routes", {}))} nets')
    print(f'    Fragmented nets: {fragmented_nets}')

    report['fragmentation'] = {
        'total_nets': len(routing.get('signal_routes', {})),
        'total_pins': total_pins,
        'fragmented_nets': fragmented_nets,
        'details': fragmentation,
    }

    # ═══════════════════════════════════════════════════
    # 4. VIA2 COVERAGE ANALYSIS
    # ═══════════════════════════════════════════════════
    print('\n  === Via2 Coverage ===')

    # Count APs that have Via2 nearby
    via2_covered = 0
    via2_missing = 0
    via2_missing_list = []

    v2_expanded = v2.sized(200)  # 200nm search radius

    for net_name, route in routing.get('signal_routes', {}).items():
        for pin_key in route.get('pins', []):
            ap = ap_data.get(pin_key)
            if not ap:
                continue
            px, py = ap['x'], ap['y']
            probe = db.Region(db.Box(px - 50, py - 50, px + 50, py + 50))
            # Check if there's a Via2 within reach of this AP's M2 pad
            m2_pad = ap.get('via_pad', {}).get('m2')
            if m2_pad:
                pad_rgn = db.Region(db.Box(*m2_pad))
                if not (pad_rgn.interacting(v2_expanded)).is_empty():
                    via2_covered += 1
                else:
                    via2_missing += 1
                    via2_missing_list.append({
                        'pin': pin_key, 'net': net_name,
                        'x': px, 'y': py
                    })

    print(f'    Via2 covered: {via2_covered}, missing: {via2_missing}')

    report['via2_coverage'] = {
        'covered': via2_covered,
        'missing': via2_missing,
        'missing_pins': via2_missing_list[:50],
    }

    # ═══════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════
    elapsed = time.time() - t0
    print(f'\n  === Summary ({elapsed:.1f}s) ===')

    drc_total = sum(len(v) for v in drc.values())
    drc_fixable = sum(len(v) for k, v in drc.items() if k.endswith('.d'))
    print(f'    DRC geometric: {drc_total} total')
    for k in sorted(drc, key=lambda x: -len(drc[x])):
        fixable = ' [fixable: min-area]' if k.endswith('.d') else ''
        print(f'      {k}: {len(drc[k])}{fixable}')
    print(f'    Comma merges: {len([m for m in merges if m["shorts"]])}')
    print(f'    Fragmented nets: {fragmented_nets}')
    print(f'    Via2 missing: {via2_missing}')

    report['summary'] = {
        'drc_total': drc_total,
        'drc_fixable_area': drc_fixable,
        'comma_merges': len([m for m in merges if m['shorts']]),
        'fragmented_nets': fragmented_nets,
        'via2_missing': via2_missing,
        'elapsed_seconds': round(elapsed, 1),
    }

    with open('output/diagnostic_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f'\n  Written: output/diagnostic_report.json')

    return report


if __name__ == '__main__':
    diagnose()
