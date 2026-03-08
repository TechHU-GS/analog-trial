#!/bin/bash
# Run 9-corner VCO simulation: 3 MOS × 3 RES (cap_typ fixed)
# Checks oscillation at 27C for each corner
# Usage: bash run_corners.sh

set -e
cd "$(dirname "$0")"

CIRCUIT=cmos_ptat_vco.sp
PASS=0
FAIL=0
RESULTS=""

run_corner() {
    local mos=$1 res=$2 label=$3

    cat > _pdk_corner.inc <<EOF
.lib cornerMOSlv.lib $mos
.lib cornerRES.lib $res
.lib cornerCAP.lib cap_typ
EOF

    sed "s|'pdk.inc'|'_pdk_corner.inc'|" "$CIRCUIT" > _corner_run.sp

    output=$(ngspice -b _corner_run.sp 2>&1)

    freq=$(echo "$output" | grep -o 'Freq = [0-9.]*' | head -1 | awk '{print $3}')
    no_osc=$(echo "$output" | grep "NO OSCILLATION" | head -1)

    if [ -n "$freq" ]; then
        PASS=$((PASS + 1))
        RESULTS="${RESULTS}  PASS  ${label}  ${freq} MHz\n"
    else
        FAIL=$((FAIL + 1))
        RESULTS="${RESULTS}  FAIL  ${label}  NO_OSC\n"
    fi
}

echo "Running 9-corner VCO simulation..."
echo ""

run_corner mos_tt res_typ "tt/typ"
run_corner mos_ss res_typ "ss/typ"
run_corner mos_ff res_typ "ff/typ"
run_corner mos_tt res_bcs "tt/bcs"
run_corner mos_tt res_wcs "tt/wcs"
run_corner mos_ss res_wcs "ss/wcs"
run_corner mos_ff res_bcs "ff/bcs"
run_corner mos_sf res_typ "sf/typ"
run_corner mos_fs res_typ "fs/typ"

rm -f _pdk_corner.inc _corner_run.sp

echo "============================================================"
echo "9-Corner Results (27C)"
echo "============================================================"
echo -e "$RESULTS"
echo "------------------------------------------------------------"
echo "PASS: $PASS / $((PASS + FAIL))"
if [ $FAIL -gt 0 ]; then
  echo "FAIL: $FAIL corners did not oscillate"
  exit 1
else
  echo "ALL CORNERS PASS"
fi
