#!/usr/bin/env python3
"""Fix cross-net M2 AP pad overlaps in GDS using DUAL-PAD shrink.

Root cause: _shrink_ap_m2_pads_gds doesn't handle full overlap (both
axes gap < 0). Single-pad shrink fails because pads are only 480nm —
shrinking one side by 275nm violates min area.

Solution: shrink BOTH pads symmetrically, each by half the needed amount.
This keeps each pad above min width/area.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.fix_m2_overlap [--gds output/ptat_vco.gds]
"""

import json
import math
import klayout.db as db
from .pdk import M2_MIN_S, M2_MIN_W, M2_MIN_AREA


def _find_and_shrink(top, m2_li, orig_bbox, new_bbox):
    """Find M2 shape matching orig_bbox in GDS and replace with new_bbox.
    Returns True if shape was found and replaced."""
    for si in top.shapes(m2_li).each():
        bb = si.bbox()
        if (abs(bb.left - orig_bbox[0]) < 20 and abs(bb.bottom - orig_bbox[1]) < 20
                and abs(bb.right - orig_bbox[2]) < 20 and abs(bb.top - orig_bbox[3]) < 20):
            si.delete()
            top.shapes(m2_li).insert(db.Box(*new_bbox))
            return True
    return False


def _validate(pad):
    """Check min width and area."""
    w = pad[2] - pad[0]
    h = pad[3] - pad[1]
    return w >= M2_MIN_W and h >= M2_MIN_W and w * h >= M2_MIN_AREA


def fix(gds_path='output/soilz.gds', routing_path='output/routing.json',
        output_path=None):
    if output_path is None:
        output_path = gds_path

    with open(routing_path) as f:
        routing = json.load(f)
    ap_data = routing.get('access_points', {})

    # Build per-pin AP M2 pad list
    pin_pads = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        for pin_key in route.get('pins', []):
            ap = ap_data.get(pin_key)
            if ap and 'm2' in ap.get('via_pad', {}):
                pin_pads[pin_key] = (net_name, list(ap['via_pad']['m2']))
    for drop in routing.get('power', {}).get('drops', []):
        pk = f"{drop['inst']}.{drop['pin']}"
        ap = ap_data.get(pk)
        if ap and 'm2' in ap.get('via_pad', {}):
            pin_pads[pk] = (drop['net'], list(ap['via_pad']['m2']))

    # Find cross-net violations
    keys = list(pin_pads.keys())
    violations = []
    for i in range(len(keys)):
        net_i, pad_i = pin_pads[keys[i]]
        for j in range(i + 1, len(keys)):
            net_j, pad_j = pin_pads[keys[j]]
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

    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    m2_li = layout.layer(10, 0)

    fixed = 0
    for pk1, n1, pad1, pk2, n2, pad2, xg, yg in violations:
        orig1, orig2 = tuple(pad1), tuple(pad2)

        # Determine which dimension to fix (smallest shrink needed)
        # X needed: overlap + spacing
        if xg < M2_MIN_S:
            x_needed = M2_MIN_S - xg  # total gap increase needed
        else:
            x_needed = 0
        if yg < M2_MIN_S:
            y_needed = M2_MIN_S - yg
        else:
            y_needed = 0

        # Fix the dimension requiring less total shrink
        if x_needed > 0 and (y_needed == 0 or x_needed <= y_needed):
            # Shrink X: each pad gives up x_needed/2 on the facing edge
            half = (x_needed + 1) // 2 + 5  # +5nm margin, round up
            # Which edge faces the other pad?
            cx1 = (pad1[0] + pad1[2]) / 2
            cx2 = (pad2[0] + pad2[2]) / 2
            if cx1 < cx2:
                # pad1 is left, pad2 is right — shrink pad1's right, pad2's left
                pad1[2] -= half
                pad2[0] += half
            else:
                pad1[0] += half
                pad2[2] -= half
        elif y_needed > 0:
            half = (y_needed + 1) // 2 + 5
            cy1 = (pad1[1] + pad1[3]) / 2
            cy2 = (pad2[1] + pad2[3]) / 2
            if cy1 < cy2:
                pad1[3] -= half
                pad2[1] += half
            else:
                pad1[1] += half
                pad2[3] -= half
        else:
            continue  # No fix needed

        # Validate both pads
        if not _validate(pad1) or not _validate(pad2):
            w1 = pad1[2]-pad1[0]
            h1 = pad1[3]-pad1[1]
            w2 = pad2[2]-pad2[0]
            h2 = pad2[3]-pad2[1]
            print(f'  {pk1}↔{pk2}: dual shrink fails '
                  f'({w1}x{h1} + {w2}x{h2}), skip')
            pad1[:] = list(orig1)
            pad2[:] = list(orig2)
            continue

        # Apply to GDS
        ok1 = _find_and_shrink(top, m2_li, orig1, pad1)
        ok2 = _find_and_shrink(top, m2_li, orig2, pad2)

        if ok1 and ok2:
            print(f'  {pk1}({n1}) shrunk + {pk2}({n2}) shrunk ✓')
            fixed += 1
        elif ok1 or ok2:
            print(f'  {pk1}↔{pk2}: partial fix (only {"1st" if ok1 else "2nd"} found)')
            fixed += 1
        else:
            print(f'  {pk1}↔{pk2}: shapes not found in GDS')
            pad1[:] = list(orig1)
            pad2[:] = list(orig2)

    layout.write(output_path)
    print(f'  Fixed {fixed}/{len(violations)} → {output_path}')
    return fixed


if __name__ == '__main__':
    fix()
