#!/usr/bin/env python3
"""Show bus obstacle analysis for each ng>=4 device.

For each device, compute:
1. Source bus position (above) — currently S2-S8, proposed S0-S8
2. Drain bus position (below)
3. Which _ap_m1_obs entries overlap each bus → gap analysis

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_bus_obstacles.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, '.')
from atk.device import get_sd_strips, get_pcell_params
from atk.pdk import s5

# Constants (must match assemble_gds.py)
M1_MIN_S = 180
BUS_W = 160     # M1_THIN
BUS_GAP = 200

with open('placement.json') as f:
    placement = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)
with open('netlist.json') as f:
    netlist_data = json.load(f)
with open('output/routing_optimized.json') as f:
    routing = json.load(f)

# Build pin→net mapping
pin_net = {}
for ne in netlist_data.get('nets', []):
    for pin in ne['pins']:
        pin_net[pin] = ne['name']

# Build _ap_m1_obs exactly as assemble_gds.py does
ap_m1_obs = []  # (xl, yb, xr, yt, net, key)
for key, ap in routing.get('access_points', {}).items():
    net = pin_net.get(key, '')
    if not net:
        continue
    stub = ap.get('m1_stub')
    if stub:
        ap_m1_obs.append((stub[0], stub[1], stub[2], stub[3], net, key + ':stub'))
    vp = ap.get('via_pad', {})
    if 'm1' in vp:
        r = vp['m1']
        ap_m1_obs.append((r[0], r[1], r[2], r[3], net, key + ':vpad'))

print(f"Total AP M1 obstacles: {len(ap_m1_obs)}")

devices = netlist_data['devices']

for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        continue
    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)
    if ng < 4:  # only ng>=4 for this analysis
        continue

    strips = get_sd_strips(dev_lib, dtype)
    if strips is None:
        continue
    inst = placement['instances'].get(name)
    if not inst:
        continue

    params = get_pcell_params(dev_lib, dtype)
    pcell_x = s5(inst['x_um'] - params['ox'])
    pcell_y = s5(inst['y_um'] - params['oy'])

    src_strips = strips['source']
    drn_strips = strips['drain']

    # Compute strip_top and strip_bot (PCell-local nm)
    all_strip_ys = [s[1] for s in src_strips + drn_strips] + \
                   [s[3] for s in src_strips + drn_strips]
    strip_top = max(all_strip_ys)
    strip_bot = min(all_strip_ys)

    # Source bus above (current: S2-S8, proposed: S0-S8)
    bus_src_current = src_strips[1:]  # current
    bus_src_proposed = src_strips     # proposed

    src_bus_y1 = pcell_y + strip_top + BUS_GAP  # bus bottom
    src_bus_y2 = src_bus_y1 + BUS_W              # bus top

    # Source bus X ranges
    src_bx1_curr = pcell_x + bus_src_current[0][0]
    src_bx2_curr = pcell_x + bus_src_current[-1][2]
    src_bx1_prop = pcell_x + bus_src_proposed[0][0]
    src_bx2_prop = pcell_x + bus_src_proposed[-1][2]

    # Drain bus below
    drn_bus_y2 = pcell_y + strip_bot - BUS_GAP  # bus top
    drn_bus_y1 = drn_bus_y2 - BUS_W              # bus bottom
    drn_bx1 = pcell_x + drn_strips[0][0]
    drn_bx2 = pcell_x + drn_strips[-1][2]

    # Get source and drain nets
    src_net = pin_net.get(f'{name}.S', '') or pin_net.get(f'{name}.S2', '')
    drn_net = pin_net.get(f'{name}.D', '')

    print(f"\n{'='*70}")
    print(f"{name} ({dtype} ng={ng})")
    print(f"  pcell_origin: ({pcell_x}, {pcell_y})")
    print(f"  strip_bot={strip_bot} strip_top={strip_top}")
    print(f"  src_net={src_net}  drn_net={drn_net}")

    # Source strips
    print(f"\n  Source strips ({len(src_strips)}):")
    for i, s in enumerate(src_strips):
        gx1, gx2 = pcell_x + s[0], pcell_x + s[2]
        print(f"    S{i*2}: x={gx1/1e3:.3f}-{gx2/1e3:.3f}")

    print(f"\n  Drain strips ({len(drn_strips)}):")
    for i, s in enumerate(drn_strips):
        gx1, gx2 = pcell_x + s[0], pcell_x + s[2]
        print(f"    D{i*2+1}: x={gx1/1e3:.3f}-{gx2/1e3:.3f}")

    # Check source bus obstacles (proposed: S0-S8)
    print(f"\n  SOURCE BUS ABOVE: Y={src_bus_y1/1e3:.1f}-{src_bus_y2/1e3:.1f}")
    print(f"    Current  X: {src_bx1_curr/1e3:.1f}-{src_bx2_curr/1e3:.1f} (S2-S8)")
    print(f"    Proposed X: {src_bx1_prop/1e3:.1f}-{src_bx2_prop/1e3:.1f} (S0-S8)")

    src_bus_gaps = []
    for sxl, syb, sxr, syt, snet, skey in ap_m1_obs:
        if snet == src_net:
            continue
        if syt <= src_bus_y1 or syb >= src_bus_y2:
            continue
        if sxr <= src_bx1_prop or sxl >= src_bx2_prop:
            continue
        gap_l = sxl - M1_MIN_S
        gap_r = sxr + M1_MIN_S
        src_bus_gaps.append((gap_l, gap_r, skey, snet))
        in_s0_region = gap_l < src_bx1_curr  # affects S0→S2 span
        print(f"    OBSTACLE: x={sxl/1e3:.3f}-{sxr/1e3:.3f} net={snet} "
              f"gap=({gap_l/1e3:.3f},{gap_r/1e3:.3f}) "
              f"{'*** IN S0-S2 REGION ***' if in_s0_region else ''} [{skey}]")

    if not src_bus_gaps:
        print(f"    No obstacles → S0 can be included!")

    # Simulate gap cutting for proposed bus
    if src_bus_gaps:
        gaps = [(gl, gr) for gl, gr, _, _ in src_bus_gaps]
        gaps.sort()
        merged = [list(gaps[0])]
        for gl, gr in gaps[1:]:
            if gl <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], gr)
            else:
                merged.append([gl, gr])

        # Check if S0 is isolated (gap spans entire S0-to-S2 region)
        s0_x = pcell_x + src_strips[0][2]  # S0 right edge
        s2_x = pcell_x + src_strips[1][0]  # S2 left edge (next source strip)
        s0_isolated = False
        for gl, gr in merged:
            if gl <= s0_x and gr >= s2_x:
                s0_isolated = True
                break
        if s0_isolated:
            print(f"    → S0 WOULD BE ISOLATED by gap (gap spans S0-S2)")
        else:
            print(f"    → S0 would have bus segment (gap does NOT span S0-S2)")

    # Check drain bus obstacles
    print(f"\n  DRAIN BUS BELOW: Y={drn_bus_y1/1e3:.1f}-{drn_bus_y2/1e3:.1f}")
    print(f"    X: {drn_bx1/1e3:.1f}-{drn_bx2/1e3:.1f} (D1-D_last)")

    drn_bus_gaps = []
    for sxl, syb, sxr, syt, snet, skey in ap_m1_obs:
        if snet == drn_net:
            continue
        if syt <= drn_bus_y1 or syb >= drn_bus_y2:
            continue
        if sxr <= drn_bx1 or sxl >= drn_bx2:
            continue
        gap_l = sxl - M1_MIN_S
        gap_r = sxr + M1_MIN_S
        drn_bus_gaps.append((gap_l, gap_r, skey, snet))
        print(f"    OBSTACLE: x={sxl/1e3:.3f}-{sxr/1e3:.3f} net={snet} "
              f"gap=({gap_l/1e3:.3f},{gap_r/1e3:.3f}) [{skey}]")

    if not drn_bus_gaps:
        print(f"    No obstacles → drain bus intact")
    else:
        # Check which drain strips are isolated
        gaps = [(gl, gr) for gl, gr, _, _ in drn_bus_gaps]
        gaps.sort()
        merged_d = [list(gaps[0])]
        for gl, gr in gaps[1:]:
            if gl <= merged_d[-1][1]:
                merged_d[-1][1] = max(merged_d[-1][1], gr)
            else:
                merged_d.append([gl, gr])

        # Check connectivity between consecutive drain strips
        for i in range(len(drn_strips) - 1):
            d_right = pcell_x + drn_strips[i][2]  # right edge of strip i
            d_left = pcell_x + drn_strips[i + 1][0]  # left edge of strip i+1
            split = False
            for gl, gr in merged_d:
                if gl <= d_right and gr >= d_left:
                    split = True
                    break
            if split:
                print(f"    → D{i*2+1}↔D{(i+1)*2+1} SPLIT by gap!")
