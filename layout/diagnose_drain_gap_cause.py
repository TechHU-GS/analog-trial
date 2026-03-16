#!/usr/bin/env python3
"""Identify what AP obstacle causes the drain bus gap for pmos_cs8.

For each pmos_cs8, traces the drain bus position (after tie pushdown)
and identifies which AP obstacle(s) cause the gap cut.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_drain_gap_cause.py
"""
import os, json, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, '.')
from atk.device import get_sd_strips, get_pcell_params
from atk.pdk import s5, M1_MIN_S

BUS_W = 160
BUS_GAP = 200

with open('placement.json') as f:
    placement = json.load(f)
with open('atk/data/device_lib.json') as f:
    dev_lib = json.load(f)
with open('netlist.json') as f:
    netlist = json.load(f)
with open('output/routing_optimized.json') as f:
    routing = json.load(f)

# Build pin→net
pin_net = {}
for ne in netlist.get('nets', []):
    for pin in ne['pins']:
        pin_net[pin] = ne['name']

# Build AP M1 obstacles (same logic as assemble_gds.py)
ap_m1_obs = []
for key, ap in routing.get('access_points', {}).items():
    net = pin_net.get(key, '')
    if not net:
        continue
    stub = ap.get('m1_stub')
    if stub:
        ap_m1_obs.append((stub[0], stub[1], stub[2], stub[3], net, key+':stub'))
    vp = ap.get('via_pad', {})
    if 'm1' in vp:
        r = vp['m1']
        ap_m1_obs.append((r[0], r[1], r[2], r[3], net, key+':vpad'))

# Build tie M1 bars (from placement.json)
tie_m1_bars = []
instances = placement['instances']
for iname, idata in instances.items():
    if 'tie' not in idata.get('type', ''):
        continue
    m1_bar = idata.get('m1_bar')
    if m1_bar:
        tie_m1_bars.append(tuple(m1_bar))

print(f"AP M1 obstacles: {len(ap_m1_obs)}")
print(f"Tie M1 bars: {len(tie_m1_bars)}")

# Process pmos_cs8 and nmos_bias8 devices
devices = netlist['devices']
for d in devices:
    name = d['name']
    dtype = d['type']
    if dtype not in dev_lib:
        continue
    if 'cs8' not in dtype and 'bias8' not in dtype:
        continue

    lib = dev_lib[dtype]
    ng = lib['params'].get('ng', 1)
    sd = get_sd_strips(dev_lib, dtype)
    if sd is None:
        continue
    inst = instances.get(name)
    if not inst:
        continue

    params = get_pcell_params(dev_lib, dtype)
    pcell_x = s5(inst['x_um'] - params['ox'])
    pcell_y = s5(inst['y_um'] - params['oy'])

    drn_strips = sd['drain']
    src_strips = sd['source']
    strip_bot = src_strips[0][1]

    # Drain bus initial position
    by2_init = pcell_y + strip_bot - BUS_GAP
    bx1 = pcell_x + drn_strips[0][0]
    bx2 = pcell_x + drn_strips[-1][2]

    # Simulate tie pushdown
    by2 = by2_init
    pushed_by_ties = []
    for txl, tyb, txr, tyt in tie_m1_bars:
        if bx2 <= txl or bx1 >= txr:
            continue
        if tyb < by2 + M1_MIN_S and tyt > by2 - BUS_W - M1_MIN_S:
            needed = tyb - M1_MIN_S - BUS_W
            if needed < by2 - BUS_W:
                pushed_by_ties.append((txl, tyb, txr, tyt, by2, needed + BUS_W))
                by2 = ((needed + BUS_W) // 5) * 5
    by1 = by2 - BUS_W

    bus_net = pin_net.get(f'{name}.D', '')

    print(f"\n{'='*70}")
    print(f"{name} ({dtype} ng={ng})")
    print(f"  pcell: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f})")
    print(f"  drain bus initial Y: {by2_init/1e3:.3f} → pushed to {by2/1e3:.3f}"
          f" (delta={(by2_init-by2)/1e3:.3f}µm)")
    print(f"  drain bus X: {bx1/1e3:.3f}-{bx2/1e3:.3f}")
    print(f"  drain bus Y: {by1/1e3:.3f}-{by2/1e3:.3f}")
    print(f"  bus_net: {bus_net}")

    if pushed_by_ties:
        print(f"  Tie pushdowns:")
        for txl, tyb, txr, tyt, old_by2, new_by2 in pushed_by_ties:
            print(f"    tie ({txl/1e3:.1f},{tyb/1e3:.1f})-({txr/1e3:.1f},{tyt/1e3:.1f})"
                  f" pushed by2 {old_by2}→{new_by2}")

    # Check AP obstacles at ACTUAL drain bus position
    gaps = []
    for sxl, syb, sxr, syt, snet, skey in ap_m1_obs:
        if snet == bus_net:
            continue  # same net, no gap needed
        if syt <= by1 or syb >= by2:
            continue  # no Y overlap
        if sxr <= bx1 or sxl >= bx2:
            continue  # no X overlap
        gap_l = sxl - M1_MIN_S
        gap_r = sxr + M1_MIN_S
        gaps.append((gap_l, gap_r, skey, snet))
        print(f"  *** AP OBSTACLE: ({sxl/1e3:.3f},{syb/1e3:.3f})-({sxr/1e3:.3f},{syt/1e3:.3f})"
              f" net={snet} gap=({gap_l/1e3:.3f},{gap_r/1e3:.3f}) [{skey}]")

    if not gaps:
        print(f"  No AP obstacles → drain bus intact")
    else:
        # Show which drain strip pairs get split
        gaps_merged = sorted(gaps, key=lambda x: x[0])
        merged_g = [list(gaps_merged[0][:2])]
        for gl, gr, _, _ in gaps_merged[1:]:
            if gl <= merged_g[-1][1]:
                merged_g[-1][1] = max(merged_g[-1][1], gr)
            else:
                merged_g.append([gl, gr])

        for i in range(len(drn_strips) - 1):
            d_right = pcell_x + drn_strips[i][2]
            d_left = pcell_x + drn_strips[i + 1][0]
            for gl, gr in merged_g:
                if gl <= d_right and gr >= d_left:
                    print(f"  → D{i*2+1}↔D{(i+1)*2+1} SPLIT by gap"
                          f" (gap={gl/1e3:.3f}-{gr/1e3:.3f},"
                          f" strip span={d_right/1e3:.3f}-{d_left/1e3:.3f})")
                    break

    # Also check: what obstacles exist at INITIAL position?
    init_gaps = []
    init_by1 = by2_init - BUS_W
    init_by2 = by2_init
    for sxl, syb, sxr, syt, snet, skey in ap_m1_obs:
        if snet == bus_net:
            continue
        if syt <= init_by1 or syb >= init_by2:
            continue
        if sxr <= bx1 or sxl >= bx2:
            continue
        init_gaps.append(skey)

    if not init_gaps and gaps:
        print(f"  ** Initial position ({init_by1/1e3:.3f}-{init_by2/1e3:.3f}) has NO obstacles!"
              f" Pushdown caused the split.")
    elif init_gaps:
        print(f"  Initial position also had obstacles: {init_gaps}")
