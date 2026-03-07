"""Phase 0 Step 3: Probe PCell geometry for device_lib.json.
Run: klayout -n sg13g2 -zz -r layout/probe_pcells_p0.py

Extracts bbox, shapes_by_layer, and port positions for all PTAT+VCO device variants.
Output: atk/data/device_lib.json
"""
import pya
import json
import os

layout = pya.Layout()
dbu = layout.dbu  # 0.001 µm = 1nm

# Device definitions: (name, pcell_type, params)
# These match the 15 device types used in l2_autoplace.py DEVICES dict (v4 design)
DEVICES = [
    # PMOS (from l2_autoplace.py lines 59-84)
    ("pmos_mirror", "pmos", {"w": 4e-6, "l": 2e-6,   "ng": 2, "m": 1}),
    ("pmos_vco",    "pmos", {"w": 4e-6, "l": 0.5e-6,  "ng": 1, "m": 1}),
    ("pmos_buf1",   "pmos", {"w": 4e-6, "l": 0.5e-6,  "ng": 1, "m": 1}),
    ("pmos_buf2",   "pmos", {"w": 8e-6, "l": 0.5e-6,  "ng": 2, "m": 1}),
    # NMOS (from l2_autoplace.py lines 86-114)
    ("nmos_vco",    "nmos", {"w": 0.5e-6, "l": 0.5e-6, "ng": 1, "m": 1}),
    ("nmos_bias",   "nmos", {"w": 1e-6,  "l": 2.5e-6, "ng": 1, "m": 1}),
    ("nmos_diode",  "nmos", {"w": 2e-6,  "l": 1e-6,   "ng": 1, "m": 1}),
    ("nmos_buf1",   "nmos", {"w": 2e-6,  "l": 0.5e-6, "ng": 1, "m": 1}),
    ("nmos_buf2",   "nmos", {"w": 4e-6,  "l": 0.5e-6, "ng": 2, "m": 1}),
    # HBT (from l2_autoplace.py lines 140-152)
    ("hbt_1x",  "npn13G2", {"Nx": 1}),
    ("hbt_8x",  "npn13G2", {"Nx": 8}),
    # Resistors (from l2_autoplace.py lines 116-138)
    ("rppd_iso",   "rppd", {"w": 2.5e-6, "l": 5e-6,    "b": 0}),
    ("rppd_ptat",  "rppd", {"w": 0.5e-6, "l": 13e-6,   "b": 11}),
    ("rppd_start", "rppd", {"w": 0.5e-6, "l": 14.4e-6, "b": 0}),
    ("rppd_out",   "rppd", {"w": 0.5e-6, "l": 5.5e-6,  "b": 5}),
]

# Key layers we want to extract (layer, datatype) -> human-readable key
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

def extract_shapes(cell, layer_idx, dbu):
    """Extract all polygon shapes from a cell's layer as lists of [x1,y1,x2,y2] in nm."""
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
    """Extract text labels from a layer."""
    texts = {}
    for shape in cell.shapes(layer_idx).each():
        if shape.is_text():
            name = shape.text_string
            x = shape.text_trans.disp.x
            y = shape.text_trans.disp.y
            texts[name] = [x, y]
    return texts


result = {}

for dev_name, pcell_type, params in DEVICES:
    print(f"Probing {dev_name} ({pcell_type}, {params})...")
    cell = layout.create_cell(pcell_type, "SG13_dev", params)
    bbox = cell.bbox()

    shapes_by_layer = {}
    # Scan all layers that have shapes
    for li in layout.layer_indices():
        info = layout.get_info(li)
        key = (info.layer, info.datatype)
        layer_name = LAYER_NAMES.get(key)
        if layer_name is None:
            # Auto-name unknown layers
            layer_name = f"L{info.layer}_{info.datatype}"

        shapes = extract_shapes(cell, li, dbu)
        if shapes:
            shapes_by_layer[layer_name] = shapes

    # Extract pin positions from text labels on all layers
    ports = {}
    for li in layout.layer_indices():
        info = layout.get_info(li)
        texts = extract_texts(cell, li)
        for tname, (tx, ty) in texts.items():
            # Skip non-pin texts
            if tname in ("SG13_dev", ""):
                continue
            layer_key = (info.layer, info.datatype)
            layer_name = LAYER_NAMES.get(layer_key, f"L{info.layer}_{info.datatype}")
            ports[tname] = {
                "layer": layer_name,
                "center": [tx, ty]
            }

    # Ensure all key layers have entries (empty list for missing)
    key_layers_for_type = {
        "pmos": ["M1_8_0", "NW_31_0", "pSD_14_0", "Activ_1_0", "GatPoly_5_0", "Cont_6_0"],
        "nmos": ["M1_8_0", "Activ_1_0", "GatPoly_5_0", "Cont_6_0"],
        "npn13G2": ["M1_8_0", "M2_10_0", "Via1_19_0", "Activ_1_0", "Cont_6_0", "EmWind_33_0", "pSD_14_0", "TRANS_26_0"],
        "rppd": ["M1_8_0", "GatPoly_5_0", "Cont_6_0", "PolyRes_128_0", "pSD_14_0", "SalBlock_28_0"],
    }
    for layer_name in key_layers_for_type.get(pcell_type, []):
        if layer_name not in shapes_by_layer:
            shapes_by_layer[layer_name] = []

    # Also declare NW/pSD empty for NMOS (explicit absence)
    if pcell_type == "nmos":
        for absent in ["NW_31_0", "pSD_14_0"]:
            if absent not in shapes_by_layer:
                shapes_by_layer[absent] = []

    result[dev_name] = {
        "pcell": pcell_type,
        "params": {k: v if not isinstance(v, float) else round(v * 1e6, 4) for k, v in params.items()},
        "params_note": "params values in µm (converted from m)",
        "bbox": [bbox.left, bbox.bottom, bbox.right, bbox.top],
        "bbox_nm": f"{bbox.width()}x{bbox.height()} nm",
        "shapes_by_layer": shapes_by_layer,
        "ports": ports,
    }

    print(f"  bbox: {bbox.left},{bbox.bottom} -> {bbox.right},{bbox.top} ({bbox.width()}x{bbox.height()} nm)")
    print(f"  layers: {sorted(shapes_by_layer.keys())}")
    print(f"  ports: {sorted(ports.keys())}")

# Write output
output_path = os.path.join(os.path.dirname(__file__), "atk", "data", "device_lib.json")
with open(output_path, 'w') as f:
    json.dump(result, f, indent=2)
print(f"\nWrote {output_path}")
print(f"Devices: {len(result)}")
print("=== DONE ===")
