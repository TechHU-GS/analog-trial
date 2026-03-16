#!/usr/bin/env python3
"""Identify what M3 obstacles block bus M3 bridge for specific stages."""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open('output/routing.json') as f:
    routing = json.load(f)
aps = routing.get('access_points', {})

from atk.pdk import (M3_MIN_W, M3_MIN_S, VIA2_PAD_M3, VIA3_PAD,
                      M1_SIG_W, VIA1_PAD)
from atk.route.maze_router import M3_LYR

# Load netlist for pin→net mapping
with open('netlist.json') as f:
    netlist = json.load(f)
pin_net = {}
for ne in netlist.get('nets', []):
    for pin in ne.get('pins', []):
        pin_net[pin] = ne['name']

# Build M3 obstacle list (mirrors assemble_gds.py)
m3_obs = []
for rd_name in ('signal_routes', 'pre_routes'):
    for vnet, rd in routing.get(rd_name, {}).items():
        for seg in rd.get('segments', []):
            lyr = seg[4]
            if lyr == M3_LYR:
                x1, y1, x2, y2 = seg[:4]
                hw = M3_MIN_W // 2
                if x1 == x2:
                    m3_obs.append((x1 - hw, min(y1, y2), x1 + hw, max(y1, y2), vnet))
                else:
                    m3_obs.append((min(x1, x2), y1 - hw, max(x1, x2), y1 + hw, vnet))
            elif lyr == -2:  # Via2
                hp3 = VIA2_PAD_M3 // 2
                m3_obs.append((seg[0] - hp3, seg[1] - hp3,
                               seg[0] + hp3, seg[1] + hp3, vnet))
            elif lyr == -3:  # Via3
                hp3 = VIA3_PAD // 2
                m3_obs.append((seg[0] - hp3, seg[1] - hp3,
                               seg[0] + hp3, seg[1] + hp3, vnet))
for rail_id, rail in routing.get('power', {}).get('rails', {}).items():
    rnet = rail.get('net', rail_id)
    hw = rail['width'] // 2
    m3_obs.append((rail['x1'], rail['y'] - hw, rail['x2'], rail['y'] + hw, rnet))
for drop in routing.get('power', {}).get('drops', []):
    vb = drop.get('m3_vbar')
    if vb:
        hw = M3_MIN_W // 2
        m3_obs.append((vb[0] - hw, min(vb[1], vb[3]),
                       vb[0] + hw, max(vb[1], vb[3]), drop['net']))

# For stages 1, 3 (M3 blocked), show what blocks the M3 bridge
# d1_cx and d2_cx are Mpb drain strip centers
# bus_cy ≈ 175095 for all stages
import klayout.db as kdb
from atk.device import load_device_lib, get_sd_strips
from atk.paths import DEVICE_LIB_JSON

device_lib = load_device_lib(DEVICE_LIB_JSON)

with open('placement.json') as f:
    placement = json.load(f)

from atk.device import get_pcell_params
DEVICES = {dt: get_pcell_params(device_lib, dt) for dt in device_lib}

def s5(um):
    return round(um * 1000 / 5) * 5

for stage in [1, 2, 3, 4, 5]:
    inst = f'Mpb{stage}'
    info = placement.get('instances', {}).get(inst)
    if not info:
        continue
    dev_type = 'pmos_cs8'
    dev = DEVICES[dev_type]
    pcell_x = s5(info['x_um'] - dev['ox'])
    pcell_y = s5(info['y_um'] - dev['oy'])
    sd = get_sd_strips(device_lib, dev_type)
    if not sd:
        continue

    drn_strips = sd['drain']
    src_strips = sd['source']
    strip_bot = src_strips[0][1]

    bus_net = pin_net.get(f'{inst}.D', '')

    # Check which drain strip pairs have M2 bridge segments
    # (simplified: check all adjacent pairs)
    mpu_d = aps.get(f'Mpu{stage}.D')
    if mpu_d:
        print(f"\n--- Stage {stage}: {inst} at ({info['x_um']},{info['y_um']})")
        print(f"  Drain strips: {len(drn_strips)}")
        for di, ds in enumerate(drn_strips):
            cx = pcell_x + (ds[0] + ds[2]) // 2
            print(f"    D{di}: cx={cx} (local {ds})")
        mx, my = mpu_d['x'], mpu_d['y']
        print(f"  Mpu{stage}.D: ({mx},{my})")

    for di in range(len(drn_strips) - 1):
        d1_cx = pcell_x + (drn_strips[di][0] + drn_strips[di][2]) // 2
        d2_cx = pcell_x + (drn_strips[di+1][0] + drn_strips[di+1][2]) // 2

        # Check if Mpu AP falls within this span
        mpu_d = aps.get(f'Mpu{stage}.D')
        if not mpu_d:
            continue
        mx, my = mpu_d['x'], mpu_d['y']
        m2hp = VIA1_PAD // 2

        # bus_cy: approximate as Mpu AP Y
        bus_cy = my  # rough approximation

        # M2 bar
        m2_bar = (d1_cx, bus_cy - m2hp, d2_cx, bus_cy + m2hp)
        # AP M2 pad
        ap_m2 = (mx - m2hp, my - m2hp, mx + m2hp, my + m2hp)
        # Check overlap
        if not (ap_m2[2] > m2_bar[0] and ap_m2[0] < m2_bar[2] and
                ap_m2[3] > m2_bar[1] and ap_m2[1] < m2_bar[3]):
            continue  # no conflict

        # M3 bridge bar
        m3hw = M1_SIG_W // 2
        m3_bar_xl = d1_cx - VIA2_PAD_M3 // 2
        m3_bar_yb = bus_cy - m3hw
        m3_bar_xr = d2_cx + VIA2_PAD_M3 // 2
        m3_bar_yt = bus_cy + m3hw
        s = M3_MIN_S

        print(f"\n{'='*70}")
        print(f"Stage {stage}: {inst} drain strip pair D{di}-D{di+1}")
        print(f"  d1_cx={d1_cx}, d2_cx={d2_cx}, bus_cy={bus_cy}")
        print(f"  M2 bar: ({m2_bar[0]},{m2_bar[1]};{m2_bar[2]},{m2_bar[3]})")
        print(f"  M3 bridge: ({m3_bar_xl},{m3_bar_yb};{m3_bar_xr},{m3_bar_yt})")
        print(f"  bus_net={bus_net}")
        print(f"  Mpu{stage}.D AP: ({mx},{my}), net=vco{stage}")

        # Find blocking M3 obstacles
        blockers = []
        for ox1, oy1, ox2, oy2, onet in m3_obs:
            if onet == bus_net:
                continue
            if (m3_bar_xr + s > ox1 and m3_bar_xl - s < ox2 and
                    m3_bar_yt + s > oy1 and m3_bar_yb - s < oy2):
                blockers.append((ox1, oy1, ox2, oy2, onet))

        if blockers:
            print(f"  M3 BLOCKED by {len(blockers)} obstacles:")
            for ox1, oy1, ox2, oy2, onet in blockers:
                print(f"    ({ox1},{oy1};{ox2},{oy2}) net={onet} "
                      f"{ox2-ox1}x{oy2-oy1}")
        else:
            print(f"  M3 CLEAR")

print("\nDone.")
