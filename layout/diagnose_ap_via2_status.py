#!/usr/bin/env python3
"""Replay _add_missing_ap_via2 logic for gate pins only, reporting per-pin status.

For each gate pin AP, determines:
  1. has_low? (router already placed M1/M2/Via1 reaching the AP)
  2. If not has_low: what did _add_missing_ap_via2 do?
     - Normal (Via2 at AP center)
     - Fallback (Via2 at shifted position)
     - Scan (Via2 on M4 wire)
     - SKIPPED (all paths failed — THIS IS THE PROBLEM)

Usage:
    cd layout && python3 diagnose_ap_via2_status.py
"""
import os, json
from collections import Counter, defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Constants matching assemble_gds.py ──────────────────────────────
M1_LYR, M2_LYR, M3_LYR, M4_LYR = 0, 1, 2, 3
M1_SIG_W = 300
M3_MIN_W = 200
M3_MIN_S = 210
VIA2_SZ = 190
VIA2_PAD_M3 = 380
VIA3_SZ = 190
VIA3_PAD = 380
_VIA2_M2_ENDCAP = 145
_wire_hw = M1_SIG_W // 2

# ── Load data ───────────────────────────────────────────────────────
with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing.get('access_points', {})
sroutes = routing.get('signal_routes', {})

# Via stack pins (power drops)
via_stack_pins = set()
for drop in routing.get('power', {}).get('drops', []):
    if drop['type'] == 'via_stack':
        via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

# Build M3 obstacle list (same as assemble_gds)
m3_obs = []
for net_name, route in sroutes.items():
    for seg in route.get('segments', []):
        lyr = seg[4]
        if lyr == M3_LYR:
            x1, y1, x2, y2 = seg[:4]
            hw = M3_MIN_W // 2
            if x1 == x2:
                m3_obs.append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2), net_name))
            else:
                m3_obs.append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw, net_name))
        elif lyr == -3:
            hp3 = VIA3_PAD // 2
            m3_obs.append((seg[0] - hp3, seg[1] - hp3, seg[0] + hp3, seg[1] + hp3, net_name))
        elif lyr == -2:
            hp3 = VIA2_PAD_M3 // 2
            m3_obs.append((seg[0] - hp3, seg[1] - hp3, seg[0] + hp3, seg[1] + hp3, net_name))

for rail_id, rail in routing.get('power', {}).get('rails', {}).items():
    rnet = rail.get('net', rail_id)
    hw = rail['width'] // 2
    m3_obs.append((rail['x1'], rail['y'] - hw, rail['x2'], rail['y'] + hw, rnet))
for drop in routing.get('power', {}).get('drops', []):
    _vb = drop.get('m3_vbar')
    if _vb:
        hw = M3_MIN_W // 2
        m3_obs.append((_vb[0] - hw, min(_vb[1], _vb[3]), _vb[0] + hw, max(_vb[1], _vb[3]), drop['net']))


def _m3_rect_conflict(rx1, ry1, rx2, ry2, net):
    s = M3_MIN_S
    for ox1, oy1, ox2, oy2, onet in m3_obs:
        if onet == net:
            continue
        if rx2 + s > ox1 and rx1 - s < ox2 and ry2 + s > oy1 and ry1 - s < oy2:
            return True
    return False


hp_via2_m3 = VIA2_PAD_M3 // 2
hp_via3 = VIA3_PAD // 2

# ── Process gate pins ───────────────────────────────────────────────
results = []  # (pin_key, net, status, detail)

for net_name, route in sroutes.items():
    segs = route.get('segments', [])
    if not segs:
        continue
    pins = route.get('pins', [])

    for pin_key in pins:
        if '.G' not in pin_key:
            continue
        if pin_key in via_stack_pins:
            continue
        ap = aps.get(pin_key)
        if not ap or not ap.get('via_pad') or 'm2' not in ap['via_pad']:
            results.append((pin_key, net_name, 'NO_VIA_PAD', ''))
            continue

        ap_x, ap_y = ap['x'], ap['y']
        _m1r = ap['via_pad'].get('m1', [0, 0, 0, 0])
        _m2r = ap['via_pad'].get('m2', [0, 0, 0, 0])

        # ── Check has_low (same logic as assemble_gds) ──────────────
        has_low = False
        low_layer = None
        for seg in segs:
            lyr = seg[4]
            if lyr == M1_LYR:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m1r[0] and px - _wire_hw < _m1r[2]
                            and py + _wire_hw > _m1r[1] and py - _wire_hw < _m1r[3]):
                        has_low = True
                        low_layer = 'M1'
                        break
            elif lyr == M2_LYR:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                            and py + _wire_hw > _m2r[1] and py - _wire_hw < _m2r[3]):
                        has_low = True
                        low_layer = 'M2'
                        break
            elif lyr == -1:  # via1
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if abs(px - ap_x) <= 200 and abs(py - ap_y) <= 200:
                        has_low = True
                        low_layer = 'Via1'
                        break
            if has_low:
                break

        if has_low:
            results.append((pin_key, net_name, 'HAS_LOW', f'via {low_layer}'))
            continue

        # ── Find nearest M3/M4/Via3 vertex ──────────────────────────
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
            results.append((pin_key, net_name, 'TOO_FAR',
                            f'nearest upper={best_dist:.0f}nm'))
            continue

        rx, ry = best_pos

        # ── M3 bbox conflict check (normal path) ───────────────────
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

        if not _m3_rect_conflict(_mbx1, _mby1, _mbx2, _mby2, net_name):
            # Normal path: Via2 at AP center
            # Also check if Via3 needed (no M3 at vertex)
            has_m3_at_route = False
            for seg in segs:
                lyr = seg[4]
                if lyr in (M3_LYR, -3):
                    for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                        if px == rx and py == ry:
                            has_m3_at_route = True
                            break
                if has_m3_at_route:
                    break
            need_via3 = not has_m3_at_route
            if need_via3:
                if _m3_rect_conflict(rx - hp_via3, ry - hp_via3,
                                     rx + hp_via3, ry + hp_via3, net_name):
                    # Via3 M3 pad conflicts — this becomes a skip
                    results.append((pin_key, net_name, 'SKIP_VIA3_CONFLICT',
                                    f'vertex=({rx},{ry})'))
                    continue
            results.append((pin_key, net_name, 'NORMAL',
                            f'vertex=({rx},{ry}) via3={"yes" if need_via3 else "no"}'))
            continue

        # ── Fallback path ───────────────────────────────────────────
        _fb_ok = False
        _m3_seg = None
        for seg in segs:
            if seg[4] == M3_LYR:
                if ((seg[0] == rx and seg[1] == ry) or
                        (seg[2] == rx and seg[3] == ry)):
                    _m3_seg = seg
                    break

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
        else:
            # Case B: M4/Via3 vertex
            if not _m3_rect_conflict(rx - hp_via2_m3, ry - hp_via2_m3,
                                     rx + hp_via2_m3, ry + hp_via2_m3, net_name):
                _fb_ok = True

        if _fb_ok:
            case = 'A' if _m3_seg else 'B'
            results.append((pin_key, net_name, f'FALLBACK_{case}',
                            f'vertex=({rx},{ry})'))
            continue

        # ── Scan fallback ───────────────────────────────────────────
        _scan_ok = False
        _best_scan_d = 99999
        _v3_endcap = VIA3_SZ // 2 + 90

        for _seg in segs:
            if _seg[4] != M4_LYR:
                continue
            _sx1, _sy1, _sx2, _sy2 = _seg[:4]
            if (min(_sx1, _sx2) > ap_x + 700 or max(_sx1, _sx2) < ap_x - 700
                    or min(_sy1, _sy2) > ap_y + 700
                    or max(_sy1, _sy2) < ap_y - 700):
                continue
            if _sx1 == _sx2:
                _wx = _sx1
                _y_lo = min(_sy1, _sy2) + _v3_endcap
                _y_hi = max(_sy1, _sy2) - _v3_endcap
                if _y_lo > _y_hi:
                    continue
                _wy = _y_lo
                while _wy <= _y_hi:
                    _wy_s = ((_wy + 2) // 5) * 5
                    _wx_s = ((_wx + 2) // 5) * 5
                    if not _m3_rect_conflict(
                            _wx_s - hp_via2_m3, _wy_s - hp_via2_m3,
                            _wx_s + hp_via2_m3, _wy_s + hp_via2_m3, net_name):
                        _d = abs(_wx_s - ap_x) + abs(_wy_s - ap_y)
                        if _d < _best_scan_d:
                            _best_scan_d = _d
                            _scan_ok = True
                    _wy += 50
            else:
                _wy = _sy1
                _x_lo = min(_sx1, _sx2) + _v3_endcap
                _x_hi = max(_sx1, _sx2) - _v3_endcap
                if _x_lo > _x_hi:
                    continue
                _wx = _x_lo
                while _wx <= _x_hi:
                    _wx_s = ((_wx + 2) // 5) * 5
                    _wy_s = ((_wy + 2) // 5) * 5
                    if not _m3_rect_conflict(
                            _wx_s - hp_via2_m3, _wy_s - hp_via2_m3,
                            _wx_s + hp_via2_m3, _wy_s + hp_via2_m3, net_name):
                        _d = abs(_wx_s - ap_x) + abs(_wy_s - ap_y)
                        if _d < _best_scan_d:
                            _best_scan_d = _d
                            _scan_ok = True
                    _wx += 50

        if _scan_ok and _best_scan_d <= 700:
            results.append((pin_key, net_name, 'SCAN',
                            f'dist={_best_scan_d}nm'))
            continue

        # ── All paths failed ────────────────────────────────────────
        results.append((pin_key, net_name, 'SKIPPED',
                        f'vertex=({rx},{ry}) dist={best_dist}nm'))

# ── Report ──────────────────────────────────────────────────────────
print("=" * 85)
print("GATE PIN Via2 STATUS (replays _add_missing_ap_via2 logic)")
print("=" * 85)
print()

status_counts = Counter(r[2] for r in results)
for st in ['HAS_LOW', 'NORMAL', 'FALLBACK_A', 'FALLBACK_B', 'SCAN',
           'SKIP_VIA3_CONFLICT', 'TOO_FAR', 'NO_VIA_PAD', 'SKIPPED']:
    c = status_counts.get(st, 0)
    if c:
        marker = '*** PROBLEM' if st in ('SKIPPED', 'TOO_FAR',
                                          'SKIP_VIA3_CONFLICT') else ''
        print(f"  {st:22s}: {c:4d}  {marker}")
print(f"  {'TOTAL':22s}: {len(results):4d}")
print()

# ── HAS_LOW breakdown ──────────────────────────────────────────────
has_low_pins = [r for r in results if r[2] == 'HAS_LOW']
if has_low_pins:
    print("=" * 85)
    print("HAS_LOW pins: router M1/M2/Via1 reaches AP → _add_missing_ap_via2 SKIPS these")
    print("  These rely on the existing route to provide Via2 connectivity up to M3/M4.")
    print("  If the route M2 endpoint has no Via2 going up, the gate is ISOLATED.")
    print("=" * 85)
    print()

    # For each HAS_LOW pin, check if there's a Via2 segment in the route
    # near the AP (within 1µm)
    has_low_with_via2 = 0
    has_low_no_via2 = 0
    has_low_no_via2_list = []
    for pin_key, net_name, _, detail in has_low_pins:
        ap = aps[pin_key]
        ap_x, ap_y = ap['x'], ap['y']
        route = sroutes[net_name]
        segs = route['segments']

        # Find nearest Via2 on this net
        best_v2_dist = float('inf')
        for seg in segs:
            if seg[4] == -2:  # Via2
                d = abs(seg[0] - ap_x) + abs(seg[1] - ap_y)
                if d < best_v2_dist:
                    best_v2_dist = d

        # The AP M2 pad connects to the routing M2 wire (has_low=True).
        # But we need Via2 SOMEWHERE on this M2 wire (not necessarily at AP).
        # Check if ANY Via2 exists on the same net
        has_any_via2 = any(seg[4] == -2 for seg in segs)

        if has_any_via2:
            has_low_with_via2 += 1
        else:
            has_low_no_via2 += 1
            has_low_no_via2_list.append(
                (pin_key, net_name, best_v2_dist, detail))

    print(f"  HAS_LOW with Via2 on net:  {has_low_with_via2}")
    print(f"  HAS_LOW WITHOUT Via2:      {has_low_no_via2}  *** PROBLEM")
    print()
    if has_low_no_via2_list:
        for pin_key, net_name, v2_dist, detail in has_low_no_via2_list:
            print(f"    {pin_key:22s} net={net_name:15s} {detail}")
    print()

# ── SKIPPED details ────────────────────────────────────────────────
problem_pins = [r for r in results if r[2] in ('SKIPPED', 'TOO_FAR',
                                                 'SKIP_VIA3_CONFLICT')]
if problem_pins:
    print("=" * 85)
    print(f"PROBLEM PINS ({len(problem_pins)} total) — no Via2 placed, gate DISCONNECTED")
    print("=" * 85)
    print()
    for pin_key, net_name, status, detail in sorted(problem_pins):
        print(f"  {pin_key:22s} net={net_name:15s} status={status:20s} {detail}")
    print()

    # Net-level summary
    problem_nets = defaultdict(list)
    for pin_key, net_name, status, detail in problem_pins:
        problem_nets[net_name].append(pin_key)
    print(f"  Affected nets: {len(problem_nets)}")
    for net in sorted(problem_nets, key=lambda n: -len(problem_nets[n])):
        print(f"    {net:15s}: {len(problem_nets[net])} pins — "
              f"{', '.join(problem_nets[net][:5])}")

print()
print("=" * 85)
print("SUMMARY")
print("=" * 85)
connected = sum(1 for r in results if r[2] in
                ('HAS_LOW', 'NORMAL', 'FALLBACK_A', 'FALLBACK_B', 'SCAN'))
disconnected = len(results) - connected
print(f"  Gate pins with Via2 path (connected):     {connected}")
print(f"  Gate pins WITHOUT Via2 path (disconnected): {disconnected}")
print(f"  Total gate pins:                           {len(results)}")
