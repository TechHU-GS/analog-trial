#!/usr/bin/env python3
"""Extract all 7 passive devices from soilz_bare.gds.

Each passive is extracted as a separate GDS file.
No routing needed — just two terminals (PLUS/MINUS).

Resistors use connectivity-based filtering:
  1. Extract with generous search box (intentionally captures neighbors)
  2. Seed from Res marker (52,0)
  3. Grow through: Res → GatPoly → Contact → M1
  4. Keep only shapes connected to device; delete stray

Caps (CMIM) are upper-metal only — no neighbor contamination issue.

Devices:
    Rptat:  rhigh_ptat    9.1×135.5um  (PTAT resistor)
    Rout:   rhigh_rout    1.6×101.3um  (output resistor)
    Rin:    rhigh_200k   22.2×2.3um   (input resistor)
    Rdac:   rhigh_200k   22.2×2.3um   (DAC resistor)
    C_fb:   cap_cmim_1p  27.2×27.2um  (feedback cap)
    Cbyp_n: cap_cmim     6.2×6.2um    (bypass cap)
    Cbyp_p: cap_cmim     6.2×6.2um    (bypass cap)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_passives.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Generous search boxes — intentionally wide, connectivity filter cleans up stray
# (name, search_x1, search_y1, search_x2, search_y2, type)
PASSIVES = [
    # Resistors: generous boxes + connectivity filter
    ('rptat',  11500, 11750, 35000, 153500, 'resistor'),
    ('rout',    7700, 11750, 21500, 128500, 'resistor'),
    ('rin',    15500, 49500, 35000, 74500,  'resistor'),
    ('rdac',   47000, 55750, 62000, 78500,  'resistor'),
    # Caps: no filter needed (upper-metal only, verified clean)
    ('c_fb',   81500, 59500, 111500, 87700, 'cap'),
    ('cbyp_n', 71500, 145500, 78700, 152700, 'cap'),
    ('cbyp_p', 59500, 138500, 66700, 145700, 'cap'),
]

# Layers
LY_RES     = (52, 0)   # Res marker — seed for resistors
LY_POLY    = (5, 0)    # GatPoly — resistor body
LY_CONT    = (6, 0)    # Contact — terminal connections
LY_M1      = (8, 0)    # Metal1 — terminal pads
LY_M1_PIN  = (8, 2)    # Metal1 pin

# Overlay layers: keep if they overlap the device body region
OVERLAY_LAYERS = [
    (7, 0),    # SalBlock
    (14, 0),   # Nbulay
    (28, 0),   # TRANS
    (111, 0),  # EXTBlock
    (128, 0),  # RES_label
    (52, 0),   # Res (seed itself)
    (51, 0),   # Vmim
    (5, 2),    # GatPoly.pin
]


def connectivity_filter(cell, layout):
    """Remove stray shapes using Res-marker-seeded connectivity.

    Chain: Res(52,0) → GatPoly(5,0) → Contact(6,0) → M1(8,0)
    Overlay layers kept if they overlap device body.
    Everything else deleted.
    """
    def get_region(ln, dt):
        li = layout.find_layer(ln, dt)
        if li is None:
            return pya.Region()
        return pya.Region(cell.begin_shapes_rec(li))

    # Step 1: Seed from Res marker
    seed = get_region(*LY_RES).merged()
    if seed.count() == 0:
        print('    WARNING: no Res marker, skipping filter')
        return 0

    # Step 2: Device GatPoly = poly touching/overlapping Res marker
    # Use 150nm expansion to catch edge-touching terminal poly pads
    poly = get_region(*LY_POLY)
    device_poly = poly & seed.sized(150)

    # Step 3: Device Contacts = contacts on device poly
    contact = get_region(*LY_CONT)
    device_contacts = contact & device_poly.sized(150)

    # Step 4: Device M1 = M1 touching device contacts
    m1 = get_region(*LY_M1)
    device_m1 = m1 & device_contacts.sized(150)

    m1pin = get_region(*LY_M1_PIN)
    device_m1pin = m1pin & device_contacts.sized(150)

    # Build keep zone: union of all device shapes, expanded slightly
    device_shapes = seed + device_poly + device_contacts + device_m1 + device_m1pin
    device_shapes = device_shapes.merged()

    # For overlay layers: keep if overlapping seed body (not just terminal)
    body_zone = seed.sized(300)

    # Step 5: Filter each layer
    removed_total = 0
    for li in layout.layer_indices():
        info = layout.get_info(li)
        ln_key = (info.layer, info.datatype)

        shapes = pya.Region(cell.begin_shapes_rec(li))
        if shapes.count() == 0:
            continue

        # Determine keep zone based on layer type
        if ln_key in [LY_RES, LY_POLY, LY_CONT, LY_M1, LY_M1_PIN]:
            # Core device layers: keep if in device_shapes
            keep = shapes & device_shapes.sized(50)
        elif ln_key in [(ln, dt) for ln, dt in OVERLAY_LAYERS]:
            # Overlay layers: keep if overlapping device body
            keep = shapes & body_zone
        else:
            # Unknown layers: keep if overlapping device footprint
            keep = shapes & device_shapes.sized(300)

        removed = shapes - keep
        n_removed = removed.count()

        if n_removed > 0:
            removed_total += n_removed
            cell.clear(li)
            for p in keep.each():
                cell.shapes(li).insert(p)

    return removed_total


def build():
    print('=== Extracting passive devices ===')

    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    for name, sx1, sy1, sx2, sy2, dev_type in PASSIVES:
        out = pya.Layout()
        out.dbu = 0.001
        cell = out.create_cell(name)

        search = pya.Box(sx1, sy1, sx2, sy2)

        # Extract all shapes within search box
        count = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)
            region = pya.Region(src_top.begin_shapes_rec(li))
            for poly in (region & pya.Region(search)).each():
                cell.shapes(tli).insert(poly.moved(-sx1, -sy1))
                count += 1

        # Apply connectivity filter for resistors
        if dev_type == 'resistor':
            removed = connectivity_filter(cell, out)
            filter_str = f', filtered {removed} stray'
        else:
            removed = 0
            filter_str = ''

        out_path = os.path.join(OUT_DIR, f'{name}.gds')
        out.write(out_path)

        bb = cell.bbox()
        print(f'  {name:8s}: {bb.width()/1000:.1f}x{bb.height()/1000:.1f}um, '
              f'{count} extracted, {count - removed} kept{filter_str}')

    print('\n=== Done ===')


if __name__ == '__main__':
    build()
