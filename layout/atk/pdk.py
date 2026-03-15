"""IHP SG13G2 PDK constants and design rules.

Single source of truth for layer numbers, DRC rules, and routing constraints.
All dimensions in nm (dbu=0.001µm) unless noted.

Constraint system: every derived value is computed from base DRC rules.
Changing one base rule auto-updates all derived values; asserts catch regressions.

    Base DRC rules (immutable)
        ↓
    Pad sizes (minimum for enclosure)
        ↓
    Via center-to-center (max of M1/M2/V1 constraints)
        ↓
    VIA_CLEAR, placement gaps, router params
        ↓
    Assertions (self-consistency check)
"""

# ═══════════════════════════════════════════════════
# Layer definitions (layer, datatype)
# ═══════════════════════════════════════════════════

# FEOL layers
ACTIV       = (1, 0)
GATPOLY     = (5, 0)
CONT        = (6, 0)
NSD         = (7, 0)
PSD         = (14, 0)
NWELL       = (31, 0)
NBULAY      = (32, 0)

# BEOL layers
METAL1      = (8, 0)
METAL2      = (10, 0)
METAL3      = (30, 0)
METAL4      = (50, 0)
VIA1        = (19, 0)
VIA2        = (29, 0)
VIA3        = (49, 0)
METAL1_PIN  = (8, 2)
METAL2_PIN  = (10, 2)
METAL3_PIN  = (30, 2)
METAL4_PIN  = (50, 2)
METAL1_LBL  = (8, 1)
METAL2_LBL  = (10, 1)
METAL3_LBL  = (30, 1)
METAL4_LBL  = (50, 1)
TOPMETAL1   = (126, 0)
TOPMETAL1_PIN = (126, 2)

# ═══════════════════════════════════════════════════
# Base DRC rules (nm) — from IHP SG13G2 design manual
# These are INPUTS to the constraint system — never derived.
# ═══════════════════════════════════════════════════

# Metal1
M1_MIN_W    = 160     # M1.a: minimum width
M1_MIN_S    = 180     # M1.b: minimum spacing (< 10µm run length) — sg13g2_tech_default.json M1_b=0.18
M1_MIN_S_10 = 210     # M1.b2: spacing for ≥ 10µm run length
M1_VIA_ENC  = 90      # M1.d: enclosure of Via1

# Metal2
M2_MIN_W    = 200     # M2.a: minimum width
M2_MIN_S    = 210     # M2.b: minimum spacing (< 10µm run length)
M2_MIN_S_10 = 280     # M2.b2: spacing for ≥ 10µm run length
M2_VIA_ENC  = 144     # M2.d: enclosure of Via1

# Metal3
M3_MIN_W    = 200     # M3.a: minimum width
M3_MIN_S    = 210     # M3.b: minimum spacing (< 10µm run length)
M3_MIN_S_10 = 280     # M3.b2: spacing for ≥ 10µm run length
M3_VIA_ENC  = 90      # M3.d: enclosure of Via2

# Via1 (Metal1 ↔ Metal2)
V1_SIZE     = 190     # V1.a: via square dimension
V1_MIN_S    = 220     # V1.b: minimum spacing between vias — sg13g2_tech_default.json V1_b=0.22
V1_ENC_M1   = 90      # = M1.d
V1_ENC_M2   = 144     # = M2.d

# Via2 (Metal2 ↔ Metal3)
V2_SIZE     = 190     # V2.a: via square dimension
V2_MIN_S    = 220     # V2.b: minimum spacing between vias — sg13g2 DRC deck = 0.22µm
V2_ENC_M2   = 144     # M2 enclosure of Via2 — Mn_d=0.144µm (same as M2_VIA_ENC)
V2_ENC_M3   = 90      # M3 enclosure of Via2

# Metal4 (same generic Mn rules as M2/M3)
M4_MIN_W    = 200     # M4.a: minimum width
M4_MIN_S    = 210     # M4.b: minimum spacing (< 10µm run length)
M4_MIN_S_10 = 280     # M4.b2: spacing for ≥ 10µm run length
M4_VIA_ENC  = 90      # M4.d: enclosure of Via3

# Via3 (Metal3 ↔ Metal4) — same generic Vn rules as Via2
V3_SIZE     = 190     # V3.a: via square dimension
V3_MIN_S    = 220     # V3.b: minimum spacing between vias
V3_ENC_M3   = 90      # M3 enclosure of Via3
V3_ENC_M4   = 90      # M4 enclosure of Via3

# Device geometry (from PCell measurements)
GATE_OFFSET = 180     # Gate pin sits this far below MOSFET bbox bottom
NMOS_GS_DX  = 440     # Gate-to-Source pin X distance (all NMOS PCells)


# ═══════════════════════════════════════════════════
# Constraint system: derived values
# Every value below is computed from base rules above.
# ═══════════════════════════════════════════════════

UM = 1000              # 1 µm in dbu

# ─── 1. Pad sizes (minimum for DRC enclosure) ───
VIA1_PAD_M1 = V1_SIZE + 2 * M1_VIA_ENC   # = 370nm — M1 enclosure of Via1
VIA1_PAD_M2 = V1_SIZE + 2 * M2_VIA_ENC   # = 478nm — M2 enclosure of Via1
VIA1_PAD    = ((VIA1_PAD_M2 + 4) // 5) * 5  # = 480nm — snap to 5nm grid
VIA1_SZ     = V1_SIZE                     # alias
VIA2_SZ     = V2_SIZE                     # alias
VIA2_PAD    = ((V2_SIZE + 2 * max(V2_ENC_M2, V2_ENC_M3) + 4) // 5) * 5  # = 480nm (snapped)
VIA2_PAD_M3 = ((V2_SIZE + 2 * V2_ENC_M3 + 4) // 5) * 5  # = 370nm → 380nm after DRC tuning
VIA2_PAD_M2 = VIA2_PAD                    # alias: M2 enclosure of Via2

# GDS-drawn pad sizes (after DRC-driven shrink from routing pad sizes)
VIA1_GDS_M1 = 310          # AP M1 pad: shrunk from VIA1_PAD_M1(370) to fix M1.b
VIA1_GDS_M2 = VIA1_PAD     # AP M2 pad: 480nm (unchanged)

# M3 wide spacing (≥10µm run length)
M3_WIDE_S   = M3_MIN_S_10  # = 280nm

VIA3_SZ     = V3_SIZE                     # alias
VIA3_PAD    = ((V3_SIZE + 2 * max(V3_ENC_M3, V3_ENC_M4) + 4) // 5) * 5  # = 370nm (snapped)
VIA3_PAD_M3 = ((V3_SIZE + 2 * V3_ENC_M3 + 4) // 5) * 5  # = 370nm
VIA3_PAD_M4 = ((V3_SIZE + 2 * V3_ENC_M4 + 4) // 5) * 5  # = 370nm

# ─── 2. Via center-to-center: max of ALL layer constraints ───
#
# Two adjacent via pads must satisfy spacing on EVERY layer simultaneously:
#   M1.b: pad_M1 + M1_MIN_S = 370 + 160 = 530
#   M2.b: pad_M2 + M2_MIN_S = 480 + 210 = 690  ← governing
#   V1.b: via    + V1_MIN_S  = 190 + 210 = 400
#
_CC_M1 = VIA1_PAD_M1 + M1_MIN_S   # 530nm
_CC_M2 = VIA1_PAD    + M2_MIN_S   # 690nm
_CC_V1 = V1_SIZE     + V1_MIN_S   # 400nm
MIN_VIA_CC = max(_CC_M1, _CC_M2, _CC_V1)  # = 690nm, governed by M2.b

# ─── 3. VIA_CLEAR: bbox edge to via center ───
#
# Gate via is at GATE_OFFSET below bbox; above/below via is at VIA_CLEAR.
# Their Y separation must be ≥ MIN_VIA_CC:
#   VIA_CLEAR ≥ GATE_OFFSET + MIN_VIA_CC = 180 + 690 = 870
#
VIA_CLEAR = GATE_OFFSET + MIN_VIA_CC   # = 870nm
HBT_VIA_CLEAR = 1200   # HBT needs larger clearance (CntB.h1 rule)

# ─── 4. Gate via X conflict: same-device pin pairs ───
#
# NMOS PCell: G and S pins are only NMOS_GS_DX = 440nm apart in X.
# MIN_VIA_CC = 690nm requires 2D distance ≥ 690nm.
# At GATE_OFFSET=180nm Y separation between gate and S via, the 2D distance is:
#   sqrt(440² + 180²) = 475nm < 690nm → CONFLICT
#
# Solution: shift gate via in X to achieve MIN_VIA_CC in 2D.
# Required X distance: sqrt(MIN_VIA_CC² - (VIA_CLEAR - GATE_OFFSET - GATE_OFFSET)²)
# But since gate via is at bbox_bot - GATE_OFFSET and S "below" via is at
# bbox_bot - VIA_CLEAR, the Y separation = VIA_CLEAR - GATE_OFFSET = MIN_VIA_CC.
# So X = 0 suffices for gate↔below-S — they're already MIN_VIA_CC apart in Y.
#
# But gate pad ↔ S pad can STILL overlap in X on M1 if pad widths + spacing > dx:
#   M1 conflict: VIA1_PAD_M1 + M1_MIN_S = 530nm > NMOS_GS_DX = 440nm
# The M1 pads overlap in X by: VIA1_PAD_M1 - (NMOS_GS_DX - VIA1_PAD_M1) =
#   370 - (440 - 370) = 370 - 70 = 300nm overlap at pad edges
# BUT M1.b only cares about edge-to-edge distance of NON-OVERLAPPING shapes.
# If the gate pad Y range and S pad Y range don't overlap, M1.b is satisfied.
#
# Gate pad Y range: gate_y ± VIA1_PAD_M1/2 = (bbox_bot - 180) ± 185
#   = [bbox_bot - 365, bbox_bot - 0] (with stub extending to bbox_bot)
# S below-via pad Y range: (bbox_bot - VIA_CLEAR) ± VIA1_PAD_M1/2
#   = [bbox_bot - 870 - 185, bbox_bot - 870 + 185]
#   = [bbox_bot - 1055, bbox_bot - 685]
# Gap between them in Y: (bbox_bot - 365) - (bbox_bot - 685) = 320nm > M1_MIN_S ✓
#
# S "above"-via at bbox_TOP + VIA_CLEAR: far away, no conflict.
#
# The REAL conflict is: gate pad vs ADJACENT DEVICE's S pad on M1.
# Both pads are at similar Y (gate at bbox_bot - GATE_OFFSET, direct/gate at similar Y).
# For same-device gate(0.59) vs S(0.15): dx=440nm, both pads at ~same Y → M1 overlap.
#
# Fix: gate via pad Y range does NOT overlap with "below" S pad Y range (shown above).
# The 50nm violations we see are between gate pads of ADJACENT DEVICES:
# e.g., MPd4.G gate pad (at x≈48.89) vs MPd3.D above-pad M1 stub (at x≈48.45).
# These are from different devices placed side-by-side.
#
# For adjacent-device conflicts: placement gap must accommodate via pad clearance.
# Minimum device gap for independent via pads on M1:
MIN_DEV_GAP_M1 = VIA1_PAD_M1 + M1_MIN_S   # = 530nm center-to-center on M1

# ─── 5. Wire widths (with margin above DRC minimums) ───
M1_SIG_W = 300         # Metal1 signal wire: 0.3µm (> M1.a by 140nm)
M1_PWR_W = 1000        # Metal1 power: 1.0µm
M2_SIG_W = 300         # Metal2 signal wire: 0.3µm (> M2.a by 100nm)
M3_PWR_W = 3000        # Metal3 power rail: 3.0µm
M4_SIG_W = 300         # Metal4 signal wire: 0.3µm (same as M2/M3)
M1_THIN  = 160         # Metal1 thin stub: matches PCell M1 strip width
CONT_SZ  = 160         # Cont cut size (nm)
CONT_ENC_M1_END = 50   # M1 endcap enclosure of Cont (nm)

# Gate contact DRC rules (Cnt.d, Cnt.e, M1.d)
CNT_D_ENC  = 70        # Cnt.d: GatPoly enclosure of Cont ≥ 70nm
CNT_E_SEP  = 140       # Cnt.e: Cont on GatPoly to Active spacing ≥ 140nm
M1_MIN_AREA = 90000    # M1.d: Min Metal1 area ≥ 0.09 µm² = 90000 nm²
GATE_POLY_EXT = 230    # GatPoly extension below PCell poly_bot for gate contact
                       # = CNT_D_ENC + CONT_SZ + CNT_E_SEP - 180 (existing ext)
                       # Total extension: 180 + 230 = 410nm.  Contact at bottom.

# ─── 5b. M1-only reach threshold ───
#
# Gate pins with ALL net-mates within this Manhattan distance can use M1-only
# access (no via pad). The router starts on M1 and finds its own via position.
# 3µm ≈ 8 grid cells on MAZE_GRID=350nm — ample for short local connections.
M1_REACH = 3 * UM   # = 3000nm

# ─── 6. Pin access obstacle margins ───
#
# Router must avoid placing wires too close to via pads.
# Margin is added to the blocked rectangle in nm (see MazeRouter.block_rect).
# After expansion, grid cells overlapping the blocked area are impassable.
#
# The effective clearance depends on grid quantization:
#   wire_edge = grid_center - wire_width/2
#   gap = wire_edge - (pad_edge + margin)
#   ≈ MAZE_GRID - wire_width/2 - margin (worst case: pad edge at grid boundary)
#
# For M2 wire vs M2 pad: gap ≥ M2_MIN_S = 210nm
#   margin ≥ MAZE_GRID - M2_SIG_W/2 - M2_MIN_S (may be negative = grid handles it)
#   But too large margin blocks routes.
#
# Split by layer: M1 and M2 have different spacing rules.
# Margin must include MIN_S + router wire half-width (M2_SIG_W/2 = 150nm),
# because block_rect prevents wire CENTER from entering blocked zone,
# but wire EDGE extends half-width beyond center.
PIN_VIA_MARGIN    = M1_MIN_S + M2_SIG_W // 2   # = 160+150 = 310nm — M1 layer blocking
PIN_VIA_MARGIN_M2 = M2_MIN_S + M2_SIG_W // 2   # = 210+150 = 360nm — M2 layer blocking

# ─── 7. Device obstacle margins ───
HBT_MARGIN = 500       # Extra clearance for HBT contact rules
DEV_MARGIN = 200       # Standard device clearance

# ─── 8. Placement gaps (derived from ALL routing constraints) ───
#
# CP-SAT solver must leave enough gap between devices for:
# (a) Router to pass signal wires through gaps
# (b) Via pads of adjacent devices to not violate spacing
#
# Constraint (a): N signal tracks through a gap
M2_ROUTE_PITCH = M2_SIG_W + M2_MIN_S          # = 510nm per track
M1_ROUTE_PITCH = M1_SIG_W + M1_MIN_S          # = 460nm per track

def channel_width(n_tracks, layer='M2'):
    """Minimum channel width (nm) to fit n_tracks signal routes.

    Includes margin for via pads at track endpoints.
    """
    pitch = M2_ROUTE_PITCH if layer == 'M2' else M1_ROUTE_PITCH
    return n_tracks * pitch + VIA1_PAD

# Preset channel widths for common cases
CHANNEL_2T = channel_width(2)   # 2 tracks: ~1500nm = 1.5µm
CHANNEL_3T = channel_width(3)   # 3 tracks: ~2010nm = 2.0µm
CHANNEL_4T = channel_width(4)   # 4 tracks: ~2520nm = 2.5µm
CHANNEL_5T = channel_width(5)   # 5 tracks: ~3030nm = 3.0µm

# Constraint (b): via pad spacing between adjacent devices
# Router blocks each device bbox with DEV_MARGIN; via pads extend beyond bbox.
# Effective requirement: gap must be max of routing channel and via pad clearance.
_GAP_1T_ROUTE = 2 * DEV_MARGIN + M2_SIG_W        # 700nm — room for 1 wire
_GAP_1T_VIAS  = MIN_VIA_CC                        # 690nm — via pad M2.b spacing
PLACE_GAP_1T  = max(_GAP_1T_ROUTE, _GAP_1T_VIAS) # 700nm — governing: route

_GAP_2T_ROUTE = 2 * DEV_MARGIN + 2 * M2_ROUTE_PITCH  # 1420nm — 2 wires
PLACE_GAP_2T  = max(_GAP_2T_ROUTE, _GAP_1T_VIAS)     # 1420nm — governing: route

# ─── 9. Maze router parameters ───
MAZE_GRID = 350        # Grid resolution (nm)
MAZE_MARGIN = 1        # Cells to block around used path (spacing enforcement)

# Router center-to-center = (MARGIN + 1) * GRID = 700nm
# This must satisfy ALL spacing rules for wire-to-wire:
#   M2: 700 - M2_SIG_W = 400nm ≥ M2_MIN_S (210nm) ✓
#   M1: 700 - M1_SIG_W = 400nm ≥ M1_MIN_S (160nm) ✓
#   Via pad: 700 - VIA1_PAD = 220nm ≥ V1_MIN_S (210nm) ✓

# ═══════════════════════════════════════════════════
# Assertions — catch parameter errors at import time
# ═══════════════════════════════════════════════════

# Pad enclosure
assert VIA1_PAD >= VIA1_PAD_M2, \
    f"VIA1_PAD {VIA1_PAD} < min {VIA1_PAD_M2} (M2.d enclosure violated)"

assert VIA1_PAD_M1 >= V1_SIZE + 2 * M1_VIA_ENC, \
    f"VIA1_PAD_M1 {VIA1_PAD_M1} < M1.d minimum"

# Wire widths
assert M2_SIG_W >= M2_MIN_W, \
    f"M2_SIG_W {M2_SIG_W} < M2.a min width {M2_MIN_W}"

assert M1_SIG_W >= M1_MIN_W, \
    f"M1_SIG_W {M1_SIG_W} < M1.a min width {M1_MIN_W}"

# Via center-to-center satisfies all layers
assert MIN_VIA_CC >= VIA1_PAD_M1 + M1_MIN_S, \
    f"MIN_VIA_CC {MIN_VIA_CC} < M1.b min {VIA1_PAD_M1 + M1_MIN_S}"
assert MIN_VIA_CC >= VIA1_PAD + M2_MIN_S, \
    f"MIN_VIA_CC {MIN_VIA_CC} < M2.b min {VIA1_PAD + M2_MIN_S}"
assert MIN_VIA_CC >= V1_SIZE + V1_MIN_S, \
    f"MIN_VIA_CC {MIN_VIA_CC} < V1.b min {V1_SIZE + V1_MIN_S}"

# VIA_CLEAR keeps gate and above/below vias apart
assert VIA_CLEAR >= GATE_OFFSET + MIN_VIA_CC, \
    f"VIA_CLEAR {VIA_CLEAR} < GATE_OFFSET + MIN_VIA_CC"

# Maze router spacing
_maze_cc = (MAZE_MARGIN + 1) * MAZE_GRID
assert _maze_cc - M2_SIG_W >= M2_MIN_S, \
    f"Maze M2 gap {_maze_cc - M2_SIG_W}nm < M2.b {M2_MIN_S}nm"
assert _maze_cc - VIA1_PAD >= V1_MIN_S, \
    f"Maze via pad gap {_maze_cc - VIA1_PAD}nm < V1.b {V1_MIN_S}nm"
assert _maze_cc - M1_SIG_W >= M1_MIN_S, \
    f"Maze M1 gap {_maze_cc - M1_SIG_W}nm < M1.b {M1_MIN_S}nm"

# Placement gaps satisfy via spacing
assert PLACE_GAP_1T >= MIN_VIA_CC, \
    f"PLACE_GAP_1T {PLACE_GAP_1T} < MIN_VIA_CC {MIN_VIA_CC}"


def s5(val_um):
    """Snap float µm to 5nm grid, return int nm."""
    nm = round(val_um * UM)
    return ((nm + 2) // 5) * 5
