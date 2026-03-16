#!/usr/bin/env python3
"""Find exactly which M3 raw shapes exist in the gap between each Via2 pad
and the adjacent cross-net rail.

For each of the 5 known bridge locations, check what M3 raw shapes fill
the 240nm gap that should separate the Via2 M3 pad from the rail.

Run:
  cd layout && source ~/pdk/venv/bin/activate && python3 diagnose_gap_shapes.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

GDS = 'output/ptat_vco.gds'
layout = kdb.Layout()
layout.read(GDS)
top = layout.top_cell()

li_m3 = layout.layer(30, 0)

m3_raw = kdb.Region(top.begin_shapes_rec(li_m3))

# Known bridge Via2 positions (from diagnose_bridge_gds.py):
# Each tuple: (via2_x, via2_y, label)
# These are the Via2 positions that connect to cross-net M3
bridge_via2 = [
    # Bias area bridges (gnd_bias rail y=144500-147500)
    (48160, 144070, "bias_lo_1"),  # GND M3 side
    (48160, 147930, "bias_hi_1"),  # VDD M3 side
    (49510, 144070, "bias_lo_2"),
    (49510, 147930, "bias_hi_2"),
    # VCO area bridges (vdd_vco rail y=176120-179120)
    (83830, 175690, "vco_lo_1"),   # GND M3 side
    (83830, 179550, "vco_hi_1"),   # VDD M3 side
    (80750, 175690, "vco_lo_2"),
    (80750, 179550, "vco_hi_2"),
    (81230, 175690, "vco_lo_3"),
    (81230, 179550, "vco_hi_3"),
]

# Rail edges for gap definition
# gnd_bias: y=146000, width=3000 → edges 144500-147500
# vdd_vco: y=177620, width=3000 → edges 176120-179120
rail_edges = {
    "bias": (144500, 147500, "gnd_bias"),
    "vco":  (176120, 179120, "vdd_vco"),
}

VIA2_PAD_M3 = 380
hp = VIA2_PAD_M3 // 2  # 190

for vx, vy, label in bridge_via2:
    area_key = label.split("_")[0]  # "bias" or "vco"
    rail_bot, rail_top, rail_name = rail_edges[area_key]

    pad_bot = vy - hp
    pad_top = vy + hp

    # Determine the gap between Via2 pad and nearest rail edge
    if "lo" in label:
        # Via2 below rail → gap is from pad_top to rail_bot
        gap_bot = pad_top
        gap_top = rail_bot
    else:
        # Via2 above rail → gap is from rail_top to pad_bot
        gap_bot = rail_top
        gap_top = pad_bot

    if gap_top <= gap_bot:
        print(f"\n{label}: Via2 pad overlaps rail! No gap.")
        continue

    gap = gap_top - gap_bot
    print(f"\n{'='*70}")
    print(f"{label}: Via2 at ({vx/1e3:.3f},{vy/1e3:.3f}), "
          f"pad [{pad_bot/1e3:.3f},{pad_top/1e3:.3f}]")
    print(f"  Rail {rail_name} [{rail_bot/1e3:.3f},{rail_top/1e3:.3f}]")
    print(f"  GAP: [{gap_bot/1e3:.3f},{gap_top/1e3:.3f}] = {gap}nm")

    # Find ALL M3 raw shapes that overlap with an expanded gap region
    # Search ±1µm in X around the via2 position, and the gap + 500nm above/below
    search_x1 = vx - 1000
    search_x2 = vx + 1000
    search_y1 = gap_bot - 500
    search_y2 = gap_top + 500

    search_region = kdb.Region(kdb.Box(search_x1, search_y1, search_x2, search_y2))
    m3_in_gap = m3_raw & search_region

    shapes = []
    for poly in m3_in_gap.each():
        bb = poly.bbox()
        shapes.append((bb.left, bb.bottom, bb.right, bb.top,
                       bb.right - bb.left, bb.top - bb.bottom))
    shapes.sort(key=lambda s: (s[1], s[0]))

    in_gap_count = 0
    print(f"  M3 raw shapes in search region ({search_x1/1e3:.1f},{search_y1/1e3:.1f})-"
          f"({search_x2/1e3:.1f},{search_y2/1e3:.1f}):")
    for xl, yb, xr, yt, w, h in shapes:
        # Check if shape enters the gap
        enters_gap = (yt > gap_bot and yb < gap_top)
        marker = " *** IN GAP ***" if enters_gap else ""
        if enters_gap:
            in_gap_count += 1
        # Classify shape
        if w > 50000:
            kind = "RAIL"
        elif w == 200 and h > 1000:
            kind = "vbar"
        elif w == 380 and h == 380:
            kind = "via2pad"
        elif h == 380 and w > 400:
            kind = "jog"
        elif w < 400 and h < 400:
            kind = "fill?"
        else:
            kind = f"{w}x{h}"
        print(f"    ({xl/1e3:.3f},{yb/1e3:.3f})-({xr/1e3:.3f},{yt/1e3:.3f})  "
              f"{w}x{h}nm  {kind}{marker}")

    if in_gap_count == 0:
        print(f"  No M3 shapes in the {gap}nm gap! Bridge not through M3 gap-fill.")
    else:
        print(f"  {in_gap_count} shapes enter the gap.")

    # Check: does the merged M3 polygon at the Via2 pad extend into the gap?
    m3_merged = kdb.Region(top.begin_shapes_rec(li_m3)).merged()
    pad_probe = kdb.Region(kdb.Box(vx - 50, vy - 50, vx + 50, vy + 50))
    for mpoly in m3_merged.each():
        mr = kdb.Region(mpoly)
        if not (mr & pad_probe).is_empty():
            mb = mpoly.bbox()
            area = mpoly.area() / 1e6
            print(f"  MERGED M3 containing this Via2: ({mb.left/1e3:.3f},{mb.bottom/1e3:.3f})-"
                  f"({mb.right/1e3:.3f},{mb.top/1e3:.3f}) area={area:.1f}µm²")
            # Does this merged polygon also overlap with the rail?
            rail_probe = kdb.Region(kdb.Box(vx - 200, rail_bot + 100,
                                           vx + 200, rail_top - 100))
            if not (mr & rail_probe).is_empty():
                print(f"  *** MERGED polygon ALSO overlaps rail → BRIDGE CONFIRMED ***")
            break

print("\n\nDONE.")
