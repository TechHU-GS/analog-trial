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
    M2_SIG_W, M2_MIN_S, M3_PWR_W, M1_SIG_W,
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
    return drops


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
