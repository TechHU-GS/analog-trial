"""Pre-GDS coordinate sanity checks.

Run BEFORE assemble_gds to catch coordinate mismatches early.

Three checks:
  1. access.py pin positions vs device_lib.json port centers (±10nm)
  2. routing.json access_points vs compute_access_points() (±5nm)
  3. m1_stub overlap with device M1 finger (must be > 0)

Usage:
    python -m atk.verify.coordinate_verify [routing.json] [placement.json]
"""
import json
import sys
from pathlib import Path

from atk.pdk import UM, s5
from atk.route.access import (
    _DEVICES, abs_pin_nm, compute_access_points, inst_bbox_nm,
)


def check_pins_vs_device_lib(device_lib_path, tolerance=10):
    """Check 1: access.py pin X vs device_lib.json port center X.

    Only checks gate pins (G) where GatPoly finger center is the ground truth.
    """
    with open(device_lib_path) as f:
        dlib = json.load(f)

    errors = []
    for dev_type, dev in _DEVICES.items():
        if 'G' not in dev['pins']:
            continue
        dlib_dev = dlib.get(dev_type)
        if dlib_dev is None:
            continue
        gp = dlib_dev['shapes_by_layer'].get('GatPoly_5_0', [])
        if not gp:
            continue

        # device_lib finger X centers
        lib_xs = sorted(set((r[0] + r[2]) // 2 for r in gp))
        # access.py G pin X (relative to PCell origin, in µm)
        gx_um = dev['pins']['G'][0]
        gx_nm = round(gx_um * UM)

        # For ng=1: single finger. For ng=2: G pin should match finger[0].
        if lib_xs and abs(gx_nm - lib_xs[0]) > tolerance:
            errors.append(
                f'{dev_type}.G: access={gx_nm}nm, device_lib={lib_xs[0]}nm, '
                f'delta={gx_nm - lib_xs[0]}nm')

        # Check poly_bot Y
        gy_um = dev['pins']['G'][1]
        gy_nm = round(gy_um * UM)
        lib_poly_bot = min(r[1] for r in gp)
        if abs(gy_nm - lib_poly_bot) > tolerance:
            errors.append(
                f'{dev_type}.G_Y: access={gy_nm}nm, device_lib={lib_poly_bot}nm, '
                f'delta={gy_nm - lib_poly_bot}nm')

    return errors


def check_routing_vs_computed(routing_path, placement_path, tolerance=5):
    """Check 2: routing.json access_points vs compute_access_points().

    Compares x, y, mode for every pin.
    """
    with open(routing_path) as f:
        routing = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)

    stored_ap = routing.get('access_points', {})
    computed = compute_access_points(placement)

    errors = []
    # Convert computed keys from (inst, pin) tuples to "inst.pin" strings
    computed_by_key = {}
    for (inst, pin), val in computed.items():
        computed_by_key[f'{inst}.{pin}'] = val

    for key, stored in stored_ap.items():
        comp = computed_by_key.get(key)
        if comp is None:
            errors.append(f'{key}: in routing.json but not computed')
            continue

        dx = abs(stored['x'] - comp['x'])
        dy = abs(stored['y'] - comp['y'])
        if dx > tolerance or dy > tolerance:
            errors.append(
                f'{key}: stored=({stored["x"]},{stored["y"]}) '
                f'computed=({comp["x"]},{comp["y"]}) '
                f'delta=({dx},{dy})')

        if stored.get('mode') != comp.get('mode'):
            errors.append(
                f'{key}: mode stored={stored.get("mode")} '
                f'computed={comp.get("mode")}')

    for key in computed_by_key:
        if key not in stored_ap:
            errors.append(f'{key}: computed but missing from routing.json')

    return errors


def check_m1_stub_overlap(placement_path, tolerance=0):
    """Check 3: m1_stub must overlap device M1 finger by > 0.

    The m1_stub connects the via pad down to the device's M1 drain/source.
    Zero overlap = open circuit.
    """
    with open(placement_path) as f:
        placement = json.load(f)

    # Load device_lib for M1 shapes
    dlib_path = Path(__file__).parent.parent / 'data' / 'device_lib.json'
    with open(dlib_path) as f:
        dlib = json.load(f)

    computed = compute_access_points(placement)
    errors = []

    for (inst_name, pin_name), ap in computed.items():
        stub = ap.get('m1_stub')
        if stub is None:
            continue

        inst = placement['instances'][inst_name]
        dev_type = inst['type']
        dev = _DEVICES.get(dev_type)
        if dev is None:
            continue

        dlib_dev = dlib.get(dev_type)
        if dlib_dev is None:
            continue

        m1_shapes = dlib_dev['shapes_by_layer'].get('M1_8_0', [])
        if not m1_shapes:
            continue

        # PCell origin (nm)
        pcell_x = s5(inst['x_um']) - s5(dev['ox'])
        pcell_y = s5(inst['y_um']) - s5(dev['oy'])

        # Find the M1 finger that contains this pin's X
        pin_rel_x = round(dev['pins'][pin_name][0] * UM)

        best_overlap = -1
        best_finger = None
        for m1 in m1_shapes:
            # Absolute M1 finger
            fx1 = pcell_x + m1[0]
            fy1 = pcell_y + m1[1]
            fx2 = pcell_x + m1[2]
            fy2 = pcell_y + m1[3]

            # Check if this finger's X range contains the pin X
            abs_pin_x = s5(pcell_x / UM + pin_rel_x / UM)
            if not (fx1 <= abs_pin_x <= fx2):
                continue

            # Compute overlap area with stub
            ox = max(0, min(stub[2], fx2) - max(stub[0], fx1))
            oy = max(0, min(stub[3], fy2) - max(stub[1], fy1))
            overlap = ox * oy

            if overlap > best_overlap:
                best_overlap = overlap
                best_finger = (fx1, fy1, fx2, fy2)

        if best_finger is not None and best_overlap <= tolerance:
            errors.append(
                f'{inst_name}.{pin_name}: m1_stub={stub} '
                f'finger={list(best_finger)} overlap={best_overlap}nm²')

    return errors


def run(routing_path=None, placement_path=None, device_lib_path=None):
    """Run all checks. Returns total error count."""
    if routing_path is None:
        from atk.paths import ROUTING_JSON
        routing_path = ROUTING_JSON
    if placement_path is None:
        from atk.paths import PLACEMENT_JSON
        placement_path = PLACEMENT_JSON
    if device_lib_path is None:
        device_lib_path = str(
            Path(__file__).parent.parent / 'data' / 'device_lib.json')

    total_errors = 0

    print('=== Check 1: access.py pins vs device_lib.json ===')
    errs = check_pins_vs_device_lib(device_lib_path)
    for e in errs:
        print(f'  ERROR: {e}')
    print(f'  {len(errs)} errors')
    total_errors += len(errs)

    print('\n=== Check 2: routing.json vs computed access points ===')
    errs = check_routing_vs_computed(routing_path, placement_path)
    for e in errs:
        print(f'  ERROR: {e}')
    print(f'  {len(errs)} errors')
    total_errors += len(errs)

    print('\n=== Check 3: m1_stub overlap with device M1 ===')
    errs = check_m1_stub_overlap(placement_path)
    for e in errs:
        print(f'  ERROR: {e}')
    print(f'  {len(errs)} errors')
    total_errors += len(errs)

    print(f'\nTotal: {total_errors} errors')
    return total_errors


if __name__ == '__main__':
    args = sys.argv[1:]
    routing = args[0] if len(args) > 0 else None
    placement = args[1] if len(args) > 1 else None
    sys.exit(0 if run(routing, placement) == 0 else 1)
