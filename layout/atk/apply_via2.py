#!/usr/bin/env python3
"""Apply Via2 solver results to GDS.

Reads via2_placements.json and patches the GDS with:
- Via2 cuts at solver positions
- M3 pads (for M4 anchors: Via3 + M3 pad)
- M2 bridges from AP to Via2 position

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.apply_via2
"""

import json
import klayout.db as db
from .pdk import (
    VIA2, VIA3, METAL2, METAL3, METAL4,
    VIA2_SZ, VIA2_PAD_M3, VIA3_SZ, VIA3_PAD,
    M2_MIN_W, M3_MIN_W,
)


def apply(gds_path='output/ptat_vco.gds',
          placements_path='output/via2_placements.json',
          output_path='output/ptat_vco_via2_patched.gds'):
    """Patch GDS with solver Via2 placements."""

    with open(placements_path) as f:
        data = json.load(f)

    placements = data['via2_placements']
    if not placements:
        print('  No Via2 placements to apply.')
        return

    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    # Layer indices
    li_v2 = layout.layer(*VIA2)
    li_v3 = layout.layer(*VIA3)
    li_m2 = layout.layer(*METAL2)
    li_m3 = layout.layer(*METAL3)
    li_m4 = layout.layer(*METAL4)

    v2_hs = VIA2_SZ // 2       # 95nm
    v3_hs = VIA3_SZ // 2       # 95nm (Via3 cut)
    m3_pad_hs = VIA2_PAD_M3 // 2  # 190nm (Via2 M3 pad)
    v3_m3_hs = VIA3_PAD // 2   # 190nm (Via3 M3 pad)
    m2_hw = M2_MIN_W // 2      # 100nm (M2 bridge half-width)
    m2_endcap = 145             # V2.c1 endcap on M2

    added_via2 = 0
    added_via3 = 0

    for p in placements:
        vx = p['via2_x']
        vy = p['via2_y']
        ax = p['anchor_x']
        ay = p['anchor_y']
        alyr = p['anchor_layer']
        px = p['ap_x']
        py = p['ap_y']

        # 1. Via2 cut
        top.shapes(li_v2).insert(db.Box(
            vx - v2_hs, vy - v2_hs, vx + v2_hs, vy + v2_hs))

        # 2. M3 pad at Via2 position
        top.shapes(li_m3).insert(db.Box(
            vx - m3_pad_hs, vy - m3_pad_hs,
            vx + m3_pad_hs, vy + m3_pad_hs))

        # 3. If anchor is on M4 (layer 3) or Via3 (-3), add Via3 + M3 bridge to anchor
        if alyr in (3, -3):
            # Via3 at anchor position (connecting M3→M4)
            top.shapes(li_v3).insert(db.Box(
                ax - v3_hs, ay - v3_hs, ax + v3_hs, ay + v3_hs))
            # M3 pad at anchor for Via3
            top.shapes(li_m3).insert(db.Box(
                ax - v3_m3_hs, ay - v3_m3_hs,
                ax + v3_m3_hs, ay + v3_m3_hs))
            # M3 bridge between Via2 position and anchor
            if vx != ax or vy != ay:
                bx1 = min(vx, ax) - M3_MIN_W // 2
                by1 = min(vy, ay) - M3_MIN_W // 2
                bx2 = max(vx, ax) + M3_MIN_W // 2
                by2 = max(vy, ay) + M3_MIN_W // 2
                top.shapes(li_m3).insert(db.Box(bx1, by1, bx2, by2))
            added_via3 += 1

        # 4. M2 bridge from AP to Via2
        bx1 = min(vx, px) - m2_hw
        by1 = min(vy, py) - m2_hw
        bx2 = max(vx, px) + m2_hw
        by2 = max(vy, py) + m2_hw
        # Endcap extension
        dx = vx - px
        dy = vy - py
        if abs(dx) >= abs(dy):
            if dx >= 0:
                bx2 = max(bx2, vx + m2_endcap)
            else:
                bx1 = min(bx1, vx - m2_endcap)
        else:
            if dy >= 0:
                by2 = max(by2, vy + m2_endcap)
            else:
                by1 = min(by1, vy - m2_endcap)

        top.shapes(li_m2).insert(db.Box(bx1, by1, bx2, by2))
        added_via2 += 1

    layout.write(output_path)
    print(f'  Applied {added_via2} Via2 + {added_via3} Via3 to {output_path}')
    return output_path


if __name__ == '__main__':
    out = apply()
    if out:
        print(f'  Run LVS on: {out}')
