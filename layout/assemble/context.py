"""Assembly context — shared state passed to all assembly modules.

Holds layout, cell, layer indices, and cross-module state (drawn_vias, etc.).
Modules mutate the context by adding shapes to ctx.top.
"""

import klayout.db


class AssemblyContext:
    """Shared state for GDS assembly modules."""

    def __init__(self, layout, top, placement, ties, routing, netlist,
                 device_lib, devices_map):
        # KLayout objects
        self.layout = layout
        self.top = top

        # Input data (dicts from JSON)
        self.placement = placement
        self.ties = ties
        self.routing = routing
        self.netlist = netlist
        self.device_lib = device_lib
        self.devices_map = devices_map  # dev_type -> {pcell, params, ox, oy, ...}

        # Layer indices (populated by init_layers)
        self.layers = {}

        # Cross-module state
        self.drawn_vias = set()       # (x, y) of drawn Via1 positions
        self.gate_cont_m1 = []        # gate contact M1 boxes for bus strap avoidance

    def init_layers(self, layer_defs):
        """Initialize layer indices from a dict of name -> (layer, datatype).

        Example: {'M1': (8, 0), 'M2': (10, 0), ...}
        """
        for name, (layer, datatype) in layer_defs.items():
            self.layers[name] = self.layout.layer(layer, datatype)

    def li(self, name):
        """Shorthand for layer index lookup."""
        return self.layers[name]
