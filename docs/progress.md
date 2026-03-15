# Progress & Decision Log

> Read this after compact to restore context.

---

## Current Status (2026-03-15 19:25 — SESSION END)

### PROVEN FINDINGS (high confidence)

1. **gnd↔vdd merge is 100% through `connect(pwell, ptap)`**
   - Removing ptap PSD from ALL 121 ptap ties → merged groups = 0 (VERIFIED)
   - `connect(pwell, ptap)` ON → merge; OFF → separate (VERIFIED by custom LVS bisection)

2. **The bridge mechanism**: ptap Conts sit on M1 shapes that connect (through via stack) to vdd M3 rail. When pwell connects to ptap through the LVS rule, pwell inherits BOTH gnd and vdd labels → merge.

3. **Binary search found `tie_MBn1_ptap`** as one specific bridge (ptap #4 of 121). There are likely MANY more bridges — the design has no tie trim protection.

4. **Custom Ruby LVS scripts** find things Python shapely/Region CANNOT:
   - KLayout found psd_ntap_abutt=7 (Python found 0)
   - KLayout bisection definitively proved pwell↔ptap is the trigger
   - Binary search via PSD removal is effective

### KEY DIAGNOSTIC SCRIPTS (save these!)

All in /tmp/ — **COPY TO PROJECT before session ends**:
- `debug_extract.lvs` — custom LVS with derived layer logging
- `debug_find_ptap_vdd.lvs` — trace ptap→vdd chain
- `debug_find_pmos_bias.lvs` — trace ntap→gnd and signal bridges
- `debug_isolated_wells.lvs` — bisection: wells disconnected from taps
- `debug_ptap_only.lvs` / `debug_ntap_only.lvs` — individual well connectivity test
- `find_all_abutt.lvs` — find salicide abutment points

### CURRENT GDS STATE: CORRUPTED

The output/ptat_vco.gds has accumulated ~10 ad-hoc modifications:
- SalBlock additions (4 locations)
- Cont removal (BUF_I ptap + MBn1 ptap)
- PSD removal (108) then restore (121)
- Via1 removal (pmos_bias bridge)
- M2 pad removal (pmos_bias bridge)
- Placement widening (136 devices pushed)

**DO NOT use this GDS for further work.** Re-run assembly from clean state.

### FILE STATE

| File | State | Action needed |
|------|-------|--------------|
| maze_router.py | Via encoding fix ✅ | Keep |
| assemble_gds.py | CLEAN L2 era | Need 5 bug fixes + tie trim |
| netlist.json | PARTIALLY RECONSTRUCTED | Need full reconstruction or backup |
| placement.json | MODIFIED + .bak backup | Restore from .bak |
| output/ptat_vco.gds | CORRUPTED | Re-generate from assembly |
| /tmp/*.lvs | Diagnostic scripts | Copy to project |

### NEXT SESSION PLAN

1. **Restore clean state**:
   - `cp placement.json.bak placement.json`
   - Re-run assembly with clean inputs

2. **Apply tie trim to assembly** (5 bug fixes, clean implementation):
   - tie_net: 'vdd' if 'ntap' else 'gnd'
   - M3 vbar: vbar_y1/vbar_y2 truncation
   - Routing M1 trim: -200nm threshold
   - Signal AP stubs: add to trim check
   - (Via encoding already in maze_router.py)

3. **Add systematic Cont protection**:
   - Use binary search method (PSD removal + LVS) to find ALL bridge ptaps
   - Remove their Conts in assembly
   - OR: add tie trim that catches ALL M1 overlaps

4. **Verify**: merged groups = 0

### SESSION LEARNINGS

1. **Custom Ruby LVS >> Python shapely** for FEOL analysis
2. **LVS bisection** (remove connect() rules) is definitive
3. **PSD removal** proves ptap is the sole bridge path
4. **Binary search** (restore PSD groups) finds specific bridges
5. **One-by-one Cont removal** is mole-whacking — need systematic approach
6. **Ad-hoc GDS modifications** corrupt state — always re-run assembly
7. **NEVER git checkout without backup** (netlist.json loss)
