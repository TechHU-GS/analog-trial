#!/usr/bin/env python3
"""Break down the 11 C3 nets into sub-categories.

C3 nets: buf1, div16_I, div16_Q, div2_Q, div4_Q, f_exc_b_d,
         t1Q_mb, t2Q_m, t2Q_mb, t3_mb, t4Q_mb

Hypothesis:
 - Some are M3_CONFLICT (= Category A but missed by hardcoded set)
 - Some are HAS_LOW with Via2 but M2 graph fragmented (= Category B)
 - Some are all-NORMAL but backbone fragmented

Usage:
    cd layout && python3 diagnose_c3_breakdown.py
"""
import os, json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

M1_LYR, M2_LYR, M3_LYR, M4_LYR = 0, 1, 2, 3
M1_SIG_W = 300
M3_MIN_W = 200
_wire_hw = M1_SIG_W // 2

with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing.get('access_points', {})
sroutes = routing.get('signal_routes', {})

C3_NETS = ['buf1', 'div16_I', 'div16_Q', 'div2_Q', 'div4_Q', 'f_exc_b_d',
           't1Q_mb', 't2Q_m', 't2Q_mb', 't3_mb', 't4Q_mb']


def has_low_check(pin_key, segs):
    ap = aps.get(pin_key)
    if not ap or not ap.get('via_pad') or 'm2' not in ap['via_pad']:
        return False
    ap_x, ap_y = ap['x'], ap['y']
    _m1r = ap['via_pad'].get('m1', [0, 0, 0, 0])
    _m2r = ap['via_pad'].get('m2', [0, 0, 0, 0])
    for seg in segs:
        lyr = seg[4]
        if lyr == M1_LYR:
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                if (px + _wire_hw > _m1r[0] and px - _wire_hw < _m1r[2]
                        and py + _wire_hw > _m1r[1] and py - _wire_hw < _m1r[3]):
                    return True
        elif lyr == M2_LYR:
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                        and py + _wire_hw > _m2r[1] and py - _wire_hw < _m2r[3]):
                    return True
        elif lyr == -1:
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                if abs(px - ap_x) <= 200 and abs(py - ap_y) <= 200:
                    return True
    return False


# Union-Find
class UF:
    def __init__(self):
        self.p = {}
    def find(self, x):
        while self.p.get(x, x) != x:
            self.p[x] = self.p.get(self.p[x], self.p[x])
            x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


# ── Analyze each C3 net ────────────────────────────────────────────
print("=" * 85)
print("C3 NET BREAKDOWN")
print("=" * 85)
print()

sub_a = []  # Has M3_CONFLICT pin (= Category A)
sub_b = []  # All HAS_LOW, M2 graph fragmented (= Category B)
sub_d = []  # All NORMAL, backbone fragmented
sub_e = []  # Unknown

for net_name in C3_NETS:
    if net_name not in sroutes:
        continue
    route = sroutes[net_name]
    segs = route.get('segments', [])
    pins = route.get('pins', [])
    gate_pins = [p for p in pins if '.G' in p]
    has_via2 = any(s[4] == -2 for s in segs)

    # Classify pins
    hl_pins = []
    non_hl_pins = []
    for p in gate_pins:
        if has_low_check(p, segs):
            hl_pins.append(p)
        else:
            non_hl_pins.append(p)

    # Check backbone connectivity (all layers)
    uf = UF()
    all_pts = set()
    for seg in segs:
        lyr = seg[4]
        if lyr < 0:  # via
            pt = (seg[0], seg[1])
            all_pts.add(pt)
        else:
            p1 = (seg[0], seg[1])
            p2 = (seg[2], seg[3])
            all_pts.add(p1)
            all_pts.add(p2)
            uf.union(p1, p2)
    # Connect via to nearby wire endpoints
    for seg in segs:
        if seg[4] >= 0:
            continue  # skip wires
        vpt = (seg[0], seg[1])
        for seg2 in segs:
            if seg2[4] < 0:
                continue
            for px, py in ((seg2[0], seg2[1]), (seg2[2], seg2[3])):
                if abs(px - vpt[0]) <= 200 and abs(py - vpt[1]) <= 200:
                    uf.union(vpt, (px, py))
    # Also connect overlapping endpoints (same position)
    pts_list = list(all_pts)
    for i in range(len(pts_list)):
        for j in range(i + 1, len(pts_list)):
            if (abs(pts_list[i][0] - pts_list[j][0]) <= 10 and
                    abs(pts_list[i][1] - pts_list[j][1]) <= 10):
                uf.union(pts_list[i], pts_list[j])
    roots = set(uf.find(p) for p in all_pts)
    n_components = len(roots)

    # Map gate APs to components
    ap_comps = {}
    for p in gate_pins:
        ap = aps.get(p)
        if not ap:
            continue
        ax, ay = ap['x'], ap['y']
        best = None
        best_d = float('inf')
        for pt in all_pts:
            d = abs(pt[0] - ax) + abs(pt[1] - ay)
            if d < best_d:
                best_d = d
                best = pt
        if best and best_d < 1000:
            comp = uf.find(best)
            ap_comps.setdefault(comp, []).append(p)

    gates_in_diff_comps = len(ap_comps) > 1

    # ── Classify ────────────────────────────────────────────────────
    # All HAS_LOW? (no non_hl pins)
    all_hl = len(non_hl_pins) == 0
    all_normal = len(hl_pins) == 0

    if not all_hl and not all_normal:
        # Mixed — but in Category C diagnostic, C2 already caught mixed
        # where there are HAS_LOW + non-HAS_LOW. This shouldn't happen.
        category = 'mixed'
    elif all_hl:
        if gates_in_diff_comps:
            category = 'B_variant'  # M2+backbone graph fragmented
            sub_b.append(net_name)
        else:
            category = 'B_connected'  # graph connected but still fragmented??
            sub_e.append(net_name)
    elif all_normal:
        if gates_in_diff_comps:
            category = 'D_backbone_frag'
            sub_d.append(net_name)
        else:
            category = 'E_mystery'
            sub_e.append(net_name)
    else:
        category = '???'
        sub_e.append(net_name)

    print(f"  {net_name:15s}: gate={len(gate_pins)} "
          f"HL={len(hl_pins)} non-HL={len(non_hl_pins)} "
          f"via2={'Y' if has_via2 else 'N'} "
          f"comps={n_components} gate_comps={len(ap_comps)} "
          f"→ {category}")

    if gates_in_diff_comps:
        for comp, cpins in sorted(ap_comps.items(), key=lambda x: -len(x[1])):
            print(f"    component: {', '.join(cpins)}")

print()

# buf1 and f_exc_b_d have M3_CONFLICT pins — check if those are effectively SKIPPED
print("=" * 85)
print("buf1 and f_exc_b_d: M3_CONFLICT pins detail")
print("=" * 85)
print()
for net_name in ['buf1', 'f_exc_b_d']:
    if net_name not in sroutes:
        continue
    route = sroutes[net_name]
    segs = route['segments']
    gate_pins = [p for p in route['pins'] if '.G' in p]
    for p in gate_pins:
        hl = has_low_check(p, segs)
        ap = aps.get(p)
        if not ap:
            continue
        ax, ay = ap['x'], ap['y']
        # Find nearest upper vertex
        best_d = float('inf')
        best_v = None
        best_lyr = None
        for seg in segs:
            if seg[4] not in (M3_LYR, M4_LYR, -3):
                continue
            for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                d = abs(px - ax) + abs(py - ay)
                if d < best_d:
                    best_d = d
                    best_v = (px, py)
                    best_lyr = seg[4]
        lyr_name = {M3_LYR: 'M3', M4_LYR: 'M4', -3: 'Via3'}.get(best_lyr, '?')
        print(f"  {p:22s} net={net_name:10s} HL={hl} "
              f"vertex={best_v} dist={best_d:.0f}nm on {lyr_name}")

print()
print("=" * 85)
print("C3 FINAL CLASSIFICATION")
print("=" * 85)
print()
print(f"  → Category A (M3_CONFLICT / SKIPPED):  buf1, f_exc_b_d")
print(f"  → Category B (all HAS_LOW, graph frag): {', '.join(sub_b) if sub_b else 'none'}")
print(f"  → Category D (all NORMAL, backbone frag): {', '.join(sub_d) if sub_d else 'none'}")
print(f"  → Category E (mystery):                 {', '.join(sub_e) if sub_e else 'none'}")
