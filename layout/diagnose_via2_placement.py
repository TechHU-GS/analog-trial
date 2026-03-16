#!/usr/bin/env python3
"""Diagnose Via2 placement failures for gate APs with M3 conflicts.

For each AP that needs Via2 but has M3 conflict at the AP center and
no valid fallback vertex, scans nearby positions for viable Via2 placement.

Usage:
    cd layout && python3 diagnose_via2_placement.py
"""
import os
import json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Layer encoding (maze router)
M1_LYR, M2_LYR, M3_LYR, M4_LYR = 0, 1, 2, 3

# PDK constants
M3_MIN_W = 200
M3_MIN_S = 210
VIA2_SZ = 190
VIA2_PAD_M3 = 380  # M3 pad around Via2
VIA3_SZ = 190
VIA3_PAD = 380
M2_MIN_W = 200
M2_MIN_S = 210
M1_SIG_W = 300
_VIA2_M2_ENDCAP = 145
_wire_hw = M1_SIG_W // 2

with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing['access_points']
sroutes = routing['signal_routes']
pre_routes = routing.get('pre_routes', {})

# Build set of pins already connected via via_stack
via_stack_pins = set()
for net_name, pr in pre_routes.items():
    for seg in pr.get('segments', []):
        if seg[4] == -2:  # via2
            for pin_key in pr.get('pins', []):
                ap = aps.get(pin_key)
                if ap and abs(ap['x'] - seg[0]) < 200 and abs(ap['y'] - seg[1]) < 200:
                    via_stack_pins.add(pin_key)

# Collect ALL M3 shapes: power + signal
m3_shapes = []  # (x1, y1, x2, y2, net_name)

# Power M3 from vbars
for vbar in routing.get('power_vbars', []):
    x = vbar['x']
    hw = vbar['width'] // 2
    y1 = vbar['y1']
    y2 = vbar['y2']
    net = vbar.get('net', 'power')
    m3_shapes.append((x - hw, y1, x + hw, y2, net))

# Power M3 rails
for rail in routing.get('power_rails', []):
    if rail.get('layer', 1) == 2:  # M3
        m3_shapes.append((rail['x1'], rail['y1'], rail['x2'], rail['y2'],
                          rail.get('net', 'power')))

# Signal M3 from routes
for net_name, route in sroutes.items():
    for seg in route['segments']:
        if seg[4] == M3_LYR:
            x1, y1, x2, y2 = seg[:4]
            hw = M3_MIN_W // 2
            if x1 == x2:  # vertical
                m3_shapes.append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2), net_name))
            else:  # horizontal
                m3_shapes.append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw, net_name))

# Signal M3 from pre_routes
for net_name, route in pre_routes.items():
    for seg in route.get('segments', []):
        if seg[4] == M3_LYR:
            x1, y1, x2, y2 = seg[:4]
            hw = M3_MIN_W // 2
            if x1 == x2:
                m3_shapes.append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2), net_name))
            else:
                m3_shapes.append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw, net_name))

# Via2 M3 pads
hp_via2_m3 = VIA2_PAD_M3 // 2
for net_name, route in sroutes.items():
    for seg in route['segments']:
        if seg[4] == -2:  # via2
            m3_shapes.append((seg[0] - hp_via2_m3, seg[1] - hp_via2_m3,
                              seg[0] + hp_via2_m3, seg[1] + hp_via2_m3, net_name))

print(f"Total M3 shapes indexed: {len(m3_shapes)}")


def m3_rect_conflict(x1, y1, x2, y2, my_net):
    """Check if M3 rect conflicts with any cross-net M3 shape."""
    conflicts = []
    for sx1, sy1, sx2, sy2, snet in m3_shapes:
        if snet == my_net:
            continue
        # Check spacing (M3_MIN_S = 210nm)
        gap_x = max(0, max(sx1 - x2, x1 - sx2))
        gap_y = max(0, max(sy1 - y2, y1 - sy2))
        gap = max(gap_x, gap_y)
        if gap < M3_MIN_S:
            conflicts.append((sx1, sy1, sx2, sy2, snet, gap))
    return conflicts


def m2_rect_conflict(x1, y1, x2, y2, my_net):
    """Check if M2 bridge conflicts with cross-net M2 shapes."""
    m2_shapes = []
    # Signal M2
    for net_name, route in sroutes.items():
        for seg in route['segments']:
            if seg[4] == M2_LYR:
                sx1, sy1, sx2, sy2 = seg[:4]
                hw = M2_MIN_W // 2
                if sx1 == sx2:
                    m2_shapes.append((sx1 - hw, min(sy1, sy2), sx1 + hw, max(sy1, sy2), net_name))
                else:
                    m2_shapes.append((min(sx1, sx2), sy1 - hw, max(sx1, sx2), sy1 + hw, net_name))
    conflicts = []
    for sx1, sy1, sx2, sy2, snet in m2_shapes:
        if snet == my_net:
            continue
        gap_x = max(0, max(sx1 - x2, x1 - sx2))
        gap_y = max(0, max(sy1 - y2, y1 - sy2))
        gap = max(gap_x, gap_y)
        if gap < M2_MIN_S:
            conflicts.append((sx1, sy1, sx2, sy2, snet, gap))
    return conflicts


# ── Analyze each skipped AP ─────────────────────────────────────────

skipped_aps = []
total_checked = 0
total_has_low = 0
total_via2_ok = 0
total_fallback_ok = 0
total_skipped = 0

for net_name, route in sroutes.items():
    segs = route.get('segments', [])
    if not segs:
        continue
    pins = route.get('pins', [])
    for pin_key in pins:
        if pin_key in via_stack_pins:
            continue
        ap = aps.get(pin_key)
        if not ap or not ap.get('via_pad') or 'm2' not in ap['via_pad']:
            continue

        total_checked += 1
        ap_x, ap_y = ap['x'], ap['y']

        # Check has_low (same logic as assemble_gds)
        has_low = False
        _m1r = ap['via_pad'].get('m1', [0, 0, 0, 0])
        _m2r = ap['via_pad'].get('m2', [0, 0, 0, 0])
        for seg in segs:
            lyr = seg[4]
            if lyr == 0:  # M1
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m1r[0] and px - _wire_hw < _m1r[2]
                            and py + _wire_hw > _m1r[1] and py - _wire_hw < _m1r[3]):
                        has_low = True
                        break
            elif lyr == 1:  # M2
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                            and py + _wire_hw > _m2r[1] and py - _wire_hw < _m2r[3]):
                        has_low = True
                        break
            elif lyr == -1:  # via1
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if abs(px - ap_x) <= 200 and abs(py - ap_y) <= 200:
                        has_low = True
                        break
            if has_low:
                break
        if has_low:
            total_has_low += 1
            continue

        # Find nearest M3/M4/Via3 vertex
        best_dist = float('inf')
        best_pos = None
        for seg in segs:
            lyr = seg[4]
            if lyr not in (M3_LYR, M4_LYR, -3):
                continue
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                dist = abs(px - ap_x) + abs(py - ap_y)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = (px, py)

        if not best_pos or best_dist > 500:
            continue

        rx, ry = best_pos

        # Compute M3 bbox for AP-center Via2
        _m3_hw = M3_MIN_W // 2
        _endcap = 50
        _via_hw = VIA2_SZ // 2
        if abs(ap_x - rx) > 10 or abs(ap_y - ry) > 10:
            _mbx1 = min(ap_x, rx) - _m3_hw
            _mby1 = min(ap_y, ry) - _m3_hw
            _mbx2 = max(ap_x, rx) + _m3_hw
            _mby2 = max(ap_y, ry) + _m3_hw
        else:
            _mbx1 = ap_x - _m3_hw
            _mby1 = ap_y - _m3_hw
            _mbx2 = ap_x + _m3_hw
            _mby2 = ap_y + _m3_hw
        _mbx1 = min(_mbx1, ap_x - _via_hw - _endcap)
        _mby1 = min(_mby1, ap_y - _via_hw - _endcap)
        _mbx2 = max(_mbx2, ap_x + _via_hw + _endcap)
        _mby2 = max(_mby2, ap_y + _via_hw + _endcap)

        m3_conflicts = m3_rect_conflict(_mbx1, _mby1, _mbx2, _mby2, net_name)
        if not m3_conflicts:
            total_via2_ok += 1
            continue

        # Has M3 conflict — try fallback
        _m3_seg = None
        for seg in segs:
            if seg[4] == M3_LYR:
                if ((seg[0] == rx and seg[1] == ry)
                        or (seg[2] == rx and seg[3] == ry)):
                    _m3_seg = seg
                    break

        _fb_ok = False
        if _m3_seg:
            _sx1, _sy1, _sx2, _sy2 = _m3_seg[:4]
            if _sx1 == rx and _sy1 == ry:
                _ox, _oy = _sx2, _sy2
            else:
                _ox, _oy = _sx1, _sy1
            if _sx1 == _sx2:
                _wlen = abs(_oy - ry)
                if _wlen >= 2 * _VIA2_M2_ENDCAP:
                    _fb_ok = True
            else:
                _wlen = abs(_ox - rx)
                if _wlen >= 2 * _VIA2_M2_ENDCAP:
                    _fb_ok = True

        if not _m3_seg:
            # Case B
            hp = VIA2_PAD_M3 // 2
            if not m3_rect_conflict(rx - hp, ry - hp, rx + hp, ry + hp, net_name):
                _fb_ok = True

        if _fb_ok:
            total_fallback_ok += 1
            continue

        # SKIPPED — collect details
        total_skipped += 1
        skipped_aps.append({
            'pin': pin_key,
            'net': net_name,
            'ap': (ap_x, ap_y),
            'vertex': (rx, ry),
            'vertex_dist': best_dist,
            'conflicts': m3_conflicts,
            'has_m3_seg': _m3_seg is not None,
            'segs': segs,
        })

print(f"\nAP Summary:")
print(f"  Total checked: {total_checked}")
print(f"  has_low (skip): {total_has_low}")
print(f"  Via2 at AP center OK: {total_via2_ok}")
print(f"  Fallback OK: {total_fallback_ok}")
print(f"  SKIPPED (no Via2): {total_skipped}")

# ── Analyze skipped cases ───────────────────────────────────────────

print(f"\n{'='*75}")
print(f"SKIPPED VIA2 ANALYSIS ({total_skipped} cases)")
print(f"{'='*75}\n")

# For each skipped case, scan nearby positions for viable Via2 placement
scan_range = 700  # nm from AP center
scan_step = 50  # nm grid
hp = VIA2_PAD_M3 // 2  # M3 pad half-size

viable_found = 0
for info in skipped_aps[:20]:  # first 20 for detail
    pin = info['pin']
    net = info['net']
    ax, ay = info['ap']
    vx, vy = info['vertex']

    # Find conflict details
    conflict_nets = set(c[4] for c in info['conflicts'])
    conflict_gaps = [c[5] for c in info['conflicts']]

    print(f"  {pin:20s} net={net:15s} AP=({ax},{ay}) vertex=({vx},{vy})"
          f" dist={info['vertex_dist']}")
    print(f"    Conflicts with: {', '.join(sorted(conflict_nets))}"
          f" (gaps: {sorted(conflict_gaps)[:3]})")

    # Find all same-net M3/M4/Via3 segments near AP
    same_net_upper = []
    for seg in info['segs']:
        lyr = seg[4]
        if lyr in (M3_LYR, M4_LYR, -2, -3):
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                d = abs(px - ax) + abs(py - ay)
                if d < 1000:
                    same_net_upper.append((px, py, lyr, d))

    # Scan nearby positions
    best_scan = None
    best_scan_dist = float('inf')
    for dx in range(-scan_range, scan_range + 1, scan_step):
        for dy in range(-scan_range, scan_range + 1, scan_step):
            cx = ax + dx
            cy = ay + dy
            # Must be near a same-net M3 wire (within wire half-width)
            near_m3 = False
            for seg in info['segs']:
                if seg[4] != M3_LYR:
                    continue
                sx1, sy1, sx2, sy2 = seg[:4]
                if sx1 == sx2:  # vertical
                    if abs(cx - sx1) <= M3_MIN_W // 2 and min(sy1, sy2) <= cy <= max(sy1, sy2):
                        near_m3 = True
                        break
                else:  # horizontal
                    if abs(cy - sy1) <= M3_MIN_W // 2 and min(sx1, sx2) <= cx <= max(sx1, sx2):
                        near_m3 = True
                        break
            if not near_m3:
                continue

            # Check M3 conflict for Via2 pad at this position
            conflicts = m3_rect_conflict(cx - hp, cy - hp, cx + hp, cy + hp, net)
            if conflicts:
                continue

            dist = abs(dx) + abs(dy)
            if dist < best_scan_dist:
                best_scan_dist = dist
                best_scan = (cx, cy)

    if best_scan:
        print(f"    ✓ VIABLE Via2 at ({best_scan[0]},{best_scan[1]})"
              f" dist={best_scan_dist}nm from AP")
        viable_found += 1
    else:
        # Try without M3 wire constraint (Case B: Via3+M3 pad)
        best_scan2 = None
        best_scan_dist2 = float('inf')
        for dx in range(-scan_range, scan_range + 1, scan_step):
            for dy in range(-scan_range, scan_range + 1, scan_step):
                cx = ax + dx
                cy = ay + dy
                conflicts = m3_rect_conflict(cx - hp, cy - hp, cx + hp, cy + hp, net)
                if conflicts:
                    continue
                # Must be near a same-net M4/Via3 vertex
                near_upper = False
                for seg in info['segs']:
                    if seg[4] in (M4_LYR, -3):
                        for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                            if abs(cx - px) <= 200 and abs(cy - py) <= 200:
                                near_upper = True
                                break
                    if near_upper:
                        break
                if not near_upper:
                    continue
                dist = abs(dx) + abs(dy)
                if dist < best_scan_dist2:
                    best_scan_dist2 = dist
                    best_scan2 = (cx, cy)

        if best_scan2:
            print(f"    ✓ VIABLE Via2+Via3 at ({best_scan2[0]},{best_scan2[1]})"
                  f" dist={best_scan_dist2}nm (Case B)")
            viable_found += 1
        else:
            print(f"    ✗ NO viable position within {scan_range}nm")
    print()

print(f"\n{'='*75}")
print(f"SUMMARY: {viable_found}/{min(20, total_skipped)} scanned have viable positions")
print(f"{'='*75}")
