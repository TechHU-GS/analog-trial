---
name: LVS Fix Log
description: Analog-trial LVS fixes — net merges, device count (+1N/+1R), bridge detection, reference generator
type: project
---

# LVS Fix Log (2026-03-14)

## Current Status (R32d)

- **Device counts: MATCH** — 121N, 124P, 1rppd, 3rhigh (extracted = reference)
- **Merged nets: 0** (was 5+)
- **DRC: 5** (unchanged, placement-constrained)
- **Net topology: ~407 mismatched** (pre-existing, not from device/merge fixes)

## Fix 1: ns|vco merges (VCO stages 1-5) — R31

**Root cause**: Mpb drain bus M2 bridge spans across Mpu.D AP Via1 M2 pad → M2 short.

**Solution**: Check `_ap_via1_m2_obs` for M2 conflict, escalate to M3/M4 bridge.
- Mpb2, Mpb4, Mpb5: M3 bridge
- Mpb1, Mpb3: M4 bridge (M3 blocked)

## Fix 2: vco_out|vdd merge — R31

**Root cause**: MBp2 source bus stub overlaps MBn2.D AP M1 pad → M1 short.

**Solution**: Skip source bus stubs that overlap cross-net AP M1 pads.

## Fix 3: +1N (MN2 device split) — R32d

**Root cause**: `_draw_gapped_bus()` cuts drain bus gaps using both `_ap_m1_obs` AND `_via1_m1_obs`, but bridge detection (line 2010) only checked `_ap_m1_obs`. MN2 (nmos_vittoz8, 8 fingers) drain bus gap from nmos_bias routing Via1/wire at (52250-54800, 149450-149750) went unbridged → KLayout extracted 2x W=8u instead of 1x W=16u.

**Solution (assemble_gds.py)**:
1. Added `_via1_m1_obs` check to bridge detection loop (mirrors `_draw_gapped_bus`)
2. Added `_via1_m2_obs` list (routing Via1 M2 pads) to M2 bridge conflict check
3. M4 bridge with Via3 endpoint shifting: checks M3 clearance at each Via3 endpoint, shifts toward gap center in 50nm steps if blocked, also checks M1 spacing vs drain strip edges
4. MN2 result: Via3 endpoint shifted 49005→49455 (vdd M3 vbar at x=48810 blocks original position; drain strip D1 right edge at 49085 constrains M1 spacing)

## Fix 4: +1R (Rout missing from reference) — R32d

**Root cause**: `gen_lvs_reference.py` had a stale rppd skip (pre-ECO workaround for polyres_drw crossing MOSFET). After Rout ECO (x=36→10), the skip is unnecessary.

**Solution**:
1. Removed rppd skip block (lines 140-147)
2. Added extracted L correction: `_RPPD_EXTRACTED_L = {25.0: 25.915}` (KLayout extracts 25.915u physical length for PCell L=25.0u)
3. Reference now outputs: `RRout vptat gnd rppd w=0.5u l=25.915u b=4 m=1`

## Key Data Structures

- `_ap_m1_obs`: AP M1 stubs/pads — bus gap cutting + stub skip
- `_ap_via1_m2_obs`: AP Via1 M2 pads — M2 bridge conflict check
- `_via1_m1_obs`: Routing via M1 pads + M1 wires — bus gap cutting + bridge detection
- `_via1_m2_obs`: Routing Via1 M2 pads — M2 bridge conflict check (NEW)
- `_m3_obs_bus`: Routing M3 obstacles — M3 bridge + Via3 endpoint clearance
- `_bus_m3_bridges`: Collected M3/M4 bridge M3 pads — obstacles for `_add_missing_ap_via2()`

## Remaining: Net Topology Mismatches (~407)

19/255 devices match, 45/452 nets match, 223/223 pins match.
Pre-existing connectivity issues — layout routing doesn't fully match reference netlist topology.
Next investigation target.
