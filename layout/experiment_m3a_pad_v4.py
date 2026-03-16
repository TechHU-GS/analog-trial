#!/usr/bin/env python3
"""M3.a experiment v4: shrink pad to 200nm + extend stub past via for M3.c1.

Run:
    cd layout && source ~/pdk/venv/bin/activate && python3 experiment_m3a_pad_v4.py
"""
import os, subprocess, glob
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import klayout.db as kdb

GDS_IN  = 'output/ptat_vco.gds'
GDS_OUT = '/tmp/exp_m3a_v4.gds'

VIA2_HW = 190 // 2     # 95nm half-via
ENDCAP = 50             # M3.c1 endcap
NEW_PAD_HW = 200 // 2  # 100nm (M3_MIN_W / 2)


def make_extension(cx, cy, direction):
    """Create a 200nm-wide M3 extension, 50nm past via edge."""
    ve_n = cy + VIA2_HW
    ve_s = cy - VIA2_HW
    ve_e = cx + VIA2_HW
    ve_w = cx - VIA2_HW

    if direction == 'N':
        return kdb.Box(cx - NEW_PAD_HW, ve_n, cx + NEW_PAD_HW, ve_n + ENDCAP)
    elif direction == 'S':
        return kdb.Box(cx - NEW_PAD_HW, ve_s - ENDCAP, cx + NEW_PAD_HW, ve_s)
    elif direction == 'E':
        return kdb.Box(ve_e, cy - NEW_PAD_HW, ve_e + ENDCAP, cy + NEW_PAD_HW)
    elif direction == 'W':
        return kdb.Box(ve_w - ENDCAP, cy - NEW_PAD_HW, ve_w, cy + NEW_PAD_HW)


def find_stub_dirs(pad_bb, all_shapes, margin=10):
    """Find directions of M3 shapes connecting to this pad."""
    pcx = (pad_bb.left + pad_bb.right) // 2
    pcy = (pad_bb.bottom + pad_bb.top) // 2
    dirs = set()
    probe = kdb.Box(pad_bb.left - 200, pad_bb.bottom - 200,
                    pad_bb.right + 200, pad_bb.top + 200)

    for bb in all_shapes:
        if bb == pad_bb:
            continue
        w, h = bb.width(), bb.height()
        if 370 <= w <= 390 and 370 <= h <= 390:
            continue  # skip other pads
        if not probe.overlaps(bb):
            continue

        bcx = (bb.left + bb.right) // 2
        bcy = (bb.bottom + bb.top) // 2

        if bb.right >= pad_bb.left - margin and bb.left <= pad_bb.right + margin:
            if bb.top >= pad_bb.top - margin and bcy > pcy:
                dirs.add('N')
            if bb.bottom <= pad_bb.bottom + margin and bcy < pcy:
                dirs.add('S')
        if bb.top >= pad_bb.bottom - margin and bb.bottom <= pad_bb.top + margin:
            if bb.right >= pad_bb.right - margin and bcx > pcx:
                dirs.add('E')
            if bb.left <= pad_bb.left + margin and bcx < pcx:
                dirs.add('W')
    return dirs


# --- Load GDS ---
layout = kdb.Layout()
layout.read(GDS_IN)
top = layout.top_cell()
li_m3 = layout.layer(30, 0)
li_v2 = layout.layer(29, 0)

# Collect all M3 shapes
all_m3 = []
for si in top.begin_shapes_rec(li_m3):
    bb = si.shape().bbox().transformed(si.trans())
    all_m3.append(bb)

# Analyze unique pads
pads_by_center = {}
for si in top.begin_shapes_rec(li_m3):
    bb = si.shape().bbox().transformed(si.trans())
    w, h = bb.width(), bb.height()
    if 370 <= w <= 390 and 370 <= h <= 390:
        cx = (bb.left + bb.right) // 2
        cy = (bb.bottom + bb.top) // 2
        key = (cx, cy)
        if key not in pads_by_center:
            dirs = find_stub_dirs(bb, all_m3)
            pads_by_center[key] = dirs

print(f"Unique Via2 M3 pads: {len(pads_by_center)}")

# Direction distribution
dir_counts = {}
for key, dirs in pads_by_center.items():
    dkey = ''.join(sorted(dirs)) if dirs else 'standalone'
    dir_counts[dkey] = dir_counts.get(dkey, 0) + 1
print("\nStub direction distribution:")
for d, n in sorted(dir_counts.items(), key=lambda x: -x[1]):
    print(f"  {d:15s}: {n}")

# --- Patch GDS ---
patched = 0
extensions = 0

for cell_idx in range(layout.cells()):
    cell = layout.cell(cell_idx)
    to_remove = []
    to_add = []

    for si in cell.shapes(li_m3).each():
        bb = si.bbox()
        w, h = bb.width(), bb.height()
        if not (370 <= w <= 390 and 370 <= h <= 390):
            continue

        cx = (bb.left + bb.right) // 2
        cy = (bb.bottom + bb.top) // 2

        # Find stub directions for this pad
        best_dist = 999999
        dirs = set()
        for (pcx, pcy), pdirs in pads_by_center.items():
            d = abs(pcx - cx) + abs(pcy - cy)
            if d < best_dist:
                best_dist = d
                dirs = pdirs

        to_remove.append(si.dup())

        if not dirs:
            # Standalone — keep 380nm pad
            to_add.append(kdb.Box(cx - 190, cy - 190, cx + 190, cy + 190))
        else:
            # Draw 200nm pad
            to_add.append(kdb.Box(cx - NEW_PAD_HW, cy - NEW_PAD_HW,
                                  cx + NEW_PAD_HW, cy + NEW_PAD_HW))

            # Add extension in anti-stub direction
            missing = {'N', 'S', 'E', 'W'} - dirs

            if len(dirs) >= 2:
                # Multiple stubs, need 1 extension max
                # Pick the missing direction that forms a pair with a stub
                for md in sorted(missing):
                    opp = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E'}[md]
                    if opp in dirs:
                        to_add.append(make_extension(cx, cy, md))
                        extensions += 1
                        break
                else:
                    # No good opposite found — add any missing
                    if missing:
                        to_add.append(make_extension(cx, cy, sorted(missing)[0]))
                        extensions += 1
            else:
                # 1 stub — extend in opposite direction
                stub_dir = list(dirs)[0]
                opp = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E'}[stub_dir]
                to_add.append(make_extension(cx, cy, opp))
                extensions += 1

        patched += 1

    for si in to_remove:
        cell.shapes(li_m3).erase(si)
    for box in to_add:
        cell.shapes(li_m3).insert(box)

print(f"\nPatched {patched} pads, drew {extensions} extensions")

# Save
layout.write(GDS_OUT)
print(f"Saved: {GDS_OUT}")

# --- Run DRC ---
print("\nRunning DRC...")
cmd = [
    'python3',
    os.path.expanduser('~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py'),
    f'--path={GDS_OUT}',
    '--topcell=ptat_vco',
    '--run_dir=/tmp/drc_m3a_v4',
    '--mp=1', '--no_density'
]
subprocess.run(cmd, capture_output=True, text=True, timeout=300)

# Parse results
import xml.etree.ElementTree as ET
lyrdbs = glob.glob('/tmp/drc_m3a_v4/*_full.lyrdb')
if lyrdbs:
    tree = ET.parse(lyrdbs[0])
    root = tree.getroot()
    items = root.find('items')
    counts = {}
    for item in items.findall('item'):
        cat = item.find('category').text.strip("'")
        counts[cat] = counts.get(cat, 0) + 1

    baseline = {'M1.b':32, 'M3.a':26, 'M2.b':12, 'NW.b1':6, 'Cnt.d':4, 'M3.b':4,
                'CntB.b2':3, 'M2.c1':3, 'M1.d':2, 'Rhi.d':2, 'V2.c1':1, 'Rppd.c':1}

    print(f"\n{'='*70}")
    print("RESULTS: 200nm pad + anti-stub extension")
    print(f"{'='*70}")
    print(f"  {'Rule':15s} {'Baseline':>10s} {'v4':>10s} {'Delta':>8s}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*8}")
    all_rules = sorted(set(list(baseline.keys()) + list(counts.keys())))
    total_b, total_e = 0, 0
    for rule in all_rules:
        b = baseline.get(rule, 0)
        e = counts.get(rule, 0)
        total_b += b
        total_e += e
        delta = e - b
        m = '***' if delta != 0 else ''
        print(f"  {rule:15s} {b:10d} {e:10d} {delta:+8d} {m}")
    print(f"  {'TOTAL':15s} {total_b:10d} {total_e:10d} {total_e-total_b:+8d}")
else:
    print("ERROR: No lyrdb file found")
