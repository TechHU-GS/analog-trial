"""Constraint-based analog device placer using OR-tools CP-SAT.

Solves a 2D rectangle packing problem with analog-specific constraints:
- No overlap (with minimum gap for routing channels)
- Symmetry pairs (matched devices)
- Adjacency (maximum distance between paired devices)
- Flow ordering (signal flow direction)
- Row alignment (devices in same logical row share Y coordinate)
- Row spacing (derived from PDK routing pitch x track count)

All gap/spacing values derived from atk.pdk — single source of truth.
Dimensions in µm, snapped to placement grid for CP-SAT integers.

Usage:
    from atk.pdk import CHANNEL_3T
    placer = ConstraintPlacer(devices)
    placer.add_row("pmos", ["M1", "M2", "M3", "M5"], gap=3.0)
    placer.add_row_spacing("pmos", "hbt", n_tracks=3)  # from PDK
    result = placer.solve(max_width=120.0, max_height=80.0)
"""

from ortools.sat.python import cp_model
from ..pdk import (
    channel_width, M2_ROUTE_PITCH, VIA1_PAD, VIA_CLEAR, DEV_MARGIN, UM,
)


# Default placement grid: 100nm (coarser = faster, 50nm grid is finer)
DEFAULT_GRID_UM = 0.10


class ConstraintPlacer:
    """CP-SAT based analog device placer."""

    def __init__(self, devices, grid=DEFAULT_GRID_UM):
        """Initialize placer.

        Args:
            devices: dict name -> {"w": float, "h": float, ...}
                     Width and height in µm.
            grid: placement grid resolution in µm (default 100nm).
        """
        self.devices = devices
        self.grid = grid
        self.model = cp_model.CpModel()
        self.x_vars = {}
        self.y_vars = {}
        self.rows = {}       # row_name -> [device_names]
        self.row_y = {}      # row_name -> y_var (shared)

    def _to_g(self, um):
        """Convert µm to grid units."""
        return int(round(um / self.grid))

    def _to_um(self, g):
        """Convert grid units to µm."""
        return g * self.grid

    def setup(self, max_width, max_height):
        """Create x, y variables for all devices.

        Args:
            max_width: maximum layout width (µm)
            max_height: maximum layout height (µm)
        """
        mx = self._to_g(max_width)
        my = self._to_g(max_height)
        for name, dev in self.devices.items():
            wg = self._to_g(dev['w'])
            hg = self._to_g(dev['h'])
            self.x_vars[name] = self.model.new_int_var(0, mx - wg, f'x_{name}')
            self.y_vars[name] = self.model.new_int_var(0, my - hg, f'y_{name}')

    # ─── NWell island spacing ───

    def add_nwell_spacing(self, islands, inter_min_um):
        """Add no-overlap constraints between devices in different NWell islands.

        Args:
            islands: list of {"id": str, "net": str, "devices": [str]}
            inter_min_um: minimum gap between cross-island device pairs (µm)
        """
        for i, island_a in enumerate(islands):
            for island_b in islands[i+1:]:
                cross_pairs = [
                    (a, b)
                    for a in island_a['devices']
                    for b in island_b['devices']
                    if a in self.devices and b in self.devices
                ]
                if cross_pairs:
                    self._add_no_overlap_pairs(cross_pairs, inter_min_um)

    # ─── Tie strip halo ───

    def add_tie_strip(self, row_name, side, strip_h_um):
        """Reserve vertical space for a tie strip adjacent to a row.

        Adds a halo to the row's effective height, consumed by add_row_spacing.

        Args:
            row_name: row that needs a tie strip
            side: 'above' or 'below'
            strip_h_um: tie strip height in µm
        """
        if not hasattr(self, 'row_halo'):
            self.row_halo = {}
        if row_name not in self.row_halo:
            self.row_halo[row_name] = {'above': 0.0, 'below': 0.0}
        self.row_halo[row_name][side] = strip_h_um

    # ─── Equal spacing (match groups) ───

    def add_equal_spacing(self, device_names):
        """Enforce equal X gaps between consecutive devices in a group.

        All devices must be in the same row (same Y) and ordered left-to-right.

        Args:
            device_names: list of device names (in X order)
        """
        if len(device_names) < 2:
            return
        gap_var = self.model.new_int_var(
            0, 10000, f'eq_gap_{device_names[0]}')
        for i in range(len(device_names) - 1):
            a, b = device_names[i], device_names[i + 1]
            wa = self._to_g(self.devices[a]['w'])
            self.model.add(
                self.x_vars[b] - self.x_vars[a] - wa == gap_var)

    # ─── No overlap ───

    def add_no_overlap(self, min_gap_um=None):
        """Non-overlapping constraint between ALL device pairs.

        Args:
            min_gap_um: minimum gap in µm. If None, uses DEV_MARGIN from PDK.
        """
        if min_gap_um is None:
            min_gap_um = DEV_MARGIN / UM  # PDK default: 200nm = 0.2µm
        self._add_no_overlap_pairs(
            [(a, b) for i, a in enumerate(self.devices)
                    for b in list(self.devices)[i+1:]],
            min_gap_um)

    def add_no_overlap_between_rows(self, row_a, row_b, min_gap_um=None):
        """Non-overlapping between devices in two different rows.

        Args:
            row_a, row_b: row names
            min_gap_um: gap in µm (default: DEV_MARGIN from PDK)
        """
        if min_gap_um is None:
            min_gap_um = DEV_MARGIN / UM
        pairs = [(a, b) for a in self.rows[row_a] for b in self.rows[row_b]]
        self._add_no_overlap_pairs(pairs, min_gap_um)

    def _add_no_overlap_pairs(self, pairs, gap_um):
        """Internal: add no-overlap for specific pairs."""
        gap_g = self._to_g(gap_um)
        for a, b in pairs:
            wa = self._to_g(self.devices[a]['w'])
            ha = self._to_g(self.devices[a]['h'])
            wb = self._to_g(self.devices[b]['w'])
            hb = self._to_g(self.devices[b]['h'])

            bL = self.model.new_bool_var(f'no_{a}_{b}_L')
            bR = self.model.new_bool_var(f'no_{a}_{b}_R')
            bB = self.model.new_bool_var(f'no_{a}_{b}_B')
            bA = self.model.new_bool_var(f'no_{a}_{b}_A')

            self.model.add(self.x_vars[a] + wa + gap_g <= self.x_vars[b]).only_enforce_if(bL)
            self.model.add(self.x_vars[b] + wb + gap_g <= self.x_vars[a]).only_enforce_if(bR)
            self.model.add(self.y_vars[a] + ha + gap_g <= self.y_vars[b]).only_enforce_if(bB)
            self.model.add(self.y_vars[b] + hb + gap_g <= self.y_vars[a]).only_enforce_if(bA)
            self.model.add_bool_or([bL, bR, bB, bA])

    # ─── Row alignment ───

    def add_row(self, row_name, device_names, gap=None, order='left_to_right'):
        """Place devices in a horizontal row with fixed intra-row gap.

        All devices share the same Y. X positions are sequential.

        Args:
            row_name: label for this row
            device_names: list of device names (left to right)
            gap: gap between devices in µm. If None, uses DEV_MARGIN from PDK.
            order: 'left_to_right' or 'free'
        """
        if not device_names:
            return
        if gap is None:
            gap = DEV_MARGIN / UM

        self.rows[row_name] = device_names
        gap_g = self._to_g(gap)

        first = device_names[0]
        for name in device_names[1:]:
            self.model.add(self.y_vars[name] == self.y_vars[first])
        self.row_y[row_name] = self.y_vars[first]

        if order == 'left_to_right':
            for i in range(len(device_names) - 1):
                a, b = device_names[i], device_names[i + 1]
                wa = self._to_g(self.devices[a]['w'])
                self.model.add(self.x_vars[a] + wa + gap_g <= self.x_vars[b])

    # ─── Row spacing (PDK-derived) ───

    def add_row_spacing(self, row_above, row_below, n_tracks=None, gap_um=None):
        """Enforce vertical gap between rows for routing channels.

        Uses PDK channel_width() to compute gap from track count.
        row_above.y >= row_below.y + max_h_below + channel_gap.

        Args:
            row_above: upper row name
            row_below: lower row name
            n_tracks: number of M2 signal tracks needed (uses PDK pitch).
                      Mutually exclusive with gap_um.
            gap_um: explicit gap in µm (overrides n_tracks).
        """
        if gap_um is not None:
            gap_g = self._to_g(gap_um)
        elif n_tracks is not None:
            gap_nm = channel_width(n_tracks)
            gap_g = self._to_g(gap_nm / UM)
        else:
            raise ValueError("Specify n_tracks or gap_um")

        max_h_below = max(
            self._to_g(self.devices[n]['h']) for n in self.rows[row_below])

        # Add tie strip halos if registered
        halo_g = 0
        if hasattr(self, 'row_halo'):
            if row_below in self.row_halo:
                halo_g += self._to_g(self.row_halo[row_below]['above'])
            if row_above in self.row_halo:
                halo_g += self._to_g(self.row_halo[row_above]['below'])

        self.model.add(
            self.row_y[row_above] >= self.row_y[row_below] + max_h_below + gap_g + halo_g)

    # ─── Same Y (sub-rows at same height) ───

    def add_same_y(self, row_a, row_b):
        """Force two rows to share the same Y coordinate."""
        self.model.add(self.row_y[row_a] == self.row_y[row_b])

    # ─── Symmetry ───

    def add_symmetry_y(self, name_a, name_b):
        """Two devices symmetric about a vertical axis. Same Y, mirrored X.

        Enforces center_a + center_b = 2*axis (centers equidistant from axis).
        Uses 4× scaling: 4*axis = 2*xa + wa + 2*xb + wb.
        Requires (wa + wb) % 4 == 0 on the grid; same-width pairs always work.
        For different-width pairs, use add_adjacent instead.
        """
        wa = self._to_g(self.devices[name_a]['w'])
        wb = self._to_g(self.devices[name_b]['w'])

        self.model.add(self.y_vars[name_a] == self.y_vars[name_b])

        # center_a + center_b = 2 * axis → 4*axis = 2*xa + wa + 2*xb + wb
        axis = self.model.new_int_var(0, 100000, f'sym_{name_a}_{name_b}')
        self.model.add(
            4 * axis == 2 * self.x_vars[name_a] + wa +
                         2 * self.x_vars[name_b] + wb)

    # ─── Adjacency ───

    def add_adjacent(self, name_a, name_b, max_dist_um):
        """Manhattan distance between centers <= max_dist_um."""
        dist_g = self._to_g(max_dist_um)
        wa = self._to_g(self.devices[name_a]['w'])
        ha = self._to_g(self.devices[name_a]['h'])
        wb = self._to_g(self.devices[name_b]['w'])
        hb = self._to_g(self.devices[name_b]['h'])

        # 2× scaled centers: c2 = 2*x + w (always integer, no parity issue)
        c2x_a = self.model.new_int_var(0, 400000, f'c2x_{name_a}_{name_b}_a')
        c2x_b = self.model.new_int_var(0, 400000, f'c2x_{name_a}_{name_b}_b')
        c2y_a = self.model.new_int_var(0, 400000, f'c2y_{name_a}_{name_b}_a')
        c2y_b = self.model.new_int_var(0, 400000, f'c2y_{name_a}_{name_b}_b')

        self.model.add(c2x_a == 2 * self.x_vars[name_a] + wa)
        self.model.add(c2x_b == 2 * self.x_vars[name_b] + wb)
        self.model.add(c2y_a == 2 * self.y_vars[name_a] + ha)
        self.model.add(c2y_b == 2 * self.y_vars[name_b] + hb)

        dx = self.model.new_int_var(0, 400000, f'dx_{name_a}_{name_b}')
        dy = self.model.new_int_var(0, 400000, f'dy_{name_a}_{name_b}')
        self.model.add_abs_equality(dx, c2x_a - c2x_b)
        self.model.add_abs_equality(dy, c2y_a - c2y_b)
        self.model.add(dx + dy <= 2 * dist_g)  # c2 is 2× scaled

    # ─── X alignment ───

    def add_x_align(self, name_a, name_b, max_offset_um=0.0):
        """Align two devices so their X centers are within max_offset_um."""
        wa = self._to_g(self.devices[name_a]['w'])
        wb = self._to_g(self.devices[name_b]['w'])
        off_g = self._to_g(max_offset_um)

        # 2*center_a = 2*x_a + w_a, 2*center_b = 2*x_b + w_b
        # |center_a - center_b| <= offset → |2*ca - 2*cb| <= 2*offset
        diff = self.model.new_int_var(-200000, 200000, f'xal_{name_a}_{name_b}')
        self.model.add(diff == (2 * self.x_vars[name_a] + wa) -
                                (2 * self.x_vars[name_b] + wb))
        abs_diff = self.model.new_int_var(0, 200000, f'xal_abs_{name_a}_{name_b}')
        self.model.add_abs_equality(abs_diff, diff)
        self.model.add(abs_diff <= 2 * off_g)

    # ─── Y range ───

    def add_y_range(self, name_a, name_b, max_dy_um):
        """Two devices' Y centers within max_dy_um."""
        ha = self._to_g(self.devices[name_a]['h'])
        hb = self._to_g(self.devices[name_b]['h'])
        dy_g = self._to_g(max_dy_um)

        # 2*center_y = 2*y + h  (scaled to avoid fractions)
        diff = self.model.new_int_var(-200000, 200000, f'yr_{name_a}_{name_b}')
        self.model.add(diff == (2 * self.y_vars[name_a] + ha) -
                                (2 * self.y_vars[name_b] + hb))
        abs_diff = self.model.new_int_var(0, 200000, f'yr_abs_{name_a}_{name_b}')
        self.model.add_abs_equality(abs_diff, diff)
        self.model.add(abs_diff <= 2 * dy_g)

    # ─── X ordering ───

    def add_x_order(self, name_a, name_b, min_gap_um=0.0):
        """Enforce name_a left of name_b."""
        wa = self._to_g(self.devices[name_a]['w'])
        gap_g = self._to_g(min_gap_um)
        self.model.add(self.x_vars[name_a] + wa + gap_g <= self.x_vars[name_b])

    # ─── Zone isolation ───

    def add_zone_isolation(self, zones, min_gaps):
        """Enforce minimum gap between device groups (isolation zones).

        Args:
            zones: dict zone_name -> [device_names]
            min_gaps: list of {"from": str, "to": str, "min_gap_um": float}
        """
        for gap_spec in min_gaps:
            zone_a = zones.get(gap_spec['from'], [])
            zone_b = zones.get(gap_spec['to'], [])
            pairs = [
                (a, b) for a in zone_a for b in zone_b
                if a in self.devices and b in self.devices
            ]
            if pairs:
                self._add_no_overlap_pairs(pairs, gap_spec['min_gap_um'])

    # ─── Net-aware wirelength ───

    def set_nets(self, nets, device_pins):
        """Register net connectivity for wirelength estimation.

        Args:
            nets: list of {"name": str, "pins": ["M1.D", "M2.G", ...]}
            device_pins: dict (dev_name, pin_name) -> (offset_x_um, offset_y_um)
                         Pin position relative to device origin in µm.
        """
        self.nets = nets
        self.device_pins = device_pins

    # ─── Objective ───

    def minimize_area(self):
        """Minimize bounding box (width + height as proxy for area)."""
        self.bb_max_x = self.model.new_int_var(0, 100000, 'bb_max_x')
        self.bb_max_y = self.model.new_int_var(0, 100000, 'bb_max_y')

        for name, dev in self.devices.items():
            wg = self._to_g(dev['w'])
            hg = self._to_g(dev['h'])
            self.model.add(self.bb_max_x >= self.x_vars[name] + wg)
            self.model.add(self.bb_max_y >= self.y_vars[name] + hg)

        self.model.minimize(self.bb_max_x + self.bb_max_y)

    def minimize_area_and_wirelength(self, wl_weight=0.5):
        """Minimize area + weighted X-direction half-perimeter wirelength.

        HPWL only in X direction (Y is fixed by row structure).
        Requires set_nets() to have been called first.

        Args:
            wl_weight: weight of HPWL term relative to area (default 0.5).
        """
        self.bb_max_x = self.model.new_int_var(0, 100000, 'bb_max_x')
        self.bb_max_y = self.model.new_int_var(0, 100000, 'bb_max_y')

        for name, dev in self.devices.items():
            wg = self._to_g(dev['w'])
            hg = self._to_g(dev['h'])
            self.model.add(self.bb_max_x >= self.x_vars[name] + wg)
            self.model.add(self.bb_max_y >= self.y_vars[name] + hg)

        # Compute X-HPWL for each signal net
        net_hpwls = []
        self._net_hpwl_vars = {}
        for net in getattr(self, 'nets', []):
            pins = net['pins']
            if len(pins) < 2:
                continue

            # Compute absolute X position of each pin on grid
            pin_xs = []
            for p in pins:
                parts = p.split('.')
                dev = parts[0]
                pin_name = parts[1] if len(parts) > 1 else parts[0]
                if dev not in self.x_vars:
                    continue
                key = (dev, pin_name)
                if key not in self.device_pins:
                    continue
                ox_um = self.device_pins[key][0]
                ox_g = self._to_g(ox_um)
                px = self.model.new_int_var(
                    0, 200000, f'px_{net["name"]}_{dev}_{pin_name}')
                self.model.add(px == self.x_vars[dev] + ox_g)
                pin_xs.append(px)

            if len(pin_xs) < 2:
                continue

            # HPWL_x = max(pin_xs) - min(pin_xs)
            max_x = self.model.new_int_var(0, 200000, f'hpwl_max_{net["name"]}')
            min_x = self.model.new_int_var(0, 200000, f'hpwl_min_{net["name"]}')
            self.model.add_max_equality(max_x, pin_xs)
            self.model.add_min_equality(min_x, pin_xs)

            hpwl = self.model.new_int_var(0, 200000, f'hpwl_{net["name"]}')
            self.model.add(hpwl == max_x - min_x)
            net_hpwls.append(hpwl)
            self._net_hpwl_vars[net['name']] = hpwl

        # Total HPWL
        self._total_hpwl = self.model.new_int_var(0, 10_000_000, 'total_hpwl')
        if net_hpwls:
            self.model.add(self._total_hpwl == sum(net_hpwls))
        else:
            self.model.add(self._total_hpwl == 0)

        # Combined objective: area + wl_weight * HPWL
        # Scale wl_weight to integer: multiply by 10 for precision
        wl_w10 = int(round(wl_weight * 10))
        self.model.minimize(
            10 * (self.bb_max_x + self.bb_max_y) + wl_w10 * self._total_hpwl)

    def add_device_region(self, device_names, x_min, y_min, x_max, y_max):
        """Constrain devices to a bounding box region (all values in µm)."""
        gx_min = self._to_g(x_min)
        gy_min = self._to_g(y_min)
        gx_max = self._to_g(x_max)
        gy_max = self._to_g(y_max)
        for name in device_names:
            if name not in self.x_vars:
                continue
            wg = self._to_g(self.devices[name]['w'])
            hg = self._to_g(self.devices[name]['h'])
            self.model.add(self.x_vars[name] >= gx_min)
            self.model.add(self.y_vars[name] >= gy_min)
            self.model.add(self.x_vars[name] + wg <= gx_max)
            self.model.add(self.y_vars[name] + hg <= gy_max)

    def add_edge_keepout(self, margin_um):
        """Enforce margin on ALL 4 sides (left/bottom/right/top).

        Left/bottom: x >= margin, y >= margin
        Right/top: x + w + margin <= bb_max_x, y + h + margin <= bb_max_y
        Must be called AFTER minimize_area().
        """
        mg = self._to_g(margin_um)
        for name, dev in self.devices.items():
            wg = self._to_g(dev['w'])
            hg = self._to_g(dev['h'])
            # Left/bottom
            self.model.add(self.x_vars[name] >= mg)
            self.model.add(self.y_vars[name] >= mg)
            # Right/top (device right edge + margin <= bbox)
            self.model.add(self.x_vars[name] + wg + mg <= self.bb_max_x)
            self.model.add(self.y_vars[name] + hg + mg <= self.bb_max_y)

    # ─── Aspect ratio ───

    def add_max_aspect(self, max_ratio):
        """Constrain bounding box aspect ratio: max(W/H, H/W) <= max_ratio.

        Must be called AFTER minimize_area() or minimize_area_and_wirelength().
        Uses integer arithmetic: H <= ratio_num * W and W <= ratio_num * H
        where ratio_num = ceil(max_ratio * 100) and variables are scaled by 100.
        """
        # Use multiplied integer form to avoid division:
        #   bb_max_y <= max_ratio * bb_max_x  (height not too tall)
        #   bb_max_x <= max_ratio * bb_max_y  (width not too wide)
        # Scale ratio to integer: multiply by 100, compare with 100x variables
        ratio_100 = int(max_ratio * 100 + 0.5)
        self.model.add(100 * self.bb_max_y <= ratio_100 * self.bb_max_x)
        self.model.add(100 * self.bb_max_x <= ratio_100 * self.bb_max_y)

    # ─── Solve ───

    def solve(self, time_limit=30.0):
        """Run CP-SAT solver. Returns dict name -> (x_um, y_um) or None."""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.random_seed = 42
        solver.parameters.num_workers = 1

        status = solver.solve(self.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result = {}
            for name in self.devices:
                result[name] = (self._to_um(solver.value(self.x_vars[name])),
                                self._to_um(solver.value(self.y_vars[name])))

            opt = 'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'
            max_x = max(x + self.devices[n]['w'] for n, (x, y) in result.items())
            max_y = max(y + self.devices[n]['h'] for n, (x, y) in result.items())
            print(f'  Placement {opt} in {solver.wall_time:.2f}s')
            print(f'  Bounding box: {max_x:.1f} x {max_y:.1f} um = {max_x * max_y:.0f} um2')

            # Report HPWL if computed
            if hasattr(self, '_total_hpwl'):
                hpwl_g = solver.value(self._total_hpwl)
                hpwl_um = self._to_um(hpwl_g)
                print(f'  Total HPWL (X): {hpwl_um:.1f} um')

            return result, opt
        else:
            status_name = solver.status_name(status)
            print(f'  Placement FAILED: {status_name}')
            return None, status_name

    def print_summary(self):
        """Print device and constraint summary."""
        print(f'  Devices: {len(self.devices)}')
        for name, dev in sorted(self.devices.items()):
            print(f'    {name:10s}  {dev["w"]:5.2f} x {dev["h"]:5.2f} um')
        print(f'  Rows: {len(self.rows)}')
        for rname, devs in self.rows.items():
            print(f'    {rname}: {", ".join(devs)}')
