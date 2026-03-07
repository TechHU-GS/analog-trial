#!/usr/bin/env python3
"""Phase 4 routing visualization — device bbox + tie M1 + access points + routing segments.

Usage:
    source ~/pdk/venv/bin/activate
    python plot_routing.py
"""

import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atk.pdk import UM, M1_SIG_W, M2_SIG_W, M3_PWR_W, VIA1_SZ
from atk.route.maze_router import M1_LYR, M2_LYR


# ─── Colors ───
M1_COLOR = '#3366CC'     # blue
M2_COLOR = '#33AA55'     # green
VIA_COLOR = '#CC3333'    # red
M3_COLOR = '#888888'     # gray
TIE_COLOR = '#DD8833'    # orange
BBOX_COLOR = '#CCCCCC'   # light gray
AP_DOT_COLOR = '#AA33AA' # purple
DROP_COLOR = '#9933CC'   # purple


def load_json(path):
    with open(path) as f:
        return json.load(f)


def plot_routing(routing, placement, ties=None, output_path=None):
    fig, ax = plt.subplots(1, 1, figsize=(18, 12))
    ax.set_aspect('equal')
    ax.set_xlabel('X (µm)', fontsize=10)
    ax.set_ylabel('Y (µm)', fontsize=10)
    ax.set_title('Phase 4: Power + Signal Routing', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.1, linewidth=0.3)

    # ── Device bboxes ──
    for inst_name, inst in placement['instances'].items():
        x, y, w, h = inst['x_um'], inst['y_um'], inst['w_um'], inst['h_um']
        rect = patches.Rectangle((x, y), w, h,
                                  linewidth=0.5, edgecolor=BBOX_COLOR,
                                  facecolor='#F5F5F5', alpha=0.4, zorder=1)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h/2, inst_name,
                ha='center', va='center', fontsize=4, color='#666666', zorder=2)

    # ── Tie M1 shapes ──
    if ties:
        for tie in ties.get('ties', []):
            for rect in tie.get('layers', {}).get('M1_8_0', []):
                x1, y1, x2, y2 = [v / UM for v in rect]
                r = patches.Rectangle((x1, y1), x2-x1, y2-y1,
                                       linewidth=0.3, edgecolor=TIE_COLOR,
                                       facecolor=TIE_COLOR, alpha=0.3, zorder=2)
                ax.add_patch(r)

    # ── M3 power rails ──
    rails = routing.get('power', {}).get('rails', {})
    for net_name, rail in rails.items():
        y = rail['y'] / UM
        x1 = rail['x1'] / UM
        x2 = rail['x2'] / UM
        hw = rail['width'] / UM / 2
        r = patches.Rectangle((x1, y - hw), x2 - x1, hw * 2,
                                linewidth=0.5, edgecolor=M3_COLOR,
                                facecolor=M3_COLOR, alpha=0.2, zorder=3)
        ax.add_patch(r)
        ax.text((x1 + x2) / 2, y, net_name.upper(),
                ha='center', va='center', fontsize=6, color='#555555',
                fontweight='bold', zorder=4)

    # ── Power drops (via2 positions) ──
    drops = routing.get('power', {}).get('drops', [])
    for drop in drops:
        v2 = drop.get('via2_pos')
        if v2:
            ax.plot(v2[0] / UM, v2[1] / UM, 's',
                    color=DROP_COLOR, markersize=2, zorder=5, alpha=0.6)

    # ── Access points ──
    for key, ap in routing.get('access_points', {}).items():
        ax.plot(ap['x'] / UM, ap['y'] / UM, '.',
                color=AP_DOT_COLOR, markersize=1.5, zorder=6, alpha=0.5)

    # ── Signal route segments ──
    all_routes = {}
    for net_name, route in routing.get('signal_routes', {}).items():
        all_routes[net_name] = route.get('segments', [])
    for net_name, route in routing.get('pre_routes', {}).items():
        all_routes.setdefault(net_name, []).extend(route.get('segments', []))

    for net_name, segments in all_routes.items():
        for seg in segments:
            x1, y1, x2, y2, layer = seg[0]/UM, seg[1]/UM, seg[2]/UM, seg[3]/UM, seg[4]
            if layer == M1_LYR:
                ax.plot([x1, x2], [y1, y2], '-', color=M1_COLOR,
                        linewidth=0.8, zorder=7, alpha=0.7)
            elif layer == M2_LYR:
                ax.plot([x1, x2], [y1, y2], '-', color=M2_COLOR,
                        linewidth=0.8, zorder=7, alpha=0.7)
            elif layer == -1:  # VIA
                ax.plot(x1, y1, 'o', color=VIA_COLOR,
                        markersize=1.5, zorder=8)

    # ── Legend ──
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color=M1_COLOR, lw=1.5, label='M1 signal'),
        Line2D([0], [0], color=M2_COLOR, lw=1.5, label='M2 signal'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=VIA_COLOR,
               markersize=5, label='Via1'),
        patches.Patch(facecolor=M3_COLOR, alpha=0.3, label='M3 power rail'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor=DROP_COLOR,
               markersize=5, label='Via2 drop'),
        patches.Patch(facecolor=TIE_COLOR, alpha=0.3, label='Tie M1'),
        patches.Patch(facecolor='#F5F5F5', edgecolor=BBOX_COLOR, label='Device bbox'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=7, framealpha=0.8)

    # ── Stats annotation ──
    stats = routing.get('statistics', {})
    info = (f"Signal nets: {stats.get('nets_routed', '?')}/17 routed\n"
            f"Pre-routed: {stats.get('nets_pre_routed', '?')}\n"
            f"Segments: {stats.get('total_segments', '?')}\n"
            f"Access pts: {stats.get('total_access_points', '?')}\n"
            f"Power drops: {stats.get('total_power_drops', '?')}")
    ax.text(0.01, 0.99, info, transform=ax.transAxes,
            fontsize=6, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=200, bbox_inches='tight')
        print(f'Saved: {output_path}')
    else:
        plt.show()

    return fig, ax


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base, 'output')

    routing = load_json(os.path.join(out_dir, 'routing.json'))
    placement = load_json(os.path.join(base, 'placement.json'))

    ties_path = os.path.join(out_dir, 'ties.json')
    ties = load_json(ties_path) if os.path.exists(ties_path) else None

    output_path = os.path.join(out_dir, 'routing_plot.png')
    plot_routing(routing, placement, ties, output_path)


if __name__ == '__main__':
    main()
