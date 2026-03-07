"""Shared gate contact/strap shape generator.

Called by BOTH assemble_gds.py (draw to GDS) and connectivity_audit.py (check).
Same input → same output → zero coordinate drift.

Usage:
    from atk.gds.gate_extras import build_gate_extras
    shapes = build_gate_extras(placement, netlist, gate_info, access_devices)
"""
from dataclasses import dataclass
from atk.pdk import (
    UM, s5,
    CONT_SZ, CONT_ENC_M1_END,
    GATE_POLY_EXT, CNT_D_ENC, M1_MIN_AREA,
)
from atk.route.access import get_access_mode


@dataclass
class GateShape:
    """One gate contact assembly for one MOSFET instance."""
    inst: str           # instance name (e.g. 'MPu1')
    net: str            # gate net name (e.g. 'vco5')
    cont: list = None   # [x1,y1,x2,y2] nm — Cont on poly
    cont2: list = None  # [x1,y1,x2,y2] nm — second Cont (ng=2 only)
    m1: list = None     # [x1,y1,x2,y2] nm — M1 pad or strap
    via1: list = None   # [x1,y1,x2,y2] nm — Via1 (m1_pin mode only)
    m2: list = None     # [x1,y1,x2,y2] nm — M2 pad (m1_pin mode only)
    poly_ext: list = None   # [x1,y1,x2,y2] nm — GatPoly extension for gate contact
    poly_ext2: list = None  # [x1,y1,x2,y2] nm — second GatPoly ext (ng=2 only)


def _pin_net_map(netlist):
    """Build inst.pin → net_name mapping from netlist.json data."""
    mapping = {}
    for ne in netlist['nets']:
        for pin in ne['pins']:
            mapping[pin] = ne['name']
    return mapping


def build_gate_extras(placement, netlist, gate_info, access_devices):
    """Generate all gate contact shapes for every MOSFET instance.

    Args:
        placement: placement.json dict (has 'instances')
        netlist: netlist.json dict (has 'nets')
        gate_info: dict[dev_type → GateInfo] from pcell_xray
        access_devices: atk.route.access._DEVICES dict

    Returns:
        list[GateShape] — one per MOSFET instance that needs gate contacts.
    """
    pin_net = _pin_net_map(netlist)
    instances = placement['instances']
    results = []

    hc = CONT_SZ // 2          # 80nm
    strap_h = CONT_SZ           # 160nm — strap height = Cont height
    hs = strap_h // 2           # 80nm

    for inst_name, info in instances.items():
        dev_type = info['type']
        acc = access_devices.get(dev_type)
        if acc is None:
            continue

        gi = gate_info.get(dev_type)
        if gi is None:
            continue  # not a MOSFET (no GatPoly)

        # Skip resistors (they have GatPoly but no gate pin)
        if 'G' not in acc['pins']:
            continue

        mode = get_access_mode(dev_type, 'G')
        if mode not in ('gate', 'm1_pin'):
            continue

        # Gate net
        gate_key = f'{inst_name}.G'
        net = pin_net.get(gate_key, '?')

        # PCell origin (nm, 5nm grid)
        pcell_x = s5(info['x_um'] - acc['ox'])
        pcell_y = s5(info['y_um'] - acc['oy'])

        if gi.ng == 1:
            # ── Single gate finger ──
            gx = s5(pcell_x / UM + gi.finger_xs[0] / UM)
            poly_bot = s5(pcell_y / UM + gi.poly_bot / UM)

            # GatPoly extension: extend poly down by GATE_POLY_EXT (230nm)
            # so gate contact sits in DRC-clean zone below PCell poly.
            ext_bot = poly_bot - GATE_POLY_EXT
            # Contact center: CNT_D_ENC (70nm) from ext bottom + half contact
            cy = ext_bot + CNT_D_ENC + hc  # ext_bot + 70 + 80 = poly_bot - 80

            # GatPoly extension rectangle (same X width as gate finger)
            gate_hw = gi.finger_hws[0]
            poly_ext = [gx - gate_hw, ext_bot, gx + gate_hw, poly_bot]

            # Cont on gate poly (in extended zone)
            cont = [gx - hc, cy - hc, gx + hc, cy + hc]

            # M1 pad covering Cont.  Access point draws Via1+M2 at poly_bot.
            # Top capped at poly_bot to avoid M1.b with S/D M1 (180nm above).
            # Extend downward so area ≥ M1_MIN_AREA (M1.d = 0.09 µm²).
            m1_hw = hc + CONT_ENC_M1_END  # 130nm → width = 260nm
            m1_w = 2 * m1_hw
            m1_min_h = (M1_MIN_AREA + m1_w - 1) // m1_w  # ceil division
            m1_min_h = ((m1_min_h + 4) // 5) * 5  # round up to 5nm grid
            m1_h = max(m1_min_h, poly_bot - (cy - hc))  # at least cover Cont
            m1 = [gx - m1_hw, poly_bot - m1_h, gx + m1_hw, poly_bot]

            results.append(GateShape(
                inst=inst_name, net=net,
                cont=cont, m1=m1,
                poly_ext=poly_ext,
            ))

        elif gi.ng == 2:
            # ── Two gate fingers: strap G1→G2 + Cont at both ──
            g1_x = s5(pcell_x / UM + gi.finger_xs[0] / UM)
            g2_x = s5(pcell_x / UM + gi.finger_xs[1] / UM)
            poly_bot = s5(pcell_y / UM + gi.poly_bot / UM)

            # GatPoly extension for DRC-clean gate contacts
            ext_bot = poly_bot - GATE_POLY_EXT
            cy = ext_bot + CNT_D_ENC + hc  # poly_bot - 80

            # GatPoly extension rectangles (one per finger)
            g1_hw = gi.finger_hws[0]
            g2_hw = gi.finger_hws[1]
            poly_ext1 = [g1_x - g1_hw, ext_bot, g1_x + g1_hw, poly_bot]
            poly_ext2 = [g2_x - g2_hw, ext_bot, g2_x + g2_hw, poly_bot]

            # Conts at G1 and G2 (in extended zone)
            cont1 = [g1_x - hc, cy - hc, g1_x + hc, cy + hc]
            cont2 = [g2_x - hc, cy - hc, g2_x + hc, cy + hc]

            # M1 strap from G1 to G2
            m1_x1 = g1_x - CONT_ENC_M1_END
            m1_x2 = g2_x + CONT_ENC_M1_END
            m1_y1 = cy - hs
            m1_y2 = cy + hs
            m1 = [m1_x1, m1_y1, m1_x2, m1_y2]

            results.append(GateShape(
                inst=inst_name, net=net,
                cont=cont1, cont2=cont2,
                m1=m1,
                poly_ext=poly_ext1, poly_ext2=poly_ext2,
            ))

    return results


if __name__ == '__main__':
    import json
    import sys
    sys.path.insert(0, '/private/tmp/analog-trial/layout')
    from atk.verify.pcell_xray import load_gate_info
    from atk.route.access import _DEVICES

    gi = load_gate_info('atk/data/device_lib.json')
    from atk.paths import PLACEMENT_JSON, NETLIST_JSON
    with open(PLACEMENT_JSON) as f:
        pl = json.load(f)
    with open(NETLIST_JSON) as f:
        nl = json.load(f)

    shapes = build_gate_extras(pl, nl, gi, _DEVICES)
    for s in shapes:
        print(f'{s.inst:12s} net={s.net:12s} cont={s.cont} m1={s.m1}'
              f'{" via1="+str(s.via1) if s.via1 else ""}'
              f'{" m2="+str(s.m2) if s.m2 else ""}'
              f'{" cont2="+str(s.cont2) if s.cont2 else ""}')
