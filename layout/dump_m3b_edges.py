#!/usr/bin/env python3
"""Dump exact M3.b DRC edge-pair coordinates and compute gap distances."""
import xml.etree.ElementTree as ET
import re

UM = 1000
tree = ET.parse('/tmp/drc_r10a/ptat_vco_ptat_vco_full.lyrdb')
root = tree.getroot()
items = root[7]

def parse_edge(s):
    p1, p2 = s.split(';')
    x1, y1 = [float(c) for c in p1.split(',')]
    x2, y2 = [float(c) for c in p2.split(',')]
    return (x1*UM, y1*UM, x2*UM, y2*UM)

print('M3.b edge-pairs:')
print('=' * 130)
idx = 0
for item in items:
    cat = item.find('category')
    if cat is None or not cat.text:
        continue
    r = cat.text.strip().split(':')[0]
    if r != "'M3.b'":
        continue
    vals = item.find('values')
    if vals is None:
        continue
    for v in vals:
        txt = v.text.strip() if v.text else ''
        m = re.match(r'edge-pair:\s*\(([^)]+)\)\|\(([^)]+)\)', txt)
        if not m:
            continue
        e1 = parse_edge(m.group(1))
        e2 = parse_edge(m.group(2))
        # Edge midpoints
        mx1 = (e1[0]+e1[2])/2
        my1 = (e1[1]+e1[3])/2
        mx2 = (e2[0]+e2[2])/2
        my2 = (e2[1]+e2[3])/2
        # Edge directions
        e1_dir = 'H' if abs(e1[2]-e1[0]) > abs(e1[3]-e1[1]) else 'V'
        e2_dir = 'H' if abs(e2[2]-e2[0]) > abs(e2[3]-e2[1]) else 'V'
        # Edge lengths
        e1_len = max(abs(e1[2]-e1[0]), abs(e1[3]-e1[1]))
        e2_len = max(abs(e2[2]-e2[0]), abs(e2[3]-e2[1]))
        # Gap (approx between edge midpoints)
        dx = abs(mx2 - mx1)
        dy = abs(my2 - my1)
        idx += 1
        print(f'V{idx}: E1({e1[0]:.0f},{e1[1]:.0f})-({e1[2]:.0f},{e1[3]:.0f}) {e1_dir} len={e1_len:.0f}nm')
        print(f'    E2({e2[0]:.0f},{e2[1]:.0f})-({e2[2]:.0f},{e2[3]:.0f}) {e2_dir} len={e2_len:.0f}nm')
        print(f'    mid1=({mx1:.0f},{my1:.0f}) mid2=({mx2:.0f},{my2:.0f}) dx={dx:.0f} dy={dy:.0f}')
        print()
