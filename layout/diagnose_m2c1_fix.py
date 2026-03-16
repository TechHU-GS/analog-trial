#!/usr/bin/env python3
"""Diagnose M2.c1/V2.c1 violations and compute fix options.

For each violation:
1. Find Via1/Via2 at the violation location
2. Identify which AP and net it belongs to
3. Find all cross-net M2 wires nearby
4. Compute the MAXIMUM M2 pad that satisfies M2.b (210nm spacing)
5. Check if that pad provides 50nm endcap (M2.c1/V2.c1)
6. If not, find nearby same-net M2 shapes that could be extended
7. Report fix strategy per violation

Run: cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_m2c1_fix.py
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# DRC constants
M2_MIN_S = 210   # M2.b spacing
M2_MIN_W = 200   # M2.a width
V1_ENDCAP = 50   # V1.c1 / M2.c1
V2_ENDCAP = 50   # V2.c1
VIA1_SZ = 190    # Via1 size
VIA2_SZ = 190    # Via2 size

layout = kdb.Layout()
layout.read('output/ptat_vco.gds')
top = layout.top_cell()

li_m1 = layout.layer(8, 0)
li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)
li_v2 = layout.layer(29, 0)
li_m3 = layout.layer(30, 0)

with open('output/routing.json') as f:
    routing = json.load(f)

# Build AP index: via1 position → (key, net, ap_data)
ap_index = {}
pin_net = {}
for key, ap in routing.get('access_points', {}).items():
    inst, pin = key.rsplit('.', 1)
    # Find net for this pin
    for net, pins in routing.get('netlist', {}).items():
        if key in pins:
            pin_net[key] = net
            break
    vp = ap.get('via_pad', {})
    if 'via1' in vp:
        v1 = tuple(vp['via1'])
        ap_index[v1] = (key, pin_net.get(key, '?'), ap)

# Build M2 wire index from signal routes (with net)
m2_wires = []  # (x1,y1,x2,y2,net)
for net, rd in routing.get('signal_routes', {}).items():
    for seg in rd.get('segments', []):
        if len(seg) >= 5 and seg[4] == 'm2':
            m2_wires.append((seg[0], seg[1], seg[2], seg[3], net))

# Collect ALL M2 shapes from GDS with approximate net info
all_m2 = []
for si in top.shapes(li_m2).each():
    bb = si.bbox()
    all_m2.append(bb)

# Known M2.c1/V2.c1 violation locations (from R21 DRC lyrdb)
# Approximate centers from previous diagnostic
VIOLS = [
    ('M2.c1', 'Via1', li_v1, 197900, 171630),
    ('M2.c1', 'Via1', li_v1, 67230, 240000),
    ('M2.c1', 'Via1', li_v1, 149470, 72000),
    ('V2.c1', 'Via2', li_v2, 197900, 171630),
]

def find_shapes(layer_idx, cx, cy, radius=500):
    """Find all shapes on layer near (cx, cy)."""
    probe = kdb.Box(cx - radius, cy - radius, cx + radius, cy + radius)
    results = []
    for si in top.shapes(layer_idx).each():
        bb = si.bbox()
        if probe.overlaps(bb):
            results.append(('TOP', bb))
    for inst in top.each_inst():
        cell = inst.cell
        for si in cell.shapes(layer_idx).each():
            bb = si.bbox().transformed(inst.trans)
            if probe.overlaps(bb):
                results.append((cell.name, bb))
    return results

def box_gap(bb1, bb2):
    """Return (x_gap, y_gap) between two boxes. Negative = overlap."""
    x_gap = max(bb1.left - bb2.right, bb2.left - bb1.right)
    y_gap = max(bb1.bottom - bb2.top, bb2.bottom - bb1.top)
    return x_gap, y_gap

for rule, via_name, via_li, cx, cy in VIOLS:
    print(f"\n{'='*80}")
    print(f"{rule}: {via_name} at ~({cx},{cy})")
    print(f"{'='*80}")

    # Find the via
    vias = find_shapes(via_li, cx, cy, 300)
    if not vias:
        print("  NO VIA FOUND!")
        continue
    via_src, via_bb = vias[0]
    via_cx = (via_bb.left + via_bb.right) // 2
    via_cy = (via_bb.bottom + via_bb.top) // 2
    print(f"\n  {via_name}: ({via_bb.left},{via_bb.bottom};{via_bb.right},{via_bb.top}) "
          f"center=({via_cx},{via_cy}) [{via_src}]")

    # Match to AP
    matched_ap = None
    matched_net = None
    for v1_pos, (ap_key, net, ap_data) in ap_index.items():
        v1_cx = (v1_pos[0] + v1_pos[2]) // 2
        v1_cy = (v1_pos[1] + v1_pos[3]) // 2
        if abs(v1_cx - via_cx) < 50 and abs(v1_cy - via_cy) < 50:
            matched_ap = ap_key
            matched_net = net
            print(f"  AP: {ap_key}  Net: {net}")
            break
    if not matched_ap:
        print("  NO MATCHING AP FOUND")

    # Find ALL M2 shapes nearby
    m2_shapes = find_shapes(li_m2, via_cx, via_cy, 2000)
    print(f"\n  M2 shapes within 2µm ({len(m2_shapes)}):")
    for src, bb in m2_shapes:
        x_gap, y_gap = box_gap(via_bb, bb)
        # Check if via is enclosed
        enc_l = via_bb.left - bb.left
        enc_r = bb.right - via_bb.right
        enc_b = via_bb.bottom - bb.bottom
        enc_t = bb.top - via_bb.top
        is_enclosed = (enc_l >= 0 and enc_r >= 0 and enc_b >= 0 and enc_t >= 0)
        min_endcap = min(enc_b, enc_t) if is_enclosed else -1
        min_side = min(enc_l, enc_r) if is_enclosed else -1

        # Identify net: check if this M2 is a routing wire for a specific net
        wire_net = '?'
        for wx1, wy1, wx2, wy2, wnet in m2_wires:
            if (abs(bb.left - wx1) < 10 and abs(bb.bottom - wy1) < 10 and
                abs(bb.right - wx2) < 10 and abs(bb.top - wy2) < 10):
                wire_net = wnet
                break

        marker = ""
        if is_enclosed:
            if min_endcap < V1_ENDCAP:
                marker = f" ← ENDCAP={min_endcap}nm (need 50)"
            else:
                marker = f" ✓ endcap OK ({min_endcap}nm)"
        else:
            dist = max(x_gap, y_gap)
            if x_gap > 0 and y_gap > 0:
                import math
                dist = math.sqrt(x_gap**2 + y_gap**2)
            elif x_gap > 0:
                dist = x_gap
            else:
                dist = y_gap
            marker = f" gap={dist:.0f}nm"
            if wire_net == matched_net:
                marker += " [SAME NET]"
            elif wire_net != '?':
                marker += f" [{wire_net}]"

        print(f"    [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
              f"{bb.width()}x{bb.height()} net={wire_net}{marker}")

    # Compute maximum M2 pad that satisfies M2.b to ALL cross-net wires
    print(f"\n  === Fix analysis ===")
    # Start with ideal endcap pad
    ideal = [via_bb.left - V1_ENDCAP, via_bb.bottom - V1_ENDCAP,
             via_bb.right + V1_ENDCAP, via_bb.top + V1_ENDCAP]
    print(f"  Ideal endcap pad: ({ideal[0]},{ideal[1]};{ideal[2]},{ideal[3]}) "
          f"{ideal[2]-ideal[0]}x{ideal[3]-ideal[1]}")

    # Find cross-net M2 wires that constrain the pad
    constraints = []  # (direction, max_coord, wire_desc)
    for src, bb in m2_shapes:
        # Identify wire net
        wire_net = '?'
        for wx1, wy1, wx2, wy2, wnet in m2_wires:
            if (abs(bb.left - wx1) < 10 and abs(bb.bottom - wy1) < 10 and
                abs(bb.right - wx2) < 10 and abs(bb.top - wy2) < 10):
                wire_net = wnet
                break
        if wire_net == matched_net or wire_net == '?':
            # Skip same-net and unidentified shapes
            # But check if unidentified overlaps via
            if wire_net == '?':
                enc_l = via_bb.left - bb.left
                enc_r = bb.right - via_bb.right
                enc_b = via_bb.bottom - bb.bottom
                enc_t = bb.top - via_bb.top
                if enc_l >= 0 and enc_r >= 0 and enc_b >= 0 and enc_t >= 0:
                    # This M2 encloses the via — it's same-net
                    continue
            else:
                continue

        # This is cross-net — compute spacing constraint on each pad edge
        # Pad right edge must be ≤ wire.left - M2_MIN_S
        if bb.bottom < ideal[3] and bb.top > ideal[1]:  # Y overlap with pad
            if bb.left > via_cx:  # Wire is to the right
                max_r = bb.left - M2_MIN_S
                if max_r < ideal[2]:
                    constraints.append(('right', max_r,
                        f"({bb.left},{bb.bottom};{bb.right},{bb.top}) {wire_net}"))
            if bb.right < via_cx:  # Wire is to the left
                min_l = bb.right + M2_MIN_S
                if min_l > ideal[0]:
                    constraints.append(('left', min_l,
                        f"({bb.left},{bb.bottom};{bb.right},{bb.top}) {wire_net}"))
        if bb.left < ideal[2] and bb.right > ideal[0]:  # X overlap with pad
            if bb.bottom > via_cy:  # Wire is above
                max_t = bb.bottom - M2_MIN_S
                if max_t < ideal[3]:
                    constraints.append(('top', max_t,
                        f"({bb.left},{bb.bottom};{bb.right},{bb.top}) {wire_net}"))
            if bb.top < via_cy:  # Wire is below
                min_b = bb.top + M2_MIN_S
                if min_b > ideal[1]:
                    constraints.append(('bottom', min_b,
                        f"({bb.left},{bb.bottom};{bb.right},{bb.top}) {wire_net}"))

    if constraints:
        print(f"\n  Cross-net constraints:")
        for direction, coord, desc in constraints:
            print(f"    {direction}: max={coord} (from {desc})")

    # Apply constraints
    clipped = list(ideal)
    for direction, coord, _ in constraints:
        if direction == 'right':
            clipped[2] = min(clipped[2], coord)
        elif direction == 'left':
            clipped[0] = max(clipped[0], coord)
        elif direction == 'top':
            clipped[3] = min(clipped[3], coord)
        elif direction == 'bottom':
            clipped[1] = max(clipped[1], coord)

    enc_l = via_bb.left - clipped[0]
    enc_r = clipped[2] - via_bb.right
    enc_b = via_bb.bottom - clipped[1]
    enc_t = clipped[3] - via_bb.top
    print(f"\n  Spacing-safe pad: ({clipped[0]},{clipped[1]};{clipped[2]},{clipped[3]}) "
          f"{clipped[2]-clipped[0]}x{clipped[3]-clipped[1]}")
    print(f"  Endcaps: L={enc_l} R={enc_r} B={enc_b} T={enc_t}")
    for d, v in [('L', enc_l), ('R', enc_r), ('B', enc_b), ('T', enc_t)]:
        if v < V1_ENDCAP:
            print(f"    *** {d} endcap violation: {v}nm < {V1_ENDCAP}nm (need +{V1_ENDCAP-v}nm)")

    # Check if any EXISTING same-net M2 shape provides partial/full endcap
    print(f"\n  Existing same-net M2 coverage:")
    any_cover = False
    for src, bb in m2_shapes:
        # Check if this shape overlaps the via
        if (bb.right > via_bb.left and bb.left < via_bb.right and
            bb.top > via_bb.bottom and bb.bottom < via_bb.top):
            el = via_bb.left - bb.left
            er = bb.right - via_bb.right
            eb = via_bb.bottom - bb.bottom
            et = bb.top - via_bb.top
            print(f"    [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}): "
                  f"L={el} R={er} B={eb} T={et}")
            any_cover = True
    if not any_cover:
        print(f"    NONE — via has zero M2 coverage")

    # Check nearby same-net M2 shapes that could be EXTENDED to cover
    print(f"\n  Same-net M2 shapes that could be extended to cover via:")
    for src, bb in m2_shapes:
        wire_net = '?'
        for wx1, wy1, wx2, wy2, wnet in m2_wires:
            if (abs(bb.left - wx1) < 10 and abs(bb.bottom - wy1) < 10 and
                abs(bb.right - wx2) < 10 and abs(bb.top - wy2) < 10):
                wire_net = wnet
                break
        if wire_net != matched_net and wire_net != '?':
            continue

        x_gap = max(via_bb.left - bb.right, bb.left - via_bb.right)
        y_gap = max(via_bb.bottom - bb.top, bb.bottom - via_bb.top)
        if x_gap > 500 or y_gap > 500:
            continue

        # Check if extending this shape could enclose the via
        # Extension needed in each direction
        needs = {}
        # To fully enclose via with endcap:
        need_l = via_bb.left - V1_ENDCAP  # pad must reach here
        need_r = via_bb.right + V1_ENDCAP
        need_b = via_bb.bottom - V1_ENDCAP
        need_t = via_bb.top + V1_ENDCAP

        ext_l = max(0, need_l - bb.left) if bb.left > need_l else 0
        ext_r = max(0, need_r - bb.right) if bb.right < need_r else 0
        ext_b = max(0, need_b - bb.bottom) if bb.bottom > need_b else 0
        ext_t = max(0, need_t - bb.top) if bb.top < need_t else 0

        # But also check that shape Y range covers via (for horizontal bars)
        if bb.top < via_bb.bottom or bb.bottom > via_bb.top:
            # Shape doesn't vertically overlap via — need to extend vertically
            if bb.top < via_bb.bottom:
                ext_t = need_t - bb.top
            else:
                ext_b = bb.bottom - need_b

        # Total extension
        total_ext = ext_l + ext_r + ext_b + ext_t
        if total_ext > 0 and total_ext < 2000:
            which_extend = []
            if ext_l: which_extend.append(f"left {ext_l}nm" if ext_l > 0 else "")
            if ext_r: which_extend.append(f"right {ext_r}nm")
            if ext_b: which_extend.append(f"down {ext_b}nm")
            if ext_t: which_extend.append(f"up {ext_t}nm")
            which_extend = [w for w in which_extend if w]
            print(f"    [{src}] ({bb.left},{bb.bottom};{bb.right},{bb.top}) "
                  f"{bb.width()}x{bb.height()} net={wire_net}: "
                  f"extend {', '.join(which_extend)}")

print("\n\nDone.")
