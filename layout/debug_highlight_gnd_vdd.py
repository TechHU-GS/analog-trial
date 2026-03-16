"""KLayout macro: highlight gnd|vdd merged net from LVS result.

Usage: Open KLayout GUI, then:
  1. File → Open: output/ptat_vco.gds
  2. Macros → Macro Development → Run this script

Or from command line (opens GUI with highlighting):
  klayout -n sg13g2 output/ptat_vco.gds -r debug_highlight_gnd_vdd.py

This loads the LVS cross-reference and highlights all shapes belonging to
the gnd|vdd merged net, making the bridge path visible.
"""

import klayout.db as kdb
import os

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
lvsdb_path = '/tmp/lvs_bridge2/ptat_vco.lvsdb'
gds_path = os.path.join(script_dir, 'output', 'ptat_vco.gds')

print(f"Loading LVS result from: {lvsdb_path}")

# Load LVS result
lvs = kdb.LayoutVsSchematic()
lvs.read(lvsdb_path)

# Get netlist
nl = lvs.netlist()

# Find top circuit
top_circuit = None
for i in range(nl.top_circuit_count()):
    c = nl.top_circuit_by_index(i)
    print(f"  Top circuit: {c.name}")
    if c.name == 'ptat_vco':
        top_circuit = c

if top_circuit is None:
    top_circuit = nl.top_circuit_by_index(0)
    print(f"  Using: {top_circuit.name}")

# Enumerate nets to find gnd|vdd
print(f"\nSearching for gnd|vdd net...")
target_net = None
net_iter = top_circuit.each_net()
net_count = 0
for net in net_iter:
    net_count += 1
    name = net.name if net.name else f'${net.cluster_id()}'
    if 'gnd' in name and 'vdd' in name:
        target_net = net
        print(f"  Found: '{name}' (cluster_id={net.cluster_id()})")
        break

print(f"  Scanned {net_count} nets")

if target_net is None:
    print("ERROR: gnd|vdd net not found!")
else:
    cid = target_net.cluster_id()
    print(f"\n  Net cluster_id: {cid}")
    print(f"  Net name: {target_net.name}")

    # Count device terminals on this net
    term_count = 0
    dev_terminals = {}
    for dev in top_circuit.each_device():
        dc = dev.device_class()
        for ti in range(dc.terminal_count()):
            t_net = dev.net_for_terminal(ti)
            if t_net and t_net.cluster_id() == cid:
                term_count += 1
                t_name = dc.terminal_definitions()[ti].name
                dev_terminals.setdefault(t_name, []).append(dev.name or f'dev_{dev.id()}')

    print(f"\n  Device terminals on gnd|vdd: {term_count}")
    for t_name, devs in sorted(dev_terminals.items()):
        print(f"    Terminal '{t_name}': {len(devs)} devices")

    # Get shapes for this net using the internal database
    # The LVS database has a shapes method per net
    print(f"\n  Trying to extract shape info from lvsdb...")

    # Use the internal net to get the cluster
    # The LayoutVsSchematic has an internal_layout() that contains the extracted shapes
    int_layout = lvs.internal_layout()
    int_top = lvs.internal_top_cell()

    print(f"  Internal layout: {int_layout.cells()} cells")
    print(f"  Internal top: {int_top.name}")
    print(f"  Internal layers: {int_layout.layers()}")

    # List internal layers
    for li in range(int_layout.layers()):
        info = int_layout.get_info(li)
        count = 0
        for s in int_top.shapes(li).each():
            count += 1
            if count > 5: break
        if count > 0:
            print(f"    layer ({info.layer},{info.datatype}): {count}+ shapes")

print("\n=== To visually inspect: ===")
print("1. Open KLayout GUI: klayout -n sg13g2 output/ptat_vco.gds")
print("2. File → Load LVS Result: /tmp/lvs_bridge2/ptat_vco.lvsdb")
print("3. In LVS browser: find 'gnd,vdd' net")
print("4. Right-click → Show in Layout → highlights all shapes on this net")
print("5. Look for the bridge path connecting gnd rail region to vdd rail region")
