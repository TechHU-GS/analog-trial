#!/usr/bin/env python3
"""Signal router for SoilZ v1 — generate routing candidates on M3+M4+M5.

Layer strategy (verified 2026-03-18):
  M1/M2    — device PCell (don't touch)
  M3       — signal routing (horizontal) + via stack transition
  M4       — signal routing (vertical)
  M5       — signal routing (avoid cap_cmim areas)
  TopMetal1 — power distribution
  TopMetal2 — forbidden (TTIHP)

Pin positions: ATK access_points (x,y) from routing.json.
  These are the M2 pad locations where Via2 can land.
  Verified DRC clean with unstripped PCells (2026-03-18).

Usage:
    cd layout && python3 -m atk.signal_router
"""

import json
import os

# --- Constants (IHP SG13G2 official DRC values) ---
MN_W = 200;  MN_S = 210   # M2-M5 width/space
VN_SZ = 190; VN_S = 220   # Via2-Via4

# Routing wire half-widths
M3_HW = 105   # 210nm wire
M4_HW = 105
M5_HW = 105
VIA_HW = 95   # 190nm via

# Via pad half-sizes (metal enclosure of via: Vn.c1=50nm)
VIA_PAD_HW = 145  # 290nm pad

# Power via stack (TM1→M1)
M5_PAD_HW = 310   # 620nm (TopVia1 enclosure)
TV1_HW = 210      # 420nm TopVia1
TM1_HW = 820      # 1640nm TopMetal1

SCALE = 10  # 1 Magic unit = 10nm

# Magic layer names for .mag files (verified 2026-03-18)
# KLayout uses GDS numbers; Magic uses these paint type names.
MAG_LAYERS = {
    'M1': 'metal1', 'V1': 'via1', 'M2': 'metal2',
    'V2': 'via2', 'M3': 'metal3', 'V3': 'via3',
    'M4': 'metal4', 'V4': 'via4', 'M5': 'metal5',
    'TV1': 'via5',     # NOT topvia1!
    'TM1': 'met6',     # NOT topmetal1!
}


def nm(val):
    return int(round(val / SCALE))


def compute_pin_positions(netlist, access_points):
    """Compute Via2 connection points for all signal nets.

    Uses ATK access_points (x,y) — these are M2 pad centers where
    M1 stub + Via1 + M2 pad already exist. Via2 lands here.

    Returns dict: net_name → list of (x_nm, y_nm, dev_name, pin_name)
    """
    # Build AP lookup: "DevName.Pin" → (x, y)
    ap_lookup = {}
    for key, ap in access_points.items():
        ap_lookup[key] = (ap['x'], ap['y'])

    net_pins = {}

    for net in netlist['nets']:
        net_name = net['name']
        if net_name in ('vdd', 'gnd'):
            continue

        pins = []
        for pk in net['pins']:
            ap = ap_lookup.get(pk)
            if not ap:
                continue
            dev_name = pk.split('.')[0]
            pin_name = pk.split('.')[1] if '.' in pk else ''
            pins.append((ap[0], ap[1], dev_name, pin_name))

        # Deduplicate by position
        seen = set()
        unique = []
        for p in pins:
            key = (p[0], p[1])
            if key not in seen:
                seen.add(key)
                unique.append(p)

        if len(unique) >= 2:
            net_pins[net_name] = unique

    return net_pins


def generate_candidates(net_pins):
    """Generate L-route candidates for each net on M3+M4.

    For a 2-pin net: generates multiple L-route variants.
    For multi-pin nets: uses nearest-neighbor chain, each pair gets L-route.

    Returns dict: net_name → list of candidates
      Each candidate = list of segments: (x1, y1, x2, y2, layer)
        layer: 'M3', 'M4', 'V2', 'V3'
    """
    candidates = {}

    for net_name, pins in net_pins.items():
        net_candidates = []

        if len(pins) == 2:
            # 2-pin net: generate L-route variants
            net_candidates = _l_route_variants(pins[0], pins[1])
        else:
            # Multi-pin: nearest-neighbor chain, then L-route each pair
            net_candidates = _chain_route_variants(pins)

        if net_candidates:
            candidates[net_name] = net_candidates

    return candidates


def _l_route_variants(p1, p2):
    """Generate L-route variants between two pins.

    Returns list of candidates. Each candidate = list of segments.
    """
    x1, y1 = p1[0], p1[1]
    x2, y2 = p2[0], p2[1]
    variants = []

    # Variant A: M3 horizontal first, then M4 vertical
    # Pin1 → Via2 → M3 horizontal → Via3 → M4 vertical → Via3 → M3 → Via2 → Pin2
    segs_a = []
    segs_a.append((x1, y1, x1, y1, 'V2'))       # Via2 at pin1
    segs_a.append((x1, y1, x2, y1, 'M3'))       # M3 horizontal
    segs_a.append((x2, y1, x2, y1, 'V3'))       # Via3 at bend
    segs_a.append((x2, y1, x2, y2, 'M4'))       # M4 vertical
    segs_a.append((x2, y2, x2, y2, 'V3'))       # Via3 at pin2 side
    segs_a.append((x2, y2, x2, y2, 'V2'))       # Via2 at pin2
    # Add M3 pad at pin2 for Via2 landing
    segs_a.append((x2, y2, x2, y2, 'M3'))       # M3 pad at pin2
    variants.append(segs_a)

    # Variant B: M4 vertical first, then M3 horizontal
    segs_b = []
    segs_b.append((x1, y1, x1, y1, 'V2'))
    segs_b.append((x1, y1, x1, y1, 'M3'))       # M3 pad at pin1
    segs_b.append((x1, y1, x1, y1, 'V3'))       # Via3 at pin1
    segs_b.append((x1, y1, x1, y2, 'M4'))       # M4 vertical
    segs_b.append((x1, y2, x1, y2, 'V3'))       # Via3 at bend
    segs_b.append((x1, y2, x2, y2, 'M3'))       # M3 horizontal
    segs_b.append((x2, y2, x2, y2, 'V2'))       # Via2 at pin2
    variants.append(segs_b)

    # Variant C: all M3 (if mostly horizontal, small Y delta)
    if abs(y2 - y1) < 2000:  # < 2um Y delta
        segs_c = []
        segs_c.append((x1, y1, x1, y1, 'V2'))
        segs_c.append((x1, y1, x2, y1, 'M3'))
        segs_c.append((x2, y1, x2, y2, 'M3'))   # short M3 vertical jog
        segs_c.append((x2, y2, x2, y2, 'V2'))
        variants.append(segs_c)

    # Variant D: all M4 (if mostly vertical, small X delta)
    if abs(x2 - x1) < 2000:
        segs_d = []
        segs_d.append((x1, y1, x1, y1, 'V2'))
        segs_d.append((x1, y1, x1, y1, 'M3'))
        segs_d.append((x1, y1, x1, y1, 'V3'))
        segs_d.append((x1, y1, x1, y2, 'M4'))
        segs_d.append((x1, y2, x2, y2, 'M4'))   # short M4 horizontal jog
        segs_d.append((x1, y2, x1, y2, 'V3'))
        segs_d.append((x2, y2, x2, y2, 'M3'))
        segs_d.append((x2, y2, x2, y2, 'V2'))
        variants.append(segs_d)

    return variants


def _chain_route_variants(pins):
    """Generate chain-route variants for multi-pin net.

    Uses nearest-neighbor ordering, then L-routes between consecutive pairs.
    Generates a few variants by trying different chain orderings.
    """
    variants = []

    # Ordering 1: nearest-neighbor from first pin
    for start_idx in range(min(3, len(pins))):
        chain = _nearest_neighbor_chain(pins, start_idx)
        # For each pair in chain, use Variant A (M3-first)
        for layer_first in ['M3', 'M4']:
            segs = []
            for i in range(len(chain) - 1):
                p1, p2 = chain[i], chain[i + 1]
                x1, y1 = p1[0], p1[1]
                x2, y2 = p2[0], p2[1]

                # Via2 at start (only for first pin in chain)
                if i == 0:
                    segs.append((x1, y1, x1, y1, 'V2'))

                if layer_first == 'M3':
                    segs.append((x1, y1, x1, y1, 'M3'))   # M3 pad
                    segs.append((x1, y1, x2, y1, 'M3'))   # horizontal
                    segs.append((x2, y1, x2, y1, 'V3'))   # Via3
                    segs.append((x2, y1, x2, y2, 'M4'))   # vertical
                    segs.append((x2, y2, x2, y2, 'V3'))   # Via3
                    segs.append((x2, y2, x2, y2, 'M3'))   # M3 pad
                else:
                    segs.append((x1, y1, x1, y1, 'M3'))
                    segs.append((x1, y1, x1, y1, 'V3'))
                    segs.append((x1, y1, x1, y2, 'M4'))
                    segs.append((x1, y2, x1, y2, 'V3'))
                    segs.append((x1, y2, x2, y2, 'M3'))

                # Via2 at end pin
                segs.append((x2, y2, x2, y2, 'V2'))

            variants.append(segs)

    return variants


def _nearest_neighbor_chain(pins, start_idx=0):
    """Order pins by nearest-neighbor starting from start_idx."""
    remaining = list(pins)
    chain = [remaining.pop(start_idx)]
    while remaining:
        last = chain[-1]
        best_d = float('inf')
        best_i = 0
        for i, p in enumerate(remaining):
            d = abs(last[0] - p[0]) + abs(last[1] - p[1])
            if d < best_d:
                best_d = d
                best_i = i
        chain.append(remaining.pop(best_i))
    return chain


def build_soilz_mag(genome, netlist, placement, device_lib_magic,
                    access_points, power_drops, candidates, output_dir):
    """Build soilz.mag with devices + APs + power via stacks + selected routes.

    Args:
        genome: dict net_name → candidate index (int)
        output_dir: directory to write soilz.mag and phase_c.tcl
    """
    import time
    instances = placement.get('instances', {})
    mag = ['magic', 'tech ihp-sg13g2', f'timestamp {int(time.time())}']

    # 1. Device instances
    for dev in netlist['devices']:
        name = dev['name']
        dt = dev['type']
        if dt not in device_lib_magic:
            continue
        cell = f'dev_{name}'.lower().replace('.', '_')
        inst = instances.get(name, {})
        x = int(round(inst.get('x_um', 0) * 100))
        y = int(round(inst.get('y_um', 0) * 100))
        mag.extend([f'use {cell} {cell}_0',
                    f'transform 1 0 {x} 0 1 {y}',
                    'box 0 0 1 1'])

    # 2. AP geometry (M1 stubs + Via1 + M2 pads) for all APs
    m1s = 40   # M1 stub half-width
    for pk, ap in access_points.items():
        px, py = ap['x'], ap['y']
        vp = ap.get('via_pad', {})
        stub = ap.get('m1_stub')
        if stub:
            cx = (stub[0] + stub[2]) // 2
            mag.append(f'<< {MAG_LAYERS["M1"]} >>')
            mag.append(f'rect {nm(cx - m1s)} {nm(stub[1])} '
                       f'{nm(cx + m1s)} {nm(stub[3])}')
        if vp:
            mag.append(f'<< {MAG_LAYERS["V1"]} >>')
            mag.append(f'rect {nm(vp["via1"][0])} {nm(vp["via1"][1])} '
                       f'{nm(vp["via1"][2])} {nm(vp["via1"][3])}')
            mag.append(f'<< {MAG_LAYERS["M1"]} >>')
            mag.append(f'rect {nm(vp["m1"][0])} {nm(vp["m1"][1])} '
                       f'{nm(vp["m1"][2])} {nm(vp["m1"][3])}')
            mag.append(f'<< {MAG_LAYERS["M2"]} >>')
            mag.append(f'rect {nm(vp["m2"][0])} {nm(vp["m2"][1])} '
                       f'{nm(vp["m2"][2])} {nm(vp["m2"][3])}')

    # 3. Power via stacks (TM1 → Via5 → M5 → Via4 → M4 → Via3 → M3 → Via2 → M2)
    # Group drops by net+Y band for TM1 stripes
    from collections import defaultdict
    stripe_bands = defaultdict(list)
    for drop in power_drops:
        ap_key = f"{drop['inst']}.{drop['pin']}"
        ap = access_points.get(ap_key)
        if not ap:
            continue
        px, py = ap['x'], ap['y']
        stripe_bands[drop['net']].append((px, py))

        # Per-drop via stack: Via2 through Via4 + M5 + Via5
        for layer, hw in [('V2', VIA_HW), ('M3', VIA_PAD_HW),
                          ('V3', VIA_HW), ('M4', VIA_PAD_HW),
                          ('V4', VIA_HW), ('M5', M5_PAD_HW),
                          ('TV1', TV1_HW)]:
            mag.append(f'<< {MAG_LAYERS[layer]} >>')
            mag.append(f'rect {nm(px - hw)} {nm(py - hw)} '
                       f'{nm(px + hw)} {nm(py + hw)}')

    # TM1 stripes (shared per Y band)
    for net, positions in stripe_bands.items():
        sorted_pos = sorted(positions, key=lambda p: p[1])
        bands = []
        current = [sorted_pos[0]]
        for p in sorted_pos[1:]:
            if p[1] - current[-1][1] < 5000:
                current.append(p)
            else:
                bands.append(current)
                current = [p]
        bands.append(current)

        for band in bands:
            xs = [p[0] for p in band]
            ys = [p[1] for p in band]
            yc = sum(ys) // len(ys)
            mag.append(f'<< {MAG_LAYERS["TM1"]} >>')
            mag.append(f'rect {nm(min(xs) - TM1_HW)} {nm(yc - TM1_HW)} '
                       f'{nm(max(xs) + TM1_HW)} {nm(yc + TM1_HW)}')

    # 4. Selected signal routes
    for net_name, cand_idx in genome.items():
        cands = candidates.get(net_name)
        if not cands or cand_idx >= len(cands):
            continue
        route = cands[cand_idx]
        for seg in route:
            x1, y1, x2, y2, layer = seg
            ml = MAG_LAYERS.get(layer)
            if not ml:
                continue
            mag.append(f'<< {ml} >>')
            if layer in ('V2', 'V3', 'V4', 'TV1'):
                # Via: point square
                mag.append(f'rect {nm(x1 - VIA_HW)} {nm(y1 - VIA_HW)} '
                           f'{nm(x1 + VIA_HW)} {nm(y1 + VIA_HW)}')
            elif x1 == x2 and y1 == y2:
                # Point pad
                mag.append(f'rect {nm(x1 - VIA_PAD_HW)} {nm(y1 - VIA_PAD_HW)} '
                           f'{nm(x1 + VIA_PAD_HW)} {nm(y1 + VIA_PAD_HW)}')
            elif x1 == x2:
                # Vertical wire
                hw = M4_HW if layer == 'M4' else M3_HW
                mag.append(f'rect {nm(x1 - hw)} {nm(min(y1, y2) - hw)} '
                           f'{nm(x1 + hw)} {nm(max(y1, y2) + hw)}')
            else:
                # Horizontal wire
                hw = M3_HW if layer == 'M3' else M4_HW
                mag.append(f'rect {nm(min(x1, x2) - hw)} {nm(y1 - hw)} '
                           f'{nm(max(x1, x2) + hw)} {nm(y1 + hw)}')

    mag.append('<< end >>')

    # Write .mag
    os.makedirs(output_dir, exist_ok=True)
    mag_path = os.path.join(output_dir, 'soilz.mag')
    with open(mag_path, 'w') as f:
        f.write('\n'.join(mag) + '\n')

    # Write phase_c.tcl (flatten + extract + ext2spice + GDS)
    tcl = (
        'load soilz\n'
        'flatten soilz_flat\n'
        'load soilz_flat\n'
        'select top cell\n'
        'extract unique\n'
        'extract all\n'
        'ext2spice lvs\n'
        'ext2spice\n'
        'gds write soilz.gds\n'
        'exit\n'
    )
    with open(os.path.join(output_dir, 'phase_c.tcl'), 'w') as f:
        f.write(tcl)

    return mag_path


def load_data(layout_dir=None):
    """Load all JSON data files."""
    if layout_dir is None:
        layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with open(os.path.join(layout_dir, 'netlist.json')) as f:
        netlist = json.load(f)
    with open(os.path.join(layout_dir, 'placement.json')) as f:
        placement = json.load(f)
    with open(os.path.join(layout_dir, 'atk', 'data',
                           'device_lib_magic.json')) as f:
        device_lib_magic = json.load(f)
    with open(os.path.join(layout_dir, 'output', 'routing.json')) as f:
        routing = json.load(f)

    return netlist, placement, device_lib_magic, routing


# --- Main: Step 1+2+3 ---
if __name__ == '__main__':
    netlist, placement, device_lib_magic, routing = load_data()
    access_points = routing['access_points']
    power_drops = routing['power']['drops']

    # Step 1: Pin positions
    net_pins = compute_pin_positions(netlist, access_points)
    print(f"Signal nets: {len(net_pins)}, pins: {sum(len(v) for v in net_pins.values())}")

    # Step 2: Candidates
    candidates = generate_candidates(net_pins)
    print(f"Candidates: {sum(len(v) for v in candidates.values())} across {len(candidates)} nets")

    # Step 3: Build soilz.mag with candidate 0 for all nets
    genome = {net: 0 for net in candidates}
    output_dir = '/tmp/signal_route_test'
    mag_path = build_soilz_mag(
        genome, netlist, placement, device_lib_magic,
        access_points, power_drops, candidates, output_dir)
    print(f"\nsoilz.mag written to {mag_path}")

    # Count lines
    with open(mag_path) as f:
        lines = f.readlines()
    print(f"  {len(lines)} lines")

    # Count layer usage
    from collections import Counter
    layer_counts = Counter()
    for line in lines:
        if line.startswith('<< ') and line.strip().endswith(' >>'):
            layer_counts[line.strip()] += 1
    print("  Layer usage:")
    for layer, count in layer_counts.most_common():
        print(f"    {layer}: {count} entries")
