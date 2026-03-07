"""Validate device.py loader against hardcoded reference data.

Compares outputs from device.py (reading device_lib_v2.json) against
the hardcoded values in access.py, tie_placer.py, and assemble_gds.py.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import device

# Load device_lib_v2.json
LIB_PATH = os.path.join(os.path.dirname(__file__), 'device_lib_v2.json')
lib = device.load_device_lib(LIB_PATH)

n_pass = 0
n_fail = 0
n_warn = 0


def check(name, got, expected, tolerance=0):
    global n_pass, n_fail
    if tolerance > 0:
        ok = abs(got - expected) <= tolerance
    else:
        ok = (got == expected)
    if ok:
        n_pass += 1
    else:
        n_fail += 1
        print(f"  FAIL {name}: got {got}, expected {expected}")
    return ok


def warn(msg):
    global n_warn
    n_warn += 1
    print(f"  WARN {msg}")


# ═══════════════════════════════════════
# 1. Pin positions vs tie_placer.py DEVICE_PINS_NM
# ═══════════════════════════════════════
print("=== 1. Pin positions (tie_placer.py reference) ===\n")

TIE_PINS = {
    'pmos_mirror': {'S1': (150, 1000), 'D': (2530, 1000), 'S2': (4910, 1000), 'G': (1340, -180)},
    'pmos_vco':    {'S': (150, 1000), 'D': (1030, 1000), 'G': (590, -180)},
    'pmos_buf1':   {'S': (150, 2000), 'D': (1030, 2000), 'G': (590, -180)},
    'pmos_buf2':   {'S1': (150, 2000), 'D': (1030, 2000), 'S2': (1910, 2000), 'G': (590, -180)},
    'nmos_vco':    {'S': (150, 500), 'D': (1030, 500), 'G': (590, -180)},
    'nmos_bias':   {'S': (150, 500), 'D': (4530, 500), 'G': (2340, -180)},
    'nmos_diode':  {'S': (150, 1000), 'D': (1530, 1000), 'G': (840, -180)},
    'nmos_buf1':   {'S': (150, 1000), 'D': (1030, 1000), 'G': (590, -180)},
    'nmos_buf2':   {'S': (150, 1000), 'D': (1030, 1000), 'S2': (1910, 1000), 'G': (590, -180)},
}

for dev_type, expected_pins in TIE_PINS.items():
    pins = device.get_device_pins_nm(lib, dev_type)
    for pname, (ex, ey) in expected_pins.items():
        # Handle nmos_buf2 S→S1 naming convention difference
        actual_name = pname
        if pname == 'S' and pname not in pins and 'S1' in pins:
            actual_name = 'S1'
            warn(f"{dev_type}: naming S→S1 (auto-prober uses consistent S1 for ng≥2)")
        if actual_name in pins:
            ax, ay = pins[actual_name]
            check(f"{dev_type}.{pname}.x", ax, ex)
            check(f"{dev_type}.{pname}.y", ay, ey)
        else:
            check(f"{dev_type}.{pname} exists", False, True)

# ═══════════════════════════════════════
# 2. Resistor pin positions vs access.py
# ═══════════════════════════════════════
print("\n=== 2. Resistor pin positions (access.py reference) ===\n")

RES_PINS = {
    'rppd_iso':    {'MINUS': (1250, -280), 'PLUS': (1250, 5280)},
    'rppd_ptat':   {'MINUS': (250, -280), 'PLUS': (7730, -320)},
    'rppd_start':  {'MINUS': (250, -280), 'PLUS': (250, 14680)},
    'rppd_out':    {'MINUS': (250, -280), 'PLUS': (3650, -290)},
}

for dev_type, expected_pins in RES_PINS.items():
    pins = device.get_device_pins_nm(lib, dev_type)
    for pname, (ex, ey) in expected_pins.items():
        if pname in pins:
            ax, ay = pins[pname]
            check(f"{dev_type}.{pname}.x", ax, ex)
            check(f"{dev_type}.{pname}.y", ay, ey)
        else:
            check(f"{dev_type}.{pname} exists", False, True)

# ═══════════════════════════════════════
# 3. HBT pin positions vs access.py
# ═══════════════════════════════════════
print("\n=== 3. HBT pin positions (access.py reference) ===\n")

HBT_PINS = {
    'hbt_1x': {'C': (0, 1130), 'B': (0, -1140), 'E': (0, 0)},
    'hbt_8x': {'C': (6475, 1240), 'B': (6475, -1140), 'E': (6475, 0)},
}

for dev_type, expected_pins in HBT_PINS.items():
    pins = device.get_device_pins_nm(lib, dev_type)
    for pname, (ex, ey) in expected_pins.items():
        if pname in pins:
            ax, ay = pins[pname]
            check(f"{dev_type}.{pname}.x", ax, ex)
            # E pin has 7nm text label offset — accept tolerance
            tol = 10 if pname == 'E' else 0
            check(f"{dev_type}.{pname}.y", ay, ey, tolerance=tol)
        else:
            check(f"{dev_type}.{pname} exists", False, True)

# ═══════════════════════════════════════
# 4. NWell/pSD bounds vs tie_placer.py NWELL_TIE_INFO
# ═══════════════════════════════════════
print("\n=== 4. NWell/pSD bounds (tie_placer.py reference) ===\n")

NWELL_REF = {
    'pmos_mirror': {'nw': (-310, -310, 5370, 2310), 'psd': (-180, -300, 5240, 2300)},
    'pmos_vco':    {'nw': (-310, -310, 1490, 2310), 'psd': (-180, -300, 1360, 2300)},
    'pmos_buf1':   {'nw': (-310, -310, 1490, 4310), 'psd': (-180, -300, 1360, 4300)},
    'pmos_buf2':   {'nw': (-310, -310, 2370, 4310), 'psd': (-180, -300, 2240, 4300)},
}

for dev_type, expected in NWELL_REF.items():
    info = device.get_nwell_tie_info(lib, dev_type)
    if info is None:
        check(f"{dev_type} nwell_tie_info exists", False, True)
        continue
    for key in ('nw', 'psd'):
        if key in expected and key in info:
            check(f"{dev_type}.{key}", info[key], expected[key])
        elif key in expected:
            check(f"{dev_type}.{key} exists", False, True)

# ═══════════════════════════════════════
# 5. Device sizes vs assemble_gds.py DEVICES
# ═══════════════════════════════════════
print("\n=== 5. Device sizes (assemble_gds.py reference) ===\n")

SIZE_REF = {
    'pmos_mirror': (5.68, 2.62, -0.31, -0.31),
    'pmos_vco':    (1.80, 2.62, -0.31, -0.31),
    'pmos_buf1':   (1.80, 4.62, -0.31, -0.31),
    'pmos_buf2':   (2.68, 4.62, -0.31, -0.31),  # assemble_gds.py value (access.py has stale 3.56)
    'nmos_vco':    (1.18, 1.36,  0.00, -0.18),   # assemble_gds.py value (access.py has stale 2.36)
    'nmos_bias':   (4.68, 1.36,  0.00, -0.18),
    'nmos_diode':  (1.68, 2.36,  0.00, -0.18),
    'nmos_buf1':   (1.18, 2.36,  0.00, -0.18),
    'nmos_buf2':   (2.06, 2.36,  0.00, -0.18),
    'rppd_iso':    (2.90, 6.22, -0.20, -0.61),
    'rppd_ptat':   (8.38, 14.93, -0.20, -0.65),
    'rppd_start':  (0.90, 15.62, -0.20, -0.61),
    'rppd_out':    (4.30, 7.29, -0.20, -0.62),
    'hbt_1x':      (6.70, 7.11, -3.35, -3.33),
    'hbt_8x':      (19.65, 7.11, -3.35, -3.33),
}

for dev_type, (w, h, ox, oy) in SIZE_REF.items():
    info = device.get_device_info(lib, dev_type)
    # 0.01µm tolerance for rounding (assemble_gds.py uses 2dp, we use 3dp)
    check(f"{dev_type}.w", info['w'], w, tolerance=0.01)
    check(f"{dev_type}.h", info['h'], h, tolerance=0.01)
    check(f"{dev_type}.ox", info['ox'], ox, tolerance=0.01)
    check(f"{dev_type}.oy", info['oy'], oy, tolerance=0.01)

# ═══════════════════════════════════════
# 6. Gate info (NG2_GATE_DATA format)
# ═══════════════════════════════════════
print("\n=== 6. Gate info (assemble_gds.py NG2_GATE_DATA reference) ===\n")

NG2_REF = {
    'pmos_mirror': {'g1': 1.34, 'poly_bot': -0.18},
    'pmos_buf2':   {'g1': 0.59, 'g2': 1.47, 'poly_bot': -0.18},
    'nmos_buf2':   {'g1': 0.59, 'g2': 1.47, 'poly_bot': -0.18},
}

for dev_type, expected in NG2_REF.items():
    gi = device.get_gate_info(lib, dev_type)
    if gi is None:
        check(f"{dev_type} gate_info exists", False, True)
        continue
    fingers = gi['finger_xs']
    pbot = gi['poly_bot']
    check(f"{dev_type}.g1", round(fingers[0] / 1000, 3), expected['g1'])
    if 'g2' in expected:
        check(f"{dev_type}.g2", round(fingers[1] / 1000, 3), expected['g2'])
    check(f"{dev_type}.poly_bot", round(pbot / 1000, 3), expected['poly_bot'])

# ═══════════════════════════════════════
# 7. Classification
# ═══════════════════════════════════════
print("\n=== 7. Device classification ===\n")

CLASS_REF = {
    'pmos_mirror': ('pmos', True, True, False),
    'nmos_vco':    ('nmos', False, False, True),
    'hbt_1x':      ('hbt', False, False, False),
    'rppd_iso':    ('resistor', False, False, False),
}

for dev_type, (cls, nw, ntap, ptap) in CLASS_REF.items():
    c = device.get_classification(lib, dev_type)
    check(f"{dev_type}.device_class", c['device_class'], cls)
    check(f"{dev_type}.has_nwell", c['has_nwell'], nw)
    check(f"{dev_type}.requires_ntap", c['requires_ntap'], ntap)
    check(f"{dev_type}.requires_ptap", c['requires_ptap'], ptap)

# ═══════════════════════════════════════
# Summary
# ═══════════════════════════════════════
print(f"\n{'='*50}")
print(f"TOTAL: {n_pass} PASS, {n_fail} FAIL, {n_warn} WARN")
if n_fail == 0:
    print("ALL CHECKS PASSED — device.py loader validated")
else:
    print(f"FAILURES detected — review above")
    sys.exit(1)
