#!/usr/bin/env python3
"""Trace all Cont (6/0) shape insertions during GDS assembly.

Monkey-patches KLayout shape insertion to log when 160×160 Cont shapes
are created near resistor terminal positions.

Run: cd layout && source ~/pdk/venv/bin/activate && klayout -n sg13g2 -zz -r trace_cont_insertion.py
"""
import os, sys, traceback
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

# Resistor cell origins
RES_ORIGINS = {
    'rppd': (10200, 137610),
    'rhigh_a': (56700, 59610),
    'rhigh_b': (24960, 59610),
    'rhigh1': (15200, 15610),
}

# Target Cont positions (offset 170,-590 from origin)
TARGETS = []
for name, (ox, oy) in RES_ORIGINS.items():
    TARGETS.append((ox + 170, oy - 590, ox + 330, oy - 430, name))

_CONT_LAYER = None
_orig_insert = None
_cont_insertions = []

class ShapesProxy:
    """Proxy for Shapes object that logs Cont insertions."""
    def __init__(self, real_shapes, layer_idx):
        self._real = real_shapes
        self._layer_idx = layer_idx

    def insert(self, shape):
        result = self._real.insert(shape)
        if self._layer_idx == _CONT_LAYER:
            bb = shape.bbox() if hasattr(shape, 'bbox') else kdb.Box(shape)
            w, h = bb.width(), bb.height()
            if w == 160 and h == 160:
                # Check if near any target
                for tx1, ty1, tx2, ty2, tname in TARGETS:
                    if (bb.left == tx1 and bb.bottom == ty1 and
                        bb.right == tx2 and bb.top == ty2):
                        stack = traceback.format_stack()
                        _cont_insertions.append({
                            'pos': (bb.left, bb.bottom, bb.right, bb.top),
                            'target': tname,
                            'stack': ''.join(stack[-6:-1]),
                        })
                        print(f"\n*** TRACED: 160×160 Cont at ({bb.left},{bb.bottom}) "
                              f"near {tname} ***")
                        for line in stack[-6:-1]:
                            print(f"  {line.strip()}")
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)

# Now run the actual assembly
print("=" * 80)
print("TRACING CONT INSERTIONS")
print("=" * 80)

# Import and patch
import klayout.db

# We can't easily monkey-patch shapes().insert, so instead let's:
# Run assemble_gds normally, then check the result
exec(open('assemble_gds.py').read())

# Actually, a simpler approach: just check the final GDS
# The monkey-patching is complex. Let me check differently.
