#!/usr/bin/env python3
"""Diagnose the 5-net LVS merge: cas3, dac_hi, dac_out, gnd, vdd.

Reads the GDS using klayout.db, extracts metal shapes, merges touching
polygons into connected groups, assigns nets from routing.json, and
finds cross-net shorts.

Run:  source ~/pdk/venv/bin/activate && python diagnose_5net_merge.py
"""

import json
import os
import sys

import klayout.db as kdb

# ── Configuration ──────────────────────────────────────────────────
GDS_PATH = os.path.join(os.path.dirname(__file__), "output", "ptat_vco.gds")
ROUTING_PATH = os.path.join(os.path.dirname(__file__), "output", "routing.json")

MERGED_NETS = {"cas3", "dac_hi", "dac_out", "gnd", "vdd"}

# Layer definitions (layer_num, datatype) -> name
LAYER_DEFS = {
    (8, 0):  "M1",
    (10, 0): "M2",
    (30, 0): "M3",
    (50, 0): "M4",
    (19, 0): "Via1",
    (29, 0): "Via2",
    (49, 0): "Via3",
}

# Routing segment layer mapping
SEG_LAYER_MAP = {
    0: (8, 0),    # M1
    1: (10, 0),   # M2
    2: (30, 0),   # M3
    3: (50, 0),   # M4
}

# Via segment layer mapping: via -> (lower_metal, upper_metal)
VIA_LAYER_MAP = {
    -1: ((8, 0), (10, 0)),    # Via1: M1+M2
    -2: ((10, 0), (30, 0)),   # Via2: M2+M3
    -3: ((30, 0), (50, 0)),   # Via3: M3+M4
}

# Wire widths from pdk.py
M1_SIG_W = 300
M2_SIG_W = 300
M3_MIN_W = 200
M3_PWR_W = 3000
M4_SIG_W = 300

WIRE_W = {
    (8, 0): M1_SIG_W,
    (10, 0): M2_SIG_W,
    (30, 0): M3_MIN_W,
    (50, 0): M4_SIG_W,
}

# Via pad sizes from pdk.py
VIA1_PAD_M1 = 310   # VIA1_GDS_M1
VIA1_PAD_M2 = 480
VIA2_PAD_M2 = 480
VIA2_PAD_M3 = 380   # after DRC tuning (370nm -> 380nm snap)
VIA3_PAD_M3 = 370
VIA3_PAD_M4 = 370
VIA1_SZ = 190
VIA2_SZ = 190
VIA3_SZ = 190


def load_routing():
    with open(ROUTING_PATH) as f:
        return json.load(f)


def seg_to_box(x1, y1, x2, y2, lyr_key, w):
    """Convert a segment (centerline) to a box (x1,y1,x2,y2) with width w."""
    hw = w // 2
    if y1 == y2:  # horizontal
        return (min(x1, x2), y1 - hw, max(x1, x2), y1 + hw)
    elif x1 == x2:  # vertical
        return (x1 - hw, min(y1, y2), x1 + hw, max(y1, y2))
    else:
        # Diagonal — approximate with bounding box expanded by hw
        return (min(x1, x2) - hw, min(y1, y2) - hw,
                max(x1, x2) + hw, max(y1, y2) + hw)


def build_net_shapes_from_routing(routing):
    """Build {layer_key: {net_name: [kdb.Box, ...]}} from routing.json."""
    shapes = {}
    for lk in LAYER_DEFS:
        shapes[lk] = {}

    # Signal routes
    for net_name, route in routing.get("signal_routes", {}).items():
        for seg in route.get("segments", []):
            x1, y1, x2, y2, layer = seg
            if layer >= 0:
                lk = SEG_LAYER_MAP.get(layer)
                if lk:
                    w = WIRE_W.get(lk, 300)
                    box = seg_to_box(x1, y1, x2, y2, lk, w)
                    shapes[lk].setdefault(net_name, []).append(box)
            else:
                # Via: shapes on both metal layers
                via_def = VIA_LAYER_MAP.get(layer)
                if via_def:
                    lk_lo, lk_hi = via_def
                    if layer == -1:
                        hp_lo = VIA1_PAD_M1 // 2
                        hp_hi = VIA1_PAD_M2 // 2
                    elif layer == -2:
                        hp_lo = VIA2_PAD_M2 // 2
                        hp_hi = VIA2_PAD_M3 // 2
                    elif layer == -3:
                        hp_lo = VIA3_PAD_M3 // 2
                        hp_hi = VIA3_PAD_M4 // 2
                    else:
                        continue
                    shapes[lk_lo].setdefault(net_name, []).append(
                        (x1 - hp_lo, y1 - hp_lo, x1 + hp_lo, y1 + hp_lo))
                    shapes[lk_hi].setdefault(net_name, []).append(
                        (x1 - hp_hi, y1 - hp_hi, x1 + hp_hi, y1 + hp_hi))

    # Access points (via pads and stubs)
    for ap_name, ap in routing.get("access_points", {}).items():
        # Determine net from access point name — find in signal_routes
        net_name = None
        for sn, sr in routing.get("signal_routes", {}).items():
            if ap_name in sr.get("pins", []):
                net_name = sn
                break
        if net_name is None:
            # Check power drops
            for drop in routing.get("power", {}).get("drops", []):
                inst_pin = f"{drop['inst']}.{drop['pin']}"
                if inst_pin == ap_name:
                    net_name = drop["net"]
                    break
        if net_name is None:
            continue

        vp = ap.get("via_pad", {})
        for sub_lyr, lk in [("m1", (8, 0)), ("m2", (10, 0))]:
            coords = vp.get(sub_lyr)
            if coords and len(coords) == 4:
                shapes[lk].setdefault(net_name, []).append(tuple(coords))
        # M1 stub
        m1_stub = ap.get("m1_stub")
        if m1_stub and len(m1_stub) == 4:
            shapes[(8, 0)].setdefault(net_name, []).append(tuple(m1_stub))
        # M2 stub
        m2_stub = ap.get("m2_stub")
        if m2_stub and len(m2_stub) == 4:
            shapes[(10, 0)].setdefault(net_name, []).append(tuple(m2_stub))

    # Power rails (M3)
    for rail_id, rail in routing.get("power", {}).get("rails", {}).items():
        net = rail.get("net", rail_id)
        rhw = rail["width"] // 2
        shapes[(30, 0)].setdefault(net, []).append(
            (rail["x1"], rail["y"] - rhw, rail["x2"], rail["y"] + rhw))

    # Power drops
    for drop in routing.get("power", {}).get("drops", []):
        net = drop["net"]
        # M3 vbar
        vbar = drop.get("m3_vbar")
        if vbar:
            vhw = M3_MIN_W // 2
            vy1 = min(vbar[1], vbar[3])
            vy2 = max(vbar[1], vbar[3])
            shapes[(30, 0)].setdefault(net, []).append(
                (vbar[0] - vhw, vy1, vbar[0] + vhw, vy2))
        # Via2 M3 pad
        v2p = drop.get("via2_pos")
        if v2p:
            hp = VIA2_PAD_M3 // 2
            shapes[(30, 0)].setdefault(net, []).append(
                (v2p[0] - hp, v2p[1] - hp, v2p[0] + hp, v2p[1] + hp))
            # Via2 M2 pad
            hp2 = VIA2_PAD_M2 // 2
            shapes[(10, 0)].setdefault(net, []).append(
                (v2p[0] - hp2, v2p[1] - hp2, v2p[0] + hp2, v2p[1] + hp2))
        # M2 vbar
        m2v = drop.get("m2_vbar")
        if m2v:
            vhw = M2_SIG_W // 2
            shapes[(10, 0)].setdefault(net, []).append(
                (m2v[0] - vhw, min(m2v[1], m2v[3]),
                 m2v[0] + vhw, max(m2v[1], m2v[3])))
        # Via1 pad
        v1p = drop.get("via1_pos")
        if v1p:
            hp_m1 = VIA1_PAD_M1 // 2
            hp_m2 = VIA1_PAD_M2 // 2
            shapes[(8, 0)].setdefault(net, []).append(
                (v1p[0] - hp_m1, v1p[1] - hp_m1,
                 v1p[0] + hp_m1, v1p[1] + hp_m1))
            shapes[(10, 0)].setdefault(net, []).append(
                (v1p[0] - hp_m2, v1p[1] - hp_m2,
                 v1p[0] + hp_m2, v1p[1] + hp_m2))

    return shapes


def boxes_overlap(a, b):
    """Check if two (x1,y1,x2,y2) boxes overlap or touch."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def find_shorts_on_layer(gds_region, net_boxes, layer_name):
    """Find cross-net shorts on a single layer.

    Strategy:
    1. Merge all GDS shapes into connected groups
    2. For each merged polygon, check which nets have routing shapes inside it
    3. If multiple nets -> short
    """
    shorts = []

    # Merge GDS shapes (0 = merge touching/overlapping)
    merged = gds_region.merged()

    if merged.is_empty():
        return shorts

    # For each merged polygon, find which routing nets overlap
    for mpoly in merged.each():
        mp_box = mpoly.bbox()
        mp_region = kdb.Region(mpoly)

        # Find which nets have shapes overlapping this merged polygon
        net_hits = {}  # net_name -> [(box, overlap_region)]
        for net_name, boxes in net_boxes.items():
            for box in boxes:
                b = kdb.Box(int(box[0]), int(box[1]), int(box[2]), int(box[3]))
                # Quick bbox check
                if not mp_box.overlaps(b) and not mp_box.touches(b):
                    continue
                # Precise overlap check
                b_region = kdb.Region(b)
                overlap = mp_region & b_region
                if not overlap.is_empty():
                    net_hits.setdefault(net_name, []).append(
                        (box, overlap.bbox()))

        # Filter to only the 5 merged nets for this investigation
        relevant_nets = {n for n in net_hits if n in MERGED_NETS}
        if len(relevant_nets) >= 2:
            shorts.append({
                "layer": layer_name,
                "merged_bbox": (mp_box.left, mp_box.bottom,
                                mp_box.right, mp_box.top),
                "nets": {n: [(b, (ob.left, ob.bottom, ob.right, ob.top))
                             for b, ob in net_hits[n]]
                         for n in relevant_nets},
                "all_nets_in_group": set(net_hits.keys()),
            })

    return shorts


def main():
    print("=" * 70)
    print("5-NET MERGE DIAGNOSTIC: cas3, dac_hi, dac_out, gnd, vdd")
    print("=" * 70)

    # Load data
    print("\nLoading routing.json...")
    routing = load_routing()

    print("Building net shapes from routing data...")
    net_shapes = build_net_shapes_from_routing(routing)

    print("Loading GDS...")
    # Keep layout alive in main scope to prevent Region invalidation
    layout = kdb.Layout()
    layout.read(GDS_PATH)
    top = layout.top_cell()
    if top is None:
        raise RuntimeError("No top cell in GDS")
    top.flatten(True)

    gds_regions = {}
    for lk in LAYER_DEFS:
        li = layout.layer(lk[0], lk[1])
        r = kdb.Region(top.begin_shapes_rec(li))
        gds_regions[lk] = r
        print(f"  {LAYER_DEFS[lk]}: {r.count()} shapes")

    # Analyze each layer
    all_shorts = []
    for lk, layer_name in LAYER_DEFS.items():
        region = gds_regions[lk]
        net_boxes = net_shapes.get(lk, {})

        n_polys = region.count()
        n_nets = len(net_boxes)
        print(f"\n--- {layer_name} ({lk[0]},{lk[1]}): "
              f"{n_polys} GDS shapes, {n_nets} routing nets ---")

        if n_polys == 0 or n_nets == 0:
            print("  (skipping - no shapes or no routing data)")
            continue

        # Only check layers that have shapes from our 5 nets
        relevant_net_count = sum(1 for n in net_boxes if n in MERGED_NETS)
        if relevant_net_count == 0:
            print(f"  (skipping - no shapes from merged nets)")
            continue

        print(f"  Nets with shapes on this layer from merged set: "
              f"{[n for n in net_boxes if n in MERGED_NETS]}")

        shorts = find_shorts_on_layer(region, net_boxes, layer_name)
        all_shorts.extend(shorts)

        if shorts:
            print(f"  *** FOUND {len(shorts)} CROSS-NET SHORT(S) ***")
        else:
            print(f"  No cross-net shorts found")

    # Report
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    if not all_shorts:
        print("\nNo cross-net shorts found between the 5 merged nets.")
        print("The merge may be caused by:")
        print("  - FEOL shorts (Cont/Activ/GatPoly level)")
        print("  - Shapes added during assembly not tracked in routing.json")
        print("  - Same-net gap fills creating bridges")
        return

    for i, short in enumerate(all_shorts):
        print(f"\n--- SHORT #{i+1} on {short['layer']} ---")
        bbox = short["merged_bbox"]
        print(f"  Merged polygon bbox: ({bbox[0]}, {bbox[1]}) - ({bbox[2]}, {bbox[3]})")
        print(f"  Bbox in um: ({bbox[0]/1000:.3f}, {bbox[1]/1000:.3f}) - "
              f"({bbox[2]/1000:.3f}, {bbox[3]/1000:.3f})")
        print(f"  Nets in merged group (from 5-net set): "
              f"{sorted(short['nets'].keys())}")
        all_nets = short.get("all_nets_in_group", set())
        other_nets = all_nets - MERGED_NETS
        if other_nets:
            print(f"  Other nets also in this group: {sorted(other_nets)}")

        # Show overlap details for each net
        for net_name in sorted(short["nets"].keys()):
            hits = short["nets"][net_name]
            print(f"  {net_name}: {len(hits)} shape(s) overlap")
            for box, ob in hits[:5]:  # limit output
                print(f"    routing box: ({box[0]}, {box[1]}) - ({box[2]}, {box[3]})")
                print(f"      overlap at: ({ob[0]}, {ob[1]}) - ({ob[2]}, {ob[3]})")
                cx = (ob[0] + ob[2]) // 2
                cy = (ob[1] + ob[3]) // 2
                print(f"      center: ({cx/1000:.3f}, {cy/1000:.3f}) um")

    # Identify bridge points
    print("\n" + "=" * 70)
    print("BRIDGE POINT ANALYSIS")
    print("=" * 70)

    for i, short in enumerate(all_shorts):
        nets_list = sorted(short["nets"].keys())
        if len(nets_list) < 2:
            continue
        print(f"\nShort #{i+1} on {short['layer']}:")
        # For each pair of nets, find where their shapes are closest
        # within the merged polygon
        for ni in range(len(nets_list)):
            for nj in range(ni + 1, len(nets_list)):
                n1, n2 = nets_list[ni], nets_list[nj]
                hits1 = short["nets"][n1]
                hits2 = short["nets"][n2]
                min_dist = float("inf")
                best_pair = None
                for box1, ob1 in hits1:
                    for box2, ob2 in hits2:
                        # Check if the routing boxes themselves overlap
                        if boxes_overlap(box1, box2):
                            print(f"  DIRECT OVERLAP: {n1} and {n2}")
                            print(f"    {n1} box: ({box1[0]}, {box1[1]}) - "
                                  f"({box1[2]}, {box1[3]})")
                            print(f"    {n2} box: ({box2[0]}, {box2[1]}) - "
                                  f"({box2[2]}, {box2[3]})")
                            ox1 = max(box1[0], box2[0])
                            oy1 = max(box1[1], box2[1])
                            ox2 = min(box1[2], box2[2])
                            oy2 = min(box1[3], box2[3])
                            print(f"    Overlap region: ({ox1}, {oy1}) - "
                                  f"({ox2}, {oy2})")
                            cx = (ox1 + ox2) / 2000
                            cy = (oy1 + oy2) / 2000
                            print(f"    Center: ({cx:.3f}, {cy:.3f}) um")
                            min_dist = 0
                            best_pair = (box1, box2)
                        else:
                            # Compute min distance between boxes
                            dx = max(0, max(box1[0] - box2[2],
                                            box2[0] - box1[2]))
                            dy = max(0, max(box1[1] - box2[3],
                                            box2[1] - box1[3]))
                            d = (dx**2 + dy**2)**0.5
                            if d < min_dist:
                                min_dist = d
                                best_pair = (box1, box2)

                if min_dist > 0 and best_pair:
                    print(f"  BRIDGE via GDS: {n1} <-> {n2}, "
                          f"routing gap = {min_dist:.0f}nm")
                    b1, b2 = best_pair
                    print(f"    {n1} nearest box: ({b1[0]}, {b1[1]}) - "
                          f"({b1[2]}, {b1[3]})")
                    print(f"    {n2} nearest box: ({b2[0]}, {b2[1]}) - "
                          f"({b2[2]}, {b2[3]})")
                    print(f"    Bridge likely from assembly-added shapes "
                          f"(gap fills, tie geometry, pcell internal metal)")


if __name__ == "__main__":
    main()
