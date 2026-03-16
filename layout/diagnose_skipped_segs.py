#!/usr/bin/env python3
"""Show route segments near APs that get skipped for Via2.

For each skipped AP, show what M3/M4/Via segments exist nearby.
"""
import os
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))

M1_LYR, M2_LYR, M3_LYR, M4_LYR = 0, 1, 2, 3
M1_SIG_W = 300
VIA2_SZ = 190
VIA2_PAD_M3 = 380
VIA3_PAD = 380
M3_MIN_W = 200
M3_MIN_S = 210
_VIA2_M2_ENDCAP = 145

LAYER_NAMES = {-3: 'Via3', -2: 'Via2', -1: 'Via1', 0: 'M1', 1: 'M2', 2: 'M3', 3: 'M4'}

with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing['access_points']
sroutes = routing['signal_routes']
pre_routes = routing.get('pre_routes', {})

via_stack_pins = set()
for net_name, pr in pre_routes.items():
    for seg in pr.get('segments', []):
        if seg[4] == -2:
            for pin_key in pr.get('pins', []):
                ap = aps.get(pin_key)
                if ap and abs(ap['x'] - seg[0]) < 200 and abs(ap['y'] - seg[1]) < 200:
                    via_stack_pins.add(pin_key)

_wire_hw = M1_SIG_W // 2

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

skipped_count = 0
m3_wire_count = 0
m3_wire_long_count = 0

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
        ap_x, ap_y = ap['x'], ap['y']

        # Check has_low
        has_low = False
        _m1r = ap['via_pad'].get('m1', [0, 0, 0, 0])
        _m2r = ap['via_pad'].get('m2', [0, 0, 0, 0])
        for seg in segs:
            lyr = seg[4]
            if lyr == 0:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m1r[0] and px - _wire_hw < _m1r[2]
                            and py + _wire_hw > _m1r[1] and py - _wire_hw < _m1r[3]):
                        has_low = True
                        break
            elif lyr == 1:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                            and py + _wire_hw > _m2r[1] and py - _wire_hw < _m2r[3]):
                        has_low = True
                        break
            elif lyr == -1:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if abs(px - ap_x) <= 200 and abs(py - ap_y) <= 200:
                        has_low = True
                        break
            if has_low:
                break
        if has_low:
            continue

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

        # Check AP-center conflict
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
            continue  # Via2 at AP center OK

        # Check original fallback
        _m3_seg = None
        for seg in segs:
            if seg[4] == M3_LYR:
                if ((seg[0] == rx and seg[1] == ry) or (seg[2] == rx and seg[3] == ry)):
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
            if not _m3_rect_conflict(rx - hp_via2_m3, ry - hp_via2_m3,
                                     rx + hp_via2_m3, ry + hp_via2_m3, net_name):
                _fb_ok = True
        if _fb_ok:
            continue

        # SKIPPED
        skipped_count += 1

        # Show all M3 segments of this route
        m3_segs_near = []
        for seg in segs:
            if seg[4] == M3_LYR:
                sx1, sy1, sx2, sy2 = seg[:4]
                d = min(abs(sx1-ap_x)+abs(sy1-ap_y), abs(sx2-ap_x)+abs(sy2-ap_y))
                if d < 1500:
                    if sx1 == sx2:
                        wlen = abs(sy2 - sy1)
                    else:
                        wlen = abs(sx2 - sx1)
                    m3_segs_near.append((seg, d, wlen))
                    m3_wire_count += 1
                    v2_endcap = VIA2_SZ // 2 + 50
                    if wlen >= 2 * v2_endcap:
                        m3_wire_long_count += 1

        if skipped_count <= 15:
            print(f"\n  {pin_key:20s} net={net_name:15s} AP=({ap_x},{ap_y}) vertex=({rx},{ry})")
            # Show upper-layer segments near AP
            for seg in segs:
                lyr = seg[4]
                if lyr not in (M3_LYR, M4_LYR, -2, -3):
                    continue
                d = min(abs(seg[0]-ap_x)+abs(seg[1]-ap_y),
                        abs(seg[2]-ap_x)+abs(seg[3]-ap_y))
                if d < 1000:
                    print(f"    [{LAYER_NAMES[lyr]:4s}] ({seg[0]},{seg[1]})->({seg[2]},{seg[3]}) dist={d}")

            for seg_info, d, wlen in m3_segs_near:
                seg = seg_info
                v2_endcap = VIA2_SZ // 2 + 50
                fits = "✓ FITS" if wlen >= 2 * v2_endcap else f"✗ too short (need {2*v2_endcap})"
                print(f"    M3 wire len={wlen}nm dist={d}nm {fits}")

print(f"\n\nTotal skipped: {skipped_count}")
print(f"M3 wires within 1500nm of skipped APs: {m3_wire_count}")
print(f"  of which long enough for Via2: {m3_wire_long_count}")
