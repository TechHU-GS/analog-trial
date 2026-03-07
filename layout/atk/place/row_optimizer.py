"""Automatic row ordering optimizer.

Finds the row permutation that minimizes weighted inter-row wire length,
then computes per-channel track counts from crossing-net analysis.

Supports NWell adjacency constraints: rows sharing a NWell island get
a large bonus weight to keep them close.

Usage:
    from atk.place.row_optimizer import optimize_row_order
    order, channels = optimize_row_order(netlist)
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict


def _build_weight_matrix(
    row_groups: dict[str, list[str]],
    nets: list[dict],
    nwell_islands: list[dict] | None = None,
    nwell_weight: int = 10,
) -> dict[tuple[str, str], int]:
    """Build row-pair weight matrix from net connectivity + NWell adjacency.

    W[(row_a, row_b)] = number of nets connecting both rows
                      + nwell_weight if rows share a NWell island.
    """
    dev_to_row: dict[str, str] = {}
    for rname, devs in row_groups.items():
        for d in devs:
            dev_to_row[d] = rname

    weights: dict[tuple[str, str], int] = defaultdict(int)

    # Signal + power net connectivity
    for net in nets:
        rows_in_net: set[str] = set()
        for pin in net["pins"]:
            dev = pin.split(".")[0]
            if dev in dev_to_row:
                rows_in_net.add(dev_to_row[dev])
        rows_list = sorted(rows_in_net)
        for i in range(len(rows_list)):
            for j in range(i + 1, len(rows_list)):
                key = (rows_list[i], rows_list[j])
                weights[key] += 1

    # NWell adjacency bonus: rows sharing NWell island should be close
    if nwell_islands:
        for island in nwell_islands:
            devs = island.get("devices", [])
            island_rows: set[str] = set()
            for d in devs:
                if d in dev_to_row:
                    island_rows.add(dev_to_row[d])
            island_rows_list = sorted(island_rows)
            for i in range(len(island_rows_list)):
                for j in range(i + 1, len(island_rows_list)):
                    key = (island_rows_list[i], island_rows_list[j])
                    weights[key] += nwell_weight

    return dict(weights)


def _eval_cost(
    order: tuple[str, ...],
    weights: dict[tuple[str, str], int],
) -> int:
    """Evaluate weighted inter-row distance for a given row ordering."""
    pos = {name: i for i, name in enumerate(order)}
    cost = 0
    for (a, b), w in weights.items():
        cost += w * abs(pos[a] - pos[b])
    return cost


def _find_optimal_order(
    row_names: list[str],
    weights: dict[tuple[str, str], int],
) -> tuple[str, ...]:
    """Find optimal row ordering by exhaustive search (≤12 rows) or greedy."""
    n = len(row_names)

    if n <= 12:
        best_cost = float("inf")
        best_order = tuple(row_names)
        for perm in itertools.permutations(row_names):
            c = _eval_cost(perm, weights)
            if c < best_cost:
                best_cost = c
                best_order = perm
        return best_order
    else:
        # Greedy nearest-neighbor for large row counts
        row_weight_sum: dict[str, int] = defaultdict(int)
        for (a, b), w in weights.items():
            row_weight_sum[a] += w
            row_weight_sum[b] += w

        remaining = set(row_names)
        start = max(remaining, key=lambda r: row_weight_sum.get(r, 0))
        order = [start]
        remaining.remove(start)

        while remaining:
            best_next = None
            best_w = -1
            for r in remaining:
                w = sum(
                    weights.get(tuple(sorted([r, placed])), 0)
                    for placed in order
                )
                if w > best_w:
                    best_w = w
                    best_next = r
            order.append(best_next)
            remaining.remove(best_next)

        return tuple(order)


def _count_crossing_nets(
    order: tuple[str, ...],
    nets: list[dict],
    row_groups: dict[str, list[str]],
    power_nets: set[str] | None = None,
) -> list[dict]:
    """Count signal nets crossing each adjacent row boundary.

    Power nets (M3 routed) are excluded from track count.
    """
    dev_to_row: dict[str, str] = {}
    for rname, devs in row_groups.items():
        for d in devs:
            dev_to_row[d] = rname

    pos = {name: i for i, name in enumerate(order)}
    n = len(order)
    if power_nets is None:
        power_nets = set()

    crossing = [0] * (n - 1)

    for net in nets:
        if net["name"] in power_nets:
            continue  # Power uses M3 rails, not signal channels
        rows_in_net: set[str] = set()
        for pin in net["pins"]:
            dev = pin.split(".")[0]
            if dev in dev_to_row:
                rows_in_net.add(dev_to_row[dev])
        if len(rows_in_net) < 2:
            continue
        positions = sorted(pos[r] for r in rows_in_net)
        min_pos, max_pos = positions[0], positions[-1]
        for i in range(min_pos, max_pos):
            crossing[i] += 1

    channels = []
    for i in range(n - 1):
        n_tracks = max(crossing[i], 2)
        channels.append({
            "above": order[i],
            "below": order[i + 1],
            "n_tracks": n_tracks,
            "crossing_nets": crossing[i],
        })

    return channels


def optimize_row_order(
    netlist: dict,
) -> tuple[list[str], list[dict], int, int]:
    """Optimize row ordering from netlist.json data.

    Returns:
        (row_order, routing_channels, old_cost, new_cost)
    """
    row_groups_raw = netlist["constraints"]["row_groups"]

    # Normalize row_groups
    row_groups: dict[str, list[str]] = {}
    for rname, info in row_groups_raw.items():
        if isinstance(info, dict):
            row_groups[rname] = info["devices"]
        else:
            row_groups[rname] = info

    nets = netlist["nets"]
    row_names = list(row_groups.keys())

    # Extract NWell islands for adjacency constraint
    nwell_islands = None
    well_cfg = netlist.get("constraints", {}).get("well_aware_spacing", {})
    if "nwell_islands" in well_cfg:
        nwell_islands = well_cfg["nwell_islands"]

    # Extract power net names
    power_nets = set()
    for net in nets:
        if net.get("type") == "power":
            power_nets.add(net["name"])

    # Build weights (including NWell adjacency bonus)
    weights = _build_weight_matrix(row_groups, nets, nwell_islands)

    # Current cost
    current_order = tuple(row_names)
    old_cost = _eval_cost(current_order, weights)

    # Optimal order
    optimal_order = _find_optimal_order(row_names, weights)
    new_cost = _eval_cost(optimal_order, weights)

    # Channel sizing (excluding power nets)
    channels = _count_crossing_nets(optimal_order, nets, row_groups, power_nets)

    return list(optimal_order), channels, old_cost, new_cost


def main():
    """CLI: optimize row order from netlist.json."""
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "netlist.json"
    with open(path) as f:
        netlist = json.load(f)

    order, channels, old_cost, new_cost = optimize_row_order(netlist)

    print(f"Row count: {len(order)}")
    print(f"Old cost (original order): {old_cost}")
    print(f"New cost (optimized):      {new_cost}")
    print(f"Improvement: {old_cost - new_cost} ({100*(old_cost-new_cost)/old_cost:.1f}%)")
    print()
    print("Optimal row order (top → bottom):")
    for i, r in enumerate(order):
        print(f"  {i}: {r}")
    print()
    print("Routing channels:")
    for ch in channels:
        print(
            f"  {ch['above']:15s} ↔ {ch['below']:15s}: "
            f"{ch['n_tracks']} tracks ({ch['crossing_nets']} crossing nets)"
        )


if __name__ == "__main__":
    main()
