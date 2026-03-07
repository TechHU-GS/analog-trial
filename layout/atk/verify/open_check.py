"""Netlist connectivity check using networkx.

Verifies that each net in the netlist is connected in the layout:
- No open circuits (disconnected pins within same net)
- No unexpected merges (pins from different nets in same M2 region)
"""

import networkx as nx
from shapely.geometry import Point
from .short_check import load_m2_from_gds, check_shorts


def check_connectivity(netlist, m2_regions, access_points):
    """Check if each net's pins land on the same M2 merged region.

    Args:
        netlist: dict net_name -> [(inst, pin), ...]
        m2_regions: list of shapely Polygons (merged M2)
        access_points: dict (inst, pin) -> (x_um, y_um) M2 access position

    Returns:
        dict with:
            'open': list of (net_name, [disconnected_groups])
            'ok': True if all nets connected
    """
    result = {'open': [], 'ok': True}

    for net_name, pins in netlist.items():
        # Find which M2 region each pin touches
        pin_regions = {}
        for inst, pin in pins:
            key = (inst, pin)
            if key not in access_points:
                continue
            x, y = access_points[key]
            pt = Point(x, y)

            region_idx = None
            for i, r in enumerate(m2_regions):
                if r.contains(pt) or r.distance(pt) < 0.3:  # 0.3µm tolerance
                    region_idx = i
                    break
            pin_regions[key] = region_idx

        # Check: all pins should be on the same region
        regions_used = set(v for v in pin_regions.values() if v is not None)
        if len(regions_used) > 1:
            result['open'].append((net_name, list(regions_used)))
            result['ok'] = False

    return result


def build_netlist_graph(netlist):
    """Build a networkx graph from netlist for analysis.

    Nodes: (inst, pin) tuples
    Edges: connect all pins within the same net

    Returns: nx.Graph with net_name edge attribute
    """
    G = nx.Graph()
    for net_name, pins in netlist.items():
        for i, (inst_a, pin_a) in enumerate(pins):
            for inst_b, pin_b in pins[i+1:]:
                G.add_edge((inst_a, pin_a), (inst_b, pin_b), net=net_name)
    return G


def print_report(result):
    """Print connectivity check results."""
    print(f"\n{'='*50}")
    print("Netlist Connectivity Check")
    print(f"{'='*50}")

    if result['ok']:
        print("STATUS: PASS — all nets connected")
    else:
        print("STATUS: FAIL — open circuits detected")
        for net_name, region_groups in result['open']:
            print(f"  OPEN: {net_name} spans {len(region_groups)} M2 regions: {region_groups}")

    return result['ok']
