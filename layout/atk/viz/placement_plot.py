"""Placement result visualization — device rectangles + row groupings + routing channels."""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np


# ─── Device type color palette ───
TYPE_COLORS = {
    'pmos':  '#4477AA',
    'nmos':  '#44AA77',
    'hbt':   '#CC6677',
    'res':   '#DDAA33',
    'buf_p': '#7766BB',
    'buf_n': '#66AA66',
}

ROW_COLORS = [
    '#E8F0FE', '#FEF0E8', '#E8FEF0', '#FEE8F0',
    '#F0E8FE', '#F0FEE8', '#E8FEFE', '#FEE8E8',
]


def plot_placement(devices, result, rows=None, row_spacings=None,
                   title="CP-SAT Placement", output_path=None):
    """Plot device placement with row annotations and routing channels.

    Args:
        devices: dict name -> {"w": float, "h": float, "type": str}
        result: dict name -> (x_um, y_um) from ConstraintPlacer.solve()
        rows: dict row_name -> [device_names] (optional, for row shading)
        row_spacings: list of (row_above, row_below, gap_um) (optional)
        title: plot title
        output_path: save PNG to this path (or None for show)

    Returns:
        (fig, ax)
    """
    fig, ax = plt.subplots(1, 1, figsize=(16, 10))
    ax.set_aspect('equal')
    ax.set_xlabel('X (µm)', fontsize=10)
    ax.set_ylabel('Y (µm)', fontsize=10)
    ax.set_title(title, fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.15, linewidth=0.5)

    # ── Row shading ──
    if rows:
        for i, (row_name, dev_names) in enumerate(rows.items()):
            valid = [n for n in dev_names if n in result]
            if not valid:
                continue
            xs = [result[n][0] for n in valid]
            ys = [result[n][1] for n in valid]
            ws = [devices[n]['w'] for n in valid]
            hs = [devices[n]['h'] for n in valid]

            rx1 = min(xs) - 0.3
            ry1 = min(ys) - 0.3
            rx2 = max(x + w for x, w in zip(xs, ws)) + 0.3
            ry2 = max(y + h for y, h in zip(ys, hs)) + 0.3

            color = ROW_COLORS[i % len(ROW_COLORS)]
            rect = patches.FancyBboxPatch(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                boxstyle="round,pad=0.2",
                linewidth=1.0, edgecolor='#999999',
                facecolor=color, alpha=0.35, linestyle='--')
            ax.add_patch(rect)
            ax.text(rx2 + 0.5, (ry1 + ry2) / 2, row_name,
                    fontsize=7, color='#666666', va='center',
                    fontstyle='italic')

    # ── Routing channel annotations ──
    if row_spacings:
        for above, below, gap_um in row_spacings:
            if above not in rows or below not in rows:
                continue
            above_devs = [n for n in rows[above] if n in result]
            below_devs = [n for n in rows[below] if n in result]
            if not above_devs or not below_devs:
                continue

            above_bottom = min(result[n][1] for n in above_devs)
            below_top = max(result[n][1] + devices[n]['h'] for n in below_devs)

            channel_y = (above_bottom + below_top) / 2
            channel_h = above_bottom - below_top

            all_x = ([result[n][0] for n in above_devs + below_devs])
            all_xr = ([result[n][0] + devices[n]['w'] for n in above_devs + below_devs])
            cx1, cx2 = min(all_x) - 0.5, max(all_xr) + 0.5

            ax.add_patch(patches.Rectangle(
                (cx1, below_top), cx2 - cx1, channel_h,
                facecolor='#E0FFE0', alpha=0.25, linewidth=0))
            ax.annotate(
                f'{channel_h:.1f}µm ch',
                xy=((cx1 + cx2) / 2, channel_y), fontsize=6,
                ha='center', va='center', color='#228B22',
                bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='#228B22',
                          alpha=0.7, lw=0.5))

    # ── Device rectangles ──
    for name, (x, y) in result.items():
        dev = devices[name]
        w, h = dev['w'], dev['h']
        dtype = dev.get('type', 'unknown')
        color = TYPE_COLORS.get(dtype, '#888888')

        rect = patches.Rectangle(
            (x, y), w, h,
            linewidth=1.2, edgecolor=color, facecolor=color, alpha=0.25)
        ax.add_patch(rect)

        # Bold border
        ax.add_patch(patches.Rectangle(
            (x, y), w, h,
            linewidth=1.2, edgecolor=color, facecolor='none'))

        # Label — scale font size by device area
        area = w * h
        if area > 50:
            fs = 7
        elif area > 10:
            fs = 6
        else:
            fs = 5

        ax.text(x + w / 2, y + h / 2, name,
                fontsize=fs, ha='center', va='center',
                color=color, fontweight='bold')

        # Dimension text for larger devices
        if w > 3 or h > 3:
            ax.text(x + w / 2, y - 0.3,
                    f'{w:.1f}×{h:.1f}',
                    fontsize=4, ha='center', va='top', color='#999999')

    # ── Bounding box ──
    all_x = [result[n][0] for n in result]
    all_y = [result[n][1] for n in result]
    all_xr = [result[n][0] + devices[n]['w'] for n in result]
    all_yr = [result[n][1] + devices[n]['h'] for n in result]

    bb_x1, bb_y1 = min(all_x), min(all_y)
    bb_x2, bb_y2 = max(all_xr), max(all_yr)
    bb_w, bb_h = bb_x2 - bb_x1, bb_y2 - bb_y1

    ax.add_patch(patches.Rectangle(
        (bb_x1, bb_y1), bb_w, bb_h,
        linewidth=2.0, edgecolor='red', facecolor='none', linestyle='--'))

    # ── Statistics ──
    dev_area = sum(devices[n]['w'] * devices[n]['h'] for n in result)
    bb_area = bb_w * bb_h
    util = dev_area / bb_area * 100 if bb_area > 0 else 0

    stats = (f'BBox: {bb_w:.1f} × {bb_h:.1f} µm = {bb_area:.0f} µm²\n'
             f'Device area: {dev_area:.0f} µm²\n'
             f'Utilization: {util:.0f}%\n'
             f'Devices: {len(result)}')

    ax.text(0.02, 0.98, stats, transform=ax.transAxes,
            fontsize=8, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))

    # ── Legend ──
    handles = []
    for dtype, color in TYPE_COLORS.items():
        h = patches.Patch(facecolor=color, alpha=0.3, edgecolor=color, label=dtype)
        handles.append(h)
    ax.legend(handles=handles, loc='upper right', fontsize=7, framealpha=0.7)

    # ── Axis limits ──
    pad = 3.0
    ax.set_xlim(bb_x1 - pad, bb_x2 + pad + 10)
    ax.set_ylim(bb_y1 - pad, bb_y2 + pad)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=200, bbox_inches='tight')
        print(f'Saved: {output_path}')

    return fig, ax
