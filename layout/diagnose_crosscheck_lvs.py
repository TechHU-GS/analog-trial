#!/usr/bin/env python3
"""Cross-check: 52 HAS_LOW-no-Via2 pins vs 53 LVS fragmented nets.

Answers: are the HAS_LOW-no-Via2 nets actually showing up as LVS gate
fragmentation?  If yes, the M1/M2 routing graph is internally disconnected.

Also checks: for each HAS_LOW-no-Via2 net, is the M2 routing graph
connected? (Do all M2 segments form a single connected component?)

Usage:
    cd layout && python3 diagnose_crosscheck_lvs.py
"""
import os, json
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Constants ───────────────────────────────────────────────────────
M1_LYR, M2_LYR = 0, 1
M1_SIG_W = 300
_wire_hw = M1_SIG_W // 2

# ── Load routing data ──────────────────────────────────────────────
with open('output/routing.json') as f:
    routing = json.load(f)

aps = routing.get('access_points', {})
sroutes = routing.get('signal_routes', {})

# ── Replay has_low + no-Via2 classification ─────────────────────────
via_stack_pins = set()
for drop in routing.get('power', {}).get('drops', []):
    if drop['type'] == 'via_stack':
        via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

has_low_no_via2_nets = set()
has_low_no_via2_pins = defaultdict(list)  # net -> [pin_key]

for net_name, route in sroutes.items():
    segs = route.get('segments', [])
    if not segs:
        continue
    # Check if net has ANY Via2
    has_any_via2 = any(seg[4] == -2 for seg in segs)
    if has_any_via2:
        continue  # Not in the problem set

    pins = route.get('pins', [])
    for pin_key in pins:
        if '.G' not in pin_key:
            continue
        if pin_key in via_stack_pins:
            continue
        ap = aps.get(pin_key)
        if not ap or not ap.get('via_pad') or 'm2' not in ap['via_pad']:
            continue

        ap_x, ap_y = ap['x'], ap['y']
        _m1r = ap['via_pad'].get('m1', [0, 0, 0, 0])
        _m2r = ap['via_pad'].get('m2', [0, 0, 0, 0])

        has_low = False
        for seg in segs:
            lyr = seg[4]
            if lyr == M1_LYR:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m1r[0] and px - _wire_hw < _m1r[2]
                            and py + _wire_hw > _m1r[1]
                            and py - _wire_hw < _m1r[3]):
                        has_low = True
                        break
            elif lyr == M2_LYR:
                for px, py in ((seg[0], seg[1]), (seg[2], seg[3])):
                    if (px + _wire_hw > _m2r[0] and px - _wire_hw < _m2r[2]
                            and py + _wire_hw > _m2r[1]
                            and py - _wire_hw < _m2r[3]):
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
            has_low_no_via2_nets.add(net_name)
            has_low_no_via2_pins[net_name].append(pin_key)

# ── Load LVS fragmented nets (replay diagnose_gate_fragmentation) ──
REF_FILE = 'ptat_vco_lvs.spice'
EXT_FILE = '/tmp/lvs_r34d/ptat_vco_extracted.cir'


def parse_spice_full(path):
    devices = []
    ports = []
    with open(path) as f:
        lines = f.readlines()
    joined = []
    for line in lines:
        line = line.rstrip('\n')
        if line.startswith('+'):
            if joined:
                joined[-1] += ' ' + line[1:].strip()
            continue
        joined.append(line)
    for line in joined:
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            continue
        if stripped.lower().startswith('.subckt'):
            ports = stripped.split()[2:]
            continue
        if stripped.startswith('.'):
            continue
        parts = stripped.split()
        if not parts:
            continue
        name = parts[0]
        if name[0] in ('M', 'm') and len(parts) >= 6:
            model = parts[5]
            w = l = None
            for p in parts[6:]:
                if p.upper().startswith('W='):
                    w = p.split('=')[1].rstrip('u')
                elif p.upper().startswith('L='):
                    l = p.split('=')[1].rstrip('u')
            devices.append({
                'name': name, 'type': 'mosfet', 'model': model,
                'pins': {'D': parts[1], 'G': parts[2], 'S': parts[3], 'B': parts[4]},
                'W': w, 'L': l, 'key': f"{model}_W{w}_L{l}",
            })
        elif name[0] in ('R', 'r') and len(parts) >= 4:
            model = parts[3]
            w = l = None
            for p in parts[4:]:
                kv = p.split('=')
                if len(kv) == 2:
                    if kv[0].lower() == 'w':
                        w = kv[1].rstrip('u')
                    elif kv[0].lower() == 'l':
                        l = kv[1].rstrip('u')
            devices.append({
                'name': name, 'type': 'resistor', 'model': model,
                'pins': {'PLUS': parts[1], 'MINUS': parts[2]},
                'W': w, 'L': l, 'key': f"{model}_W{w}_L{l}",
            })
    return devices, set(ports)


ref_devs, ref_ports = parse_spice_full(REF_FILE)
ext_devs, ext_ports = parse_spice_full(EXT_FILE)

common_ports_lower = set()
for p in ext_ports:
    if p.lower() in {rp.lower() for rp in ref_ports}:
        common_ports_lower.add(p.lower())

# Match devices
ref_by_key = defaultdict(list)
ext_by_key = defaultdict(list)
for d in ref_devs:
    ref_by_key[d['key']].append(d)
for d in ext_devs:
    ext_by_key[d['key']].append(d)

device_map = {}
for key in set(ref_by_key) & set(ext_by_key):
    rds = ref_by_key[key]
    eds = list(ext_by_key[key])
    if len(rds) == 1 and len(eds) == 1:
        device_map[rds[0]['name']] = eds[0]
        continue
    used_ext = set()
    for rd in rds:
        rd_port_pins = {}
        for pin, net in rd['pins'].items():
            if net.lower() in common_ports_lower:
                rd_port_pins[pin] = net.lower()
        if not rd_port_pins:
            continue
        best_match = None
        best_score = 0
        for ed in eds:
            if ed['name'] in used_ext:
                continue
            score = 0
            for pin, ref_net_lc in rd_port_pins.items():
                ext_net = ed['pins'].get(pin, '').lower()
                if ext_net == ref_net_lc:
                    score += 2
                elif pin == 'D' and ed['pins'].get('S', '').lower() == ref_net_lc:
                    score += 1
                elif pin == 'S' and ed['pins'].get('D', '').lower() == ref_net_lc:
                    score += 1
            if score > best_score:
                best_score = score
                best_match = ed
        if best_match and best_score > 0:
            device_map[rd['name']] = best_match
            used_ext.add(best_match['name'])

# Gate fragmentation
ref_gate_net = defaultdict(list)
for d in ref_devs:
    if d['type'] == 'mosfet':
        ref_gate_net[d['pins']['G']].append((d['name'], 'G'))

gate_frags = {}
for ref_net, ref_pins in ref_gate_net.items():
    if ref_net in ('vdd', 'gnd'):
        continue
    ext_nets_found = defaultdict(list)
    for rd_name, pin_type in ref_pins:
        if rd_name not in device_map:
            continue
        ed = device_map[rd_name]
        ext_net = ed['pins'].get(pin_type, '?')
        ext_nets_found[ext_net].append((rd_name, pin_type))
    if len(ext_nets_found) > 1:
        gate_frags[ref_net] = dict(ext_nets_found)

lvs_frag_nets = set(gate_frags.keys())

# ── Cross-check ────────────────────────────────────────────────────
print("=" * 85)
print("CROSS-CHECK: HAS_LOW-no-Via2 nets vs LVS gate-fragmented nets")
print("=" * 85)
print()
print(f"  HAS_LOW-no-Via2 nets:      {len(has_low_no_via2_nets)}")
print(f"  LVS gate-fragmented nets:  {len(lvs_frag_nets)}")
print()

intersection = has_low_no_via2_nets & lvs_frag_nets
hl_only = has_low_no_via2_nets - lvs_frag_nets
lvs_only = lvs_frag_nets - has_low_no_via2_nets

print(f"  INTERSECTION (in both):    {len(intersection)}")
print(f"  HAS_LOW-only (not in LVS): {len(hl_only)}")
print(f"  LVS-only (not HAS_LOW):    {len(lvs_only)}")
print()

if intersection:
    print("  ── INTERSECTION: these HAS_LOW-no-Via2 nets ARE fragmented in LVS ──")
    for net in sorted(intersection):
        n_frags = len(gate_frags[net])
        pins = has_low_no_via2_pins[net]
        print(f"    {net:15s}: {n_frags} LVS fragments, "
              f"{len(pins)} HAS_LOW gate pins: {', '.join(pins[:4])}")
    print()

if hl_only:
    print("  ── HAS_LOW-only: these nets are NOT fragmented in LVS (OK) ──")
    for net in sorted(hl_only):
        pins = has_low_no_via2_pins[net]
        print(f"    {net:15s}: {len(pins)} gate pins: {', '.join(pins[:4])}")
    print()

if lvs_only:
    print(f"  ── LVS-only: {len(lvs_only)} fragmented nets NOT in HAS_LOW-no-Via2 ──")
    print(f"     (These are likely from the 35 SKIPPED pins or other causes)")
    for net in sorted(lvs_only):
        n_frags = len(gate_frags[net])
        print(f"    {net:15s}: {n_frags} LVS fragments")
    print()

# ── M1/M2 connectivity analysis for intersection nets ──────────────
if intersection:
    print("=" * 85)
    print("M1/M2 ROUTING CONNECTIVITY for INTERSECTION nets")
    print("  Is the M1/M2 routing graph internally connected?")
    print("=" * 85)
    print()

    for net_name in sorted(intersection):
        route = sroutes[net_name]
        segs = route['segments']

        # Collect M1 and M2 wire segments (not vias)
        m1_segs = [(s[0], s[1], s[2], s[3]) for s in segs if s[4] == M1_LYR]
        m2_segs = [(s[0], s[1], s[2], s[3]) for s in segs if s[4] == M2_LYR]
        via1_pts = [(s[0], s[1]) for s in segs if s[4] == -1]
        m3_segs = [(s[0], s[1], s[2], s[3]) for s in segs if s[4] == 2]
        m4_segs = [(s[0], s[1], s[2], s[3]) for s in segs if s[4] == 3]

        # Build connectivity graph using Union-Find
        parent = {}

        def find(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Each segment connects its two endpoints
        all_points = set()
        for x1, y1, x2, y2 in m1_segs + m2_segs + m3_segs + m4_segs:
            p1 = (x1, y1)
            p2 = (x2, y2)
            all_points.add(p1)
            all_points.add(p2)
            union(p1, p2)

        # Via1 connects M1 and M2 at the same point
        for vx, vy in via1_pts:
            pt = (vx, vy)
            all_points.add(pt)
            # Connect to any M1/M2 endpoint within wire half-width
            for x1, y1, x2, y2 in m1_segs + m2_segs:
                for px, py in ((x1, y1), (x2, y2)):
                    if abs(px - vx) <= _wire_hw and abs(py - vy) <= _wire_hw:
                        union(pt, (px, py))

        # Also connect wire endpoints that overlap (within wire width)
        all_endpoints = list(all_points)
        for i in range(len(all_endpoints)):
            for j in range(i + 1, len(all_endpoints)):
                px1, py1 = all_endpoints[i]
                px2, py2 = all_endpoints[j]
                if abs(px1 - px2) <= _wire_hw and abs(py1 - py2) <= _wire_hw:
                    union(all_endpoints[i], all_endpoints[j])

        # Count connected components
        roots = set(find(p) for p in all_points)
        n_components = len(roots)

        # Also count how many gate APs are in each component
        gate_pins = [p for p in route['pins'] if '.G' in p]
        ap_components = {}
        for pin_key in gate_pins:
            ap = aps.get(pin_key)
            if not ap:
                continue
            ap_x, ap_y = ap['x'], ap['y']
            # Find which component this AP belongs to
            best_pt = None
            best_d = float('inf')
            for px, py in all_points:
                d = abs(px - ap_x) + abs(py - ap_y)
                if d < best_d:
                    best_d = d
                    best_pt = (px, py)
            if best_pt and best_d < 1000:
                comp = find(best_pt)
                ap_components.setdefault(comp, []).append(pin_key)

        n_ap_components = len(ap_components)

        status = "CONNECTED" if n_components <= 1 else f"FRAGMENTED ({n_components} components)"
        ap_status = ("all in 1 component" if n_ap_components <= 1
                     else f"gates in {n_ap_components} components")

        print(f"  {net_name:15s}: M1={len(m1_segs)} M2={len(m2_segs)} "
              f"Via1={len(via1_pts)} M3={len(m3_segs)} M4={len(m4_segs)} | "
              f"graph: {status} | {ap_status}")

        if n_ap_components > 1:
            for comp, pins in sorted(ap_components.items(),
                                     key=lambda x: -len(x[1])):
                print(f"    component: {', '.join(pins)}")

    print()

# ── Also classify the 35 SKIPPED pins' nets vs LVS ─────────────────
# (Quick check to confirm they account for the LVS-only nets)
print("=" * 85)
print("SKIPPED PINS NET COVERAGE")
print("=" * 85)
print()

# Replay SKIPPED classification (simplified — just check net names)
skipped_nets = {
    'f_exc', 'ref_I', 'vco_out', 'vco5', 'freq_sel', 'f_exc_d',
    'comp_outp', 'comp_clk', 'lat_qb', 'lat_q', 'mid_p', 'vco4',
    'bias_n', 'div2_I', 'div2_I_b', 'div2_Q_b', 'div4_I', 'div4_I_b',
    'div8', 'div8_b', 'db1', 'ota_out', 'vco_b',
}

skip_in_lvs = skipped_nets & lvs_frag_nets
skip_not_in_lvs = skipped_nets - lvs_frag_nets

print(f"  SKIPPED nets in LVS fragmented:     {len(skip_in_lvs)}")
print(f"  SKIPPED nets NOT in LVS fragmented: {len(skip_not_in_lvs)}")
if skip_not_in_lvs:
    print(f"    Not fragmented: {', '.join(sorted(skip_not_in_lvs))}")
print()

# ── Grand summary ──────────────────────────────────────────────────
all_problem_nets = has_low_no_via2_nets | skipped_nets
covered = all_problem_nets & lvs_frag_nets
uncovered = lvs_frag_nets - all_problem_nets

print("=" * 85)
print("GRAND SUMMARY: Do the two problem categories cover all LVS fragmented nets?")
print("=" * 85)
print()
print(f"  LVS fragmented nets:                     {len(lvs_frag_nets)}")
print(f"  Covered by HAS_LOW-no-Via2 OR SKIPPED:   {len(covered)}")
print(f"  UNCOVERED (unexplained fragmentation):   {len(uncovered)}")
if uncovered:
    print(f"    Unexplained: {', '.join(sorted(uncovered))}")
