"""Pre-routing placement DRC — catch access-pad conflicts BEFORE routing.

Computes access points for every pin, then checks that access structures
(M1 via_pad, M1 stub, M2 via_pad) on different nets don't overlap or
violate DRC spacing.

Pipeline position:  placement_check → coordinate_verify → route → ...

Usage:
    python -m atk.verify.placement_check [placement.json]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import box

from atk.pdk import UM, s5, M1_MIN_S, M2_MIN_S
from atk.route.access import compute_access_points


def _ap_shapes(ap):
    """Extract (layer, shapely_box, desc) list from one access point."""
    shapes = []
    vp = ap.get('via_pad')
    if vp:
        if 'm1' in vp:
            r = vp['m1']
            shapes.append(('M1', box(r[0], r[1], r[2], r[3]), 'via_pad'))
        if 'm2' in vp:
            r = vp['m2']
            shapes.append(('M2', box(r[0], r[1], r[2], r[3]), 'via_pad'))
    stub = ap.get('m1_stub')
    if stub:
        shapes.append(('M1', box(stub[0], stub[1], stub[2], stub[3]), 'm1_stub'))
    return shapes


def check_access_spacing(placement_path, netlist_path):
    """Check that access structures on different nets have DRC-clean spacing.

    Returns list of violation dicts:
        {'pin_a': str, 'net_a': str, 'pin_b': str, 'net_b': str,
         'layer': str, 'type': 'overlap'|'spacing', 'detail': str}
    """
    with open(placement_path) as f:
        placement = json.load(f)
    with open(netlist_path) as f:
        netlist = json.load(f)

    # pin → net mapping
    pin_net = {}
    for ne in netlist['nets']:
        for pin in ne['pins']:
            pin_net[pin] = ne['name']

    access = compute_access_points(placement)

    # Build per-pin shapes with net info
    pin_shapes = []  # [(key, net, layer, box, desc)]
    for (inst, pin), ap in access.items():
        key = f'{inst}.{pin}'
        net = pin_net.get(key, '?')
        for layer, shp, desc in _ap_shapes(ap):
            pin_shapes.append((key, net, layer, shp, desc))

    # DRC spacing per layer
    min_space = {'M1': M1_MIN_S, 'M2': M2_MIN_S}

    violations = []
    n = len(pin_shapes)
    for i in range(n):
        key_a, net_a, lyr_a, shp_a, desc_a = pin_shapes[i]
        for j in range(i + 1, n):
            key_b, net_b, lyr_b, shp_b, desc_b = pin_shapes[j]

            # Same net — no constraint
            if net_a == net_b:
                continue
            # Different layer — no constraint
            if lyr_a != lyr_b:
                continue

            layer = lyr_a
            dist = shp_a.distance(shp_b)

            if dist < 0.1:  # overlap (distance ≈ 0)
                area = shp_a.intersection(shp_b).area
                if area > 0:
                    violations.append({
                        'pin_a': key_a, 'net_a': net_a,
                        'pin_b': key_b, 'net_b': net_b,
                        'layer': layer, 'type': 'overlap',
                        'detail': f'overlap area={area:.0f}nm²',
                    })
            elif dist < min_space[layer]:
                violations.append({
                    'pin_a': key_a, 'net_a': net_a,
                    'pin_b': key_b, 'net_b': net_b,
                    'layer': layer, 'type': 'spacing',
                    'detail': f'gap={dist:.0f}nm < {min_space[layer]}nm',
                })

    return violations


def run(placement_path=None, netlist_path=None):
    """Run placement access-pad check. Returns error count."""
    if placement_path is None:
        from atk.paths import PLACEMENT_JSON
        placement_path = PLACEMENT_JSON
    if netlist_path is None:
        from atk.paths import NETLIST_JSON
        netlist_path = NETLIST_JSON

    print('=== Placement Access-Pad Check ===')
    violations = check_access_spacing(placement_path, netlist_path)

    overlaps = [v for v in violations if v['type'] == 'overlap']
    spacings = [v for v in violations if v['type'] == 'spacing']

    if overlaps:
        print(f'\n  OVERLAPS ({len(overlaps)}):')
        for v in overlaps:
            print(f'    {v["pin_a"]}({v["net_a"]}) <-> '
                  f'{v["pin_b"]}({v["net_b"]}) '
                  f'{v["layer"]}: {v["detail"]}')

    if spacings:
        print(f'\n  SPACING VIOLATIONS ({len(spacings)}):')
        for v in spacings:
            print(f'    {v["pin_a"]}({v["net_a"]}) <-> '
                  f'{v["pin_b"]}({v["net_b"]}) '
                  f'{v["layer"]}: {v["detail"]}')

    total = len(violations)
    print(f'\n  Result: {len(overlaps)} overlaps, {len(spacings)} spacing violations')
    return total


if __name__ == '__main__':
    args = sys.argv[1:]
    placement = args[0] if len(args) > 0 else None
    netlist = args[1] if len(args) > 1 else None
    sys.exit(0 if run(placement, netlist) == 0 else 1)
