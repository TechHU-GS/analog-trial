#!/usr/bin/env python3
"""Build a single VCO stage with compact analog layout.

Layout (top to bottom):
    VDD
    Mpb (pmos_cs8, 13x8um) — PMOS current source
    Mpu (pmos_vco, 1.2x5um) — PMOS inverter  } shared NWell
    ─── vcoN output node ───
    Mpd (nmos_vco, 1.2x6um) — NMOS inverter
    Mnb (nmos_bias8, 12x8um) — NMOS current source
    GND

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/build_vco_stage.py
"""

import klayout.db as pya
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, LAYOUT_DIR)

from atk.pdk import s5


def build_vco_stage():
    """Build one VCO stage with compact placement."""

    with open(os.path.join(LAYOUT_DIR, 'placement.json')) as f:
        placement = json.load(f)

    # Load BARE GDS to get PCell shapes
    src = pya.Layout()
    src.read(os.path.join(LAYOUT_DIR, 'output', 'soilz_bare.gds'))
    src_top = src.top_cell()

    # Original Stage 1 device positions
    orig = {
        'Mpb1': placement['instances']['Mpb1'],  # (92.0, 176.0)
        'Mpu1': placement['instances']['Mpu1'],  # (101.1, 171.5)
        'Mpd1': placement['instances']['Mpd1'],  # (101.4, 168.0)
        'Mnb1': placement['instances']['Mnb1'],  # (92.3, 164.0)
    }

    # Compact placement based on actual PCell geometry:
    #
    # All devices are ~15-17um wide (X), heights vary (Y).
    # Active Y extents (relative to placement origin):
    #   Mnb1: y+0.18 to y+9.81 (9.6um)
    #   Mpd1: ~5um height (nmos_vco, single finger)
    #   Mpu1: y+0.31 to y+5.31 (5.0um)
    #   Mpb1: y+0.31 to y+8.81 (8.5um)
    #
    # Spacing rules:
    #   NMOS↔NMOS (same substrate): ~1.0um gap
    #   NMOS↔PMOS (NW.b1 = 1.8um): ~2.0um gap
    #   PMOS↔PMOS (shared NWell, NW.b = 0.62um): ~1.0um gap
    #
    # All at x=0 (aligned for drain connections)

    mnb_y = 0.0       # Bottom: NMOS current source (active top ~9.8um)
    mpd_y = 11.0      # NMOS inverter (1.2um gap from Mnb top)
    mpu_y = 18.5      # PMOS inverter (NW.b1 gap: 18.5+0.13=18.63 vs mpd top ~16.3 → 2.3um gap)
    mpb_y = 24.5      # PMOS current source (shared NWell: 24.5-23.81=0.7um gap)

    # All same X — aligned for vertical signal flow
    mpb_x = 0.0
    mnb_x = 0.0
    mpu_x = 0.0
    mpd_x = 0.0

    new_pos = {
        'Mpb1': (mpb_x, mpb_y),
        'Mpu1': (mpu_x, mpu_y),
        'Mpd1': (mpd_x, mpd_y),
        'Mnb1': (mnb_x, mnb_y),
    }

    # Create output layout
    out = pya.Layout()
    out.dbu = 0.001
    cell = out.create_cell('vco_stage')

    # For each device: extract from BARE GDS at original position,
    # shift to new position
    for dev_name, (new_x, new_y) in new_pos.items():
        orig_info = orig[dev_name]
        ox = orig_info['x_um'] * 1000  # original position in nm
        oy = orig_info['y_um'] * 1000

        # Search region — tight to avoid picking up neighbor devices
        # Device widths ~15um, heights 5-10um
        dev_type = orig[dev_name]['type']
        if 'cs8' in dev_type or 'bias8' in dev_type:
            search = pya.Box(int(ox - 3000), int(oy - 1000),
                             int(ox + 16000), int(oy + 11000))
        else:  # vco (small single-finger)
            search = pya.Box(int(ox - 3000), int(oy - 1000),
                             int(ox + 16000), int(oy + 7000))

        # Copy shapes shifted to new position
        dx = int(new_x * 1000) - int(ox)
        dy = int(new_y * 1000) - int(oy)

        shapes_copied = 0
        for li in src.layer_indices():
            info = src.get_info(li)
            tli = out.layer(info.layer, info.datatype)

            region = pya.Region(src_top.begin_shapes_rec(li))
            clipped = region & pya.Region(search)

            for poly in clipped.each():
                shifted = poly.moved(dx, dy)
                cell.shapes(tli).insert(shifted)
                shapes_copied += 1

        print(f'  {dev_name}: ({orig_info["x_um"]:.1f},{orig_info["y_um"]:.1f}) → '
              f'({new_x:.1f},{new_y:.1f}) [{shapes_copied} shapes]')

    # Write output
    out_dir = os.path.join(LAYOUT_DIR, 'modular', 'output')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'vco_stage_compact.gds')
    out.write(out_path)

    # DRC check
    bb = cell.bbox()
    print(f'\n  Compact VCO stage: {bb.width()/1000:.1f} x {bb.height()/1000:.1f} um')
    print(f'  Written: {out_path}')

    li_m1 = out.find_layer(8, 0)
    if li_m1 is not None:
        region = pya.Region(cell.begin_shapes_rec(li_m1))
        m1b = region.space_check(180)
        m1a = region.width_check(160)
        print(f'  M1.b: {m1b.count()}, M1.a: {m1a.count()}')

    return out_path


if __name__ == '__main__':
    print('=== Building Compact VCO Stage ===')
    build_vco_stage()
    print('=== Done ===')
