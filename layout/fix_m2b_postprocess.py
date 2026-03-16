#!/usr/bin/env python3
"""Post-assembly M2.b fix: surgically trim Via1 M2 pads at violation sites.

Strict version:
- All coordinates grid-snapped (5nm)
- Self-check BEFORE writing: OffGrid, M2.a, M2.d
- Only single-pad local shrink, no topology changes
- Conservative: pad width/height stays ≥ 400nm

Run AFTER assemble_gds.py, BEFORE DRC:
  klayout -n sg13g2 -zz -r fix_m2b_postprocess.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__ if '__file__' in dir() else '.')))
os.chdir(os.path.dirname(os.path.abspath(__file__ if '__file__' in dir() else '.')))

import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'
GDS_OUT = 'output/ptat_vco.gds'

# DRC constants (nm)
M2_MIN_S = 210
M2_MIN_W = 200
M2_MIN_AREA = 144000   # 0.144 µm²
VIA1_SZ = 190
V1_SIDE_ENC = 30
V1_END_ENC  = 50
VIA1_PAD = 480
GRID = 5

# Conservative limit: don't shrink pad below this
MIN_PAD_DIM = 400      # well above M2.a=200nm, prevents merged-shape M2.a issues
# Max trim per side = (480 - 400) / 2 if trimming both sides on one axis,
# or (480 - 400) = 80 if trimming one side only.
MAX_TRIM_ONE_SIDE = VIA1_PAD - MIN_PAD_DIM  # 80nm


def s5(x):
    """Snap down to 5nm grid."""
    return (x // GRID) * GRID


layout = kdb.Layout()
layout.read(GDS_IN)
top = layout.top_cell()

li_m2 = layout.layer(10, 0)
li_v1 = layout.layer(19, 0)

print("=== M2.b Post-Processing Fix (strict) ===\n")

# --- Baseline self-check ---
m2_base = kdb.Region(top.begin_shapes_rec(li_m2)).merged()
base_space = m2_base.space_check(M2_MIN_S).count()
base_width = m2_base.width_check(M2_MIN_W).count()
print(f"Baseline self-check: M2.b={base_space}, M2.a={base_width}")

# Step 1: Via1 positions
via1_positions = set()
for si in top.begin_shapes_rec(li_v1):
    box = si.shape().bbox().transformed(si.trans())
    cx = (box.left + box.right) // 2
    cy = (box.top + box.bottom) // 2
    via1_positions.add((cx, cy))
print(f"Via1 positions: {len(via1_positions)}")

# Step 2: Find M2.b violations
violations = m2_base.space_check(M2_MIN_S)
print(f"M2.b violations to fix: {violations.count()}")

if violations.count() == 0:
    print("Nothing to fix!")
    sys.exit(0)

# Step 3: For each violation, find nearby via pads and compute trim
# Collect violation edge info
viol_edges = []
for ep in violations.each():
    e1, e2 = ep.first, ep.second
    e1_mx = (e1.p1.x + e1.p2.x) // 2
    e1_my = (e1.p1.y + e1.p2.y) // 2
    e2_mx = (e2.p1.x + e2.p2.x) // 2
    e2_my = (e2.p1.y + e2.p2.y) // 2
    # Edge orientation
    e1_is_h = abs(e1.p2.x - e1.p1.x) > abs(e1.p2.y - e1.p1.y)
    e2_is_h = abs(e2.p2.x - e2.p1.x) > abs(e2.p2.y - e2.p1.y)
    viol_edges.append((e1_mx, e1_my, e1_is_h, e2_mx, e2_my, e2_is_h))

# Build pad map: via_pos → shape iterator reference
# We need to enumerate shapes and track which are via pads
pad_info = {}   # via_pos → original Box
shape_list = [] # all top-level M2 shapes for later modification
for si in top.each_shape(li_m2):
    box = si.bbox()
    w, h = box.width(), box.height()
    cx = (box.left + box.right) // 2
    cy = (box.top + box.bottom) // 2
    for vx, vy in via1_positions:
        if abs(cx - vx) <= 10 and abs(cy - vy) <= 10:
            if w >= MIN_PAD_DIM and h >= MIN_PAD_DIM:
                pad_info[(vx, vy)] = box
            break

print(f"Trimmable pads: {len(pad_info)}")

# Compute trims for each pad
trims = {}  # via_pos → [left, right, bottom, top] (all grid-snapped, all ≥ 0)

search_r = VIA1_PAD // 2 + 50  # 290nm

for e1_mx, e1_my, e1_is_h, e2_mx, e2_my, e2_is_h in viol_edges:
    # Compute gap
    if e1_is_h and e2_is_h:
        gap = abs(e1_my - e2_my)
    elif not e1_is_h and not e2_is_h:
        gap = abs(e1_mx - e2_mx)
    else:
        gap = max(abs(e1_mx - e2_mx), abs(e1_my - e2_my))

    shortfall = M2_MIN_S - gap + GRID  # 5nm safety
    if shortfall <= 0:
        continue

    # Find pads near each edge
    for vpos, pbox in pad_info.items():
        vx, vy = vpos
        pcx = (pbox.left + pbox.right) // 2
        pcy = (pbox.top + pbox.bottom) // 2

        near_e1 = abs(pcx - e1_mx) <= search_r and abs(pcy - e1_my) <= search_r
        near_e2 = abs(pcx - e2_mx) <= search_r and abs(pcy - e2_my) <= search_r

        if not near_e1 and not near_e2:
            continue

        if vpos not in trims:
            trims[vpos] = [0, 0, 0, 0]

        trim_amt = s5(min(shortfall, MAX_TRIM_ONE_SIDE))

        # Determine side: edge position relative to pad center
        for emx, emy, e_is_h, is_near in [
            (e1_mx, e1_my, e1_is_h, near_e1),
            (e2_mx, e2_my, e2_is_h, near_e2),
        ]:
            if not is_near:
                continue
            if e_is_h:
                # Horizontal edge → gap is vertical → trim top or bottom
                if emy > pcy:
                    trims[vpos][3] = max(trims[vpos][3], trim_amt)  # top
                else:
                    trims[vpos][2] = max(trims[vpos][2], trim_amt)  # bottom
            else:
                # Vertical edge → gap is horizontal → trim left or right
                if emx > pcx:
                    trims[vpos][1] = max(trims[vpos][1], trim_amt)  # right
                else:
                    trims[vpos][0] = max(trims[vpos][0], trim_amt)  # left

# Step 4: Enforce constraints and clamp trims
for vpos in trims:
    lt, rt, bt, tt = trims[vpos]
    pbox = pad_info[vpos]
    orig_w = pbox.width()
    orig_h = pbox.height()

    # Clamp so pad stays ≥ MIN_PAD_DIM in both dimensions
    max_h_trim = orig_w - MIN_PAD_DIM
    if lt + rt > max_h_trim:
        # Scale down proportionally
        total = lt + rt
        lt = s5(lt * max_h_trim // total)
        rt = s5(rt * max_h_trim // total)

    max_v_trim = orig_h - MIN_PAD_DIM
    if bt + tt > max_v_trim:
        total = bt + tt
        bt = s5(bt * max_v_trim // total)
        tt = s5(tt * max_v_trim // total)

    # V1 enclosure check
    vx, vy = vpos
    new_left = pbox.left + lt
    new_right = pbox.right - rt
    new_bottom = pbox.bottom + bt
    new_top = pbox.top - tt

    via_l = vx - VIA1_SZ // 2
    via_r = vx + VIA1_SZ // 2
    via_b = vy - VIA1_SZ // 2
    via_t = vy + VIA1_SZ // 2

    encs = [via_l - new_left, new_right - via_r,
            via_b - new_bottom, new_top - via_t]
    if min(encs) < V1_SIDE_ENC:
        # Reduce trim to maintain enclosure
        if via_l - new_left < V1_SIDE_ENC:
            lt = s5(max(0, lt - (V1_SIDE_ENC - (via_l - new_left))))
        if new_right - via_r < V1_SIDE_ENC:
            rt = s5(max(0, rt - (V1_SIDE_ENC - (new_right - via_r))))
        if via_b - new_bottom < V1_SIDE_ENC:
            bt = s5(max(0, bt - (V1_SIDE_ENC - (via_b - new_bottom))))
        if new_top - via_t < V1_SIDE_ENC:
            tt = s5(max(0, tt - (V1_SIDE_ENC - (new_top - via_t))))

    trims[vpos] = [lt, rt, bt, tt]

# Step 5: Apply trims
trim_count = 0
for si in top.each_shape(li_m2):
    box = si.bbox()
    cx = (box.left + box.right) // 2
    cy = (box.top + box.bottom) // 2

    matched_via = None
    for vx, vy in via1_positions:
        if abs(cx - vx) <= 10 and abs(cy - vy) <= 10:
            matched_via = (vx, vy)
            break

    if matched_via is None or matched_via not in trims:
        continue

    lt, rt, bt, tt = trims[matched_via]
    if lt + rt + bt + tt == 0:
        continue

    new_left = box.left + lt
    new_right = box.right - rt
    new_bottom = box.bottom + bt
    new_top = box.top - tt

    new_w = new_right - new_left
    new_h = new_top - new_bottom

    # Final safety gate
    if new_w < MIN_PAD_DIM or new_h < MIN_PAD_DIM:
        print(f"  BLOCK ({matched_via[0]/1e3:.3f},{matched_via[1]/1e3:.3f}): "
              f"{new_w}x{new_h} < {MIN_PAD_DIM}")
        continue

    # Grid check
    for coord in [new_left, new_right, new_bottom, new_top]:
        if coord % GRID != 0:
            print(f"  BLOCK ({matched_via[0]/1e3:.3f},{matched_via[1]/1e3:.3f}): "
                  f"off-grid coord {coord}")
            continue

    si.box = kdb.Box(new_left, new_bottom, new_right, new_top)
    trim_count += 1
    print(f"  OK ({matched_via[0]/1e3:.3f},{matched_via[1]/1e3:.3f}): "
          f"{box.width()}x{box.height()} → {new_w}x{new_h} "
          f"[L={lt},R={rt},B={bt},T={tt}]")

print(f"\nApplied {trim_count} trims")

# Step 6: Self-verification (BEFORE writing)
print("\n=== Self-Verification ===")
m2_post = kdb.Region(top.begin_shapes_rec(li_m2)).merged()

# M2.b (spacing)
post_space = m2_post.space_check(M2_MIN_S).count()
delta_b = post_space - base_space
print(f"M2.b: {base_space} → {post_space} (delta={delta_b:+d})")

# M2.a (width)
post_width = m2_post.width_check(M2_MIN_W).count()
delta_a = post_width - base_width
print(f"M2.a: {base_width} → {post_width} (delta={delta_a:+d})")

# M2.d (min area) — check standalone shapes
# Note: merged shapes have large area, so this checks the region's individual polygons
area_viols = 0
for poly in m2_post.each():
    if poly.area() < M2_MIN_AREA:
        area_viols += 1
print(f"M2.d (standalone area < {M2_MIN_AREA}nm²): {area_viols}")

# OffGrid check (all M2 edges on 5nm grid)
offgrid = 0
for poly in m2_post.each():
    for edge in poly.each_edge():
        for pt in [edge.p1, edge.p2]:
            if pt.x % GRID != 0 or pt.y % GRID != 0:
                offgrid += 1
                break
print(f"OffGrid.Metal2 (edges not on {GRID}nm grid): {offgrid}")

# Decision gate
regressions = []
if delta_a > 0:
    regressions.append(f"M2.a +{delta_a}")
if area_viols > 0:
    regressions.append(f"M2.d {area_viols}")
if offgrid > 0:
    regressions.append(f"OffGrid {offgrid}")

if regressions:
    print(f"\n*** REGRESSIONS DETECTED: {', '.join(regressions)} ***")
    print("NOT saving — fix the regressions first.")
    sys.exit(1)

if delta_b >= 0:
    print(f"\n*** No M2.b improvement (delta={delta_b:+d}). NOT saving. ***")
    sys.exit(1)

# All checks passed — save
print(f"\n✓ All checks passed. M2.b improved by {-delta_b}.")
layout.write(GDS_OUT)
print(f"Saved to {GDS_OUT}")
