#!/usr/bin/env python3
"""Diagnose V1.b (Via1 spacing) violation. Find the two Via1 shapes and
determine if they come from routing (fixable) or PCell (unfixable)."""
import klayout.db as kdb
import xml.etree.ElementTree as ET

GDS = 'output/ptat_vco.gds'
LYRDB = '/tmp/drc_verify_now/ptat_vco_ptat_vco_full.lyrdb'
VIA1 = (19, 0)
V1_MIN_S = 220  # nm

layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()
li_via1 = layout.layer(*VIA1)

# Parse V1.b violations
tree = ET.parse(LYRDB)
root = tree.getroot()
viols = []
for item in root.find('items').findall('item'):
    cat = item.find('category').text.strip().strip("'\"")
    if cat != 'V1.b':
        continue
    values = item.find('values')
    if values is None:
        continue
    for v in values.findall('value'):
        if v.text:
            viols.append(v.text.strip())
            break

print(f"V1.b violations: {len(viols)}")
print("=" * 70)

for vi, coords in enumerate(viols):
    parts = coords.replace('edge-pair: ', '').replace('(', '').replace(')', '')
    sep = '|' if '|' in parts else '/'
    sides = parts.split(sep)

    edges = []
    for side in sides:
        pts = side.strip().split(';')
        edge_pts = []
        for pt in pts:
            xy = pt.split(',')
            edge_pts.append((int(float(xy[0]) * 1000), int(float(xy[1]) * 1000)))
        edges.append(edge_pts)

    e1, e2 = edges[0], edges[1]
    e1_mx = (e1[0][0] + e1[1][0]) // 2
    e1_my = (e1[0][1] + e1[1][1]) // 2
    e2_mx = (e2[0][0] + e2[1][0]) // 2
    e2_my = (e2[0][1] + e2[1][1]) // 2

    cx = (e1_mx + e2_mx) // 2
    cy = (e1_my + e2_my) // 2

    # Find Via1 shapes near violation
    search = kdb.Box(cx - 2000, cy - 2000, cx + 2000, cy + 2000)
    print(f"\nV{vi+1}: center=({cx/1e3:.3f}, {cy/1e3:.3f})µm")
    print(f"  E1: ({e1[0][0]/1e3:.3f},{e1[0][1]/1e3:.3f})-({e1[1][0]/1e3:.3f},{e1[1][1]/1e3:.3f})")
    print(f"  E2: ({e2[0][0]/1e3:.3f},{e2[0][1]/1e3:.3f})-({e2[1][0]/1e3:.3f},{e2[1][1]/1e3:.3f})")

    via1_shapes = []
    for si in top.begin_shapes_rec_overlapping(li_via1, search):
        cell_name = layout.cell(si.cell_index()).name
        box = si.shape().bbox().transformed(si.trans())
        via1_shapes.append((box, cell_name))
        source = 'ROUTING' if cell_name == top.name else f'DEVICE({cell_name})'
        print(f"  Via1: {source:30s} [{box.left/1e3:.3f},{box.bottom/1e3:.3f}]-"
              f"[{box.right/1e3:.3f},{box.top/1e3:.3f}] ({box.width()}x{box.height()}nm)")

    # Calculate actual spacing between Via1 shapes
    if len(via1_shapes) >= 2:
        # Find closest pair
        min_gap = 999999
        pair = None
        for i in range(len(via1_shapes)):
            for j in range(i+1, len(via1_shapes)):
                b1, c1 = via1_shapes[i]
                b2, c2 = via1_shapes[j]
                # Edge-to-edge spacing
                dx = max(0, max(b1.left - b2.right, b2.left - b1.right))
                dy = max(0, max(b1.bottom - b2.top, b2.bottom - b1.top))
                if dx == 0 and dy == 0:
                    gap = 0  # overlapping
                elif dx == 0:
                    gap = dy
                elif dy == 0:
                    gap = dx
                else:
                    gap = (dx**2 + dy**2)**0.5  # diagonal
                if gap < min_gap:
                    min_gap = gap
                    pair = (via1_shapes[i], via1_shapes[j], dx, dy)

        if pair:
            (b1, c1), (b2, c2), dx, dy = pair
            cx1 = (b1.left + b1.right) // 2
            cy1 = (b1.bottom + b1.top) // 2
            cx2 = (b2.left + b2.right) // 2
            cy2 = (b2.bottom + b2.top) // 2
            cc_dist = ((cx1-cx2)**2 + (cy1-cy2)**2)**0.5
            src1 = 'ROUTING' if c1 == top.name else f'DEVICE({c1})'
            src2 = 'ROUTING' if c2 == top.name else f'DEVICE({c2})'

            print(f"\n  Closest pair:")
            print(f"    V1: {src1} center=({cx1/1e3:.3f},{cy1/1e3:.3f})")
            print(f"    V2: {src2} center=({cx2/1e3:.3f},{cy2/1e3:.3f})")
            print(f"    Edge spacing: dx={dx}nm, dy={dy}nm")
            print(f"    Edge-to-edge (diagonal): {min_gap:.1f}nm (need {V1_MIN_S}nm)")
            print(f"    Center-to-center: {cc_dist:.1f}nm")
            print(f"    Deficit: {V1_MIN_S - min_gap:.1f}nm")

            # Check: is this a diagonal placement?
            if dx > 0 and dy > 0:
                print(f"    >> DIAGONAL via placement — solver C-C check misses edge spacing")
