#!/usr/bin/env python3
"""Generate tie geometry for Magic layout from ties.json.

Reads ties.json (pre-computed tie rectangles in nm) and appends
ntap/ptap tie geometry to soilz.mag before the << end >> marker.

Magic paint types:
  ntap tie: ntapc (contact) + ntap (diffusion) + nwell + metal1
  ptap tie: ptapc (contact) + ptap (diffusion) + metal1

Also appends nwell_extensions from ties.json.

Usage:
    python3 -m atk.gen_magic_ties /tmp/magic_soilz/soilz.mag
"""

import json
import os
import sys

SCALE = 10  # 1 Magic unit = 10nm


def nm(val):
    return int(round(val / SCALE))


def generate_ties(mag_path, ties_path=None):
    """Append tie geometry to soilz.mag."""
    if ties_path is None:
        layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ties_path = os.path.join(layout_dir, 'output', 'ties.json')

    with open(ties_path) as f:
        ties_data = json.load(f)

    ties = ties_data.get('ties', [])
    nwell_exts = ties_data.get('nwell_extensions', [])

    # Read existing soilz.mag
    with open(mag_path) as f:
        content = f.read()

    # Remove << end >> to append before it
    if '<< end >>' in content:
        content = content.replace('<< end >>', '')

    lines = [content.rstrip()]

    # GDS layer key → Magic paint type mapping
    # For ntap ties (net=vdd):
    #   Activ_1_0 → ntap (bare diffusion in NWell)
    #   Cont_6_0 → ntapc (contact on ntap)
    #   NW_31_0 → nwell
    #   M1_8_0 → metal1
    # For ptap ties (net=gnd):
    #   Activ_1_0 → ptap (bare diffusion in pwell)
    #   Cont_6_0 → ptapc (contact on ptap)
    #   pSD_14_0 → (not needed, auto-derived)
    #   M1_8_0 → metal1

    NTAP_LAYER_MAP = {
        'Activ_1_0': 'ntap',
        'Cont_6_0': 'ntapc',
        'NW_31_0': 'nwell',
        'M1_8_0': 'metal1',
    }

    PTAP_LAYER_MAP = {
        'Activ_1_0': 'ptap',
        'Cont_6_0': 'ptapc',
        'pSD_14_0': None,  # skip — auto-derived by Magic from ptap
        'M1_8_0': 'metal1',
    }

    current_layer = None
    tie_count = 0

    def emit_layer(layer_name):
        nonlocal current_layer
        if layer_name != current_layer:
            lines.append(f'<< {layer_name} >>')
            current_layer = layer_name

    # Group by Magic layer for efficient output
    layer_rects = {}  # magic_layer → list of (x1,y1,x2,y2)

    for tie in ties:
        tie_type = tie.get('type', '')
        layer_map = NTAP_LAYER_MAP if tie_type == 'ntap' else PTAP_LAYER_MAP
        tie_layers = tie.get('layers', {})

        for gds_key, rects in tie_layers.items():
            magic_layer = layer_map.get(gds_key)
            if not magic_layer:
                continue
            if magic_layer not in layer_rects:
                layer_rects[magic_layer] = []
            for rect in rects:
                x1, y1, x2, y2 = rect
                layer_rects[magic_layer].append((nm(x1), nm(y1), nm(x2), nm(y2)))

        tie_count += 1

    # NWell extensions
    nwell_count = 0
    if 'nwell' not in layer_rects:
        layer_rects['nwell'] = []
    for ext in nwell_exts:
        if isinstance(ext, list) and len(ext) == 4:
            x1, y1, x2, y2 = ext
            layer_rects['nwell'].append((nm(x1), nm(y1), nm(x2), nm(y2)))
            nwell_count += 1

    # Emit grouped by layer
    # Order: paint contacts last (they override bare diffusion)
    layer_order = ['nwell', 'ntap', 'ptap', 'ntapc', 'ptapc', 'metal1']
    for layer in layer_order:
        rects = layer_rects.get(layer, [])
        if not rects:
            continue
        emit_layer(layer)
        for x1, y1, x2, y2 in rects:
            lines.append(f'rect {x1} {y1} {x2} {y2}')

    lines.append('<< end >>')

    with open(mag_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    total_rects = sum(len(r) for r in layer_rects.values())
    print(f'  Ties: {tie_count} ({sum(1 for t in ties if t["type"]=="ntap")} ntap, '
          f'{sum(1 for t in ties if t["type"]=="ptap")} ptap)')
    print(f'  NWell extensions: {nwell_count}')
    print(f'  Total rectangles added: {total_rects}')


if __name__ == '__main__':
    mag_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/magic_soilz/soilz.mag'
    generate_ties(mag_path)
