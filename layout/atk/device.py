"""Unified device_lib.json loader for ATK toolbox.

Replaces hardcoded device data in:
  - access.py (_DEVICES, PIN_ACCESS)
  - tie_placer.py (DEVICE_PINS_NM, NWELL_TIE_INFO, NTAP_CONFIG)
  - assemble_gds.py (DEVICES, NG2_GATE_DATA)
  - verify/*.py (duplicate DEVICES/PIN_ACCESS)

Data sources:
  - device_lib.json: auto-generated geometry (Phase C probing)
  - netlist.json constraints: design choices (pin_access, tie_config, m2_stub_dx)
"""

import json
import os


# nm ↔ µm conversion
UM = 1000  # 1 µm = 1000 nm


def _snap5(nm):
    """Snap nm value to 5nm grid."""
    return ((nm + 2) // 5) * 5


def load_device_lib(path):
    """Load device_lib.json and return raw dict."""
    with open(path) as f:
        return json.load(f)


def get_device_info(device_lib, dev_type):
    """Return device info dict compatible with access.py _DEVICES format.

    Returns:
        {
            'w': float (µm), 'h': float (µm),
            'ox': float (µm), 'oy': float (µm),
            'pins': {pin_name: (x_µm, y_µm), ...},
        }
    """
    d = device_lib[dev_type]
    bb = d['bbox']
    w_um = round((bb[2] - bb[0]) / UM, 3)
    h_um = round((bb[3] - bb[1]) / UM, 3)
    ox_um = round(bb[0] / UM, 3)
    oy_um = round(bb[1] / UM, 3)

    pins_um = {}
    for pname, pdata in d['pins'].items():
        x_nm, y_nm = pdata['pos_nm']
        pins_um[pname] = (round(x_nm / UM, 3), round(y_nm / UM, 3))

    return {
        'w': w_um, 'h': h_um,
        'ox': ox_um, 'oy': oy_um,
        'pins': pins_um,
    }


def get_all_device_info(device_lib):
    """Return _DEVICES-compatible dict for all devices."""
    result = {}
    for dev_type in device_lib:
        result[dev_type] = get_device_info(device_lib, dev_type)
    return result


def get_device_pins_nm(device_lib, dev_type):
    """Return pin positions in nm (tie_placer.py DEVICE_PINS_NM format).

    Returns: {pin_name: (x_nm, y_nm), ...}
    """
    d = device_lib[dev_type]
    pins = {}
    for pname, pdata in d['pins'].items():
        x, y = pdata['pos_nm']
        pins[pname] = (x, y)
    return pins


def get_nwell_tie_info(device_lib, dev_type):
    """Return NWell/pSD bounds (tie_placer.py NWELL_TIE_INFO format).

    Returns: {'nw': (x1, y1, x2, y2), 'psd': (x1, y1, x2, y2)} or None.
    """
    d = device_lib[dev_type]
    ib = d.get('implant_bounds', {})
    if 'nwell' not in ib:
        return None
    result = {}
    if 'nwell' in ib:
        result['nw'] = tuple(ib['nwell'])
    if 'psd' in ib:
        result['psd'] = tuple(ib['psd'])
    return result


def get_gate_info(device_lib, dev_type):
    """Return gate finger info from device_lib.

    Returns: {'ng': int, 'finger_xs': [int,...], 'poly_bot': int, 'poly_top': int}
             or None if no gate.
    """
    d = device_lib[dev_type]
    return d.get('gate_info', None)


def _format_pcell_params(raw_params, pcell_type):
    """Convert probed numeric params to KLayout PCell format.

    IHP SG13G2 PCells declare w/l as TypeString ('4u' format).
    Probed params are numeric (µm floats). Convert back.

    Dimension params (w, l, ps) → 'Xu' string.
    Count params (ng, m, b) → int (KLayout coerces to string).
    HBT Nx/Ny → int (TypeInt).
    """
    # Params that represent physical dimensions (µm → 'Xu' string)
    DIM_KEYS = {'w', 'l', 'ps'}
    # Params that are counts (keep as int)
    COUNT_KEYS = {'ng', 'm', 'b'}
    SKIP_KEYS = set()

    result = {}
    for k, v in raw_params.items():
        if k in SKIP_KEYS:
            continue
        if k in DIM_KEYS and isinstance(v, (int, float)):
            # Format: remove trailing decimal zeros, append 'u'
            s = '%.4g' % v
            if '.' in s:
                s = s.rstrip('0').rstrip('.')
            result[k] = s + 'u'
        elif k in COUNT_KEYS:
            result[k] = int(v)
        else:
            result[k] = v
    return result


def get_pcell_params(device_lib, dev_type):
    """Return PCell instantiation params (assemble_gds.py DEVICES format).

    Returns:
        {
            'pcell': str, 'params': {str: value, ...},
            'w': float (µm), 'h': float (µm),
            'ox': float (µm), 'oy': float (µm),
        }
    """
    d = device_lib[dev_type]
    bb = d['bbox']
    result = {
        'pcell': d['pcell'],
        'pcell_name': d.get('pcell_name', d['pcell']),
        'params': _format_pcell_params(d['params'], d['pcell']),
        'w': round((bb[2] - bb[0]) / UM, 3),
        'h': round((bb[3] - bb[1]) / UM, 3),
        'ox': round(bb[0] / UM, 3),
        'oy': round(bb[1] / UM, 3),
    }
    if 'rotation' in d:
        result['rotation'] = d['rotation']
    return result


def get_ng2_gate_data(device_lib, dev_type):
    """Return NG2_GATE_DATA format for ng=2 MOSFET devices only.

    Returns: {'g1': float (µm), 'g2': float (µm), 'poly_bot': float (µm)}
             or None if not a ng=2 MOSFET.
    """
    if not is_mosfet(device_lib, dev_type):
        return None
    gi = get_gate_info(device_lib, dev_type)
    if gi is None or gi['ng'] != 2:
        return None
    fingers = gi['finger_xs']
    return {
        'g1': round(fingers[0] / UM, 3),
        'g2': round(fingers[1] / UM, 3),
        'poly_bot': round(gi['poly_bot'] / UM, 3),
    }


def get_classification(device_lib, dev_type):
    """Return device classification.

    Returns: {'device_class': str, 'has_nwell': bool,
              'requires_ntap': bool, 'requires_ptap': bool}
    """
    return device_lib[dev_type]['classification']


def is_mosfet(device_lib, dev_type):
    """Check if device is a MOSFET (PMOS or NMOS)."""
    cls = device_lib[dev_type]['classification']['device_class']
    return cls in ('pmos', 'nmos')


def get_sd_strips(device_lib, dev_type):
    """Return source and drain M1 strip rectangles for ng>=2 MOSFET devices.

    IHP SG13G2 multi-finger PCells have isolated M1 strips per S/D finger.
    Strips alternate S-D-S-D-...-S (strip 0 = source, strip 1 = drain, etc.).

    Returns: {'source': [(x1, y1, x2, y2), ...], 'drain': [...]}
             or None if ng < 2 or not a MOSFET.
    All coordinates in nm, PCell-local.
    """
    if not is_mosfet(device_lib, dev_type):
        return None
    d = device_lib[dev_type]
    gi = d.get('gate_info')
    if gi is None or gi['ng'] < 2:
        return None

    # Get unique M1 strips sorted by X
    m1_shapes = d['shapes_by_layer'].get('M1_8_0', [])
    unique = []
    for s in m1_shapes:
        if s not in unique:
            unique.append(s)
    unique.sort(key=lambda s: s[0])

    source = [tuple(s) for i, s in enumerate(unique) if i % 2 == 0]
    drain = [tuple(s) for i, s in enumerate(unique) if i % 2 != 0]
    return {'source': source, 'drain': drain}
