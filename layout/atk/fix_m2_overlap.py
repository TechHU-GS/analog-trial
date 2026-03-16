#!/usr/bin/env python3
"""Fix cross-net M2 AP pad overlaps in GDS.

Root cause: _shrink_ap_m2_pads_gds in assemble_gds.py doesn't handle
the case where both X and Y axes have overlap (gap < 0 on both).
It only handles "gap on one axis, overlap on the other".

This post-fix script reads the GDS, finds the 5 known violations,
and shrinks the smaller pad to eliminate the overlap + enforce M2.b spacing.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.fix_m2_overlap
"""

import json
import klayout.db as db
from .pdk import M2_MIN_S, M2_MIN_W, M2_MIN_AREA


def fix(gds_path='output/ptat_vco.gds', routing_path='output/routing.json',
        output_path=None):
    """Fix cross-net M2 pad overlaps."""
    if output_path is None:
        output_path = gds_path  # overwrite in place

    with open(routing_path) as f:
        routing = json.load(f)
    ap_data = routing.get('access_points', {})

    # Build per-net AP M2 pad list
    net_pads = {}  # pin_key → (net, bbox)
    for net_name, route in routing.get('signal_routes', {}).items():
        for pin_key in route.get('pins', []):
            ap = ap_data.get(pin_key)
            if ap and 'm2' in ap.get('via_pad', {}):
                net_pads[pin_key] = (net_name, ap['via_pad']['m2'])
    for drop in routing.get('power', {}).get('drops', []):
        pk = f"{drop['inst']}.{drop['pin']}"
        ap = ap_data.get(pk)
        if ap and 'm2' in ap.get('via_pad', {}):
            net_pads[pk] = (drop['net'], ap['via_pad']['m2'])

    # Find cross-net violations
    keys = list(net_pads.keys())
    violations = []
    for i in range(len(keys)):
        net_i, pad_i = net_pads[keys[i]]
        for j in range(i + 1, len(keys)):
            net_j, pad_j = net_pads[keys[j]]
            if net_i == net_j:
                continue
            x_gap = max(pad_i[0] - pad_j[2], pad_j[0] - pad_i[2])
            y_gap = max(pad_i[1] - pad_j[3], pad_j[1] - pad_i[3])
            if x_gap < M2_MIN_S and y_gap < M2_MIN_S:
                diag = (max(0, x_gap)**2 + max(0, y_gap)**2)**0.5
                if diag < M2_MIN_S:
                    violations.append((keys[i], net_i, pad_i,
                                       keys[j], net_j, pad_j,
                                       x_gap, y_gap))

    if not violations:
        print('  No cross-net M2 pad violations found.')
        return

    print(f'  Found {len(violations)} cross-net M2 pad violations')

    # Load GDS
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    m2_li = layout.layer(10, 0)

    fixed = 0
    for pk1, n1, pad1, pk2, n2, pad2, xg, yg in violations:
        # Decide which pad to shrink:
        # - Don't shrink power net pads (gnd/vdd)
        # - Shrink the smaller one
        if n1 in ('gnd', 'vdd', 'vdd_vco'):
            target_pk, target_pad, other_pad = pk2, list(pad2), pad1
        elif n2 in ('gnd', 'vdd', 'vdd_vco'):
            target_pk, target_pad, other_pad = pk1, list(pad1), pad2
        else:
            a1 = (pad1[2]-pad1[0]) * (pad1[3]-pad1[1])
            a2 = (pad2[2]-pad2[0]) * (pad2[3]-pad2[1])
            if a1 <= a2:
                target_pk, target_pad, other_pad = pk1, list(pad1), pad2
            else:
                target_pk, target_pad, other_pad = pk2, list(pad2), pad1

        # Calculate shrink needed on each edge
        # We need: target_pad edges to be M2_MIN_S away from other_pad
        orig = tuple(target_pad)

        # X dimension
        if target_pad[2] > other_pad[0] and target_pad[0] < other_pad[2]:
            # X overlap — shrink the closer edge
            if abs(target_pad[2] - other_pad[0]) < abs(target_pad[0] - other_pad[2]):
                target_pad[2] = min(target_pad[2], other_pad[0] - M2_MIN_S)
            else:
                target_pad[0] = max(target_pad[0], other_pad[2] + M2_MIN_S)

        # Y dimension
        if target_pad[3] > other_pad[1] and target_pad[1] < other_pad[3]:
            if abs(target_pad[3] - other_pad[1]) < abs(target_pad[1] - other_pad[3]):
                target_pad[3] = min(target_pad[3], other_pad[1] - M2_MIN_S)
            else:
                target_pad[1] = max(target_pad[1], other_pad[3] + M2_MIN_S)

        # Validate
        w = target_pad[2] - target_pad[0]
        h = target_pad[3] - target_pad[1]
        if w < M2_MIN_W or h < M2_MIN_W or w * h < M2_MIN_AREA:
            print(f'  {target_pk}: cannot shrink ({w}x{h}nm < min), skip')
            continue

        # Find and replace in GDS
        replaced = False
        for si in top.shapes(m2_li).each():
            bb = si.bbox()
            if (abs(bb.left - orig[0]) < 20 and abs(bb.bottom - orig[1]) < 20
                    and abs(bb.right - orig[2]) < 20 and abs(bb.top - orig[3]) < 20):
                si.delete()
                top.shapes(m2_li).insert(db.Box(*target_pad))
                replaced = True
                break

        if replaced:
            print(f'  {target_pk}({n1 if target_pk == pk1 else n2}): '
                  f'[{orig[0]},{orig[1]},{orig[2]},{orig[3]}] → '
                  f'[{target_pad[0]},{target_pad[1]},{target_pad[2]},{target_pad[3]}]')
            fixed += 1
        else:
            print(f'  {target_pk}: M2 shape not found in GDS, skip')

    layout.write(output_path)
    print(f'  Fixed {fixed}/{len(violations)} M2 pad overlaps → {output_path}')


if __name__ == '__main__':
    fix()
