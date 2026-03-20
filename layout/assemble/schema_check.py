"""Pipeline JSON schema validation.

Validates placement.json, ties.json, routing.json structure
before assembly consumes them. Catches structural errors early.

Usage:
    from assemble.schema_check import validate_all
    errors = validate_all(placement, ties, routing)
"""


def validate_placement(p):
    """Validate placement.json structure."""
    errors = []
    if 'instances' not in p:
        errors.append('placement: missing "instances"')
        return errors

    for name, info in p['instances'].items():
        for field in ('x_um', 'y_um', 'type'):
            if field not in info:
                errors.append(f'placement: {name} missing "{field}"')
        if 'x_um' in info and 'y_um' in info:
            if info['x_um'] < -10 or info['x_um'] > 500:
                errors.append(f'placement: {name} x_um={info["x_um"]} out of range')
            if info['y_um'] < -10 or info['y_um'] > 500:
                errors.append(f'placement: {name} y_um={info["y_um"]} out of range')

    bb = p.get('bounding_box', {})
    if 'w_um' not in bb or 'h_um' not in bb:
        errors.append('placement: missing bounding_box w_um/h_um')

    return errors


def validate_ties(t):
    """Validate ties.json structure."""
    errors = []
    if 'ties' not in t:
        errors.append('ties: missing "ties" array')
        return errors

    for i, tie in enumerate(t['ties']):
        for field in ('id', 'net', 'device', 'center_nm'):
            if field not in tie:
                errors.append(f'ties[{i}]: missing "{field}"')
        if 'net' in tie and tie['net'] not in ('gnd', 'vdd', 'vdd_vco'):
            errors.append(f'ties[{i}]: unexpected net "{tie["net"]}"')
        if 'center_nm' in tie:
            cx, cy = tie['center_nm']
            if cx < 0 or cx > 500000 or cy < 0 or cy > 500000:
                errors.append(f'ties[{i}] ({tie.get("id","")}): '
                              f'center ({cx},{cy}) out of range')

    return errors


def validate_routing(r, placement=None):
    """Validate routing.json structure."""
    errors = []

    # Access points
    aps = r.get('access_points', {})
    if not aps:
        errors.append('routing: no access_points')

    for key, ap in aps.items():
        if '.' not in key:
            errors.append(f'routing: AP key "{key}" missing dot (expect inst.pin)')
        for field in ('x', 'y'):
            if field not in ap:
                errors.append(f'routing: AP {key} missing "{field}"')

    # Cross-reference: AP instance names should exist in placement
    if placement:
        inst_names = set(placement.get('instances', {}).keys())
        for key in aps:
            inst = key.split('.')[0]
            if inst not in inst_names:
                errors.append(f'routing: AP {key} instance "{inst}" '
                              f'not in placement')

    # Signal routes
    for net_name, route in r.get('signal_routes', {}).items():
        segs = route.get('segments', [])
        for i, seg in enumerate(segs):
            if len(seg) < 5:
                errors.append(f'routing: {net_name} seg[{i}] has '
                              f'{len(seg)} fields (need 5)')

    # Power
    power = r.get('power', {})
    for drop in power.get('drops', []):
        for field in ('net', 'inst', 'pin', 'type'):
            if field not in drop:
                errors.append(f'routing: power drop missing "{field}"')

    return errors


def validate_all(placement, ties, routing):
    """Run all validations. Returns list of error strings."""
    errors = []
    errors.extend(validate_placement(placement))
    errors.extend(validate_ties(ties))
    errors.extend(validate_routing(routing, placement))
    return errors


def print_validation(placement, ties, routing):
    """Validate and print results."""
    errors = validate_all(placement, ties, routing)
    if errors:
        print(f'  ⚠️ Schema validation: {len(errors)} errors')
        for e in errors[:10]:
            print(f'    {e}')
        if len(errors) > 10:
            print(f'    ... +{len(errors)-10} more')
    else:
        print(f'  ✓ Schema validation: all OK')
    return errors
