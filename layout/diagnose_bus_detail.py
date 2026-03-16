#!/usr/bin/env python3
"""Detailed bus strap diagnostic for specific disconnected devices.

Traces M1 shapes around bus strap area to find where the gap is.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_bus_detail.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb
from atk.device import load_device_lib, get_pcell_params, get_sd_strips
from atk.pdk import UM, s5

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
m1_merged = kdb.Region(top.begin_shapes_rec(li_m1)).merged()

with open('placement.json') as f:
    placement = json.load(f)
instances = placement['instances']

device_lib = load_device_lib('atk/data/device_lib.json')
DEVICES = {dt: get_pcell_params(device_lib, dt) for dt in device_lib}

# Examine MS1 in detail
for inst_name in ['MS1', 'Mc_tail', 'Mpb1']:
    info = instances[inst_name]
    dev_type = info['type']
    sd = get_sd_strips(device_lib, dev_type)
    dev = DEVICES[dev_type]
    pcell_x = s5(info['x_um'] - dev['ox'])
    pcell_y = s5(info['y_um'] - dev['oy'])

    src_strips = sd['source']
    strip_top = src_strips[0][3]
    strip_bot = src_strips[0][1]

    print(f"\n{'='*70}")
    print(f"Device: {inst_name} ({dev_type})")
    print(f"PCell origin: ({pcell_x/1e3:.3f}, {pcell_y/1e3:.3f})")
    print(f"{'='*70}")

    for i, strip in enumerate(src_strips):
        sx1 = pcell_x + strip[0]
        sy1 = pcell_y + strip[1]
        sx2 = pcell_x + strip[2]
        sy2 = pcell_y + strip[3]
        print(f"  S[{i}]: ({sx1/1e3:.3f},{sy1/1e3:.3f})-({sx2/1e3:.3f},{sy2/1e3:.3f})")

    for i, strip in enumerate(sd['drain']):
        dx1 = pcell_x + strip[0]
        dy1 = pcell_y + strip[1]
        dx2 = pcell_x + strip[2]
        dy2 = pcell_y + strip[3]
        print(f"  D[{i}]: ({dx1/1e3:.3f},{dy1/1e3:.3f})-({dx2/1e3:.3f},{dy2/1e3:.3f})")

    # Find ALL M1 shapes in the bus strap region
    # Above device: y from strip_top to strip_top + 1000nm
    # Below device: y from strip_bot - 1000nm to strip_bot
    s_left = pcell_x + src_strips[0][0] - 200
    s_right = pcell_x + src_strips[-1][2] + 200

    print(f"\n  M1 shapes ABOVE device (y={pcell_y+strip_top:.0f}..+1000):")
    above_region = kdb.Region(kdb.Box(s_left, pcell_y + strip_top,
                                       s_right, pcell_y + strip_top + 1000))
    m1_above = m1_merged & above_region
    for poly in m1_above.each():
        bb = poly.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" {bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    print(f"\n  M1 shapes BELOW device (y={pcell_y+strip_bot:.0f}-1000..{pcell_y+strip_bot:.0f}):")
    below_region = kdb.Region(kdb.Box(s_left, pcell_y + strip_bot - 1000,
                                       s_right, pcell_y + strip_bot))
    m1_below = m1_merged & below_region
    for poly in m1_below.each():
        bb = poly.bbox()
        print(f"    ({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})"
              f" {bb.width()/1e3:.3f}x{bb.height()/1e3:.3f}")

    # Check: which M1 merged polygon contains each source strip?
    print(f"\n  Source strip → merged polygon mapping:")
    for i, strip in enumerate(src_strips):
        cx = pcell_x + (strip[0] + strip[2]) // 2
        cy = pcell_y + (strip[1] + strip[3]) // 2
        probe = kdb.Region(kdb.Box(cx - 5, cy - 5, cx + 5, cy + 5))
        found = False
        for idx, poly in enumerate(m1_merged.each()):
            if not (kdb.Region(poly) & probe).is_empty():
                bb = poly.bbox()
                print(f"    S[{i}] center ({cx/1e3:.3f},{cy/1e3:.3f}) → M1#{idx} "
                      f"({bb.left/1e3:.3f},{bb.bottom/1e3:.3f})-({bb.right/1e3:.3f},{bb.top/1e3:.3f})")
                found = True
                break
        if not found:
            print(f"    S[{i}] center ({cx/1e3:.3f},{cy/1e3:.3f}) → NO M1!")

    # Check labels at source strip positions
    print(f"\n  Labels near source strips:")
    for lname, (ll, ld) in [('M1', (8, 25)), ('M2', (10, 25))]:
        li_lbl = layout.layer(ll, ld)
        for shape in top.shapes(li_lbl).each():
            if shape.is_text():
                tx, ty = shape.text.x, shape.text.y
                if s_left <= tx <= s_right and \
                   pcell_y + strip_bot - 500 <= ty <= pcell_y + strip_top + 1000:
                    print(f"    {lname} '{shape.text.string}' at ({tx/1e3:.3f},{ty/1e3:.3f})")
