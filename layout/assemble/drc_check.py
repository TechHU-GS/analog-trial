"""Inline DRC checking using KLayout Region API.

Runs spacing/width checks after each assembly phase.
Tracks incremental violations (new since last phase).
Enabled by DRC_INLINE=1 environment variable. Default off.

Usage:
    from assemble.drc_check import DRCTracker
    tracker = DRCTracker(top, layers)
    tracker.checkpoint('bus_straps')
    tracker.checkpoint('gate')
    tracker.report()
"""

import os
import klayout.db as db


ENABLED = bool(os.environ.get('DRC_INLINE'))


class DRCTracker:
    """Track DRC violations incrementally across assembly phases."""

    def __init__(self, top, layer_config):
        """
        Args:
            top: KLayout Cell
            layer_config: dict of layer_name -> (li, min_spacing, min_width)
        """
        self.top = top
        self.layer_config = layer_config
        self.history = []  # [(phase, {layer: {spacing: N, width: N}})]
        self.prev = {}     # previous checkpoint counts

    def checkpoint(self, phase):
        """Run DRC checks and report incremental changes."""
        if not ENABLED:
            return None

        current = {}
        for name, (li, min_s, min_w) in self.layer_config.items():
            region = db.Region(self.top.begin_shapes_rec(li))

            counts = {}
            space_viols = region.space_check(min_s)
            n_space = space_viols.count()
            if n_space > 0:
                counts['spacing'] = n_space
                # Extract hotspot bbox from violations
                viol_bbox = space_viols.bbox()
                counts['spacing_hotspot'] = (
                    f'({viol_bbox.left/1000:.0f},{viol_bbox.bottom/1000:.0f})-'
                    f'({viol_bbox.right/1000:.0f},{viol_bbox.top/1000:.0f})')

            if min_w:
                width_viols = region.width_check(min_w)
                n_width = width_viols.count()
                if n_width > 0:
                    counts['width'] = n_width

            if counts:
                current[name] = counts

        # Compute delta from previous checkpoint
        delta = {}
        for name, counts in current.items():
            prev_counts = self.prev.get(name, {})
            for check_type, n in counts.items():
                if '_hotspot' in check_type:
                    continue
                prev_n = prev_counts.get(check_type, 0)
                diff = n - prev_n
                if diff != 0:
                    delta.setdefault(name, {})[check_type] = (prev_n, n, diff)

        # Report
        if delta:
            parts = []
            for name, checks in sorted(delta.items()):
                for check_type, (prev_n, cur_n, diff) in checks.items():
                    sign = '+' if diff > 0 else ''
                    hotspot = current.get(name, {}).get(f'{check_type}_hotspot', '')
                    loc = f' {hotspot}' if hotspot and diff > 0 else ''
                    parts.append(f'{name}.{check_type}: {prev_n}→{cur_n} ({sign}{diff}){loc}')
            print(f'  ⚠️ DRC after {phase}: {", ".join(parts)}')
        else:
            if current:
                # No change from previous
                total = sum(v for c in current.values() for v in c.values())
                print(f'  ✓ DRC after {phase}: no new violations (total {total})')
            else:
                print(f'  ✓ DRC after {phase}: clean')

        self.history.append((phase, current, delta))
        self.prev = current
        return delta

    def report(self):
        """Print summary of all checkpoints."""
        if not ENABLED or not self.history:
            return

        print(f'\n  === DRC Incremental Summary ===')
        for phase, current, delta in self.history:
            if delta:
                parts = []
                for name, checks in sorted(delta.items()):
                    for ct, (prev, cur, diff) in checks.items():
                        if '_hotspot' in ct:
                            continue
                        sign = '+' if diff > 0 else ''
                        parts.append(f'{name}.{ct} {sign}{diff}')
                print(f'    {phase:20s}: {", ".join(parts)}')
            else:
                print(f'    {phase:20s}: (no change)')

        # Final totals
        if self.history:
            _, final, _ = self.history[-1]
            total = sum(v for c in final.values() for k, v in c.items()
                        if '_hotspot' not in k and isinstance(v, int))
            print(f'    {"TOTAL":20s}: {total}')


# Backwards compatibility
def check_layer(top, li, layer_name, min_spacing, min_width=None,
                phase='', halt_on_error=False):
    """Legacy single-layer check."""
    if not ENABLED:
        return None

    region = db.Region(top.begin_shapes_rec(li))
    result = {}

    space_viols = region.space_check(min_spacing)
    n_space = space_viols.count()
    if n_space > 0:
        result['spacing'] = n_space

    if min_width:
        width_viols = region.width_check(min_width)
        n_width = width_viols.count()
        if n_width > 0:
            result['width'] = n_width

    if result:
        detail = ', '.join(f'{k}={v}' for k, v in result.items())
        print(f'  ⚠️ {layer_name}: {detail} after {phase}')
        if halt_on_error:
            raise RuntimeError(
                f'Inline DRC failed: {layer_name} {detail} after {phase}')

    return result


def check_metal_layers(top, layers, phase=''):
    """Legacy multi-layer check."""
    if not ENABLED:
        return {}

    results = {}
    for name, (li, min_s, min_w) in layers.items():
        r = check_layer(top, li, name, min_s, min_w, phase)
        if r:
            results[name] = r

    if not results:
        print(f'  ✓ Inline DRC clean after {phase}')

    return results
