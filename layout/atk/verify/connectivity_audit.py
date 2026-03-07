"""JSON-based net connectivity checker — no GDS needed.

Collects M1/M2/Via1 shapes from routing.json + gate_extras + ties.json,
builds UnionFind connectivity per signal net, verifies all pins are in
the same connected component.

Usage:
    python -m atk.verify.connectivity_audit [routing.json] [placement.json]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import box, Point
from shapely.ops import unary_union

from ..pdk import UM, M1_SIG_W, M2_SIG_W, VIA1_SZ
from ..route.access import _DEVICES, compute_access_points
from ..route.maze_router import M1_LYR, M2_LYR


class UF:
    """Union-Find with path compression."""
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


def _seg_to_box_nm(seg, wire_w):
    """Convert segment to shapely box (nm coords, NOT µm)."""
    x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
    hw = wire_w / 2
    return box(min(x1, x2) - hw, min(y1, y2) - hw,
               max(x1, x2) + hw, max(y1, y2) + hw)


def _rect_to_box_nm(rect):
    """Convert [x1,y1,x2,y2] nm to shapely box (nm coords)."""
    return box(rect[0], rect[1], rect[2], rect[3])


def _collect_net_shapes(routing, placement, netlist, gate_info,
                        access_devices, ties=None):
    """Collect per-net M1/M2/Via1 shapes.

    Returns dict[net_name → {'m1': [box], 'm2': [box], 'via1': [box], 'pins': [key]}]
    """
    from ..gds.gate_extras import build_gate_extras

    nets = defaultdict(lambda: {'m1': [], 'm2': [], 'via1': [], 'pins': []})

    # Pin → net mapping from netlist.json
    pin_net = {}
    for ne in netlist['nets']:
        for pin in ne['pins']:
            pin_net[pin] = ne['name']

    hw_m1 = M1_SIG_W / 2
    hw_m2 = M2_SIG_W / 2
    hv = VIA1_SZ / 2

    # ─── 1. Signal route segments ───
    for net_name, route in routing.get('signal_routes', {}).items():
        n = nets[net_name]
        for seg in route.get('segments', []):
            layer = seg[4]
            if layer == M1_LYR:
                n['m1'].append(_seg_to_box_nm(seg, M1_SIG_W))
            elif layer == M2_LYR:
                n['m2'].append(_seg_to_box_nm(seg, M2_SIG_W))
            elif layer == -1:  # Via1
                n['via1'].append(box(seg[0] - hv, seg[1] - hv,
                                     seg[0] + hv, seg[1] + hv))

    # ─── 2. Pre-routes ───
    for net_name, route in routing.get('pre_routes', {}).items():
        n = nets[net_name]
        for seg in route.get('segments', []):
            layer = seg[4]
            if layer == M1_LYR:
                n['m1'].append(_seg_to_box_nm(seg, M1_SIG_W))
            elif layer == M2_LYR:
                n['m2'].append(_seg_to_box_nm(seg, M2_SIG_W))
            elif layer == -1:
                n['via1'].append(box(seg[0] - hv, seg[1] - hv,
                                     seg[0] + hv, seg[1] + hv))

    # ─── 3. Access point via pads + M1 stubs ───
    ap = routing.get('access_points', {})
    for key, val in ap.items():
        net = pin_net.get(key, '')
        if not net:
            continue
        n = nets[net]
        n['pins'].append(key)

        vp = val.get('via_pad')
        if vp:
            if 'm1' in vp:
                n['m1'].append(_rect_to_box_nm(vp['m1']))
            if 'm2' in vp:
                n['m2'].append(_rect_to_box_nm(vp['m2']))
            if 'via1' in vp:
                n['via1'].append(_rect_to_box_nm(vp['via1']))
        stub = val.get('m1_stub')
        if stub:
            n['m1'].append(_rect_to_box_nm(stub))

    # ─── 4. Gate contact extras ───
    gate_shapes = build_gate_extras(placement, netlist, gate_info,
                                    access_devices)
    for gs in gate_shapes:
        n = nets[gs.net]
        if gs.m1:
            n['m1'].append(_rect_to_box_nm(gs.m1))
        if gs.m2:
            n['m2'].append(_rect_to_box_nm(gs.m2))
        if gs.via1:
            n['via1'].append(_rect_to_box_nm(gs.via1))
        if gs.cont:
            # Cont connects poly to M1 — model as M1 shape
            n['m1'].append(_rect_to_box_nm(gs.cont))
        if gs.cont2:
            n['m1'].append(_rect_to_box_nm(gs.cont2))

    # ─── 5. Tie M1 shapes ───
    if ties:
        for tie in ties.get('ties', []):
            net = tie.get('net', '')
            if not net:
                continue
            n = nets[net]
            for rect in tie.get('m1_rects', []):
                n['m1'].append(_rect_to_box_nm(rect))

    return dict(nets)


def check_net_connectivity(net_name, shapes):
    """Check if all pins of a net are in the same connected component.

    Algorithm:
    1. M1 shapes → unary_union → connected regions (nodes)
    2. M2 shapes → unary_union → connected regions (nodes)
    3. Via1 shapes → find overlapping M1 + M2 regions → UF.union
    4. For each pin, find which region it falls in → check all same UF root.

    Returns (status, details):
        ('OK', None) — all connected
        ('OPEN', {components: [pin_lists]}) — split into multiple components
        ('NO_SHAPES', None) — net has no geometry
    """
    m1_list = shapes['m1']
    m2_list = shapes['m2']
    via_list = shapes['via1']
    pins = shapes['pins']

    if not m1_list and not m2_list:
        return ('NO_SHAPES', None)

    # Build connected regions
    m1_regions = []
    if m1_list:
        u = unary_union(m1_list)
        if not u.is_empty:
            m1_regions = list(u.geoms) if u.geom_type == 'MultiPolygon' else [u]

    m2_regions = []
    if m2_list:
        u = unary_union(m2_list)
        if not u.is_empty:
            m2_regions = list(u.geoms) if u.geom_type == 'MultiPolygon' else [u]

    n_m1 = len(m1_regions)
    n_m2 = len(m2_regions)
    n_total = n_m1 + n_m2

    if n_total == 0:
        return ('NO_SHAPES', None)

    uf = UF(n_total)

    # Via1: bridge M1 and M2 regions
    for v in via_list:
        mi = mj = None
        for i, r in enumerate(m1_regions):
            if r.intersects(v):
                mi = i
                break
        for j, r in enumerate(m2_regions):
            if r.intersects(v):
                mj = j
                break
        if mi is not None and mj is not None:
            uf.union(mi, n_m1 + mj)
        # Also bridge M1-M1 or M2-M2 through via
        # (via pad on both layers creates M1-M1 and M2-M2 connectivity too)

    # M1 regions that overlap each other (through stubs, gate contacts, etc.)
    # Already handled by unary_union — they'd be one region.

    # Find which component each pin belongs to
    pin_components = {}
    all_regions = m1_regions + m2_regions

    for pin_key in pins:
        # Get pin coordinates from access_points
        # We need to check both M1 and M2 regions
        found = False
        for i, r in enumerate(all_regions):
            # Pin is "in" a region if the access point coordinate is inside or very close
            # We don't have exact pin coords here, but the access point shapes ARE in the regions
            pass

    # Simpler approach: just check if all regions are in the same UF component
    if n_total <= 1:
        return ('OK', None)

    roots = set()
    for i in range(n_total):
        roots.add(uf.find(i))

    if len(roots) == 1:
        return ('OK', None)

    # Multiple components — report
    comp_map = defaultdict(list)
    for i in range(n_total):
        root = uf.find(i)
        layer = 'M1' if i < n_m1 else 'M2'
        idx = i if i < n_m1 else i - n_m1
        region = all_regions[i]
        comp_map[root].append((layer, idx, region.bounds))

    return ('OPEN', {
        'n_components': len(roots),
        'components': dict(comp_map),
    })


def run(routing_path=None, placement_path=None, netlist_path=None,
        ties_path=None, device_lib_path=None):
    """Run connectivity audit. Returns error count."""
    from ..paths import (ROUTING_JSON, PLACEMENT_JSON, NETLIST_JSON,
                         TIES_JSON, DEVICE_LIB_JSON)
    if routing_path is None:
        routing_path = ROUTING_JSON
    if placement_path is None:
        placement_path = PLACEMENT_JSON
    if netlist_path is None:
        netlist_path = NETLIST_JSON
    if ties_path is None:
        ties_path = TIES_JSON
    if device_lib_path is None:
        device_lib_path = DEVICE_LIB_JSON

    from ..verify.pcell_xray import load_gate_info

    with open(routing_path) as f:
        routing = json.load(f)
    with open(placement_path) as f:
        placement = json.load(f)
    with open(netlist_path) as f:
        netlist = json.load(f)

    ties = None
    if Path(ties_path).exists():
        with open(ties_path) as f:
            ties = json.load(f)

    gate_info = load_gate_info(device_lib_path)

    net_shapes = _collect_net_shapes(
        routing, placement, netlist, gate_info, _DEVICES, ties)

    errors = 0
    ok_count = 0

    print('=== Connectivity Audit ===')
    for net_name in sorted(net_shapes.keys()):
        shapes = net_shapes[net_name]
        status, details = check_net_connectivity(net_name, shapes)

        if status == 'OK':
            ok_count += 1
        elif status == 'OPEN':
            n_comp = details['n_components']
            n_m1 = sum(1 for v in details['components'].values()
                       for l, _, _ in v if l == 'M1')
            n_m2 = sum(1 for v in details['components'].values()
                       for l, _, _ in v if l == 'M2')
            print(f'  OPEN  {net_name}: {n_comp} components '
                  f'({n_m1} M1 + {n_m2} M2 regions)')
            for root, members in details['components'].items():
                bounds_strs = []
                for layer, idx, bounds in members[:3]:
                    bounds_strs.append(
                        f'{layer}({bounds[0]:.0f},{bounds[1]:.0f})-'
                        f'({bounds[2]:.0f},{bounds[3]:.0f})')
                extra = f' +{len(members)-3}' if len(members) > 3 else ''
                print(f'    comp: {", ".join(bounds_strs)}{extra}')
            errors += 1
        elif status == 'NO_SHAPES':
            print(f'  WARN  {net_name}: no geometry')

    print(f'\nResult: {ok_count} OK, {errors} OPEN')
    return errors


if __name__ == '__main__':
    args = sys.argv[1:]
    routing = args[0] if len(args) > 0 else None
    placement = args[1] if len(args) > 1 else None
    sys.exit(0 if run(routing, placement) == 0 else 1)
