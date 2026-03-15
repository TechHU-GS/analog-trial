"""M3 power rail topology computation.

Data-driven — reads power_topology from netlist.json constraints.
Pure math — returns rail positions + via drop geometry descriptors.

Architecture:
  M3 horizontal rails (configurable nets, multiple rails per net supported)
  Drop path: M3 rail → Via2 → M2 vbar → Via1 → M1 → device pin
  Some drops use via_stack (Via1+Via2 at pin pos) → M3 vbar to rail.
"""

from atk.pdk import (
    UM, s5,
    M2_SIG_W, M2_MIN_S, M3_PWR_W, M3_MIN_S, M1_SIG_W,
    VIA2_SZ, VIA2_PAD, MAZE_GRID,
    V2_MIN_S,
)
from atk.route.access import inst_bbox_nm, abs_pin_nm

# M2 vbar total blocked half-width from center line:
#   block_rect gets rect expanded by M2_SIG_W/2 (physical wire),
#   then margin = M2_MIN_S + M2_SIG_W/2 (DRC + router wire half-width).
#   Total = M2_SIG_W/2 + M2_MIN_S + M2_SIG_W/2 = 510nm
_VBAR_BLOCK_HALF = M2_SIG_W // 2 + M2_MIN_S + M2_SIG_W // 2


def compute_power_rails(placement, power_topology):
    """Compute M3 horizontal power rail positions from power_topology config.

    Supports multiple rails per net (e.g., gnd_0, gnd_1).
    Each rail config has 'net' and unique 'id' (or uses net as id).

    Returns dict: {rail_id: {net, y, x1, x2, width}} in nm.
    """
    rail_x_cfg = power_topology['rail_x']
    x_left = s5(rail_x_cfg['left_margin_um'])
    _, _, right_edge, _ = inst_bbox_nm(placement, rail_x_cfg['right_anchor_inst'])
    x_right = right_edge + s5(rail_x_cfg['right_margin_um'])

    rails = {}
    for rail_cfg in power_topology['rails']:
        net = rail_cfg['net']
        rail_id = rail_cfg.get('id', net)  # id defaults to net name
        inst = rail_cfg['anchor_inst']
        side = rail_cfg['anchor_side']
        offset = rail_cfg['offset_um']

        left, bot, right, top = inst_bbox_nm(placement, inst)
        anchor_y = top if side == 'top' else bot
        rail_y = anchor_y + s5(offset)

        rails[rail_id] = {
            'net': net,
            'y': rail_y,
            'x1': x_left,
            'x2': x_right,
            'width': M3_PWR_W,
        }

    return rails


def _nearest_rail(net, pin_y, rails):
    """Find the nearest rail matching the given net name.

    Returns (rail_id, rail_y).
    """
    best_id = None
    best_dist = float('inf')
    for rail_id, rail in rails.items():
        if rail['net'] != net:
            continue
        d = abs(rail['y'] - pin_y)
        if d < best_dist:
            best_dist = d
            best_id = rail_id
    if best_id is None:
        raise ValueError(f'No rail found for net {net}')
    return best_id, rails[best_id]['y']


def compute_power_drops(placement, access_points, rails, power_topology):
    """Compute via drop positions from power_topology config.

    Each drop auto-selects the nearest same-net rail.

    Returns list of drop dicts with geometry segments.
    """
    drops = []

    for drop_cfg in power_topology['drops']:
        net = drop_cfg['net']
        inst = drop_cfg['inst']
        pin = drop_cfg['pin']
        strategy = drop_cfg['strategy']

        if strategy == 'via_access':
            ap = access_points[(inst, pin)]
            _, rail_y = _nearest_rail(net, ap['y'], rails)
            drops.append(_make_via_access_drop(net, inst, pin, access_points, rail_y))
        elif strategy == 'via_stack':
            pins = abs_pin_nm(placement, inst)
            px, py = pins[pin]
            _, rail_y = _nearest_rail(net, py, rails)
            drops.append(_make_via_stack_drop(net, inst, pin, placement, rail_y))

    _apply_vbar_jogs(drops, access_points)
    _resolve_m3_vbar_rail_conflicts(drops, rails)
    _resolve_m3_vbar_crossnet_spacing(drops)
    _resolve_m3_vbar_crossnet_spacing(drops)  # second pass for cascaded shifts
    return drops


def _resolve_m3_vbar_rail_conflicts(drops, rails):
    """Truncate M3 vbars that cross ANY other-net M3 power rails.

    Power nets are grouped by base name (vdd, vdd_vco, vdd_sd → all 'vdd-family';
    gnd → 'gnd-family'). A gnd vbar crossing any vdd-family rail is a conflict.

    When conflict detected: truncate vbar to stop before the nearest cross-net
    rail boundary (with M3_MIN_S margin).
    """
    # Map rail net names to families
    def _net_family(n):
        if 'gnd' in n: return 'gnd'
        if 'vdd' in n: return 'vdd'
        return n

    # Build rail zones
    rail_zones = []  # (y_lo, y_hi, net, family)
    for rid, rail in rails.items():
        y = rail['y']
        hw = rail['width'] // 2
        rnet = rail.get('net', rid)
        rail_zones.append((y - hw, y + hw, rnet, _net_family(rnet)))

    fixed = 0
    skipped = 0
    for drop in drops:
        if drop['type'] != 'via_stack' or 'm3_vbar' not in drop:
            continue
        vbar = drop['m3_vbar']
        drop_net = drop['net']
        drop_family = _net_family(drop_net)
        vbar_y1, vbar_y2 = min(vbar[1], vbar[3]), max(vbar[1], vbar[3])
        px = vbar[0]
        pin_y = drop['via_y']
        rail_y = drop['rail_y']

        # Find ALL cross-family rail conflicts
        conflicts = []
        for ry1, ry2, rnet, rfam in rail_zones:
            if rfam == drop_family:
                continue  # same family, no conflict
            if ry2 > vbar_y1 and ry1 < vbar_y2:
                conflicts.append((ry1, ry2, rnet))

        if not conflicts:
            continue

        # Find the cross-net rail closest to the pin (first obstacle encountered)
        conflicts.sort(key=lambda c: abs((c[0]+c[1])/2 - pin_y))
        nearest_ry1, nearest_ry2, nearest_rnet = conflicts[0]
        margin = M3_MIN_S + 300 + M3_MIN_S  # 720nm: spacing + signal wire + spacing

        if pin_y < rail_y:
            # Vbar goes upward — truncate below nearest cross-net rail
            new_top = nearest_ry1 - margin
            if new_top > pin_y + 200:  # minimum useful vbar length
                drop['m3_vbar'] = [px, pin_y, px, new_top]
                fixed += 1
            else:
                # Vbar too short to be useful — skip entirely
                drop['m3_vbar'] = [px, pin_y, px, pin_y]  # zero-length
                skipped += 1
        else:
            # Vbar goes downward — truncate above nearest cross-net rail
            new_bot = nearest_ry2 + margin
            if new_bot < pin_y - 200:
                drop['m3_vbar'] = [px, new_bot, px, pin_y]
                fixed += 1
            else:
                drop['m3_vbar'] = [px, pin_y, px, pin_y]
                skipped += 1

    # Second pass: check vbar-vs-vbar cross-family conflicts
    vbar_fixed = 0
    for i, di in enumerate(drops):
        if di['type'] != 'via_stack' or 'm3_vbar' not in di:
            continue
        vi = di['m3_vbar']
        if vi[1] == vi[3]:
            continue  # already eliminated
        fi = _net_family(di['net'])
        vi_y1, vi_y2 = min(vi[1], vi[3]), max(vi[1], vi[3])
        vi_hw = 100
        for j, dj in enumerate(drops):
            if i == j:
                continue
            if dj['type'] != 'via_stack' or 'm3_vbar' not in dj:
                continue
            vj = dj['m3_vbar']
            if vj[1] == vj[3]:
                continue
            fj = _net_family(dj['net'])
            if fi == fj:
                continue  # same family
            vj_y1, vj_y2 = min(vj[1], vj[3]), max(vj[1], vj[3])
            # Check X overlap (within 200nm = 2*hw)
            if abs(vi[0] - vj[0]) > 200:
                continue
            # Check Y overlap
            if vi_y2 > vj_y1 and vi_y1 < vj_y2:
                # Conflict! Truncate the one that's closer to its pin
                pin_y = di['via_y']
                rail_y = di['rail_y']
                if pin_y < rail_y:
                    new_top = vj_y1 - M3_MIN_S
                    if new_top > pin_y + 200:
                        di['m3_vbar'] = [vi[0], pin_y, vi[0], new_top]
                    else:
                        di['m3_vbar'] = [vi[0], pin_y, vi[0], pin_y]
                else:
                    new_bot = vj_y2 + M3_MIN_S
                    if new_bot < pin_y - 200:
                        di['m3_vbar'] = [vi[0], new_bot, vi[0], pin_y]
                    else:
                        di['m3_vbar'] = [vi[0], pin_y, vi[0], pin_y]
                vbar_fixed += 1
                break  # one fix per drop

    total = fixed + skipped + vbar_fixed
    if total:
        print(f'  M3 vbar conflicts: {fixed} rail-truncated, {skipped} eliminated, {vbar_fixed} vbar-truncated')


def _resolve_m3_vbar_crossnet_spacing(drops):
    """Shift M3 vbar X positions to maintain cross-net spacing.

    When gnd and vdd M3 vbars from adjacent devices are too close in X
    (edge gap < M3_MIN_S = 210nm), shift one vbar's X to achieve spacing.

    Vbar width = 200nm, so edge gap = |x1-x2| - 200nm.
    Need: |x1-x2| >= 200 + M3_MIN_S = 410nm center-to-center.
    """
    MIN_CC = 200 + M3_MIN_S  # 410nm center-to-center

    def _net_family(n):
        if 'gnd' in n: return 'gnd'
        if 'vdd' in n: return 'vdd'
        return n

    # Collect all via_stack drops with M3 vbars
    vbar_drops = []
    for i, drop in enumerate(drops):
        if drop['type'] != 'via_stack' or 'm3_vbar' not in drop:
            continue
        v = drop['m3_vbar']
        if v[1] == v[3]:
            continue  # zero-length
        vbar_drops.append((i, drop, v[0], _net_family(drop['net'])))

    shifted = 0
    for ii in range(len(vbar_drops)):
        idx_a, drop_a, xa, fam_a = vbar_drops[ii]
        for jj in range(ii + 1, len(vbar_drops)):
            idx_b, drop_b, xb, fam_b = vbar_drops[jj]
            if fam_a == fam_b:
                continue  # same family

            # Check Y overlap (vbars must have overlapping Y ranges to conflict)
            va = drop_a['m3_vbar']
            vb = drop_b['m3_vbar']
            ya1, ya2 = min(va[1], va[3]), max(va[1], va[3])
            yb1, yb2 = min(vb[1], vb[3]), max(vb[1], vb[3])
            if ya2 <= yb1 or yb2 <= ya1:
                continue  # no Y overlap

            cc = abs(xa - xb)
            if cc >= MIN_CC:
                continue  # already safe

            # Need to shift one vbar. Shift the one whose X is adjustable
            # (shift away from the other by the needed amount)
            needed = MIN_CC - cc + 10  # +10nm safety margin
            # Shift the second one (arbitrary choice — could optimize later)
            if xa < xb:
                new_xb = xb + needed
            else:
                new_xb = xb - needed
            # Snap to 5nm grid
            new_xb = ((new_xb + 2) // 5) * 5
            # Update vbar
            drop_b['m3_vbar'] = [new_xb, vb[1], new_xb, vb[3]]
            # Update via2_pos X to match
            if 'via2_pos' in drop_b:
                drop_b['via2_pos'] = [new_xb, drop_b['via2_pos'][1]]
            vbar_drops[jj] = (idx_b, drop_b, new_xb, fam_b)
            shifted += 1

    if shifted:
        print(f'  M3 vbar cross-net spacing: {shifted} vbars shifted')



def _shorten_vbars_near_signal_m3(drops):
    """Shorten M3 vbar endpoints that land near signal M3 wires.

    After rail conflict truncation, vbar endpoints may land in the
    signal M3 routing corridor. This causes GDS merge between power
    and signal M3 shapes.

    For each vbar endpoint, check if it's within M3_MIN_S + wire_hw
    of any signal M3 wire. If so, shorten the vbar further.
    """
    # Build signal M3 Y ranges per X bucket
    sig_ranges = {}  # x_bucket(1um) -> [(y_lo, y_hi)]
    import os, json as _json
    _rpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'routing.json')
    if not os.path.exists(_rpath): return
    with open(_rpath) as _f: _routing = _json.load(_f)
    for nn, nd in _routing.get('signal_routes', {}).items():
        for seg in nd.get('segments', []):
            if seg[4] != 2: continue  # M3 only
            x1, y1, x2, y2 = seg[:4]
            cx = (x1 + x2) // 2
            ylo = min(y1, y2) - 150  # wire half-width
            yhi = max(y1, y2) + 150
            for db in range(-2, 3):  # ±2 buckets (±2µm)
                sig_ranges.setdefault(cx // 1000 + db, []).append((ylo, yhi))

    CLEAR = M3_MIN_S + 150 + 50  # spacing + signal half-width + safety

    shortened = 0
    for drop in drops:
        if drop['type'] != 'via_stack' or 'm3_vbar' not in drop:
            continue
        v = drop['m3_vbar']
        if v[1] == v[3]: continue

        vx = v[0]
        bucket = vx // 1000
        ranges = sig_ranges.get(bucket, [])
        if not ranges: continue

        pin_y = drop['via_y']
        vy_lo = min(v[1], v[3])
        vy_hi = max(v[1], v[3])

        # Check top endpoint
        if pin_y < drop['rail_y']:  # vbar goes up
            for sy_lo, sy_hi in ranges:
                if abs(vy_hi - sy_lo) < CLEAR or (sy_lo <= vy_hi <= sy_hi):
                    new_top = sy_lo - CLEAR
                    if new_top > pin_y + 200:
                        drop['m3_vbar'] = [vx, pin_y, vx, new_top]
                        shortened += 1
                    else:
                        drop['m3_vbar'] = [vx, pin_y, vx, pin_y]  # eliminate
                        shortened += 1
                    break
        else:  # vbar goes down
            for sy_lo, sy_hi in ranges:
                if abs(vy_lo - sy_hi) < CLEAR or (sy_lo <= vy_lo <= sy_hi):
                    new_bot = sy_hi + CLEAR
                    if new_bot < pin_y - 200:
                        drop['m3_vbar'] = [vx, new_bot, vx, pin_y]
                        shortened += 1
                    else:
                        drop['m3_vbar'] = [vx, pin_y, vx, pin_y]
                        shortened += 1
                    break

    if shortened:
        print(f'  M3 vbar signal proximity: {shortened} vbars shortened')



def _apply_vbar_jogs(drops, access_points):
    """Jog M2 vbar X to avoid same-device router blocking AND M2.b/V2 DRC.

    Computes forbidden X ranges from:
    1. Same-device access points (router blocking)
    2. ALL M2 pads with Y overlap (DRC M2.b spacing)
    3. Other drops' Via2 at same rail (DRC V2.b spacing)

    Picks the nearest valid position to the original.
    """
    from atk.pdk import VIA1_PAD
    _VBAR_PAD_CLEAR = M2_SIG_W // 2 + M2_MIN_S + VIA1_PAD // 2  # 600nm
    _V2_CC = VIA2_PAD + M2_MIN_S  # 480+210=690nm (Via2 M2 pad CC)

    for drop in drops:
        if drop['type'] != 'via_access':
            continue

        inst = drop['inst']
        vbar_x = drop['via_x']
        rail_y = drop['rail_y']
        vbar_y1 = min(drop['via_y'], rail_y)
        vbar_y2 = max(drop['via_y'], rail_y)

        # Build forbidden ranges: vbar_x cannot be in any of these
        forbidden = []

        # 1. Same-device access points — router blocking
        has_same_dev = False
        for (ap_inst, ap_pin), ap in access_points.items():
            if ap_inst != inst or ap_pin == drop['pin']:
                continue
            half = _VBAR_BLOCK_HALF + MAZE_GRID
            forbidden.append((ap['x'] - half, ap['x'] + half))
            has_same_dev = True

        if not has_same_dev:
            continue  # no conflict, no jog needed

        # 2. ALL M2 pads (any device) whose Y range overlaps vbar
        for (ap_inst, ap_pin), ap in access_points.items():
            if ap_inst == inst and ap_pin == drop['pin']:
                continue  # skip self
            vp = ap.get('via_pad')
            if not vp or 'm2' not in vp:
                continue
            pad_m2 = vp['m2']
            if pad_m2[3] < vbar_y1 or pad_m2[1] > vbar_y2:
                continue
            forbidden.append((ap['x'] - _VBAR_PAD_CLEAR,
                              ap['x'] + _VBAR_PAD_CLEAR))

        # 3. Other drops' Via2 at same rail Y + vbar M2 with Y overlap
        _VBAR_CC = M2_SIG_W + M2_MIN_S  # 300+210=510 center-to-center
        for other in drops:
            if other is drop:
                continue
            # Via2 spacing
            ov2 = other.get('via2_pos')
            if ov2 and abs(ov2[1] - rail_y) < _V2_CC:
                forbidden.append((ov2[0] - _V2_CC, ov2[0] + _V2_CC))
            # M2 vbar spacing (already-jogged drops have updated m2_vbar)
            ovbar = other.get('m2_vbar')
            if ovbar:
                ov_y1, ov_y2 = min(ovbar[1], ovbar[3]), max(ovbar[1], ovbar[3])
                if ov_y2 >= vbar_y1 and ov_y1 <= vbar_y2:
                    forbidden.append((ovbar[0] - _VBAR_CC,
                                      ovbar[0] + _VBAR_CC))

        # Merge overlapping forbidden ranges
        forbidden.sort()
        merged = []
        for lo, hi in forbidden:
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))

        def _is_valid(x):
            for lo, hi in merged:
                if lo < x < hi:
                    return False
            return True

        # Find nearest valid position (scan outward from vbar_x)
        best = None
        for dist in range(0, 3000, 5):
            for sign in (+1, -1):
                candidate = vbar_x + sign * dist
                if _is_valid(candidate):
                    best = candidate
                    break
            if best is not None:
                break

        if best is None or best == vbar_x:
            continue  # no jog needed or no valid position

        jog_x = best - vbar_x
        new_x = best
        vy = drop['via_y']

        drop['m2_jog'] = [min(vbar_x, new_x), vy, max(vbar_x, new_x), vy]
        drop['m2_vbar'] = [new_x, min(vy, rail_y), new_x, max(vy, rail_y)]
        drop['via2_pos'] = [new_x, rail_y]
        drop['jog_x'] = jog_x
        vy = drop['via_y']
        rail_y = drop['rail_y']

        drop['m2_jog'] = [min(vbar_x, new_x), vy, max(vbar_x, new_x), vy]
        drop['m2_vbar'] = [new_x, min(vy, rail_y), new_x, max(vy, rail_y)]
        drop['via2_pos'] = [new_x, rail_y]
        drop['jog_x'] = jog_x


def _make_via_access_drop(net, inst, pin, access_points, rail_y):
    """Drop using existing access point → M2 vbar → Via2 at rail."""
    ap = access_points[(inst, pin)]
    vx, vy = ap['x'], ap['y']
    return {
        'net': net,
        'inst': inst,
        'pin': pin,
        'type': 'via_access',
        'via_x': vx,
        'via_y': vy,
        'rail_y': rail_y,
        # M2 vertical bar from access point to rail
        'm2_vbar': [vx, min(vy, rail_y), vx, max(vy, rail_y)],
        # Via2 at rail intersection
        'via2_pos': [vx, rail_y],
    }


def _make_via_stack_drop(net, inst, pin, placement, rail_y):
    """Drop using via_stack at pin pos → M3 vbar to rail."""
    pins = abs_pin_nm(placement, inst)
    px, py = pins[pin]
    return {
        'net': net,
        'inst': inst,
        'pin': pin,
        'type': 'via_stack',
        'via_x': px,
        'via_y': py,
        'rail_y': rail_y,
        # Via stack at pin (Via1 + Via2)
        'via1_pos': [px, py],
        'via2_pos': [px, py],
        # M3 vertical bar from pin to rail
        'm3_vbar': [px, min(py, rail_y), px, max(py, rail_y)],
    }
