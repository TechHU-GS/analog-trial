#!/usr/bin/env python3
"""Comprehensive module audit — check every module GDS for extra/missing shapes.

Checks:
  A. STRAY (extra shapes from neighbors):
     - Transistor modules: Active region count vs expected device count
     - Passive modules: should have 0 transistor-like Active+Poly overlap
     - Edge-risk: Active/Poly within 200nm of module bbox edge

  B. MISSING (search box cut off own shapes):
     - Contact count (every device needs contacts)
     - Resistors: Res marker (52,0) present and reasonable area
     - Caps: M5 marker (67,0) present and reasonable area
     - Device count vs MODULE_MAP expected

  C. INTEGRITY:
     - Floating Via1 (no M1 below or no M2 above)
     - Floating M2 (no Via1)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/audit_modules.py
"""

import klayout.db as pya
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# Layer numbers
LY = {
    'Active':  (1, 0),
    'GatPoly': (5, 0),
    'Contact': (6, 0),
    'M1':      (8, 0),
    'Via1':    (19, 0),
    'M2':      (10, 0),
    'Via2':    (29, 0),
    'M3':      (30, 0),
    'NWell':   (31, 0),
    'Res':     (52, 0),   # resistor marker
    'M5':      (67, 0),   # cap marker (CMIM uses TopMetal2=67,0)
    'ThickOx': (44, 0),
}

# Expected device count per transistor module (from MODULE_MAP in mini_lvs.py)
EXPECTED_DEVICES = {
    'bias_mn': 2,
    'chopper': 4,
    'dac_sw': 4,
    'sw': 6,
    'ota': 7,
    'comp': 11,
    'bias_cascode': 9,
    'hbridge': 8,
    'hbridge_drive': 4,
    'vco_buffer': 4,
    'ptat_core': 7,
}

# Passive modules — should have 0 transistor Active islands
PASSIVE_MODULES = {
    'rptat':  {'type': 'resistor', 'marker': 'Res'},
    'rout':   {'type': 'resistor', 'marker': 'Res'},
    'rin':    {'type': 'resistor', 'marker': 'Res'},
    'rdac':   {'type': 'resistor', 'marker': 'Res'},
    'c_fb':   {'type': 'cap',      'marker': 'M5'},
    'cbyp_n': {'type': 'cap',      'marker': 'M5'},
    'cbyp_p': {'type': 'cap',      'marker': 'M5'},
}

# Skip these (not individual modules for audit)
SKIP = {'digital', 'vco_5stage'}

# All 20 assembled modules
with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
    fp = json.load(f)
MODULES = [k for k in fp if k != 'tile']


def get_layer(layout, ln, dt):
    """Find layer index, return None if not present."""
    li = layout.find_layer(ln, dt)
    return li


def region_for(layout, cell, layer_name):
    """Get Region for a layer, empty if layer not present."""
    ln, dt = LY[layer_name]
    li = layout.find_layer(ln, dt)
    if li is None:
        return pya.Region()
    return pya.Region(cell.begin_shapes_rec(li))


def count_islands(region):
    """Count separate polygon islands after merge."""
    merged = region.merged()
    return merged.count()


def audit_one(name):
    """Audit a single module GDS. Returns dict of findings."""
    gds_path = os.path.join(OUT_DIR, f'{name}.gds')
    if not os.path.exists(gds_path):
        return {'status': 'MISSING_GDS'}

    ly = pya.Layout()
    ly.read(gds_path)
    cell = ly.top_cell()
    bb = cell.bbox()

    result = {
        'name': name,
        'bbox': f'{bb.width()/1000:.1f}x{bb.height()/1000:.1f}',
        'issues': [],
    }

    # Get key regions
    active = region_for(ly, cell, 'Active')
    poly = region_for(ly, cell, 'GatPoly')
    contact = region_for(ly, cell, 'Contact')
    m1 = region_for(ly, cell, 'M1')
    via1 = region_for(ly, cell, 'Via1')
    m2 = region_for(ly, cell, 'M2')
    nwell = region_for(ly, cell, 'NWell')
    res_marker = region_for(ly, cell, 'Res')
    m5_marker = region_for(ly, cell, 'M5')

    # Basic counts
    active_islands = count_islands(active)
    poly_islands = count_islands(poly)
    contact_count = contact.merged().count()
    via1_count = via1.merged().count()
    m2_count = count_islands(m2)

    result['active_islands'] = active_islands
    result['poly_islands'] = poly_islands
    result['contact_count'] = contact_count
    result['via1_count'] = via1_count
    result['m2_islands'] = m2_count

    # --- A. STRAY detection ---

    # Transistor-like structures: Active overlapping with Poly (= gate region)
    transistor_active = active & poly.sized(100)  # slight expansion to catch near-misses
    transistor_regions = count_islands(transistor_active)
    result['transistor_regions'] = transistor_regions

    if name in PASSIVE_MODULES:
        # Passive: should have 0 transistor-like structures
        if transistor_regions > 0:
            # Find locations
            locs = []
            for p in transistor_active.merged().each():
                b = p.bbox()
                locs.append(f'({b.left/1000:.1f},{b.bottom/1000:.1f})')
            result['issues'].append(
                f'STRAY: {transistor_regions} transistor Active+Poly at {", ".join(locs[:5])}'
            )
    elif name in EXPECTED_DEVICES:
        # Transistor module: check device count
        expected = EXPECTED_DEVICES[name]
        # Count actual transistor gates: poly regions that overlap with Active
        gates_on_active = poly & active.sized(50)
        gate_count = count_islands(gates_on_active)
        result['gate_count'] = gate_count

        if gate_count > expected:
            result['issues'].append(
                f'EXTRA: {gate_count} gates found, expected {expected} (possible stray)'
            )
        elif gate_count < expected:
            result['issues'].append(
                f'MISSING: only {gate_count} gates found, expected {expected}'
            )

    # Edge-risk: Active or Poly within 200nm of bbox edge
    edge_margin = 200  # nm
    inner_box = pya.Box(
        bb.left + edge_margin, bb.bottom + edge_margin,
        bb.right - edge_margin, bb.top - edge_margin
    )
    inner_region = pya.Region(inner_box)
    edge_band = pya.Region(bb) - inner_region

    active_at_edge = active & edge_band
    poly_at_edge = poly & edge_band
    edge_active = count_islands(active_at_edge)
    edge_poly = count_islands(poly_at_edge)
    result['edge_active'] = edge_active
    result['edge_poly'] = edge_poly

    if edge_active > 0 and name in PASSIVE_MODULES:
        locs = []
        for p in active_at_edge.merged().each():
            b = p.bbox()
            locs.append(f'({b.left/1000:.1f},{b.bottom/1000:.1f})')
        result['issues'].append(
            f'EDGE_RISK: {edge_active} Active within 200nm of edge at {", ".join(locs[:5])}'
        )

    # --- B. MISSING detection ---

    if name in PASSIVE_MODULES:
        info = PASSIVE_MODULES[name]
        if info['type'] == 'resistor':
            res_area = res_marker.merged().area()
            result['res_marker_area_um2'] = res_area / 1e6
            if res_area == 0:
                result['issues'].append('MISSING: no Res marker (52,0)')
        elif info['type'] == 'cap':
            m5_area = m5_marker.merged().area()
            result['cap_marker_area_um2'] = m5_area / 1e6
            if m5_area == 0:
                result['issues'].append('MISSING: no M5/cap marker (67,0)')

        # Contacts for passives
        if contact_count == 0:
            result['issues'].append('MISSING: 0 Contacts (no terminals)')

    # --- C. INTEGRITY ---

    # Floating Via1: no M1 below
    if via1_count > 0:
        via1_no_m1 = via1 - m1.sized(0)
        floating_via1 = count_islands(via1_no_m1)
        if floating_via1 > 0:
            result['issues'].append(f'INTEGRITY: {floating_via1} Via1 without M1 below')

    # Floating Via1: no M2 above
    if via1_count > 0:
        via1_no_m2 = via1 - m2.sized(0)
        orphan_via1 = count_islands(via1_no_m2)
        if orphan_via1 > 0:
            result['issues'].append(f'INTEGRITY: {orphan_via1} Via1 without M2 above')

    # Floating M2: no Via1
    if m2_count > 0:
        m2_touching_via1 = m2 & via1.sized(50)
        m2_no_via1 = m2 - m2_touching_via1
        floating_m2 = count_islands(m2_no_via1)
        if floating_m2 > 0:
            result['issues'].append(f'INTEGRITY: {floating_m2} M2 islands without Via1')

    # NWell check for PMOS-containing modules
    if nwell.merged().area() > 0:
        result['has_nwell'] = True
        nwell_islands = count_islands(nwell)
        if nwell_islands > 1:
            result['issues'].append(f'INTEGRITY: {nwell_islands} separate NWell (should be 1)')

    # Status
    if not result['issues']:
        result['status'] = 'PASS'
    elif any('STRAY' in i or 'EXTRA' in i or 'MISSING' in i for i in result['issues']):
        result['status'] = 'FAIL'
    else:
        result['status'] = 'WARN'

    return result


def main():
    print('=' * 80)
    print('MODULE AUDIT — Comprehensive stray/missing shape check')
    print('=' * 80)

    results = []
    for name in sorted(MODULES):
        if name in SKIP:
            print(f'  {name:18s} — SKIP (complex/external)')
            continue
        r = audit_one(name)
        results.append(r)

        status = r.get('status', '?')
        icon = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}.get(status, '?')

        if name in EXPECTED_DEVICES:
            gate_info = f"gates={r.get('gate_count', '?')}/{EXPECTED_DEVICES[name]}"
        elif name in PASSIVE_MODULES:
            info = PASSIVE_MODULES[name]
            if info['type'] == 'resistor':
                gate_info = f"res={r.get('res_marker_area_um2', 0):.0f}um²"
            else:
                gate_info = f"cap={r.get('cap_marker_area_um2', 0):.0f}um²"
        else:
            gate_info = ''

        print(f'  {icon} {name:18s} {r["bbox"]:>12s}  Active={r.get("active_islands",0):2d}  '
              f'Poly={r.get("poly_islands",0):2d}  Cnt={r.get("contact_count",0):3d}  '
              f'V1={r.get("via1_count",0):2d}  {gate_info}')

        for issue in r.get('issues', []):
            print(f'     → {issue}')

    # Summary
    print('\n' + '=' * 80)
    fail_count = sum(1 for r in results if r.get('status') == 'FAIL')
    warn_count = sum(1 for r in results if r.get('status') == 'WARN')
    pass_count = sum(1 for r in results if r.get('status') == 'PASS')
    print(f'SUMMARY: {pass_count} PASS, {warn_count} WARN, {fail_count} FAIL '
          f'(out of {len(results)} modules)')

    if fail_count > 0:
        print('\nFAILED modules:')
        for r in results:
            if r.get('status') == 'FAIL':
                print(f'  ❌ {r["name"]}:')
                for issue in r['issues']:
                    print(f'     {issue}')

    print('\n' + '=' * 80)


if __name__ == '__main__':
    main()
