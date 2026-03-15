# Progress & Decision Log

> Read this after compact to restore context.

---

## Current Status (2026-03-15 19:50 — SUCCESS)

### LVS MERGED GROUPS = 0 ✅

| Metric | Value |
|--------|:---:|
| Merged groups | **0** |
| NMOS bulk | **all gnd** ✅ |
| PMOS bulk | **all vdd (17/17)** ✅ |
| Net mismatches | 8 |
| Routing | 128/132 (reduced due to incomplete power topology) |
| Tie M1 trimmed | 71 |

### How it was achieved

**2 edits to clean L2-era assemble_gds.py**:

1. **M3 vbar truncation** (line 1054): use `m3v[1]/m3v[3]` (truncated from power.py) instead of `pin_y/rail_y` (full range)

2. **Tie M1 trim mechanism** (lines 912-990): Before drawing tie M1, check for overlap with:
   - Routing M1 wires + via1 pads (threshold -200nm)
   - Signal AP M1 stubs
   - Cross-net power drop M1 shapes (only trim if power net ≠ tie net)
   - tie_net = 'vdd' if 'ntap' else 'gnd' (correct direction)
   - M1.d min area protection
   - Cont enclosure check (drop Conts outside trimmed M1)

### Root cause (PROVEN)

gnd↔vdd merge was 100% through `connect(pwell, ptap)` in LVS.
ptap Conts sat on M1 shapes connected to vdd metal chain.
pwell inherited both gnd AND vdd labels → merge.

**Proven by**: removing all ptap PSD → merged=0 (custom Ruby LVS).
**Fixed by**: tie M1 trim prevents routing/power M1 from overlapping tie M1 bars.

### Files changed (to commit)

| File | Edit | Description |
|------|:---:|-------------|
| assemble_gds.py | 1 | M3 vbar truncation (line 1054) |
| assemble_gds.py | 2 | Tie M1 trim mechanism (lines 912-990) |
| netlist.json | — | Reconstructed SoilZ version |

### Remaining work

1. **Improve routing**: only 128/132 (was 132/133). Power topology reconstruction is incomplete (36 drops vs original 153)
2. **DRC**: not yet run on new GDS
3. **LVS 8 mismatches**: likely from incomplete routing + missing power drops
4. **Commit** the working assemble_gds.py + netlist.json
