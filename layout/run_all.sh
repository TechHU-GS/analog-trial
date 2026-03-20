#!/bin/bash
# ATK End-to-End Runner: Phase 2→6 automated pipeline
# Usage: cd /private/tmp/analog-trial/layout && source ~/pdk/venv/bin/activate && bash run_all.sh
set -euo pipefail

CELL="soilz"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GDS="${SCRIPT_DIR}/output/${CELL}.gds"
CDL="${SCRIPT_DIR}/${CELL}_lvs.spice"
LVS_DIR="/tmp/lvs_run"
DRC_DIR="/tmp/drc_run"
PDK_ROOT="${PDK_ROOT:-$HOME/pdk/IHP-Open-PDK}"

echo "============================================================"
echo "ATK End-to-End Pipeline: ${CELL}"
echo "============================================================"
echo ""

# --- Phase 2: CP-SAT Placement ---
if [ ! -f placement.json ]; then
    echo "=== Phase 2: Placement ==="
    python3 solve_placement.py
else
    echo "=== Phase 2: Placement (skipped — placement.json exists) ==="
fi
echo ""

# --- Phase 3: Tie Cell Placement ---
echo "=== Phase 3: Ties ==="
python3 solve_ties.py
echo ""

# --- Phase 4: Signal Routing ---
if [ ! -f output/routing.json ]; then
    echo "=== Phase 4: Routing ==="
    python3 solve_routing.py || true  # gate warning (HBT pre-route disabled) is non-fatal
    echo ""
    echo "=== Phase 4b: Route Optimization ==="
    python3 -m atk.route.optimize
else
    echo "=== Phase 4: Routing (skipped — routing.json exists) ==="
fi
echo ""

# --- Phase 5: GDS Assembly ---
echo "=== Phase 5: GDS Assembly ==="
klayout -n sg13g2 -zz -r assemble_gds.py
echo ""

# --- Phase 5b: DRC ---
echo "=== Phase 5b: DRC ==="
rm -rf "${DRC_DIR}"
mkdir -p "${DRC_DIR}"
python3 "${PDK_ROOT}/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py" \
    --path="${GDS}" \
    --topcell="${CELL}" \
    --run_dir="${DRC_DIR}" \
    --mp=1 --no_density 2>&1 | tail -5 || true  # DRC violations are reported, not fatal
echo ""

# --- Phase 6: LVS ---
echo "=== Phase 6: LVS ==="
rm -rf "${LVS_DIR}"
mkdir -p "${LVS_DIR}"
python3 "${PDK_ROOT}/ihp-sg13g2/libs.tech/klayout/tech/lvs/run_lvs.py" \
    --layout="${GDS}" \
    --netlist="${CDL}" \
    --run_dir="${LVS_DIR}" \
    --topcell="${CELL}" \
    --allow_unmatched_ports 2>&1 | tail -5 || true  # LVS result in summary
echo ""

# --- Phase 7: LVS Diagnosis ---
echo "=== Phase 7: LVS Diagnosis ==="
python3 -m atk.diagnose_lvs \
    --lvsdb="${LVS_DIR}/${CELL}.lvsdb" \
    --output=output/lvs_report.json 2>&1 || true
echo ""

# --- Summary ---
echo "=== Results Summary ==="
python3 -m atk.summary \
    --placement=placement.json \
    --drc-dir="${DRC_DIR}" \
    --lvs-dir="${LVS_DIR}" \
    --cell="${CELL}"
