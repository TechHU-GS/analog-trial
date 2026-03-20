"""§4: Draw power rails, drops, via stacks, TM1 stripes."""

import klayout.db

from atk.pdk import (
    METAL1, METAL2, METAL3, METAL4, METAL5, VIA1, VIA2, VIA3, VIA4,
    TOPMETAL1, TOPVIA1,
    M1_SIG_W, M1_MIN_S, M2_SIG_W, M2_MIN_S, M2_MIN_W,
    M3_MIN_W, M3_MIN_S, M3_WIDE_S, M3_PWR_W, M4_SIG_W, M4_MIN_S, M4_MIN_W,
    VIA1_PAD, VIA1_GDS_M1, VIA1_GDS_M2,
    VIA2_SZ, VIA2_PAD, VIA2_PAD_M2, VIA2_PAD_M3,
    VIA3_SZ, VIA3_PAD, VIA3_PAD_M4,
    VIA4_SZ, VIA4_PAD_M4, VIA4_PAD_M5,
    TV1_SIZE, TV1_ENC_M5, TV1_ENC_TM1, TM1_MIN_W,
    M5_MIN_S, M5_MIN_W, M3_MIN_AREA, M4_MIN_AREA,
    UM, s5, MAZE_GRID,
)
from atk.route.maze_router import M1_LYR, M2_LYR, M3_LYR, M4_LYR


def draw_power(top, li_m1, li_m2, li_m3, li_m4, li_m5,
               li_v1, li_v2, li_v3, li_v4, li_tv1, li_tm1,
               layout, instances, placement, routing,
               device_lib, devices_map, pin_net_map,
               drawn_vias, bus_m3_bridges, m2_route_wires):
    """Draw power rails, drops, via stacks, TM1 stripes.

    Returns:
        drop_count, gap_bridge_m3_pads, gap_bridge_m3_jogs,
        m2_signal_segs: data for later sections
    """
    from assemble_gds import (via1, via2, via2_no_m2_pad, via2_cut_m2,
                              via3, via4, topvia1,
                              hbar, vbar, wire, draw_rect,
                              via2_no_m2_pad, via2_cut_m2, via2_cut_only,
                              _fill_vbar_to_pad, _draw_rail_bridges)

    # ═══ 4. Draw power rails + drops ═══
    print('\n  === Drawing power ===')

    # M3 horizontal rails — SKIPPED: power goes to TM1 via stack,
    # M3 rails conflict with M3 signal routing (layer strategy: M3=signal H)
    print('    M3 rails: SKIPPED (power on TM1, M3 for signal)')

    # Empty all_rails so vbar drawing is also skipped (no target rail → no vbar)
    all_rails = {}

    # Pre-collect M2 signal segments for bridge conflict checking
    m2_signal_segs = []
    for _sn, _sr in routing.get('signal_routes', {}).items():
        for seg in _sr.get('segments', []):
            if len(seg) >= 5 and seg[4] == M2_LYR:
                m2_signal_segs.append(seg[:4])  # x1,y1,x2,y2

    # Pre-collect M3 vbar shapes for bridge via2 M3.b spacing checks
    # Each entry: (net, x_center, y1, y2) — vbar body at M3_MIN_W width
    _m3_vbar_index = []
    for _d in routing.get('power', {}).get('drops', []):
        _m3v = _d.get('m3_vbar')
        if _m3v:
            _m3_vbar_index.append((_d['net'], _m3v[0],
                                   min(_m3v[1], _m3v[3]),
                                   max(_m3v[1], _m3v[3])))

    def _m3_pad_near_xnet_rail(px, py, drop_net):
        """Check if an M3 pad at (px, py) is within M3_MIN_S of a cross-net rail.
        Returns True if the pad would bridge to a cross-net rail."""
        hp = VIA2_PAD_M3 // 2
        pad_bot = py - hp
        pad_top = py + hp
        _fam = 'gnd' if 'gnd' in drop_net else 'vdd'
        for _rn, _rl in all_rails.items():
            _rfam = 'gnd' if 'gnd' in _rl.get('net', _rn) else 'vdd'
            if _rfam == _fam:
                continue  # same family
            rh = _rl['width'] // 2
            rail_bot = _rl['y'] - rh
            rail_top = _rl['y'] + rh
            dist_above = pad_bot - rail_top
            dist_below = rail_bot - pad_top
            if dist_above < M3_MIN_S and dist_below < M3_MIN_S:
                return True
        return False

    def _check_m3b_bridge(bx, by, drop_net):
        """Check bridge via2 M3 pad at (bx, by) against cross-net M3 vbars.

        Returns the worst (smallest) edge-to-edge gap, or None if clean.
        """
        hp = VIA2_PAD_M3 // 2   # 190
        bhw = M3_MIN_W // 2     # 100
        pad_l, pad_r = bx - hp, bx + hp
        pad_b, pad_t = by - hp, by + hp
        worst = None
        for vnet, vcx, vy1, vy2 in _m3_vbar_index:
            if vnet == drop_net:
                continue
            # Y overlap check: pad vs vbar body
            if pad_t <= vy1 or vy2 <= pad_b:
                continue
            vl, vr = vcx - bhw, vcx + bhw
            if pad_r <= vl:
                gap = vl - pad_r
            elif vr <= pad_l:
                gap = pad_l - vr
            else:
                gap = 0  # overlap
            if gap < M3_MIN_S:
                if worst is None or gap < worst:
                    worst = gap
        return worst

    # Track drawn M2 underpass positions to avoid duplicates
    _drawn_m2_underpasses = set()
    # Track drawn via2 (x, y) positions for partial-overlap prevention
    _drawn_via2_positions = set()
    # Track gap-bridge via2 M3 pad positions for _fill_same_net_gaps
    # Each entry: (x, y, net) — via2_no_m2_pad draws M3 pad at this position
    _gap_bridge_m3_pads = []
    # Track M3 jog bar rects: (x1, y1, x2, y2, net) — hbar connecting
    # shifted bridge back to vbar on M3.
    _gap_bridge_m3_jogs = []

    # ── Build M2 obstacle index for underpass spacing checks ──
    # Each entry: (x1, y1, x2, y2, net)
    # Used to enforce M2.b (M2_MIN_S=210nm) between cross-net M2 shapes
    _m2_obstacles = []

    # 1) AP M2 pads — build pin→net mapping first
    _pin_net_map = {}
    for route_dict in [routing.get('signal_routes', {}),
                       routing.get('pre_routes', {})]:
        for net_name, rd in route_dict.items():
            for pin_key in rd.get('pins', []):
                _pin_net_map[pin_key] = net_name

    for key, ap in routing.get('access_points', {}).items():
        net = _pin_net_map.get(key)
        if not net:
            continue
        vp = ap.get('via_pad')
        if vp and 'm2' in vp:
            m2r = vp['m2']
            _m2_obstacles.append((m2r[0], m2r[1], m2r[2], m2r[3], net))
        if ap.get('m2_stub'):
            st = ap['m2_stub']
            _m2_obstacles.append((st[0], st[1], st[2], st[3], net))

    # Pad half-sizes for obstacle indexing
    _v1hp = VIA1_PAD // 2
    _v2hp = VIA2_PAD_M2 // 2

    # 2) Signal M2 shapes: wire bodies + via1/via2 M2 pads
    _hw = M2_SIG_W // 2  # 150nm
    for _sn, _sr in routing.get('signal_routes', {}).items():
        for seg in _sr.get('segments', []):
            if len(seg) < 5:
                continue
            x1, y1, x2, y2, slyr = seg[:5]
            if slyr == M2_LYR:
                if x1 == x2 and y1 != y2:  # vertical
                    _m2_obstacles.append((
                        x1 - _hw, min(y1, y2), x1 + _hw, max(y1, y2), _sn))
                elif y1 == y2 and x1 != x2:  # horizontal
                    _m2_obstacles.append((
                        min(x1, x2), y1 - _hw, max(x1, x2), y1 + _hw, _sn))
            elif slyr == -1:  # via1 → M2 pad (VIA1_PAD)
                _m2_obstacles.append((
                    x1 - _v1hp, y1 - _v1hp,
                    x1 + _v1hp, y1 + _v1hp, _sn))
            elif slyr == -2:  # via2 → M2 pad (VIA2_PAD_M2)
                _m2_obstacles.append((
                    x1 - _v2hp, y1 - _v2hp,
                    x1 + _v2hp, y1 + _v2hp, _sn))

    # 3) Pre-register ALL power drop M2 pads (via1, via2)
    # so that underpass positioning sees all pads regardless of
    # processing order in the drops loop.
    for _drop in routing.get('power', {}).get('drops', []):
        _dnet = _drop['net']
        if _drop['type'] == 'via_stack':
            v1 = _drop.get('via1_pos')
            if v1:
                _m2_obstacles.append((
                    v1[0] - _v1hp, v1[1] - _v1hp,
                    v1[0] + _v1hp, v1[1] + _v1hp, _dnet))
            # Also register via2 M2 pad — via2() draws a full M2 pad
            # for non-crossing drops; conservative to always register.
            v2 = _drop.get('via2_pos')
            if v2:
                _m2_obstacles.append((
                    v2[0] - _v2hp, v2[1] - _v2hp,
                    v2[0] + _v2hp, v2[1] + _v2hp, _dnet))
        elif _drop['type'] == 'via_access':
            v2 = _drop.get('via2_pos')
            if v2:
                _m2_obstacles.append((
                    v2[0] - _v2hp, v2[1] - _v2hp,
                    v2[0] + _v2hp, v2[1] + _v2hp, _dnet))

    # Min center-to-center distance between via2 cuts to avoid partial overlap
    _MIN_V2_CTR_DIST = VIA2_SZ + 220  # VIA2_SZ + V2.b min spacing = 410nm

    def _check_via2_overlap(bx, gy1, gy2, gy1_excl, gy2_excl):
        """Return True if via2 cuts at (bx, gy1/gy2) would partially overlap
        with any already-drawn via2 position."""
        for vy in [gy1, gy2]:
            is_excl = gy1_excl if vy == gy1 else gy2_excl
            if is_excl:
                continue  # No via2 drawn at excl edges
            for (ex, ey) in _drawn_via2_positions:
                if ey != vy:
                    continue
                dx = abs(bx - ex)
                if 0 < dx < _MIN_V2_CTR_DIST:
                    return True  # Partial overlap or too-close
        return False

    def _check_m2b_spacing(bx, by1, by2, bw, drop_net):
        """Check if M2 vbar at (bx, by1, by2) with width bw violates M2.b
        against any obstacle. Returns min gap if violated, else None.
        Checks both cross-net AND same-net non-overlapping shapes,
        because DRC space() checks all M2 shape pairs."""
        bhw = bw // 2
        bx1, bx2 = bx - bhw, bx + bhw
        worst = None
        for ox1, oy1, ox2, oy2, onet in _m2_obstacles:
            # Skip if no Y overlap range (with MIN_S margin)
            if by1 >= oy2 + M2_MIN_S or by2 <= oy1 - M2_MIN_S:
                continue
            # Compute gap
            x_gap = max(ox1 - bx2, bx1 - ox2, 0)
            y_gap = max(oy1 - by2, by1 - oy2, 0)
            if x_gap > 0 and y_gap > 0:
                dist = (x_gap ** 2 + y_gap ** 2) ** 0.5
            elif x_gap > 0:
                dist = x_gap
            elif y_gap > 0:
                dist = y_gap
            else:
                # Overlapping shapes: same-net overlap is a merge (ok),
                # but cross-net overlap is a SHORT — worst possible violation.
                if onet != drop_net:
                    dist = 0  # cross-net overlap = zero gap
                else:
                    continue  # same-net merge, no gap
            if dist < M2_MIN_S:
                if worst is None or dist < worst:
                    worst = dist
        return worst

    print(f'  M2 obstacles for underpass spacing: {len(_m2_obstacles)}')

    # ── Pre-compute M3 vbar positions for cross-net overlap check ──
    # A cross-net M3 vbar passing through an exclusion zone edge can
    # physically merge with the Via2 M3 pad, creating a net short.
    _m3_vbar_info = []  # (vbar_x, y_min, y_max, net)
    for _drop in routing.get('power', {}).get('drops', []):
        if _drop['type'] != 'via_stack':
            continue
        _vbar = _drop.get('m3_vbar')
        if not _vbar:
            continue
        _m3_vbar_info.append((
            _vbar[0],
            min(_vbar[1], _vbar[3]),
            max(_vbar[1], _vbar[3]),
            _drop['net']))

    def _check_m3_crossnet_vbar(bx, by, drop_net):
        """Check if Via2 M3 pad at (bx, by) would overlap or be too close
        to any cross-net M3 vbar.  Returns min gap if violation, None ok."""
        hp = VIA2_PAD_M3 // 2   # 190
        vbar_hw = M3_MIN_W // 2  # 100
        worst = None
        for vx, vy1, vy2, vnet in _m3_vbar_info:
            if vnet == drop_net:
                continue
            # Vbar must cover the pad Y range
            if vy1 > by + hp or vy2 < by - hp:
                continue
            # X distance: pad edge to vbar edge
            gap = abs(bx - vx) - hp - vbar_hw
            if gap < M3_MIN_S:
                if worst is None or gap < worst:
                    worst = gap
        return worst

    print(f'  M3 vbar entries for cross-net check: {len(_m3_vbar_info)}')

    # ── Pre-compute signal M3 pad positions (Via2/Via3 from signal routes) ──
    # These pads can merge with power M3 jog bars, creating net bridges.
    _signal_m3_pads = []  # (cx, cy, net_name)
    for _sn, _sr in routing.get('signal_routes', {}).items():
        for _seg in _sr.get('segments', []):
            if len(_seg) < 5:
                continue
            _lyr = _seg[4]
            if _lyr in (-2, -3):  # Via2 or Via3 — both create M3 pads
                _signal_m3_pads.append((_seg[0], _seg[1], _sn))
    for _sn, _sr in routing.get('pre_routes', {}).items():
        for _seg in _sr.get('segments', []):
            if len(_seg) < 5:
                continue
            _lyr = _seg[4]
            if _lyr in (-2, -3):
                _signal_m3_pads.append((_seg[0], _seg[1], _sn))

    def _check_m3_jog_signal_overlap(bx, pin_x, gy, gy_in_excl):
        """Check if M3 jog bar from pin_x to bx at center gy (height
        VIA2_PAD_M3) would overlap with any signal M3 pad.
        Returns True if overlap found."""
        if bx == pin_x or gy_in_excl:
            return False  # no jog needed / edge suppressed
        jx1 = min(bx, pin_x)
        jx2 = max(bx, pin_x)
        jog_hp = VIA2_PAD_M3 // 2  # 190
        jy1 = gy - jog_hp
        jy2 = gy + jog_hp
        pad_hp = VIA2_PAD_M3 // 2  # 190 (signal via M3 pad half-size)
        for sx, sy, sn in _signal_m3_pads:
            sx1 = sx - pad_hp
            sx2 = sx + pad_hp
            sy1 = sy - pad_hp
            sy2 = sy + pad_hp
            if sx2 > jx1 and sx1 < jx2 and sy2 > jy1 and sy1 < jy2:
                return True
        return False

    print(f'  Signal M3 pads for jog overlap check: {len(_signal_m3_pads)}')

    # Power drops
    drop_count = 0
    _tm1_drops = []  # collect (x, y, net) for TM1 stripe drawing
    for drop in routing.get('power', {}).get('drops', []):
        dtype = drop['type']
        if dtype == 'via_access':
            # M2 vbar from via2 toward pin
            vb = drop['m2_vbar']
            vbar(top, li_m2, vb[0], vb[1], vb[3], M2_SIG_W)
            # Register via_access M2 vbar as obstacle
            va_hw = M2_SIG_W // 2
            _m2_obstacles.append((
                vb[0] - va_hw, min(vb[1], vb[3]),
                vb[0] + va_hw, max(vb[1], vb[3]),
                drop['net']))
            # M2 jog connecting vbar to access pad — use VIA1_PAD width
            # to match M2 pad height and avoid M2.b notch violations
            if 'm2_jog' in drop:
                jog = drop['m2_jog']
                hbar(top, li_m2, jog[0], jog[2], jog[1], VIA1_PAD)
            # M2 fill: bridge the gap between vbar right edge and pad left edge
            # (vbar at offset X, pad centered on pin — 30nm gap without fill)
            _fill_vbar_to_pad(top, li_m2, vb, drop, routing)
            # Via2 at rail
            v2 = drop['via2_pos']
            via2(top, li_v2, li_m2, li_m3, v2[0], v2[1])
            # Register via2 M2 pad as obstacle
            v2_hp = VIA2_PAD_M2 // 2
            _m2_obstacles.append((
                v2[0] - v2_hp, v2[1] - v2_hp,
                v2[0] + v2_hp, v2[1] + v2_hp,
                drop['net']))
        elif dtype == 'via_stack':
            drop_net = drop['net']
            # Find nearest same-net rail (multi-rail support)
            target_rail = None
            pin_y = drop['via2_pos'][1]
            best_dist = float('inf')
            for _rid, _rl in all_rails.items():
                if _rl.get('net', _rid) != drop_net:
                    continue
                d = abs(_rl['y'] - pin_y)
                if d < best_dist:
                    best_dist = d
                    target_rail = _rl
            # Via1 at pin
            v1 = drop['via1_pos']
            via1(top, li_v1, li_m1, li_m2, v1[0], v1[1])
            # Register via1 M2 pad as obstacle
            v1_hp = VIA1_PAD // 2
            _m2_obstacles.append((
                v1[0] - v1_hp, v1[1] - v1_hp,
                v1[0] + v1_hp, v1[1] + v1_hp,
                drop_net))

            # M2 jog connecting via1 (at pin X) to offset via2
            if 'm2_jog' in drop:
                jog = drop['m2_jog']
                hbar(top, li_m2, jog[0], jog[2], jog[1], VIA1_PAD)

            if 'm3_vbar' not in drop or target_rail is None:
                # No M3 rail — draw via2 + full via stack to TM1
                v2 = drop['via2_pos']
                via2(top, li_v2, li_m2, li_m3, v2[0], v2[1])
                # Via stack: M3 pad → Via3 → M4 → Via4 → M5 → TopVia1
                # (TM1 stripe drawn separately after all drops)
                via3(top, li_v3, li_m3, li_m4, v2[0], v2[1])
                via4(top, li_v4, li_m4, li_m5, v2[0], v2[1])
                # M5 vbar from drop to rail_y, TopVia1 at rail_y (inside TM1 stripe).
                # Don't draw TM1 pad at drop — would overlap cross-net stripes.
                _drop_rail_y = drop.get('rail_y')
                if _drop_rail_y is not None:
                    # M5 vbar — merge with same-net M5 to avoid M5.b notch
                    _m5_hw = VIA4_PAD_M5 // 2
                    _m5_y1 = min(v2[1], _drop_rail_y)
                    _m5_y2 = max(v2[1], _drop_rail_y)
                    _m5_x1 = v2[0] - _m5_hw
                    _m5_x2 = v2[0] + _m5_hw
                    # Extend to merge with nearby same-net M5 shapes
                    _m5_search = klayout.db.Box(_m5_x1 - M5_MIN_S, _m5_y1,
                                                _m5_x2 + M5_MIN_S, _m5_y2)
                    for _es in top.shapes(li_m5).each_overlapping(_m5_search):
                        if _es.is_box():
                            _eb = _es.box
                            # Check Y overlap (must share vertical range)
                            if _eb.top > _m5_y1 and _eb.bottom < _m5_y2:
                                # Extend X to cover this shape (merge)
                                _m5_x1 = min(_m5_x1, _eb.left)
                                _m5_x2 = max(_m5_x2, _eb.right)
                    top.shapes(li_m5).insert(klayout.db.Box(_m5_x1, _m5_y1, _m5_x2, _m5_y2))
                    _hs_tv1 = TV1_SIZE // 2
                    _hp_m5_tv1 = _hs_tv1 + TV1_ENC_M5
                    top.shapes(li_tv1).insert(klayout.db.Box(
                        v2[0] - _hs_tv1, _drop_rail_y - _hs_tv1,
                        v2[0] + _hs_tv1, _drop_rail_y + _hs_tv1))
                    top.shapes(li_m5).insert(klayout.db.Box(
                        v2[0] - _hp_m5_tv1, _drop_rail_y - _hp_m5_tv1,
                        v2[0] + _hp_m5_tv1, _drop_rail_y + _hp_m5_tv1))
                _tm1_drops.append((v2[0], v2[1], drop_net))
            else:
                m3v = drop['m3_vbar']
                pin_x = m3v[0]
                pin_y = drop['via2_pos'][1]
                rail_y = target_rail['y']
                vbar_y1 = min(m3v[1], m3v[3])  # truncated by power.py
                vbar_y2 = max(m3v[1], m3v[3])

                # Collect exclusion zones (other nets' M3 rails)
                # Clearance = rail half-width + M3.e spacing + VIA2 pad half
                # M3.e (240nm) applies because rails are > 390nm wide and
                # bridge pads create > 1µm parallel run along the rail edge.
                hp_v2 = VIA2_PAD_M3 // 2
                excl = []
                for rn, rl in all_rails.items():
                    if rl.get('net', rn) == drop_net:
                        continue
                    rh = rl['width'] // 2
                    ry_lo = rl['y'] - rh - M3_WIDE_S - hp_v2
                    ry_hi = rl['y'] + rh + M3_WIDE_S + hp_v2
                    if ry_lo < vbar_y2 and ry_hi > vbar_y1:
                        excl.append((ry_lo, ry_hi))
                excl.sort()

                if not excl:
                    # No crossing — draw via2 at pin + M3 vbar
                    v2 = drop['via2_pos']
                    # Check M3 pad vs cross-net vbar AND cross-net rail
                    _skip_m3 = _m3_pad_near_xnet_rail(v2[0], v2[1], drop_net)
                    if not _skip_m3:
                        _hp_v2_m3 = VIA2_PAD_M3 // 2
                        for _vn, _vx, _vy1, _vy2 in _m3_vbar_index:
                            if _vn == drop_net:
                                continue
                            _vhw = M3_MIN_W // 2
                            if (v2[0] + _hp_v2_m3 > _vx - _vhw and
                                    v2[0] - _hp_v2_m3 < _vx + _vhw and
                                    v2[1] + _hp_v2_m3 > _vy1 and
                                    v2[1] - _hp_v2_m3 < _vy2):
                                _skip_m3 = True
                                break
                    if _skip_m3:
                        via2_cut_m2(top, li_v2, li_m2, v2[0], v2[1])
                    else:
                        via2(top, li_v2, li_m2, li_m3, v2[0], v2[1])
                    vbar(top, li_m3, pin_x, vbar_y1, vbar_y2, M3_MIN_W)
                else:
                    # M3 vbar crosses rails — draw M3 segments with gaps,
                    # bridge gaps with M2 underpass (via2 at gap edges)
                    # Pin via2 only if pin is NOT inside an exclusion zone
                    pin_in_excl = any(e[0] <= pin_y <= e[1] for e in excl)
                    if not pin_in_excl:
                        if _m3_pad_near_xnet_rail(pin_x, pin_y, drop_net):
                            via2_cut_m2(top, li_v2, li_m2, pin_x, pin_y)
                        else:
                            via2(top, li_v2, li_m2, li_m3, pin_x, pin_y)

                    # Draw M3 segments in gaps between exclusion zones
                    seg_y1 = vbar_y1
                    gap_entries = []
                    for ey1, ey2 in excl:
                        if ey1 > seg_y1:
                            vbar(top, li_m3, pin_x, seg_y1, ey1, M3_MIN_W)
                        gap_entries.append((max(seg_y1, ey1), ey2))
                        seg_y1 = max(seg_y1, ey2)
                    if seg_y1 < vbar_y2:
                        vbar(top, li_m3, pin_x, seg_y1, vbar_y2, M3_MIN_W)

                    # Bridge each gap with M2 underpass
                    # Check M2 signal conflicts and shift bridge X if needed
                    hp_m3_gap = VIA2_PAD_M3 // 2  # M3 pad size for rail proximity
                    # M2 underpass uses via2_no_m2_pad (no M2 pad) — the M2
                    # footprint is just the narrow vbar (M2_MIN_W).
                    hp_m2 = M2_MIN_W // 2          # actual M2 half-width for conflict
                    for gy1, gy2 in gap_entries:
                        # Check if M3 vbar segments exist on each side of gap.
                        # If the vbar endpoint (pin_y or rail_y) is inside the
                        # gap, Via2 at the far edge has no M3 to connect to and
                        # would create a floating pad that merges with the
                        # cross-net rail, causing a net short.
                        has_m3_below = gy1 > vbar_y1  # M3 segment below gap
                        has_m3_above = gy2 < vbar_y2  # M3 segment above gap
                        # Mark edges with no M3 as "in excl" to suppress Via2
                        gy1_no_m3 = not has_m3_below
                        gy2_no_m3 = not has_m3_above

                        # Determine if each gap edge is inside an excl zone
                        # (i.e. M3 pad at that point would short to a rail)
                        gy1_in_excl = gy1_no_m3 or any(
                            (rl['y'] - rl['width']//2) < gy1 + hp_m3_gap
                            and (rl['y'] + rl['width']//2) > gy1 - hp_m3_gap
                            for rn, rl in all_rails.items()
                            if rl.get('net', rn) != drop_net
                        )
                        gy2_in_excl = gy2_no_m3 or any(
                            (rl['y'] - rl['width']//2) < gy2 + hp_m3_gap
                            and (rl['y'] + rl['width']//2) > gy2 - hp_m3_gap
                            for rn, rl in all_rails.items()
                            if rl.get('net', rn) != drop_net
                        )

                        # If BOTH edges have no M3, skip the underpass
                        if gy1_no_m3 and gy2_no_m3:
                            continue

                        # Check if M2 bridge at pin_x physically overlaps
                        # signal M2 wires (original check — prevents shorts)
                        bridge_x = pin_x
                        has_conflict = False
                        for sx1, sy1, sx2, sy2 in m2_signal_segs:
                            sw = M2_SIG_W // 2
                            if sx1 == sx2:  # M2 vertical
                                if ((sx1 - sw) < bridge_x + hp_m2
                                        and (sx1 + sw) > bridge_x - hp_m2):
                                    slo, shi = min(sy1, sy2), max(sy1, sy2)
                                    if slo < gy2 and shi > gy1:
                                        has_conflict = True
                                        break
                            elif sy1 == sy2:  # M2 horizontal
                                if gy1 < sy1 < gy2:
                                    slo_x = min(sx1, sx2)
                                    shi_x = max(sx1, sx2)
                                    if ((slo_x - sw) < bridge_x + hp_m2
                                            and (shi_x + sw) > bridge_x - hp_m2):
                                        has_conflict = True
                                        break

                        if has_conflict:
                            # Shift bridge X left by 1600nm to clear conflict
                            bridge_x = pin_x - 1600
                            print(f'    M2 bridge shifted x={pin_x}->{bridge_x} '
                                  f'for gap y={gy1}-{gy2}')

                        # ── M2.b + M3 cross-net vbar spacing enforcement ──
                        # Check underpass M2 body against cross-net M2 obstacles,
                        # via2 partial overlap, AND M3 cross-net vbar proximity
                        # (prevents net shorts from Via2 M3 pad merging with a
                        # cross-net vbar passing near the exclusion zone edge).
                        vbar_y1_t = gy1 - _VIA2_M2_ENDCAP
                        vbar_y2_t = gy2 + _VIA2_M2_ENDCAP
                        if gy2_no_m3 and pin_y < gy2:
                            vbar_y2_t = pin_y + _VIA2_M2_ENDCAP
                        if gy1_no_m3 and pin_y > gy1:
                            vbar_y1_t = pin_y - _VIA2_M2_ENDCAP
                        vio = _check_m2b_spacing(
                            bridge_x, vbar_y1_t, vbar_y2_t,
                            M2_MIN_W, drop_net)
                        v2_overlap = _check_via2_overlap(
                            bridge_x, gy1, gy2,
                            gy1_in_excl, gy2_in_excl)
                        # Check Via2 M3 pad vs cross-net M3 vbars
                        m3_vbar_vio = None
                        for _ey in (gy1, gy2):
                            _ie = (gy1_in_excl if _ey == gy1
                                   else gy2_in_excl)
                            if _ie:
                                continue
                            _mv = _check_m3_crossnet_vbar(
                                bridge_x, _ey, drop_net)
                            if _mv is not None:
                                if m3_vbar_vio is None or _mv < m3_vbar_vio:
                                    m3_vbar_vio = _mv
                        # Check M3 jog bar vs signal M3 pads
                        m3_jog_overlap = False
                        if bridge_x != pin_x:
                            for _ey in (gy1, gy2):
                                _ie = (gy1_in_excl if _ey == gy1
                                       else gy2_in_excl)
                                if _check_m3_jog_signal_overlap(
                                        bridge_x, pin_x, _ey, _ie):
                                    m3_jog_overlap = True
                                    break
                        if (vio is not None or v2_overlap
                                or m3_vbar_vio is not None
                                or m3_jog_overlap):
                            # Try alternative X positions: ±350, ±700, ...
                            # Collect ALL M2.b-clean candidates, then pick
                            # the one with best M3.b score (tiebreaker).
                            m2_clean_cands = []   # [(x, m3b_gap)]
                            # Fallback tier: candidates that pass M2 checks
                            # but have M3 vbar proximity (gap > 0, DRC only,
                            # NOT LVS short).  Used when pin_x has M2 overlap.
                            _m3v_drc_cands = []   # [(x, m3v_gap)]
                            best_x = bridge_x
                            best_vio = vio if vio is not None else 0
                            best_v2ok = not v2_overlap
                            for step in range(1, 9):
                                for sign in (-1, +1):
                                    cand_x = pin_x + sign * step * MAZE_GRID
                                    # Check signal wire overlap at candidate
                                    cand_conflict = False
                                    for sx1, sy1, sx2, sy2 in m2_signal_segs:
                                        sw = M2_SIG_W // 2
                                        if sx1 == sx2:
                                            if ((sx1 - sw) < cand_x + hp_m2
                                                    and (sx1 + sw) > cand_x - hp_m2):
                                                slo = min(sy1, sy2)
                                                shi = max(sy1, sy2)
                                                if slo < gy2 and shi > gy1:
                                                    cand_conflict = True
                                                    break
                                        elif sy1 == sy2:
                                            if gy1 < sy1 < gy2:
                                                slo_x = min(sx1, sx2)
                                                shi_x = max(sx1, sx2)
                                                if ((slo_x - sw) < cand_x + hp_m2
                                                        and (shi_x + sw) > cand_x - hp_m2):
                                                    cand_conflict = True
                                                    break
                                    if cand_conflict:
                                        continue
                                    # Check via2 partial overlap
                                    if _check_via2_overlap(
                                            cand_x, gy1, gy2,
                                            gy1_in_excl, gy2_in_excl):
                                        continue
                                    # Check M3 cross-net vbar proximity
                                    _cand_m3v = None
                                    for _ey in (gy1, gy2):
                                        _ie = (gy1_in_excl if _ey == gy1
                                               else gy2_in_excl)
                                        if _ie:
                                            continue
                                        _cmv = _check_m3_crossnet_vbar(
                                            cand_x, _ey, drop_net)
                                        if _cmv is not None:
                                            if (_cand_m3v is None
                                                    or _cmv < _cand_m3v):
                                                _cand_m3v = _cmv
                                    if _cand_m3v is not None:
                                        # M3 vbar proximity violation.
                                        # If gap > 0, it's DRC-only (shapes
                                        # separate, no LVS short). Track as
                                        # fallback for when pin_x has M2
                                        # overlap.
                                        if _cand_m3v > 0:
                                            # Also need M3 jog + M2.b clean
                                            _fb_jog_ok = True
                                            if cand_x != pin_x:
                                                for _ey in (gy1, gy2):
                                                    _ie = (gy1_in_excl
                                                           if _ey == gy1
                                                           else gy2_in_excl)
                                                    if _check_m3_jog_signal_overlap(
                                                            cand_x, pin_x,
                                                            _ey, _ie):
                                                        _fb_jog_ok = False
                                                        break
                                            if _fb_jog_ok:
                                                _fb_cv = _check_m2b_spacing(
                                                    cand_x, vbar_y1_t,
                                                    vbar_y2_t, M2_MIN_W,
                                                    drop_net)
                                                if _fb_cv is None:
                                                    _m3v_drc_cands.append(
                                                        (cand_x, _cand_m3v))
                                        continue
                                    # Check M3 jog bar vs signal M3 pads
                                    _cand_jog_overlap = False
                                    if cand_x != pin_x:
                                        for _ey in (gy1, gy2):
                                            _ie = (gy1_in_excl if _ey == gy1
                                                   else gy2_in_excl)
                                            if _check_m3_jog_signal_overlap(
                                                    cand_x, pin_x, _ey, _ie):
                                                _cand_jog_overlap = True
                                                break
                                    if _cand_jog_overlap:
                                        continue
                                    cv = _check_m2b_spacing(
                                        cand_x, vbar_y1_t, vbar_y2_t,
                                        M2_MIN_W, drop_net)
                                    if cv is None:
                                        # M2.b clean — evaluate M3.b
                                        cm3 = None
                                        for _by in (gy1, gy2):
                                            _ie = (gy1_in_excl if _by == gy1
                                                   else gy2_in_excl)
                                            if not _ie:
                                                _g = _check_m3b_bridge(
                                                    cand_x, _by, drop_net)
                                                if _g is not None:
                                                    cm3 = (_g if cm3 is None
                                                           else min(cm3, _g))
                                        m2_clean_cands.append((cand_x, cm3))
                                    elif cv > best_vio:
                                        best_x = cand_x
                                        best_vio = cv
                                        best_v2ok = True

                            if m2_clean_cands:
                                # Prefer M3.b-clean, else largest M3.b gap
                                m3_clean = [(x, g) for x, g in m2_clean_cands
                                            if g is None]
                                if m3_clean:
                                    # Among M3.b-clean, pick closest to pin_x
                                    best_x = min(m3_clean,
                                                 key=lambda t: abs(t[0] - pin_x))[0]
                                else:
                                    # All M2.b-clean have M3.b violations.
                                    # Check if pin_x is M3.b-clean; if so,
                                    # keep pin_x (accept M2.b) rather than
                                    # shift and create M3.b violation.
                                    pin_m3b = None
                                    for _by in (gy1, gy2):
                                        _ie = (gy1_in_excl if _by == gy1
                                               else gy2_in_excl)
                                        if not _ie:
                                            _g = _check_m3b_bridge(
                                                pin_x, _by, drop_net)
                                            if _g is not None:
                                                pin_m3b = (_g if pin_m3b is None
                                                           else min(pin_m3b, _g))
                                    if pin_m3b is None:
                                        # pin_x is M3.b-clean — keep it
                                        best_x = bridge_x  # no change
                                    else:
                                        best_x = max(m2_clean_cands,
                                                     key=lambda t: t[1])[0]
                                best_vio = None
                                best_v2ok = True

                            if best_x != bridge_x:
                                if m3_jog_overlap:
                                    reason = 'M3-jog'
                                elif m3_vbar_vio is not None:
                                    reason = 'M3-vbar'
                                elif vio is not None:
                                    reason = 'M2.b'
                                else:
                                    reason = 'V2.a'
                                print(f'    {reason} spacing: shifted x='
                                      f'{bridge_x}->{best_x} '
                                      f'for {drop_net} gap y={gy1}-{gy2}')
                                bridge_x = best_x
                            elif (m3_jog_overlap
                                  and bridge_x != pin_x):
                                # No clean candidate found but jog overlap
                                # creates net short — fall back to pin_x
                                # UNLESS pin_x has M2 overlap (LVS short).
                                pin_m2v = _check_m2b_spacing(
                                    pin_x, vbar_y1_t, vbar_y2_t,
                                    M2_MIN_W, drop_net)
                                if pin_m2v is not None and pin_m2v == 0:
                                    # pin_x has M2 overlap → LVS short.
                                    # Use DRC-only fallback (M3 vbar
                                    # proximity > 0 but < M3_MIN_S) if
                                    # available — DRC violation beats
                                    # LVS short.
                                    if _m3v_drc_cands:
                                        # Pick candidate with largest
                                        # M3 vbar gap (least DRC impact)
                                        fb = max(_m3v_drc_cands,
                                                 key=lambda t: t[1])
                                        print(
                                            f'    M2-overlap guard: '
                                            f'pin_x={pin_x} has M2 '
                                            f'overlap, using x={fb[0]} '
                                            f'(M3v gap={fb[1]}nm) '
                                            f'for {drop_net} gap '
                                            f'y={gy1}-{gy2}')
                                        bridge_x = fb[0]
                                    else:
                                        print(
                                            f'    WARNING: no safe M2 '
                                            f'position for {drop_net} '
                                            f'gap y={gy1}-{gy2} — '
                                            f'pin_x={pin_x} has M2 '
                                            f'overlap, skipping '
                                            f'underpass')
                                        continue
                                else:
                                    print(
                                        f'    M3-jog fallback: '
                                        f'x={bridge_x}->{pin_x} '
                                        f'(LVS priority) '
                                        f'for {drop_net} gap '
                                        f'y={gy1}-{gy2}')
                                    bridge_x = pin_x

                        # De-duplicate: skip if same underpass already drawn
                        ukey = (bridge_x, gy1, gy2)
                        if ukey in _drawn_m2_underpasses:
                            continue
                        _drawn_m2_underpasses.add(ukey)

                        # Draw via2 at gap edges — skip if edge is inside
                        # another net's rail (would short M3).
                        # Use via2_no_m2_pad: M2 coverage comes from the
                        # extended vbar below (saves 95nm clearance per side).
                        _hp_v2m3 = VIA2_PAD_M3 // 2
                        for _gy, _gy_in_excl in ((gy1, gy1_in_excl),
                                                  (gy2, gy2_in_excl)):
                            if _gy_in_excl:
                                continue
                            # Check: would M3 pad overlap cross-net M3 vbar?
                            _m3_xnet = False
                            for _vn, _vx, _vy1, _vy2 in _m3_vbar_index:
                                if _vn == drop_net:
                                    continue
                                _vhw = M3_MIN_W // 2
                                if (bridge_x + _hp_v2m3 > _vx - _vhw and
                                        bridge_x - _hp_v2m3 < _vx + _vhw and
                                        _gy + _hp_v2m3 > _vy1 and
                                        _gy - _hp_v2m3 < _vy2):
                                    _m3_xnet = True
                                    break
                            if _m3_xnet:
                                # Skip M3 pad — vbar provides M3 coverage
                                via2_cut_only(top, li_v2, bridge_x, _gy)
                            else:
                                via2_no_m2_pad(top, li_v2, li_m3,
                                               bridge_x, _gy)
                            _drawn_via2_positions.add((bridge_x, _gy))
                            if not _m3_xnet:
                                _gap_bridge_m3_pads.append(
                                    (bridge_x, _gy, drop_net))

                        # M2 vbar extended by endcap distance at each end
                        # to provide V2.c1 enclosure (50nm) for via2 cuts.
                        # If one edge has no M3, truncate M2 to pin_y instead
                        # of extending to the far gap edge.
                        m2_y1 = gy1 - _VIA2_M2_ENDCAP
                        m2_y2 = gy2 + _VIA2_M2_ENDCAP
                        if gy2_no_m3 and pin_y < gy2:
                            m2_y2 = pin_y + _VIA2_M2_ENDCAP
                        if gy1_no_m3 and pin_y > gy1:
                            m2_y1 = pin_y - _VIA2_M2_ENDCAP
                        vbar(top, li_m2, bridge_x, m2_y1, m2_y2, M2_MIN_W)

                        # Register this underpass as an M2 obstacle for
                        # subsequent underpasses (cross-net spacing)
                        uhw = M2_MIN_W // 2
                        _m2_obstacles.append((
                            bridge_x - uhw, m2_y1,
                            bridge_x + uhw, m2_y2,
                            drop_net))

                        # If bridge_x shifted, add M3 jogs to connect back
                        if bridge_x != pin_x:
                            hp_v2m3 = VIA2_PAD_M3 // 2
                            jx1 = min(bridge_x, pin_x)
                            jx2 = max(bridge_x, pin_x)
                            # Only draw M3 jog if that edge is not in excl
                            if not gy1_in_excl:
                                hbar(top, li_m3, jx1, jx2, gy1,
                                     VIA2_PAD_M3)
                                _gap_bridge_m3_jogs.append(
                                    (jx1, gy1 - hp_v2m3, jx2,
                                     gy1 + hp_v2m3, drop_net))
                            if not gy2_in_excl:
                                hbar(top, li_m3, jx1, jx2, gy2,
                                     VIA2_PAD_M3)
                                _gap_bridge_m3_jogs.append(
                                    (jx1, gy2 - hp_v2m3, jx2,
                                     gy2 + hp_v2m3, drop_net))
        drop_count += 1
    print(f'  Drew {drop_count} power drops')

    # ── TM1 power stripes ──
    # Group drops by net+rail_y → each group shares a TM1 horizontal stripe.
    # Use original rail Y positions from routing.json for stripe placement.
    _orig_rails = routing.get('power', {}).get('rails', {})
    _tm1_stripe_count = 0
    li_tm1_lbl = layout.layer(126, 25)  # TM1 text for LVS net naming
    if _tm1_drops:
        # Group drops by net
        _drops_by_net = {}
        for dx, dy, dn in _tm1_drops:
            _drops_by_net.setdefault(dn, []).append((dx, dy))
        # For each net, find the closest original rail Y → draw TM1 stripe there
        _tm1_hw = TM1_MIN_W // 2  # 820nm half-width
        for net, positions in _drops_by_net.items():
            # Find matching rail Y positions for this net
            net_rails = [(rid, rl) for rid, rl in _orig_rails.items()
                         if rl.get('net', rid) == net]
            # Group drops to nearest rail
            rail_groups = {}  # rail_y → [drop positions]
            for px, py in positions:
                best_ry = None
                best_d = float('inf')
                for rid, rl in net_rails:
                    d = abs(rl['y'] - py)
                    if d < best_d:
                        best_d = d
                        best_ry = rl['y']
                if best_ry is not None:
                    rail_groups.setdefault(best_ry, []).append((px, py))
            # Draw TM1 stripe for each rail group
            for ry, drops in rail_groups.items():
                xs = [p[0] for p in drops]
                x1 = min(xs) - _tm1_hw
                x2 = max(xs) + _tm1_hw
                # Ensure stripe is at least TM1_MIN_W wide
                if x2 - x1 < TM1_MIN_W:
                    mid = (x1 + x2) // 2
                    x1 = mid - _tm1_hw
                    x2 = mid + _tm1_hw
                hbar(top, li_tm1, x1, x2, ry, TM1_MIN_W)
                # Label on TM1 for LVS
                mid_x = (x1 + x2) // 2
                top.shapes(li_tm1_lbl).insert(klayout.db.Text(
                    net, klayout.db.Trans(klayout.db.Point(mid_x, ry))))
                _tm1_stripe_count += 1
    print(f'  TM1 stripes: {_tm1_stripe_count} ({len(_tm1_drops)} drops)')

    # ── Multi-rail bridges (connect same-net M3 rails via M2 underpass) ──
    _draw_rail_bridges(top, li_m2, li_v2, li_m3, all_rails, m2_signal_segs)

    # ── M3 cross-net rail proximity cleanup ──
    # Remove non-rail M3 shapes within M3_MIN_S of a cross-net power rail.
    # These shapes (Via2 pads, vbar segments, stubs) can bridge gnd↔vdd
    # through the ptap→pwell global network + M3 proximity.
    _m3_xnet_removed = 0
    _rail_zones = []  # (y1, y2, family)
    for _rn, _rl in all_rails.items():
        _rh = _rl['width'] // 2
        _rfam = 'gnd' if 'gnd' in _rl.get('net', _rn) else 'vdd'
        _rail_zones.append((_rl['y'] - _rh, _rl['y'] + _rh, _rfam))
    # Build M3 family markers: vbar bodies + Via2 pad envelopes + Via1 X positions
    _m3_family_markers = []  # (xl, yb, xr, yt, family)
    for _d in routing.get('power', {}).get('drops', []):
        _dfam = 'gnd' if 'gnd' in _d['net'] else 'vdd'
        _m3v = _d.get('m3_vbar')
        if _m3v and _m3v[1] != _m3v[3]:
            _vhw = M3_MIN_W // 2
            _m3_family_markers.append((_m3v[0] - _vhw,
                min(_m3v[1], _m3v[3]), _m3v[0] + _vhw,
                max(_m3v[1], _m3v[3]), _dfam))
        _v2 = _d.get('via2_pos')
        if _v2:
            _hp = VIA2_PAD_M3 // 2
            _m3_family_markers.append((_v2[0] - _hp, _v2[1] - _hp,
                _v2[0] + _hp, _v2[1] + _hp, _dfam))
    for _si in list(top.shapes(li_m3)):
        _b = _si.bbox()
        if _b.width() > 100000:
            continue  # skip rails
        # Determine shape's net family from markers (vbar + Via2 pad)
        _sfam = None
        for _mx1, _my1, _mx2, _my2, _mfam in _m3_family_markers:
            if (_b.left <= _mx2 and _b.right >= _mx1 and
                    _b.bottom <= _my2 and _b.top >= _my1):
                _sfam = _mfam
                break
        if _sfam is None:
            continue  # can't determine family
        _removed = False
        # Check against cross-net rails
        for _ry1, _ry2, _rfam in _rail_zones:
            if _rfam == _sfam:
                continue
            _dist_above = _b.bottom - _ry2
            _dist_below = _ry1 - _b.top
            if (0 <= _dist_above <= M3_MIN_S or
                    0 <= _dist_below <= M3_MIN_S or
                    (_dist_above < 0 and _dist_below < 0)):
                _si.delete()
                _m3_xnet_removed += 1
                _removed = True
                break
        if _removed:
            continue
        # Check against cross-net M3 vbars (the main bridge mechanism:
        # ptap→pwell global network extends gnd M3 chain near vdd M3 vbars)
        for _vn, _vx, _vy1, _vy2 in _m3_vbar_index:
            _vfam = 'gnd' if 'gnd' in _vn else 'vdd'
            if _vfam == _sfam:
                continue
            _vhw = M3_MIN_W // 2
            _x_gap = max(_b.left - (_vx + _vhw), (_vx - _vhw) - _b.right)
            if _x_gap > M3_MIN_S:
                continue
            _y_ov = min(_b.top, _vy2) - max(_b.bottom, _vy1)
            if _y_ov <= 0:
                continue
            if _x_gap < M3_MIN_S:
                _si.delete()
                _m3_xnet_removed += 1
                break
    if _m3_xnet_removed:
        print(f'  M3 cross-net rail cleanup: {_m3_xnet_removed} shapes removed')



    return drop_count, _gap_bridge_m3_pads, _gap_bridge_m3_jogs, m2_signal_segs
