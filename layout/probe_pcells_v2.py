"""Phase 0 v2: Enhanced PCell probing for generic ATK.

Extracts everything from v1 PLUS:
- bbox_offset (ox, oy in µm)
- structured pins (pos_nm, pin_role)
- implant_bounds (nwell, psd, activ union bboxes)
- gate_info (ng, finger_xs, poly_bot, poly_top)
- device_class, has_nwell, requires_ntap/ptap
- pcell_name (full KLayout PCell name)

Run: klayout -n sg13g2 -zz -r probe_pcells_v2.py
"""
import pya
import json
import os

layout = pya.Layout()
dbu = layout.dbu  # 0.001 µm = 1nm

# ── Device definitions ──
# CMOS Dual-CS VCO + VPTAT (no BJT)
DEVICES = [
    # PTAT PMOS mirror (PM3, PM4, PM_ref, PM5): w=0.5u l=10u (compact, fits tile)
    # Original l=100u → 101.3µm wide, impossible in 202µm tile. l=10u → 11.3µm.
    ("pmos_mirror", "pmos", {"w": 0.5e-6, "l": 10e-6, "ng": 1, "m": 1}),
    # PMOS current source diode (PM_pdiode): w=0.5u l=2u
    ("pmos_cs", "pmos", {"w": 0.5e-6, "l": 2e-6, "ng": 1, "m": 1}),
    # PMOS current source x8 (Mpb1-5): w=4u l=2u ng=8 (total w, per-finger=0.5u)
    ("pmos_cs8", "pmos", {"w": 4e-6, "l": 2e-6, "ng": 8, "m": 1}),
    # PMOS VCO inverter (MPu1-5): w=2u l=0.5u
    ("pmos_vco", "pmos", {"w": 2e-6, "l": 0.5e-6, "ng": 1, "m": 1}),
    # PMOS buffer stage 1 (MBp1): w=4u l=0.5u
    ("pmos_buf1", "pmos", {"w": 4e-6, "l": 0.5e-6, "ng": 1, "m": 1}),
    # PMOS buffer stage 2 (MBp2): w=8u l=0.5u ng=2
    ("pmos_buf2", "pmos", {"w": 8e-6, "l": 0.5e-6, "ng": 2, "m": 1}),
    # NMOS Vittoz 1x (MN1): w=2u l=4u
    ("nmos_vittoz", "nmos", {"w": 2e-6, "l": 4e-6, "ng": 1, "m": 1}),
    # NMOS Vittoz 8x (MN2): w=16u l=4u ng=8 (total w, per-finger=2u)
    ("nmos_vittoz8", "nmos", {"w": 16e-6, "l": 4e-6, "ng": 8, "m": 1}),
    # NMOS bias unit (MN_diode, MN_pgen): w=1u l=2u
    ("nmos_bias", "nmos", {"w": 1e-6, "l": 2e-6, "ng": 1, "m": 1}),
    # NMOS bias x8 (MNb1-5): w=8u l=2u ng=8 (total w, per-finger=1u)
    ("nmos_bias8", "nmos", {"w": 8e-6, "l": 2e-6, "ng": 8, "m": 1}),
    # NMOS VCO inverter (MPd1-5): w=1u l=0.5u
    ("nmos_vco", "nmos", {"w": 1e-6, "l": 0.5e-6, "ng": 1, "m": 1}),
    # NMOS buffer stage 1 (MBn1): w=2u l=0.5u
    ("nmos_buf1", "nmos", {"w": 2e-6, "l": 0.5e-6, "ng": 1, "m": 1}),
    # NMOS buffer stage 2 (MBn2): w=4u l=0.5u ng=2
    ("nmos_buf2", "nmos", {"w": 4e-6, "l": 0.5e-6, "ng": 2, "m": 1}),
    # PTAT resistor: rhigh w=0.5u l=133u b=12
    ("rhigh_ptat", "rhigh", {"w": 0.5e-6, "l": 133e-6, "b": 12}),
    # Output resistor: rppd w=0.5u l=25u b=4
    ("rppd_out", "rppd", {"w": 0.5e-6, "l": 25e-6, "b": 4}),

    # ── SoilZ v1: Excitation Path (cascode current source) ──
    # Cascode bias ref + mirror x1 (PM_cas_ref, PM_mir1): pmos w=1u l=10u
    ("pmos_cas_mir1", "pmos", {"w": 1e-6, "l": 10e-6, "ng": 1, "m": 1}),
    # Mirror x2 (PM_mir2): pmos w=2u l=10u
    ("pmos_cas_mir2", "pmos", {"w": 2e-6, "l": 10e-6, "ng": 1, "m": 1}),
    # Mirror x4 (PM_mir3): pmos w=4u l=10u ng=2
    ("pmos_cas_mir4", "pmos", {"w": 4e-6, "l": 10e-6, "ng": 2, "m": 1}),
    # Cascode x1 (PM_cas_diode, PM_cas1): pmos w=1u l=2u
    ("pmos_cas1", "pmos", {"w": 1e-6, "l": 2e-6, "ng": 1, "m": 1}),
    # Cascode x2 (PM_cas2): pmos w=2u l=2u
    ("pmos_cas2", "pmos", {"w": 2e-6, "l": 2e-6, "ng": 1, "m": 1}),
    # Cascode x4 (PM_cas3): pmos w=4u l=2u ng=2
    ("pmos_cas4", "pmos", {"w": 4e-6, "l": 2e-6, "ng": 2, "m": 1}),
    # Cascode bias load (MN_cas_load): nmos w=0.5u l=2u
    ("nmos_cas_load", "nmos", {"w": 0.5e-6, "l": 2e-6, "ng": 1, "m": 1}),

    # ── SoilZ v1: Measurement Path (OTA + comparator) ──
    # OTA PMOS active load (XMp_load_p/n): pmos w=4u l=4u
    ("pmos_ota_load", "pmos", {"w": 4e-6, "l": 4e-6, "ng": 1, "m": 1}),
    # OTA NMOS bias diode (XMbias_d): nmos w=4u l=4u
    ("nmos_ota_bias", "nmos", {"w": 4e-6, "l": 4e-6, "ng": 1, "m": 1}),
    # OTA NMOS input pair (XMin_p/n): nmos w=10u l=2u ng=4
    ("nmos_ota_input", "nmos", {"w": 10e-6, "l": 2e-6, "ng": 4, "m": 1}),
    # OTA NMOS tail (XMtail): nmos w=8u l=4u ng=2
    ("nmos_ota_tail", "nmos", {"w": 8e-6, "l": 4e-6, "ng": 2, "m": 1}),
    # Comparator PMOS latch (XMc_lp1/lp2): pmos w=1u l=0.5u
    ("pmos_comp_latch", "pmos", {"w": 1e-6, "l": 0.5e-6, "ng": 1, "m": 1}),

    # ── SoilZ v1: Passives ──
    # 200kΩ ΣΔ resistor (R_in, R_dac): rhigh w=0.5u l=20u b=2 (verified: ~199kΩ)
    ("rhigh_200k", "rhigh", {"w": 0.5e-6, "l": 20e-6, "b": 2}),
    # 1pF MIM cap (C_fb): manual placement in assemble_gds.py, probed for dimensions
    # PCell class = "cmim" in SG13_dev, SPICE model = "cap_cmim"
    # Caspec = 1.5 fF/µm², 26x26µm ≈ 1.01pF
    ("cap_cmim_1p", "cmim", {"w": 26e-6, "l": 26e-6}),
]

LAYER_NAMES = {
    (1, 0):   "Activ_1_0",
    (1, 20):  "Activ_mask_1_20",
    (3, 0):   "BiWind_3_0",
    (5, 0):   "GatPoly_5_0",
    (5, 2):   "GatPoly_pin_5_2",
    (6, 0):   "Cont_6_0",
    (7, 0):   "nSD_7_0",
    (7, 21):  "nSD_block_7_21",
    (8, 0):   "M1_8_0",
    (8, 2):   "M1_pin_8_2",
    (10, 0):  "M2_10_0",
    (10, 2):  "M2_pin_10_2",
    (13, 0):  "BasPoly_13_0",
    (14, 0):  "pSD_14_0",
    (19, 0):  "Via1_19_0",
    (24, 0):  "Res_24_0",
    (26, 0):  "TRANS_26_0",
    (28, 0):  "SalBlock_28_0",
    (29, 0):  "Via2_29_0",
    (30, 0):  "M3_30_0",
    (31, 0):  "NW_31_0",
    (33, 0):  "EmWind_33_0",
    (40, 0):  "Substrate_40_0",
    (44, 0):  "ThickGateOx_44_0",
    (46, 0):  "PWell_46_0",
    (46, 21): "PWell_block_46_21",
    (111, 0): "EXTBlock_111_0",
    (126, 0): "TopMetal1_126_0",
    (128, 0): "PolyRes_128_0",
}

# ── Pin role inference ──
PIN_ROLE_MAP = {
    'S': 'source', 'S1': 'source', 'S2': 'source',
    'D': 'drain',
    'G': 'gate',
    'B': 'base',
    'C': 'collector',
    'E': 'emitter',
    'PLUS': 'plus', 'MINUS': 'minus',
    'SUB': 'substrate',
}


def extract_shapes(cell, layer_idx, dbu):
    rects = []
    for shape in cell.shapes(layer_idx).each():
        if shape.is_box():
            b = shape.box
            rects.append([b.left, b.bottom, b.right, b.top])
        elif shape.is_polygon():
            b = shape.polygon.bbox()
            rects.append([b.left, b.bottom, b.right, b.top])
        elif shape.is_path():
            b = shape.path.polygon().bbox()
            rects.append([b.left, b.bottom, b.right, b.top])
    return rects


def extract_texts(cell, layer_idx):
    texts = {}
    for shape in cell.shapes(layer_idx).each():
        if shape.is_text():
            name = shape.text_string
            x = shape.text_trans.disp.x
            y = shape.text_trans.disp.y
            texts[name] = [x, y]
    return texts


def union_bbox(rects):
    if not rects:
        return None
    x1 = min(r[0] for r in rects)
    y1 = min(r[1] for r in rects)
    x2 = max(r[2] for r in rects)
    y2 = max(r[3] for r in rects)
    return [x1, y1, x2, y2]


def infer_pin_role(pin_name):
    return PIN_ROLE_MAP.get(pin_name.upper(), 'unknown')


def derive_gate_info(shapes_by_layer):
    rects = shapes_by_layer.get('GatPoly_5_0', [])
    if not rects:
        return None
    xs = sorted(set((r[0] + r[2]) // 2 for r in rects))
    poly_bot = min(r[1] for r in rects)
    poly_top = max(r[3] for r in rects)
    return {
        'ng': len(xs),
        'finger_xs': xs,
        'poly_bot': poly_bot,
        'poly_top': poly_top,
    }


def derive_implant_bounds(shapes_by_layer):
    result = {}
    for key, layer_name in [('nwell', 'NW_31_0'), ('psd', 'pSD_14_0'), ('activ', 'Activ_1_0')]:
        rects = shapes_by_layer.get(layer_name, [])
        bb = union_bbox(rects)
        if bb:
            result[key] = bb
    return result


def classify_device(pcell_type):
    if pcell_type == 'pmos':
        return {'device_class': 'pmos', 'has_nwell': True, 'requires_ntap': True, 'requires_ptap': False}
    elif pcell_type == 'nmos':
        return {'device_class': 'nmos', 'has_nwell': False, 'requires_ntap': False, 'requires_ptap': True}
    elif pcell_type == 'npn13G2':
        return {'device_class': 'hbt', 'has_nwell': False, 'requires_ntap': False, 'requires_ptap': False}
    elif pcell_type in ('rppd', 'rhigh'):
        return {'device_class': 'resistor', 'has_nwell': False, 'requires_ntap': False, 'requires_ptap': False}
    elif pcell_type in ('cmim', 'cap_cmim'):
        return {'device_class': 'capacitor', 'has_nwell': False, 'requires_ntap': False, 'requires_ptap': False}
    return {'device_class': 'unknown', 'has_nwell': False, 'requires_ntap': False, 'requires_ptap': False}


def dedupe_rects(rects):
    seen = set()
    unique = []
    for r in rects:
        key = tuple(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def infer_mos_pins(shapes_by_layer, ng, pcell_type):
    """Infer MOS S/D/G pin positions from M1 + GatPoly geometry.

    Returns dict of {pin_name: {'pos_nm': [x, y], 'pin_role': ...}}.
    Pin positions are M1 center for S/D, GatPoly bottom for G.
    Naming: ng=1 → S,D,G. ng≥2 PMOS → S1,D,S2,G. ng≥2 NMOS → S,D,S2,G.
    (Matches existing netlist.json pin naming convention.)
    """
    m1 = dedupe_rects(shapes_by_layer.get('M1_8_0', []))
    gp = dedupe_rects(shapes_by_layer.get('GatPoly_5_0', []))
    if not m1 or not gp:
        return {}

    # Sort M1 strips by center x
    m1_sorted = sorted(m1, key=lambda r: (r[0] + r[2]) // 2)
    pins = {}

    if ng == 1 and len(m1_sorted) >= 2:
        # S (left), D (right)
        for name, rect in [('S', m1_sorted[0]), ('D', m1_sorted[-1])]:
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2
            pins[name] = {'pos_nm': [cx, cy], 'pin_role': 'source' if 'S' in name else 'drain'}
    elif ng >= 2 and len(m1_sorted) >= 3:
        # PMOS ng≥2: S1, D, S2 (netlist uses S1/S2 for PMOS)
        # NMOS ng≥2: S, D, S2 (netlist uses S/S2 for NMOS)
        first_src = 'S1' if pcell_type == 'pmos' else 'S'
        for name, rect in [(first_src, m1_sorted[0]), ('D', m1_sorted[1]), ('S2', m1_sorted[-1])]:
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2
            role = 'drain' if name == 'D' else 'source'
            pins[name] = {'pos_nm': [cx, cy], 'pin_role': role}

    # Gate: first finger center x, poly bottom y
    gp_sorted = sorted(gp, key=lambda r: (r[0] + r[2]) // 2)
    g_cx = (gp_sorted[0][0] + gp_sorted[0][2]) // 2
    g_bot = min(r[1] for r in gp_sorted)
    pins['G'] = {'pos_nm': [g_cx, g_bot], 'pin_role': 'gate'}

    return pins


def infer_res_pins(shapes_by_layer):
    m1 = dedupe_rects(shapes_by_layer.get('M1_8_0', []))
    if len(m1) < 2:
        return {}
    m1_sorted = sorted(m1, key=lambda r: ((r[0]+r[2])//2, (r[1]+r[3])//2))
    pins = {}
    for name, rect in [('MINUS', m1_sorted[0]), ('PLUS', m1_sorted[-1])]:
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        pins[name] = {'pos_nm': [cx, cy], 'pin_role': name.lower()}
    return pins


def infer_cap_pins(raw_ports):
    """Infer capacitor pins from text labels."""
    VALID = {'PLUS': 'plus', 'MINUS': 'minus'}
    pins = {}
    for pname, pdata in raw_ports.items():
        if pname in VALID:
            pins[pname] = {
                'pos_nm': pdata['center'],
                'pin_role': VALID[pname],
            }
    return pins


def infer_hbt_pins(raw_ports):
    VALID = {'C': 'collector', 'B': 'base', 'E': 'emitter'}
    pins = {}
    for pname, pdata in raw_ports.items():
        if pname in VALID:
            pins[pname] = {
                'pos_nm': pdata['center'],
                'pin_role': VALID[pname],
            }
    return pins


# ── Main probing loop ──
result = {}

for dev_name, pcell_type, params in DEVICES:
    print(f"Probing {dev_name} ({pcell_type})...")
    cell = layout.create_cell(pcell_type, "SG13_dev", params)
    bbox = cell.bbox()

    # Extract shapes
    shapes_by_layer = {}
    for li in layout.layer_indices():
        info = layout.get_info(li)
        key = (info.layer, info.datatype)
        layer_name = LAYER_NAMES.get(key, f"L{info.layer}_{info.datatype}")
        shapes = extract_shapes(cell, li, dbu)
        if shapes:
            shapes_by_layer[layer_name] = shapes

    # Extract ports (text labels)
    raw_ports = {}
    for li in layout.layer_indices():
        info = layout.get_info(li)
        texts = extract_texts(cell, li)
        for tname, (tx, ty) in texts.items():
            if tname in ("SG13_dev", ""):
                continue
            layer_key = (info.layer, info.datatype)
            layer_name = LAYER_NAMES.get(layer_key, f"L{info.layer}_{info.datatype}")
            raw_ports[tname] = {"layer": layer_name, "center": [tx, ty]}

    # Ensure key layers have entries
    key_layers = {
        "pmos": ["M1_8_0", "NW_31_0", "pSD_14_0", "Activ_1_0", "GatPoly_5_0", "Cont_6_0"],
        "nmos": ["M1_8_0", "Activ_1_0", "GatPoly_5_0", "Cont_6_0", "NW_31_0", "pSD_14_0"],
        "npn13G2": ["M1_8_0", "M2_10_0", "Via1_19_0", "Activ_1_0", "Cont_6_0"],
        "rppd": ["M1_8_0", "GatPoly_5_0", "Cont_6_0", "PolyRes_128_0", "pSD_14_0"],
        "rhigh": ["M1_8_0", "GatPoly_5_0", "Cont_6_0", "PolyRes_128_0", "pSD_14_0"],
        "cmim": ["M1_8_0", "M2_10_0", "Via1_19_0"],
        "cap_cmim": ["M1_8_0", "M2_10_0", "M3_30_0", "Via1_19_0", "Via2_29_0", "TopMetal1_126_0"],
    }
    for ln in key_layers.get(pcell_type, []):
        if ln not in shapes_by_layer:
            shapes_by_layer[ln] = []

    # ── Derived fields ──

    bbox_offset = {
        'ox_um': round(bbox.left / 1000.0, 3),
        'oy_um': round(bbox.bottom / 1000.0, 3),
    }

    ng = params.get('ng', 1)
    if pcell_type in ('pmos', 'nmos'):
        pins = infer_mos_pins(shapes_by_layer, ng, pcell_type)
    elif pcell_type in ('rppd', 'rhigh'):
        pins = infer_res_pins(shapes_by_layer)
    elif pcell_type in ('cmim', 'cap_cmim'):
        pins = infer_cap_pins(raw_ports)
    elif pcell_type == 'npn13G2':
        pins = infer_hbt_pins(raw_ports)
    else:
        pins = {}
        for pname, pdata in raw_ports.items():
            pins[pname] = {
                'pos_nm': pdata['center'],
                'pin_role': infer_pin_role(pname),
            }

    implant_bounds = derive_implant_bounds(shapes_by_layer)
    gate_info = derive_gate_info(shapes_by_layer)
    classification = classify_device(pcell_type)

    pcell_name = "sg13_lv_pmos" if pcell_type == "pmos" else \
                 "sg13_lv_nmos" if pcell_type == "nmos" else \
                 "cap_cmim" if pcell_type == "cap_cmim" else \
                 pcell_type

    entry = {
        "pcell": pcell_type,
        "params": {k: v if not isinstance(v, float) else round(v * 1e6, 4) for k, v in params.items()},
        "params_note": "params values in µm (converted from m)",
        "bbox": [bbox.left, bbox.bottom, bbox.right, bbox.top],
        "bbox_nm": f"{bbox.width()}x{bbox.height()} nm",
        "shapes_by_layer": shapes_by_layer,
        "ports": raw_ports,
        "pcell_name": pcell_name,
        "bbox_offset": bbox_offset,
        "pins": pins,
        "implant_bounds": implant_bounds,
        "classification": classification,
    }
    if gate_info:
        entry["gate_info"] = gate_info

    result[dev_name] = entry

    pin_roles = {p: d['pin_role'] for p, d in pins.items()}
    print(f"  bbox: {bbox.left},{bbox.bottom} -> {bbox.right},{bbox.top}")
    print(f"  size: {bbox.width()/1000:.1f} x {bbox.height()/1000:.1f} um")
    print(f"  offset: ox={bbox_offset['ox_um']}, oy={bbox_offset['oy_um']} um")
    print(f"  pins: {pin_roles}")
    print(f"  implant: {list(implant_bounds.keys())}")
    if gate_info:
        print(f"  gate: ng={gate_info['ng']}, Xs={gate_info['finger_xs']}")
    print(f"  class: {classification['device_class']}, nwell={classification['has_nwell']}")

# Write output
output_path = os.path.join(os.path.dirname(__file__), "atk", "data", "device_lib.json")
with open(output_path, 'w') as f:
    json.dump(result, f, indent=2)
print(f"\nWrote {output_path}")
print(f"Devices: {len(result)}")
print("=== DONE ===")
