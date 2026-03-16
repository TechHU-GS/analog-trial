#!/usr/bin/env python3
"""Diagnose 10 missing nets + vdd_vco label/connectivity issues.

For each target net:
1. Find ALL labels in GDS (M1/M2/M3) matching the net name
2. Check if the label lands on a valid metal polygon
3. Check connectivity from that polygon (Via1/Via2/Via3 hops)
4. Cross-reference with extracted netlist — is the net present under a different name?
5. Cross-reference with reference netlist — what devices should be on this net?

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_missing_nets.py
"""
import os, json, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

TARGET_NETS = [
    'buf1', 'sel0', 'sel0b', 'sel1', 'sel1b', 'sel2', 'sel2b',
    'vco_out', 'vref_comp', 'vref_ota', 'vdd_vco'
]

LABEL_LAYERS = {
    'M1': (8, 25),
    'M2': (10, 25),
    'M3': (30, 25),
}
METAL_LAYERS = {
    'M1': (8, 0),
    'M2': (10, 0),
    'M3': (30, 0),
    'M4': (50, 0),
}
VIA_LAYERS = {
    'Via1': (19, 0),
    'Via2': (29, 0),
    'Via3': (49, 0),
}

# Build merged metal regions
metal_regions = {}
metal_polys = {}
for name, (l, d) in METAL_LAYERS.items():
    reg = kdb.Region(top.begin_shapes_rec(layout.layer(l, d))).merged()
    metal_regions[name] = reg
    metal_polys[name] = list(reg.each())

via_regions = {}
for name, (l, d) in VIA_LAYERS.items():
    via_regions[name] = kdb.Region(top.begin_shapes_rec(layout.layer(l, d)))

# ── Collect ALL labels ──
all_labels = {}  # net_name -> [(layer_name, x, y)]
for lname, (ll, ld) in LABEL_LAYERS.items():
    li = layout.layer(ll, ld)
    for shape in top.shapes(li).each():
        if not shape.is_text():
            continue
        net = shape.text.string
        pt = (shape.text.x, shape.text.y)
        if net not in all_labels:
            all_labels[net] = []
        all_labels[net].append((lname, pt[0], pt[1]))

# ── Load reference netlist ──
ref_device_nets = {}  # net_name -> [(device_name, pin_name)]
with open('ptat_vco_lvs.spice') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        if line.startswith('M'):
            parts = line.split()
            # M name D G S B type ...
            if len(parts) >= 6:
                mname = parts[0]
                d, g, s, b = parts[1], parts[2], parts[3], parts[4]
                for pin, net in [('D', d), ('G', g), ('S', s), ('B', b)]:
                    if net not in ref_device_nets:
                        ref_device_nets[net] = []
                    ref_device_nets[net].append((mname, pin))
        elif line.startswith('R'):
            parts = line.split()
            if len(parts) >= 4:
                rname = parts[0]
                p1, p2 = parts[1], parts[2]
                for pin, net in [('P', p1), ('N', p2)]:
                    if net not in ref_device_nets:
                        ref_device_nets[net] = []
                    ref_device_nets[net].append((rname, pin))

# ── Load extracted netlist ──
ext_net_names = set()
with open('/tmp/lvs_test2/ptat_vco_extracted.cir') as f:
    for line in f:
        line = line.strip()
        if line.startswith('.SUBCKT'):
            parts = line.split()
            for p in parts[2:]:
                ext_net_names.add(p.replace('\\', ''))
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        if line.startswith('M') or line.startswith('R'):
            parts = line.split()
            for p in parts[1:]:
                if not p.startswith('sg13') and '=' not in p and not p[0].isdigit():
                    ext_net_names.add(p.replace('\\', ''))

# ── Load routing data ──
with open('output/routing_optimized.json') as f:
    routing = json.load(f)

# ── Analyze each target net ──
print('=' * 70)
print(f'Missing net analysis ({len(TARGET_NETS)} nets)')
print('=' * 70)

for net_name in TARGET_NETS:
    print(f'\n{"─" * 50}')
    print(f'Net: {net_name}')
    print(f'{"─" * 50}')

    # 1. Labels in GDS
    labels = all_labels.get(net_name, [])
    if labels:
        print(f'  Labels in GDS: {len(labels)}')
        for lname, lx, ly in labels:
            print(f'    {lname} label at ({lx/1e3:.3f}, {ly/1e3:.3f})')
            # Check if label lands on a valid metal polygon
            probe = kdb.Region(kdb.Box(lx - 50, ly - 50, lx + 50, ly + 50))
            metal_name = lname  # label layer corresponds to metal layer
            overlap = metal_regions[metal_name] & probe
            if overlap.is_empty():
                print(f'      *** NO {metal_name} polygon under label! ***')
            else:
                for p in overlap.each():
                    bb = p.bbox()
                    print(f'      On {metal_name} polygon: ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})'
                          f'-({bb.right/1e3:.3f},{bb.top/1e3:.3f})')
    else:
        print(f'  Labels in GDS: NONE')

    # 2. Check routing data
    route = routing.get('signal_routes', {}).get(net_name)
    if route:
        segs = route.get('segments', [])
        pins = route.get('pins', [])
        layer_counts = {}
        for seg in segs:
            lyr = seg[4] if len(seg) > 4 else -1
            ln = {0:'M1',1:'M2',2:'M3',3:'M4',-1:'Via1',-2:'Via2',-3:'Via3'}.get(lyr, f'L{lyr}')
            layer_counts[ln] = layer_counts.get(ln, 0) + 1
        has_m1 = layer_counts.get('M1', 0) > 0
        has_m2 = layer_counts.get('M2', 0) > 0
        print(f'  Route: {len(segs)} segments, pins={pins}')
        print(f'    Layers: {dict(sorted(layer_counts.items()))}')
        if not has_m1 and not has_m2:
            print(f'    *** NO M1/M2 segments — label may be on M3 only ***')
    else:
        print(f'  Route: NOT in signal_routes')
        # Check power rails
        power = routing.get('power', {})
        rails = power.get('rails', {})
        if net_name in rails or any(net_name in str(r) for r in (rails if isinstance(rails, list) else rails.values())):
            print(f'    Found in power rails')

    # 3. Reference netlist connections
    ref_conns = ref_device_nets.get(net_name, [])
    if ref_conns:
        print(f'  Reference: {len(ref_conns)} device connections')
        for dname, pin in ref_conns[:8]:
            print(f'    {dname}.{pin}')
        if len(ref_conns) > 8:
            print(f'    ... and {len(ref_conns)-8} more')
    else:
        print(f'  Reference: no device connections (port only?)')

    # 4. Check extracted netlist
    if net_name in ext_net_names:
        print(f'  Extracted: PRESENT')
    else:
        # Check with $ prefix or other mangling
        close = [n for n in ext_net_names if net_name in n]
        if close:
            print(f'  Extracted: ABSENT but similar names: {close[:5]}')
        else:
            print(f'  Extracted: ABSENT (no similar names)')

    # 5. For missing labels: check if AP positions have labels
    if not labels:
        if route:
            pins = route.get('pins', [])
            aps = routing.get('access_points', {})
            print(f'  Checking AP positions for label coverage:')
            for pin in pins[:4]:
                ap = aps.get(pin)
                if ap:
                    apx, apy = ap['x'], ap['y']
                    # Check what labels exist at this AP position
                    for lname, (ll, ld) in LABEL_LAYERS.items():
                        li = layout.layer(ll, ld)
                        for shape in top.shapes(li).each():
                            if shape.is_text():
                                pt = (shape.text.x, shape.text.y)
                                if abs(pt[0] - apx) < 500 and abs(pt[1] - apy) < 500:
                                    print(f'    {pin} AP ({apx/1e3:.3f},{apy/1e3:.3f}): '
                                          f'found {lname} label "{shape.text.string}" '
                                          f'at ({pt[0]/1e3:.3f},{pt[1]/1e3:.3f})')

print(f'\n{"=" * 70}')
print('Summary')
print(f'{"=" * 70}')
labeled = sum(1 for n in TARGET_NETS if n in all_labels)
print(f'Nets with GDS labels: {labeled}/{len(TARGET_NETS)}')
routed = sum(1 for n in TARGET_NETS if n in routing.get('signal_routes', {}))
print(f'Nets with signal routes: {routed}/{len(TARGET_NETS)}')
extracted = sum(1 for n in TARGET_NETS if n in ext_net_names)
print(f'Nets in extracted netlist: {extracted}/{len(TARGET_NETS)}')
