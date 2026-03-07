#!/bin/bash
# Run PTAT core across all PVT corners
# Usage: bash run_corners.sh

cd "$(dirname "$0")"

PASS=0
FAIL=0

run_corner() {
    local mos=$1 hbt=$2 res=$3 label=$4

    cat > _corner_tmp.sp << EOF
* Corner: $label
.include ptat_core.sp
.lib cornerMOSlv.lib $mos
.lib cornerHBT.lib $hbt
.lib cornerRES.lib $res
.lib cornerCAP.lib cap_typ

Xdut vdd vptat vbe 0 ptat_core
Vdd vdd 0 DC 1.8

.option method=gear gmin=1e-12 abstol=1e-12 reltol=1e-3 itl1=300 itl4=50

.dc TEMP -40 125 5

.control
run
echo "CORNER: $label"
echo "VPTAT_27C:"
print v(vptat)[13]
echo "VBE_27C:"
print v(vbe)[13]
echo "VPTAT_RANGE:"
print v(vptat)[0] v(vptat)[33]
quit
.endc
.end
EOF

    output=$(ngspice -b _corner_tmp.sp 2>&1)
    if echo "$output" | grep -q "VPTAT_27C"; then
        echo "[$label] PASS"
        echo "$output" | grep -A1 "VPTAT_27C\|VBE_27C\|VPTAT_RANGE" | grep -v "^--$"
        PASS=$((PASS+1))
    else
        echo "[$label] FAIL — did not converge"
        echo "$output" | tail -5
        FAIL=$((FAIL+1))
    fi
    echo ""
}

echo "========================================="
echo "  PTAT CORE — PVT CORNER SWEEP"
echo "========================================="
echo ""

# 9 corners: 3 MOS x 3 HBT (res_typ fixed)
run_corner mos_tt hbt_typ res_typ "TT-TYP"
run_corner mos_ss hbt_typ res_typ "SS-TYP"
run_corner mos_ff hbt_typ res_typ "FF-TYP"
run_corner mos_tt hbt_bcs res_typ "TT-BCS"
run_corner mos_tt hbt_wcs res_typ "TT-WCS"
run_corner mos_ss hbt_wcs res_typ "SS-WCS"
run_corner mos_ff hbt_bcs res_typ "FF-BCS"
run_corner mos_tt hbt_typ res_bcs "TT-TYP-RBCS"
run_corner mos_tt hbt_typ res_wcs "TT-TYP-RWCS"

echo "========================================="
echo "  SUMMARY: $PASS PASS, $FAIL FAIL"
echo "========================================="

rm -f _corner_tmp.sp
