#!/usr/bin/env python3
"""GA signal router — evolve route selection on M3+M4 using 192 cores.

Genome: dict net_name → candidate_index (int)
Fitness: Netgen LVS matched device count (higher = better)

Run on ECS:
    cd /root/analog-trial/layout && python3 -m atk.ga_signal_router
"""

import json
import os
import random
import subprocess
import sys
import time
from multiprocessing import Pool, cpu_count

from atk.signal_router import (
    compute_pin_positions, generate_candidates, build_soilz_mag,
    MAG_LAYERS, nm, VIA_HW, VIA_PAD_HW, M3_HW, M4_HW
)

# --- Server paths (ECS) ---
MAGIC_CMD = (
    'CAD_ROOT=/usr/local/lib /usr/local/bin/magic '
    '-noconsole -dnull '
    '-T /root/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2'
)
NETGEN_CMD = '/usr/local/lib/netgen/tcl/netgenexec'
NETGEN_SETUP = '/root/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/netgen/ihp-sg13g2_setup.tcl'
LVS_REF = '/root/analog-trial/layout/soilz_lvs.spice'
PCELL_DIR = '/tmp/magic_soilz'  # clean PCells stored here

# --- Detect local vs server ---
if os.path.exists(os.path.expanduser('~/.local/bin/magic')):
    MAGIC_CMD = (
        'CAD_ROOT=$HOME/.local/lib $HOME/.local/bin/magic '
        '-noconsole -dnull '
        '-T ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2'
    )
    NETGEN_CMD = os.path.expanduser('~/.local/lib/netgen/tcl/netgenexec')
    NETGEN_SETUP = os.path.expanduser(
        '~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/netgen/ihp-sg13g2_setup.tcl')
    LVS_REF = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'soilz_lvs.spice')
    PCELL_DIR = '/tmp/pcell_drc_test'


def convert_spice(spice_path, output_path):
    """Convert Magic ext2spice X-format to M/R/C for Netgen."""
    with open(spice_path) as f:
        lines = f.readlines()
    out = []
    for line in lines:
        if line.startswith('X'):
            parts = line.split()
            if 'sg13_lv_nmos' in parts or 'sg13_lv_pmos' in parts:
                model = 'sg13_lv_nmos' if 'sg13_lv_nmos' in parts else 'sg13_lv_pmos'
                s, g, d, b = parts[1], parts[2], parts[3], parts[4]
                w = l = ''
                for p in parts:
                    if p.startswith('w='): w = p.split('=')[1]
                    elif p.startswith('l='): l = p.split('=')[1]
                if w.startswith('70n') and l.startswith('70n'):
                    continue
                out.append(f'M{parts[0][1:]} {d} {g} {s} {b} {model} W={w} L={l}\n')
            elif 'rhigh' in parts:
                w = l = ''
                for p in parts:
                    if p.startswith('w='): w = p.split('=')[1]
                    elif p.startswith('l='): l = p.split('=')[1]
                out.append(f'R{parts[0][1:]} {parts[1]} {parts[2]} rhigh W={w} L={l}\n')
            elif 'cap_cmim' in parts:
                w = l = ''
                for p in parts:
                    if p.startswith('w='): w = p.split('=')[1]
                    elif p.startswith('l='): l = p.split('=')[1]
                out.append(f'C{parts[0][1:]} {parts[1]} {parts[2]} cap_cmim W={w} L={l}\n')
            else:
                out.append(line)
        else:
            out.append(line)
    with open(output_path, 'w') as f:
        f.writelines(out)


def evaluate(args):
    """Evaluate one genome. Returns (idx, device_count)."""
    idx, genome_list, net_names = args
    genome = dict(zip(net_names, genome_list))
    W = f'/tmp/ga_{idx}'
    try:
        os.makedirs(W, exist_ok=True)

        # Build soilz.mag
        build_soilz_mag(
            genome, _netlist, _placement, _dlm,
            _access_points, _power_drops, _candidates, W)

        # Copy PCells
        os.system(f'cp {PCELL_DIR}/dev_*.mag {W}/')

        # Magic extract: start background, poll for SPICE, kill when done
        proc = subprocess.Popen(
            f'cd {W} && {MAGIC_CMD} < phase_c.tcl > /dev/null 2>&1',
            shell=True)
        spice_path = f'{W}/soilz_flat.spice'
        for _ in range(600):  # max 600s
            time.sleep(1)
            if os.path.exists(spice_path) and os.path.getsize(spice_path) > 100:
                time.sleep(1)  # let ext2spice finish flushing
                break
        proc.kill()
        proc.wait()
        if not os.path.exists(spice_path):
            os.system(f'rm -rf {W}')
            return idx, 0

        # Convert SPICE
        clean_path = f'{W}/soilz_clean.spice'
        convert_spice(spice_path, clean_path)

        # Netgen LVS
        ng_tcl = (
            f'source /usr/local/lib/netgen/tcl/netgen.tcl\n'
            if not os.path.exists(os.path.expanduser('~/.local/lib/netgen'))
            else f'source {os.path.expanduser("~/.local/lib/netgen/tcl/netgen.tcl")}\n'
        )
        ng_tcl += (
            f'set s {NETGEN_SETUP}\n'
            f'lvs {{{clean_path} soilz_flat}} {{{LVS_REF} soilz}} $s {W}/comp.out\n'
            f'quit\n'
        )
        with open(f'{W}/ng.tcl', 'w') as f:
            f.write(ng_tcl)

        subprocess.run(
            f'{NETGEN_CMD} < {W}/ng.tcl',
            shell=True, capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(LVS_REF))

        # Parse result
        devs = 0
        if os.path.exists(f'{W}/comp.out'):
            with open(f'{W}/comp.out') as cf:
                for line in cf:
                    if 'device' in line.lower() and 'mismatch' not in line.lower():
                        # Look for matched device count
                        pass
                    if 'Circuits match' in line:
                        devs = 255
                        break
                    if 'Number of devices' in line and 'Mismatch' in line:
                        try:
                            devs = int(line.split(':')[1].strip().split()[0])
                        except:
                            pass

            # Alternative: count non-merged devices
            if devs == 0:
                with open(f'{W}/comp.out') as cf:
                    content = cf.read()
                    # Count matched device classes
                    for line in content.split('\n'):
                        if 'Matched' in line and 'device' in line.lower():
                            try:
                                n = int(line.split(':')[1].strip().split()[0])
                                devs = max(devs, n)
                            except:
                                pass
                    # Fallback: count from circuit info
                    if devs == 0:
                        for line in content.split('\n'):
                            if 'contains' in line and 'device' in line and 'soilz_flat' in line:
                                try:
                                    n = int(line.split('contains')[1].strip().split()[0])
                                    devs = n
                                except:
                                    pass

        os.system(f'rm -rf {W}')
        return idx, devs
    except Exception as e:
        os.system(f'rm -rf {W}')
        return idx, 0


# --- Globals for multiprocessing (set in main) ---
_netlist = None
_placement = None
_dlm = None
_access_points = None
_power_drops = None
_candidates = None


def main():
    global _netlist, _placement, _dlm, _access_points, _power_drops, _candidates

    layout_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(layout_dir)

    # Load data
    with open('netlist.json') as f: _netlist = json.load(f)
    with open('placement.json') as f: _placement = json.load(f)
    with open('atk/data/device_lib_magic.json') as f: _dlm = json.load(f)
    with open('output/routing.json') as f: routing = json.load(f)

    _access_points = routing['access_points']
    _power_drops = routing['power']['drops']

    # Compute pins + candidates
    net_pins = compute_pin_positions(_netlist, _access_points)
    _candidates = generate_candidates(net_pins)

    net_names = sorted(_candidates.keys())
    n_nets = len(net_names)
    n_cands = [len(_candidates[n]) for n in net_names]

    print(f'Nets: {n_nets}, candidates per net: {min(n_cands)}-{max(n_cands)}')
    print(f'Search space: {" × ".join(str(c) for c in n_cands[:10])}...')

    # GA parameters
    NCORES = cpu_count()
    POP_SIZE = NCORES
    GENERATIONS = 100
    MUTATE_RATE = 0.10

    print(f'GA: pop={POP_SIZE}, gen={GENERATIONS}, cores={NCORES}')

    # Initial population: random candidate selection per net
    population = []
    for _ in range(POP_SIZE):
        genome = [random.randint(0, n_cands[i] - 1) for i in range(n_nets)]
        population.append(genome)

    # Also add all-zeros (candidate 0 for every net)
    population[0] = [0] * n_nets

    best_ever = 0
    best_genome = None

    for gen in range(GENERATIONS):
        t0 = time.time()

        # Evaluate
        work = [(i, pop, net_names) for i, pop in enumerate(population)]
        with Pool(NCORES) as pool:
            results = pool.map(evaluate, work)

        scores = [0] * POP_SIZE
        for idx, devs in results:
            scores[idx] = devs

        # Sort
        scored = sorted(zip(scores, population), key=lambda x: -x[0])
        gen_best = scored[0][0]
        gen_median = scored[POP_SIZE // 2][0]

        if gen_best > best_ever:
            best_ever = gen_best
            best_genome = list(scored[0][1])
            # Save best
            with open('/tmp/ga_signal_best.json', 'w') as f:
                json.dump({
                    'score': best_ever,
                    'genome': dict(zip(net_names, best_genome)),
                    'generation': gen + 1
                }, f, indent=2)

        elapsed = time.time() - t0
        print(f'Gen {gen+1}/{GENERATIONS}: best={gen_best} median={gen_median} '
              f'alltime={best_ever} ({elapsed:.1f}s)', flush=True)

        if gen_best >= 255:
            print('PERFECT MATCH!', flush=True)
            break

        # Selection: top 50%
        survivors = [g for _, g in scored[:POP_SIZE // 2]]

        # Breed
        children = []
        while len(children) < POP_SIZE // 2:
            p1, p2 = random.sample(survivors, 2)
            child = []
            for i in range(n_nets):
                # Crossover: pick from either parent
                child.append(p1[i] if random.random() < 0.5 else p2[i])
            # Mutation: randomly change some nets' candidate selection
            for i in range(n_nets):
                if random.random() < MUTATE_RATE:
                    child[i] = random.randint(0, n_cands[i] - 1)
            children.append(child)

        population = survivors + children

    print(f'\n=== GA COMPLETE ===')
    print(f'Best: {best_ever}/255')
    if best_genome:
        genome_dict = dict(zip(net_names, best_genome))
        print(f'Saved to /tmp/ga_signal_best.json')

        # Build final soilz.mag
        build_soilz_mag(
            genome_dict, _netlist, _placement, _dlm,
            _access_points, _power_drops, _candidates, '/tmp/ga_final')
        os.system(f'cp {PCELL_DIR}/dev_*.mag /tmp/ga_final/')
        print(f'Final layout in /tmp/ga_final/soilz.mag')


if __name__ == '__main__':
    main()
