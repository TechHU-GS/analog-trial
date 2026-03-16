#!/usr/bin/env python3
"""Diagnose pSD coverage overlapping ntap ties.

Flattens the GDS and checks which ntap tie Activ regions overlap with
PCell pSD shapes. Reports affected ties and suggests placement fixes.
"""
import json
import gdstk
import sys

def main():
    gds_path = "output/ptat_vco_beol_clean.gds"
    ties_path = "output/ties.json"

    lib = gdstk.read_gds(gds_path)
    top = [c for c in lib.cells if c.name == 'ptat_vco'][0]

    # Collect PCell pSD shapes in global coords (from references only)
    pcell_psds = []
    for ref in top.references:
        ox, oy = ref.origin[0] * 1000, ref.origin[1] * 1000  # nm
        pcell = None
        for c in lib.cells:
            if c.name == ref.cell_name:
                pcell = c
                break
        if not pcell:
            continue
        for p in pcell.polygons:
            if p.layer == 14 and p.datatype == 0:
                bb = p.bounding_box()
                gx1 = ox + bb[0][0] * 1000
                gy1 = oy + bb[0][1] * 1000
                gx2 = ox + bb[1][0] * 1000
                gy2 = oy + bb[1][1] * 1000
                pcell_psds.append({
                    'cell': ref.cell_name,
                    'origin': (ox, oy),
                    'rect': (gx1, gy1, gx2, gy2),
                })

    print(f"PCell pSD shapes: {len(pcell_psds)}")
    for ps in pcell_psds:
        r = ps['rect']
        area = (r[2]-r[0]) * (r[3]-r[1])
        if area > 1e6:  # > 1µm² — significant
            print(f"  {ps['cell']} at ({ps['origin'][0]:.0f},{ps['origin'][1]:.0f}): "
                  f"pSD ({r[0]:.0f},{r[1]:.0f})-({r[2]:.0f},{r[3]:.0f}) area={area/1e6:.1f}µm²")

    # Load ties
    with open(ties_path) as f:
        ties = json.load(f)

    # Check each ntap tie for pSD overlap
    print(f"\n--- ntap ties overlapping PCell pSD ---")
    contaminated = []
    for t in ties['ties']:
        if t['type'] != 'ntap':
            continue
        act = t['layers']['Activ_1_0'][0]  # [x1, y1, x2, y2]
        for ps in pcell_psds:
            r = ps['rect']
            # Check overlap
            if act[0] < r[2] and act[2] > r[0] and act[1] < r[3] and act[3] > r[1]:
                contaminated.append({
                    'tie_id': t['id'],
                    'activ': act,
                    'pcell': ps['cell'],
                    'pcell_origin': ps['origin'],
                    'psd': r,
                })
                print(f"  {t['id']}: activ ({act[0]},{act[1]})-({act[2]},{act[3]})")
                print(f"    overlap with {ps['cell']} at ({ps['origin'][0]:.0f},{ps['origin'][1]:.0f})")
                print(f"    pSD: ({r[0]:.0f},{r[1]:.0f})-({r[2]:.0f},{r[3]:.0f})")
                # How far to shift X to escape?
                escape_x_right = r[2] - act[0] + 200  # +200nm margin
                escape_x_left = act[2] - r[0] + 200
                print(f"    escape: shift X right by {escape_x_right:.0f}nm or left by {escape_x_left:.0f}nm")

    if not contaminated:
        print("  None! All ntap ties are outside PCell pSD.")
    else:
        print(f"\n  Total: {len(contaminated)} ntap ties contaminated by PCell pSD")


if __name__ == '__main__':
    main()
