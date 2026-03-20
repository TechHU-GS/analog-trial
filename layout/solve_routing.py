#!/usr/bin/env python3
"""Phase 4 entry — route power + signal nets, output routing.json.

Usage:
    source ~/pdk/venv/bin/activate
    python solve_routing.py

Reads:
    placement.json  — Phase 2 device placement (from atk.paths)
    ties.json       — Phase 3 tie cells (from atk.paths)
    netlist.json    — net definitions + routing constraints

Writes:
    routing.json    — to WORK_DIR (from atk.paths)
"""

import json
import os
import sys

# Add layout dir to path for atk imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from atk.paths import PLACEMENT_JSON, NETLIST_JSON, TIES_JSON, ROUTING_JSON
from atk.route.solver import RoutingSolver


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    # Load inputs — all paths from atk.paths (single source of truth)
    placement = load_json(PLACEMENT_JSON)
    netlist = load_json(NETLIST_JSON)

    ties = load_json(TIES_JSON) if os.path.exists(TIES_JSON) else None

    print(f'Placement: {len(placement["instances"])} instances')
    print(f'Netlist: {len(netlist["nets"])} nets')
    print(f'Ties: {len(ties["ties"]) if ties else 0} ties')
    print()

    # Solve
    solver = RoutingSolver(placement, ties, netlist)
    seed = int(os.environ['ROUTE_SEED']) if 'ROUTE_SEED' in os.environ else None
    solver.solve(seed=seed)

    # Gate checks
    n_pass, n_total, errors = solver.verify()

    # Write output
    with open(ROUTING_JSON, 'w') as f:
        json.dump(solver.to_json(), f, indent=2)
    print(f'\nWritten: {ROUTING_JSON}')

    if n_pass < n_total:
        print(f'\nWARNING: {n_total - n_pass} gate check(s) FAILED')
        sys.exit(1)


if __name__ == '__main__':
    main()
