"""Pin access point computation for routing.

Pure math — no GDS drawing.  Returns coordinates + geometry descriptors
that both the maze router (obstacle registration) and GDS renderer use.

Eight access modes:
  above      — Via1 above device bbox, M1 stub from bbox top to via
  below      — Via1 below device bbox, M1 stub from bbox bottom to via
  m2_below   — Via1 below device bbox, M2 stub from via up to pin.
               Used for HBT emitter: pin is on PCell M2 but M1 stub
               would cross base M1 bar causing shorts.
  gate       — Via1 at gate pin position (below bbox, safe clearance)
  gate_no_m1 — Like gate but M1 pad omitted (PCell provides M1).
               Used when G-S=G-D distance is too tight for VIA1_PAD_M1.
  direct     — Via1 at pin position (resistors, pin near bbox edge)
  m1_pin     — M1-only access, no via (tight NMOS G-S spacing)
  m2         — Pin already on M2 (HBT B), no via needed

Data sources:
  - device_lib.json: device geometry (pins, bbox, implant bounds)
  - netlist.json constraints.pin_access: access mode table
  - netlist.json constraints.hbt_extras: m2_stub_dx
"""

from atk.pdk import (
    UM, s5,
    VIA_CLEAR, HBT_VIA_CLEAR,
    VIA1_PAD_M1, VIA1_PAD, VIA1_SZ,
    M1_THIN,
)
from atk.device import load_device_lib, get_device_info as _dl_get_device_info
from atk.paths import DEVICE_LIB_JSON, NETLIST_JSON
import json

# ═══════════════════════════════════════════════════
# Load data from device_lib.json + netlist.json
# ═══════════════════════════════════════════════════

_device_lib = load_device_lib(DEVICE_LIB_JSON)

with open(NETLIST_JSON) as _f:
    _netlist = json.load(_f)
_constraints = _netlist.get('constraints', {})

# Pin access mode table — from netlist.json constraints.pin_access
_PIN_ACCESS_TABLE = _constraints.get('pin_access', {})

# HBT M2 stub offsets — from netlist.json constraints.hbt_extras
_HBT_EXTRAS = _constraints.get('hbt_extras', {})

# Build _DEVICES dict from device_lib.json (backward compat for external consumers)
_DEVICES = {}
for _dt in _device_lib:
    _info = _dl_get_device_info(_device_lib, _dt)
    _entry = {
        'w': _info['w'], 'h': _info['h'],
        'ox': _info['ox'], 'oy': _info['oy'],
        'pins': _info['pins'],
    }
    # Add HBT m2_stub_dx from netlist.json
    if _dt in _HBT_EXTRAS:
        _entry['m2_stub_dx'] = _HBT_EXTRAS[_dt].get('m2_stub_dx', 0)
    _DEVICES[_dt] = _entry

# Build PIN_ACCESS flat dict for backward compat
PIN_ACCESS = {}
for _dt, _pins in _PIN_ACCESS_TABLE.items():
    if _dt.startswith('_'):
        continue  # skip _note
    for _pn, _mode in _pins.items():
        PIN_ACCESS[(_dt, _pn)] = _mode


# ═══════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════

def get_device_info(dev_type):
    """Return device info dict for a device type."""
    return _DEVICES[dev_type]


def get_access_mode(dev_type, pin_name):
    """Return access mode for (device_type, pin_name)."""
    return PIN_ACCESS.get((dev_type, pin_name), 'above')


def inst_bbox_nm(placement, inst_name):
    """Return (left, bot, right, top) in nm for a placed instance."""
    inst = placement['instances'][inst_name]
    x = s5(inst['x_um'])
    y = s5(inst['y_um'])
    w = s5(inst['w_um'])
    h = s5(inst['h_um'])
    return (x, y, x + w, y + h)


def abs_pin_nm(placement, inst_name):
    """Return dict of {pin_name: (x_nm, y_nm)} for all pins of an instance."""
    inst = placement['instances'][inst_name]
    dev_type = inst['type']
    dev = _DEVICES[dev_type]
    # PCell origin = placement position - bbox offset (ox, oy are negative offsets)
    origin_x = s5(inst['x_um']) - s5(dev['ox'])
    origin_y = s5(inst['y_um']) - s5(dev['oy'])
    result = {}
    for pin_name, (px, py) in dev['pins'].items():
        result[pin_name] = (s5(origin_x / UM + px), s5(origin_y / UM + py))
    return result


def compute_access_points(placement):
    """Compute access point for every (instance, pin) pair.

    Returns dict mapping (inst_name, pin_name) → AccessPoint dict:
        {
            'x': int,              # nm
            'y': int,              # nm
            'mode': str,           # access mode
            'via_pad': {           # geometry for obstacle registration + GDS drawing
                'm1': [x1,y1,x2,y2],
                'm2': [x1,y1,x2,y2],
                'via1': [x1,y1,x2,y2],
            } or None,
            'm1_stub': [x1,y1,x2,y2] or None,
        }
    """
    hp_m1 = VIA1_PAD_M1 // 2  # 185
    hp_m2 = VIA1_PAD // 2     # 240
    hs_v1 = VIA1_SZ // 2      # 95
    hp_stub = M1_THIN // 2    # 80 — narrower M1 stub body avoids
    #                           shorting to adjacent gate M1 when stub
    #                           passes through device (below/above mode)

    access = {}

    for inst_name, inst in placement['instances'].items():
        dev_type = inst['type']
        dev = _DEVICES.get(dev_type)
        if dev is None:
            continue
        pins = abs_pin_nm(placement, inst_name)
        bbox = inst_bbox_nm(placement, inst_name)
        is_hbt = dev_type.startswith('hbt')
        clear = HBT_VIA_CLEAR if is_hbt else VIA_CLEAR

        # M1 finger top sits |oy| below bbox top (oy is negative offset)
        oy_nm = abs(s5(dev['oy']))  # typically 310nm

        for pin_name in dev['pins']:
            mode = get_access_mode(dev_type, pin_name)
            px, py = pins[pin_name]

            if mode == 'above':
                via_y = bbox[3] + clear  # bbox_top + clearance
                # M1 stub: pin position to via pad (must reach PCell M1
                # finger for Cont→M1→Via1 connectivity).
                # Use hp_stub (M1_THIN/2) width to avoid shorting to
                # adjacent gate M1 when stub passes through device body.
                m1_stub = [px - hp_stub, py,
                           px + hp_stub, via_y + hp_m1]
                via_pad = _make_via_pad(px, via_y, hp_m1, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': via_y, 'mode': 'above',
                    'via_pad': via_pad, 'm1_stub': m1_stub,
                }

            elif mode == 'below':
                via_y = bbox[1] - clear  # bbox_bot - clearance
                # M1 stub: via pad to pin position (must reach PCell M1
                # finger for Cont→M1→Via1 connectivity).
                # Use hp_stub (M1_THIN/2) width — same rationale as above.
                m1_stub = [px - hp_stub, via_y - hp_m1,
                           px + hp_stub, py]
                via_pad = _make_via_pad(px, via_y, hp_m1, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': via_y, 'mode': 'below',
                    'via_pad': via_pad, 'm1_stub': m1_stub,
                }

            elif mode == 'm2_below':
                via_y = bbox[1] - clear  # bbox_bot - clearance
                # X offset: avoid B→C pre-route M2 at same X as pin
                stub_dx = dev.get('m2_stub_dx', 0)
                stub_x = px + stub_dx
                # M2 stub: via pad to PCell M2 (avoids M1 crossing base bar)
                m2_stub = [stub_x - hp_m2, via_y - hp_m2,
                           stub_x + hp_m2, py]
                via_pad = _make_via_pad(stub_x, via_y, hp_m1, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': stub_x, 'y': via_y, 'mode': 'm2_below',
                    'via_pad': via_pad, 'm1_stub': None,
                    'm2_stub': m2_stub,
                }

            elif mode == 'gate':
                via_pad = _make_via_pad(px, py, hp_m1, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': py, 'mode': 'gate',
                    'via_pad': via_pad, 'm1_stub': None,
                }

            elif mode == 'gate_no_m1':
                # Via1 + M2 pad at gate pin, but NO M1 pad (PCell provides M1).
                # The via_pad still has m1 key for obstacle registration in router,
                # but GDS assembly will skip drawing M1 for this mode.
                via_pad = _make_via_pad(px, py, hp_m1, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': py, 'mode': 'gate_no_m1',
                    'via_pad': via_pad, 'm1_stub': None,
                }

            elif mode == 'direct':
                via_pad = _make_via_pad(px, py, hp_m2, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': py, 'mode': 'direct',
                    'via_pad': via_pad, 'm1_stub': None,
                }

            elif mode == 'm2':
                # Already on M2 — no via, just record position
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': py, 'mode': 'm2',
                    'via_pad': None, 'm1_stub': None,
                }

            elif mode == 'm1_pin':
                # M1-only access: tight G-S spacing precludes standard
                # VIA1_PAD_M1 pad.  GDS assembly creates a compact Via1 +
                # full M2 pad at (px, py) to bridge M1 pin to M2 routing.
                # Include via_pad so solver blocks the M2 area.
                # M1 pad: hs_v1 + 50nm for V1.c1 endcap enclosure (50nm).
                hp_m1_pin = hs_v1 + 50  # 145nm half → 290nm M1 pad
                via_pad = _make_via_pad(px, py, hp_m1_pin, hp_m2, hs_v1)
                access[(inst_name, pin_name)] = {
                    'x': px, 'y': py, 'mode': 'm1_pin',
                    'via_pad': via_pad, 'm1_stub': None,
                }

    return access


def _make_via_pad(cx, cy, hp_m1, hp_m2, hs_v1):
    """Create via pad geometry descriptor."""
    return {
        'm1': [cx - hp_m1, cy - hp_m1, cx + hp_m1, cy + hp_m1],
        'm2': [cx - hp_m2, cy - hp_m2, cx + hp_m2, cy + hp_m2],
        'via1': [cx - hs_v1, cy - hs_v1, cx + hs_v1, cy + hs_v1],
    }
