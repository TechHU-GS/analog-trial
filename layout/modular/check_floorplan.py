#!/usr/bin/env python3
"""Floorplan constraint checker for SoilZ v1.

Checks:
  1. Module overlaps
  2. Tile boundary (202.08 × 627.48 um, 1x2)
  3. Power stripe avoidance (x < 9.2)
  4. ua[] pin proximity
  5. Signal chain wirelength (weighted)
  6. Isolation zone spacing
  7. Routing channel width between adjacent modules
  8. Rotated modules detection
  9. Area utilization

Usage:
    python3 modular/check_floorplan.py [coords.json]
    # or paste coords inline
"""

import json
import sys
import os

TILE_W = 202.08
TILE_H = 627.48  # 1x2 tile
POWER_X = 9.2
UA_PINS = {'ua[0]': (191, 5), 'ua[1]': (167, 5)}

# Signal chain connections: (mod1, mod2, weight, description)
SIGNAL_CHAINS = [
    # SD loop
    ('chopper', 'rin', 3, 'chop_out'),
    ('rin', 'ota', 3, 'sum_n'),
    ('ota', 'comp', 3, 'ota_out'),
    ('comp', 'hbridge', 3, 'comp_outp/n'),
    ('hbridge', 'dac_sw', 3, 'lat_q/qb'),
    ('dac_sw', 'rdac', 2, 'dac_out'),
    # SD feedback
    ('ota', 'c_fb', 3, 'ota_out/sum_n feedback'),
    ('c_fb', 'comp', 2, 'ota_out'),
    ('c_fb', 'rin', 2, 'sum_n'),
    ('c_fb', 'rdac', 2, 'sum_n'),
    # Excitation
    ('nol', 'hbridge_drive', 2, 'phi_p/phi_n'),
    ('hbridge_drive', 'sw', 2, 'exc_out'),
    ('sw', 'chopper', 1, 'exc→chop'),
    ('nol', 'chopper', 2, 'f_exc/f_exc_b'),
    # VCO chain
    ('vco_5stage', 'vco_buffer', 2, 'vco5'),
    ('vco_buffer', 'inv_iso', 2, 'vco_out'),
    ('inv_iso', 'digital', 2, 'vco_buf/b'),
    # Bias distribution
    ('ptat_core', 'bias_mn', 3, 'nmos_bias/pmos_bias'),
    ('bias_mn', 'cbyp_n', 2, 'nmos_bias bypass'),
    ('bias_mn', 'cbyp_p', 2, 'pmos_bias bypass'),
    ('ptat_core', 'rptat', 2, 'net_rptat'),
    ('ptat_core', 'rout', 1, 'vptat'),
    ('ptat_core', 'bias_cascode', 1, 'net_c1'),
    ('bias_cascode', 'sw', 2, 'src1/2/3'),
    ('bias_mn', 'vco_5stage', 1, 'nmos_bias'),
    ('bias_mn', 'ota', 1, 'pmos_bias'),
]

# ua pin assignments
UA_ASSIGNMENTS = [
    ('vco_buffer', 'ua[0]', 5, 'VCO output'),
    ('rout', 'ua[1]', 3, 'VPTAT output'),
]

# Isolation requirements: (mod1, mod2, min_gap_um, reason)
ISOLATION = [
    ('vco_5stage', 'digital', 3.0, 'VCO noise sensitivity'),
    ('ptat_core', 'nol', 2.0, 'PTAT precision'),
    ('ptat_core', 'hbridge_drive', 2.0, 'PTAT precision'),
    ('bias_mn', 'nol', 2.0, 'bias precision'),
]

# Original (unrotated) module sizes
ORIG_SIZES = {
    'vco_5stage': (108.8, 14.4), 'vco_buffer': (7.2, 12.7), 'inv_iso': (3.8, 9.8),
    'digital': (80.0, 30.0), 'chopper': (9.5, 6.4), 'rin': (3.8, 5.3),
    'ota': (23.0, 18.0), 'c_fb': (27.2, 27.2), 'comp': (9.3, 25.2),
    'hbridge': (7.7, 9.2), 'dac_sw': (8.2, 6.4), 'rdac': (2.3, 3.8),
    'nol': (30.1, 11.8), 'hbridge_drive': (12.9, 4.1), 'sw': (15.6, 6.1),
    'bias_cascode': (55.0, 16.6), 'ptat_core': (14.5, 18.0), 'bias_mn': (8.5, 3.0),
    'cbyp_n': (6.2, 6.2), 'cbyp_p': (6.2, 6.2), 'rptat': (10.6, 135.5), 'rout': (1.6, 101.3),
}

# Minimum routing channel between any adjacent modules
MIN_CHANNEL = 2.0  # um


def center(m):
    return m['x'] + m['w'] / 2, m['y'] + m['h'] / 2


def edge_gap(a, b):
    dx = max(0, max(a['x'], b['x']) - min(a['x'] + a['w'], b['x'] + b['w']))
    dy = max(0, max(a['y'], b['y']) - min(a['y'] + a['h'], b['y'] + b['h']))
    return (dx ** 2 + dy ** 2) ** 0.5


def center_dist(a, b):
    cx1, cy1 = center(a)
    cx2, cy2 = center(b)
    return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5


def check(coords):
    errors = []
    warnings = []
    info = []
    names = list(coords.keys())

    # === 1. Overlaps ===
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = coords[names[i]], coords[names[j]]
            ox = max(0, min(a['x'] + a['w'], b['x'] + b['w']) - max(a['x'], b['x']))
            oy = max(0, min(a['y'] + a['h'], b['y'] + b['h']) - max(a['y'], b['y']))
            if ox > 0.1 and oy > 0.1:
                errors.append(f'OVERLAP: {names[i]} ↔ {names[j]}: {ox:.1f}×{oy:.1f}um')

    # === 2. Tile boundary ===
    for name, m in coords.items():
        if m['x'] + m['w'] > TILE_W:
            errors.append(f'BOUNDARY: {name} right={m["x"]+m["w"]:.1f} > tile {TILE_W}')
        if m['y'] + m['h'] > TILE_H:
            errors.append(f'BOUNDARY: {name} top={m["y"]+m["h"]:.1f} > tile {TILE_H}')
        if m['x'] < 0 or m['y'] < 0:
            errors.append(f'BOUNDARY: {name} at ({m["x"]:.1f},{m["y"]:.1f}) — negative coords')

    # === 3. Power stripe ===
    for name, m in coords.items():
        if m['x'] < POWER_X:
            warnings.append(f'POWER: {name} at x={m["x"]:.1f} — inside power stripe (x<{POWER_X})')

    # === 4. ua[] proximity ===
    for mod, ua_name, weight, desc in UA_ASSIGNMENTS:
        if mod not in coords:
            continue
        ux, uy = UA_PINS[ua_name]
        m = coords[mod]
        cx, cy = center(m)
        dist = ((cx - ux) ** 2 + (cy - uy) ** 2) ** 0.5
        if dist > 30:
            warnings.append(f'UA_PIN: {mod} center ({cx:.0f},{cy:.0f}) → {ua_name} ({ux},{uy}): {dist:.0f}um — {desc}')
        else:
            info.append(f'ua_pin: {mod} → {ua_name}: {dist:.0f}um ✓')

    # === 5. Signal chains ===
    total_wl = 0
    chain_issues = []
    for n1, n2, weight, desc in SIGNAL_CHAINS:
        if n1 not in coords or n2 not in coords:
            continue
        d = center_dist(coords[n1], coords[n2])
        total_wl += d * weight
        if d > 50:
            warnings.append(f'WIRELENGTH: {n1}→{n2}: {d:.0f}um (net: {desc})')
        elif d > 30:
            info.append(f'wirelength: {n1}→{n2}: {d:.0f}um (net: {desc})')

    # === 6. Isolation ===
    for n1, n2, min_gap, reason in ISOLATION:
        if n1 not in coords or n2 not in coords:
            continue
        gap = edge_gap(coords[n1], coords[n2])
        if gap < min_gap:
            errors.append(f'ISOLATION: {n1}↔{n2}: {gap:.1f}um < {min_gap}um ({reason})')
        else:
            info.append(f'isolation: {n1}↔{n2}: {gap:.1f}um ≥ {min_gap} ✓')

    # === 7. Routing channels ===
    # Check gaps between modules that share signal nets
    checked = set()
    for n1, n2, weight, desc in SIGNAL_CHAINS:
        if n1 not in coords or n2 not in coords:
            continue
        pair = tuple(sorted([n1, n2]))
        if pair in checked:
            continue
        checked.add(pair)
        gap = edge_gap(coords[n1], coords[n2])
        if gap < MIN_CHANNEL and gap < 50:  # only check nearby modules
            warnings.append(f'CHANNEL: {n1}↔{n2}: {gap:.1f}um < {MIN_CHANNEL}um routing channel')

    # === 8. Rotated modules ===
    rotated = []
    for name, m in coords.items():
        if name in ORIG_SIZES:
            ow, oh = ORIG_SIZES[name]
            if abs(m['w'] - oh) < 0.5 and abs(m['h'] - ow) < 0.5:
                rotated.append(f'{name}: {ow}×{oh} → {m["w"]}×{m["h"]}')

    # === 9. Area utilization ===
    total_area = sum(m['w'] * m['h'] for m in coords.values())
    tile_area = TILE_W * TILE_H
    max_y = max(m['y'] + m['h'] for m in coords.values())

    # === Report ===
    print('=' * 60)
    print('  SoilZ v1 Floorplan Check')
    print(f'  Tile: {TILE_W} × {TILE_H}um (1x2)')
    print('=' * 60)

    if errors:
        print(f'\n❌ ERRORS ({len(errors)}):')
        for e in errors:
            print(f'  {e}')

    if warnings:
        print(f'\n⚠️  WARNINGS ({len(warnings)}):')
        for w in sorted(warnings):
            print(f'  {w}')

    if info:
        print(f'\n✓  INFO ({len(info)}):')
        for i in sorted(info):
            print(f'  {i}')

    if rotated:
        print(f'\n🔄 ROTATED ({len(rotated)}):')
        for r in rotated:
            print(f'  {r}')

    print(f'\n📊 STATS:')
    print(f'  Modules: {len(coords)}')
    print(f'  Total wirelength (weighted): {total_wl:.0f}')
    print(f'  Module area: {total_area:.0f}um² / {tile_area:.0f}um² = {total_area/tile_area*100:.1f}%')
    print(f'  Analog extent: y = {min(m["y"] for m in coords.values()):.1f} to {max_y:.1f}um')
    print(f'  Remaining height: {TILE_H - max_y:.0f}um (for digital expansion)')
    print(f'\n  Result: {"❌ FAIL" if errors else "⚠️  PASS with warnings" if warnings else "✅ CLEAN"}')
    print(f'  Errors={len(errors)} Warnings={len(warnings)}')
    return len(errors)


if __name__ == '__main__':
    # Try loading from file or stdin
    data = None
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        # Try default path
        default = os.path.join(os.path.dirname(__file__), 'output', 'floorplan_coords.json')
        if os.path.exists(default):
            with open(default) as f:
                data = json.load(f)

    if data is None:
        print('Usage: python3 check_floorplan.py <coords.json>')
        sys.exit(1)

    # Remove non-module keys
    coords = {k: v for k, v in data.items() if k != 'tile' and isinstance(v, dict) and 'x' in v}
    check(coords)
