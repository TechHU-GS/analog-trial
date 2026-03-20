"""Same-net gap fill using KLayout Region API.

Replaces the 267-line _fill_same_net_gaps with Region-based merge.
For each net on each metal layer: grow shapes by half the min spacing,
merge overlapping shapes, shrink back. The difference = fill regions.
"""

import klayout.db as db
from collections import defaultdict

from atk.pdk import (
    M1_SIG_W, M2_SIG_W, M1_MIN_W, M2_MIN_W, M3_MIN_W, M4_MIN_W,
    M1_MIN_S, M2_MIN_S, M3_MIN_S, M4_MIN_S,
    VIA1_GDS_M1, VIA1_PAD, VIA2_PAD, VIA2_PAD_M3, VIA3_PAD,
)


def fill_same_net_gaps_region(cell, layer_indices, routing,
                               gap_bridge_m3_pads=None,
                               gap_bridge_m3_jogs=None,
                               ap_via2_m3_stubs=None):
    """Fill gaps between same-net shapes using Region API.

    Same interface as _fill_same_net_gaps but uses Region sized/merged
    instead of pairwise coordinate arithmetic.
    """
    li_m1, li_m2, li_m3, li_m4 = layer_indices

    layer_config = [
        (0, M1_SIG_W, M1_MIN_W, M1_MIN_S, li_m1, 'M1'),
        (1, M2_SIG_W, M2_MIN_W, M2_MIN_S, li_m2, 'M2'),
        (2, M1_SIG_W, M3_MIN_W, M3_MIN_S, li_m3, 'M3'),
        (3, M1_SIG_W, M4_MIN_W, M4_MIN_S, li_m4, 'M4'),
    ]

    via_pad_sizes = {
        (-1, 0): VIA1_GDS_M1,
        (-1, 1): VIA1_PAD,
        (-2, 1): VIA2_PAD,
        (-2, 2): VIA2_PAD_M3,
        (-3, 2): VIA3_PAD,
        (-3, 3): VIA3_PAD,
    }

    ap_data = routing.get('access_points', {})
    total_fills = 0

    for lyr_idx, wire_w, min_w, min_s, li, lyr_name in layer_config:
        hw = wire_w // 2

        # Build per-net Region from routing.json
        net_regions = defaultdict(db.Region)

        for route_dict_name in ('signal_routes', 'pre_routes'):
            for net_name, rd in routing.get(route_dict_name, {}).items():
                for seg in rd.get('segments', []):
                    if len(seg) < 5:
                        continue
                    x1, y1, x2, y2, slyr = seg[:5]

                    if slyr == lyr_idx:
                        if x1 == x2:
                            net_regions[net_name].insert(db.Box(
                                x1 - hw, min(y1, y2), x1 + hw, max(y1, y2)))
                        elif y1 == y2:
                            net_regions[net_name].insert(db.Box(
                                min(x1, x2), y1 - hw, max(x1, x2), y1 + hw))

                    ps = via_pad_sizes.get((slyr, lyr_idx))
                    if ps:
                        hp = ps // 2
                        net_regions[net_name].insert(db.Box(
                            x1 - hp, y1 - hp, x1 + hp, y1 + hp))

                for pin_key in rd.get('pins', []):
                    ap = ap_data.get(pin_key)
                    if not ap:
                        continue
                    vp = ap.get('via_pad', {})
                    lk = {0: 'm1', 1: 'm2', 2: 'm3', 3: 'm4'}.get(lyr_idx)
                    if lk and lk in vp:
                        r = vp[lk]
                        net_regions[net_name].insert(db.Box(*r))
                    if lyr_idx == 0 and ap.get('m1_stub'):
                        net_regions[net_name].insert(
                            db.Box(*ap['m1_stub']))
                    if lyr_idx == 1 and ap.get('m2_stub'):
                        net_regions[net_name].insert(
                            db.Box(*ap['m2_stub']))

        # Add power shapes for M3
        if lyr_idx == 2:
            for drop in routing.get('power', {}).get('drops', []):
                net = drop['net']
                v2p = drop.get('via2_pos')
                if v2p:
                    hp = VIA2_PAD_M3 // 2
                    net_regions[net].insert(db.Box(
                        v2p[0] - hp, v2p[1] - hp, v2p[0] + hp, v2p[1] + hp))
            if gap_bridge_m3_pads:
                hp = VIA2_PAD_M3 // 2
                for bx, by, bnet in gap_bridge_m3_pads:
                    net_regions[bnet].insert(db.Box(
                        bx - hp, by - hp, bx + hp, by + hp))
            if gap_bridge_m3_jogs:
                for jx1, jy1, jx2, jy2, jnet in gap_bridge_m3_jogs:
                    net_regions[jnet].insert(db.Box(jx1, jy1, jx2, jy2))
            if ap_via2_m3_stubs:
                for sx1, sy1, sx2, sy2, snet in ap_via2_m3_stubs:
                    net_regions[snet].insert(db.Box(sx1, sy1, sx2, sy2))

        # Add power shapes for M2
        if lyr_idx == 1:
            for drop in routing.get('power', {}).get('drops', []):
                net = drop['net']
                m2v = drop.get('m2_vbar')
                if m2v:
                    vhw = M2_SIG_W // 2
                    net_regions[net].insert(db.Box(
                        m2v[0] - vhw, min(m2v[1], m2v[3]),
                        m2v[0] + vhw, max(m2v[1], m2v[3])))

        # Per-net: grow → merge → shrink → difference = fills
        layer_fills = 0
        half_s = min_s // 2
        for net_name, region in net_regions.items():
            if region.is_empty():
                continue
            original = region.dup()
            # Grow by half spacing, merge, shrink back
            grown = region.sized(half_s)
            merged = grown.merged()
            shrunk = merged.sized(-half_s)
            # Fill = shrunk minus original
            fills = shrunk - original
            # Filter: skip fills smaller than min_w in either dimension
            for poly in fills.each():
                bbox = poly.bbox()
                if bbox.width() >= min_w or bbox.height() >= min_w:
                    cell.shapes(li).insert(poly)
                    layer_fills += 1

        if layer_fills:
            print(f'    {lyr_name}: {layer_fills} same-net gap fills (Region)')
        total_fills += layer_fills

    if total_fills:
        print(f'    Total same-net gap fills: {total_fills}')
