#!/usr/bin/env python3
"""Automated inter-module router using M3/M4 with shapely collision detection.

Strategy:
  - M3 = Horizontal, M4 = Vertical (LEF default)
  - Via2 lands on existing module M2 pads
  - L-route: src M2 → Via2 → M3-H → Via3 → M4-V → Via3 → M3-H → Via2 → dst M2
  - Routes sorted by length (short first, less conflict)
  - Shapely obstacle map updated after each route

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/route_intermodule.py
"""
import json
import os
import sys

# Use PDK venv python (has shapely + gdstk)
try:
    import gdstk
    from shapely.geometry import box as sbox, Polygon
    from shapely.ops import unary_union
except ImportError:
    print("ERROR: Run with PDK venv python3, not klayout")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')

# DRC rules (um)
M3_WIDTH = 0.200
M3_SPACE = 0.210
M4_WIDTH = 0.200
M4_SPACE = 0.210
VIA2_SIZE = 0.190
VIA3_SIZE = 0.190
M3_VIA2_ENC = 0.055  # M3 enclosure of Via2
M4_VIA3_ENC = 0.055

# GDS layers
L_M2 = (10, 0)
L_VIA2 = (29, 0)
L_M3 = (30, 0)
L_VIA3 = (49, 0)
L_M4 = (50, 0)

# Net definitions: (net_name, [(module, terminal_type), ...])
# terminal_type: 'auto' = find nearest M2 pad
# Digital M3 pin positions (label layer 30/25, offset by digital placement x=23, y=5)
DIGITAL_ORIGIN = (23.0, 5.0)
DIGITAL_M3_PINS = {
    'f_exc':   (29.0, 50.0),
    'f_exc_b': (29.0, 59.2),
    'phi_p':   (29.0, 58.4),
    'phi_n':   (29.0, 60.1),
    'vco_out': (1.0, 23.1),  # left edge!
}

def digital_pin_abs(pin_name):
    """Get absolute position of digital M3 pin."""
    rel = DIGITAL_M3_PINS.get(pin_name)
    if rel:
        return {'cx': DIGITAL_ORIGIN[0] + rel[0], 'cy': DIGITAL_ORIGIN[1] + rel[1],
                'is_m3': True}
    return None

NETS = [
    # Signal chain
    ('chop_out',   [('chopper', 'auto'), ('rin', 'auto')]),
    ('sum_n',      [('rin', 'auto'), ('ota', 'auto'), ('rdac', 'auto'), ('c_fb', 'auto')]),
    ('ota_out',    [('ota', 'auto'), ('comp', 'auto'), ('c_fb', 'auto')]),
    ('comp_outp',  [('comp', 'auto'), ('hbridge', 'auto')]),
    ('comp_outn',  [('comp', 'auto'), ('hbridge', 'auto')]),
    ('lat_q',      [('hbridge', 'auto'), ('dac_sw', 'auto')]),
    ('lat_qb',     [('hbridge', 'auto'), ('dac_sw', 'auto')]),
    ('dac_out',    [('dac_sw', 'auto'), ('rdac', 'auto')]),
    ('exc_out',    [('hbridge_drive', 'auto'), ('sw', 'auto')]),
    # Bias
    ('nmos_bias',  [('bias_mn', 'auto'), ('cbyp_n', 'auto'), ('vco_5stage', 'auto'), ('ptat_core', 'auto')]),
    ('pmos_bias',  [('bias_mn', 'auto'), ('cbyp_p', 'auto'), ('vco_5stage', 'auto'), ('ptat_core', 'auto')]),
    ('net_c1',     [('ptat_core', 'auto'), ('bias_cascode', 'auto')]),
    ('src1',       [('bias_cascode', 'auto'), ('sw', 'auto')]),
    ('src2',       [('bias_cascode', 'auto'), ('sw', 'auto')]),
    ('src3',       [('bias_cascode', 'auto'), ('sw', 'auto')]),
    ('vptat',      [('ptat_core', 'auto'), ('rout', 'auto')]),
    ('net_rptat',  [('ptat_core', 'auto'), ('rptat', 'auto')]),
    # Clock / digital (use M3 pins directly)
    ('f_exc',      [('digital', 'f_exc'), ('chopper', 'auto')]),
    ('f_exc_b',    [('digital', 'f_exc_b'), ('chopper', 'auto')]),
    ('phi_p',      [('digital', 'phi_p'), ('hbridge_drive', 'auto')]),
    ('phi_n',      [('digital', 'phi_n'), ('hbridge_drive', 'auto')]),
    ('vco5',       [('vco_5stage', 'auto'), ('vco_buffer', 'auto')]),
    ('vco_out',    [('vco_buffer', 'auto'), ('digital', 'vco_out')]),
]


def load_assembled_m2():
    """Load M2 pads from assembled GDS, grouped by module."""
    lib = gdstk.read_gds(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell = [c for c in lib.cells if c.name == 'tt_um_techhu_analog_trial'][0]
    cell.flatten()

    m2_pads = []
    for p in cell.polygons:
        if p.layer == L_M2[0] and p.datatype == L_M2[1]:
            b = p.bounding_box()
            cx = (b[0][0] + b[1][0]) / 2
            cy = (b[0][1] + b[1][1]) / 2
            m2_pads.append({'cx': cx, 'cy': cy,
                            'x1': b[0][0], 'y1': b[0][1],
                            'x2': b[1][0], 'y2': b[1][1]})
    return m2_pads


def assign_pads_to_modules(m2_pads, floorplan):
    """Assign each M2 pad to a module based on floorplan coordinates."""
    module_pads = {}
    for pad in m2_pads:
        for mod_name, m in floorplan.items():
            if mod_name == 'tile':
                continue
            if (m['x'] - 1 < pad['cx'] < m['x'] + m['w'] + 1 and
                m['y'] - 1 < pad['cy'] < m['y'] + m['h'] + 1):
                module_pads.setdefault(mod_name, []).append(pad)
                break
    return module_pads


def find_nearest_pad(module_pads, mod_name, target_cx=None, target_cy=None, exclude_pads=None):
    """Find the M2 pad in module closest to target, excluding used pads."""
    pads = module_pads.get(mod_name, [])
    if not pads:
        return None
    if exclude_pads:
        pads = [p for p in pads if not any(
            abs(p['cx']-e['cx'])<0.5 and abs(p['cy']-e['cy'])<0.5 for e in exclude_pads)]
        if not pads:
            pads = module_pads.get(mod_name, [])
    if target_cx is None or target_cy is None:
        return pads[0]
    best = min(pads, key=lambda p: (p['cx'] - target_cx)**2 + (p['cy'] - target_cy)**2)
    return best


def l_route(src, dst):
    """Generate L-route with M4 column at dst x."""
    return l_route_flex(src, dst, dst['cx'])


def z_route(src, dst, m4_x, mid_y):
    """Z-route: src → M4-V(at m4_x) to mid_y → M3-H to dst_x → M4-V to dst_y.
    Used when direct L-route is blocked (e.g., digital M3 obstacles).
    """
    sx, sy = src['cx'], src['cy']
    dx, dy = dst['cx'], dst['cy']
    hw = M3_WIDTH / 2
    v2_half = VIA2_SIZE / 2
    m3_enc = M3_VIA2_ENC
    m3_pad = v2_half + m3_enc
    v3_half = VIA3_SIZE / 2
    m4_pad = v3_half + M4_VIA3_ENC

    shapes = []
    src_is_m3 = src.get('is_m3', False)
    dst_is_m3 = dst.get('is_m3', False)

    # Via2 at endpoints (skip for M3 pins)
    if not src_is_m3:
        shapes.append((L_VIA2, sbox(sx-v2_half, sy-v2_half, sx+v2_half, sy+v2_half)))
    if not dst_is_m3:
        shapes.append((L_VIA2, sbox(dx-v2_half, dy-v2_half, dx+v2_half, dy+v2_half)))

    # M3 pads at endpoints
    shapes.append((L_M3, sbox(sx-m3_pad, sy-hw, sx+m3_pad, sy+hw)))
    shapes.append((L_M3, sbox(dx-m3_pad, dy-hw, dx+m3_pad, dy+hw)))

    # Segment 1: M4-V from src_y to mid_y at m4_x
    # M3-H from src_x to m4_x at src_y
    if abs(sx - m4_x) > 0.01:
        shapes.append((L_M3, sbox(min(sx,m4_x)-hw, sy-hw, max(sx,m4_x)+hw, sy+hw)))
    shapes.append((L_M4, sbox(m4_x-hw, min(sy,mid_y)-hw, m4_x+hw, max(sy,mid_y)+hw)))
    shapes.append((L_VIA3, sbox(m4_x-v3_half, sy-v3_half, m4_x+v3_half, sy+v3_half)))
    shapes.append((L_M3, sbox(m4_x-m3_pad, sy-hw, m4_x+m3_pad, sy+hw)))
    shapes.append((L_M4, sbox(m4_x-hw, sy-m4_pad, m4_x+hw, sy+m4_pad)))

    # Segment 2: M3-H from m4_x to dx at mid_y
    shapes.append((L_M3, sbox(min(m4_x,dx)-hw, mid_y-hw, max(m4_x,dx)+hw, mid_y+hw)))
    shapes.append((L_VIA3, sbox(m4_x-v3_half, mid_y-v3_half, m4_x+v3_half, mid_y+v3_half)))
    shapes.append((L_M3, sbox(m4_x-m3_pad, mid_y-hw, m4_x+m3_pad, mid_y+hw)))
    shapes.append((L_M4, sbox(m4_x-hw, mid_y-m4_pad, m4_x+hw, mid_y+m4_pad)))

    # Segment 3: M4-V from mid_y to dst_y at dx
    if abs(mid_y - dy) > 0.01:
        shapes.append((L_M4, sbox(dx-hw, min(mid_y,dy)-hw, dx+hw, max(mid_y,dy)+hw)))
    shapes.append((L_VIA3, sbox(dx-v3_half, mid_y-v3_half, dx+v3_half, mid_y+v3_half)))
    shapes.append((L_M3, sbox(dx-m3_pad, mid_y-hw, dx+m3_pad, mid_y+hw)))
    shapes.append((L_M4, sbox(dx-hw, mid_y-m4_pad, dx+hw, mid_y+m4_pad)))
    shapes.append((L_VIA3, sbox(dx-v3_half, dy-v3_half, dx+v3_half, dy+v3_half)))
    shapes.append((L_M3, sbox(dx-m3_pad, dy-hw, dx+m3_pad, dy+hw)))
    shapes.append((L_M4, sbox(dx-hw, dy-m4_pad, dx+hw, dy+m4_pad)))

    return shapes


def l_route_flex(src, dst, m4_x):
    """Generate L-route shapes with configurable M4 column x position.
    Pattern: src → M3-H → Via3 → M4-V(at m4_x) → Via3 → M3-H → dst
    Returns list of (layer, shapely_box) tuples.
    """
    sx, sy = src['cx'], src['cy']
    dx, dy = dst['cx'], dst['cy']
    hw = M3_WIDTH / 2

    shapes = []

    v2_half = VIA2_SIZE / 2
    m3_enc = M3_VIA2_ENC
    m3_pad = v2_half + m3_enc
    v3_half = VIA3_SIZE / 2
    m4_pad = v3_half + M4_VIA3_ENC

    # Via2 + M3 pad at source (skip if M3 pin)
    src_is_m3 = src.get('is_m3', False)
    dst_is_m3 = dst.get('is_m3', False)
    if not src_is_m3:
        shapes.append((L_VIA2, sbox(sx - v2_half, sy - v2_half, sx + v2_half, sy + v2_half)))
    shapes.append((L_M3, sbox(sx - m3_pad, sy - hw, sx + m3_pad, sy + hw)))
    if not dst_is_m3:
        shapes.append((L_VIA2, sbox(dx - v2_half, dy - v2_half, dx + v2_half, dy + v2_half)))
    shapes.append((L_M3, sbox(dx - m3_pad, dy - hw, dx + m3_pad, dy + hw)))

    # M3 horizontal from src to m4_x
    x_min, x_max = min(sx, m4_x), max(sx, m4_x)
    if x_max - x_min > 0.01:
        shapes.append((L_M3, sbox(x_min - hw, sy - hw, x_max + hw, sy + hw)))

    # M3 horizontal from m4_x to dst
    x_min2, x_max2 = min(m4_x, dx), max(m4_x, dx)
    if x_max2 - x_min2 > 0.01:
        shapes.append((L_M3, sbox(x_min2 - hw, dy - hw, x_max2 + hw, dy + hw)))

    # M4 vertical from sy to dy
    y_min, y_max = min(sy, dy), max(sy, dy)
    if y_max - y_min > 0.01:
        shapes.append((L_M4, sbox(m4_x - hw, y_min - hw, m4_x + hw, y_max + hw)))

    # Via3 at corners
    shapes.append((L_VIA3, sbox(m4_x - v3_half, sy - v3_half, m4_x + v3_half, sy + v3_half)))
    shapes.append((L_VIA3, sbox(m4_x - v3_half, dy - v3_half, m4_x + v3_half, dy + v3_half)))

    # M3/M4 pads at via3 positions
    shapes.append((L_M3, sbox(m4_x - m3_pad, sy - hw, m4_x + m3_pad, sy + hw)))
    shapes.append((L_M4, sbox(m4_x - hw, sy - m4_pad, m4_x + hw, sy + m4_pad)))
    shapes.append((L_M3, sbox(m4_x - m3_pad, dy - hw, m4_x + m3_pad, dy + hw)))
    shapes.append((L_M4, sbox(m4_x - hw, dy - m4_pad, m4_x + hw, dy + m4_pad)))

    return shapes


LAYER_SPACING = {L_M3: 0.250, L_M4: 0.250, L_VIA2: 0.260, L_VIA3: 0.260}

def check_collision(new_shapes, obstacles, spacing=None):
    """Check if any new shape collides with existing obstacles (per-layer spacing)."""
    for layer, shape in new_shapes:
        obs = obstacles.get(layer)
        if obs and not obs.is_empty:
            sp = LAYER_SPACING.get(layer, 0.250)
            buffered = obs.buffer(sp)
            if shape.intersects(buffered):
                return True
    return False


def route_all():
    print('=== Inter-module Auto Router ===\n')

    # Load data
    with open(os.path.join(OUT_DIR, 'floorplan_coords.json')) as f:
        floorplan = json.load(f)
    m2_pads = load_assembled_m2()
    module_pads = assign_pads_to_modules(m2_pads, floorplan)

    print(f'Loaded {len(m2_pads)} M2 pads across {len(module_pads)} modules\n')

    # Obstacle maps per layer — initialize from existing GDS shapes
    # Exclude zones around digital M3 pins (they are connection points, not obstacles)
    pin_exclusions = []
    for pin_name, rel in DIGITAL_M3_PINS.items():
        ax = DIGITAL_ORIGIN[0] + rel[0]
        ay = DIGITAL_ORIGIN[1] + rel[1]
        pin_exclusions.append(sbox(ax - 1.0, ay - 0.5, ax + 1.0, ay + 0.5))
    pin_excl_union = unary_union(pin_exclusions) if pin_exclusions else None

    obstacles = {}
    lib_obs = gdstk.read_gds(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell_obs = [c for c in lib_obs.cells if c.name == 'tt_um_techhu_analog_trial'][0]
    cell_obs.flatten()
    for layer_key in [L_M3, L_M4, L_VIA2, L_VIA3]:
        polys = []
        for p in cell_obs.polygons:
            if p.layer == layer_key[0] and p.datatype == layer_key[1]:
                try:
                    pg = Polygon(p.points)
                    if pg.is_valid:
                        # For M3: exclude digital pin zones
                        if layer_key == L_M3 and pin_excl_union and pg.intersects(pin_excl_union):
                            remaining = pg.difference(pin_excl_union)
                            if not remaining.is_empty:
                                if hasattr(remaining, 'geoms'):
                                    polys.extend(remaining.geoms)
                                else:
                                    polys.append(remaining)
                        else:
                            polys.append(pg)
                except: pass
        obstacles[layer_key] = unary_union(polys) if polys else None
        if polys:
            print(f'  Pre-existing {layer_key}: {len(polys)} shapes')

    # Track used pads per module (to avoid reuse)
    used_pads = {}

    # Sort nets by estimated length (short first)
    def net_length(net_def):
        name, terminals = net_def
        if len(terminals) < 2:
            return 0
        coords = []
        for mod, _ in terminals:
            m = floorplan.get(mod)
            if m:
                coords.append((m['x'] + m['w']/2, m['y'] + m['h']/2))
        if len(coords) < 2:
            return 0
        return sum(abs(coords[i][0]-coords[i+1][0]) + abs(coords[i][1]-coords[i+1][1])
                   for i in range(len(coords)-1))

    sorted_nets = sorted(NETS, key=net_length)

    # Route each net
    routed = []
    failed = []

    for net_name, terminals in sorted_nets:
        if len(terminals) < 2:
            continue

        # Find pads for each terminal
        pads = []
        for mod, term_type in terminals:
            # Digital M3 pin?
            if mod == 'digital' and term_type != 'auto':
                dpin = digital_pin_abs(term_type)
                if dpin:
                    pads.append((mod, dpin))
                    continue
            other_mods = [t[0] for t in terminals if t[0] != mod]
            if other_mods:
                om = floorplan.get(other_mods[0], {})
                target_cx = om.get('x', 0) + om.get('w', 0)/2
                target_cy = om.get('y', 0) + om.get('h', 0)/2
            else:
                target_cx = target_cy = None
            used = used_pads.get(mod, [])
            pad = find_nearest_pad(module_pads, mod, target_cx, target_cy, exclude_pads=used)
            if pad:
                pads.append((mod, pad))

        if len(pads) < 2:
            failed.append((net_name, 'insufficient M2 pads'))
            continue

        # For multi-terminal nets, route as chain (pad0→pad1→pad2→...)
        all_shapes = []
        success = True
        for i in range(len(pads) - 1):
            src_mod, src_pad = pads[i]
            dst_mod, dst_pad = pads[i + 1]
            shapes = l_route(src_pad, dst_pad)

            # Check collision with multiple M4 column positions
            found = False
            sx, dx = src_pad['cx'], dst_pad['cx']
            mid_x = (sx + dx) / 2
            DIG_RIGHT = DIGITAL_ORIGIN[0] + 31
            DIG_LEFT = DIGITAL_ORIGIN[0] - 1
            if src_pad.get('is_m3') or dst_pad.get('is_m3'):
                dig_pad = src_pad if src_pad.get('is_m3') else dst_pad
                if dig_pad['cx'] > 40:
                    candidates = [DIG_RIGHT + o for o in [0,1,2,3,5,8,10,15]]
                else:
                    candidates = [DIG_LEFT + o for o in [0,-1,-2,-3,-5,-8]]
            else:
                offsets = [0, -1, 1, -2, 2, -3, 3, -5, 5, -8, 8, -12, 12, -15, 15, -20, 20]
                candidates = [dx + o for o in offsets] + [sx + o for o in offsets] + [mid_x + o for o in offsets]
            for m4_x in candidates:
                shapes = l_route_flex(src_pad, dst_pad, m4_x)
                if not check_collision(shapes, obstacles, M3_SPACE):
                    found = True
                    break
            # If L-route fails and involves digital pin, try Z-route via free y channels
            if not found and (src_pad.get('is_m3') or dst_pad.get('is_m3')):
                free_ys = [8, 10, 12, 15, 68, 70, 72, 80, 82, 84]
                for m4_x in candidates:
                    for mid_y in free_ys:
                        shapes = z_route(src_pad, dst_pad, m4_x, mid_y)
                        if not check_collision(shapes, obstacles, M3_SPACE):
                            found = True
                            break
                    if found: break
            if not found:
                failed.append((net_name, f'{src_mod}→{dst_mod} collision'))
                success = False
                break

            all_shapes.extend(shapes)

        if success:
            # Update obstacles
            for layer, shape in all_shapes:
                if layer in obstacles:
                    if obstacles[layer] is None:
                        obstacles[layer] = shape
                    else:
                        obstacles[layer] = unary_union([obstacles[layer], shape])

            dist = sum(abs(pads[i][1]['cx']-pads[i+1][1]['cx']) +
                       abs(pads[i][1]['cy']-pads[i+1][1]['cy'])
                       for i in range(len(pads)-1))
            # Record used pads
            for mod, pad in pads:
                used_pads.setdefault(mod, []).append(pad)
            routed.append((net_name, all_shapes, pads, dist))
            print(f'  ✓ {net_name:16s} {len(pads)} terminals, {len(all_shapes)} shapes, {dist:.0f}um')
        else:
            print(f'  ✗ {net_name:16s} FAILED')

    print(f'\n  Routed: {len(routed)}/{len(NETS)}')
    if failed:
        print(f'  Failed: {len(failed)}')
        for name, reason in failed:
            print(f'    {name}: {reason}')

    # Write to GDS
    if routed:
        write_routes_to_gds(routed)

    return routed, failed


def write_routes_to_gds(routed):
    """Add routes to assembled GDS."""
    lib = gdstk.read_gds(os.path.join(OUT_DIR, 'soilz_assembled.gds'))
    cell = [c for c in lib.cells if c.name == 'tt_um_techhu_analog_trial'][0]

    total = 0
    for net_name, shapes, pads, dist in routed:
        for (layer_num, layer_dt), shapely_shape in shapes:
            b = shapely_shape.bounds  # (x1, y1, x2, y2) in um
            rect = gdstk.rectangle(
                (b[0], b[1]), (b[2], b[3]),
                layer=layer_num, datatype=layer_dt)
            cell.add(rect)
            total += 1

    out_path = os.path.join(OUT_DIR, 'soilz_routed.gds')
    lib.write_gds(out_path)
    print(f'\n  Wrote {total} shapes to {out_path}')


if __name__ == '__main__':
    route_all()
    print('\n=== Done ===')
