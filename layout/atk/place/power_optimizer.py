"""Automatic power rail topology optimizer.

Given placement + netlist (which pins connect to which power net),
auto-computes:
  1. How many M3 rails per power net and where (Y clustering)
  2. Each drop's strategy (via_access vs via_stack) and which rail to use
  3. M2 vbar collision detection across different nets

Usage:
    from atk.place.power_optimizer import optimize_power_topology
    topo = optimize_power_topology(netlist, placement)
    # topo is a power_topology dict ready for netlist.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict


# Maximum M2 vbar length before we need a closer rail (µm)
_MAX_VBAR_UM = 20.0

# via_stack only works if device is within this distance of rail (µm)
_VIA_STACK_MAX_UM = 5.0

# M2 vbar collision half-width (nm) — M2_SIG_W/2 + M2_MIN_S + M2_SIG_W/2
_VBAR_BLOCK_HALF_NM = 510

# M3 power rail width (nm)
_M3_PWR_W_NM = 3000

# Minimum gap between M3 rails of different nets (nm)
_M3_RAIL_GAP_NM = 1000


def _collect_power_pins(netlist: dict) -> dict[str, list[dict]]:
    """Collect all power pins grouped by net name.

    Returns: {net_name: [{inst, pin}, ...]}
    """
    pins_by_net: dict[str, list[dict]] = defaultdict(list)
    for net in netlist["nets"]:
        if net.get("type") != "power":
            continue
        net_name = net["name"]
        for pin_str in net["pins"]:
            inst, pin = pin_str.split(".")
            pins_by_net[net_name].append({"inst": inst, "pin": pin})
    return dict(pins_by_net)


def _get_pin_y(placement: dict, inst: str, pin: str = "",
               netlist: dict | None = None) -> float:
    """Get estimated pin Y in µm from placement.

    Uses pin_access info to determine if pin exits above (top) or below (bottom).
    Falls back to device center if no access info available.
    """
    info = placement["instances"][inst]
    dev_type = info.get("type", "")

    # Try to determine pin access direction from netlist
    if netlist and dev_type:
        pin_access = netlist.get("constraints", {}).get("pin_access", {})
        dev_access = pin_access.get(dev_type, {})
        mode = dev_access.get(pin, "")
        if mode in ("above", "gate"):
            return info["y_um"] + info["h_um"]  # top of device
        elif mode in ("below", "m2_below"):
            return info["y_um"]  # bottom of device

    # Default: device center
    return info["y_um"] + info["h_um"] / 2


def _cluster_rails(
    net_name: str,
    pins: list[dict],
    placement: dict,
    max_vbar_um: float = _MAX_VBAR_UM,
    netlist: dict | None = None,
) -> list[dict]:
    """Determine how many rails this net needs and where.

    Simple greedy: sort pins by Y, sweep and split when gap > max_vbar_um.
    Each cluster gets one rail at its centroid Y.
    """
    # Get Y positions of all pins (using pin access direction)
    pin_ys = []
    for p in pins:
        y = _get_pin_y(placement, p["inst"], p["pin"], netlist)
        pin_ys.append(y)

    if not pin_ys:
        return []

    # Sort and cluster
    indexed = sorted(enumerate(pin_ys), key=lambda t: t[1])
    clusters: list[list[int]] = [[indexed[0][0]]]
    cluster_ys: list[list[float]] = [[indexed[0][1]]]

    for i in range(1, len(indexed)):
        idx, y = indexed[i]
        if y - cluster_ys[-1][-1] > max_vbar_um:
            clusters.append([])
            cluster_ys.append([])
        clusters[-1].append(idx)
        cluster_ys[-1].append(y)

    # Build rails — one per cluster
    rails = []
    for ci, (cl_indices, cl_y_vals) in enumerate(zip(clusters, cluster_ys)):
        # Rail at centroid of cluster, offset 3µm below min or above max
        y_min = min(cl_y_vals)
        y_max = max(cl_y_vals)
        y_mid = (y_min + y_max) / 2

        # Place rail at edge of cluster (bottom for GND, top for VDD)
        # Use centroid as default, caller can override
        rail_id = f"{net_name}" if len(clusters) == 1 else f"{net_name}_{ci}"
        rails.append({
            "id": rail_id,
            "net": net_name,
            "y_um": round(y_mid, 2),
            "y_min_um": round(y_min, 2),
            "y_max_um": round(y_max, 2),
            "pin_indices": cl_indices,
            "n_pins": len(cl_indices),
        })

    return rails


def _has_signal_pin_between(inst: str, power_pins: list[str],
                             netlist: dict) -> bool:
    """Check if device has a signal pin (D) squeezed between power pins (S1/S2).

    via_stack on S1+S2 would trap D's escape route → force via_access.
    """
    if not netlist:
        return False
    # Find device type
    dev_type = ""
    for dev in netlist.get("devices", []):
        if dev["name"] == inst:
            dev_type = dev["type"]
            break
    if not dev_type:
        return False

    pin_access = netlist.get("constraints", {}).get("pin_access", {})
    dev_access = pin_access.get(dev_type, {})

    # Check if device has both S1/S2 (or S+S2) as power and D as signal
    pwr_set = set(power_pins)
    has_flanking = ({"S1", "S2"} <= pwr_set) or ({"S", "S2"} <= pwr_set)
    has_drain = "D" in dev_access and "D" not in pwr_set
    return has_flanking and has_drain


def _assign_drops(
    net_name: str,
    pins: list[dict],
    rails: list[dict],
    placement: dict,
    netlist: dict | None = None,
) -> list[dict]:
    """Assign each pin to nearest same-net rail, choose strategy."""
    # Collect power pins per instance for pin-trapping check
    inst_power_pins: dict[str, list[str]] = defaultdict(list)
    for p in pins:
        inst_power_pins[p["inst"]].append(p["pin"])

    drops = []
    for i, p in enumerate(pins):
        pin_y = _get_pin_y(placement, p["inst"], p["pin"], netlist)

        # Find nearest rail
        best_rail = min(rails, key=lambda r: abs(r["y_um"] - pin_y))
        dist_um = abs(best_rail["y_um"] - pin_y)

        # Strategy: via_stack if very close, via_access otherwise
        strategy = "via_stack" if dist_um <= _VIA_STACK_MAX_UM else "via_access"

        # Pin-trapping guard: if device has D between S1/S2 power pins,
        # force via_access to avoid trapping D's escape route
        if strategy == "via_stack" and _has_signal_pin_between(
                p["inst"], inst_power_pins[p["inst"]], netlist):
            strategy = "via_access"

        # PMOS ntap guard: PMOS devices need via_access so that the
        # access point M1 pad overlaps with the ntap tie M1.
        # via_stack skips access point drawing → ntap M1 floats → bulk disconnected.
        if strategy == "via_stack" and netlist:
            for dev in netlist.get("devices", []):
                if dev["name"] == p["inst"] and dev.get("has_nwell"):
                    strategy = "via_access"
                    break

        drops.append({
            "net": net_name,
            "inst": p["inst"],
            "pin": p["pin"],
            "strategy": strategy,
            "rail_id": best_rail["id"],
            "dist_um": round(dist_um, 2),
        })

    return drops


def _compute_rail_anchors(
    rails: list[dict],
    placement: dict,
    pins: list[dict],
) -> list[dict]:
    """Convert clustered rails into netlist.json rail config format.

    Each rail needs an anchor_inst and anchor_side to compute absolute Y.
    """
    result = []
    for rail in rails:
        # Find the pin whose device center is closest to rail Y
        best_inst = None
        best_dist = float("inf")
        best_side = "top"

        for idx in rail["pin_indices"]:
            p = pins[idx]
            inst_info = placement["instances"][p["inst"]]
            inst_y = inst_info["y_um"]
            inst_h = inst_info["h_um"]
            inst_top = inst_y + inst_h
            inst_bot = inst_y

            # Try anchoring from top or bottom
            for side, anchor_y in [("top", inst_top), ("bottom", inst_bot)]:
                d = abs(rail["y_um"] - anchor_y)
                if d < best_dist:
                    best_dist = d
                    best_inst = p["inst"]
                    best_side = side

        # Compute offset
        inst_info = placement["instances"][best_inst]
        anchor_y = (inst_info["y_um"] + inst_info["h_um"]) if best_side == "top" else inst_info["y_um"]
        offset_um = round(rail["y_um"] - anchor_y, 2)

        result.append({
            "id": rail["id"],
            "net": rail["net"],
            "anchor_inst": best_inst,
            "anchor_side": best_side,
            "offset_um": offset_um,
        })

    return result


def optimize_power_topology(
    netlist: dict,
    placement: dict,
    max_vbar_um: float = _MAX_VBAR_UM,
) -> dict:
    """Auto-compute power topology from netlist + placement.

    Returns a power_topology dict compatible with netlist.json format,
    with multi-rail support for nets that span large Y ranges.
    """
    power_pins = _collect_power_pins(netlist)

    all_rails = []
    all_drops = []
    all_rail_configs = []

    for net_name, pins in power_pins.items():
        # Cluster pins → determine rail count and positions
        rails = _cluster_rails(net_name, pins, placement, max_vbar_um, netlist)

        # Assign each pin to nearest rail
        drops = _assign_drops(net_name, pins, rails, placement, netlist)

        # Convert to anchor-based config
        rail_configs = _compute_rail_anchors(rails, placement, pins)

        all_rails.extend(rails)
        all_drops.extend(drops)
        all_rail_configs.extend(rail_configs)

    # Report
    print(f"\nPower topology optimization:")
    print(f"  Nets: {len(power_pins)}")
    for net_name, pins in power_pins.items():
        net_rails = [r for r in all_rails if r["net"] == net_name]
        net_drops = [d for d in all_drops if d["net"] == net_name]
        max_dist = max((d["dist_um"] for d in net_drops), default=0)
        print(f"  {net_name}: {len(pins)} pins → {len(net_rails)} rail(s), max_drop={max_dist:.1f}µm")
        for r in net_rails:
            print(f"    rail {r['id']}: y={r['y_um']:.1f}µm ({r['n_pins']} pins)")

    # Check for long vbars
    long_drops = [d for d in all_drops if d["dist_um"] > max_vbar_um]
    if long_drops:
        print(f"\n  WARNING: {len(long_drops)} drops exceed {max_vbar_um}µm:")
        for d in long_drops:
            print(f"    {d['inst']}.{d['pin']} ({d['net']}): {d['dist_um']:.1f}µm to rail {d['rail_id']}")

    # Build output
    # Deduplicate drops: same (inst, pin) should only appear once
    seen = set()
    unique_drops = []
    for d in all_drops:
        key = (d["inst"], d["pin"])
        if key not in seen:
            seen.add(key)
            unique_drops.append({
                "net": d["net"],
                "inst": d["inst"],
                "pin": d["pin"],
                "strategy": d["strategy"],
            })

    # Get rail_x from existing config or compute
    existing_topo = netlist.get("constraints", {}).get("power_topology", {})
    rail_x = existing_topo.get("rail_x", {
        "left_margin_um": -1.0,
        "right_anchor_inst": "MBp2",
        "right_margin_um": 3.0,
    })

    return {
        "_note": "Auto-generated by power_optimizer.py",
        "rails": all_rail_configs,
        "rail_x": rail_x,
        "drops": unique_drops,
    }


def main():
    """CLI: optimize power topology from netlist.json + placement.json."""
    netlist_path = sys.argv[1] if len(sys.argv) > 1 else "netlist.json"
    placement_path = sys.argv[2] if len(sys.argv) > 2 else "placement.json"

    with open(netlist_path) as f:
        netlist = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)

    topo = optimize_power_topology(netlist, placement)

    print("\n--- Generated power_topology ---")
    print(json.dumps(topo, indent=2))

    # Show diff vs current
    current = netlist.get("constraints", {}).get("power_topology", {})
    cur_rails = len(current.get("rails", []))
    new_rails = len(topo["rails"])
    cur_drops = len(current.get("drops", []))
    new_drops = len(topo["drops"])
    print(f"\nDiff: rails {cur_rails} → {new_rails}, drops {cur_drops} → {new_drops}")


if __name__ == "__main__":
    main()
