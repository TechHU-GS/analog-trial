"""Layout visualization using matplotlib — per-net coloring, DRC overlay, debug views."""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.geometry import Polygon
from shapely.ops import unary_union


# ─── Color palette for nets ───
NET_COLORS = {
    'vdd': '#CC0000', 'vdd_vco': '#FF4444', 'gnd': '#333333',
    'net_c1': '#1f77b4', 'net_c2': '#ff7f0e', 'net_rptat': '#2ca02c',
    'nmos_bias': '#d62728', 'vptat': '#9467bd',
    'vco1': '#8c564b', 'vco2': '#e377c2', 'vco3': '#7f7f7f',
    'vco4': '#bcbd22', 'vco5': '#17becf',
    'buf1': '#aec7e8', 'vco_out': '#ff9896',
}

DEVICE_COLORS = {
    'pmos': '#4477AA', 'nmos': '#44AA77', 'rppd': '#DDAA33',
    'npn13G2': '#CC6677', 'hbt': '#CC6677',
}


def plot_m2_regions(ax, m2_polys, title="M2 Merged Regions"):
    """Plot merged M2 regions with distinct colors per region."""
    merged = unary_union(m2_polys)

    if merged.geom_type == 'Polygon':
        regions = [merged]
    elif merged.geom_type == 'MultiPolygon':
        regions = list(merged.geoms)
    else:
        regions = []

    cmap = plt.cm.tab20
    for i, r in enumerate(regions):
        if r.is_empty:
            continue
        color = cmap(i % 20)
        try:
            x, y = r.exterior.xy
            ax.fill(x, y, alpha=0.3, color=color, linewidth=0.5, edgecolor=color)
        except:
            pass

    ax.set_title(f"{title} ({len(regions)} regions)", fontweight='bold')
    return regions


def plot_devices(ax, devices, alpha=0.15):
    """Plot device bounding boxes.

    devices: dict name -> (type, x, y, w, h) in µm
    """
    for name, (dtype, x, y, w, h) in devices.items():
        color = DEVICE_COLORS.get(dtype.split('_')[0], '#888888')
        rect = patches.Rectangle((x, y), w, h, linewidth=0.8,
                                  edgecolor=color, facecolor=color, alpha=alpha)
        ax.add_patch(rect)
        if w > 2 or h > 5:
            ax.text(x + w/2, y + h/2, name, fontsize=5, ha='center', va='center',
                    color=color, fontweight='bold')


def plot_rails(ax, rails):
    """Plot power rail zones.

    rails: list of (name, x1, x2, y_center, width, color)
    """
    for name, x1, x2, yc, rw, color in rails:
        rect = patches.Rectangle((x1, yc - rw/2), x2 - x1, rw,
                                  linewidth=0, facecolor=color, alpha=0.08)
        ax.add_patch(rect)
        ax.axhline(y=yc, color=color, linewidth=0.3, linestyle='--', alpha=0.5)
        ax.text(x2 + 0.5, yc, name, fontsize=6, color=color, va='center')


def plot_drc_markers(ax, violations_by_rule, x=2, y_start=47):
    """Overlay DRC violation summary text."""
    y = y_start
    ax.text(x, y, 'DRC Violations:', fontsize=9, fontweight='bold', color='red')
    for rule, count in sorted(violations_by_rule.items()):
        y -= 1.2
        ax.text(x, y, f'  {rule}: {count}', fontsize=7, color='red')


def full_layout_figure(m2_polys, m1_polys=None, devices=None, rails=None,
                        drc_counts=None, output_path=None):
    """Generate a 2-panel layout debug figure.

    Left: M2 merged regions (short check visualization)
    Right: M1 + devices + DRC markers
    """
    fig, axes = plt.subplots(1, 2, figsize=(24, 10))

    for ax in axes:
        ax.set_aspect('equal')
        ax.set_xlabel('X (µm)')
        ax.set_ylabel('Y (µm)')
        ax.grid(True, alpha=0.2, linewidth=0.5)
        if devices:
            plot_devices(ax, devices)
        if rails:
            plot_rails(ax, rails)

    # Left: M2
    regions = plot_m2_regions(axes[0], m2_polys)

    # Right: M1 + DRC
    axes[1].set_title("M1 + Devices + DRC", fontweight='bold')
    if m1_polys:
        for sp in m1_polys:
            if sp.is_empty or not sp.is_valid:
                continue
            try:
                x, y = sp.exterior.xy
                axes[1].fill(x, y, alpha=0.15, color='blue', linewidth=0.3, edgecolor='blue')
            except:
                pass

    if drc_counts:
        plot_drc_markers(axes[1], drc_counts)

    for ax in axes:
        ax.set_xlim(-5, 105)
        ax.set_ylim(-3, 50)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=200, bbox_inches='tight')
        print(f"Saved: {output_path}")

    return fig, axes, regions
