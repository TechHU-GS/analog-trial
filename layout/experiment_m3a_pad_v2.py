#!/usr/bin/env python3
"""M3.a experiment v2: try multiple Via2 M3 pad sizes.

Tests: 380nm (baseline) vs 300nm vs 200nm (already failed).
300nm pad: (300-190)/2 = 55nm > 50nm → M3.c1 satisfied on all sides.
           Width mismatch with 200nm stubs: (300-200)/2 = 50nm thin wing → still M3.a?
           Width match with 300nm wires: 0 mismatch → clean.

Also: directional pad experiment — match connecting shape width.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_pad_v2.py
"""
import os, sys, re, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'

def count_drc_viols(lyrdb_path):
    """Parse lyrdb and return {rule: count}."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(lyrdb_path)
    root = tree.getroot()
    items = root.find('items')
    counts = {}
    for item in items.findall('item'):
        cat = item.find('category').text.strip("'")
        counts[cat] = counts.get(cat, 0) + 1
    return counts

def patch_gds(gds_in, gds_out, new_pad_size):
    """Shrink all Via2 M3 pads (370-390nm square) to new_pad_size."""
    layout = kdb.Layout()
    layout.read(gds_in)
    li_m3 = layout.layer(30, 0)
    count = 0
    hp = new_pad_size // 2

    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        to_remove = []
        to_add = []
        for si in cell.shapes(li_m3).each():
            bb = si.bbox()
            w, h = bb.width(), bb.height()
            if 370 <= w <= 390 and 370 <= h <= 390:
                cx = (bb.left + bb.right) // 2
                cy = (bb.bottom + bb.top) // 2
                to_remove.append(si.dup())
                to_add.append(kdb.Box(cx - hp, cy - hp, cx + hp, cy + hp))
        for si in to_remove:
            cell.shapes(li_m3).erase(si)
        for box in to_add:
            cell.shapes(li_m3).insert(box)
        count += len(to_add)

    layout.write(gds_out)
    return count

def patch_gds_directional(gds_in, gds_out):
    """Shrink Via2 M3 pads to match connecting M3 shape width.

    For each 380nm pad, find adjacent M3 shapes and match width to the
    narrowest neighbor in each direction. If no neighbor, keep 380nm.
    """
    layout = kdb.Layout()
    layout.read(gds_in)
    top = layout.top_cell()
    li_m3 = layout.layer(30, 0)

    # Collect all M3 shapes first
    all_m3 = []
    for si in top.begin_shapes_rec(li_m3):
        bb = si.shape().bbox().transformed(si.trans())
        all_m3.append(bb)

    # Find pads and their neighbors
    pads = []
    for si in top.begin_shapes_rec(li_m3):
        bb = si.shape().bbox().transformed(si.trans())
        w, h = bb.width(), bb.height()
        if 370 <= w <= 390 and 370 <= h <= 390:
            pads.append(bb)

    # For each pad, find touching/overlapping M3 shapes
    pad_info = {}
    for pad in pads:
        key = (pad.left, pad.bottom, pad.right, pad.top)
        if key in pad_info:
            continue
        # Expanded probe to find neighbors
        probe = kdb.Box(pad.left - 10, pad.bottom - 10,
                        pad.right + 10, pad.top + 10)
        neighbors = []
        for bb in all_m3:
            if bb.width() == pad.width() and bb.height() == pad.height():
                if abs(bb.left - pad.left) < 5 and abs(bb.bottom - pad.bottom) < 5:
                    continue  # same pad
            if probe.overlaps(bb):
                neighbors.append(bb)

        # Determine connecting shape widths
        # For horizontal neighbors: look at their height (width perpendicular to connection)
        # For vertical neighbors: look at their width
        neighbor_widths = set()
        for nb in neighbors:
            w, h = nb.width(), nb.height()
            # Determine connection direction
            if nb.top <= pad.top + 10 and nb.bottom >= pad.bottom - 10:
                # Horizontally adjacent — match height
                neighbor_widths.add(min(w, h))
            elif nb.left <= pad.right + 10 and nb.right >= pad.left - 10:
                # Vertically adjacent — match width
                neighbor_widths.add(min(w, h))
            else:
                neighbor_widths.add(min(w, h))

        if neighbor_widths:
            # Match the narrowest connecting shape
            target_w = min(neighbor_widths)
            # But cap at VIA2_SZ + 2*50 = 290nm minimum for M3.c1
            target_w = max(target_w, 290)
        else:
            target_w = 380  # standalone — keep original

        pad_info[key] = (pad, target_w, len(neighbors), neighbor_widths)

    print(f"\nDirectional pad analysis:")
    width_dist = {}
    for key, (pad, tw, nn, nw) in pad_info.items():
        width_dist[tw] = width_dist.get(tw, 0) + 1
    for tw, cnt in sorted(width_dist.items()):
        print(f"  target_width={tw}nm: {cnt} pads")

    # Now patch
    count = 0
    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        to_remove = []
        to_add = []
        for si in cell.shapes(li_m3).each():
            bb = si.bbox()
            w, h = bb.width(), bb.height()
            if 370 <= w <= 390 and 370 <= h <= 390:
                key = (bb.left, bb.bottom, bb.right, bb.top)
                # Find in pad_info by matching center
                cx = (bb.left + bb.right) // 2
                cy = (bb.bottom + bb.top) // 2
                # Look up by finding closest pad_info entry
                best_key = None
                best_dist = 9999999
                for pk, (pad, tw, nn, nw) in pad_info.items():
                    pcx = (pk[0] + pk[2]) // 2
                    pcy = (pk[1] + pk[3]) // 2
                    dist = abs(pcx - cx) + abs(pcy - cy)
                    if dist < best_dist:
                        best_dist = dist
                        best_key = pk
                if best_key and best_dist < 500:
                    target_w = pad_info[best_key][1]
                else:
                    target_w = 380

                hp = target_w // 2
                to_remove.append(si.dup())
                to_add.append(kdb.Box(cx - hp, cy - hp, cx + hp, cy + hp))
        for si in to_remove:
            cell.shapes(li_m3).erase(si)
        for box in to_add:
            cell.shapes(li_m3).insert(box)
        count += len(to_add)

    layout.write(gds_out)
    return count


# --- Run experiments ---
import subprocess

def run_drc(gds_path, run_dir):
    """Run DRC and return violation counts."""
    cmd = [
        'python3',
        os.path.expanduser('~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py'),
        f'--path={gds_path}',
        '--topcell=ptat_vco',
        f'--run_dir={run_dir}',
        '--mp=1', '--no_density'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    # Find lyrdb file
    import glob
    lyrdbs = glob.glob(os.path.join(run_dir, '*_full.lyrdb'))
    if lyrdbs:
        return count_drc_viols(lyrdbs[0])
    return {}

baseline = {'M1.b':32, 'M3.a':26, 'M2.b':12, 'NW.b1':6, 'Cnt.d':4, 'M3.b':4,
            'CntB.b2':3, 'M2.c1':3, 'M1.d':2, 'Rhi.d':2, 'V2.c1':1, 'Rppd.c':1}

# Experiment 1: 300nm pad
print("="*70)
print("EXPERIMENT 1: VIA2 M3 pad = 300nm (symmetric)")
print("="*70)
n = patch_gds(GDS_IN, '/tmp/exp_m3a_300.gds', 300)
print(f"Patched {n} pads to 300nm")
exp1 = run_drc('/tmp/exp_m3a_300.gds', '/tmp/drc_m3a_300')

# Experiment 2: directional matching
print("\n" + "="*70)
print("EXPERIMENT 2: Directional pad (match neighbor, min 290nm)")
print("="*70)
n = patch_gds_directional(GDS_IN, '/tmp/exp_m3a_dir.gds')
print(f"Patched {n} pads (directional)")
exp2 = run_drc('/tmp/exp_m3a_dir.gds', '/tmp/drc_m3a_dir')

# --- Compare ---
print("\n" + "="*70)
print("COMPARISON")
print("="*70)
print(f"  {'Rule':15s} {'Baseline':>10s} {'300nm':>10s} {'Direct':>10s}")
print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*10}")
all_rules = sorted(set(list(baseline.keys()) + list(exp1.keys()) + list(exp2.keys())))
total_b, total_1, total_2 = 0, 0, 0
for rule in all_rules:
    b = baseline.get(rule, 0)
    e1 = exp1.get(rule, 0)
    e2 = exp2.get(rule, 0)
    total_b += b
    total_1 += e1
    total_2 += e2
    m1 = '***' if e1 != b else ''
    m2 = '***' if e2 != b else ''
    print(f"  {rule:15s} {b:10d} {e1:10d} {m1:3s} {e2:10d} {m2:3s}")
print(f"  {'TOTAL':15s} {total_b:10d} {total_1:10d}     {total_2:10d}")
