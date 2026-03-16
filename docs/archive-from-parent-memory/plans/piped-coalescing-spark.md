# Main DRC Deck Cleanup: 229 → 0 (Incremental)

## Approach: One Variable at a Time

每轮只改一个变量 → 跑完整 pipeline + DRC → 记录 before/after counts → 理清事实 vs 推测 → 再决定下一步。

不预设后续步骤的具体 fix — 每轮 DRC 结果可能改变后续策略。

## Context

- Maximal DRC deck = **0** violations (supplementary rules, already clean)
- Main DRC deck (`ihp-sg13g2.drc`) = **229** violations (basic metal/via spacing, NWell)
- CI runs both decks. Must reach 0 on both.

## Current Status: DRC 5 (R27) + LVS device match, ~407 net mismatches (R32d)

Note: ECO reroute (Rout x=36→10, for LVS fix) happened after R16, regressing DRC 30→188.
Post-ECO cleanup (E1–E9) brought it to 19.

| Rule | R0 | R5 | R11 | R15 | R16 | R17 | R18 | R20 | R21 | R22d | R24c | R25c | R26c | R27 (current) | Notes |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|------|
| M2.b | 60 | 27 | 12 | 14 | 15 | 12 | 12 | 6 | 6 | 2 | 2 | 2 | 1 | **1** | Placement-constrained (490nm via sep, need 500nm) |
| NW.b1 | 12 | 12 | 6 | 6 | 6 | 6 | 6 | 4 | 4 | 4 | 4 | 4 | 4 | **4** | NMOS NWell gap (Pair B, parked) |
| M1.b | 10 | 6 | 7 | 5 | 5 | 32 | 4 | 4 | 4 | 4 | 1 | 0 | 0 | **0** | Fixed R25c: tie M1 trim |
| M3.b | 94 | 18 | 11 | 4 | 0 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | **0** | Fixed R27: AP Via2 M3 bbox gap fill |
| M1.a | 10 | 2 | 2 | 2 | 2 | 0 | 3 | 3 | 3 | 3 | 0 | 0 | 0 | **0** | Fixed R24c: AP M1 pad extend |
| M2.c1 | - | - | - | - | - | 3 | 3 | 3 | 3 | 0 | 0 | 0 | **0** | Fixed R22d |
| M1.d | - | - | - | - | - | 2 | 2 | 2 | 2 | 2 | 0 | 0 | **0** | Fixed R23d: bus strap area |
| V2.c1 | - | - | - | - | - | 1 | 1 | 1 | 1 | 0 | 0 | 0 | **0** | Fixed R22d |
| Cnt.d | - | - | - | - | - | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | **0** | Fixed R21 |
| CntB.b2 | - | - | - | - | - | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 | **0** | Fixed R21 |
| Rhi.d | - | - | - | - | - | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | **0** | Fixed R21 |
| Rppd.c | - | - | - | - | - | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | **0** | Fixed R21 |
| M3.a | - | - | - | - | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** | Fixed R17 |
| M3.e | 4 | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** | |
| NW.b | 4 | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** | |
| M4.b | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** | |
| **Total** | **229** | **78** | **43** | **35** | **30** | **70** | **45** | **37** | **27** | **19** | **11** | **10** | **9** | **5** | |

## Round 3 Fix: _fill_same_net_gaps enhancement (assemble_gds.py)

**Changes**:
1. When overlap dimension < min_w, extend fill symmetrically (grid-snapped to 5nm) instead of skipping
2. Added power M3 shapes (vbars, via2 pads, rails) to gap fill collection
3. Added power M2 shapes (drops) to gap fill collection (neutral — no new M2 fills found)

**Result**: M3.b 44→18 (-26), M3.e 4→2 (-2), total 177→142 (-35)

**Remaining M3.b=18 breakdown**:
- signal-signal cross-net: 6 (needs router M3 spacing enforcement)
- signal-signal same-net: 4 (notch/diagonal patterns, not fixable by gap fill)
- power same-net: 3 (remaining notches)
- power cross-net: 2 (vbar/rail spacing)
- unknown: 3

## Round 4 Fix: M4 L-corner trimming (optimize.py)

**Changes**:
1. Removed experimental `_mark_upper_layer_margins` from solver.py (didn't work)
2. Added `trim_m4_lcorners()` post-pass in optimize.py: trims M4 wire endpoints
   by 15nm at cross-net L-corners where gap = GRID - HW = 200nm < 210nm
3. Handles both horizontal and vertical endpoint trimming
4. Protection: skips endpoints at via3 pad positions

**Result**: M4.b 20→0 (-20), M1.b 13→6 (-7), M1.a 8→2 (-6), total 142→109 (-33)
M1 improvement is bonus from solver.py cleanup (removing experimental code)

## Round 5 Fix: M2 underpass minimization (assemble_gds.py)

**Root cause analysis** (definitive, KLayout-verified):
- 44 "UNKNOWN" 480x3800nm M2 shapes = power drop M2 underpasses bridging excl zones
- Created by via_stack drop code when M3 vbar crosses other-net rails
- MOSFETs have ZERO M2 shapes (confirmed by recursive KLayout probe)

**Key discovery**: V2.c = 5nm (M2 side enclosure of Via2), V2.c1 = 50nm (endcap).
Current VIA2_PAD = 480nm gives 145nm enclosure — **massively overbuilt**.

**Changes (R5a → R5b)**:

R5a: Narrow + dedup:
1. Narrowed M2 underpass vbar: VIA2_PAD (480nm) → M2_MIN_W (200nm)
2. Narrowed M2 rail bridge vbar similarly
3. De-duplicated underpass draws via `_drawn_m2_underpasses` set
Result: M2.b 58→51 (-7)

R5b: Eliminate via2 M2 pad for underpasses:
4. Created `via2_no_m2_pad()` — draws only via2 cut + M3 pad (no M2 pad)
5. Extended M2 vbar by `_VIA2_M2_ENDCAP = VIA2_SZ//2 + 50 = 145nm` at each end
6. The extended narrow vbar (200nm) provides V2.c (5nm side) + V2.c1 (50nm endcap) enclosure
Result: M2.b 51→27 (-24), V2.c1 = 0 violations, V2.b = 2 (unchanged)

**Total R5**: M2.b 58→27 (-31), all other rules unchanged, total 109→78 (-31)

**Failed experiments** (reverted):
- Aggressive DRC-aware conflict check + AP/power obstacle rects: M2.b→45 but M3.e 2→19 (+17)
- Incremental X shift (±50nm steps): dense packing → no clear position → M3 regression

## Round 14e Fix: M1 L-corner extension (optimize.py)

**Changes**:
1. New `extend_lcorners()` function in optimize.py
2. At same-net L-corner junctions WITHOUT a via, extends the H wire endpoint by HW (150nm) to fill the concave notch
3. Cross-net obstacle check using bbox proximity (signal wires + AP pads + power M2)
4. Only applied to M1 — M2 extensions cause cascade of new notches/proximity issues

**Result**: M1.a 4→2 (-2), M1.b 8→5 (-3), total 41→36 (-5), zero regressions

**Failed experiments**:
- M2 L-corner extension: M2.b 14→17-20 (+3-6), M2.a 0→2 — extensions create new
  cross-net proximity and L-corner notches with adjacent shapes
- L-corner notch FILL in assemble_gds.py: 3016 fills (was 128), M2.b 14→34 — too aggressive
- solver.py tie M1 protection (add tie cells to pass 1 protected): routing failure
  (dac_out 132/133) — pins need M1 escape through tie areas

## LVS Gate Fragmentation — Round 35: Phase Assessment (2026-03-15)

### Outcome

**Post-processing reached its limit.** vcas fixed (1 net), 3 nets partially improved,
~50 nets structurally blocked by M3 power infrastructure.

### What was implemented

1. **Fix 1 (has_low bypass)**: `_m2_island_has_via2()` + bypass logic. 25 Via2 placed, 0 LVS improvement.
2. **M4 dead-end drops**: 4 safe Via3+Via2 at M4 wire endpoints. vcas FIXED, net_c1 5→3, f_exc 7→6, div4_I 5→4.
3. DRC: maximal=0, main=7 (unchanged from R27 baseline).

### Root cause (verified on bias_n, t1Q_mb, net_c1)

M3 power rails/vbars occupy most M3 layer → Via2 M3 pad (needs ~800nm clearance) cannot be placed
at most signal M4 endpoints. This is a **router + power planning structural issue**, not fixable
by assemble_gds post-processing.

### What needs to change for further LVS progress

- `power.py`: relocate M3 vbars to create Via2 landing zones between power rails
- `solver.py`: route signals with M3 power occupancy awareness
- Or accept current LVS state and verify critical nets only

### Original analysis

LVS shows ~54 fragmented gate/bulk nets (~407 total net mismatches, 54 are root causes; rest cascade).
Diagnostic scripts confirmed:

- **230/237 gate pins** lack M1 connectivity to routing backbone
- **ALL gaps < 500nm** — backbone (M3/M4) reaches every gate AP
- Problem is **vertical drop stack not closing**: Via1→M2→Via2→M3→backbone

Root causes (3 categories, all in `_add_missing_ap_via2` or its assumptions):

| Cat | Nets | Pins | Root Cause |
|-----|-----:|-----:|------------|
| **A** | ~24 | 35 | Via2 SKIPPED — M3 too crowded, all fallback paths fail |
| **B** | ~22 | 52 | `has_low=True` early-skip, but M2 island not connected to backbone |
| **D** | 3 | 6 | Via2 placed OK but M3/M4 backbone is fragmented between pins |

### Strategy: Two targeted fixes in `_add_missing_ap_via2` + one small new pass

**Don't** build a separate `_gate_drop_completion` function or a complex NetGraph class.
Instead, fix the existing function's two bugs and add a small backbone-bridge pass.

### Fix 1: Category B — Replace `has_low` skip with `has_low_and_connected` (lines 1149-1176)

**Problem**: `has_low=True` means a route M1/M2/Via1 endpoint overlaps the AP pad.
The code assumes this means the pin is fully connected. But on 52 pins, the M2 segment
is on an isolated island — no Via2 anywhere connecting it to M3/M4.

**Fix**: After finding `has_low=True`, perform lightweight M2 island connectivity check:

```python
if has_low:
    # ── NEW: verify M2 island actually connects to M3/M4 ──
    # BFS from the touching M2 segment through same-net M2 segments.
    # If any reached M2 segment has a Via2 within wire-width, truly connected.
    # If not, M2 island → fall through to Via2 placement.
    _truly_connected = _m2_island_has_via2(segs, ap_x, ap_y, _m2r)
    if _truly_connected:
        continue  # Existing behavior — skip
    # Fall through to Via2 placement (same as non-has_low path)
```

**`_m2_island_has_via2` function** (~40 lines):
1. Find the M2 segment whose endpoint overlaps AP M2 pad (the one that triggered `has_low`)
2. BFS: collect all M2 segments reachable from that segment (endpoints within `_wire_hw`)
3. Check if any Via2 segment position overlaps any collected M2 segment
4. Also check if any M3 segment endpoint overlaps any collected M2 segment (for routes that go directly M2→M3 without explicit Via2)
5. Return True if connected, False if island

**DRC risk**: None. This only changes which pins get Via2 placement attempted. The actual Via2 placement uses existing DRC-checked code paths (normal/fallback/scan).

### Fix 2: Category A — Expand search radius and try all same-net vertices (lines 1178-1471)

**Problem**: The normal path finds nearest M3/M4 vertex within 500nm, but M3 conflict
blocks Via2. Fallback and SCAN (700nm radius) also fail because M3 is too dense.

**Fix 2a: Expand vertex search from 500nm → 1500nm** (line 1191)

```python
# OLD: if not best_pos or best_dist > 500:
# NEW: if not best_pos or best_dist > 1500:
```

**Fix 2b: Expand SCAN radius from 700nm → 1500nm** (lines 1353-1401)

```python
# OLD: if (min(_sx1, _sx2) > ap_x + 700 ...):
# NEW: if (min(_sx1, _sx2) > ap_x + 1500 ...):
# OLD: if _scan_pos and _best_scan_d <= 700:
# NEW: if _scan_pos and _best_scan_d <= 1500:
```

**Fix 2c: Try ALL same-net M3/M4 vertices, not just nearest** (new fallback after SCAN)

After SCAN fails, add a "WIDE" fallback:
1. Collect all M3/M4 segment endpoints on the same net (no distance limit)
2. Sort by Manhattan distance from AP
3. For each vertex, check if M3 pad is conflict-free
4. For the first clear vertex, draw Via2 + M2 bridge from AP to that position
5. M2 bridge needs cross-net M2 conflict check (`xnet_m2_wires`)

```python
# ── WIDE fallback: search ALL same-net M3/M4 vertices ──
if not _scan_ok:
    _wide_ok = False
    _candidates = []
    for _seg in segs:
        if _seg[4] not in (M3_LYR, M4_LYR):
            continue
        for _px, _py in ((_seg[0], _seg[1]), (_seg[2], _seg[3])):
            _d = abs(_px - ap_x) + abs(_py - ap_y)
            _candidates.append((_d, _px, _py, _seg))
    _candidates.sort()

    for _d, _vx, _vy, _vseg in _candidates:
        _vx_s = ((_vx + 2) // 5) * 5
        _vy_s = ((_vy + 2) // 5) * 5
        # Check M3 pad conflict at vertex
        if _m3_rect_conflict(_vx_s - hp_via2_m3, _vy_s - hp_via2_m3,
                             _vx_s + hp_via2_m3, _vy_s + hp_via2_m3, net_name):
            continue
        # Check M2 bridge conflict (cross-net)
        _bridge = _compute_m2_bridge(ap_x, ap_y, _vx_s, _vy_s)
        if _m2_bridge_conflict(_bridge, net_name, xnet_m2_wires):
            continue
        # Place Via2 + Via3 (if on M4) + M2 bridge
        _wide_ok = True
        # ... draw shapes (same pattern as SCAN/FALLBACK) ...
        break
```

**DRC risk**: Low-Medium.
- Longer M2 bridges increase chance of cross-net M2 proximity → mitigated by explicit `_m2_bridge_conflict` check
- Larger SCAN radius is safe (same M3 conflict check applies)
- Via2 M2 pads use existing `via2_cut_only` (no extra M2 pad) → no M2.b risk

### Fix 3: Category D — Backbone bridge pass (~50 lines, new function)

**Problem**: 3 nets (t1Q_mb, t3_mb, t4Q_mb) have two gate pins connecting to different
M3/M4 backbone islands. Even with Via2 placed correctly, the backbone itself is split.

**Fix**: New function `_bridge_backbone_islands()` called after `_add_missing_ap_via2`:

1. For each of the 3 known nets, collect all M3/M4 segments
2. Build connectivity graph (endpoints touching within wire half-width)
3. If multiple components, find closest pair of points between components
4. Draw M3 or M4 wire segment bridging them (with M3.b spacing check)
5. If M3 is too crowded, try M4 bridge + Via3 at each end

**Integration point** (after line ~3920):
```python
_ap_via2_m3_stubs, _fallback_shapes = _add_missing_ap_via2(...)
# NEW: Bridge fragmented backbones
_bridge_backbone_islands(top, li_m3, li_m4, li_v3, routing, m3_obs=...)
```

**DRC risk**: Low. Only 3 nets, each needs at most one short M3/M4 bridge. Full M3.b/M4.b spacing check included.

### Implementation Order

| Step | What | Lines | DRC Risk | Verifiable |
|------|------|------:|----------|------------|
| 1 | `_m2_island_has_via2()` helper | +40 | None | diagnose script |
| 2 | Replace `has_low` skip with connectivity check (Fix 1) | ~10 | None | LVS rerun |
| 3 | Expand search radii (Fix 2a, 2b) | ~6 | Low | LVS rerun |
| 4 | WIDE fallback + `_m2_bridge_conflict` helper (Fix 2c) | +60 | Low-Med | LVS rerun |
| 5 | `_bridge_backbone_islands()` (Fix 3) | +50 | Low | LVS rerun |
| 6 | Return `m3_obs` from `_add_missing_ap_via2` for Fix 3 | +3 | None | — |

**Total**: ~170 new lines + ~16 modified lines

### Pilot Plan

**Step 1-2 (Fix 1)**: Run on ALL nets — it's a pure filter change, safe.
- Expected: ~18 of 22 Category B nets fixed (the ones with NO Via2 on net)
- Remaining B nets (M2 island with Via2 on different island): Fixed by expanded search

**Step 3-4 (Fix 2)**: Run on ALL nets.
- Expected: majority of 24 Category A nets fixed by wider search

**Step 5 (Fix 3)**: Only 3 specific nets.

### Verification

```bash
cd /private/tmp/analog-trial/layout && source ~/pdk/venv/bin/activate

# 1. Regenerate GDS
klayout -n sg13g2 -zz -r assemble_gds.py

# 2. Run LVS (expect fragmented nets to drop from 53)
mkdir -p /tmp/lvs_r35 && cd /tmp/lvs_r35
klayout -n sg13g2 -zz -r ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/lvs/run_lvs.py \
    /private/tmp/analog-trial/layout/output/ptat_vco.gds ptat_vco \
    /private/tmp/analog-trial/layout/ptat_vco_lvs.spice

# 3. Run DRC (must remain at 5 — no regressions)
python3 ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py \
    --path=/private/tmp/analog-trial/layout/output/ptat_vco.gds \
    --topcell=ptat_vco --run_dir=/tmp/drc_r35 --mp=1 --no_density

# 4. Run gate fragmentation diagnostic (expect count drop)
cd /private/tmp/analog-trial/layout
python3 diagnose_gate_fragmentation.py   # was 53 fragmented nets
python3 diagnose_ap_via2_status.py        # was 35 SKIPPED + 52 HAS_LOW-no-Via2
```

### Key Files

| File | Changes |
|------|---------|
| `layout/assemble_gds.py` | Fix 1: `_m2_island_has_via2()` + has_low logic change. Fix 2: radius expansion + WIDE fallback + `_m2_bridge_conflict()`. Fix 3: `_bridge_backbone_islands()` |
| `layout/atk/pdk.py` | Read-only: DRC constants |
| `layout/output/routing.json` | Read-only: routing data |

### Existing functions to reuse

- `via2_cut_only(top, li_v2, x, y)` — Via2 cut without M2/M3 pads (line 136)
- `via3(cell, li_v3, li_m3, li_m4, x, y)` — Via3 + M3/M4 pads (line 146)
- `draw_rect(cell, li, rect)` — generic rect draw (line 155)
- `_m3_rect_conflict()` — M3 spacing check (already inside `_add_missing_ap_via2`, line 1107)
- `_fill_same_net_gaps()` — downstream gap fill already handles new M3 stubs (line 3925)

### What NOT to do

- Don't build a complex `NetGraph` class or shapely-based connectivity checker in assemble_gds.
  The simple BFS on M2 segment endpoints is sufficient and avoids adding shapely dependency.
- Don't change `solve_routing.py` or re-route.
- Don't add a separate `_gate_drop_completion()` function — integrate into existing `_add_missing_ap_via2`.
- Don't try to fix Category E separately — it will likely auto-resolve.

## Remaining Issues (post-R27) — 5 violations (2026-03-14)

All remaining violations are placement-constrained — no further assembly/routing fixes possible.

### TOP-cell placement-constrained — parked (5)
- M2.b=1: MBn2.D vs MBp2.G, gap=200nm (need 210nm). Via1 centers 490nm apart, need 500nm.
  Endcap (M2.c1=50nm) + area (M2.d=144000nm²) prevent further shrink. Requires placement change.
- NW.b1=4: ntap NWell vs pmos$1 NWell (Pair B only, NMOS blocks bridge)

## Round 24c Fix: AP M1 pad extension for offset routing vias (assemble_gds.py)

**Root cause**: Maze router grid quantization (350nm grid) can place routing via1 offset
from AP center. At the AP pad-stub-wire junction, the offset creates concave notches
< M1_MIN_W (160nm) → M1.a violations and sub-M1.b gaps → M1.b violations.

**Changes**:
1. Added routing via1 position index per net (`_via1_per_net`)
2. In AP M1 pad drawing: when a routing via is offset from AP center by > half-pad-size,
   extend the M1 pad to cover both AP and via positions
3. Added M1.a edge adjustment (protrusion must be 0 or ≥ M1_MIN_W)
4. Added V1.c1 enclosure clamping (pad must enclose AP via with 50nm endcap)
5. Threshold check: only extend for large offsets (>155nm), skip small ones that
   don't cause DRC-visible violations

**Result**: M1.a 3→0 (-3), M1.b 4→1 (-3), M1.d 2→0 (-2), total 19→11 (-8)
(M1.d fixed by R23d bus strap area enforcement, also in this session)

## Round 25c Fix: Tie M1 proximity trim (assemble_gds.py)

**Root cause**: Tie cell M1 shapes (260×600nm, 2 Conts) can be too close to routing M1
wires. The solver blocks tie M1 with margin, but pin_terminal exemption (same grid row as
Mdac_tg2n.S pin) allows the block to be cleared during routing. The dac_out wire then
routes 85nm from tie M1 top (need 180nm).

**Changes**:
1. Build routing M1 wire index from signal_routes + pre_routes (wires + via1 pads)
2. Before drawing each tie, check tie M1 rects against routing M1 shapes
3. If gap < M1_MIN_S (180nm), trim tie M1 on the offending edge
4. Drop Conts not fully enclosed by trimmed M1 (prevent M1.c/M1.c1 violations)
5. Enforce M1.d min area (anchor at bottom, extend top if needed)

**Result**: M1.b 1→0 (-1), total 11→10 (-1), zero regressions

## Round 26c Fix: Duplicate M2 removal + gap fill bridging (assemble_gds.py)

**Root causes**:
1. `_add_missing_ap_via2()` drew Via2 M2 pad (`via2_cut_m2`) at AP locations that already had
   M2 pads from section 3. Post-assembly shrink deleted one copy; the un-shrunk duplicate remained.
2. `_fill_same_net_gaps()` Pass 2 only checked fills vs originals, not fills vs fills.
   Two same-net gap fills (tail net, between Min_p.S2↔Mtail.D and Mtail.D↔Min_n.S) had 80nm gap.

**Changes**:
1. Changed `via2_cut_m2(top, li_v2, li_m2, ...)` → `via2_cut_only(top, li_v2, ...)` at line 1143
   (AP M2 pad already provides M2 enclosure for Via2 cut)
2. Gap fill Pass 2: changed `for j in range(n_orig)` → `for j in range(len(shapes)) if j < i`
   to also bridge fill-vs-fill gaps on same net
3. Added diagonal Y-shrink second pass in `_try_shrink()` with area/width validation + revert guard

**Result**: M2.b 2→1 (-1), total 10→9 (-1), zero regressions

**Remaining M2.b=1**: MBn2.D vs MBp2.G. Via1 centers 490nm apart (need 500nm for
M2.c1=50nm endcap on both). M2.d area (144000nm²) prevents asymmetric pad reshaping.
Unfixable without placement adjustment.

## Round 27 Fix: AP Via2 M3 bbox stub gap fill (assemble_gds.py)

**Root cause**: `_add_missing_ap_via2()` draws M3 bbox stubs (Via2 pad → route vertex)
that create same-net gaps with adjacent signal M3 wires and via pads from the same route.
These bbox stubs weren't included in `_fill_same_net_gaps()` M3 shape collection, so gap
fill couldn't bridge them.

All 4 violations were same-net:
- #1 (t2Q_m): bbox stub left edge 100nm from vertical wire right edge (notch below horizontal bar)
- #2 (t1Q_m): same pattern, 100nm gap
- #3 (div16_I_b): bbox stub 45nm from vertical wire (tighter geometry)
- #4 (t3_nmn): Via3 pad 195nm below AP bbox stub (Y gap)

**Changes**:
1. `_add_missing_ap_via2()` now returns list of `(x1, y1, x2, y2, net)` for M3 bbox stubs
2. `_fill_same_net_gaps()` accepts `ap_via2_m3_stubs` parameter
3. When processing M3 gap fill (lyr_idx == 2), adds bbox stubs to per-net shape collection
4. Gap fill then detects and bridges the same-net gaps (M3 fills went 44→48)

**Result**: M3.b 4→0 (-4), total 9→5 (-4), zero regressions

### Fixed R22d: M2.c1=3→0, V2.c1=1→0 (-4)
Root causes:
1. solver.py `punch_net_holes()` M2 pin-center exemption was too broad (center+vicinity → center cell only). Fixed 2 M2.c1 + 1 V2.c1.
2. solver.py `_reblock_ap_m2_pads()`: new function. `_signal_escape_recheck()` with `add_pin_escape(all_directions=True)` clears soft blocks along escape channels, which can remove AP M2 pad blocking. This re-blocks M2-only around all APs after escape recheck. Fixed remaining M2.c1 (M_db2_n.G/f_exc_b).
3. optimize.py `bridge_m2_over_aps()`: new function. Detects M2 wires through cross-net AP M2 pads and bridges on M3 via Via2→M3→Via2. Correctly detected M3 power vbar conflict for M_db2_n.G case and skipped (not needed after solver fix).

**Important discovery**: R22b one-off fix (manual M3 bridge in routing.json) had a HIDDEN M3 SHORT CIRCUIT — the M3 bridge overlapped a gnd M3 vbar at x=149030. DRC didn't catch it because it's flat (no net awareness). Would have been caught by LVS.

### Previously fixed
- M2.c1=3→0, V2.c1=1→0: Fixed R22d (solver pin_centers + _reblock_ap_m2_pads)
- Cnt.d=4, CntB.b2=3, Rhi.d=2, Rppd.c=1: Fixed R21 (resistor gate strap filter)
- M3.a=26→0: Fixed R17 (bbox approach)

## Verification (每轮)

```bash
cd /private/tmp/analog-trial/layout && source ~/pdk/venv/bin/activate
python3 solve_routing.py    # 133/133 routes
python3 -m atk.route.optimize
klayout -n sg13g2 -zz -r assemble_gds.py
python3 ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py \
    --path=output/ptat_vco.gds --topcell=ptat_vco \
    --run_dir=/tmp/drc_ci_verify --mp=1 --no_density
```

## Key Files

| File | Role |
|------|------|
| `layout/atk/route/power.py` | M3 vbar conflict resolution, M2 drop spacing |
| `layout/assemble_gds.py` | GDS assembly, fill shapes, gap fills |
| `layout/atk/route/optimize.py` | M4 straightening, obstacle model |
| `layout/atk/route/solver.py` | Maze router, obstacle blocking |
| `layout/atk/pdk.py` | DRC constants |

## Progress Log

| Round | Change | Before | After | Delta | Notes |
|-------|--------|--------|-------|-------|-------|
| 0 | baseline | - | 229 | - | 已记录 per-rule counts |
| 1 | MIN_M3_SEP 200→410 | 229 | ~177 | ~-52 | M3.b 94→44 (推测, 含其他changes) |
| 2 | pad-aware jog, MAX_JOG=420, MAX_M2_HEIGHT=50µm | ~229 | 177 | - | routing frozen baseline |
| 3 | _fill_same_net_gaps enhancement | 177 | 142 | -35 | M3.b 44→18, M3.e 4→2 |
| 4 | M4 L-corner trim + solver cleanup | 142 | 109 | -33 | M4.b 20→0, M1.b 13→6, M1.a 8→2 |
| 5 | M2 underpass minimize (vbar narrow+dedup+pad eliminate) | 109 | 78 | -31 | M2.b 58→27, zero regressions |
| 11 | (R5→R11 intermediate rounds) | 78 | 43 | -35 | M2.b→12, M3.b→11, NW.b1→6, NW.b→1 |
| 12b | Router M3 spacing fix (pin_terminal, M3 obstacle) | 43 | 42 | -1 | M3.b 11→5 but M2.b+2, M1.a+2, M1.b+1 |
| 12h-j | M3 jog gap fill + M1 min_w guard + escape fix | 42 | 41 | -1 | M3.b 5→4, other regressions unchanged |
| 14e | M1 L-corner extension (optimize.py) | 41 | 36 | -5 | M1.a 4→2, M1.b 8→5, zero regressions |
| 15 | NWell notch close (morphological, NW.b) | 36 | 35 | -1 | NW.b 1→0, NW.b1 unfixable (NMOS in gap) |
| 17 | M3.a bbox: pad+stubs → single bbox rect (assemble_gds.py) | 96 | 70 | -26 | Maximal deck: M3.a 26→0, zero regressions |
| 18 | M1 AP pad shrink 370→310nm (pdk.py VIA1_GDS_M1 + assemble_gds.py) | 70 | 45 | -25 | M1.b 32→4 (-28), M1.a 0→3 (+3). Gap fill updated for shrunk pads |
| 19 | NWell bridge A (tie_M_ia_p_ntap ↔ pmos$1) | 45 | 43 | -2 | NW.b1 6→4 |
| 20 | M2 AP+power pad shrink (GDS-based BFS + strict validation) | 43 | 37 | -6 | M2.b 12→6 (-6). Pass 1: AP pads (5 shrunk). Pass 2: non-AP ≥400nm pads (3 shrunk). Zero regressions |
| 21 | Skip resistor gate straps (pcell!=nmos/pmos filter) | 37 | 27 | -10 | Cnt.d 4→0, CntB.b2 3→0, Rhi.d 2→0, Rppd.c 1→0. Root cause: get_ng2_gate_data() classified resistors as ng=2 MOSFETs |
| 22d | solver pin_centers M2 fix + _reblock_ap_m2_pads() + bridge_m2_over_aps() | 27 | 19 | -8 | M2.c1 3→0, V2.c1 1→0, M2.b 6→2 |
| 23d | Bus strap bridge area enforce + via/wire M1 obstacle check | 19 | 15 | -4 | M1.d 2→0, M1.b 4→2 (bus strap proximity) |
| 24c | AP M1 pad extend for offset routing vias | 15 | 11 | -4 | M1.a 3→0, M1.b 2→1 (grid quantization fix) |
| 25c | Tie M1 proximity trim (assemble_gds.py) | 11 | 10 | -1 | M1.b 1→0. Root cause: pin_terminal exemption cleared tie M1 block |
| 26c | Duplicate M2 removal + gap fill fix | 10 | 9 | -1 | M2.b 2→1. Remaining: placement-constrained (via sep 490nm < 500nm) |
| **27** | **AP Via2 M3 bbox stub gap fill** | **9** | **5** | **-4** | **M3.b 4→0. All same-net gaps bridged. Remaining 5 = placement-constrained** |
| **31** | **LVS: M3/M4 bus bridge + stub skip** | **5+merges** | **5+0** | **0 merges** | **ns\|vco: M3/M4 drain bus bridge. vco_out\|vdd: source bus stub skip. DRC unchanged** |
| **32d** | **LVS: +1N bridge + +1R ref fix** | **5+0** | **5+0** | **device match** | **MN2 M4 bridge (via1_m1_obs detection + via3 shift). Rout rppd ref fix (L=25.915u). 121N/124P/1rppd/3rhigh MATCH** |
