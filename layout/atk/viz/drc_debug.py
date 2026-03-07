"""DRC violation debug visualizer — per-violation zoomed plots.

Reads GDS + lyrdb DRC report, generates one PNG per violation cluster
showing the local geometry context. Claude Code reads these PNGs to
identify root causes visually instead of guessing from coordinates.

Usage:
    python -m atk.viz.drc_debug <gds_file> <lyrdb_file> [cell_name] [--radius 5]
"""

import xml.etree.ElementTree as ET
import re
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly

from ..pdk import METAL1, METAL2, VIA1


# ─── Layer extraction ───

def _extract_polys(gds_path, cell_name, layer, datatype=0):
    """Extract all polygons from a GDS layer (flattened)."""
    import gdstk
    lib = gdstk.read_gds(gds_path)
    cell = None
    if cell_name:
        for c in lib.cells:
            if c.name == cell_name:
                cell = c
                break
    if cell is None:
        for c in lib.cells:
            if not c.name.startswith('$'):
                cell = c
                break
    if cell is None:
        raise ValueError(f'Cell not found in {gds_path}')

    flat = cell.copy(name='_flat_debug')
    flat.flatten()
    return flat.get_polygons(layer=layer, datatype=datatype)


# ─── Parse DRC lyrdb ───

def parse_lyrdb(lyrdb_path):
    """Parse KLayout DRC report (.lyrdb), return dict rule -> [(x, y, text)].

    Coordinates in µm (matching GDS units).
    """
    tree = ET.parse(lyrdb_path)
    root = tree.getroot()

    violations = {}
    for item in root.iter('item'):
        cat_elem = item.find('category')
        if cat_elem is None or cat_elem.text is None:
            continue
        cat = cat_elem.text.strip().strip("'")

        values = item.find('values')
        if values is None:
            continue
        text = values.text or ''

        # Extract edge-pair coordinates: (x1,y1;x2,y2)
        pairs = re.findall(r'\(([0-9.\-]+),([0-9.\-]+);([0-9.\-]+),([0-9.\-]+)\)', text)
        if pairs:
            x = (float(pairs[0][0]) + float(pairs[0][2])) / 2
            y = (float(pairs[0][1]) + float(pairs[0][3])) / 2
        else:
            # Try polygon format: (x,y; x,y; ...)
            pts = re.findall(r'([0-9.\-]+),([0-9.\-]+)', text)
            if pts:
                x = sum(float(p[0]) for p in pts) / len(pts)
                y = sum(float(p[1]) for p in pts) / len(pts)
            else:
                continue

        violations.setdefault(cat, []).append((x, y, text))

    return violations


# ─── Cluster nearby violations ───

def _cluster(points, merge_radius=2.0):
    """Group points within merge_radius of each other."""
    clusters = []
    used = [False] * len(points)

    for i, (x, y, _) in enumerate(points):
        if used[i]:
            continue
        group = [points[i]]
        used[i] = True
        for j in range(i + 1, len(points)):
            if used[j]:
                continue
            dx = points[j][0] - x
            dy = points[j][1] - y
            if (dx * dx + dy * dy) < merge_radius * merge_radius:
                group.append(points[j])
                used[j] = True
        clusters.append(group)

    return clusters


# ─── Plot ───

LAYER_COLORS = {
    'M1': ('#4444ff30', 'blue'),
    'M2': ('#44aa4430', 'green'),
    'V1': ('#ff000030', 'red'),
}


def plot_violations(gds_path, violations_by_rule, cell_name=None,
                    radius=5.0, output_dir='.', rules=None):
    """Generate per-cluster debug plots.

    Args:
        gds_path: path to GDS file
        violations_by_rule: dict from parse_lyrdb()
        cell_name: GDS cell name
        radius: view radius around violation center (µm)
        output_dir: where to save PNGs
        rules: list of rules to plot (None = all)

    Returns:
        list of saved PNG paths
    """
    import os

    # Determine which layers to load based on rules
    load_m1 = False
    load_m2 = False
    load_v1 = False

    target_rules = rules or list(violations_by_rule.keys())
    for rule in target_rules:
        r = rule.upper()
        if 'M1' in r:
            load_m1 = True
        if 'M2' in r:
            load_m2 = True
        if 'V1' in r:
            load_v1 = True
            load_m1 = True  # V1 context needs M1+M2
            load_m2 = True

    # Load needed layers
    polys = {}
    if load_m1:
        polys['M1'] = _extract_polys(gds_path, cell_name, *METAL1)
        print(f'  Loaded {len(polys["M1"])} M1 polygons')
    if load_m2:
        polys['M2'] = _extract_polys(gds_path, cell_name, *METAL2)
        print(f'  Loaded {len(polys["M2"])} M2 polygons')
    if load_v1:
        polys['V1'] = _extract_polys(gds_path, cell_name, *VIA1)
        print(f'  Loaded {len(polys["V1"])} V1 polygons')

    saved = []
    plot_idx = 0

    for rule in target_rules:
        if rule not in violations_by_rule:
            continue

        viols = violations_by_rule[rule]
        clusters = _cluster(viols, merge_radius=radius * 0.8)
        print(f'  {rule}: {len(viols)} violations in {len(clusters)} clusters')

        # Determine which layers to show for this rule
        r = rule.upper()
        show_layers = []
        if 'M1' in r:
            show_layers.append('M1')
        if 'M2' in r:
            show_layers.append('M2')
        if 'V1' in r:
            show_layers = ['M1', 'M2', 'V1']
        if not show_layers:
            show_layers = list(polys.keys())

        for cluster in clusters:
            cx = sum(p[0] for p in cluster) / len(cluster)
            cy = sum(p[1] for p in cluster) / len(cluster)

            fig, ax = plt.subplots(figsize=(12, 12))
            ax.set_title(f'{rule} cluster #{plot_idx} ({len(cluster)} viols) '
                        f'center=({cx:.2f}, {cy:.2f})', fontsize=12)

            # Draw shapes in view window
            for layer_name in show_layers:
                if layer_name not in polys:
                    continue
                fc, ec = LAYER_COLORS.get(layer_name, ('#88888830', 'gray'))

                for poly in polys[layer_name]:
                    bb = poly.bounding_box()
                    # Skip shapes entirely outside view
                    if (bb[1][0] < cx - radius or bb[0][0] > cx + radius or
                            bb[1][1] < cy - radius or bb[0][1] > cy + radius):
                        continue

                    pts = poly.points
                    p = MplPoly(pts, closed=True, fill=True,
                                facecolor=fc, edgecolor=ec, linewidth=0.8)
                    ax.add_patch(p)

                    # Annotate shape dimensions
                    w_nm = (bb[1][0] - bb[0][0]) * 1000
                    h_nm = (bb[1][1] - bb[0][1]) * 1000
                    scx = (bb[0][0] + bb[1][0]) / 2
                    scy = (bb[0][1] + bb[1][1]) / 2
                    ax.annotate(f'{layer_name}\n{w_nm:.0f}x{h_nm:.0f}',
                                (scx, scy), fontsize=5, ha='center', va='center',
                                color=ec, alpha=0.8)

            # Mark violation locations
            for vx, vy, _ in cluster:
                ax.plot(vx, vy, 'rx', markersize=15, markeredgewidth=2.5, zorder=10)
                ax.annotate(f'({vx:.3f},{vy:.3f})', (vx, vy),
                            fontsize=7, textcoords='offset points',
                            xytext=(8, 8), color='red', fontweight='bold')

            ax.set_xlim(cx - radius, cx + radius)
            ax.set_ylim(cy - radius, cy + radius)
            ax.set_aspect('equal')
            ax.grid(True, linewidth=0.5, alpha=0.3)
            ax.set_xlabel('X (um)')
            ax.set_ylabel('Y (um)')

            fname = os.path.join(output_dir, f'drc_{rule}_{plot_idx:03d}.png')
            plt.tight_layout()
            plt.savefig(fname, dpi=200, bbox_inches='tight')
            plt.close()
            saved.append(fname)
            plot_idx += 1

    return saved


# ─── CLI ───

def main():
    import argparse
    parser = argparse.ArgumentParser(description='DRC violation debug plots')
    parser.add_argument('gds', help='GDS file path')
    parser.add_argument('lyrdb', help='KLayout DRC report (.lyrdb)')
    parser.add_argument('--cell', default=None, help='Cell name')
    parser.add_argument('--radius', type=float, default=5.0, help='View radius (um)')
    parser.add_argument('--rules', nargs='*', help='Rules to plot (default: all)')
    parser.add_argument('--output', default='.', help='Output directory')
    args = parser.parse_args()

    import os
    os.makedirs(args.output, exist_ok=True)

    violations = parse_lyrdb(args.lyrdb)
    print(f'Parsed {sum(len(v) for v in violations.values())} violations:')
    for rule, viols in sorted(violations.items()):
        print(f'  {rule}: {len(viols)}')

    saved = plot_violations(args.gds, violations, cell_name=args.cell,
                           radius=args.radius, output_dir=args.output,
                           rules=args.rules)
    print(f'\nSaved {len(saved)} debug plots to {args.output}/')
    for f in saved:
        print(f'  {f}')


if __name__ == '__main__':
    main()
