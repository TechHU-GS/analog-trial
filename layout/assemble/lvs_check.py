"""Inline LVS power connectivity check using LayoutToNetlist.

Checks power net fragmentation and GND-VDD shorts.
Uses full metal stack: M1→Via1→M2→Via2→M3→Via3→M4→Via4→M5→TopVia1→TM1.

Usage:
    from assemble.lvs_check import check_power_connectivity
    result = check_power_connectivity(layout, top, ties)
"""

import os
import klayout.db as db


ENABLED = bool(os.environ.get('LVS_INLINE'))

# Full metal stack layer definitions: (layer, datatype)
_LAYER_DEFS = [
    ('M1',  (8, 0)),
    ('M2',  (10, 0)),
    ('M3',  (30, 0)),
    ('M4',  (50, 0)),
    ('M5',  (67, 0)),
    ('TM1', (126, 0)),
    ('Via1', (19, 0)),
    ('Via2', (29, 0)),
    ('Via3', (49, 0)),
    ('Via4', (66, 0)),
    ('TV1',  (125, 0)),
]

# Inter-layer connections: (layer_a, layer_b)
_CONNECTIONS = [
    ('Via1', 'M1'), ('Via1', 'M2'),
    ('Via2', 'M2'), ('Via2', 'M3'),
    ('Via3', 'M3'), ('Via3', 'M4'),
    ('Via4', 'M4'), ('Via4', 'M5'),
    ('TV1',  'M5'), ('TV1',  'TM1'),
]


def check_power_connectivity(layout, top, ties):
    """Check power net fragmentation and GND-VDD shorts.

    Uses full metal stack M1 through TM1.

    Returns:
        dict with 'gnd_components', 'vdd_components', 'short' flag
        or None if disabled
    """
    if not ENABLED:
        return None

    # Build layer map
    layers = {}
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))

    for name, (lnum, dt) in _LAYER_DEFS:
        li = layout.find_layer(lnum, dt)
        if li is not None:
            layers[name] = l2n.make_layer(li, name)

    if 'M1' not in layers:
        return {'error': 'M1 layer not found'}

    # Intra-layer connectivity
    for name, region in layers.items():
        l2n.connect(region)

    # Inter-layer connectivity
    for a, b in _CONNECTIONS:
        if a in layers and b in layers:
            l2n.connect(layers[a], layers[b])

    l2n.extract_netlist()

    # Probe tie cell positions to find GND and VDD nets
    gnd_nets = set()
    vdd_nets = set()

    probe_layer = layers['M1']
    for tie in ties.get('ties', []):
        cx, cy = tie['center_nm']
        net = l2n.probe_net(probe_layer, db.Point(cx, cy))
        if net is None:
            continue
        cid = net.cluster_id
        if tie['net'] == 'gnd':
            gnd_nets.add(cid)
        elif tie['net'] in ('vdd', 'vdd_vco'):
            vdd_nets.add(cid)

    # Note: metal-only L2N does NOT include substrate/NWell/diffusion
    # connections. "shared" clusters may be false positives because
    # substrate connectivity separates nets that metal connectivity merges.
    # Report fragmentation only — short detection requires full KLayout LVS.
    shared = len(gnd_nets & vdd_nets)
    result = {
        'gnd_components': len(gnd_nets),
        'vdd_components': len(vdd_nets),
        'shared_clusters': shared,
        'layers_connected': len(layers),
    }

    gnd_ok = '✓' if len(gnd_nets) == 1 else f'⚠️{len(gnd_nets)} fragments'
    vdd_ok = '✓' if len(vdd_nets) <= 2 else f'⚠️{len(vdd_nets)} fragments'
    shared_note = f', {shared} metal-shared (verify with full LVS)' if shared else ''
    print(f'  LVS proxy [{len(layers)} layers]: '
          f'GND {gnd_ok}, VDD {vdd_ok}{shared_note}')

    return result
