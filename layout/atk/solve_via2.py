#!/usr/bin/env python3
"""Via2 Constraint Solver v5: dual-layer constraints using geometric connectivity.

Key insight: instead of reconstructing net labels from routing.json,
use klayout.db Region.interacting() to determine same-net vs cross-net
shapes by geometric connectivity (touching shapes = same net).

For each pin:
  1. Find AP's M2 pad → flood fill to get all connected M2 = same-net M2
  2. Cross-net M2 = all M2 - same-net M2
  3. Search for Via2 position where:
     - M3 pad doesn't violate M3.b to any M3 shape (except same-net)
     - M2 bridge doesn't touch cross-net M2 (expanded by M2.b spacing)
  4. Via2 must be near same-net M3/M4 anchor

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.solve_via2
    python3 -m atk.apply_via2
"""

import json
import time
import klayout.db as db
from .pdk import (
    M2_MIN_S, M3_MIN_S, VIA2_PAD_M3, M2_MIN_W,
)
from .paths import ROUTING_JSON

ANCHOR_RADIUS = 2500   # nm (was 1500: wider search finds +79 pins)
MAX_M2_BRIDGE = 5000   # nm (was 3000: longer bridges reach more anchors)
GRID_STEP = 100
M2_BRIDGE_HW = M2_MIN_W // 2  # 100nm
M2_ENDCAP = 145
VIA2_PAD_M3_HALF = VIA2_PAD_M3 // 2  # 190nm


def _bridge_box(px, py, vx, vy):
    """M2 bridge rectangle from AP to Via2."""
    hw = M2_BRIDGE_HW
    bx1 = min(vx, px) - hw
    by1 = min(vy, py) - hw
    bx2 = max(vx, px) + hw
    by2 = max(vy, py) + hw
    dx, dy = vx - px, vy - py
    if abs(dx) >= abs(dy):
        if dx >= 0: bx2 = max(bx2, vx + M2_ENDCAP)
        else:       bx1 = min(bx1, vx - M2_ENDCAP)
    else:
        if dy >= 0: by2 = max(by2, vy + M2_ENDCAP)
        else:       by1 = min(by1, vy - M2_ENDCAP)
    return (bx1, by1, bx2, by2)


def solve(gds_path='output/ptat_vco.gds', routing_path=None):
    if routing_path is None:
        routing_path = ROUTING_JSON

    t0 = time.time()

    # ── Load GDS ──
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    # M3: available space (same as before)
    m3_li = layout.layer(30, 0)
    m3_all = db.Region(top.begin_shapes_rec(m3_li)).merged()
    m3_clearance = M3_MIN_S + VIA2_PAD_M3_HALF
    m3_blocked = m3_all.sized(m3_clearance)
    chip = db.Region(db.Box(0, 0, 200000, 260000))
    m3_available = chip - m3_blocked

    # M2: full merged region (for connectivity-based net identification)
    m2_li = layout.layer(10, 0)
    m2_all = db.Region(top.begin_shapes_rec(m2_li)).merged()

    print(f'  M3 available: {m3_available.count()} regions')
    print(f'  M2 shapes: {m2_all.count()}')
    print(f'  Setup: {time.time()-t0:.2f}s')

    # ── Load routing data ──
    with open(routing_path) as f:
        routing = json.load(f)

    ap_data = routing.get('access_points', {})
    via_stack_pins = set()
    for drop in routing.get('power', {}).get('drops', []):
        if drop['type'] == 'via_stack':
            via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

    # ── Per-pin solver ──
    found = 0
    blocked = 0
    m2_rejected = 0
    results = []

    for net_name, route in routing.get('signal_routes', {}).items():
        segs = route.get('segments', [])
        has_via2 = any(s[4] == -2 for s in segs)
        has_upper = any(s[4] in (2, 3, -3) for s in segs)
        if has_via2 or not has_upper:
            continue

        # Anchor points
        anchors = []
        for s in segs:
            if s[4] in (2, 3):
                anchors.append((s[0], s[1], s[4]))
                anchors.append((s[2], s[3], s[4]))
            elif s[4] == -3:
                anchors.append((s[0], s[1], -3))
        if not anchors:
            continue

        # Compute same-net M2 ONCE per net (using first AP as seed)
        # All APs on the same net should be on the same M2 connected component
        pins = route.get('pins', [])
        net_seed_m2 = db.Region()
        for pin_key in pins:
            ap = ap_data.get(pin_key)
            if not ap:
                continue
            via_pad = ap.get('via_pad', {})
            m2_pad = via_pad.get('m2')
            if m2_pad:
                net_seed_m2.insert(db.Box(m2_pad[0], m2_pad[1],
                                          m2_pad[2], m2_pad[3]))

        if net_seed_m2.is_empty():
            # No M2 pads for this net — skip M2 check (unlikely to cause merge)
            same_net_m2 = db.Region()
            cross_net_m2 = m2_all
        else:
            same_net_m2 = m2_all.interacting(net_seed_m2)
            cross_net_m2 = m2_all - same_net_m2

        # Pre-expand cross-net M2 by spacing for bridge check
        cross_net_m2_expanded = cross_net_m2.sized(M2_MIN_S)

        for pin_key in pins:
            if pin_key in via_stack_pins:
                continue
            ap = ap_data.get(pin_key)
            if not ap:
                continue

            px, py = ap['x'], ap['y']
            best_cost = 999999
            best_pos = None
            best_anchor = None
            pin_m2_rej = 0

            for ax, ay, alyr in anchors:
                if abs(ax - px) + abs(ay - py) > MAX_M2_BRIDGE + ANCHOR_RADIUS:
                    continue

                sr = ANCHOR_RADIUS
                search = db.Region(db.Box(ax - sr, ay - sr, ax + sr, ay + sr))
                local_m3_avail = m3_available & search
                if local_m3_avail.is_empty():
                    continue

                # Also limit cross-net M2 check to local area for speed
                bridge_area = db.Region(db.Box(
                    min(px, ax) - MAX_M2_BRIDGE,
                    min(py, ay) - MAX_M2_BRIDGE,
                    max(px, ax) + MAX_M2_BRIDGE,
                    max(py, ay) + MAX_M2_BRIDGE))
                local_xnet_m2 = cross_net_m2_expanded & bridge_area

                for poly in local_m3_avail.each():
                    bbox = poly.bbox()
                    x_lo = max(bbox.left, ax - sr)
                    x_hi = min(bbox.right, ax + sr)
                    y_lo = max(bbox.bottom, ay - sr)
                    y_hi = min(bbox.top, ay + sr)

                    for tx in range(x_lo, x_hi + 1, GRID_STEP):
                        for ty in range(y_lo, y_hi + 1, GRID_STEP):
                            if not poly.inside(db.Point(tx, ty)):
                                continue
                            d_bridge = abs(tx - px) + abs(ty - py)
                            if d_bridge > MAX_M2_BRIDGE:
                                continue

                            # M2 bridge feasibility (AP → Via2)
                            bx1, by1, bx2, by2 = _bridge_box(px, py, tx, ty)
                            bridge_r = db.Region(db.Box(bx1, by1, bx2, by2))
                            if not (bridge_r & local_xnet_m2).is_empty():
                                pin_m2_rej += 1
                                continue

                            # M3 bridge feasibility (Via2 → anchor)
                            # If anchor is on M4 (layer 3/-3), apply_via2 draws
                            # M3 bridge + Via3 + M3 pad at anchor. Check that
                            # this M3 bridge doesn't violate M3.b spacing.
                            if alyr in (3, -3) and (tx != ax or ty != ay):
                                m3_hw = M3_MIN_W // 2  # 100nm
                                m3bx1 = min(tx, ax) - m3_hw
                                m3by1 = min(ty, ay) - m3_hw
                                m3bx2 = max(tx, ax) + m3_hw
                                m3by2 = max(ty, ay) + m3_hw
                                m3_bridge = db.Region(db.Box(
                                    m3bx1, m3by1, m3bx2, m3by2))
                                # Check against cross-net M3 (using m3_blocked
                                # which already has M3_MIN_S + pad margin)
                                if not (m3_bridge & m3_blocked).is_empty():
                                    # Check same-net exception: bridge over
                                    # same-net M3 is OK
                                    m3_bridge_conflict = m3_bridge & m3_blocked
                                    # Subtract same-net M3 from conflict
                                    same_net_m3 = m3_all.interacting(
                                        db.Region(db.Box(
                                            ax - 200, ay - 200,
                                            ax + 200, ay + 200)))
                                    real_conflict = m3_bridge_conflict - \
                                        same_net_m3.sized(m3_clearance)
                                    if not real_conflict.is_empty():
                                        continue

                            d_anchor = abs(tx - ax) + abs(ty - ay)
                            cost = d_bridge + d_anchor * 2
                            if cost < best_cost:
                                best_cost = cost
                                best_pos = (((tx + 2) // 5) * 5,
                                            ((ty + 2) // 5) * 5)
                                best_anchor = (ax, ay, alyr)

            m2_rejected += pin_m2_rej
            entry = {'pin': pin_key, 'net': net_name, 'ap_x': px, 'ap_y': py}
            if best_pos:
                entry['status'] = 'FOUND'
                entry['via2_x'] = best_pos[0]
                entry['via2_y'] = best_pos[1]
                entry['anchor_x'] = best_anchor[0]
                entry['anchor_y'] = best_anchor[1]
                entry['anchor_layer'] = best_anchor[2]
                entry['bridge_len'] = abs(best_pos[0] - px) + abs(best_pos[1] - py)
                found += 1
            else:
                entry['status'] = 'BLOCKED'
                blocked += 1
            results.append(entry)

    elapsed = time.time() - t0
    print(f'  Via2 solver: {found} found, {blocked} blocked '
          f'({found * 100 // max(found + blocked, 1)}%) in {elapsed:.1f}s')
    print(f'  M2 candidates rejected: {m2_rejected}')

    if found:
        bridges = [r['bridge_len'] for r in results if r['status'] == 'FOUND']
        print(f'  M2 bridge: avg={sum(bridges)//len(bridges)}nm, max={max(bridges)}nm')

    blocked_nets = set(r['net'] for r in results if r['status'] == 'BLOCKED')
    found_nets = set(r['net'] for r in results if r['status'] == 'FOUND')
    fully_blocked = sorted(blocked_nets - found_nets)
    if fully_blocked:
        print(f'  Nets fully blocked: {len(fully_blocked)}')
        for n in fully_blocked[:15]:
            print(f'    {n}')
        if len(fully_blocked) > 15:
            print(f'    ... and {len(fully_blocked)-15} more')

    output = {
        'via2_placements': [r for r in results if r['status'] == 'FOUND'],
        'blocked': [r for r in results if r['status'] == 'BLOCKED'],
        'stats': {'found': found, 'blocked': blocked, 'total': found + blocked,
                  'm2_rejected': m2_rejected},
    }
    with open('output/via2_placements.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f'  Written: output/via2_placements.json')
    return output


if __name__ == '__main__':
    solve()
