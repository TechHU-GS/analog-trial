#!/usr/bin/env python3
"""Parameterized digital placement sweep (parallel).

Sweeps X gap, Y gap, and routing seed. Runs full pipeline per point,
collects DRC scores. Supports parallel execution on ECS.

Usage:
    cd layout && source ~/pdk/venv/bin/activate
    python3 -m atk.sweep_placement --x-steps 5 --y-steps 5 --seeds 5 --parallel 96
"""

import argparse
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy


DIGITAL_PREFIXES = {
    'dig_left': ['T1I_', 'T1Q_', 'T2I_', 'T2Q_'],
    'dig_right': ['T3_', 'T4I_', 'T4Q_', 'MXfi_', 'MXfq_', 'MXiq_',
                  'BUF_', 'INV_'],
}

PDK_ROOT = os.environ.get('PDK_ROOT',
                          os.path.expanduser('~/pdk/IHP-Open-PDK'))
CELL = 'soilz'
LAYOUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def generate_placement(original, x_gap_factor, y_gap_extra):
    """Generate placement with digital devices spread.

    x_gap_factor: multiply X gaps within each row (1.0 = original).
    y_gap_extra: add this many um between each digital row pair.
    """
    p = deepcopy(original)

    # --- X spreading ---
    for region, prefixes in DIGITAL_PREFIXES.items():
        rows = {}
        for name, info in p['instances'].items():
            if any(name.startswith(pf) for pf in prefixes):
                y = round(info['y_um'], 1)
                rows.setdefault(y, []).append(name)

        for y, names in rows.items():
            names.sort(key=lambda n: original['instances'][n]['x_um'])
            if len(names) <= 1:
                continue
            orig_xs = [original['instances'][n]['x_um'] for n in names]
            center = (orig_xs[0] + orig_xs[-1]) / 2
            for name, orig_x in zip(names, orig_xs):
                new_x = center + (orig_x - center) * x_gap_factor
                p['instances'][name]['x_um'] = round(new_x, 2)

    # --- Y spreading ---
    if y_gap_extra > 0:
        all_dig_names = set()
        for prefixes in DIGITAL_PREFIXES.values():
            for name in p['instances']:
                if any(name.startswith(pf) for pf in prefixes):
                    all_dig_names.add(name)

        orig_ys = sorted(set(round(original['instances'][n]['y_um'], 1)
                             for n in all_dig_names))

        if len(orig_ys) > 1:
            y_offsets = {y: i * y_gap_extra for i, y in enumerate(orig_ys)}
            for name in all_dig_names:
                orig_y = round(original['instances'][name]['y_um'], 1)
                offset = y_offsets.get(orig_y, 0)
                p['instances'][name]['y_um'] = round(
                    original['instances'][name]['y_um'] + offset, 2)

    # Update bounding box
    all_x = [i['x_um'] + i.get('w_um', 0) for i in p['instances'].values()]
    all_y = [i['y_um'] + i.get('h_um', 0) for i in p['instances'].values()]
    p['bounding_box']['w_um'] = round(max(all_x) + 5, 2)
    p['bounding_box']['h_um'] = round(max(all_y) + 5, 2)

    return p


def setup_workdir(workdir, placement):
    """Create isolated working directory with symlinks + placement."""
    os.makedirs(workdir, exist_ok=True)

    for item in ['atk', 'netlist.json', 'solve_ties.py', 'solve_routing.py',
                 'assemble_gds.py', 'soilz_lvs.spice']:
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


def run_single_point(args_tuple):
    """Run one sweep point in isolated directory."""
    idx, x_factor, y_extra, seed, original, sweep_dir, routing_timeout = args_tuple

    workdir = os.path.join(sweep_dir, f'run_{idx:03d}')
    placement = generate_placement(original, x_factor, y_extra)
    setup_workdir(workdir, placement)

    gds = os.path.join(workdir, 'output', f'{CELL}.gds')
    drc_dir = os.path.join(workdir, 'drc')
    os.makedirs(drc_dir, exist_ok=True)

    env = dict(os.environ, GDS_OUTPUT=gds)
    if seed is not None:
        env['ROUTE_SEED'] = str(seed)
    t0 = time.time()

    def result(drc):
        return idx, x_factor, y_extra, seed, drc, time.time() - t0

    try:
        # Ties
        r = subprocess.run(['python3', 'solve_ties.py'],
                           capture_output=True, text=True, timeout=30,
                           cwd=workdir)
        if r.returncode != 0:
            return result({'error': 'ties'})

        # Routing (seed via ROUTE_SEED env var)
        r = subprocess.run(['python3', 'solve_routing.py'],
                           capture_output=True, text=True,
                           timeout=routing_timeout, cwd=workdir, env=env)

        # Optimize
        subprocess.run(['python3', '-m', 'atk.route.optimize'],
                       capture_output=True, text=True, timeout=30,
                       cwd=workdir)

        # Assembly
        r = subprocess.run(['klayout', '-n', 'sg13g2', '-zz', '-r',
                            'assemble_gds.py'],
                           capture_output=True, text=True, timeout=120,
                           cwd=workdir, env=env)
        if r.returncode != 0:
            return result({'error': 'assembly'})

        # DRC
        subprocess.run([
            'python3',
            f'{PDK_ROOT}/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py',
            f'--path={gds}', f'--topcell={CELL}',
            f'--run_dir={drc_dir}', '--mp=1', '--no_density'],
            capture_output=True, text=True, timeout=120, cwd=workdir)

        # Parse results
        lyrdb = os.path.join(drc_dir, f'{CELL}_{CELL}_full.lyrdb')
        if not os.path.exists(lyrdb):
            return result({'error': 'no_lyrdb'})

        diag_out = os.path.join(workdir, 'diag.json')
        subprocess.run([
            'python3', '-m', 'atk.diagnose_drc',
            f'--lyrdb={lyrdb}', f'--gds={gds}',
            f'--routing=output/routing.json',
            f'--output={diag_out}'],
            capture_output=True, text=True, timeout=60, cwd=workdir)

        if os.path.exists(diag_out):
            with open(diag_out) as f:
                diag = json.load(f)
            return result(diag.get('by_rule', {}))

        return result({'error': 'no_diag'})

    except subprocess.TimeoutExpired:
        return result({'error': 'timeout'})
    except Exception as e:
        return result({'error': str(e)[:100]})


def score(drc_result):
    """Composite score: lower = better."""
    if 'error' in drc_result:
        return 99999

    critical = sum(drc_result.get(r, 0)
                   for r in ['M1.b', 'M1.e', 'M3.b', 'M5.b', 'V3.b'])
    major = sum(drc_result.get(r, 0)
                for r in ['pSD.c', 'NW.c', 'Cnt.b', 'NW.f', 'Act.b'])
    minor = sum(v for k, v in drc_result.items()
                if isinstance(v, int) and k not in
                {'M1.b', 'M1.e', 'M3.b', 'M5.b', 'V3.b',
                 'pSD.c', 'NW.c', 'Cnt.b', 'NW.f', 'Act.b', 'total'})

    return critical * 10 + major * 3 + minor


def main():
    parser = argparse.ArgumentParser(
        description='Sweep digital placement parameters (parallel)')
    parser.add_argument('--x-steps', type=int, default=5)
    parser.add_argument('--y-steps', type=int, default=5)
    parser.add_argument('--x-min', type=float, default=1.0)
    parser.add_argument('--x-max', type=float, default=1.5)
    parser.add_argument('--y-min', type=float, default=0.0)
    parser.add_argument('--y-max', type=float, default=4.0)
    parser.add_argument('--seeds', type=int, default=1,
                        help='Number of routing seeds (1=no sweep)')
    parser.add_argument('--parallel', type=int, default=1)
    parser.add_argument('--routing-timeout', type=int, default=300)
    args = parser.parse_args()

    orig_path = os.path.join(LAYOUT_DIR, 'placement_original.json')
    if not os.path.exists(orig_path):
        orig_path = os.path.join(LAYOUT_DIR, 'placement.json')
    with open(orig_path) as f:
        original = json.load(f)

    sweep_dir = '/tmp/placement_sweep'
    if os.path.exists(sweep_dir):
        shutil.rmtree(sweep_dir)
    os.makedirs(sweep_dir)

    x_factors = [args.x_min + i * (args.x_max - args.x_min) /
                 max(1, args.x_steps - 1) for i in range(args.x_steps)]
    y_extras = [args.y_min + i * (args.y_max - args.y_min) /
                max(1, args.y_steps - 1) for i in range(args.y_steps)]
    seeds = list(range(args.seeds)) if args.seeds > 1 else [None]

    points = []
    for i, (xf, ye, sd) in enumerate(
            (xf, ye, sd) for xf in x_factors
            for ye in y_extras for sd in seeds):
        points.append((i, xf, ye, sd))
    total = len(points)

    print(f'\n{"="*70}')
    print(f' Placement Sweep: {args.x_steps}x{args.y_steps}x{len(seeds)} '
          f'= {total} points, {args.parallel} workers')
    print(f' X gap: {args.x_min:.2f}→{args.x_max:.2f} ({args.x_steps})')
    print(f' Y gap: {args.y_min:.1f}→{args.y_max:.1f}um ({args.y_steps})')
    print(f' Seeds: {seeds}')
    print(f' Timeout: {args.routing_timeout}s')
    print(f'{"="*70}\n')

    t_start = time.time()
    tasks = [(idx, xf, ye, sd, original, sweep_dir, args.routing_timeout)
             for idx, xf, ye, sd in points]

    results = []
    if args.parallel <= 1:
        for task in tasks:
            r = run_single_point(task)
            idx, xf, ye, sd, drc, dt = r
            s = score(drc)
            err = drc.get('error', '')
            tv = sum(v for v in drc.values() if isinstance(v, int))
            sd_str = f' s={sd}' if sd is not None else ''
            print(f'  [{idx+1}/{total}] x={xf:.2f} y={ye:.1f}{sd_str} → '
                  f'{"ERR:"+err if err else f"total={tv} score={s}"} '
                  f'({dt:.0f}s)')
            results.append(r)
    else:
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(run_single_point, t): t for t in tasks}
            done = 0
            for future in as_completed(futures):
                r = future.result()
                idx, xf, ye, sd, drc, dt = r
                s = score(drc)
                err = drc.get('error', '')
                tv = sum(v for v in drc.values() if isinstance(v, int))
                done += 1
                sd_str = f' s={sd}' if sd is not None else ''
                print(f'  [{done}/{total}] x={xf:.2f} y={ye:.1f}{sd_str} → '
                      f'{"ERR:"+err if err else f"total={tv} score={s}"} '
                      f'({dt:.0f}s)')
                results.append(r)

    t_total = time.time() - t_start

    scored = [(score(drc), idx, xf, ye, sd, drc, dt)
              for idx, xf, ye, sd, drc, dt in results]
    scored.sort()

    print(f'\n{"="*70}')
    print(f' RESULTS ({total} points, {t_total:.0f}s total)')
    print(f'{"="*70}')
    print(f'\n  {"X":>5s} {"Y":>5s} {"Seed":>4s} {"Score":>6s} {"Total":>6s} '
          f'{"M1.b":>5s} {"M1.e":>5s} {"M3.b":>5s} {"M5.b":>5s} '
          f'{"pSD":>5s} {"NW.c":>5s}')

    for s, idx, xf, ye, sd, drc, dt in scored[:20]:
        if 'error' in drc:
            print(f'  {xf:5.2f} {ye:5.1f} {str(sd):>4s} {s:6d}  '
                  f'ERROR: {drc["error"]}')
        else:
            tv = sum(v for v in drc.values() if isinstance(v, int))
            print(f'  {xf:5.2f} {ye:5.1f} {str(sd):>4s} {s:6d} {tv:6d} '
                  f'{drc.get("M1.b","?"):>5} {drc.get("M1.e","?"):>5} '
                  f'{drc.get("M3.b","?"):>5} {drc.get("M5.b","?"):>5} '
                  f'{drc.get("pSD.c","?"):>5} {drc.get("NW.c","?"):>5}')

    save = [{'x_factor': xf, 'y_extra': ye, 'seed': sd,
             'score': s, 'drc': drc}
            for s, idx, xf, ye, sd, drc, dt in scored]
    with open(os.path.join(sweep_dir, 'results.json'), 'w') as f:
        json.dump(save, f, indent=2)

    best_s, _, best_xf, best_ye, best_sd, best_drc, _ = scored[0]
    print(f'\n  Best: x={best_xf:.2f} y={best_ye:.1f} seed={best_sd} '
          f'score={best_s}')
    print(f'  Saved: /tmp/placement_sweep/results.json')

    if best_s < 99999:
        best_p = generate_placement(original, best_xf, best_ye)
        with open(os.path.join(LAYOUT_DIR, 'placement.json'), 'w') as f:
            json.dump(best_p, f, indent=2)
        print(f'  Applied best placement to placement.json')


if __name__ == '__main__':
    main()
