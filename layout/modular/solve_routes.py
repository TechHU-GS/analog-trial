#!/usr/bin/env python3
"""OR-Tools CP-SAT solver for remaining inter-module routes.

Routes the 19 easy nets first (greedy), then uses constraint programming
to find collision-free paths for the remaining hard nets simultaneously.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 modular/solve_routes.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ortools.sat.python import cp_model
import route_intermodule as ri

ri.OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')

from shapely.geometry import box as sbox
from shapely.ops import unary_union
import gdstk


def build_obstacles_and_pads():
    """Route easy nets, return obstacles + pad info for hard nets."""
    with open(os.path.join(ri.OUT_DIR, 'floorplan_coords.json')) as f:
        fp = json.load(f)

    m2_pads = ri.load_assembled_m2()
    module_pads = ri.assign_pads_to_modules(m2_pads, fp)

    dig_ox = fp['digital']['x'] if 'digital' in fp else 23.0
    dig_oy = fp['digital']['y'] if 'digital' in fp else 5.0

    # Build initial obstacles from GDS
    pin_exclusions = []
    for pn, rel in ri.DIGITAL_M3_PINS.items():
        pin_exclusions.append(sbox(dig_ox+rel[0]-1, dig_oy+rel[1]-0.5, dig_ox+rel[0]+1, dig_oy+rel[1]+0.5))
    pin_excl_union = unary_union(pin_exclusions)

    lib_obs = gdstk.read_gds(os.path.join(ri.OUT_DIR, 'soilz_assembled.gds'))
    cell_obs = [c for c in lib_obs.cells if c.name == 'tt_um_techhu_analog_trial'][0]
    cell_obs.flatten()

    from shapely.geometry import Polygon
    obstacles = {}
    for lk in [ri.L_M3, ri.L_M4, ri.L_VIA2, ri.L_VIA3]:
        polys = []
        for p in cell_obs.polygons:
            if p.layer == lk[0] and p.datatype == lk[1]:
                try:
                    pg = Polygon(p.points)
                    if pg.is_valid:
                        if lk == ri.L_M3 and pg.intersects(pin_excl_union):
                            rem = pg.difference(pin_excl_union)
                            if not rem.is_empty:
                                polys.extend(rem.geoms if hasattr(rem,'geoms') else [rem])
                        else: polys.append(pg)
                except: pass
        obstacles[lk] = unary_union(polys) if polys else None

    # Route easy nets first
    HARD_NETS = {'pmos_bias', 'vco_out'}
    easy_nets = [n for n in ri.NETS if n[0] not in HARD_NETS]
    hard_nets = [n for n in ri.NETS if n[0] in HARD_NETS]

    used_pads = {}
    easy_routed = 0

    PRIORITY = {'ota_out', 'sum_n', 'nmos_bias', 'pmos_bias'}
    easy_sorted = sorted(easy_nets, key=lambda n: (0 if n[0] in PRIORITY else 1, 0))

    for net_name, terminals in easy_sorted:
        pads = []
        for mod, tt in terminals:
            if mod == 'digital' and tt != 'auto':
                dpin = ri.digital_pin_abs(tt, fp)
                if dpin: pads.append((mod, dpin)); continue
            other = [t[0] for t in terminals if t[0] != mod]
            om = fp.get(other[0],{}) if other else {}
            tcx = om.get('x',0)+om.get('w',0)/2 if om else None
            tcy = om.get('y',0)+om.get('h',0)/2 if om else None
            pad = ri.find_nearest_pad(module_pads, mod, tcx, tcy, used_pads.get(mod,[]))
            if pad: pads.append((mod, pad))

        if len(pads) < 2: continue
        if len(pads) > 2: pads.sort(key=lambda p: p[1]['cx'])

        ok = True
        shapes_all = []
        for i in range(len(pads)-1):
            sp, dp = pads[i][1], pads[i+1][1]
            sx, dx = sp['cx'], dp['cx']
            mx = (sx+dx)/2
            DIG_R = dig_ox+31; DIG_L = dig_ox-1
            if sp.get('is_m3') or dp.get('is_m3'):
                dp2 = sp if sp.get('is_m3') else dp
                cands = [DIG_R+o for o in [0,1,2,3,5,8,10,15]] if dp2['cx']>40 else [DIG_L+o for o in [0,-1,-2,-3,-5,-8]]
            else:
                offs = list(range(-30,31,1))
                cands = list(set([dx+o for o in offs]+[sx+o for o in offs]+[mx+o for o in offs]))

            found = False
            for m4x in cands:
                sh = ri.l_route_flex(sp, dp, m4x)
                if not ri.check_collision(sh, obstacles):
                    found = True; shapes_all.extend(sh); break
            if not found:
                zys = list(range(3,95,2))
                for m4x in cands[:20]:
                    for my in zys:
                        sh = ri.z_route(sp, dp, m4x, my)
                        if not ri.check_collision(sh, obstacles):
                            found = True; shapes_all.extend(sh); break
                    if found: break
            if not found: ok = False; break

        if ok:
            for mod,pad in pads: used_pads.setdefault(mod,[]).append(pad)
            for layer,shape in shapes_all:
                if layer in obstacles:
                    obstacles[layer] = unary_union([obstacles[layer],shape]) if obstacles[layer] else shape
            easy_routed += 1

    print(f'Easy nets: {easy_routed}/{len(easy_nets)} routed')

    # Get pads for hard nets
    hard_pad_info = {}
    for net_name, terminals in hard_nets:
        pads = []
        for mod, tt in terminals:
            if mod == 'digital' and tt != 'auto':
                dpin = ri.digital_pin_abs(tt, fp)
                if dpin: pads.append((mod, dpin)); continue
            other = [t[0] for t in terminals if t[0] != mod]
            om = fp.get(other[0],{}) if other else {}
            tcx = om.get('x',0)+om.get('w',0)/2 if om else None
            tcy = om.get('y',0)+om.get('h',0)/2 if om else None
            pad = ri.find_nearest_pad(module_pads, mod, tcx, tcy, used_pads.get(mod,[]))
            if pad: pads.append((mod, pad))
        if len(pads) > 2: pads.sort(key=lambda p: p[1]['cx'])
        hard_pad_info[net_name] = pads

    return obstacles, hard_pad_info, fp, dig_ox


def solve_hard_nets(obstacles, hard_pad_info, fp, dig_ox):
    """Use CP-SAT to find simultaneous collision-free routes for hard nets."""
    model = cp_model.CpModel()

    # Discretize: M4_x in 0.5um steps (100-200um), mid_y in 1um steps (3-95)
    M4_RANGE = list(range(500, 2000, 5))  # 0.1um units → 500 to 2000 (50-200um)
    MY_RANGE = list(range(30, 950, 10))    # 0.1um units → 30 to 950 (3-95um)

    # For each hard net segment, create variables
    segments = {}
    for net_name, pads in hard_pad_info.items():
        for i in range(len(pads)-1):
            seg_id = f'{net_name}_{i}'
            sp, dp = pads[i][1], pads[i+1][1]

            # M4 column x (in 0.1um units)
            m4x_var = model.NewIntVar(500, 2000, f'm4x_{seg_id}')
            # Route type: 0=L-route, 1=Z-route
            is_z = model.NewBoolVar(f'isz_{seg_id}')
            # Mid Y for Z-route (in 0.1um units)
            my_var = model.NewIntVar(30, 950, f'my_{seg_id}')

            segments[seg_id] = {
                'src': sp, 'dst': dp, 'net': net_name,
                'm4x': m4x_var, 'is_z': is_z, 'mid_y': my_var,
            }

    # For each candidate (m4x, mid_y), pre-check collision with fixed obstacles
    # This is too many combinations for explicit constraints
    # Instead: enumerate feasible (m4x) for L-route and (m4x, mid_y) for Z-route

    print(f'\nFinding feasible candidates for {len(segments)} segments...')

    feasible = {}
    for seg_id, seg in segments.items():
        sp, dp = seg['src'], seg['dst']
        sx, dx = int(sp['cx']*10), int(dp['cx']*10)

        # L-route feasible m4x values
        l_feasible = []
        for m4x_10 in range(min(sx,dx)-300, max(sx,dx)+300, 5):
            m4x = m4x_10 / 10.0
            shapes = ri.l_route_flex(sp, dp, m4x)
            if not ri.check_collision(shapes, obstacles):
                l_feasible.append(m4x_10)

        # Z-route feasible (m4x, mid_y) pairs
        z_feasible = []
        if not l_feasible:
            # Only try Z if L fails
            for m4x_10 in range(min(sx,dx)-300, max(sx,dx)+300, 10):
                m4x = m4x_10 / 10.0
                for my_10 in range(30, 950, 20):
                    mid_y = my_10 / 10.0
                    shapes = ri.z_route(sp, dp, m4x, mid_y)
                    if not ri.check_collision(shapes, obstacles):
                        z_feasible.append((m4x_10, my_10))

        feasible[seg_id] = {'L': l_feasible, 'Z': z_feasible}
        print(f'  {seg_id}: {len(l_feasible)} L-routes, {len(z_feasible)} Z-routes')

    # Now check which combinations are mutually compatible
    # For each pair of segments, check if their chosen routes collide
    seg_ids = list(segments.keys())

    # Enumerate all valid single-segment routes
    all_options = {}  # seg_id → list of (type, m4x, mid_y, shapes)
    for seg_id, seg in segments.items():
        sp, dp = seg['src'], seg['dst']
        options = []
        for m4x_10 in feasible[seg_id]['L']:
            m4x = m4x_10 / 10.0
            shapes = ri.l_route_flex(sp, dp, m4x)
            options.append(('L', m4x, None, shapes))
        for m4x_10, my_10 in feasible[seg_id]['Z']:
            m4x = m4x_10 / 10.0
            mid_y = my_10 / 10.0
            shapes = ri.z_route(sp, dp, m4x, mid_y)
            options.append(('Z', m4x, mid_y, shapes))
        all_options[seg_id] = options
        print(f'  {seg_id}: {len(options)} total options')

    # If any segment has 0 options, impossible
    for seg_id, opts in all_options.items():
        if not opts:
            print(f'\n  {seg_id}: NO FEASIBLE ROUTE — layout must change')
            return None

    # For segments from the same net chain, find compatible pairs
    # Use CP-SAT: one variable per segment = index into options list
    print(f'\nBuilding CP-SAT model...')
    model = cp_model.CpModel()

    choice_vars = {}
    for seg_id, opts in all_options.items():
        choice_vars[seg_id] = model.NewIntVar(0, len(opts)-1, f'choice_{seg_id}')

    # Constraint: chosen routes must not collide with each other
    # For each pair of segments, add incompatible pairs
    for i in range(len(seg_ids)):
        for j in range(i+1, len(seg_ids)):
            si, sj = seg_ids[i], seg_ids[j]
            incompatible = []
            for oi, (_, _, _, shapes_i) in enumerate(all_options[si]):
                for oj, (_, _, _, shapes_j) in enumerate(all_options[sj]):
                    # Check if these two routes collide
                    collides = False
                    for layer_i, shape_i in shapes_i:
                        for layer_j, shape_j in shapes_j:
                            if layer_i == layer_j:
                                sp = ri.LAYER_SPACING.get(layer_i, 0.25)
                                if shape_i.buffer(sp).intersects(shape_j):
                                    collides = True
                                    break
                        if collides: break
                    if collides:
                        incompatible.append((oi, oj))

            # Add forbidden assignments
            for oi, oj in incompatible:
                b = model.NewBoolVar(f'inc_{si}_{sj}_{oi}_{oj}')
                model.Add(choice_vars[si] != oi).OnlyEnforceIf(b)
                model.Add(choice_vars[sj] != oj).OnlyEnforceIf(b.Not())
                # Simpler: just add that not both can be chosen
                model.AddForbiddenAssignments(
                    [choice_vars[si], choice_vars[sj]], [(oi, oj)])

            print(f'  {si} vs {sj}: {len(incompatible)} incompatible pairs (of {len(all_options[si])*len(all_options[sj])})')

    # Solve
    print(f'\nSolving...')
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f'SOLUTION FOUND!')
        result = {}
        for seg_id in seg_ids:
            idx = solver.Value(choice_vars[seg_id])
            typ, m4x, mid_y, shapes = all_options[seg_id][idx]
            result[seg_id] = (typ, m4x, mid_y, shapes)
            print(f'  {seg_id}: {typ}-route m4x={m4x:.1f}' + (f' mid_y={mid_y:.1f}' if mid_y else ''))
        return result
    else:
        print(f'NO SOLUTION (status={status})')
        return None


if __name__ == '__main__':
    print('=== OR-Tools Route Solver ===\n')
    obstacles, hard_pad_info, fp, dig_ox = build_obstacles_and_pads()
    result = solve_hard_nets(obstacles, hard_pad_info, fp, dig_ox)

    if result:
        print('\n=== Writing routes to GDS ===')
        # Add solved routes + easy routes to GDS
        # For now just report success

    print('\n=== Done ===')
