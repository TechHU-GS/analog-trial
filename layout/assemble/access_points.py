"""§3: Draw access points (Via1 + M1 pad + M2 pad + M1 stub)."""

import klayout.db

from atk.pdk import (
    M1_MIN_S, M1_MIN_W, M1_SIG_W, M2_MIN_S, M2_MIN_W, UM,
    VIA1_PAD, VIA1_PAD_M1, VIA1_GDS_M1, VIA1_GDS_M2, M1_MIN_AREA,
    s5,
)
from atk.route.maze_router import M1_LYR, M2_LYR, M3_LYR, M4_LYR


def draw_access_points(top, li_m1, li_m2, li_v1, layout,
                       instances, routing, device_lib, devices_map,
                       pin_net_map, drawn_vias, ap_m1_obs):
    """Draw access point Via1 + M1/M2 pads for all routed pins.

    Returns:
        ap_count: number of APs drawn
        m2_route_wires: list of M2 wire boxes for cross-net checking
    """
    from assemble_gds import via1, draw_rect

    # ═══ 3. Draw access points ═══
    print('\n  === Drawing access points ===')

    # Build set of via_stack pins (they skip access point drawing)
    via_stack_pins = set()
    for drop in routing.get('power', {}).get('drops', []):
        if drop['type'] == 'via_stack':
            via_stack_pins.add(f"{drop['inst']}.{drop['pin']}")

    # Build cross-net M2 routing wire obstacles (for AP M2 pad shrink).
    # Collects all M2 wire segments from signal/pre-routes tagged with net.
    pin_net_map = {}
    for _rn, _rd in routing.get('signal_routes', {}).items():
        for pin in _rd.get('pins', []):
            pin_net_map[pin] = _rn
    for _rn, _rd in routing.get('pre_routes', {}).items():
        for pin in _rd.get('pins', []):
            pin_net_map[pin] = _rn
    _m2_route_wires = []  # (x1, y1, x2, y2, net_name)
    _hw_sig = M1_SIG_W // 2
    for route_dict in [routing.get('signal_routes', {}),
                       routing.get('pre_routes', {})]:
        for _rnet, _rd in route_dict.items():
            for seg in _rd.get('segments', []):
                if seg[4] == M2_LYR:
                    x1, y1, x2, y2 = seg[:4]
                    if x1 == x2:
                        _m2_route_wires.append(
                            (x1 - _hw_sig, min(y1, y2),
                             x1 + _hw_sig, max(y1, y2), _rnet))
                    elif y1 == y2:
                        _m2_route_wires.append(
                            (min(x1, x2), y1 - _hw_sig,
                             max(x1, x2), y1 + _hw_sig, _rnet))
    # V1 enclosure margins for minimum AP M2 pad
    _V1_ENDCAP = 50  # V1.c1 nm

    # Routing via1 positions per net — used to extend AP M1 pads when
    # routing via is offset from AP center (grid quantization artifact).
    _via1_per_net = {}  # net → [(vx, vy)]
    for _rd_name in ('signal_routes', 'pre_routes'):
        for _rnet, _rd in routing.get(_rd_name, {}).items():
            for _seg in _rd.get('segments', []):
                if len(_seg) >= 5 and _seg[4] == -1:  # via1
                    _via1_per_net.setdefault(_rnet, []).append((_seg[0], _seg[1]))

    # drawn_vias already contains gate-contact Via1 positions from section 1c.
    # Now add access-point Via1 positions.
    gate_via_count = len(drawn_vias)

    ap_count = 0
    _ap_m2_shrink = 0
    for key, ap in routing.get('access_points', {}).items():
        is_via_stack = key in via_stack_pins
        vp = ap.get('via_pad')
        skip_m1 = ap.get('mode') == 'gate_no_m1'
        if vp and not is_via_stack:
            if 'via1' in vp:
                draw_rect(top, li_v1, vp['via1'])
                v = vp['via1']
                drawn_vias.add(((v[0] + v[2]) // 2, (v[1] + v[3]) // 2))
            if 'm1' in vp and not skip_m1:
                # Gate pins: skip AP M1 pad if PCell already has M1 at
                # the Via1 position (gate contact M1).  The AP pad is
                # 290nm which violates M1.b with adjacent S/D strips
                # (gate sits between S/D, gap ~100-150nm < 180nm).
                _is_gate = '.G' in key
                if _is_gate and 'via1' in vp:
                    _gv = vp['via1']
                    _gvx = (_gv[0] + _gv[2]) // 2
                    _gvy = (_gv[1] + _gv[3]) // 2
                    _gs = klayout.db.Box(_gvx - 50, _gvy - 50,
                                         _gvx + 50, _gvy + 50)
                    if any(True for _ in top.shapes(li_m1).each_overlapping(_gs)):
                        continue  # PCell M1 covers Via1 → skip AP pad
                # Shrink M1 AP pad to VIA1_GDS_M1 (310nm) from routing's
                # VIA1_PAD_M1 (370nm) to reduce M1.b violations
                m1r = vp['m1']
                m1w = m1r[2] - m1r[0]
                m1h = m1r[3] - m1r[1]
                if m1w == VIA1_PAD_M1 and m1h == VIA1_PAD_M1:
                    cx = (m1r[0] + m1r[2]) // 2
                    cy = (m1r[1] + m1r[3]) // 2
                    hp = VIA1_GDS_M1 // 2
                    m1_pad = [cx - hp, cy - hp, cx + hp, cy + hp]
                    # Extend pad when routing via is offset from AP center.
                    # Grid quantization can place the via at a different
                    # position than the AP, creating sub-M1.a protrusions
                    # at the stub-pad-wire junction.
                    stub = ap.get('m1_stub')
                    ap_net = pin_net_map.get(key, '')
                    _ap_via = vp.get('via1')
                    if stub and ap_net and _ap_via:
                        # Find routing via1 closest to AP center on same net
                        _best_via = None
                        _best_dist = float('inf')
                        for _vx, _vy in _via1_per_net.get(ap_net, []):
                            _d = abs(_vx - cx) + abs(_vy - cy)
                            if (_d < _best_dist
                                    and abs(_vx - cx) <= VIA1_PAD_M1
                                    and abs(_vy - cy) <= VIA1_PAD_M1
                                    and (_vx != cx or _vy != cy)):
                                _best_dist = _d
                                _best_via = (_vx, _vy)
                        if _best_via:
                            _vx, _vy = _best_via
                            # Only extend when via center falls outside
                            # the standard pad (large offset).  Small
                            # offsets don't create DRC-visible M1.a.
                            if max(abs(_vx - cx), abs(_vy - cy)) <= hp:
                                _best_via = None
                        if _best_via:
                            _vx, _vy = _best_via
                            # Extend pad to cover both AP and via
                            m1_pad[0] = min(m1_pad[0], _vx - hp)
                            m1_pad[1] = min(m1_pad[1], _vy - hp)
                            m1_pad[2] = max(m1_pad[2], _vx + hp)
                            m1_pad[3] = max(m1_pad[3], _vy + hp)
                            # Wire X extent at via
                            _whw = M1_SIG_W // 2
                            _wl = _vx - _whw
                            _wr = _vx + _whw
                            m1_pad[0] = min(m1_pad[0], _wl)
                            m1_pad[2] = max(m1_pad[2], _wr)
                            # Adjust edges for M1.a at stub junction:
                            # protrusion must be 0 or >= M1_MIN_W.
                            # CONSTRAINT: pad must still enclose AP via
                            # with V1.c1 (50nm endcap) on all sides.
                            _v1ec = 50  # V1.c1 endcap
                            _pad_min_l = _ap_via[0] - _v1ec
                            _pad_min_b = _ap_via[1] - _v1ec
                            _pad_max_r = _ap_via[2] + _v1ec
                            _pad_max_t = _ap_via[3] + _v1ec
                            _sl, _sr = stub[0], stub[2]
                            # Left: snap to wire left if tiny protrusion
                            _dl = _sl - m1_pad[0]
                            if 0 < _dl < M1_MIN_W:
                                m1_pad[0] = min(max(m1_pad[0], _wl),
                                                _pad_min_l)
                            # Right: extend to stub + M1_MIN_W
                            _dr = m1_pad[2] - _sr
                            if 0 < _dr < M1_MIN_W:
                                m1_pad[2] = max(_sr + M1_MIN_W,
                                                _pad_max_r)
                            # Top: extend past stub top
                            _dt = m1_pad[3] - stub[3]
                            if 0 < _dt < M1_MIN_W:
                                m1_pad[3] = max(stub[3] + M1_MIN_W,
                                                _pad_max_t)
                            # Clamp: never shrink below AP via enclosure
                            m1_pad[0] = min(m1_pad[0], _pad_min_l)
                            m1_pad[1] = min(m1_pad[1], _pad_min_b)
                            m1_pad[2] = max(m1_pad[2], _pad_max_r)
                            m1_pad[3] = max(m1_pad[3], _pad_max_t)
                    # Draw pad and stub separately to avoid bridging
                    # adjacent pins' M1 regions. Only merge if they
                    # overlap or gap < M1_MIN_S (would cause M1.b).
                    if stub:
                        _gap_x = max(0, max(stub[0], m1_pad[0])
                                     - min(stub[2], m1_pad[2]))
                        _gap_y = max(0, max(stub[1], m1_pad[1])
                                     - min(stub[3], m1_pad[3]))
                        _gap = max(_gap_x, _gap_y)
                        if _gap < M1_MIN_S:
                            # Close enough — merge to avoid M1.b notch
                            m1_pad[0] = min(m1_pad[0], stub[0])
                            m1_pad[1] = min(m1_pad[1], stub[1])
                            m1_pad[2] = max(m1_pad[2], stub[2])
                            m1_pad[3] = max(m1_pad[3], stub[3])
                        else:
                            # Far apart — draw stub separately
                            draw_rect(top, li_m1, stub)
                    draw_rect(top, li_m1, m1_pad)
                else:
                    # Draw pad; draw stub separately if gap >= M1_MIN_S
                    _m1_draw = list(m1r)
                    if stub:
                        _gap_x = max(0, max(stub[0], _m1_draw[0])
                                     - min(stub[2], _m1_draw[2]))
                        _gap_y = max(0, max(stub[1], _m1_draw[1])
                                     - min(stub[3], _m1_draw[3]))
                        _gap = max(_gap_x, _gap_y)
                        if _gap < M1_MIN_S:
                            _m1_draw[0] = min(_m1_draw[0], stub[0])
                            _m1_draw[1] = min(_m1_draw[1], stub[1])
                            _m1_draw[2] = max(_m1_draw[2], stub[2])
                            _m1_draw[3] = max(_m1_draw[3], stub[3])
                        else:
                            draw_rect(top, li_m1, stub)
                    draw_rect(top, li_m1, _m1_draw)
            if 'm2' in vp:
                m2_rect = vp['m2']
                ap_net = pin_net_map.get(key, '')
                # Check if AP M2 pad overlaps any cross-net M2 routing wire
                _has_xnet_overlap = False
                if ap_net:
                    for wx1, wy1, wx2, wy2, wnet in _m2_route_wires:
                        if wnet != ap_net:
                            if (m2_rect[2] > wx1 and m2_rect[0] < wx2 and
                                    m2_rect[3] > wy1 and m2_rect[1] < wy2):
                                _has_xnet_overlap = True
                                break
                if _has_xnet_overlap and 'via1' in vp:
                    # Shrink M2 pad to minimum Via1 enclosure
                    v1 = vp['via1']
                    m2_min = [v1[0] - _V1_ENDCAP, v1[1] - _V1_ENDCAP,
                              v1[2] + _V1_ENDCAP, v1[3] + _V1_ENDCAP]
                    # Clip M2 pad against cross-net M2 wires to prevent merge
                    for wx1, wy1, wx2, wy2, wnet in _m2_route_wires:
                        if wnet == ap_net:
                            continue
                        # Clip each edge if overlapping
                        if (m2_min[2] > wx1 and m2_min[0] < wx2 and
                                m2_min[3] > wy1 and m2_min[1] < wy2):
                            # Determine which edge to clip
                            clip_r = m2_min[2] - wx1
                            clip_l = wx2 - m2_min[0]
                            clip_t = m2_min[3] - wy1
                            clip_b = wy2 - m2_min[1]
                            # Pick the smallest positive clip
                            clips = [(clip_r, 'r'), (clip_l, 'l'),
                                     (clip_t, 't'), (clip_b, 'b')]
                            clips = [(c, d) for c, d in clips if c > 0]
                            if clips:
                                _, best_dir = min(clips)
                                if best_dir == 'r':
                                    m2_min[2] = wx1 - 5  # 5nm gap (on grid)
                                elif best_dir == 'l':
                                    m2_min[0] = wx2 + 5
                                elif best_dir == 't':
                                    m2_min[3] = wy1 - 5
                                elif best_dir == 'b':
                                    m2_min[1] = wy2 + 5
                    _m2w = m2_min[2] - m2_min[0]
                    _m2h = m2_min[3] - m2_min[1]
                    if (_m2w >= M2_MIN_W and _m2h >= M2_MIN_W
                            and _m2w * _m2h >= 144000):
                        draw_rect(top, li_m2, m2_min)
                    else:
                        pass  # Pad clipped to nothing — dropped (causes M2.c1)
                    _ap_m2_shrink += 1
                else:
                    draw_rect(top, li_m2, m2_rect)
        # Always draw m1_stub — via_stack pins need it to bridge
        # ptap/ntap tie M1 to PCell M1 strip.
        # For via_stack (power) pins, truncate stub if it extends into
        # cross-net AP M1 territory to prevent pmos_bias↔gnd type bridges.
        if ap.get('m1_stub') and not skip_m1:
            _ms = list(ap['m1_stub'])
            if is_via_stack:
                _snet = next((d['net'] for d in routing.get('power', {}).get('drops', [])
                              if f"{d['inst']}.{d['pin']}" == key), '')
                for _axl, _ayb, _axr, _ayt, _anet in ap_m1_obs:
                    if _anet == _snet or not _anet:
                        continue
                    # X overlap check
                    if _ms[2] <= _axl or _ms[0] >= _axr:
                        continue
                    # Cross-net M1 above stub bottom: raise stub bottom
                    if _ayt > _ms[1] and _ayb < _ms[1] + M1_MIN_S:
                        _ms[1] = max(_ms[1], _ayt + M1_MIN_S)
                        _ms[1] = ((_ms[1] + 4) // 5) * 5
                    # Cross-net M1 below stub top: lower stub top
                    if _ayb < _ms[3] and _ayt > _ms[3] - M1_MIN_S:
                        _ms[3] = min(_ms[3], _ayb - M1_MIN_S)
                        _ms[3] = (_ms[3] // 5) * 5
            if _ms[3] - _ms[1] >= M1_MIN_W:
                draw_rect(top, li_m1, _ms)
            else:
                pass  # stub clipped to nothing
        if ap.get('m2_stub') and not is_via_stack:
            draw_rect(top, li_m2, ap['m2_stub'])
        ap_count += 1
    print(f'  Drew {ap_count} access points ({len(drawn_vias)} via1 positions tracked'
          f'{f", {_ap_m2_shrink} M2 pads shrunk" if _ap_m2_shrink else ""})')




    return ap_count, _m2_route_wires
