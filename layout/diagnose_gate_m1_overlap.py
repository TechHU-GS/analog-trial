#!/usr/bin/env python3
"""GDS probe: verify gate M1 pad vs routing M1 wire overlap.

For each sample failing gate:
1. Finds the gate pin position from routing.json
2. Lists ALL M1 shapes within 2µm from the GDS
3. Identifies the gate contact M1 pad (contains pin center)
4. Checks which other M1 shapes overlap/touch the gate pad
5. Traces connectivity cluster (shapes connected via overlap)

Usage:
    cd layout && python3 diagnose_gate_m1_overlap.py
"""
import os
import json
import gdstk

os.chdir(os.path.dirname(os.path.abspath(__file__)))

GDS_FILE = 'output/ptat_vco.gds'
M1_LAYER = 8
M1_DTYPE = 0

# Representative failing gates — using routing.json pin names
# (pin_name, ref_net, ext_net, circuit_block)
SAMPLE_GATES = [
    ('MN1.G',         'net_c1',    '$182',   'PTAT mirror diode'),
    ('PM3.G',         'net_c1',    '$182',   'PTAT mirror diode'),
    ('PM_mir2.G',     'net_c1',    '$150',   'PTAT mirror 2'),
    ('Mtail.G',       'bias_n',    '$35',    'tail bias'),
    ('T1I_m2.G',      'vco_out',   '$264',   'TFF T1I'),
    ('Mc_tail.G',     'comp_clk',  '$131',   'comparator'),
    ('Mdac_tg1n.G',   'lat_q',     '$108',   'DAC TG'),
    ('Mchop1p.G',     'f_exc_b',   '$8',     'chopper'),
    ('MBp2.G',        'buf1',      '$227',   'VCO buffer'),
    ('MBn2.G',        'buf1',      '$223',   'VCO buffer n'),
    ('T2I_m1.G',      'div2_I_b',  't2I_mb', 'TFF T2I'),
    ('MXfi_n1.G',     'freq_sel',  '$505',   'MUX fi'),
    ('Mp_load_n.G',   'mid_p',     '$80',    'OTA load'),
]

# ── Load routing data ─────────────────────────────────────────────────

with open('output/routing.json') as f:
    routing = json.load(f)
aps = routing['access_points']

# Build M1 wire index from routing
route_m1_wires = {}  # net -> [(x1, y1, x2, y2)]
M1_HW = 150  # half-width for M1 signal wires

for net_name, route in routing['signal_routes'].items():
    wires = []
    for seg in route['segments']:
        x1, y1, x2, y2, lyr = seg
        if lyr == 1:  # M1
            wires.append((x1, y1, x2, y2))
    if wires:
        route_m1_wires[net_name] = wires

# ── Load GDS M1 shapes ───────────────────────────────────────────────

lib = gdstk.read_gds(GDS_FILE)
top = [c for c in lib.top_level() if c.name == 'ptat_vco']
cell = top[0] if top else lib.top_level()[0]

# Determine scale (µm→nm)
sample = [p for p in cell.polygons if p.layer == M1_LAYER][:1]
if sample:
    max_c = max(abs(v) for pt in sample[0].points for v in pt)
    SCALE = 1 if max_c > 1000 else 1000
else:
    SCALE = 1000

m1_shapes = []
for poly in cell.polygons:
    if poly.layer == M1_LAYER and poly.datatype == M1_DTYPE:
        pts = poly.points
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        m1_shapes.append((
            int(round(min(xs) * SCALE)),
            int(round(min(ys) * SCALE)),
            int(round(max(xs) * SCALE)),
            int(round(max(ys) * SCALE)),
        ))

print(f"GDS: {len(m1_shapes)} M1 shapes (scale={SCALE})")
print()


def shapes_near(cx, cy, radius=2000):
    """Return M1 shapes within radius of point."""
    return [(x1, y1, x2, y2) for x1, y1, x2, y2 in m1_shapes
            if x2 >= cx - radius and x1 <= cx + radius
            and y2 >= cy - radius and y1 <= cy + radius]


def shapes_overlap(a, b):
    """Check if two bboxes overlap (share area, not just edge)."""
    return (a[0] < b[2] and a[2] > b[0] and
            a[1] < b[3] and a[3] > b[1])


def gap_between(a, b):
    """Compute gap between two bboxes. 0 if touching/overlapping."""
    dx = max(0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0, max(a[1] - b[3], b[1] - a[3]))
    return max(dx, dy)


def find_cluster(shapes, seed_idx):
    """BFS to find all shapes connected (overlapping) to seed."""
    visited = {seed_idx}
    queue = [seed_idx]
    while queue:
        i = queue.pop(0)
        for j, s in enumerate(shapes):
            if j not in visited and shapes_overlap(shapes[i], s):
                visited.add(j)
                queue.append(j)
    return visited


def wire_bbox(x1, y1, x2, y2, hw=M1_HW):
    """Convert wire centerline to bbox."""
    if x1 == x2:  # vertical
        return (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
    else:  # horizontal
        return (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)


# ── Probe each sample gate ───────────────────────────────────────────

print("=" * 80)
print("GATE M1 CONNECTIVITY PROBE")
print("=" * 80)

results = []  # (pin, status)

for pin_name, ref_net, ext_net, block in SAMPLE_GATES:
    print(f"\n{'─'*70}")
    print(f"  {pin_name}  ref_net={ref_net}  ext={ext_net}  [{block}]")
    print(f"{'─'*70}")

    ap = aps.get(pin_name)
    if not ap:
        print(f"  ⚠ Pin not found in routing access_points!")
        results.append((pin_name, 'NOT_FOUND'))
        continue

    px, py = ap['x'], ap['y']
    mode = ap.get('mode', '?')
    ap_m1 = ap.get('via_pad', {}).get('m1')

    print(f"  Pin: ({px}, {py}) mode={mode}")
    if ap_m1:
        print(f"  AP M1 pad: [{ap_m1[0]}, {ap_m1[1]}, {ap_m1[2]}, {ap_m1[3]}]"
              f"  ({ap_m1[2]-ap_m1[0]}×{ap_m1[3]-ap_m1[1]})")

    # Get all GDS M1 shapes within 2µm
    nearby = shapes_near(px, py, 2000)
    print(f"  GDS M1 within 2µm: {len(nearby)} shapes")

    # List all nearby shapes with distance to pin center
    for i, s in enumerate(nearby):
        w = s[2] - s[0]
        h = s[3] - s[1]
        contains_pin = (s[0] <= px <= s[2] and s[1] <= py <= s[3])
        gap = gap_between((px, py, px, py), s)
        label = " ◄ GATE PAD" if contains_pin else ""
        print(f"    [{i}] [{s[0]:6d},{s[1]:6d},{s[2]:6d},{s[3]:6d}]"
              f"  {w:4d}×{h:4d}  gap={gap:5d}{label}")

    # Find the gate pad (M1 shape containing pin center)
    gate_pad_idx = None
    gate_pad = None
    for i, s in enumerate(nearby):
        if s[0] <= px <= s[2] and s[1] <= py <= s[3]:
            if gate_pad is None:
                gate_pad_idx = i
                gate_pad = s
            else:
                # Pick smaller shape
                area_old = (gate_pad[2]-gate_pad[0]) * (gate_pad[3]-gate_pad[1])
                area_new = (s[2]-s[0]) * (s[3]-s[1])
                if area_new < area_old:
                    gate_pad_idx = i
                    gate_pad = s

    if gate_pad is None:
        print(f"  ✗ NO M1 at gate pin center!")
        results.append((pin_name, 'NO_PAD'))
        continue

    # Find connectivity cluster containing the gate pad
    cluster = find_cluster(nearby, gate_pad_idx)
    cluster_shapes = [nearby[i] for i in cluster]
    non_gate_in_cluster = [nearby[i] for i in cluster if i != gate_pad_idx]

    print(f"  Gate pad cluster: {len(cluster)} shapes"
          f" (gate pad + {len(non_gate_in_cluster)} others)")

    if not non_gate_in_cluster:
        print(f"  ✗ GATE PAD IS ISOLATED — no M1 overlaps it!")
        # Find nearest non-gate M1
        best_gap = 99999
        best_shape = None
        for i, s in enumerate(nearby):
            if i == gate_pad_idx:
                continue
            g = gap_between(gate_pad, s)
            if g < best_gap:
                best_gap = g
                best_shape = s
        if best_shape:
            sw = best_shape[2] - best_shape[0]
            sh = best_shape[3] - best_shape[1]
            print(f"  Nearest M1: [{best_shape[0]},{best_shape[1]},"
                  f"{best_shape[2]},{best_shape[3]}]"
                  f" ({sw}×{sh}) gap={best_gap}nm")
        results.append((pin_name, f'ISOLATED gap={best_gap}nm'))
    else:
        # Gate pad touches other M1 shapes — report
        for cs in non_gate_in_cluster:
            cw = cs[2] - cs[0]
            ch = cs[3] - cs[1]
            print(f"    connected: [{cs[0]},{cs[1]},{cs[2]},{cs[3]}]"
                  f" ({cw}×{ch})")
        results.append((pin_name, f'CONNECTED cluster={len(cluster)}'))

    # Check if any routing wire for ref_net is in the cluster
    ref_wires = route_m1_wires.get(ref_net, [])
    wire_in_cluster = False
    for wx1, wy1, wx2, wy2 in ref_wires:
        wb = wire_bbox(wx1, wy1, wx2, wy2)
        for cs in cluster_shapes:
            if shapes_overlap(wb, cs):
                wire_in_cluster = True
                break
        if wire_in_cluster:
            break

    if wire_in_cluster:
        print(f"  ✓ Routing wire for '{ref_net}' IS in the cluster")
    else:
        # Check nearest routing wire distance
        best_dist = 99999
        best_rw = None
        for wx1, wy1, wx2, wy2 in ref_wires:
            wb = wire_bbox(wx1, wy1, wx2, wy2)
            for cs in cluster_shapes:
                g = gap_between(wb, cs)
                if g < best_dist:
                    best_dist = g
                    best_rw = (wx1, wy1, wx2, wy2)
        if best_rw:
            print(f"  ✗ Nearest '{ref_net}' wire: gap={best_dist}nm"
                  f"  wire=({best_rw[0]},{best_rw[1]})->({best_rw[2]},{best_rw[3]})")
        else:
            print(f"  ✗ No routing M1 wires for '{ref_net}' found!")

# ── Summary ───────────────────────────────────────────────────────────

print()
print("=" * 80)
print("PROBE SUMMARY")
print("=" * 80)
print()

isolated = 0
connected = 0
no_pad = 0
for pin, status in results:
    icon = "✗" if 'ISOLATED' in status or 'NO_PAD' in status else "✓"
    if 'ISOLATED' in status:
        isolated += 1
    elif 'CONNECTED' in status:
        connected += 1
    elif 'NO_PAD' in status:
        no_pad += 1
    print(f"  {icon} {pin:20s}  {status}")

print()
print(f"  ISOLATED (gap > 0): {isolated}")
print(f"  CONNECTED:          {connected}")
print(f"  NO M1 PAD:          {no_pad}")
print()
if isolated > connected:
    print("CONFIRMED: Gate M1 pads are systematically isolated from routing wires.")
    print("Root cause is in assemble_gds.py gate contact M1 pad geometry.")
elif connected > isolated:
    print("HYPOTHESIS REJECTED: Gate M1 pads DO overlap with nearby M1.")
    print("The disconnection must come from a DIFFERENT cause.")
    print("Possible causes:")
    print("  - The nearby M1 that touches gate pad is from a DIFFERENT net")
    print("  - The routing wire doesn't match the GDS shape positions")
    print("  - Multi-finger device internal connectivity issue")
