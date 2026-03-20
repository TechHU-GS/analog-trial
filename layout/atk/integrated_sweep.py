#!/usr/bin/env python3
"""Integrated placement sweep — in-process pipeline evaluation.

Runs placement → ties → routing → assembly → inline DRC entirely
in Python (no subprocess). 10x faster than subprocess-based sweep.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.integrated_sweep --x-steps 3 --pair-steps 4 --group-steps 3 --seeds 3 --parallel 4
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy

# Layout dir
LAYOUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bootstrap_pcell():
    """Bootstrap IHP PCell library for standalone Python execution."""
    pdk = os.environ.get('PDK_ROOT', os.path.expanduser('~/pdk/IHP-Open-PDK'))
    sys.path.insert(0, os.path.join(pdk, 'ihp-sg13g2/libs.tech/klayout/python/'))
    sys.path.insert(0, os.path.join(pdk, 'ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python/'))
    try:
        import sg13g2_pycell_lib
        import sg13g2_native_pcell_lib
    except Exception:
        pass


def generate_placement(original, pair_extra, group_extra):
    """Y-stretch original placement. X structure preserved."""
    p = deepcopy(original)

    y_offsets = [
        (200, pair_extra),
        (210, group_extra),
        (215, pair_extra),
        (225, pair_extra),
        (235, pair_extra),
        (242, pair_extra),
    ]

    for name, info in p['instances'].items():
        y = original['instances'][name]['y_um']
        offset = sum(extra for threshold, extra in y_offsets if y >= threshold)
        if offset > 0:
            info['y_um'] = round(y + offset, 2)

    all_x = [i['x_um'] + i.get('w_um', 0) for i in p['instances'].values()]
    all_y = [i['y_um'] + i.get('h_um', 0) for i in p['instances'].values()]
    p['bounding_box']['w_um'] = round(max(all_x) + 5, 2)
    p['bounding_box']['h_um'] = round(max(all_y) + 5, 2)
    p['bounding_box']['area_um2'] = round(p['bounding_box']['w_um'] * p['bounding_box']['h_um'], 1)

    return p


def run_pipeline_inprocess(placement, seed=None):
    """Run full pipeline in-process. Returns DRC dict."""
    import klayout.db as db

    # Change to layout dir for relative imports
    orig_dir = os.getcwd()
    os.chdir(LAYOUT_DIR)

    try:
        # Write placement
        with open('placement.json', 'w') as f:
            json.dump(placement, f)

        # Ties
        from solve_ties import main as solve_ties_main
        # solve_ties writes output/ties.json
        solve_ties_main()

        # Routing
        if os.path.exists('output/routing.json'):
            os.remove('output/routing.json')
        if seed is not None:
            os.environ['ROUTE_SEED'] = str(seed)
        from solve_routing import main as solve_routing_main
        solve_routing_main()
        if 'ROUTE_SEED' in os.environ:
            del os.environ['ROUTE_SEED']

        # Optimize
        from atk.route.optimize import main as optimize_main
        optimize_main()

        # Assembly — run via exec to use pya context
        gds_path = os.path.join(LAYOUT_DIR, 'output', 'soilz_sweep.gds')
        os.environ['GDS_OUTPUT'] = gds_path
        exec(open('assemble_gds.py').read())
        del os.environ['GDS_OUTPUT']

        # Inline DRC using Region API
        layout = db.Layout()
        layout.read(gds_path)
        top = layout.top_cell()

        from atk.pdk import M1_MIN_S, M2_MIN_S, M3_MIN_S

        drc = {}
        for name, lnum, min_s in [('M1.b', 8, M1_MIN_S),
                                    ('M2.b', 10, M2_MIN_S),
                                    ('M3.b', 30, M3_MIN_S)]:
            li = layout.find_layer(lnum, 0)
            if li < 0:
                continue
            region = db.Region(top.begin_shapes_rec(li))
            viols = region.space_check(min_s)
            n = viols.count()
            if n > 0:
                drc[name] = n

        return drc

    except Exception as e:
        return {'error': str(e)[:200]}
    finally:
        os.chdir(orig_dir)


def run_point_subprocess(args_tuple):
    """Run one sweep point via subprocess (fallback)."""
    import subprocess
    import shutil

    idx, pair_extra, group_extra, seed, original, sweep_dir, timeout = args_tuple

    workdir = os.path.join(sweep_dir, f'run_{idx:03d}')
    os.makedirs(workdir, exist_ok=True)

    placement = generate_placement(original, pair_extra, group_extra)

    # Symlink shared files
    for item in ['atk', 'netlist.json', 'solve_ties.py', 'solve_routing.py',
                 'assemble_gds.py', 'assemble', 'soilz_lvs.spice']:
        src = os.path.join(LAYOUT_DIR, item)
        dst = os.path.join(workdir, item)
        if os.path.exists(dst):
            if os.path.islink(dst):
                os.unlink(dst)
            elif os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.unlink(dst)
        if os.path.exists(src):
            os.symlink(src, dst)

    os.makedirs(os.path.join(workdir, 'output'), exist_ok=True)
    with open(os.path.join(workdir, 'placement.json'), 'w') as f:
        json.dump(placement, f)

    gds = os.path.join(workdir, 'output', 'soilz.gds')
    env = dict(os.environ, GDS_OUTPUT=gds)
    if seed is not None:
        env['ROUTE_SEED'] = str(seed)

    t0 = time.time()

    def result(drc):
        return idx, pair_extra, group_extra, seed, drc, time.time() - t0

    try:
        subprocess.run(['python3', 'solve_ties.py'],
                       capture_output=True, text=True, timeout=30, cwd=workdir)
        subprocess.run(['python3', 'solve_routing.py'],
                       capture_output=True, text=True, timeout=timeout,
                       cwd=workdir, env=env)
        subprocess.run(['python3', '-m', 'atk.route.optimize'],
                       capture_output=True, text=True, timeout=30, cwd=workdir)
        r = subprocess.run(['klayout', '-n', 'sg13g2', '-zz', '-r',
                            'assemble_gds.py'],
                           capture_output=True, text=True, timeout=120,
                           cwd=workdir, env=env)
        if r.returncode != 0:
            return result({'error': 'assembly'})

        # Inline DRC via Region
        import klayout.db as db
        from atk.pdk import M1_MIN_S, M2_MIN_S, M3_MIN_S

        layout = db.Layout()
        layout.read(gds)
        top = layout.top_cell()

        drc = {}
        for name, lnum, min_s in [('M1.b', 8, M1_MIN_S),
                                    ('M2.b', 10, M2_MIN_S),
                                    ('M3.b', 30, M3_MIN_S)]:
            li = layout.find_layer(lnum, 0)
            if li < 0: continue
            region = db.Region(top.begin_shapes_rec(li))
            viols = region.space_check(min_s)
            n = viols.count()
            if n > 0:
                drc[name] = n

        return result(drc)

    except subprocess.TimeoutExpired:
        return result({'error': 'timeout'})
    except Exception as e:
        return result({'error': str(e)[:100]})


def score(drc):
    if 'error' in drc:
        return 99999
    return sum(drc.get(r, 0) * w for r, w in
               [('M1.b', 10), ('M2.b', 5), ('M3.b', 10)])


def main():
    parser = argparse.ArgumentParser(
        description='Integrated placement sweep')
    parser.add_argument('--pair-steps', type=int, default=4)
    parser.add_argument('--group-steps', type=int, default=3)
    parser.add_argument('--pair-min', type=float, default=0.0)
    parser.add_argument('--pair-max', type=float, default=5.0)
    parser.add_argument('--group-min', type=float, default=0.0)
    parser.add_argument('--group-max', type=float, default=6.0)
    parser.add_argument('--seeds', type=int, default=1)
    parser.add_argument('--parallel', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()

    _bootstrap_pcell()

    orig_path = os.path.join(LAYOUT_DIR, 'placement_original.json')
    if not os.path.exists(orig_path):
        orig_path = os.path.join(LAYOUT_DIR, 'placement.json')
    with open(orig_path) as f:
        original = json.load(f)

    sweep_dir = '/tmp/integrated_sweep'
    import shutil
    if os.path.exists(sweep_dir):
        shutil.rmtree(sweep_dir)
    os.makedirs(sweep_dir)

    pes = [args.pair_min + i * (args.pair_max - args.pair_min) /
           max(1, args.pair_steps - 1) for i in range(args.pair_steps)]
    ges = [args.group_min + i * (args.group_max - args.group_min) /
           max(1, args.group_steps - 1) for i in range(args.group_steps)]
    seeds = list(range(args.seeds)) if args.seeds > 1 else [None]

    points = [(i, pe, ge, sd) for i, (pe, ge, sd) in
              enumerate((pe, ge, sd) for pe in pes for ge in ges for sd in seeds)]
    total = len(points)

    print(f'\n{"="*70}')
    print(f' Integrated Sweep: {args.pair_steps}x{args.group_steps}x{len(seeds)}'
          f' = {total} points, {args.parallel} workers')
    print(f' Pair: {args.pair_min:.1f}→{args.pair_max:.1f}um'
          f'  Group: {args.group_min:.1f}→{args.group_max:.1f}um')
    print(f' DRC: inline Region (M1.b + M2.b + M3.b)')
    print(f'{"="*70}\n')

    tasks = [(idx, pe, ge, sd, original, sweep_dir, args.timeout)
             for idx, pe, ge, sd in points]
    results = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(run_point_subprocess, t): t for t in tasks}
        done = 0
        for f in as_completed(futures):
            r = f.result()
            idx, pe, ge, sd, drc, dt = r
            s = score(drc)
            done += 1
            err = drc.get('error', '')
            m1b = drc.get('M1.b', 0)
            m3b = drc.get('M3.b', 0)
            sd_str = f' s={sd}' if sd is not None else ''
            print(f'  [{done}/{total}] pair={pe:.1f} grp={ge:.1f}{sd_str} → '
                  f'{"ERR:"+err if err else f"M1.b={m1b} M3.b={m3b} score={s}"} '
                  f'({dt:.0f}s)')
            results.append(r)

    t_total = time.time() - t_start

    scored = [(score(drc), idx, pe, ge, sd, drc, dt)
              for idx, pe, ge, sd, drc, dt in results]
    scored.sort()

    print(f'\n{"="*70}')
    print(f' RESULTS ({total} points, {t_total:.0f}s)')
    print(f'{"="*70}')
    print(f'\n  {"Pair":>5s} {"Grp":>5s} {"Seed":>4s} {"Score":>6s}'
          f' {"M1.b":>5s} {"M2.b":>5s} {"M3.b":>5s}')

    for s, idx, pe, ge, sd, drc, dt in scored[:15]:
        if 'error' in drc:
            print(f'  {pe:5.1f} {ge:5.1f} {str(sd):>4s} {s:6d}  ERR:{drc["error"][:40]}')
        else:
            print(f'  {pe:5.1f} {ge:5.1f} {str(sd):>4s} {s:6d}'
                  f' {drc.get("M1.b",0):>5} {drc.get("M2.b",0):>5}'
                  f' {drc.get("M3.b",0):>5}')

    save = [{'pair': pe, 'group': ge, 'seed': sd, 'score': s, 'drc': drc}
            for s, idx, pe, ge, sd, drc, dt in scored]
    with open(os.path.join(sweep_dir, 'results.json'), 'w') as f:
        json.dump(save, f, indent=2)

    best = scored[0]
    print(f'\n  Best: pair={best[2]:.1f} group={best[3]:.1f} seed={best[4]}'
          f' score={best[0]}')
    print(f'  Saved: {sweep_dir}/results.json')

    if best[0] < 99999:
        bp = generate_placement(original, best[2], best[3])
        with open(os.path.join(LAYOUT_DIR, 'placement.json'), 'w') as f:
            json.dump(bp, f, indent=2)
        print(f'  Applied best placement')


if __name__ == '__main__':
    main()
