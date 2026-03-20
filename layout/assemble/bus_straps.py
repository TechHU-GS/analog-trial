"""§1a: M1 S/D bus straps for ng>=2 devices.

IHP SG13G2 multi-finger PCells have isolated M1 strips per S/D finger.
Bus straps connect all source strips and all drain strips with M1 bars.
"""

import json
import os

import klayout.db

from atk.pdk import (
    M1_THIN, M1_MIN_S, M1_SIG_W, M2_SIG_W, M4_MIN_W,
    VIA1_PAD, VIA1_GDS_M1, VIA2_PAD, VIA2_PAD_M3, VIA3_PAD,
    M3_MIN_W, M3_MIN_S, M3_WIDE_S, UM,
    s5,
)
from atk.route.maze_router import M3_LYR
from atk.device import get_sd_strips, get_ng2_gate_data
from atk.pdk import GATE_POLY_EXT, CNT_D_ENC


def draw_bus_straps(top, li_m1, li_m2, li_m3, li_m4, li_v1, li_v2, li_v3,
                    instances, placement, ties, routing,
                    device_lib, devices_map, pin_net_map, drawn_vias):
    """Draw M1 S/D bus straps for all multi-finger devices.

    Returns:
        bus_count, bus_tie_adj, bus_gap_cuts, bus_m2_bridges: counters
        bus_m3_bridges: list of (xl, yb, xr, yt, net) for M3 obstacle tracking
        gate_cont_m1: empty list (placeholder for gate contact M1 tracking)
    """
    from assemble_gds import via1, via2, via3, hbar, vbar, wire

    # ═══ 1a. M1 S/D bus straps for ng>=2 devices ═══
    # IHP SG13G2 multi-finger PCells have isolated M1 strips per S/D finger.
    # The PCell does NOT internally connect same-type (S or D) strips.
    # Bus straps connect all source strips and all drain strips with M1 bars.
    #
    # Source bus (ABOVE device): connects intermediate source strips + S2.
    #   Skips S1 (strip 0) to avoid crossing D pin's m1_stub at strip 1.
    #   S1 connects to the net independently via its own access point.
    # Drain bus (BELOW device): connects D pin + intermediate drain strips.
    #   Stays within drain strip X range, avoiding S/S2 m1_stubs at edges.
    #
    # Geometry: 160nm-wide M1 bars with 200nm gap from strip edges (> M1.b=180nm).
    # Extends ~50-180nm beyond PCell bbox; well within placer's 700nm device gap.
    print('\n  === Drawing M1 S/D bus straps ===')
    BUS_W = M1_THIN   # 160nm — bus bar width (matches PCell M1 strip width)
    BUS_GAP = 200      # 200nm gap from strip edge to bus bar (> M1.b = 180nm)

    # Build tie M1 bar index for bus strap collision avoidance
    _tie_m1_bars = []  # (xl, yb, xr, yt)
    for _tie in ties.get('ties', []):
        for _r in _tie.get('layers', {}).get('M1_8_0', []):
            _tie_m1_bars.append((_r[0], _r[1], _r[2], _r[3]))

    # Use pin_net_map passed as parameter
    _pin_net_bus = pin_net_map
    _ap_m1_obs = []  # (xl, yb, xr, yt, net) — stubs + pads
    for _key, _ap in routing.get('access_points', {}).items():
        _net = _pin_net_bus.get(_key, '')
        if not _net:
            continue
        _stub = _ap.get('m1_stub')
        if _stub:
            _ap_m1_obs.append((_stub[0], _stub[1], _stub[2], _stub[3], _net))
        _vp = _ap.get('via_pad', {})
        if 'm1' in _vp:
            _r = _vp['m1']
            _ap_m1_obs.append((_r[0], _r[1], _r[2], _r[3], _net))

    # Build AP Via1 M2 pad index for drain bus M2 bridge conflict avoidance.
    _ap_via1_m2_obs = []  # (xl, yb, xr, yt, net)
    _m2hp = VIA1_PAD // 2  # 240nm half-pad
    for _key, _ap in routing.get('access_points', {}).items():
        _net = _pin_net_bus.get(_key, '')
        if not _net:
            continue
        _vp = _ap.get('via_pad', {})
        if 'via1' in _vp:
            _v = _vp['via1']
            _cx = (_v[0] + _v[2]) // 2
            _cy = (_v[1] + _v[3]) // 2
            _ap_via1_m2_obs.append((_cx - _m2hp, _cy - _m2hp,
                                    _cx + _m2hp, _cy + _m2hp, _net))

    # Build M3 obstacle index for bus M3 bridge clearance checking.
    # Mirrors the m3_obs construction in _add_missing_ap_via2().
    _m3_obs_bus = []  # (xl, yb, xr, yt, net)
    for _rd_name in ('signal_routes', 'pre_routes'):
        for _vnet, _rd in routing.get(_rd_name, {}).items():
            for _seg in _rd.get('segments', []):
                _lyr = _seg[4]
                if _lyr == M3_LYR:
                    _x1, _y1, _x2, _y2 = _seg[:4]
                    _hw = M3_MIN_W // 2
                    if _x1 == _x2:
                        _m3_obs_bus.append((_x1 - _hw, min(_y1, _y2),
                                            _x1 + _hw, max(_y1, _y2), _vnet))
                    else:
                        _m3_obs_bus.append((min(_x1, _x2), _y1 - _hw,
                                            max(_x1, _x2), _y1 + _hw, _vnet))
                elif _lyr == -2:  # Via2
                    _hp3 = VIA2_PAD_M3 // 2
                    _m3_obs_bus.append((_seg[0] - _hp3, _seg[1] - _hp3,
                                        _seg[0] + _hp3, _seg[1] + _hp3, _vnet))
                elif _lyr == -3:  # Via3
                    _hp3 = VIA3_PAD // 2
                    _m3_obs_bus.append((_seg[0] - _hp3, _seg[1] - _hp3,
                                        _seg[0] + _hp3, _seg[1] + _hp3, _vnet))
    for _rail_id, _rail in routing.get('power', {}).get('rails', {}).items():
        _rnet = _rail.get('net', _rail_id)
        _hw = _rail['width'] // 2
        _m3_obs_bus.append((_rail['x1'], _rail['y'] - _hw, _rail['x2'],
                            _rail['y'] + _hw, _rnet))
    for _drop in routing.get('power', {}).get('drops', []):
        _vb = _drop.get('m3_vbar')
        if _vb:
            _hw = M3_MIN_W // 2
            _m3_obs_bus.append((_vb[0] - _hw, min(_vb[1], _vb[3]),
                                _vb[0] + _hw, max(_vb[1], _vb[3]),
                                _drop['net']))

    # Build routing via1 M1 pad + wire index for bus strap collision avoidance.
    _via1_m1_obs = []  # (xl, yb, xr, yt, net) — routing via M1 pads + M1 wires
    _via1_m2_obs = []  # (xl, yb, xr, yt, net) — routing via M2 pads
    _v1hp = VIA1_GDS_M1 // 2
    _v1m2hp = VIA1_PAD // 2  # M2 pad half-size for via1
    _m1hw = M1_SIG_W // 2
    for _rd_name in ('signal_routes', 'pre_routes'):
        for _vnet, _rd in routing.get(_rd_name, {}).items():
            for _seg in _rd.get('segments', []):
                if len(_seg) < 5:
                    continue
                sx1, sy1, sx2, sy2, slyr = _seg[:5]
                if slyr == -1:  # via1
                    _via1_m1_obs.append((sx1 - _v1hp, sy1 - _v1hp,
                                        sx1 + _v1hp, sy1 + _v1hp, _vnet))
                    _via1_m2_obs.append((sx1 - _v1m2hp, sy1 - _v1m2hp,
                                        sx1 + _v1m2hp, sy1 + _v1m2hp, _vnet))
                elif slyr == 0:  # M1 wire
                    if sx1 == sx2:  # vertical
                        _via1_m1_obs.append((sx1 - _m1hw, min(sy1, sy2),
                                            sx1 + _m1hw, max(sy1, sy2), _vnet))
                    elif sy1 == sy2:  # horizontal
                        _via1_m1_obs.append((min(sx1, sx2) - _m1hw, sy1 - _m1hw,
                                            max(sx1, sx2) + _m1hw, sy1 + _m1hw, _vnet))
                elif slyr == 1:  # M2 wire — index for drain bus bridge checks
                    _m2hw = M2_SIG_W // 2
                    if sx1 == sx2:  # vertical
                        _via1_m2_obs.append((sx1 - _m2hw, min(sy1, sy2),
                                            sx1 + _m2hw, max(sy1, sy2), _vnet))
                    elif sy1 == sy2:  # horizontal
                        _via1_m2_obs.append((min(sx1, sx2), sy1 - _m2hw,
                                            max(sx1, sx2), sy1 + _m2hw, _vnet))

    _M1_MIN_AREA = 90000  # nm² (M1.d)

    def _draw_gapped_bus(bx1, by1, bx2, by2, bus_net):
        """Draw horizontal bus bar with gaps at cross-net positions.

        Uses interval merge (matching e4b82ae algorithm exactly).
        """
        gaps = []  # (gap_xl, gap_xr) — X ranges to cut
        # AP stubs/pads: overlap check
        for sxl, syb, sxr, syt, snet in _ap_m1_obs:
            if snet == bus_net:
                continue
            if syt <= by1 or syb >= by2:
                continue
            if sxr <= bx1 or sxl >= bx2:
                continue
            gaps.append((sxl - M1_MIN_S, sxr + M1_MIN_S))
        # Routing vias/wires: proximity check
        for sxl, syb, sxr, syt, snet in _via1_m1_obs:
            if snet == bus_net:
                continue
            if syt <= by1 - M1_MIN_S or syb >= by2 + M1_MIN_S:
                continue
            if sxr <= bx1 or sxl >= bx2:
                continue
            gaps.append((sxl - M1_MIN_S, sxr + M1_MIN_S))
        if not gaps:
            top.shapes(li_m1).insert(klayout.db.Box(bx1, by1, bx2, by2))
            return 0
        gaps.sort()
        merged = [list(gaps[0])]
        for gl, gr in gaps[1:]:
            if gl <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], gr)
            else:
                merged.append([gl, gr])

        def _emit_seg(sx1, sy1, sx2, sy2):
            seg_w = sx2 - sx1
            seg_h = sy2 - sy1
            if seg_w > 0 and seg_h > 0 and seg_w * seg_h < _M1_MIN_AREA:
                need_h = (_M1_MIN_AREA + seg_w - 1) // seg_w
                sy1 -= (need_h - seg_h)
            top.shapes(li_m1).insert(klayout.db.Box(sx1, sy1, sx2, sy2))

        cur_x = bx1
        for gap_l, gap_r in merged:
            seg_end = max(cur_x, min(gap_l, bx2))
            if seg_end > cur_x:
                _emit_seg(cur_x, by1, seg_end, by2)
            cur_x = max(cur_x, min(gap_r, bx2))
        if cur_x < bx2:
            _emit_seg(cur_x, by1, bx2, by2)
        return len(merged)

    # Device types without PCell via stacks on S0 — need M2 bridge
    # to connect S0 across D1's AP gap in the source bus.
    _NO_VIA_STACK_TYPES = {'nmos_vittoz8', 'nmos_ota_input'}

    bus_count = 0
    bus_tie_adj = 0
    bus_gap_cuts = 0
    bus_m2_bridges = 0
    _bus_m3_bridges = []  # (xl, yb, xr, yt, net) for xnet conflict avoidance
    for inst_name, info in instances.items():
        dev_type = info['type']
        sd = get_sd_strips(device_lib, dev_type)
        if sd is None:
            continue

        dev = devices_map[dev_type]
        pcell_x = s5(info['x_um'] - dev['ox'])
        pcell_y = s5(info['y_um'] - dev['oy'])

        src_strips = sd['source']
        drn_strips = sd['drain']
        strip_top = src_strips[0][3]  # All strips share same Y range
        strip_bot = src_strips[0][1]

        # Source bus above: include ALL source strips (S0..S_last).
        # D1's m1_stub may create a gap between S0 and S2.  For devices
        # with PCell via stacks (pmos_cs8, nmos_bias8), the gap is harmless
        # because S0 connects to the supply rail via M3.  For devices
        # without via stacks (nmos_vittoz8, nmos_ota_input), S0 would be
        # isolated — handled by the M2 bridge below.
        #
        # ng=2 devices (nmos_buf2 etc.) use the BELOW-device bus instead:
        # the above bus gets cut by D0's AP stub between the two source strips.
        # Below the device (under gate strap), no drain AP interferes.
        bus_src = src_strips  # include S0
        if len(bus_src) > 2:
            by1 = pcell_y + strip_top + BUS_GAP
            bx1 = pcell_x + bus_src[0][0]
            bx2 = pcell_x + bus_src[-1][2]
            # Check tie M1 bars — push bus up if too close
            for txl, tyb, txr, tyt in _tie_m1_bars:
                if bx2 <= txl or bx1 >= txr:
                    continue  # no X overlap
                # Bus bar [by1, by1+BUS_W] vs tie [tyb, tyt]
                if tyt > by1 - M1_MIN_S and tyb < by1 + BUS_W + M1_MIN_S:
                    needed = tyt + M1_MIN_S
                    if needed > by1:
                        by1 = ((needed + 4) // 5) * 5  # snap up to 5nm
                        bus_tie_adj += 1
            by2 = by1 + BUS_W
            # Safety: if tie avoidance pushed bus too far above the PCell,
            # the stubs could merge with a neighbouring device's bus strap
            # on a different net (e.g. Mtail gnd bus reaching Min_n tail bus).
            # Cap: skip the bus if push exceeds 700nm above nominal position.
            _nominal_by1 = pcell_y + strip_top + BUS_GAP
            if by1 - _nominal_by1 > 700:
                print(f'    {inst_name}: SKIPPING source bus — tie avoidance '
                      f'pushed {by1 - _nominal_by1}nm above nominal '
                      f'(>{700}nm cap)')
            else:
                # Horizontal bus bar with cross-net AP gap cutting
                bus_net = _pin_net_bus.get(f'{inst_name}.S', '') or \
                          _pin_net_bus.get(f'{inst_name}.S2', '')
                n_gaps = _draw_gapped_bus(bx1, by1, bx2, by2, bus_net)
                bus_gap_cuts += n_gaps
                # Stubs connecting each source strip top to bus
                for strip in bus_src:
                    sx1 = pcell_x + strip[0]
                    sx2 = pcell_x + strip[2]
                    sy1 = pcell_y + strip_top
                    sy2 = by2
                    _stub_ok = True
                    for _axl, _ayb, _axr, _ayt, _anet in _ap_m1_obs:
                        if _anet == bus_net:
                            continue
                        if (_axr > sx1 - M1_MIN_S and _axl < sx2 + M1_MIN_S
                                and _ayt > sy1 and _ayb < sy2):
                            _stub_ok = False
                            break
                    if _stub_ok:
                        top.shapes(li_m1).insert(klayout.db.Box(
                            sx1, sy1, sx2, sy2))
            # M2 bridge: connect S0 to S2 across D1's AP gap
            if dev_type in _NO_VIA_STACK_TYPES:
                s0_cx = pcell_x + (src_strips[0][0] + src_strips[0][2]) // 2
                s2_cx = pcell_x + (src_strips[1][0] + src_strips[1][2]) // 2
                bus_cy = (by1 + by2) // 2
                for vx in (s0_cx, s2_cx):
                    via1(top, li_v1, li_m1, li_m2, vx, bus_cy,
                         m1_pad=VIA1_GDS_M1)
                m2_hh = VIA1_PAD // 2
                top.shapes(li_m2).insert(klayout.db.Box(
                    s0_cx, bus_cy - m2_hh, s2_cx, bus_cy + m2_hh))
                bus_m2_bridges += 1
            bus_count += 1
        elif len(src_strips) == 2:
            # ng=2: connect S1 and S2 BELOW device, BELOW the gate strap.
            # Gate strap M1 sits at PCell-local y = [poly_bot-160, poly_bot].
            # Bus goes below gate strap with M1.b spacing.
            # Stubs from S strips pass through at S X positions (≥230nm
            # gap to gate strap X) — no cross-net collision.
            gdata = get_ng2_gate_data(device_lib, dev_type)
            if gdata is not None:
                gate_strap_bot = round(gdata['poly_bot'] * UM) \
                                 - GATE_POLY_EXT + CNT_D_ENC
                by2_local = gate_strap_bot - BUS_GAP  # PCell-local
            else:
                by2_local = strip_bot - BUS_GAP  # fallback
            by2 = ((pcell_y + by2_local + 2) // 5) * 5
            bx1 = pcell_x + src_strips[0][0]
            bx2 = pcell_x + src_strips[-1][2]
            for txl, tyb, txr, tyt in _tie_m1_bars:
                if bx2 <= txl or bx1 >= txr:
                    continue
                if tyb < by2 + M1_MIN_S and tyt > by2 - BUS_W - M1_MIN_S:
                    needed = tyb - M1_MIN_S - BUS_W
                    if needed < by2 - BUS_W:
                        by2 = ((needed + BUS_W) // 5) * 5
                        bus_tie_adj += 1
            by1 = by2 - BUS_W
            bus_net = _pin_net_bus.get(f'{inst_name}.S', '') or \
                      _pin_net_bus.get(f'{inst_name}.S1', '')
            n_gaps = _draw_gapped_bus(bx1, by1, bx2, by2, bus_net)
            bus_gap_cuts += n_gaps
            # Stubs: S strip bottom (PCell-local y=0) down to bus
            for strip in src_strips:
                sx1 = pcell_x + strip[0]
                sx2 = pcell_x + strip[2]
                sy1 = by1
                sy2 = pcell_y + strip_bot
                # Skip stub if it overlaps a cross-net AP M1 pad
                # (the bus bar is already gap-cut there, so stub
                # would dangle and short to the cross-net AP)
                _stub_ok = True
                for _axl, _ayb, _axr, _ayt, _anet in _ap_m1_obs:
                    if _anet == bus_net:
                        continue
                    if (_axr > sx1 - M1_MIN_S and _axl < sx2 + M1_MIN_S
                            and _ayt > sy1 and _ayb < sy2):
                        _stub_ok = False
                        break
                if _stub_ok:
                    top.shapes(li_m1).insert(klayout.db.Box(
                        sx1, sy1, sx2, sy2))
            bus_count += 1

        # Drain bus below: connect all drain strips (D pin + intermediates).
        # Bus range = strip 1 to strip N-2, never reaches strip 0 or strip N,
        # so it avoids S/S2 m1_stubs (which may extend below for NMOS).
        if len(drn_strips) >= 2:
            by2 = pcell_y + strip_bot - BUS_GAP
            bx1 = pcell_x + drn_strips[0][0]
            bx2 = pcell_x + drn_strips[-1][2]
            # Check tie M1 bars — push bus down if too close
            for txl, tyb, txr, tyt in _tie_m1_bars:
                if bx2 <= txl or bx1 >= txr:
                    continue
                if tyb < by2 + M1_MIN_S and tyt > by2 - BUS_W - M1_MIN_S:
                    needed = tyb - M1_MIN_S - BUS_W
                    if needed < by2 - BUS_W:
                        by2 = ((needed + BUS_W) // 5) * 5  # snap down to 5nm
                        bus_tie_adj += 1
            by1 = by2 - BUS_W
            # Horizontal bus bar with cross-net AP gap cutting
            bus_net = _pin_net_bus.get(f'{inst_name}.D', '')
            n_gaps = _draw_gapped_bus(bx1, by1, bx2, by2, bus_net)
            bus_gap_cuts += n_gaps
            # Stubs connecting each drain strip bottom to bus
            for strip in drn_strips:
                top.shapes(li_m1).insert(klayout.db.Box(
                    pcell_x + strip[0], by1,
                    pcell_x + strip[2], pcell_y + strip_bot))
            # M2 bridges across drain bus gaps: if a gap separates adjacent
            # drain strips, add Via1+M2 on each side to bridge the gap.
            if n_gaps > 0 and len(drn_strips) >= 3:
                bus_cy = (by1 + by2) // 2
                # Find which drain strips are on the same bus segment.
                # A strip at position x is "connected" to the bus at x if
                # the bus bar has M1 at that x (no gap cut there).
                # Compute gap intervals (same logic as _draw_gapped_bus)
                _drn_gaps = []
                for sxl, syb, sxr, syt, snet in _ap_m1_obs:
                    if snet == bus_net:
                        continue
                    if syt <= by1 or syb >= by2:
                        continue
                    if sxr <= bx1 or sxl >= bx2:
                        continue
                    _drn_gaps.append((sxl - M1_MIN_S, sxr + M1_MIN_S))
                # Also check routing vias/wires (mirrors _draw_gapped_bus)
                for sxl, syb, sxr, syt, snet in _via1_m1_obs:
                    if snet == bus_net:
                        continue
                    if syt <= by1 - M1_MIN_S or syb >= by2 + M1_MIN_S:
                        continue
                    if sxr <= bx1 or sxl >= bx2:
                        continue
                    _drn_gaps.append((sxl - M1_MIN_S, sxr + M1_MIN_S))
                if _drn_gaps:
                    _drn_gaps.sort()
                    _mgaps = [list(_drn_gaps[0])]
                    for gl, gr in _drn_gaps[1:]:
                        if gl <= _mgaps[-1][1]:
                            _mgaps[-1][1] = max(_mgaps[-1][1], gr)
                        else:
                            _mgaps.append([gl, gr])
                    # For each adjacent pair of drain strips, check if a gap
                    # falls between them
                    for di in range(len(drn_strips) - 1):
                        d1_cx = pcell_x + (drn_strips[di][0] + drn_strips[di][2]) // 2
                        d2_cx = pcell_x + (drn_strips[di+1][0] + drn_strips[di+1][2]) // 2
                        gap_between = False
                        for gl, gr in _mgaps:
                            if gl < d2_cx and gr > d1_cx:
                                gap_between = True
                                break
                        if gap_between:
                            # Check if M2 bar would short to cross-net AP Via1
                            m2_hh = VIA1_PAD // 2
                            _m2_bar = (d1_cx, bus_cy - m2_hh,
                                       d2_cx, bus_cy + m2_hh)
                            _has_xnet_m2 = False
                            for _obs_list in (_ap_via1_m2_obs, _via1_m2_obs):
                                for _axl, _ayb, _axr, _ayt, _anet in _obs_list:
                                    if _anet == bus_net:
                                        continue
                                    if (_axr > _m2_bar[0] and _axl < _m2_bar[2] and
                                            _ayt > _m2_bar[1] and _ayb < _m2_bar[3]):
                                        _has_xnet_m2 = True
                                        break
                                if _has_xnet_m2:
                                    break
                            if not _has_xnet_m2:
                                # No conflict: M2 bar as normal
                                for vx in (d1_cx, d2_cx):
                                    via1(top, li_v1, li_m1, li_m2, vx, bus_cy,
                                         m1_pad=VIA1_GDS_M1)
                                top.shapes(li_m2).insert(klayout.db.Box(*_m2_bar))
                            else:
                                # Cross-net AP Via1 M2 conflict: use M3 bridge.
                                # Check M3 clearance at bridge region.
                                _m3hw = M1_SIG_W // 2  # 150nm
                                _m3_bar = klayout.db.Box(
                                    d1_cx - VIA2_PAD_M3 // 2,
                                    bus_cy - _m3hw,
                                    d2_cx + VIA2_PAD_M3 // 2,
                                    bus_cy + _m3hw)
                                _m3_clear = True
                                # Check routing-derived M3 obstacles (includes
                                # signal M3 wires drawn later + power M3 shapes)
                                _s = M3_MIN_S
                                for _ox1, _oy1, _ox2, _oy2, _onet in _m3_obs_bus:
                                    if _onet == bus_net:
                                        continue
                                    if (_m3_bar.right + _s > _ox1 and
                                            _m3_bar.left - _s < _ox2 and
                                            _m3_bar.top + _s > _oy1 and
                                            _m3_bar.bottom - _s < _oy2):
                                        _m3_clear = False
                                        break
                                if _m3_clear:
                                    # Check via endpoint M2 pads against
                                    # cross-net M2 wires before drawing
                                    _v2m2hp = VIA2_PAD // 2
                                    _ep_m2_ok = True
                                    for vx in (d1_cx, d2_cx):
                                        _ep = (vx - _v2m2hp, bus_cy - _v2m2hp,
                                               vx + _v2m2hp, bus_cy + _v2m2hp)
                                        for _obs_list in (_ap_via1_m2_obs,
                                                          _via1_m2_obs):
                                            for _o in _obs_list:
                                                if _o[4] == bus_net:
                                                    continue
                                                if (_o[2] > _ep[0] and _o[0] < _ep[2]
                                                        and _o[3] > _ep[1]
                                                        and _o[1] < _ep[3]):
                                                    _ep_m2_ok = False
                                                    break
                                            if not _ep_m2_ok:
                                                break
                                        if not _ep_m2_ok:
                                            break
                                    if not _ep_m2_ok:
                                        pass  # skip M3 bridge — M2 pad conflict
                                    else:
                                        for vx in (d1_cx, d2_cx):
                                            via1(top, li_v1, li_m1, li_m2, vx,
                                                 bus_cy, m1_pad=VIA1_GDS_M1)
                                            via2(top, li_v2, li_m2, li_m3, vx,
                                                 bus_cy)
                                    hbar(top, li_m3, d1_cx, d2_cx, bus_cy,
                                         M1_SIG_W)
                                    _bus_m3_bridges.append((
                                        _m3_bar.left, _m3_bar.bottom,
                                        _m3_bar.right, _m3_bar.top,
                                        bus_net))
                                else:
                                    # M3 also blocked — use M4 bridge
                                    # Via1+Via2+Via3 at endpoints + M4 hbar
                                    # Check M3 clearance at Via3 endpoints;
                                    # shift toward gap center if needed.
                                    _hp3 = VIA3_PAD // 2
                                    _v1hp_m1 = VIA1_GDS_M1 // 2
                                    _gap_cx = (d1_cx + d2_cx) // 2
                                    # Build drain strip X edges for M1 gap check
                                    _drn_strip_edges = []
                                    for _ds in drn_strips:
                                        _drn_strip_edges.append(
                                            (pcell_x + _ds[0], pcell_x + _ds[2]))
                                    _v4_pts = []
                                    for _orig_vx in (d1_cx, d2_cx):
                                        vx = _orig_vx
                                        for _shift in range(40):
                                            _v3box = (vx - _hp3, bus_cy - _hp3,
                                                      vx + _hp3, bus_cy + _hp3)
                                            _v3_ok = True
                                            # Check M3 clearance
                                            for _ox1, _oy1, _ox2, _oy2, _onet in _m3_obs_bus:
                                                if _onet == bus_net:
                                                    continue
                                                if (_v3box[2] + _s > _ox1 and
                                                        _v3box[0] - _s < _ox2 and
                                                        _v3box[3] + _s > _oy1 and
                                                        _v3box[1] - _s < _oy2):
                                                    _v3_ok = False
                                                    break
                                            if not _v3_ok:
                                                if _orig_vx < _gap_cx:
                                                    vx += 50
                                                else:
                                                    vx -= 50
                                                continue
                                            # Check M1 spacing: Via1 pad must not
                                            # create sub-M1.b gap with drain strips
                                            _v1_xl = vx - _v1hp_m1
                                            _v1_xr = vx + _v1hp_m1
                                            _m1_ok = True
                                            for _dxl, _dxr in _drn_strip_edges:
                                                # Skip if Via1 overlaps strip (OK)
                                                if _v1_xl <= _dxr and _v1_xr >= _dxl:
                                                    continue
                                                g = (_v1_xl - _dxr if _v1_xl > _dxr
                                                     else _dxl - _v1_xr)
                                                if 0 < g < M1_MIN_S:
                                                    _m1_ok = False
                                                    break
                                            if _m1_ok:
                                                break
                                            if _orig_vx < _gap_cx:
                                                vx += 50
                                            else:
                                                vx -= 50
                                        _v4_pts.append(vx)
                                    for vx in _v4_pts:
                                        via1(top, li_v1, li_m1, li_m2, vx,
                                             bus_cy, m1_pad=VIA1_GDS_M1)
                                        via2(top, li_v2, li_m2, li_m3, vx,
                                             bus_cy)
                                        via3(top, li_v3, li_m3, li_m4, vx,
                                             bus_cy)
                                    hbar(top, li_m4, _v4_pts[0], _v4_pts[1],
                                         bus_cy, M4_MIN_W)
                                    # Record Via3 M3 pads as M3 obstacles
                                    for vx in _v4_pts:
                                        _bus_m3_bridges.append((
                                            vx - _hp3, bus_cy - _hp3,
                                            vx + _hp3, bus_cy + _hp3,
                                            bus_net))
                                    _shifted = [f"{o}→{v}" for o, v
                                                in zip((d1_cx, d2_cx), _v4_pts)
                                                if o != v]
                                    print(f"    M4 bridge: {inst_name}"
                                          f" net={bus_net} at y={bus_cy}"
                                          f" (M3 blocked by xnet)"
                                          + (f" shifted={_shifted}"
                                             if _shifted else ""))
                            bus_m2_bridges += 1
            bus_count += 1

        if len(bus_src) > 2:
            n_src = len(bus_src)
        elif len(src_strips) == 2:
            n_src = 2
        else:
            n_src = 0
        n_drn = len(drn_strips) if len(drn_strips) >= 2 else 0
        if n_src or n_drn:
            print(f'    {inst_name}: S bus {n_src} strips, D bus {n_drn} strips')
    return (bus_count, bus_tie_adj, bus_gap_cuts, bus_m2_bridges,
            _bus_m3_bridges)
