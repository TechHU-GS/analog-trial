#!/usr/bin/env python3
"""Deep-dive into Category C: nets where Via2 NORMAL placement succeeded
but LVS still shows fragmentation.

For 4 representative nets (buf1, net_c1, t1I_mb, vco_out), answers:
  1. Did M3 stub actually overlap with same-net backbone?
  2. Mixed HAS_LOW + NORMAL pins on same net?
  3. Where exactly does the chain break?

Usage:
    cd layout && python3 diagnose_category_c.py
"""
import os, json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

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

with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing.get('access_points', {})
sroutes = routing.get('signal_routes', {})

via_stack_pins = set()
for drop in routing.get('power', {}).get('drops', []):
    if drop['type'] == 'via_stack':
        via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

# Build M3 obstacle list
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
        m3_obs.append((_vb[0] - hw, min(_vb[1], _vb[3]),
                       _vb[0] + hw, max(_vb[1], _vb[3]), drop['net']))


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


def classify_pin(pin_key, net_name, segs):
    """Replay _add_missing_ap_via2 for a single pin. Returns (status, detail_dict)."""
    ap = aps.get(pin_key)
    if not ap or not ap.get('via_pad') or 'm2' not in ap['via_pad']:
        return 'NO_VIA_PAD', {}

    ap_x, ap_y = ap['x'], ap['y']
    _m1r = ap['via_pad'].get('m1', [0, 0, 0, 0])
    _m2r = ap['via_pad'].get('m2', [0, 0, 0, 0])

    # has_low check
    has_low = False
    low_layer = None
    low_seg = None
    for seg in segs:
        lyr = seg[4]
        if lyr == M1_LYR:
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                if (px + _wire_hw > _m1r[0] and px - _wire_hw < _m1r[2]
                        and py + _wire_hw > _m1r[1] and py - _wire_hw < _m1r[3]):
                    has_low = True
                    low_layer = 'M1'
                    low_seg = seg
                    break
        elif lyr == M2_LYR:
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                        and py + _wire_hw > _m2r[1] and py - _wire_hw < _m2r[3]):
                    has_low = True
                    low_layer = 'M2'
                    low_seg = seg
                    break
        elif lyr == -1:
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                if abs(px - ap_x) <= 200 and abs(py - ap_y) <= 200:
                    has_low = True
                    low_layer = 'Via1'
                    low_seg = seg
                    break
        if has_low:
            break

    if has_low:
        return 'HAS_LOW', {'low_layer': low_layer, 'low_seg': low_seg}

    # Find nearest M3/M4/Via3 vertex
    best_dist = float('inf')
    best_pos = None
    best_seg = None
    for seg in segs:
        lyr = seg[4]
        if lyr not in (M3_LYR, M4_LYR, -3):
            continue
        for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
            dist = abs(px - ap_x) + abs(py - ap_y)
            if dist < best_dist:
                best_dist = dist
                best_pos = (px, py)
                best_seg = seg

    if not best_pos or best_dist > 500:
        return 'TOO_FAR', {'dist': best_dist}

    rx, ry = best_pos

    # M3 bbox for normal path
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

    # Snap
    mbx1 = (_mbx1 // 5) * 5
    mby1 = (_mby1 // 5) * 5
    mbx2 = ((_mbx2 + 4) // 5) * 5
    mby2 = ((_mby2 + 4) // 5) * 5

    if not _m3_rect_conflict(_mbx1, _mby1, _mbx2, _mby2, net_name):
        # Normal path
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
        return 'NORMAL', {
            'vertex': (rx, ry), 'vertex_seg': best_seg,
            'need_via3': need_via3,
            'm3_bbox': (mbx1, mby1, mbx2, mby2),
            'vertex_dist': best_dist,
        }

    return 'M3_CONFLICT', {'vertex': (rx, ry), 'dist': best_dist}


def rects_overlap(a, b):
    """Check if two rects (x1,y1,x2,y2) overlap."""
    return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]


# ── Analyze representative nets ────────────────────────────────────
TARGET_NETS = ['buf1', 'net_c1', 't1I_mb', 'vco_out']

# Also do all 18 uncovered nets for completeness
ALL_UNCOVERED = [
    'buf1', 'comp_outn', 'div16_I', 'div16_Q', 'div16_Q_b', 'div2_Q',
    'div4_Q', 'f_exc_b', 'f_exc_b_d', 'net_c1', 't1I_mb', 't1Q_mb',
    't2Q_m', 't2Q_mb', 't3_mb', 't4I_mb', 't4Q_mb', 'vcas',
]

for net_name in ALL_UNCOVERED:
    if net_name not in sroutes:
        continue
    route = sroutes[net_name]
    segs = route.get('segments', [])
    pins = route.get('pins', [])
    gate_pins = [p for p in pins if '.G' in p]

    is_target = net_name in TARGET_NETS
    separator = "=" * 85 if is_target else "-" * 85
    print(separator)
    print(f"NET: {net_name} ({len(gate_pins)} gate pins, {len(segs)} segments)")
    print(separator)

    # Layer breakdown
    layer_counts = defaultdict(int)
    for seg in segs:
        layer_counts[seg[4]] += 1
    layer_str = ', '.join(f"{k}={v}" for k, v in
                          sorted(layer_counts.items()))
    print(f"  Segments by layer: {layer_str}")
    print(f"  Has Via2 in routing: {any(s[4] == -2 for s in segs)}")
    print()

    # Classify each gate pin
    pin_statuses = []
    for pin_key in gate_pins:
        status, detail = classify_pin(pin_key, net_name, segs)
        pin_statuses.append((pin_key, status, detail))

    # Count statuses
    status_summary = defaultdict(int)
    for _, st, _ in pin_statuses:
        status_summary[st] += 1
    print(f"  Pin classification: {dict(status_summary)}")
    print()

    # Q2: Mixed HAS_LOW + non-HAS_LOW?
    has_low_pins = [(p, d) for p, s, d in pin_statuses if s == 'HAS_LOW']
    non_has_low = [(p, s, d) for p, s, d in pin_statuses if s != 'HAS_LOW']
    is_mixed = bool(has_low_pins) and bool(non_has_low)
    print(f"  Q2 - Mixed HAS_LOW + others: {'YES' if is_mixed else 'NO'}")
    if is_mixed:
        print(f"    HAS_LOW pins ({len(has_low_pins)}):")
        for p, d in has_low_pins:
            seg = d.get('low_seg', [0, 0, 0, 0, 0])
            print(f"      {p:22s} via {d['low_layer']} "
                  f"seg=({seg[0]},{seg[1]})->({seg[2]},{seg[3]})")
        print(f"    Non-HAS_LOW pins ({len(non_has_low)}):")
        for p, s, d in non_has_low:
            vtx = d.get('vertex', ('?', '?'))
            print(f"      {p:22s} status={s} vertex={vtx}")
    print()

    # Q1: For NORMAL pins, does M3 stub overlap with same-net backbone?
    normal_pins = [(p, d) for p, s, d in pin_statuses if s == 'NORMAL']
    if normal_pins:
        print(f"  Q1 - M3 stub → backbone overlap check ({len(normal_pins)} NORMAL pins):")
        for pin_key, detail in normal_pins:
            ap = aps[pin_key]
            ap_x, ap_y = ap['x'], ap['y']
            m3_bbox = detail['m3_bbox']
            rx, ry = detail['vertex']
            need_via3 = detail['need_via3']

            # Find all same-net M3 segments
            same_net_m3 = []
            for seg in segs:
                if seg[4] == M3_LYR:
                    x1, y1, x2, y2 = seg[:4]
                    hw = M3_MIN_W // 2
                    if x1 == x2:
                        wire_rect = (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
                    else:
                        wire_rect = (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)
                    same_net_m3.append((seg, wire_rect))

            # Check if M3 bbox overlaps any same-net M3 wire
            overlaps = []
            for seg, wire_rect in same_net_m3:
                if rects_overlap(m3_bbox, wire_rect):
                    overlaps.append((seg, wire_rect))

            # If need_via3, also check M4 coverage at vertex
            m4_at_vertex = []
            if need_via3:
                for seg in segs:
                    if seg[4] == M4_LYR:
                        x1, y1, x2, y2 = seg[:4]
                        hw = M1_SIG_W // 2  # M4 wire width
                        if x1 == x2:
                            wire_rect = (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
                        else:
                            wire_rect = (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)
                        # Check if vertex is on this M4 wire
                        if (wire_rect[0] <= rx <= wire_rect[2] and
                                wire_rect[1] <= ry <= wire_rect[3]):
                            m4_at_vertex.append(seg)

            overlap_ok = len(overlaps) > 0 or (need_via3 and len(m4_at_vertex) > 0)

            print(f"    {pin_key:22s} AP=({ap_x},{ap_y}) "
                  f"vertex=({rx},{ry}) via3={'Y' if need_via3 else 'N'}")
            print(f"      M3 bbox: ({m3_bbox[0]},{m3_bbox[1]})-"
                  f"({m3_bbox[2]},{m3_bbox[3]})")
            if overlaps:
                for seg, wr in overlaps:
                    print(f"      ✓ M3 bbox overlaps M3 wire "
                          f"({seg[0]},{seg[1]})->({seg[2]},{seg[3]})")
            elif need_via3 and m4_at_vertex:
                for seg in m4_at_vertex:
                    print(f"      ✓ Via3@vertex on M4 wire "
                          f"({seg[0]},{seg[1]})->({seg[2]},{seg[3]})")
            else:
                print(f"      ✗ M3 bbox does NOT overlap any same-net M3!")
                if need_via3:
                    print(f"      ✗ No M4 wire at vertex either!")
                # Show nearest M3 wire
                if same_net_m3:
                    best_m3_d = float('inf')
                    best_m3 = None
                    for seg, wr in same_net_m3:
                        for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                            d = abs(px - rx) + abs(py - ry)
                            if d < best_m3_d:
                                best_m3_d = d
                                best_m3 = seg
                    if best_m3:
                        print(f"      Nearest M3: ({best_m3[0]},{best_m3[1]})->"
                              f"({best_m3[2]},{best_m3[3]}) dist={best_m3_d}nm")
                # Show nearest M4 wire
                best_m4_d = float('inf')
                best_m4 = None
                for seg in segs:
                    if seg[4] == M4_LYR:
                        for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                            d = abs(px - rx) + abs(py - ry)
                            if d < best_m4_d:
                                best_m4_d = d
                                best_m4 = seg
                if best_m4:
                    print(f"      Nearest M4: ({best_m4[0]},{best_m4[1]})->"
                          f"({best_m4[2]},{best_m4[3]}) dist={best_m4_d}nm")

            if not overlap_ok:
                print(f"      >>> ROOT CAUSE: M3 stub island — Via2 placed but "
                      f"not connected to backbone")
        print()

    # Q3: For HAS_LOW pins, trace the M2 connection path
    if has_low_pins and is_target:
        print(f"  Q3 - HAS_LOW chain trace ({len(has_low_pins)} pins):")
        for pin_key, detail in has_low_pins:
            ap = aps[pin_key]
            ap_x, ap_y = ap['x'], ap['y']
            low_seg = detail['low_seg']
            low_lyr = detail['low_layer']

            # Find the M2 segment that reaches this AP
            # Then trace: does this M2 segment have a Via2 anywhere?
            m2_touching = []
            _m2r = ap['via_pad']['m2']
            for seg in segs:
                if seg[4] != M2_LYR:
                    continue
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                            and py + _wire_hw > _m2r[1]
                            and py - _wire_hw < _m2r[3]):
                        m2_touching.append(seg)
                        break

            # Check if any Via2 connects to these M2 segments
            via2_on_m2 = []
            for v2_seg in segs:
                if v2_seg[4] != -2:
                    continue
                v2x, v2y = v2_seg[0], v2_seg[1]
                for m2_seg in m2_touching:
                    # Check if Via2 position is on the M2 wire
                    x1, y1, x2, y2 = m2_seg[:4]
                    hw = _wire_hw
                    if x1 == x2:  # vertical
                        if (abs(v2x - x1) <= hw and
                                min(y1, y2) <= v2y <= max(y1, y2)):
                            via2_on_m2.append((v2_seg, m2_seg))
                    elif y1 == y2:  # horizontal
                        if (abs(v2y - y1) <= hw and
                                min(x1, x2) <= v2x <= max(x1, x2)):
                            via2_on_m2.append((v2_seg, m2_seg))

            print(f"    {pin_key:22s} via {low_lyr}")
            print(f"      M2 segs touching AP pad: {len(m2_touching)}")
            print(f"      Via2 on those M2 segs:    {len(via2_on_m2)}")
            if not via2_on_m2:
                # Check nearest Via2 on ANY segment of this net
                best_v2 = float('inf')
                for seg in segs:
                    if seg[4] == -2:
                        d = abs(seg[0] - ap_x) + abs(seg[1] - ap_y)
                        if d < best_v2:
                            best_v2 = d
                has_any_v2 = any(s[4] == -2 for s in segs)
                print(f"      Net has any Via2: {has_any_v2}"
                      f" (nearest={best_v2:.0f}nm)" if has_any_v2 else "")
                if not has_any_v2:
                    print(f"      >>> CHAIN BREAK: M2 reaches AP but NO Via2 "
                          f"anywhere on net → M2 island")
        print()

    print()

# ── Final classification of all 18 uncovered nets ──────────────────
print("=" * 85)
print("CATEGORY C ROOT CAUSE CLASSIFICATION")
print("=" * 85)
print()

c1_count = 0  # M3 stub island
c2_count = 0  # Mixed HAS_LOW + disconnected M2
c3_count = 0  # Other
c1_nets = []
c2_nets = []
c3_nets = []

for net_name in ALL_UNCOVERED:
    if net_name not in sroutes:
        continue
    route = sroutes[net_name]
    segs = route.get('segments', [])
    pins = route.get('pins', [])
    gate_pins = [p for p in pins if '.G' in p]

    pin_statuses = []
    for pin_key in gate_pins:
        status, detail = classify_pin(pin_key, net_name, segs)
        pin_statuses.append((pin_key, status, detail))

    has_low_pins = [p for p, s, _ in pin_statuses if s == 'HAS_LOW']
    normal_pins = [(p, d) for p, s, d in pin_statuses if s == 'NORMAL']
    is_mixed = bool(has_low_pins) and bool(
        [p for p, s, _ in pin_statuses if s != 'HAS_LOW'])

    # Check if any NORMAL pin has M3 stub that doesn't overlap backbone
    has_m3_island = False
    for pin_key, detail in normal_pins:
        m3_bbox = detail['m3_bbox']
        rx, ry = detail['vertex']
        need_via3 = detail['need_via3']

        backbone_overlap = False
        for seg in segs:
            if seg[4] == M3_LYR:
                x1, y1, x2, y2 = seg[:4]
                hw = M3_MIN_W // 2
                if x1 == x2:
                    wr = (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
                else:
                    wr = (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)
                if rects_overlap(m3_bbox, wr):
                    backbone_overlap = True
                    break
        if not backbone_overlap and need_via3:
            for seg in segs:
                if seg[4] == M4_LYR:
                    x1, y1, x2, y2 = seg[:4]
                    hw = M1_SIG_W // 2
                    if x1 == x2:
                        wr = (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
                    else:
                        wr = (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)
                    if (wr[0] <= rx <= wr[2] and wr[1] <= ry <= wr[3]):
                        backbone_overlap = True
                        break
        if not backbone_overlap:
            has_m3_island = True

    if has_m3_island:
        c1_count += 1
        c1_nets.append(net_name)
    elif is_mixed:
        c2_count += 1
        c2_nets.append(net_name)
    else:
        c3_count += 1
        c3_nets.append(net_name)

print(f"  C1 — M3 stub island (Via2 placed but stub doesn't reach backbone): "
      f"{c1_count} nets")
if c1_nets:
    print(f"       {', '.join(c1_nets)}")
print(f"  C2 — Mixed HAS_LOW + non-HAS_LOW (M2 routing graph fragmented):    "
      f"{c2_count} nets")
if c2_nets:
    print(f"       {', '.join(c2_nets)}")
print(f"  C3 — Other / unknown:                                               "
      f"{c3_count} nets")
if c3_nets:
    print(f"       {', '.join(c3_nets)}")
print()

# ── Grand unified table ────────────────────────────────────────────
print("=" * 85)
print("GRAND UNIFIED ROOT CAUSE TABLE (all 53 fragmented nets)")
print("=" * 85)
print()
print(f"  {'Category':<60} {'Nets':>5}")
print(f"  {'-'*60} {'-'*5}")
print(f"  {'A: SKIPPED — Via2 M3 conflict (no Via2 placed)':<60} {'22':>5}")
print(f"  {'B: HAS_LOW-no-Via2 — M2 routing graph fragmented':<60} {'18':>5}")
print(f"  {'C1: NORMAL Via2 but M3 stub island (not touching backbone)':<60} {c1_count:>5}")
print(f"  {'C2: Mixed HAS_LOW + NORMAL — routing graph fragmented':<60} {c2_count:>5}")
print(f"  {'C3: Other':<60} {c3_count:>5}")
total = 22 + 18 + c1_count + c2_count + c3_count
# Note: some overlap between B and C
print(f"  {'(with overlaps, total unique = 53)':<60}")
