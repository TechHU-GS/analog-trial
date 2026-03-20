"""§2: Draw tie cells + NWell extensions/bridges/gap fills."""

import klayout.db

from atk.pdk import (
    METAL1, NWELL, PSD, ACTIV,
    M1_MIN_S, M1_MIN_W, M1_SIG_W, M1_MIN_AREA, UM, s5,
    VIA1_GDS_M1,
)


def draw_ties_and_nwell(top, li_m1, li_nw, li_psd, layout, instances,
                         placement, ties, routing, access_points_data,
                         device_lib, devices_map, pin_net_map,
                         ap_m1_obs, gate_cont_m1):
    """Draw tie cells from ties.json + NWell extensions/bridges/fills.

    Returns nothing — mutates top cell directly.
    """
    from assemble_gds import (draw_rect, hbar, vbar,
                               _parse_tie_layer, _add_tff_nwell_bridges,
                               _add_nwell_bridge, _fill_nwell_gaps)

    # ═══ 2. Draw tie cells from ties.json ═══
    # Build routing M1 wire index for tie M1 proximity check.
    _route_m1_shapes = []  # (xl, yb, xr, yt)
    _hw_m1 = M1_SIG_W // 2
    for _rd_name in ('signal_routes', 'pre_routes'):
        for _rnet, _rd in routing.get(_rd_name, {}).items():
            for _seg in _rd.get('segments', []):
                if len(_seg) < 5:
                    continue
                sx1, sy1, sx2, sy2, slyr = _seg[:5]
                if slyr == 0:  # M1 wire
                    if sx1 == sx2:
                        _route_m1_shapes.append((sx1 - _hw_m1, min(sy1, sy2),
                                                 sx1 + _hw_m1, max(sy1, sy2)))
                    elif sy1 == sy2:
                        _route_m1_shapes.append((min(sx1, sx2) - _hw_m1, sy1 - _hw_m1,
                                                 max(sx1, sx2) + _hw_m1, sy1 + _hw_m1))
                elif slyr == -1:  # via1 → M1 pad
                    _vhp = VIA1_GDS_M1 // 2
                    _route_m1_shapes.append((sx1 - _vhp, sy1 - _vhp,
                                            sx1 + _vhp, sy1 + _vhp))

    # Add signal AP m1_stubs to routing M1 shapes (bridge source #2)
    _via_stack_pins_trim = set()
    for _d in routing.get('power', {}).get('drops', []):
        if _d['type'] == 'via_stack':
            _via_stack_pins_trim.add(f"{_d['inst']}.{_d['pin']}")
    _ap_stub_count = 0
    for _key, _ap in routing.get('access_points', {}).items():
        if _key in _via_stack_pins_trim:
            continue  # power pin — handled in _power_m1_shapes
        _stub = _ap.get('m1_stub')
        if _stub:
            _route_m1_shapes.append(tuple(_stub))
            _ap_stub_count += 1

    # Power M1 shapes: Via1 M1 pads + via_stack AP m1_stubs, tagged with net
    # Only used for cross-net trim (power_net != tie_net)
    _power_m1_shapes = []  # (xl, yb, xr, yt, net)
    _v1_hp = VIA1_GDS_M1 // 2
    for _d in routing.get('power', {}).get('drops', []):
        if _d['type'] == 'via_stack':
            _x, _y = _d['via1_pos']
            _power_m1_shapes.append((_x - _v1_hp, _y - _v1_hp,
                                      _x + _v1_hp, _y + _v1_hp, _d['net']))
            _pin_key = f"{_d['inst']}.{_d['pin']}"
            _pap = routing.get('access_points', {}).get(_pin_key)
            if _pap and _pap.get('m1_stub'):
                _s = _pap['m1_stub']
                _power_m1_shapes.append((_s[0], _s[1], _s[2], _s[3], _d['net']))

    print('\n  === Drawing ties ===')
    print(f'  Trim index: {len(_route_m1_shapes)} route M1 ({_ap_stub_count} AP stubs)'
          f' + {len(_power_m1_shapes)} power M1 (cross-net)')
    tie_layer_cache = {}
    # Build cross-net tie M1 index for tie-vs-tie overlap check
    _tie_m1_by_net = {}  # net → [(xl, yb, xr, yt), ...]
    for _t in ties.get('ties', []):
        _tn = _t.get('net', 'gnd')
        for _r in _t.get('layers', {}).get('M1_8_0', []):
            _tie_m1_by_net.setdefault(_tn, []).append(tuple(_r))

    _tie_m1_trimmed = 0
    _CONT_LD = (6, 0)
    _M1_LD = (8, 0)
    for tie in ties.get('ties', []):
        tid = tie['id']
        tie_net = tie.get('net', 'gnd')  # ntap→vdd, ptap→gnd
        # Check if tie M1 conflicts with routing/power M1 or cross-net tie M1.
        # If so, shrink tie M1 and drop exposed Conts.
        m1_rects = tie.get('layers', {}).get('M1_8_0', [])
        _trimmed_m1 = {}  # index → new rect (or None to skip)
        for mi, m1r in enumerate(m1_rects):
            new_top = m1r[3]
            new_bot = m1r[1]
            # Check against signal routing M1 + AP m1_stubs
            # ntap (vdd) ties: skip actual-overlap trim to preserve NWell
            # connectivity. The M3 cleanup handles the LVS bridge.
            _is_ntap = (tie_net == 'vdd')
            for w in _route_m1_shapes:
                x_ov = min(m1r[2], w[2]) - max(m1r[0], w[0])
                if x_ov <= 0:
                    continue
                y_ov = min(m1r[3], w[3]) - max(m1r[1], w[1])
                if y_ov > 0:
                    if _is_ntap:
                        # Gentle single-side trim: avoid dropping ntap
                        y_gap_top = w[1] - m1r[3]
                        if -200 < y_gap_top < M1_MIN_S:
                            new_top = min(new_top, w[1] - M1_MIN_S)
                        y_gap_bot = m1r[1] - w[3]
                        if -200 < y_gap_bot < M1_MIN_S:
                            new_bot = max(new_bot, w[3] + M1_MIN_S)
                    else:
                        new_top = min(new_top, w[1] - M1_MIN_S)
                        new_bot = max(new_bot, w[3] + M1_MIN_S)
                else:
                    # Near-miss — use gap threshold
                    y_gap_top = w[1] - m1r[3]
                    if -200 < y_gap_top < M1_MIN_S:
                        new_top = min(new_top, w[1] - M1_MIN_S)
                    y_gap_bot = m1r[1] - w[3]
                    if -200 < y_gap_bot < M1_MIN_S:
                        new_bot = max(new_bot, w[3] + M1_MIN_S)
            # Check against cross-net power M1 (trim only if different net)
            for pw in _power_m1_shapes:
                if pw[4] == tie_net:
                    continue  # same net — no bridge risk
                x_ov = min(m1r[2], pw[2]) - max(m1r[0], pw[0])
                if x_ov <= 0:
                    continue
                y_ov = min(m1r[3], pw[3]) - max(m1r[1], pw[1])
                if y_ov > 0:
                    if _is_ntap:
                        y_gap_top = pw[1] - m1r[3]
                        if -200 < y_gap_top < M1_MIN_S:
                            new_top = min(new_top, pw[1] - M1_MIN_S)
                        y_gap_bot = m1r[1] - pw[3]
                        if -200 < y_gap_bot < M1_MIN_S:
                            new_bot = max(new_bot, pw[3] + M1_MIN_S)
                    else:
                        new_top = min(new_top, pw[1] - M1_MIN_S)
                        new_bot = max(new_bot, pw[3] + M1_MIN_S)
                else:
                    y_gap_top = pw[1] - m1r[3]
                    if -200 < y_gap_top < M1_MIN_S:
                        new_top = min(new_top, pw[1] - M1_MIN_S)
                    y_gap_bot = m1r[1] - pw[3]
                    if -200 < y_gap_bot < M1_MIN_S:
                        new_bot = max(new_bot, pw[3] + M1_MIN_S)
            # Check against cross-net tie M1 bars (tie-vs-tie overlap)
            # Only trim ptap (gnd) ties — ntap (vdd) must be preserved
            # for NWell connectivity. ptap loss is less harmful (pwell backup).
            if tie_net != 'vdd':
              for _xnet in ('gnd', 'vdd'):
                if _xnet == tie_net:
                    continue
                for tw in _tie_m1_by_net.get(_xnet, []):
                    x_ov = min(m1r[2], tw[2]) - max(m1r[0], tw[0])
                    if x_ov <= 0:
                        continue
                    y_ov = min(m1r[3], tw[3]) - max(m1r[1], tw[1])
                    if y_ov > 0:
                        new_top = min(new_top, tw[1] - M1_MIN_S)
                        new_bot = max(new_bot, tw[3] + M1_MIN_S)
                    else:
                        y_gap_top = tw[1] - m1r[3]
                        if -200 < y_gap_top < M1_MIN_S:
                            new_top = min(new_top, tw[1] - M1_MIN_S)
                        y_gap_bot = m1r[1] - tw[3]
                        if -200 < y_gap_bot < M1_MIN_S:
                            new_bot = max(new_bot, tw[3] + M1_MIN_S)
            if new_top != m1r[3] or new_bot != m1r[1]:
                # Displacement guard: if trim moves bar center > 500nm, drop it
                orig_cy = (m1r[1] + m1r[3]) // 2
                new_cy = (new_bot + new_top) // 2
                if new_top <= new_bot or abs(new_cy - orig_cy) > 500:
                    # Degenerate or excessive displacement — drop entire bar
                    _trimmed_m1[mi] = None  # signal to skip
                    _tie_m1_trimmed += 1
                else:
                    # Enforce M1.d min area
                    w_m1 = m1r[2] - m1r[0]
                    min_h = (M1_MIN_AREA + w_m1 - 1) // w_m1
                    min_h = ((min_h + 4) // 5) * 5
                    if new_top - new_bot < min_h:
                        new_top = max(new_top, new_bot + min_h)
                    new_top = ((new_top + 2) // 5) * 5
                    new_bot = ((new_bot + 2) // 5) * 5
                    # Final displacement check after grid snap
                    final_cy = (new_bot + new_top) // 2
                    if abs(final_cy - orig_cy) > 500:
                        _trimmed_m1[mi] = None
                    else:
                        _trimmed_m1[mi] = [m1r[0], new_bot, m1r[2], new_top]
                    _tie_m1_trimmed += 1

        for layer_key, rects in tie.get('layers', {}).items():
            ld = _parse_tie_layer(layer_key)
            if ld is None:
                print(f'    WARNING: unknown tie layer {layer_key}')
                continue
            if ld not in tie_layer_cache:
                tie_layer_cache[ld] = layout.layer(*ld)
            li = tie_layer_cache[ld]
            for ri, rect in enumerate(rects):
                if ld == _M1_LD and ri in _trimmed_m1:
                    if _trimmed_m1[ri] is not None:
                        draw_rect(top, li, _trimmed_m1[ri])
                    # else: dropped (overlap/displacement)
                    continue
                elif ld == _CONT_LD and _trimmed_m1:
                    # Drop Conts when M1 is dropped or trimmed
                    m1_new = list(_trimmed_m1.values())[0]
                    if m1_new is None:
                        continue  # M1 dropped — drop all Conts too
                    if (rect[0] < m1_new[0] or rect[2] > m1_new[2]
                            or rect[1] < m1_new[1] or rect[3] > m1_new[3]):
                        continue  # Cont not fully inside trimmed M1 — skip
                    draw_rect(top, li, rect)
                else:
                    draw_rect(top, li, rect)
    print(f'  Drew {len(ties.get("ties", []))} ties'
          f'{f" ({_tie_m1_trimmed} M1 trimmed)" if _tie_m1_trimmed else ""}')

    # ── NWell extensions ──
    li_nw = layout.layer(*NWELL)
    for ext in ties.get('nwell_extensions', []):
        draw_rect(top, li_nw, ext['rect_nm'])
    print(f'  Drew {len(ties.get("nwell_extensions", []))} NWell extensions')

    # ── NWell bridge (MBp1 ↔ MBp2) ──
    _add_nwell_bridge(top, layout, placement)

    # ── TFF NWell bridges (merge PMOS NWells per half-stage for LU.a) ──
    _add_tff_nwell_bridges(top, layout, placement)

    # ── NWell island fill (continuous NWell for shared-well groups) ──
    island_count = 0
    for island in placement.get('nwell_islands', []):
        bbox = island['bbox_um']
        x1 = int(bbox[0] * 1000)
        y1 = int(bbox[1] * 1000)
        x2 = int(bbox[2] * 1000)
        y2 = int(bbox[3] * 1000)
        top.shapes(li_nw).insert(klayout.db.Box(x1, y1, x2, y2))
        island_count += 1
        print(f'    NWell island {island["id"]}: '
              f'[{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}] µm '
              f'({island["net"]})')
    if island_count:
        print(f'  Drew {island_count} NWell island fills')

    # ── NWell gap fill for adjacent PMOS devices (NW.b fix) ──
    # Adjacent PMOS devices may have NWell gaps < 0.62µm (NW.b min space/notch).
    # Fill gaps to merge NWells — electrically correct for shared-well groups.
    # Group by Y band first (rects at different Y positions interleave in X sort).
    nw_fill_count = 0
    NW_B1_MAX_GAP = 1850  # Fill gaps up to NW.b1 = 1840nm (nm)
    NW_A_MIN = 620        # NW.a = min NWell width — fill must be >= this tall
    pmos_nw_rects = []    # (x1, y1, x2, y2) in nm
    for inst_name, info in instances.items():
        dev_type = info['type']
        dev_lib = device_lib.get(dev_type, {})
        cls = dev_lib.get('classification', {}).get('device_class', '')
        if cls != 'pmos':
            continue
        nw_shapes = dev_lib.get('shapes_by_layer', {}).get('NW_31_0', [])
        if not nw_shapes:
            continue
        bbox = dev_lib.get('bbox', [0, 0, 0, 0])
        pcell_x = round((info['x_um'] - bbox[0] / 1000) * 1000)
        pcell_y = round((info['y_um'] - bbox[1] / 1000) * 1000)
        for s in nw_shapes:
            pmos_nw_rects.append((pcell_x + s[0], pcell_y + s[1],
                                  pcell_x + s[2], pcell_y + s[3]))
    # Also include NWell extensions from ties (they partially close gaps)
    for ext in ties.get('nwell_extensions', []):
        r = ext['rect_nm']
        pmos_nw_rects.append((r[0], r[1], r[2], r[3]))
    # Fill all NWell gaps < NW.b1 between adjacent rects.
    # Pass 1: X gaps with Y overlap (sorted by x1)
    pmos_nw_rects.sort()
    for i in range(len(pmos_nw_rects)):
        r1 = pmos_nw_rects[i]
        for j in range(i + 1, len(pmos_nw_rects)):
            r2 = pmos_nw_rects[j]
            gap_x = r2[0] - r1[2]
            if gap_x >= NW_B1_MAX_GAP:
                break  # sorted by x1, further rects are further right
            if gap_x <= 0:
                continue
            y_overlap = min(r1[3], r2[3]) - max(r1[1], r2[1])
            if y_overlap >= NW_A_MIN:
                fill_y1 = max(r1[1], r2[1])
                fill_y2 = min(r1[3], r2[3])
                top.shapes(li_nw).insert(klayout.db.Box(
                    r1[2], fill_y1, r2[0], fill_y2))
                nw_fill_count += 1
    # Pass 2: Y gaps with X overlap (sorted by y1)
    by_y = sorted(pmos_nw_rects, key=lambda r: r[1])
    for i in range(len(by_y)):
        r1 = by_y[i]
        for j in range(i + 1, len(by_y)):
            r2 = by_y[j]
            gap_y = r2[1] - r1[3]
            if gap_y >= NW_B1_MAX_GAP:
                break
            if gap_y <= 0:
                continue
            x_overlap = min(r1[2], r2[2]) - max(r1[0], r2[0])
            if x_overlap >= NW_A_MIN:
                fill_x1 = max(r1[0], r2[0])
                fill_x2 = min(r1[2], r2[2])
                top.shapes(li_nw).insert(klayout.db.Box(
                    fill_x1, r1[3], fill_x2, r2[1]))
                nw_fill_count += 1
    # Pass 3: Targeted NWell bridge
    # TODO: auto-bridge with isolated_check causes NW.d/NW.e violations
    # Keeping hardcoded until DRC-safe auto-fill algorithm is developed
    _NW_BRIDGE_A = (140580, 83485, 141200, 86120)
    top.shapes(li_nw).insert(klayout.db.Box(*_NW_BRIDGE_A))
    nw_fill_count += 1
    print(f'    NWell bridge A: {_NW_BRIDGE_A}')

    if nw_fill_count:
        print(f'  Filled {nw_fill_count} NWell gaps between adjacent PMOS devices (NW.b)')

    # ── Final NWell gap fill (catch-all from actual layout shapes) ──
    _fill_nwell_gaps(top, layout)


