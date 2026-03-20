#!/usr/bin/env python3
"""Systematic DRC/LVS spatial and structural analysis.

Reads diagnostic_report.json + placement.json + lvs_report.json,
produces a global picture: where are violations, why, and how they
correlate with LVS failures.

Usage:
    python3 -m atk.analyze_drc \
        --diag output/diagnostic_report.json \
        --placement placement.json \
        --lvs output/lvs_report.json \
        [--output output/analysis_report.json] \
        [--grid 10] [--cluster-radius 5]
"""

import argparse
import json
import math
from collections import Counter, defaultdict


# Functional block classification
BLOCK_PATTERNS = {
    'TFF_1I': ['T1I_'],
    'TFF_1Q': ['T1Q_'],
    'TFF_2I': ['T2I_'],
    'TFF_2Q': ['T2Q_'],
    'TFF_3':  ['T3_'],
    'TFF_4I': ['T4I_'],
    'TFF_4Q': ['T4Q_'],
    'MUX_fi': ['MXfi_'],
    'MUX_fq': ['MXfq_'],
    'MUX_iq': ['MXiq_'],
    'NOL':    ['M_da', 'M_db', 'M_na', 'M_nb', 'M_ia', 'M_ib', 'M_inv0'],
    'VCO':    ['Mpb', 'Mpu', 'Mpd', 'Mnb'],
    'COMP':   ['Mc_'],
    'BUF':    ['BUF_', 'INV_'],
    'BIAS':   ['PM', 'MN', 'Rptat', 'Rout', 'Rin', 'Rdac'],
    'OTA':    ['Mp_load', 'Min_', 'Mbias', 'Mtail'],
    'HBRIDGE': ['MS1', 'MS2', 'MS3', 'MS4'],
    'CHOPPER': ['Mchop'],
    'SR':     ['Mn1a', 'Mn1b', 'Mn2a', 'Mn2b', 'Mp1a', 'Mp1b', 'Mp2a', 'Mp2b'],
    'SW':     ['SW1', 'SW2', 'SW3'],
    'DAC':    ['Mdac_'],
    'CAP':    ['Cbyp', 'C_fb'],
}


def classify_block(device_name):
    """Classify a device into a functional block."""
    if not device_name or device_name == '?':
        return 'unknown'
    for block, prefixes in BLOCK_PATTERNS.items():
        for prefix in prefixes:
            if device_name.startswith(prefix):
                return block
    return 'other'


def extract_device(ap_key):
    """Extract device name from AP key like 'T1I_m3.G' → 'T1I_m3'."""
    if not ap_key or ap_key == '?':
        return '?'
    dot = ap_key.rfind('.')
    if dot > 0:
        return ap_key[:dot]
    return ap_key


# ── DBSCAN clustering (no scipy dependency) ──

def _dbscan(points, eps, min_pts=1):
    """Simple DBSCAN. points = [(x, y, index), ...]. Returns cluster labels."""
    n = len(points)
    labels = [-1] * n  # -1 = unvisited
    cluster_id = 0

    def region_query(idx):
        px, py = points[idx][0], points[idx][1]
        neighbors = []
        for j in range(n):
            if j == idx:
                continue
            dx = points[j][0] - px
            dy = points[j][1] - py
            if dx * dx + dy * dy <= eps * eps:
                neighbors.append(j)
        return neighbors

    for i in range(n):
        if labels[i] != -1:
            continue
        neighbors = region_query(i)
        if len(neighbors) < min_pts - 1:
            labels[i] = -2  # noise
            continue
        labels[i] = cluster_id
        queue = list(neighbors)
        while queue:
            j = queue.pop(0)
            if labels[j] == -2:
                labels[j] = cluster_id
            if labels[j] != -1:
                continue
            labels[j] = cluster_id
            j_neighbors = region_query(j)
            if len(j_neighbors) >= min_pts - 1:
                queue.extend(j_neighbors)
        cluster_id += 1

    return labels


def _analyze_gds_footprint(gds_path, instances, dev_pos):
    """Measure actual M1 shape extents vs device body from GDS."""
    try:
        import klayout.db as db
    except ImportError:
        print('  klayout not available, skipping GDS analysis')
        return

    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    li_m1 = layout.find_layer(8, 0)  # Metal1
    if li_m1 < 0:
        print('  M1 layer not found in GDS')
        return

    # For each device type, measure M1 extent beyond device body
    type_extents = defaultdict(list)  # type → [(dev_name, extend_um), ...]

    for name, info in instances.items():
        if name not in dev_pos:
            continue
        cx, cy, w, h = dev_pos[name]
        dev_type = info.get('type', '?')

        # Device body bounds (nm, GDS uses nm with dbu)
        dbu = layout.dbu  # usually 0.001 (1nm)
        dx1_nm = int((cx - w / 2) / dbu)
        dy1_nm = int((cy - h / 2) / dbu)
        dx2_nm = int((cx + w / 2) / dbu)
        dy2_nm = int((cy + h / 2) / dbu)

        # Search M1 shapes overlapping device body + margin
        margin = int(3.0 / dbu)  # 3um search margin
        search = db.Box(dx1_nm - margin, dy1_nm - margin,
                        dx2_nm + margin, dy2_nm + margin)

        max_extend = 0
        for s in top.shapes(li_m1).each_overlapping(search):
            b = s.bbox()
            # Check if shape overlaps device body
            if b.right < dx1_nm or b.left > dx2_nm:
                continue
            if b.top < dy1_nm or b.bottom > dy2_nm:
                continue
            # Measure extension beyond device body
            ext_left = max(0, dx1_nm - b.left) * dbu
            ext_right = max(0, b.right - dx2_nm) * dbu
            ext_bot = max(0, dy1_nm - b.bottom) * dbu
            ext_top = max(0, b.top - dy2_nm) * dbu
            ext = max(ext_left, ext_right, ext_bot, ext_top)
            max_extend = max(max_extend, ext)

        if max_extend > 0:
            type_extents[dev_type].append((name, max_extend))

    # Report by device type
    print(f'\n  M1 extension beyond device body (um), by PCell type:')
    print(f'  {"Type":<16s} {"Count":>5s} {"Min":>6s} {"Med":>6s} '
          f'{"Max":>6s} {"Mean":>6s}')
    for dtype in sorted(type_extents.keys(),
                        key=lambda t: -max(e for _, e in type_extents[t])):
        exts = sorted([e for _, e in type_extents[dtype]])
        n = len(exts)
        print(f'  {dtype:<16s} {n:5d} {exts[0]:6.2f} '
              f'{exts[n//2]:6.2f} {exts[-1]:6.2f} '
              f'{sum(exts)/n:6.2f}')

    # Top individual devices
    all_devs = [(name, ext, info.get('type', '?'))
                for dtype, devs in type_extents.items()
                for name, ext in devs
                for info in [instances.get(name, {})]
                if ext > 0.5]
    all_devs.sort(key=lambda x: -x[1])
    if all_devs:
        print(f'\n  Top 15 devices with largest M1 extension:')
        print(f'  {"Device":<20s} {"Type":<16s} {"Extend(um)":>10s}')
        for name, ext, dtype in all_devs[:15]:
            print(f'  {name:<20s} {dtype:<16s} {ext:10.2f}')


def analyze(diag_path, placement_path, lvs_path, grid_size=10,
            cluster_radius=5.0, output_path=None, gds_path=None):
    """Run full analysis."""
    # ── Load data ──
    with open(diag_path) as f:
        diag = json.load(f)
    violations = diag.get('violations', [])

    with open(placement_path) as f:
        placement = json.load(f)
    instances = placement.get('instances', {})
    bb = placement.get('bounding_box', {})

    lvs = None
    if lvs_path:
        try:
            with open(lvs_path) as f:
                lvs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            print(f'  Warning: could not load LVS report from {lvs_path}')

    print(f'\n{"="*65}')
    print(f' DRC/LVS Systematic Analysis')
    print(f' {len(violations)} violations, {len(instances)} devices')
    print(f' Chip: {bb.get("w_um", "?")} x {bb.get("h_um", "?")} um')
    print(f'{"="*65}')

    # Build device position map (um)
    dev_pos = {}  # name → (cx, cy, w, h)
    for name, info in instances.items():
        x = info.get('x_um', 0)
        y = info.get('y_um', 0)
        w = info.get('w_um', 0)
        h = info.get('h_um', 0)
        dev_pos[name] = (x + w / 2, y + h / 2, w, h)

    # Collect violation coordinates (um) with metadata
    viol_pts = []  # (x_um, y_um, violation_dict, index)
    for i, v in enumerate(violations):
        p1 = v.get('p1')
        p2 = v.get('p2')
        if p1:
            viol_pts.append((p1[0], p1[1], v, i))
        elif p2:
            viol_pts.append((p2[0], p2[1], v, i))

    # ══════════════════════════════════════════════
    # A. SPATIAL CLUSTERING (DBSCAN)
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' A. SPATIAL CLUSTERING (DBSCAN, eps={cluster_radius}um)')
    print(f'{"="*65}')

    if viol_pts:
        cluster_labels = _dbscan(
            [(p[0], p[1], p[3]) for p in viol_pts],
            eps=cluster_radius, min_pts=2)

        # Group by cluster
        clusters = defaultdict(list)  # cluster_id → [violation indices]
        noise = 0
        for idx, label in enumerate(cluster_labels):
            if label < 0:
                noise += 1
            else:
                clusters[label].append(idx)

        print(f'\n  {len(clusters)} clusters found, {noise} noise points')

        # Analyze each cluster
        cluster_stats = []
        for cid in sorted(clusters.keys()):
            members = clusters[cid]
            xs = [viol_pts[i][0] for i in members]
            ys = [viol_pts[i][1] for i in members]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            radius = max(math.sqrt((x - cx)**2 + (y - cy)**2)
                         for x, y in zip(xs, ys)) if len(members) > 1 else 0

            rules = Counter(viol_pts[i][2]['rule'] for i in members)
            collisions = Counter(viol_pts[i][2].get('collision', '?')
                                 for i in members)
            devices = Counter()
            for i in members:
                v = viol_pts[i][2]
                for ap in [v.get('ap1', '?'), v.get('ap2', '?')]:
                    dev = extract_device(ap)
                    if dev != '?':
                        devices[dev] += 1

            # Find nearest placement devices to cluster center
            nearby_devs = []
            for dname, (dx, dy, dw, dh) in dev_pos.items():
                dist = math.sqrt((dx - cx)**2 + (dy - cy)**2)
                if dist < cluster_radius + 5:
                    nearby_devs.append((dname, dist))
            nearby_devs.sort(key=lambda x: x[1])

            cluster_stats.append({
                'id': cid,
                'count': len(members),
                'center': (round(cx, 1), round(cy, 1)),
                'radius': round(radius, 1),
                'rules': dict(rules.most_common(5)),
                'collisions': dict(collisions.most_common(5)),
                'top_devices': [d for d, _ in devices.most_common(5)],
                'nearby_placement': [n for n, _ in nearby_devs[:5]],
                'block': classify_block(
                    devices.most_common(1)[0][0] if devices else '?'),
            })

        # Sort by count
        cluster_stats.sort(key=lambda c: -c['count'])

        print(f'\n  Top clusters:')
        print(f'  {"#":>3s} {"Count":>5s} {"Center (um)":>16s} {"R":>5s}  '
              f'{"Block":<10s} Top rules              Top devices')
        for c in cluster_stats[:15]:
            rules_str = ', '.join(f'{r}({n})' for r, n in
                                  list(c['rules'].items())[:3])
            devs_str = ', '.join(c['top_devices'][:3])
            print(f'  {c["id"]:3d} {c["count"]:5d} '
                  f'({c["center"][0]:6.1f},{c["center"][1]:6.1f}) '
                  f'{c["radius"]:5.1f}  '
                  f'{c["block"]:<10s} {rules_str:<22s} {devs_str}')

        # Cluster coverage
        clustered = sum(c['count'] for c in cluster_stats)
        print(f'\n  Clustered: {clustered}/{len(viol_pts)} '
              f'({100*clustered/len(viol_pts):.0f}%), '
              f'noise: {noise} ({100*noise/len(viol_pts):.0f}%)')
        top5_count = sum(c['count'] for c in cluster_stats[:5])
        print(f'  Top 5 clusters: {top5_count}/{len(viol_pts)} '
              f'({100*top5_count/len(viol_pts):.0f}%)')

    # ══════════════════════════════════════════════
    # B. GRID HEAT MAP
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' B. GRID HEAT MAP ({grid_size}x{grid_size})')
    print(f'{"="*65}')

    if viol_pts and bb:
        x_min = 0
        y_min = 0
        x_max = bb.get('w_um', 200)
        y_max = bb.get('h_um', 260)
        cell_w = (x_max - x_min) / grid_size
        cell_h = (y_max - y_min) / grid_size

        grid = defaultdict(int)
        for cx, cy, v, _ in viol_pts:
            gx = min(int((cx - x_min) / cell_w), grid_size - 1)
            gy = min(int((cy - y_min) / cell_h), grid_size - 1)
            grid[(gx, gy)] += 1

        # ASCII heat map
        max_val = max(grid.values()) if grid else 1
        chars = ' ·▪▫░▒▓█'
        print(f'\n  Y↑')
        for gy in range(grid_size - 1, -1, -1):
            row = '  '
            for gx in range(grid_size):
                val = grid.get((gx, gy), 0)
                ci = min(len(chars) - 1, int(val / max_val * (len(chars) - 1)))
                row += chars[ci]
            y_lo = y_min + gy * cell_h
            y_hi = y_lo + cell_h
            row += f'  {y_lo:5.0f}-{y_hi:5.0f}'
            print(row)
        print(f'  {"X→":>{grid_size + 2}}')
        print(f'  Scale: " "=0  "·"=1-{max_val//7}  '
              f'"█"={max_val}')

    # ══════════════════════════════════════════════
    # C. DEVICE-LEVEL RANKING
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' C. DEVICE-LEVEL RANKING')
    print(f'{"="*65}')

    dev_violations = Counter()
    dev_rules = defaultdict(Counter)
    for v in violations:
        for ap_key in [v.get('ap1', '?'), v.get('ap2', '?')]:
            dev = extract_device(ap_key)
            if dev != '?':
                dev_violations[dev] += 1
                dev_rules[dev][v['rule']] += 1

    print(f'\n  Top 20 devices:')
    print(f'  {"Device":<20s} {"Count":>5s} {"Block":<10s}  Top rules')
    for dev, cnt in dev_violations.most_common(20):
        top_rules = dev_rules[dev].most_common(3)
        rules_str = ', '.join(f'{r}({c})' for r, c in top_rules)
        print(f'  {dev:<20s} {cnt:5d} {classify_block(dev):<10s}  {rules_str}')

    # ══════════════════════════════════════════════
    # D. FUNCTIONAL BLOCK SUMMARY
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' D. FUNCTIONAL BLOCK SUMMARY')
    print(f'{"="*65}')

    block_violations = Counter()
    block_rules = defaultdict(Counter)
    block_collisions = defaultdict(Counter)
    for v in violations:
        blocks_seen = set()
        for ap_key in [v.get('ap1', '?'), v.get('ap2', '?')]:
            dev = extract_device(ap_key)
            block = classify_block(dev)
            blocks_seen.add(block)
        block = 'unknown'
        for b in blocks_seen:
            if b != 'unknown':
                block = b
                break
        block_violations[block] += 1
        block_rules[block][v['rule']] += 1
        block_collisions[block][v.get('collision', '?')] += 1

    print(f'\n  {"Block":<12s} {"Count":>5s} {"% ":>5s}  '
          f'Top rules                    Collisions')
    for block, cnt in block_violations.most_common():
        pct = 100 * cnt / len(violations)
        top_rules = block_rules[block].most_common(3)
        rules_str = ', '.join(f'{r}({c})' for r, c in top_rules)
        top_coll = block_collisions[block].most_common(3)
        coll_str = ', '.join(f'{c}({n})' for c, n in top_coll)
        print(f'  {block:<12s} {cnt:5d} {pct:4.0f}%  '
              f'{rules_str:<28s} {coll_str}')

    tff_blocks = [b for b in block_violations if b.startswith('TFF')]
    tff_total = sum(block_violations[b] for b in tff_blocks)
    print(f'\n  TFF subtotal: {tff_total}/{len(violations)} '
          f'({100*tff_total/len(violations):.0f}%)')

    # ══════════════════════════════════════════════
    # E. RULE × COLLISION MATRIX
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' E. RULE × COLLISION TYPE MATRIX')
    print(f'{"="*65}')

    collision_types = ['notch', 'same_net', 'cross_device', 'cross_net',
                       'self_ap', 'polygon', 'unknown', 'no_geometry']
    print(f'\n  {"Rule":<10s}', end='')
    for ct in collision_types:
        print(f' {ct[:7]:>7s}', end='')
    print(f' {"Total":>6s}')

    for rule, cnt in sorted(diag['by_rule'].items(), key=lambda x: -x[1]):
        if cnt < 3:
            continue
        row = Counter(v.get('collision', 'unknown')
                      for v in violations if v['rule'] == rule)
        print(f'  {rule:<10s}', end='')
        for ct in collision_types:
            n = row.get(ct, 0)
            print(f' {n if n else "·":>7}', end='')
        print(f' {cnt:>6d}')

    # ══════════════════════════════════════════════
    # F. LVS CORRELATION
    # ══════════════════════════════════════════════
    if lvs:
        print(f'\n{"="*65}')
        print(f' F. LVS CORRELATION')
        print(f'{"="*65}')

        matched = lvs.get('matched_devices', lvs.get('devices_matched', 0))
        merges = lvs.get('comma_merges', [])
        wb = lvs.get('wrong_bulk_pmos', lvs.get('wrong_bulk', 0))

        print(f'\n  Matched: {matched}, Wrong-bulk: {wb}, '
              f'Merges: {len(merges)}')

        if merges:
            print(f'\n  Comma merges:')
            for m in merges:
                nets = m.split(',') if isinstance(m, str) else m
                print(f'    [{len(nets)} nets] '
                      f'{",".join(nets[:6])}'
                      f'{"..." if len(nets) > 6 else ""}')

    # ══════════════════════════════════════════════
    # G. GAP DISTRIBUTION PER RULE
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' G. GAP DISTRIBUTION PER RULE')
    print(f'{"="*65}')

    for rule, cnt in sorted(diag['by_rule'].items(), key=lambda x: -x[1]):
        if cnt < 5:
            continue
        gaps = [v.get('gap', -1) for v in violations
                if v['rule'] == rule and v.get('gap', -1) >= 0]
        if not gaps:
            continue
        gaps.sort()
        print(f'\n  {rule} ({cnt} violations, {len(gaps)} with gap data):')
        # Histogram
        buckets = Counter()
        for g in gaps:
            bucket = (g // 20) * 20  # 20nm buckets
            buckets[bucket] += 1
        for bucket in sorted(buckets.keys()):
            bar = '█' * min(40, buckets[bucket])
            print(f'    {bucket:4d}-{bucket+19:4d}nm: '
                  f'{buckets[bucket]:3d} {bar}')

    # ══════════════════════════════════════════════
    # H. DEVICE-PAIR CONFLICT GRAPH
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' H. DEVICE-PAIR CONFLICTS')
    print(f'{"="*65}')

    pair_counts = Counter()
    pair_rules = defaultdict(Counter)
    for v in violations:
        d1 = extract_device(v.get('ap1', '?'))
        d2 = extract_device(v.get('ap2', '?'))
        if d1 == '?' or d2 == '?':
            continue
        pair = tuple(sorted([d1, d2]))
        pair_counts[pair] += 1
        pair_rules[pair][v['rule']] += 1

    # Self-violations (same device) vs cross-device
    self_viols = sum(c for (a, b), c in pair_counts.items() if a == b)
    cross_viols = sum(c for (a, b), c in pair_counts.items() if a != b)
    print(f'\n  Self (within device): {self_viols}')
    print(f'  Cross (between devices): {cross_viols}')

    # Top cross-device pairs with spacing
    print(f'\n  Top 15 cross-device conflict pairs:')
    print(f'  {"Device A":<18s} {"Device B":<18s} {"Count":>5s} '
          f'{"Dist(um)":>8s}  Top rules')
    for (d1, d2), cnt in pair_counts.most_common(30):
        if d1 == d2:
            continue
        # Compute center-to-center distance
        dist_str = '?'
        if d1 in dev_pos and d2 in dev_pos:
            cx1, cy1 = dev_pos[d1][0], dev_pos[d1][1]
            cx2, cy2 = dev_pos[d2][0], dev_pos[d2][1]
            dist = math.sqrt((cx1 - cx2)**2 + (cy1 - cy2)**2)
            dist_str = f'{dist:.1f}'
        rules_str = ', '.join(f'{r}({n})'
                              for r, n in pair_rules[(d1, d2)].most_common(3))
        print(f'  {d1:<18s} {d2:<18s} {cnt:5d} {dist_str:>8s}  {rules_str}')
        if sum(1 for (a, b), _ in pair_counts.most_common(30)
               if a != b and (a, b) == (d1, d2) or (b, a) == (d1, d2)) >= 15:
            break

    # Top self-violation devices
    print(f'\n  Top 10 self-violation devices (within same device):')
    print(f'  {"Device":<20s} {"Count":>5s}  Top rules')
    rank = 0
    for (d1, d2), cnt in pair_counts.most_common():
        if d1 != d2:
            continue
        rules_str = ', '.join(f'{r}({n})'
                              for r, n in pair_rules[(d1, d2)].most_common(3))
        print(f'  {d1:<20s} {cnt:5d}  {rules_str}')
        rank += 1
        if rank >= 10:
            break

    # ══════════════════════════════════════════════
    # I. VIOLATION POSITION vs DEVICE BODY
    # ══════════════════════════════════════════════
    print(f'\n{"="*65}')
    print(f' I. VIOLATION POSITION vs DEVICE BODY')
    print(f'{"="*65}')

    # For each violation with known AP, check if violation coordinate
    # is inside, at edge, or outside the device body
    inside = 0
    edge = 0     # within 1um of device edge
    outside = 0
    outside_dist = []  # distances outside device body
    no_dev = 0

    for v in violations:
        p1 = v.get('p1')
        if not p1:
            continue
        vx, vy = p1[0], p1[1]  # violation position in um

        dev = extract_device(v.get('ap1', '?'))
        if dev == '?' or dev not in dev_pos:
            no_dev += 1
            continue

        cx, cy, w, h = dev_pos[dev]
        # Device body bounds (um)
        dx1 = cx - w / 2
        dy1 = cy - h / 2
        dx2 = cx + w / 2
        dy2 = cy + h / 2

        # Distance outside device body (negative = inside)
        dist_x = max(dx1 - vx, vx - dx2, 0)
        dist_y = max(dy1 - vy, vy - dy2, 0)
        dist_out = math.sqrt(dist_x**2 + dist_y**2)

        if dist_out < 0.01:  # inside
            inside += 1
        elif dist_out < 1.0:  # edge (within 1um)
            edge += 1
            outside_dist.append(dist_out)
        else:
            outside += 1
            outside_dist.append(dist_out)

    total_classified = inside + edge + outside
    if total_classified > 0:
        print(f'\n  Inside device body:  {inside:4d} '
              f'({100*inside/total_classified:.0f}%)')
        print(f'  Edge (<1um outside): {edge:4d} '
              f'({100*edge/total_classified:.0f}%)')
        print(f'  Outside (>1um):      {outside:4d} '
              f'({100*outside/total_classified:.0f}%)')
        print(f'  No device match:     {no_dev:4d}')

        if outside_dist:
            outside_dist.sort()
            print(f'\n  Distance outside device body (um):')
            print(f'    Min: {outside_dist[0]:.2f}  '
                  f'Median: {outside_dist[len(outside_dist)//2]:.2f}  '
                  f'Max: {outside_dist[-1]:.2f}')

            # Histogram
            buckets = Counter()
            for d in outside_dist:
                b = int(d)  # 1um buckets
                buckets[b] += 1
            print(f'\n  Distance distribution:')
            for b in sorted(buckets.keys()):
                bar = '█' * min(40, buckets[b])
                print(f'    {b:2d}-{b+1:2d}um: {buckets[b]:3d} {bar}')

    # ══════════════════════════════════════════════
    # J. GDS M1 FOOTPRINT ANALYSIS (optional)
    # ══════════════════════════════════════════════
    if gds_path:
        print(f'\n{"="*65}')
        print(f' J. GDS M1 FOOTPRINT vs DEVICE BODY')
        print(f'{"="*65}')
        _analyze_gds_footprint(gds_path, instances, dev_pos)

    # ── Save JSON report ──
    if output_path:
        report = {
            'total': len(violations),
            'by_rule': diag['by_rule'],
            'by_block': dict(block_violations),
            'tff_total': tff_total,
            'tff_pct': round(100 * tff_total / len(violations), 1),
            'top_devices': dev_violations.most_common(30),
        }
        if viol_pts and 'cluster_stats' in dir():
            report['clusters'] = cluster_stats[:15]
        if lvs:
            report['lvs'] = {
                'matched': matched,
                'wrong_bulk': wb,
                'merges': len(merges),
            }
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'\n  Report saved: {output_path}')


def main():
    parser = argparse.ArgumentParser(
        description='Systematic DRC/LVS spatial and structural analysis')
    parser.add_argument('--diag', required=True,
                        help='diagnostic_report.json from diagnose_drc')
    parser.add_argument('--placement', required=True,
                        help='placement.json')
    parser.add_argument('--lvs', default=None,
                        help='lvs_report.json (optional)')
    parser.add_argument('--output', default=None,
                        help='Output JSON report path')
    parser.add_argument('--grid', type=int, default=10,
                        help='Spatial grid size (default 10)')
    parser.add_argument('--cluster-radius', type=float, default=5.0,
                        help='DBSCAN cluster radius in um (default 5)')
    parser.add_argument('--gds', default=None,
                        help='GDS file for M1 footprint analysis (optional)')
    args = parser.parse_args()
    analyze(args.diag, args.placement, args.lvs, args.grid,
            args.cluster_radius, args.output, args.gds)


if __name__ == '__main__':
    main()
