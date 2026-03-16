"""GDS probe: trace the full Via chain at a gate pin AP.

Reads the assembled GDS and reports actual shapes on each layer
near the AP, with overlap checks between adjacent layers.

Usage (run via KLayout):
    klayout -n sg13g2 -zz -r probe_gds_chain.py
"""
import klayout.db as db

GDS = 'output/ptat_vco.gds'
NET = 't1Q_mb'

# Probe targets: (pin_name, ap_x_nm, ap_y_nm)
PROBES = [
    ('T1Q_m7.G', 60350, 202000),
    ('T1Q_m6.G', 64900, 206630),
    ('LABEL_M1', 59800, 210150),      # label position
    ('BRIDGE_H', 59375, 204200),      # M4 bridge H midpoint
    ('BRIDGE_V', 60250, 205425),      # M4 bridge V midpoint
]

# GDS layer numbers
LAYERS = {
    'M1':    (8, 0),
    'Via1':  (19, 0),
    'M2':    (10, 0),
    'Via2':  (29, 0),
    'M3':    (30, 0),
    'Via3':  (49, 0),
    'M4':    (50, 0),
    'M1_lbl': (8, 25),
    'M2_lbl': (10, 25),
    'M3_lbl': (30, 25),
}

SEARCH_RADIUS = 2000  # nm — search box half-size


def collect_shapes(top, layout, layer_pair, cx, cy, radius):
    """Collect all shapes within radius of (cx, cy) on given layer."""
    li = layout.layer(*layer_pair)
    results = []
    search = db.Box(cx - radius, cy - radius, cx + radius, cy + radius)
    for sh in top.shapes(li).each_overlapping(search):
        bb = sh.bbox()
        results.append((bb.left, bb.bottom, bb.right, bb.top))
    return results


def rects_overlap(a, b):
    """Check if two (x1,y1,x2,y2) rects overlap."""
    return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]


def collect_labels(top, layout, layer_pair, cx, cy, radius):
    """Collect text labels near position."""
    li = layout.layer(*layer_pair)
    results = []
    search = db.Box(cx - radius, cy - radius, cx + radius, cy + radius)
    for sh in top.shapes(li).each_overlapping(search):
        if sh.is_text():
            txt = sh.text
            tx = txt.x
            ty = txt.y
            results.append((txt.string, tx, ty))
    return results


# ── Main ────────────────────────────────────────────────────────────
layout = db.Layout()
layout.read(GDS)
top = layout.top_cell()

print('=' * 70)
print(f'GDS CHAIN PROBE: {GDS}')
print(f'Net: {NET}')
print('=' * 70)

for probe_name, cx, cy in PROBES:
    print(f'\n{"─" * 70}')
    print(f'PROBE: {probe_name} at ({cx}, {cy})')
    print(f'{"─" * 70}')

    # Collect shapes on each layer
    layer_shapes = {}
    for lname, lpair in LAYERS.items():
        if lname.endswith('_lbl'):
            labels = collect_labels(top, layout, lpair, cx, cy, SEARCH_RADIUS)
            if labels:
                print(f'  {lname}: {len(labels)} labels')
                for txt, tx, ty in labels:
                    d = abs(tx - cx) + abs(ty - cy)
                    print(f'    "{txt}" at ({tx},{ty}) dist={d}nm')
            continue
        shapes = collect_shapes(top, layout, lpair, cx, cy, SEARCH_RADIUS)
        layer_shapes[lname] = shapes
        if shapes:
            print(f'  {lname}: {len(shapes)} shapes')
            for s in sorted(shapes, key=lambda r: abs((r[0]+r[2])//2-cx)+abs((r[1]+r[3])//2-cy)):
                w = s[2] - s[0]
                h = s[3] - s[1]
                scx = (s[0] + s[2]) // 2
                scy = (s[1] + s[3]) // 2
                d = abs(scx - cx) + abs(scy - cy)
                print(f'    ({s[0]:>6},{s[1]:>6})-({s[2]:>6},{s[3]:>6})'
                      f'  {w}x{h}nm  center=({scx},{scy}) dist={d}nm')
        else:
            print(f'  {lname}: NONE')

    # ── Overlap chain check ─────────────────────────────────────────
    chain = [
        ('M1', 'Via1'),
        ('Via1', 'M2'),
        ('M2', 'Via2'),
        ('Via2', 'M3'),
        ('M3', 'Via3'),
        ('Via3', 'M4'),
    ]

    print(f'\n  Chain overlap check:')
    for lyr_a, lyr_b in chain:
        shapes_a = layer_shapes.get(lyr_a, [])
        shapes_b = layer_shapes.get(lyr_b, [])
        if not shapes_a or not shapes_b:
            status = 'SKIP (no shapes)'
        else:
            # Check if ANY shape on lyr_a overlaps ANY shape on lyr_b
            found = False
            for sa in shapes_a:
                for sb in shapes_b:
                    if rects_overlap(sa, sb):
                        found = True
                        break
                if found:
                    break
            status = 'OK' if found else '*** BREAK ***'
        print(f'    {lyr_a:>4} ↔ {lyr_b:<4}: {status}')

print('\n' + '=' * 70)
print('DONE')
