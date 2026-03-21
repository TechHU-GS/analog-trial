#!/usr/bin/env python3
"""Module Quality Verification Script — SoilZ v1

Runs 9 checks on every module GDS:
  1. Quick DRC: M1.b (space), M1.a (width), M2.b (space), M2.a (width)
  2. CI DRC: IHP ihp-sg13g2.drc (official precheck standard)
  3. Floating M1: M1 regions with no Contact AND no Via1
  4. Floating M2: M2 regions with no Via1
  5. Via1 coverage (down): every Via1 must have M1 underneath
  6. Via1 coverage (up): every Via1 must have M2 above
  7. Contact coverage: every Contact must have M1 above
  8. Strip↔routing: M1 regions with Via1 but no Contact (potential disconnect)
  9. Gate contact: every gate contact (Cont on GatPoly) must connect to routing

Lessons learned (Session 9):
  - find_layer returns 0 for first layer → use `is not None`, never `if layer_idx`
  - Via1 can be placed without M1 pad underneath → must verify overlap
  - M1 routing bars above strips may not touch strip top → verify strip↔bar connection
  - Gate contact M1 pad + routing bar at same Y can merge with wrong-net shapes
  - ntap M1 too close to gate contact M1 → can short VDD to signal
  - PCell shapes at extraction boundary can be clipped → widen search margins

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/verify_modules.py                    # check all
    python3 modular/verify_modules.py chopper dac_sw     # check specific
"""

import klayout.db as pya
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

CI_DRC = os.path.expanduser(
    '~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/ihp-sg13g2.drc')
CI_REPORT = os.path.join(LAYOUT_DIR, '..', 'sg13g2_drc_main.lyrdb')

# IHP SG13G2 layer numbers
LAYERS = {
    'Activ': (1, 0), 'GatPoly': (5, 0), 'Cont': (6, 0),
    'M1': (8, 0), 'M2': (10, 0), 'pSD': (14, 0),
    'Via1': (19, 0), 'NWell': (31, 0),
}

# DRC rule values (nm)
RULES = {
    'M1_space': 180, 'M1_width': 160,
    'M2_space': 210, 'M2_width': 210,
}


def _get_layer(ly, name):
    """Safe layer lookup — returns None if not found, never confuses 0 with False."""
    ln, ld = LAYERS[name]
    idx = ly.find_layer(ln, ld)
    return idx  # can be 0 (valid), None (not found)


def _get_region(cell, ly, name):
    """Get Region for a layer, handling index=0 correctly."""
    idx = _get_layer(ly, name)
    if idx is None:
        return pya.Region()
    return pya.Region(cell.begin_shapes_rec(idx))


def check_module(mod_name, run_ci=True):
    """Run all checks on a module. Returns dict of results."""
    path = os.path.join(OUT_DIR, f'{mod_name}.gds')
    if not os.path.exists(path):
        return None

    ly = pya.Layout()
    ly.read(path)

    # Handle multiple top cells gracefully
    if ly.top_cells() and len(ly.top_cells()) == 1:
        cell = ly.top_cell()
    elif ly.top_cells():
        cell = ly.top_cells()[0]  # use first
    else:
        return None

    results = {
        'name': mod_name,
        'size': f'{cell.bbox().width()/1000:.1f}x{cell.bbox().height()/1000:.1f}',
        'issues': [],
    }

    # Build regions using safe accessor
    m1_raw = _get_region(cell, ly, 'M1')
    m1 = m1_raw.merged()
    m2_raw = _get_region(cell, ly, 'M2')
    m2 = m2_raw.merged()
    cont = _get_region(cell, ly, 'Cont')
    via1 = _get_region(cell, ly, 'Via1')
    poly = _get_region(cell, ly, 'GatPoly')

    has_m2 = m2_raw.count() > 0
    has_via1 = via1.count() > 0

    # ════════════════════════════════════════════
    # Check 1: Quick DRC (M1 + M2 space/width)
    # ════════════════════════════════════════════
    m1b = m1.space_check(RULES['M1_space']).count()
    m1a = m1.width_check(RULES['M1_width']).count()
    m2b = m2.space_check(RULES['M2_space']).count() if has_m2 else 0
    m2a = m2.width_check(RULES['M2_width']).count() if has_m2 else 0
    results.update({'m1b': m1b, 'm1a': m1a, 'm2b': m2b, 'm2a': m2a})
    if m1b: results['issues'].append(f'M1.b={m1b} spacing violations')
    if m1a: results['issues'].append(f'M1.a={m1a} width violations')
    if m2b: results['issues'].append(f'M2.b={m2b} spacing violations')
    if m2a: results['issues'].append(f'M2.a={m2a} width violations')

    # ════════════════════════════════════════════
    # Check 2: CI DRC
    # ════════════════════════════════════════════
    results['ci'] = -1
    if run_ci and os.path.exists(CI_DRC):
        os.system(f'klayout -n sg13g2 -zz -r {CI_DRC} -rd input={path} > /dev/null 2>&1')
        if os.path.exists(CI_REPORT):
            import xml.etree.ElementTree as ET
            tree = ET.parse(CI_REPORT)
            ci = sum(len(c.findall('.//item'))
                     for c in tree.getroot().findall('.//category'))
            results['ci'] = ci
            if ci: results['issues'].append(f'CI DRC={ci} violations')

    # ════════════════════════════════════════════
    # Check 3: Floating M1 (no Cont AND no Via1)
    # ════════════════════════════════════════════
    floating_m1 = []
    for p in m1.each():
        region = pya.Region(p)
        if (cont & region).count() == 0 and (via1 & region).count() == 0:
            b = p.bbox()
            floating_m1.append(f'({b.left/1000:.2f},{b.bottom/1000:.2f})')
    results['floating_m1'] = len(floating_m1)
    if floating_m1:
        results['issues'].append(f'Floating M1: {len(floating_m1)} at {"; ".join(floating_m1[:5])}')

    # ════════════════════════════════════════════
    # Check 4: Floating M2 (no Via1)
    # ════════════════════════════════════════════
    floating_m2 = []
    if has_m2:
        for p in m2.each():
            if (via1 & pya.Region(p)).count() == 0:
                b = p.bbox()
                floating_m2.append(f'({b.left/1000:.2f},{b.bottom/1000:.2f})')
    results['floating_m2'] = len(floating_m2)
    if floating_m2:
        results['issues'].append(f'Floating M2: {len(floating_m2)} at {"; ".join(floating_m2[:5])}')

    # ════════════════════════════════════════════
    # Check 5: Via1 without M1 underneath
    # ════════════════════════════════════════════
    v1_no_m1 = []
    for p in via1.each():
        b = p.bbox()
        if (m1_raw & pya.Region(b)).count() == 0:
            v1_no_m1.append(f'({b.left/1000:.2f},{b.bottom/1000:.2f})')
    results['v1_no_m1'] = len(v1_no_m1)
    if v1_no_m1:
        results['issues'].append(f'Via1 no M1 below: {len(v1_no_m1)} at {"; ".join(v1_no_m1[:5])}')

    # ════════════════════════════════════════════
    # Check 6: Via1 without M2 above
    # ════════════════════════════════════════════
    v1_no_m2 = []
    if has_m2:
        for p in via1.each():
            b = p.bbox()
            if (m2_raw & pya.Region(b)).count() == 0:
                v1_no_m2.append(f'({b.left/1000:.2f},{b.bottom/1000:.2f})')
    results['v1_no_m2'] = len(v1_no_m2)
    if v1_no_m2:
        results['issues'].append(f'Via1 no M2 above: {len(v1_no_m2)} at {"; ".join(v1_no_m2[:5])}')

    # ════════════════════════════════════════════
    # Check 7: Contact without M1 above
    # ════════════════════════════════════════════
    cont_no_m1 = []
    for p in cont.each():
        b = p.bbox()
        if (m1_raw & pya.Region(b)).count() == 0:
            cont_no_m1.append(f'({b.left/1000:.2f},{b.bottom/1000:.2f})')
    results['cont_no_m1'] = len(cont_no_m1)
    if cont_no_m1:
        results['issues'].append(f'Cont no M1: {len(cont_no_m1)} at {"; ".join(cont_no_m1[:5])}')

    # ════════════════════════════════════════════
    # Check 8: M1 with Via1 but no Contact (strip disconnect)
    # ════════════════════════════════════════════
    v1_no_cont = 0
    if has_via1:
        for p in m1.each():
            region = pya.Region(p)
            if (via1 & region).count() > 0 and (cont & region).count() == 0:
                v1_no_cont += 1
    results['v1_no_cont'] = v1_no_cont
    if v1_no_cont:
        results['issues'].append(f'M1+Via1 no Cont: {v1_no_cont} (strip disconnect?)')

    # ════════════════════════════════════════════
    # Check 9: Gate contact connectivity
    # A gate contact (Cont overlapping GatPoly) should be in a M1 region
    # that also connects to something else (routing bar or strip).
    # If the M1 region is tiny (< 500nm both dims), the gate pad is isolated.
    # ════════════════════════════════════════════
    iso_gates = 0
    for cp in cont.each():
        cb = cp.bbox()
        if (poly & pya.Region(cb)).count() == 0:
            continue  # not a gate contact
        touching = m1.interacting(pya.Region(cb))
        if touching.count() == 0:
            iso_gates += 1
        else:
            # A gate contact is isolated only if its M1 region is tiny
            # AND has no Via1 (no M2 routing escape)
            for mp in touching.each():
                mb = mp.bbox()
                mr = pya.Region(mp)
                is_small = mb.width() < 400 and mb.height() < 400
                has_via = (via1 & mr).count() > 0
                if is_small and not has_via:
                    iso_gates += 1
                break
    results['iso_gates'] = iso_gates
    if iso_gates:
        results['issues'].append(f'Isolated gate contacts: {iso_gates}')

    # ════════════════════════════════════════════
    # Check 10: Contact not on Poly AND not on Activ (floating contact)
    # ════════════════════════════════════════════
    activ = _get_region(cell, ly, 'Activ')
    cont_floating = 0
    for cp in cont.each():
        cb = cp.bbox()
        if (poly & pya.Region(cb)).count() == 0 and (activ & pya.Region(cb)).count() == 0:
            cont_floating += 1
    results['cont_float'] = cont_floating
    if cont_floating:
        results['issues'].append(f'Floating Cont (not on Poly/Activ): {cont_floating}')

    # ════════════════════════════════════════════
    # Check 11: Via1 M1 enclosure < 50nm
    # ════════════════════════════════════════════
    v1_enc_fail = 0
    for vp in via1.each():
        vb = vp.bbox()
        for mp in m1_raw.interacting(pya.Region(vb)).each():
            mb = mp.bbox()
            enc = min(vb.left-mb.left, mb.right-vb.right, vb.bottom-mb.bottom, mb.top-vb.top)
            if enc < 50:
                v1_enc_fail += 1
            break
    results['v1_enc'] = v1_enc_fail
    if v1_enc_fail:
        results['issues'].append(f'Via1 M1 enc <50nm: {v1_enc_fail}')

    # ════════════════════════════════════════════
    # Check 12: Gate contact M1 enclosure < 60nm (Cnt.c=70nm)
    # Only checks contacts on GatPoly (our routing), skips PCell S/D contacts
    # ════════════════════════════════════════════
    gate_enc_fail = 0
    for cp in cont.each():
        cb = cp.bbox()
        if (poly & pya.Region(cb)).count() == 0:
            continue  # S/D contact (PCell-designed), skip
        for mp in m1_raw.interacting(pya.Region(cb)).each():
            mb = mp.bbox()
            enc = min(cb.left-mb.left, mb.right-cb.right, cb.bottom-mb.bottom, mb.top-cb.top)
            if enc < 60:
                gate_enc_fail += 1
            break
    results['gate_enc'] = gate_enc_fail
    if gate_enc_fail:
        results['issues'].append(f'Gate Cont M1 enc <60nm: {gate_enc_fail}')

    return results


def print_report(results_list):
    """Print formatted verification report."""
    # Two-tier display: DRC tier + connectivity tier
    print('── DRC Checks ──')
    hdr1 = f'{"Module":16s} {"Size":>10s} {"M1.b":>5s} {"M1.a":>5s} {"M2.b":>5s} {"M2.a":>5s} {"CI":>4s}'
    print(hdr1); print('-'*len(hdr1))
    for r in results_list:
        if not r: continue
        ci = str(r['ci']) if r['ci']>=0 else '?'
        print(f'{r["name"]:16s} {r["size"]:>10s} {r["m1b"]:>5d} {r["m1a"]:>5d} {r["m2b"]:>5d} {r.get("m2a",0):>5d} {ci:>4s}')

    print('\n── Connectivity Checks ──')
    hdr2 = f'{"Module":16s} {"FltM1":>5s} {"FltM2":>5s} {"V1nM1":>5s} {"V1nM2":>5s} {"CnM1":>5s} {"V1nC":>5s} {"Gate":>5s}'
    print(hdr2); print('-'*len(hdr2))
    for r in results_list:
        if not r: continue
        print(f'{r["name"]:16s} {r["floating_m1"]:>5d} {r["floating_m2"]:>5d} {r["v1_no_m1"]:>5d} '
              f'{r.get("v1_no_m2",0):>5d} {r.get("cont_no_m1",0):>5d} {r["v1_no_cont"]:>5d} {r.get("iso_gates",0):>5d}')

    print('\n── Physical Integrity Checks ──')
    hdr3 = f'{"Module":16s} {"CFloat":>6s} {"V1Enc":>6s} {"GtEnc":>6s}'
    print(hdr3); print('-'*len(hdr3))
    all_pass = True
    for r in results_list:
        if not r: continue
        if r['issues']: all_pass = False
        print(f'{r["name"]:16s} {r.get("cont_float",0):>6d} {r.get("v1_enc",0):>6d} {r.get("gate_enc",0):>6d}')

    print()
    if all_pass:
        print('ALL MODULES PASS ✅')
    else:
        print('ISSUES FOUND:')
        for r in results_list:
            if r and r['issues']:
                for iss in r['issues']:
                    print(f'  {r["name"]}: {iss}')


def main():
    args = sys.argv[1:]
    if args:
        modules = args
    else:
        # Auto-detect: all .gds in output/ except soilz_* and tff_*
        modules = []
        if os.path.exists(OUT_DIR):
            for f in sorted(os.listdir(OUT_DIR)):
                if f.endswith('.gds') and not f.startswith(('soilz', 'tff')):
                    modules.append(f[:-4])

    print(f'=== SoilZ Module Verification ({len(modules)} modules) ===\n')

    results = []
    for mod in modules:
        r = check_module(mod, run_ci=True)
        if r:
            results.append(r)

    print_report(results)


if __name__ == '__main__':
    main()
