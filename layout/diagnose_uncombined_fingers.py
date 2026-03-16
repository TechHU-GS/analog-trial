#!/usr/bin/env python3
"""Diagnose uncombined multi-finger MOSFETs.

With --combine_devices, KLayout should merge parallel fingers into one device.
Current status: 5 NMOS W=4u→2×W=2u and 5 PMOS W=4u→2×W=2u remain split.
Also: NMOS L=4u missing 2u width, PMOS L=10u missing 1u width.

This script finds:
1. All extracted W=2u L=0.5u NMOS — which ones should be W=4u?
2. All extracted W=2u L=2u PMOS — which ones should be W=4u?
3. Checks S/D connectivity between adjacent fingers
4. Identifies missing-width devices

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_uncombined_fingers.py
"""
import os, re, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
EXT_CIR = '/tmp/lvs_combine/ptat_vco_extracted.cir'
REF_CIR = 'ptat_vco_lvs.spice'

# Parse extracted netlist — get device names and connections
def parse_cir(path):
    devices = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^(M\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(sg13_lv_[np]mos)\s+(.*)', line)
            if m:
                name, d, g, s, b, model, params = m.groups()
                w_m = re.search(r'W=([\d.]+)u', params)
                l_m = re.search(r'L=([\d.]+)u', params)
                w = float(w_m.group(1)) if w_m else 0
                l = float(l_m.group(1)) if l_m else 0
                devices.append({
                    'name': name, 'D': d, 'G': g, 'S': s, 'B': b,
                    'model': model, 'W': w, 'L': l
                })
    return devices

ext_devs = parse_cir(EXT_CIR)
ref_devs = parse_cir(REF_CIR)

print("=" * 70)
print("Issue 1: Uncombined NMOS W=2u L=0.5u (should be W=4u)")
print("=" * 70)

# Reference W=4u L=0.5u NMOS
ref_4u_nmos = [d for d in ref_devs if d['model'] == 'sg13_lv_nmos' and abs(d['W']-4)<0.01 and abs(d['L']-0.5)<0.01]
print(f"\nReference W=4u L=0.5u NMOS: {len(ref_4u_nmos)}")
for d in ref_4u_nmos:
    print(f"  {d['name']}: D={d['D']} G={d['G']} S={d['S']} B={d['B']}")

# Extracted W=2u L=0.5u NMOS — these include both legitimate W=2u AND split W=4u→2×W=2u
ext_2u_nmos = [d for d in ext_devs if d['model'] == 'sg13_lv_nmos' and abs(d['W']-2)<0.01 and abs(d['L']-0.5)<0.01]
print(f"\nExtracted W=2u L=0.5u NMOS: {len(ext_2u_nmos)} (ref has {len([d for d in ref_devs if d['model']=='sg13_lv_nmos' and abs(d['W']-2)<0.01 and abs(d['L']-0.5)<0.01])})")

# Group by (G, B) — same gate/bulk = same logical device
from collections import defaultdict
nmos_by_gb = defaultdict(list)
for d in ext_2u_nmos:
    key = (d['G'], d['B'])
    nmos_by_gb[key].append(d)

print(f"\nGrouped by (G,B):")
for (g, b), devs in sorted(nmos_by_gb.items(), key=lambda x: -len(x[1])):
    # Find pairs that share S/D (should combine)
    print(f"  G={g}, B={b}: {len(devs)} devices")
    # Check which share S or D nets
    for i, d1 in enumerate(devs):
        for d2 in devs[i+1:]:
            sd1 = {d1['S'], d1['D']}
            sd2 = {d2['S'], d2['D']}
            shared = sd1 & sd2
            if shared:
                print(f"    PAIR: {d1['name']}(D={d1['D']},S={d1['S']}) + {d2['name']}(D={d2['D']},S={d2['S']}) share={shared}")
            elif sd1 == sd2:
                print(f"    PARALLEL: {d1['name']} + {d2['name']} same S/D nets → should combine!")

print("\n" + "=" * 70)
print("Issue 2: Uncombined PMOS W=2u L=2u (should be W=4u)")
print("=" * 70)

ref_4u_pmos = [d for d in ref_devs if d['model'] == 'sg13_lv_pmos' and abs(d['W']-4)<0.01 and abs(d['L']-2)<0.01]
print(f"\nReference W=4u L=2u PMOS: {len(ref_4u_pmos)}")
for d in ref_4u_pmos:
    print(f"  {d['name']}: D={d['D']} G={d['G']} S={d['S']} B={d['B']}")

ext_2u_pmos = [d for d in ext_devs if d['model'] == 'sg13_lv_pmos' and abs(d['W']-2)<0.01 and abs(d['L']-2)<0.01]
print(f"\nExtracted W=2u L=2u PMOS: {len(ext_2u_pmos)}")

pmos_by_gb = defaultdict(list)
for d in ext_2u_pmos:
    key = (d['G'], d['B'])
    pmos_by_gb[key].append(d)

print(f"\nGrouped by (G,B):")
for (g, b), devs in sorted(pmos_by_gb.items(), key=lambda x: -len(x[1])):
    print(f"  G={g}, B={b}: {len(devs)} devices")
    for i, d1 in enumerate(devs):
        for d2 in devs[i+1:]:
            sd1 = {d1['S'], d1['D']}
            sd2 = {d2['S'], d2['D']}
            shared = sd1 & sd2
            if shared:
                print(f"    PAIR: {d1['name']}(D={d1['D']},S={d1['S']}) + {d2['name']}(D={d2['D']},S={d2['S']}) share={shared}")
            if sd1 == sd2:
                print(f"    *** SHOULD COMBINE: {d1['name']} + {d2['name']} ***")

print("\n" + "=" * 70)
print("Issue 3: Missing width")
print("=" * 70)

# NMOS L=4u: ext=28u, ref=30u → missing 2u
ext_nmos_l4 = [d for d in ext_devs if d['model'] == 'sg13_lv_nmos' and abs(d['L']-4)<0.01]
ref_nmos_l4 = [d for d in ref_devs if d['model'] == 'sg13_lv_nmos' and abs(d['L']-4)<0.01]
print(f"\nNMOS L=4u:")
print(f"  Extracted: {len(ext_nmos_l4)} devices, total W={sum(d['W'] for d in ext_nmos_l4):.1f}u")
print(f"  Reference: {len(ref_nmos_l4)} devices, total W={sum(d['W'] for d in ref_nmos_l4):.1f}u")
for d in ext_nmos_l4:
    print(f"    {d['name']}: W={d['W']}u D={d['D']} G={d['G']} S={d['S']} B={d['B']}")
print(f"  Reference devices:")
for d in ref_nmos_l4:
    print(f"    {d['name']}: W={d['W']}u D={d['D']} G={d['G']} S={d['S']} B={d['B']}")

# PMOS L=10u: ext=9u, ref=10u → missing 1u
ext_pmos_l10 = [d for d in ext_devs if d['model'] == 'sg13_lv_pmos' and abs(d['L']-10)<0.01]
ref_pmos_l10 = [d for d in ref_devs if d['model'] == 'sg13_lv_pmos' and abs(d['L']-10)<0.01]
print(f"\nPMOS L=10u:")
print(f"  Extracted: {len(ext_pmos_l10)} devices, total W={sum(d['W'] for d in ext_pmos_l10):.1f}u")
print(f"  Reference: {len(ref_pmos_l10)} devices, total W={sum(d['W'] for d in ref_pmos_l10):.1f}u")
for d in ext_pmos_l10:
    print(f"    {d['name']}: W={d['W']}u D={d['D']} G={d['G']} S={d['S']} B={d['B']}")
print(f"  Reference devices:")
for d in ref_pmos_l10:
    print(f"    {d['name']}: W={d['W']}u D={d['D']} G={d['G']} S={d['S']} B={d['B']}")

print("\n" + "=" * 70)
print("Issue 4: NMOS W=4u L=0.5u analysis")
print("=" * 70)
ext_4u_nmos = [d for d in ext_devs if d['model'] == 'sg13_lv_nmos' and abs(d['W']-4)<0.01 and abs(d['L']-0.5)<0.01]
print(f"\nExtracted W=4u L=0.5u NMOS: {len(ext_4u_nmos)} (ref={len(ref_4u_nmos)})")
for d in ext_4u_nmos:
    print(f"  {d['name']}: D={d['D']} G={d['G']} S={d['S']} B={d['B']}")

# Show the split ones — same gate as ref W=4u but extracted as W=2u
print(f"\nCross-referencing: which ref W=4u NMOS gates appear as W=2u in extracted?")
ref_gates = set(d['G'] for d in ref_4u_nmos)
for gate in sorted(ref_gates):
    ext_matches = [d for d in ext_2u_nmos if d['G'] == gate]
    ext_4u_matches = [d for d in ext_4u_nmos if d['G'] == gate]
    if ext_matches:
        print(f"  Gate={gate}: ref has {sum(1 for d in ref_4u_nmos if d['G']==gate)} W=4u, "
              f"ext has {len(ext_4u_matches)} W=4u + {len(ext_matches)} W=2u")
        for d in ext_matches:
            print(f"    {d['name']}: D={d['D']} S={d['S']}")
