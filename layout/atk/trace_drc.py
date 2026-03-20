#!/usr/bin/env python3
"""DRC violation shape provenance tracer.

For each DRC violation, identifies which assembly code path produced
the offending M1 shapes by matching GDS shape geometry against known
fingerprints (size, position relative to device).

Usage:
    python3 -m atk.trace_drc \
        --diag output/diagnostic_report.json \
        --gds output/soilz.gds \
        --placement placement.json \
        --routing output/routing.json \
        [--rule M1.b] [--output output/trace_report.json]
"""

import argparse
import json
import math
import os
from collections import Counter, defaultdict


def classify_m1_shape(box_nm, dev_pos_nm, ap_data, routing_data):
    """Classify an M1 shape by its likely assembly code origin.

    box_nm: (left, bottom, right, top) in nm
    dev_pos_nm: dict of device_name -> (x1, y1, x2, y2) in nm
    ap_data: access_points from routing.json
    routing_data: routing segments

    Returns: (source_type, confidence, detail)
    """
    left, bot, right, top = box_nm
    w = right - left
    h = top - bot
    cx = (left + right) // 2
    cy = (bot + top) // 2
    area = w * h

    # 1. Via1 pad: ~310x310nm square
    if 290 <= w <= 340 and 290 <= h <= 340:
        return 'via1_pad', 'high', f'{w}x{h}nm'

    # 2. Gate contact: small square at gate position, typically ~260-310nm
    if 240 <= w <= 320 and 240 <= h <= 320 and w != h:
        return 'gate_contact', 'medium', f'{w}x{h}nm'

    # 3. Bus strap: wide horizontal bar (w >> h, or w > 2um)
    if w > 2000 and h < 500:
        return 'bus_strap', 'high', f'{w}x{h}nm horizontal'
    if h > 2000 and w < 500:
        return 'bus_strap', 'high', f'{w}x{h}nm vertical'

    # 4. Tie cell: ~660x660nm or similar
    if 600 <= w <= 800 and 600 <= h <= 800:
        return 'tie_cell', 'medium', f'{w}x{h}nm'

    # 5. AP M1 pad: check against routing.json via_pad.m1
    if ap_data:
        for key, ap in ap_data.items():
            vp = ap.get('via_pad', {})
            m1 = vp.get('m1')
            if m1:
                # m1 is [x1,y1,x2,y2] in nm
                if (abs(left - m1[0]) < 50 and abs(bot - m1[1]) < 50 and
                        abs(right - m1[2]) < 50 and abs(top - m1[3]) < 50):
                    pw = m1[2] - m1[0]
                    ph = m1[3] - m1[1]
                    return 'ap_m1_pad', 'high', f'{key} {pw}x{ph}nm'

    # 6. AP M1 stub: check against routing.json m1_stub
    if ap_data:
        for key, ap in ap_data.items():
            stub = ap.get('m1_stub')
            if stub:
                if (abs(left - stub[0]) < 50 and abs(bot - stub[1]) < 50 and
                        abs(right - stub[2]) < 50 and abs(top - stub[3]) < 50):
                    sw = stub[2] - stub[0]
                    sh = stub[3] - stub[1]
                    return 'ap_m1_stub', 'high', f'{key} {sw}x{sh}nm'

    # 7. Routing M1 wire: ~300nm wide
    if (280 <= w <= 320 and h > 400) or (280 <= h <= 320 and w > 400):
        return 'routing_m1', 'medium', f'{w}x{h}nm'

    # 8. Gap fill: small rectangle, typically < 500nm in both dimensions
    if w < 500 and h < 500 and area < 150000:
        return 'gap_fill', 'low', f'{w}x{h}nm'

    # 9. Large pad (merged pad+stub or extended)
    if w > 400 or h > 400:
        # Check if overlaps known AP position
        if ap_data:
            for key, ap in ap_data.items():
                ax, ay = ap.get('x', 0), ap.get('y', 0)
                if left <= ax <= right and bot <= ay <= top:
                    return 'ap_m1_merged', 'medium', f'near {key} {w}x{h}nm'

        return 'ext_pad_unknown', 'low', f'{w}x{h}nm'

    return 'unknown', 'low', f'{w}x{h}nm at ({cx},{cy})'


def trace(diag_path, gds_path, placement_path, routing_path,
          rule_filter=None, output_path=None):
    """Trace DRC violations to assembly code origins."""
    try:
        import klayout.db as db
    except ImportError:
        print('ERROR: klayout.db not available')
        return

    # Load data
    with open(diag_path) as f:
        diag = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)
    with open(routing_path) as f:
        routing = json.load(f)

    violations = diag.get('violations', [])
    if rule_filter:
        violations = [v for v in violations if v['rule'] == rule_filter]

    ap_data = routing.get('access_points', {})

    # Load GDS
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    li_m1 = layout.find_layer(8, 0)  # Metal1

    # Build device position map (nm)
    dev_pos_nm = {}
    for name, info in placement.get('instances', {}).items():
        x = int(info['x_um'] * 1000)
        y = int(info['y_um'] * 1000)
        w = int(info.get('w_um', 0) * 1000)
        h = int(info.get('h_um', 0) * 1000)
        dev_pos_nm[name] = (x, y, x + w, y + h)

    # Trace each violation
    results = []
    source_counts = Counter()
    source_by_collision = defaultdict(Counter)

    for vi, v in enumerate(violations):
        p1 = v.get('p1')
        if not p1:
            results.append({'violation': vi, 'sources': ['no_coords']})
            continue

        # Convert violation coordinates to nm
        vx_nm = int(p1[0] * 1000)
        vy_nm = int(p1[1] * 1000)

        # Search M1 shapes near violation
        margin = 500  # 500nm search radius
        search = db.Box(vx_nm - margin, vy_nm - margin,
                        vx_nm + margin, vy_nm + margin)

        shapes_found = []
        for s in top.shapes(li_m1).each_overlapping(search):
            b = s.bbox()
            box = (b.left, b.bottom, b.right, b.top)
            source, conf, detail = classify_m1_shape(
                box, dev_pos_nm, ap_data, routing)
            shapes_found.append({
                'box': box,
                'source': source,
                'confidence': conf,
                'detail': detail,
            })

        # Determine primary sources for this violation
        sources = [s['source'] for s in shapes_found]
        collision = v.get('collision', '?')
        gap = v.get('gap', -1)

        for src in set(sources):
            source_counts[src] += 1
            source_by_collision[collision][src] += 1

        results.append({
            'violation': vi,
            'rule': v.get('rule'),
            'collision': collision,
            'gap': gap,
            'ap1': v.get('ap1', '?'),
            'ap2': v.get('ap2', '?'),
            'coord': [p1[0], p1[1]],
            'shapes': shapes_found,
            'primary_sources': list(set(sources)),
        })

    # Report
    total = len(violations)
    print(f'\n{"="*65}')
    print(f' DRC Shape Provenance Trace')
    print(f' {total} violations ({rule_filter or "all rules"})')
    print(f'{"="*65}')

    print(f'\n  Shape source frequency:')
    for src, cnt in source_counts.most_common():
        pct = 100 * cnt / total if total else 0
        print(f'    {src:20s}: {cnt:4d} ({pct:4.0f}%)')

    print(f'\n  Source × Collision type:')
    collisions = sorted(set(v.get('collision', '?') for v in violations))
    print(f'    {"Source":20s}', end='')
    for c in collisions:
        print(f' {c[:7]:>7s}', end='')
    print()
    for src, _ in source_counts.most_common():
        print(f'    {src:20s}', end='')
        for c in collisions:
            n = source_by_collision[c].get(src, 0)
            print(f' {n if n else ".":>7}', end='')
        print()

    # Source pair analysis: which pairs of sources create violations
    print(f'\n  Source pair (the two shapes causing each violation):')
    pair_counts = Counter()
    for r in results:
        srcs = sorted(set(r['primary_sources']))
        if len(srcs) >= 2:
            for i in range(len(srcs)):
                for j in range(i+1, len(srcs)):
                    pair_counts[(srcs[i], srcs[j])] += 1
        elif len(srcs) == 1:
            pair_counts[(srcs[0], srcs[0])] += 1
    for (s1, s2), cnt in pair_counts.most_common(10):
        print(f'    {s1:20s} ↔ {s2:20s}: {cnt}')

    # Gap distribution per source
    print(f'\n  Gap distribution per source:')
    source_gaps = defaultdict(list)
    for r in results:
        gap = r.get('gap', -1)
        if gap >= 0:
            for src in set(r['primary_sources']):
                source_gaps[src].append(gap)
    for src, gaps in sorted(source_gaps.items(),
                            key=lambda x: -len(x[1])):
        if len(gaps) < 3:
            continue
        gaps.sort()
        med = gaps[len(gaps)//2]
        print(f'    {src:20s}: n={len(gaps):3d}  '
              f'min={gaps[0]:3d} med={med:3d} max={gaps[-1]:3d}nm')

    # Save
    if output_path:
        report = {
            'total': total,
            'rule': rule_filter,
            'source_counts': dict(source_counts),
            'source_by_collision': {k: dict(v)
                                    for k, v in source_by_collision.items()},
            'pair_counts': {f'{s1}↔{s2}': c
                           for (s1, s2), c in pair_counts.most_common()},
            'violations': results,
        }
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'\n  Saved: {output_path}')


def main():
    parser = argparse.ArgumentParser(
        description='DRC violation shape provenance tracer')
    parser.add_argument('--diag', required=True)
    parser.add_argument('--gds', required=True)
    parser.add_argument('--placement', required=True)
    parser.add_argument('--routing', required=True)
    parser.add_argument('--rule', default=None,
                        help='Filter by DRC rule (e.g. M1.b)')
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    trace(args.diag, args.gds, args.placement, args.routing,
          args.rule, args.output)


if __name__ == '__main__':
    main()
