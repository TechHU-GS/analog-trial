"""§5: Draw signal routing segments."""

import klayout.db

from atk.pdk import (
    M1_SIG_W, M2_SIG_W, M3_MIN_W, M3_MIN_S, M4_MIN_W,
    VIA1_PAD, VIA1_GDS_M1, VIA2_SZ, VIA2_PAD, VIA2_PAD_M2, VIA2_PAD_M3, VIA3_PAD,
    M1_MIN_AREA, M3_MIN_AREA, M4_MIN_AREA, M1_MIN_S, M2_MIN_S,
    M2_MIN_W, MAZE_GRID, s5,
)
from atk.route.maze_router import M1_LYR, M2_LYR, M3_LYR, M4_LYR


def draw_signal_routes(top, li_m1, li_m2, li_m3, li_m4, li_m5,
                       li_v1, li_v2, li_v3, li_v4,
                       li_route_0, li_route_1, li_route_2,
                       li_via_01, li_via_12,
                       routing, instances, placement,
                       device_lib, devices_map, pin_net_map,
                       drawn_vias, bus_m3_bridges, gate_cont_m1, m2_route_wires, gap_bridge_m3_pads, gap_bridge_m3_jogs):
    """Draw signal routing + floating detection + gap fills + Via2 insertion."""
    from assemble_gds import (draw_segments, via1, via2, via3, hbar, vbar, wire,
                              draw_rect, via2_cut_only,
                              _add_missing_ap_via2,
                              _fill_via_m1_corners, _fill_via_ap_m2_gaps, _check_m2_power_signal_collision, _shrink_ap_m2_pads_gds)

    # ═══ 5. Draw signal routing ═══
    print('\n  === Drawing signal routes ===')

    # Build per-net AP M2 pad index for cross-net Via2 M2 pad clipping.
    # Prevents Via2 M2 pads from merging with other-net AP M2 pads.
    _ap_m2_by_net = {}  # net_name -> [(x1,y1,x2,y2), ...]
    _pin_net_map = {}
    for _rn2, _rd2 in routing.get('signal_routes', {}).items():
        for pin in _rd2.get('pins', []):
            _pin_net_map[pin] = _rn2
    for _rn2, _rd2 in routing.get('pre_routes', {}).items():
        for pin in _rd2.get('pins', []):
            _pin_net_map[pin] = _rn2
    for pin_key, ap in routing.get('access_points', {}).items():
        vp = ap.get('via_pad')
        if vp and 'm2' in vp:
            net = _pin_net_map.get(pin_key, '')
            if net:
                _ap_m2_by_net.setdefault(net, []).append(tuple(vp['m2']))
    # Flat list of all AP M2 pads with their net for easy filtering
    _all_ap_m2 = []
    for net, pads in _ap_m2_by_net.items():
        for pad in pads:
            _all_ap_m2.append((pad, net))

    def _xnet_m2_obs(net_name):
        """Return list of AP M2 pad boxes from other nets."""
        return [pad for pad, pnet in _all_ap_m2 if pnet != net_name]

    # Pre-routes
    for net_name, route in routing.get('pre_routes', {}).items():
        segs = route.get('segments', [])
        # Route layers remapped: router 0→M3, 1→M4, 2→M5, via -1→Via3, -2→Via4
        draw_segments(top, li_route_0, li_route_1, li_via_01, segs, M2_SIG_W,
                      drawn_vias=drawn_vias, li_m3=li_route_2, li_v2=li_via_12)
        print(f'    Pre-route {net_name}: {len(segs)} segments')

    # Determine which routes will get Via2 connections (pre-scan).
    # Routes without Via2 produce floating M3/M4 wire → interferes with LVS.
    # Only draw wire for routes that _add_missing_ap_via2 can connect.
    _via_stack_pins_pre = set()
    for _d in routing.get('power', {}).get('drops', []):
        if _d['type'] == 'via_stack':
            _via_stack_pins_pre.add(f"{_d['inst']}.{_d['pin']}")
    _aps_pre = routing.get('access_points', {})
    _pos_pre = {}
    for _ak, _av in _aps_pre.items():
        _pos_pre.setdefault((_av['x'], _av['y']), []).append(_ak)
    _shared_pre = set()
    for _pos, _keys in _pos_pre.items():
        if len(_keys) >= 2:
            _shared_pre.update(_keys)

    # Signal routes — skip floating (marked by two-pass Via2 check)
    total_segs = 0
    via1_before = len(drawn_vias)
    total_via_segs = 0
    _skipped_floating = 0
    for net_name, route in routing.get('signal_routes', {}).items():
        if route.get('_floating'):
            _skipped_floating += 1
            continue
        segs = route.get('segments', [])
        total_via_segs += sum(1 for s in segs if s[4] < 0)
        draw_segments(top, li_route_0, li_route_1, li_via_01, segs, M2_SIG_W,
                      drawn_vias=drawn_vias, li_m3=li_route_2, li_v2=li_via_12)
        total_segs += len(segs)
    new_vias = len(drawn_vias) - via1_before
    skipped_vias = total_via_segs - new_vias
    print(f'  Drew {len(routing.get("signal_routes", {})) - _skipped_floating} signal nets '
          f'(skipped {_skipped_floating} floating), '
          f'{total_segs} segments ({new_vias} new vias, '
          f'{skipped_vias} deduped)')

    # Fill M1 corner notches at routing via bends
    _fill_via_m1_corners(top, li_m1, routing, gate_cont_m1)

    # Fill M2 gaps between routing vias and access point M2 pads
    _fill_via_ap_m2_gaps(top, li_m2, routing)

    # Add missing Via2/Via3 where route M3/M4 endpoints need AP M2 connection
    _v2_before = top.shapes(li_v2).size()
    # Check if Via2 at M_db1_n.G AP exists BEFORE _add_missing_ap_via2
    # Check Via2 at M_db1_n.G AP (debug — uses AP coords, not hardcoded)
    _db1_ap = routing.get('access_points', {}).get('M_db1_n.G')
    _db1_found = False
    if _db1_ap:
        _db1_x, _db1_y = _db1_ap['x'], _db1_ap['y']
        for _sh in top.shapes(li_v2).each():
            _bb = _sh.bbox()
            _cx = (_bb.left + _bb.right) // 2
            _cy = (_bb.top + _bb.bottom) // 2
            if abs(_cx - _db1_x) < 20 and abs(_cy - _db1_y) < 20:
                _db1_found = True
                break
    print(f'    Via2 at M_db1_n.G AP BEFORE: {_db1_found}')
    _ap_via2_m3_stubs, _fallback_shapes = _add_missing_ap_via2(
        top, li_v2, li_m2, li_m3, li_v3, li_m4, routing,
        xnet_m2_wires=m2_route_wires,
        bus_m3_bridges=bus_m3_bridges)
    _v2_after = top.shapes(li_v2).size()
    print(f'    Via2 shapes: {_v2_before} → {_v2_after} (+{_v2_after - _v2_before})')

    # ── M4 dead-end drops: Region-based detection + DRC-safe ──
    import klayout.db as _db
    from atk.pdk import VIA3_SZ, VIA3_PAD
    _m4_region = _db.Region(top.begin_shapes_rec(li_m4))
    _v3_region = _db.Region(top.begin_shapes_rec(li_v3))
    _m2_region = _db.Region(top.begin_shapes_rec(li_m2))
    _m3_region = _db.Region(top.begin_shapes_rec(li_m3))
    _m4_dead = _m4_region.not_interacting(_v3_region)
    _m4_safe = _m4_dead.interacting(_m2_region)
    _M3_MIN_S = 210
    _hp_m3pad = VIA3_PAD // 2  # M3 pad half-size from Via3
    _n_drops = 0
    _n_skip = 0
    for _poly in _m4_safe.each():
        _bb = _poly.bbox()
        _cx = (_bb.left + _bb.right) // 2
        _cy = (_bb.bottom + _bb.top) // 2
        # Check: would M3 pad at this position violate M3.b spacing?
        _m3_pad = _db.Region(_db.Box(
            _cx - _hp_m3pad, _cy - _hp_m3pad,
            _cx + _hp_m3pad, _cy + _hp_m3pad))
        _m3_obs = _m3_region.sized(_M3_MIN_S)  # grow existing M3 by min spacing
        if not _m3_pad.interacting(_m3_obs).is_empty():
            _n_skip += 1
            continue
        via3(top, li_v3, li_m3, li_m4, _cx, _cy)
        via2_cut_only(top, li_v2, _cx, _cy)
        _n_drops += 1
    print(f'    M4 dead-end drops: {_n_drops} Via3+Via2 (Region-detected'
          f'{f", {_n_skip} skipped spacing" if _n_skip else ""})')

    # Fill same-net gaps on all metal layers (grid quantization artifact)
    from assemble.gap_fill import fill_same_net_gaps_region
    fill_same_net_gaps_region(top, (li_m1, li_m2, li_m3, li_m4), routing,
                              gap_bridge_m3_pads, gap_bridge_m3_jogs,
                              ap_via2_m3_stubs=_ap_via2_m3_stubs)
    print(f'    Via2 after gap fill: {top.shapes(li_v2).size()}')

    # ── M2 collision check: signal routes vs power M2 pads ──
    _check_m2_power_signal_collision(routing)

    # ── Post-assembly M2 AP pad shrink (GDS-based) ──
    # Scan actual GDS M2 shapes for AP pads too close to other shapes.
    # Routing-json-based obstacle list is incomplete: assembly gap fills,
    # via stubs, and other generated shapes are not in routing.json.
    _shrink_ap_m2_pads_gds(top, li_m2, li_v1, routing)
    print(f'    Via2 after pad shrink: {top.shapes(li_v2).size()}')



    return _fallback_shapes
