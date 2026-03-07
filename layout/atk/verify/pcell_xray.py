"""Parse device_lib.json GatPoly shapes into structured gate geometry data.

Provides GateInfo per device type: number of gate fingers, finger X positions,
poly vertical extent.  Used by gate_extras.py and coordinate_verify.py.

Usage:
    from atk.verify.pcell_xray import load_gate_info
    gate_info = load_gate_info('atk/data/device_lib.json')
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GateInfo:
    """Structured gate geometry for one device type."""
    dev_type: str
    ng: int                     # number of unique gate fingers
    finger_xs: list = field(default_factory=list)   # gate finger X centers (nm, PCell coords)
    finger_hws: list = field(default_factory=list)  # gate finger half-widths (nm)
    poly_bot: int = 0           # GatPoly bottom Y (nm, PCell coords)
    poly_top: int = 0           # GatPoly top Y (nm, PCell coords)


def load_gate_info(device_lib_path):
    """Parse device_lib.json → dict[dev_type, GateInfo].

    Only returns entries for devices that have GatPoly (MOSFETs).
    HBTs and resistors are skipped.
    """
    path = Path(device_lib_path)
    with open(path) as f:
        dlib = json.load(f)

    result = {}
    for dev_type, dev in dlib.items():
        rects = dev['shapes_by_layer'].get('GatPoly_5_0', [])
        if not rects:
            continue

        # Group rects by X center, get unique fingers
        from collections import defaultdict
        by_cx = defaultdict(list)
        for r in rects:
            cx = (r[0] + r[2]) // 2
            by_cx[cx].append(r)
        xs = sorted(by_cx.keys())
        # Half-width per finger (use first rect at each X center)
        hws = [((by_cx[cx][0][2] - by_cx[cx][0][0]) // 2) for cx in xs]
        poly_bot = min(r[1] for r in rects)
        poly_top = max(r[3] for r in rects)

        result[dev_type] = GateInfo(
            dev_type=dev_type,
            ng=len(xs),
            finger_xs=xs,
            finger_hws=hws,
            poly_bot=poly_bot,
            poly_top=poly_top,
        )

    return result


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        '/private/tmp/analog-trial/layout/atk/data/device_lib.json'
    info = load_gate_info(path)
    for name, gi in sorted(info.items()):
        print(f'{name:15s}  ng={gi.ng}  Xs={gi.finger_xs}  '
              f'poly=[{gi.poly_bot},{gi.poly_top}]')
