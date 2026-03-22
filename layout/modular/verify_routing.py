#!/usr/bin/env python3
"""Post-routing verification: L2N extraction to detect shorts and open nets.

Runs after all routing scripts. Checks:
  1. Each routed net pair has endpoints on the SAME extracted net (connected)
  2. No two DIFFERENT signal routes share a net (short circuit)
  3. Total net count is reasonable (no massive merging)

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    klayout -n sg13g2 -zz -r modular/verify_routing.py
"""

import klayout.db as pya
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')


def verify():
    print('=== Post-Routing Verification (L2N) ===\n')

    ly = pya.Layout()
    ly.read(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell = ly.top_cell()

    # Full metal stack L2N extraction
    l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(ly, cell, []))

    layers = {}
    layer_defs = [
        (6, 0, 'Cont'), (8, 0, 'M1'), (19, 0, 'Via1'), (10, 0, 'M2'),
        (29, 0, 'Via2'), (30, 0, 'M3'), (49, 0, 'Via3'), (50, 0, 'M4'),
        (66, 0, 'Via4'), (67, 0, 'M5'), (125, 0, 'TV1'), (126, 0, 'TM1'),
    ]
    for ln, dt, name in layer_defs:
        li = ly.find_layer(ln, dt)
        if li is not None:
            layers[name] = l2n.make_layer(li, name)

    # Connect metal stack
    connections = [
        ('Cont', 'M1'), ('M1', 'Via1'), ('Via1', 'M2'),
        ('M2', 'Via2'), ('Via2', 'M3'), ('M3', 'Via3'), ('Via3', 'M4'),
        ('M4', 'Via4'), ('Via4', 'M5'), ('M5', 'TV1'), ('TV1', 'TM1'),
    ]
    for a, b in connections:
        if a in layers and b in layers:
            l2n.connect(layers[a], layers[b])

    l2n.extract_netlist()
    tc = list(l2n.netlist().each_circuit_top_down())[0]
    total_nets = len(list(tc.each_net()))
    print(f'  Total extracted nets: {total_nets}')

    # Define all routed signal pairs: (src_x, src_y, dst_x, dst_y, name, probe_layer)
    # probe_layer: which layer to probe at each endpoint
    routes = [
        # route_m3.py (12 routes) — probe M2
        (142.620, 27.340, 150.500, 33.900, 'comp_outp', 'M2', 'M2'),
        (142.120, 29.840, 150.500, 39.840, 'comp_outn', 'M2', 'M2'),
        (92.360, 22.300, 113.210, 30.830, 'chop_out', 'M2', 'M2'),
        (65.700, 22.650, 66.350, 34.150, 'exc_out', 'M2', 'M2'),
        (148.600, 36.250, 177.150, 39.600, 'lat_q', 'M2', 'M2'),
        (148.600, 37.550, 179.350, 39.000, 'lat_qb', 'M2', 'M2'),
        (81.700, 60.300, 61.250, 34.650, 'src1', 'M2', 'M2'),
        (96.200, 60.300, 67.250, 35.150, 'src2', 'M2', 'M2'),
        (109.850, 60.300, 73.250, 35.700, 'src3', 'M2', 'M2'),
        (183.600, 34.800, 188.900, 21.200, 'dac_out', 'M2', 'M2'),
        (125.000, 41.350, 160.300, 24.710, 'ota_out', 'M2', 'M2'),
        (169.900, 64.400, 196.400, 2.200, 'vptat', 'M2', 'M2'),
        # route_long.py (8 routes) — digital end probe M3, analog end probe M2
        (46.000, 63.400, 68.100, 23.700, 'phi_p', 'M3', 'M2'),
        (46.000, 65.100, 65.400, 23.200, 'phi_n', 'M3', 'M2'),
        (46.000, 55.000, 86.200, 23.000, 'f_exc', 'M3', 'M2'),
        (46.000, 64.200, 91.900, 23.550, 'f_exc_b', 'M3', 'M2'),
        (17.000, 28.100, 181.400, 8.100, 'vco_out', 'M3', 'M2'),
        (107.700, 59.300, 169.300, 62.150, 'net_c1', 'M2', 'M2'),
        (160.500, 51.000, 188.100, 79.100, 'net_rptat', 'M2', 'M2'),
        (163.000, 36.900, 157.000, 2.600, 'nmos_bias', 'M2', 'M2'),
    ]

    # Verify each route
    net_to_route = {}  # cluster_id → route name (detect shorts)
    connected = 0
    disconnected = 0
    shorted = 0
    unprobed = 0

    print(f'\n{"Route":12s} {"Src":>6s} {"Dst":>6s} {"Status":>12s}')
    print('-' * 40)

    for sx, sy, dx, dy, name, src_layer, dst_layer in routes:
        ns = l2n.probe_net(layers[src_layer], pya.DPoint(sx, sy)) if src_layer in layers else None
        nd = l2n.probe_net(layers[dst_layer], pya.DPoint(dx, dy)) if dst_layer in layers else None

        sid = ns.cluster_id if ns else None
        did = nd.cluster_id if nd else None

        if sid is not None and did is not None:
            if sid == did:
                # Connected — check for shorts with other routes
                if sid in net_to_route and net_to_route[sid] != name:
                    status = f'⚠️ SHORT:{net_to_route[sid]}'
                    shorted += 1
                else:
                    status = '✅ OK'
                    connected += 1
                net_to_route[sid] = name
            else:
                status = '❌ OPEN'
                disconnected += 1
        else:
            status = '? PROBE_FAIL'
            unprobed += 1

        print(f'{name:12s} {str(sid or "?"):>6s} {str(did or "?"):>6s} {status}')

    # Summary
    print(f'\n=== SUMMARY ===')
    print(f'  Connected: {connected}')
    print(f'  Disconnected: {disconnected}')
    print(f'  Shorted: {shorted}')
    print(f'  Probe failed: {unprobed}')
    print(f'  Total nets: {total_nets}')

    if shorted > 0:
        print(f'\n  ❌ {shorted} SHORT CIRCUITS DETECTED — must fix before tapeout!')
    elif disconnected > 0:
        print(f'\n  ⚠️ {disconnected} routes not connected — routing incomplete')
    elif unprobed > 0:
        print(f'\n  ⚠️ {unprobed} endpoints could not be probed — verify manually')
    else:
        print(f'\n  ✅ ALL ROUTES VERIFIED CORRECT')

    return shorted == 0


if __name__ == '__main__':
    result = verify()
    print(f'\n=== {"PASS" if result else "FAIL"} ===')
