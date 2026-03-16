#!/usr/bin/env python3
"""Diagnose why PM3 and PM4 are not extracted as PMOS transistors.

Replicates the PDK LVS derivation chain step by step at PM3/PM4 positions:
  pactiv  = activ.and(psd_drw)
  tgate   = gatpoly.and(activ).not(res_mk)
  pgate   = pactiv.and(tgate)
  psd_fet = pactiv.and(nwell_drw).interacting(pgate).not(pgate).not_interacting(res_mk)

Also checks mos_exclude layers that might block extraction.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_pm3_pm4_extraction.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

# --- Load placement ---
with open('placement.json') as f:
    placement = json.load(f)

# All 4 pmos_mirror instances
MIRROR_DEVICES = ['PM3', 'PM4', 'PM5', 'PM_ref']

# --- GDS layer numbers (from PDK layers_definitions.lvs) ---
LAYERS = {
    'Activ':     (1, 0),
    'Activ_fill': (1, 22),
    'Activ_mask': (1, 20),
    'GatPoly':   (5, 0),
    'GatPoly_fill': (5, 22),
    'nSD':       (7, 0),
    'nSD_block': (7, 21),
    'pSD':       (14, 0),
    'NWell':     (31, 0),
    'Substrate': (40, 0),
    'Cont':      (6, 0),
    'M1':        (8, 0),
    'Via1':      (19, 0),
    'M2':        (10, 0),
    # Exclusion layers in mos_exclude:
    'pwell_block': (31, 21),
    'trans_drw':   (5, 30),
    'emwind_drw':  (11, 0),
    'emwihv_drw':  (12, 0),
    'salblock_drw': (28, 0),
    'polyres_drw': (5, 13),
    'extblock_drw': (111, 0),
    'res_drw':     (24, 0),
    'recog_diode': (18, 0),
    'recog_esd':   (19, 10),
    'ind_drw':     (38, 0),
    'ind_pin':     (38, 2),
    'thickgateox': (44, 0),
}

def get_layer(name):
    ln, dt = LAYERS[name]
    return layout.layer(ln, dt)

# Load key layer regions (flattened/merged)
def load_region(name):
    li = get_layer(name)
    return kdb.Region(top.begin_shapes_rec(li))

activ_drw = load_region('Activ')
activ_fill = load_region('Activ_fill')
activ = (activ_drw + activ_fill).merged()

gatpoly_drw = load_region('GatPoly')
gatpoly_fill = load_region('GatPoly_fill')
gatpoly = (gatpoly_drw + gatpoly_fill).merged()

psd_drw = load_region('pSD')
nsd_drw = load_region('nSD')
nsd_block = load_region('nSD_block')
nwell_drw = load_region('NWell')
substrate_drw = load_region('Substrate')
activ_mask = load_region('Activ_mask')

# Exclusion layers
polyres_drw = load_region('polyres_drw')
res_drw = load_region('res_drw')
recog_diode = load_region('recog_diode')

# Derive LVS layers
res_mk = (polyres_drw + res_drw).merged()
nactiv = activ - psd_drw - nsd_block
pactiv = activ & psd_drw
tgate = (gatpoly & activ) - res_mk
ngate = nactiv & tgate
pgate = pactiv & tgate
nsd_fet = ((nactiv - nwell_drw).interacting(ngate) - ngate).not_interacting(res_mk)
psd_fet = ((pactiv & nwell_drw).interacting(pgate) - pgate).not_interacting(res_mk)

# Load device lib for PCell origins
from atk.device import load_device_lib, get_pcell_params
from atk.pdk import UM, s5
device_lib = load_device_lib('atk/data/device_lib.json')

print("=" * 70)
print("PM3/PM4 PMOS Extraction Diagnostic")
print("=" * 70)

for inst_name in MIRROR_DEVICES:
    info = placement['instances'].get(inst_name)
    if info is None:
        continue
    dev_type = info['type']
    dev = get_pcell_params(device_lib, dev_type)

    # PCell origin in GDS coordinates (nm)
    pcell_x = s5(info['x_um'] - dev['ox'])
    pcell_y = s5(info['y_um'] - dev['oy'])

    # Device bounding box in GDS (nm)
    dev_w = int(dev['w'] * UM)
    dev_h = int(dev['h'] * UM)

    print(f"\n{'='*60}")
    print(f"Device: {inst_name} ({dev_type})")
    print(f"Placement: ({info['x_um']}, {info['y_um']}) µm")
    print(f"PCell origin: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f}) µm")
    print(f"PCell bbox: ({pcell_x/1e3:.3f},{pcell_y/1e3:.3f}) - "
          f"({(pcell_x+dev_w)/1e3:.3f},{(pcell_y+dev_h)/1e3:.3f}) µm")
    print(f"{'='*60}")

    # Probe region = PCell bounding box + 1µm margin
    margin = 1000  # nm
    probe_box = kdb.Box(pcell_x - margin, pcell_y - margin,
                        pcell_x + dev_w + margin, pcell_y + dev_h + margin)
    probe = kdb.Region(probe_box)

    # Check each raw layer
    print(f"\n  Raw layers at device position:")
    for lname in ['Activ', 'GatPoly', 'pSD', 'nSD', 'NWell', 'Substrate',
                  'Activ_mask', 'nSD_block', 'polyres_drw', 'res_drw',
                  'recog_diode']:
        li = get_layer(lname)
        shapes = kdb.Region(top.begin_shapes_rec(li)) & probe
        if shapes.is_empty():
            print(f"    {lname:15s}: EMPTY")
        else:
            count = 0
            for poly in shapes.each():
                bb = poly.bbox()
                print(f"    {lname:15s}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                      f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                      f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f} µm")
                count += 1
                if count >= 5:
                    print(f"    {lname:15s}: ... (more shapes)")
                    break

    # Check derived layers
    print(f"\n  Derived layers:")
    for dname, dreg in [('activ', activ), ('pactiv', pactiv), ('nactiv', nactiv),
                        ('gatpoly', gatpoly), ('tgate', tgate), ('pgate', pgate),
                        ('pactiv&NWell', pactiv & nwell_drw),
                        ('psd_fet', psd_fet), ('nsd_fet', nsd_fet),
                        ('res_mk', res_mk)]:
        hit = dreg & probe
        if hit.is_empty():
            print(f"    {dname:15s}: EMPTY {'*** PROBLEM ***' if dname in ('pgate', 'psd_fet') else ''}")
        else:
            for poly in hit.each():
                bb = poly.bbox()
                print(f"    {dname:15s}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                      f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                      f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f} µm")

    # Check mos_exclude layers
    print(f"\n  mos_exclude layers:")
    exclude_layers = ['pwell_block', 'nSD', 'trans_drw', 'emwind_drw', 'emwihv_drw',
                      'salblock_drw', 'polyres_drw', 'extblock_drw', 'res_drw',
                      'Activ_mask', 'recog_diode', 'recog_esd', 'ind_drw', 'ind_pin',
                      'Substrate', 'nSD_block']
    any_exclude = False
    for lname in exclude_layers:
        try:
            li = get_layer(lname)
            shapes = kdb.Region(top.begin_shapes_rec(li)) & probe
            if not shapes.is_empty():
                any_exclude = True
                for poly in shapes.each():
                    bb = poly.bbox()
                    print(f"    {lname:15s}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                          f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                          f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f} µm")
        except:
            pass
    if not any_exclude:
        print(f"    None present")

    # Check PMOS exclusion chain: rfpmos_exc = pwell.join(nwell_holes).join(mos_exclude)
    # pmos_exc = rfpmos_exc.join(rfpmos_mk)
    # pgate_lv = pgate_lv_base.not(pmos_exc)
    # If pgate is present but gets excluded by pmos_exc, the transistor won't extract

    # Check if pgate overlaps with pwell (which would indicate wrong region)
    pwell_allowed = kdb.Region(top.bbox()) - nwell_drw  # simplified
    pwell_at_device = pwell_allowed & probe
    pgate_at_device = pgate & probe
    if not pgate_at_device.is_empty():
        pgate_in_pwell = pgate_at_device & pwell_at_device
        if not pgate_in_pwell.is_empty():
            print(f"\n  *** pgate overlaps pwell! This is wrong for PMOS ***")

    # Check contact/M1 connectivity
    print(f"\n  Contact/M1 shapes:")
    for lname in ['Cont', 'M1']:
        li = get_layer(lname)
        shapes = kdb.Region(top.begin_shapes_rec(li)) & probe
        count = 0
        for poly in shapes.each():
            bb = poly.bbox()
            print(f"    {lname:15s}: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-"
                  f"({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
                  f"{bb.width()/1e3:.3f}x{bb.height()/1e3:.3f} µm")
            count += 1
            if count >= 10:
                print(f"    {lname:15s}: ... (more shapes)")
                break

# --- Global summary ---
print(f"\n{'='*70}")
print(f"Global psd_fet count: {psd_fet.count()} shapes")
print(f"Global pgate count: {pgate.count()} shapes")
print(f"Global nsd_fet count: {nsd_fet.count()} shapes")
print(f"Global ngate count: {ngate.count()} shapes")

# Check: how many pgate shapes are in the mirror island region?
mirror_region = kdb.Region(kdb.Box(
    int(20 * 1000), int(150 * 1000),
    int(75 * 1000), int(160 * 1000)
))
pgate_mirror = pgate & mirror_region
psd_mirror = psd_fet & mirror_region
print(f"\nIn mirror island (20-75, 150-160 µm):")
print(f"  pgate shapes: {pgate_mirror.count()}")
print(f"  psd_fet shapes: {psd_mirror.count()}")

for poly in pgate_mirror.each():
    bb = poly.bbox()
    w_um = bb.width() / 1e3
    h_um = bb.height() / 1e3
    print(f"  pgate: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f}) "
          f"W={min(w_um,h_um):.3f} L={max(w_um,h_um):.3f} µm")

for poly in psd_mirror.each():
    bb = poly.bbox()
    print(f"  psd_fet: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
