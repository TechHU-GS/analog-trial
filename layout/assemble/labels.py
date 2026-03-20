"""§6: Pin labels for LVS."""

import os
import json
import klayout.db


def draw_labels(top, layout, li_m2_lbl, li_m3_lbl, routing, pin_net_map):
    """Add net name labels on M2/M3 for KLayout LVS.

    Returns label counts.
    """
    # ═══ 6. Pin labels for LVS ═══
    print('\n  === Adding pin labels ===')

    # Power labels — on TM1 (drawn with TM1 stripes above), NOT on M3 rails
    # (M3 rails removed; orphaned M3 labels would land on signal wires → comma merge)

    # Signal labels on M1 (8,25) and M2 (10,25) for every signal net.
    # LVS needs labels to name extracted nets; unlabelled nets become $N.
    li_m1_lbl = layout.layer(8, 25)
    sig_label_count = 0
    # Build pin→net map for 0-segment net label placement
    _ap_data = routing.get('access_points', {})

    for net_name, route in routing.get('signal_routes', {}).items():
        segs = route.get('segments', [])
        if not segs:
            # 0-segment net (same-cell connection): place label on M2 at
            # first access point that has a via_pad (Via1 M2 pad).
            # Without a label, KLayout LVS cannot name the extracted net.
            pins = route.get('pins', [])
            labeled = False
            for pin_key in pins:
                ap = _ap_data.get(pin_key)
                if ap and ap.get('via_pad') and 'm2' in ap['via_pad']:
                    vp = ap['via_pad']['m2']
                    mx = (vp[0] + vp[2]) // 2
                    my = (vp[1] + vp[3]) // 2
                    top.shapes(li_m2_lbl).insert(klayout.db.Text(
                        net_name, klayout.db.Trans(klayout.db.Point(mx, my))))
                    sig_label_count += 1
                    labeled = True
                    break
            if not labeled and pins:
                # Fallback: use access point position directly
                ap = _ap_data.get(pins[0])
                if ap:
                    top.shapes(li_m2_lbl).insert(klayout.db.Text(
                        net_name, klayout.db.Trans(
                            klayout.db.Point(ap['x'], ap['y']))))
                    sig_label_count += 1
            continue
        # Routing is on M3+M4+M5 (router layers 0,1,2).  Labels must be
        # on a layer with physical metal.  Place label on M2 at AP via_pad
        # (every AP has M2 from the via stack M1→Via1→M2→Via2→M3).
        # Label propagates through Via2→M3→routing wire.
        # Fallback: M3 label at first M3 segment (router layer 0).
        pins = route.get('pins', [])
        _lbl_placed = False
        for pin_key in pins:
            ap = _ap_data.get(pin_key)
            if ap and ap.get('via_pad') and 'm2' in ap['via_pad']:
                vp = ap['via_pad']['m2']
                mx = (vp[0] + vp[2]) // 2
                my = (vp[1] + vp[3]) // 2
                top.shapes(li_m2_lbl).insert(klayout.db.Text(
                    net_name, klayout.db.Trans(klayout.db.Point(mx, my))))
                sig_label_count += 1
                _lbl_placed = True
                break
        if not _lbl_placed:
            m3_seg = next((s for s in segs if s[4] == 0), None)  # router layer 0 = M3
            if m3_seg:
                mx = (m3_seg[0] + m3_seg[2]) // 2
                my = (m3_seg[1] + m3_seg[3]) // 2
                top.shapes(li_m3_lbl).insert(klayout.db.Text(
                    net_name, klayout.db.Trans(klayout.db.Point(mx, my))))
                sig_label_count += 1
                _lbl_placed = True
        if not _lbl_placed:
            # Last resort: M2 label at AP position (even without via_pad)
            for pin_key in pins:
                ap = _ap_data.get(pin_key)
                if ap:
                    top.shapes(li_m2_lbl).insert(klayout.db.Text(
                        net_name, klayout.db.Trans(
                            klayout.db.Point(ap['x'], ap['y']))))
                    sig_label_count += 1
                    _lbl_placed = True
                    break
    # Pre-routes: same AP via_pad M2 label strategy
    for net_name, route in routing.get('pre_routes', {}).items():
        segs = route.get('segments', [])
        if not segs:
            continue
        _pr_placed = False
        pr_pins = route.get('pins', [])
        for pin_key in pr_pins:
            ap = _ap_data.get(pin_key)
            if ap and ap.get('via_pad') and 'm2' in ap['via_pad']:
                vp = ap['via_pad']['m2']
                mx = (vp[0] + vp[2]) // 2
                my = (vp[1] + vp[3]) // 2
                top.shapes(li_m2_lbl).insert(klayout.db.Text(
                    net_name, klayout.db.Trans(klayout.db.Point(mx, my))))
                sig_label_count += 1
                _pr_placed = True
                break
        if not _pr_placed:
            # Fallback: M3 label at router layer 0 segment
            m3_seg = next((s for s in segs if s[4] == 0), None)
            if m3_seg:
                mx = (m3_seg[0] + m3_seg[2]) // 2
                my = (m3_seg[1] + m3_seg[3]) // 2
                top.shapes(li_m3_lbl).insert(klayout.db.Text(
                    net_name, klayout.db.Trans(klayout.db.Point(mx, my))))
                sig_label_count += 1

    # Labels for single-pin nets (nets with APs but no signal route).
    # These are typically external input pins (gate connections) that the
    # router skips because there's only one pin — nothing to route to.
    # Place M2 label at the AP via_pad position.
    _routed_nets = set(routing.get('signal_routes', {}).keys()) | \
                   set(routing.get('pre_routes', {}).keys())
    _netlist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'netlist.json')
    with open(_netlist_path) as _f:
        _netlist_lbl = json.load(_f)
    _pin_to_net = {}
    for _ne in _netlist_lbl.get('nets', []):
        for _pin in _ne['pins']:
            _pin_to_net[_pin] = _ne['name']
    _single_pin_count = 0
    _ap_data_lbl = routing.get('access_points', {})
    for _ne in _netlist_lbl.get('nets', []):
        net_name = _ne['name']
        if net_name in _routed_nets:
            continue  # already labeled
        pins = _ne['pins']
        for pin_key in pins:
            ap = _ap_data_lbl.get(pin_key)
            if ap and ap.get('via_pad') and 'm2' in ap['via_pad']:
                vp = ap['via_pad']['m2']
                mx = (vp[0] + vp[2]) // 2
                my = (vp[1] + vp[3]) // 2
                top.shapes(li_m2_lbl).insert(klayout.db.Text(
                    net_name, klayout.db.Trans(klayout.db.Point(mx, my))))
                _single_pin_count += 1
                break  # one label per net is enough

    print(f'  Added pin labels: vdd/vdd_vco/gnd (M3), {sig_label_count} signal nets'
          f', {_single_pin_count} single-pin nets')


