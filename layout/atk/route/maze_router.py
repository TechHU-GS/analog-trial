"""Three-layer A* maze router for analog IC signal routing on M3+M4+M5.

Grid resolution from pdk.MAZE_GRID. Costs: same-layer step=1, via=VIA_COST.
Supports multi-pin nets via sequential nearest-neighbor Steiner tree.

Layer mapping (2026-03-18 verified):
  Router layer 0 → Metal3 (HORIZONTAL, IHP preferred)
  Router layer 1 → Metal4 (VERTICAL, IHP preferred)
  Router layer 2 → Metal5 (HORIZONTAL per IHP LEF, used as V for routability)
  Via code -1    → Via3 (M3↔M4, GDS 49/0)
  Via code -2    → Via4 (M4↔M5, GDS 66/0)

Pin entry: Via2 bridge pre-drawn at M2 AP → pin presented at layer 0 (M3).

Obstacle model:
  permanent: power via stack pads on M3/M4/M5, cap_cmim on M5 — never cleared.
  soft:      pin access protection rings — clearable per-net for routing.

NOTE: Device bboxes are NOT obstacles (PCell has no M3/M4/M5 geometry, verified).
"""

import heapq
from ..pdk import MAZE_GRID, MAZE_MARGIN, M2_SIG_W

# --- Abstract routing layer indices ---
# Internal to router; physical layer mapping done at GDS assembly.
M1_LYR = 0   # → Metal3 (physical)
M2_LYR = 1   # → Metal4 (physical)
M3_LYR = 2   # → Metal5 (physical)

# Keep old names for backward compat with solver.py imports,
# but the MEANING has changed:
#   M1_LYR(0) = Metal3, M2_LYR(1) = Metal4, M3_LYR(2) = Metal5
# M4_LYR is no longer used (3-layer router).
M4_LYR = None  # Explicitly disabled — catch any stale references

N_ROUTING_LAYERS = 3

# Adjacent layer pairs for via transitions
_VIA_PAIRS = {
    (M1_LYR, M2_LYR),   # Via3 (M3↔M4)
    (M2_LYR, M3_LYR),   # Via4 (M4↔M5)
}

# For a given layer, which layers can be reached via a single via
_VIA_NEIGHBORS = {
    M1_LYR: (M2_LYR,),           # M3 → M4
    M2_LYR: (M1_LYR, M3_LYR),   # M4 → M3 or M5
    M3_LYR: (M2_LYR,),           # M5 → M4
}


class MazeRouter:
    """Three-layer (M3+M4+M5) maze router using A* pathfinding."""

    GRID = MAZE_GRID
    VIA_COST = 8

    def __init__(self, x_range, y_range):
        """Initialize router grid.

        Args:
            x_range: (x_min_nm, x_max_nm)
            y_range: (y_min_nm, y_max_nm)
        """
        self.x0, self.x1 = x_range
        self.y0, self.y1 = y_range
        self.nx = (self.x1 - self.x0) // self.GRID + 1
        self.ny = (self.y1 - self.y0) // self.GRID + 1
        self.blocked = set()      # (gx, gy, layer) — impassable
        self.permanent = set()    # (gx, gy, layer) — subset of blocked, never clearable
        self.used = set()         # (gx, gy, layer) — occupied by previous routes
        self.pin_terminals = set()  # (gx, gy) — pin centers: margin=0 in _mark_used

    def to_grid(self, x_nm, y_nm):
        """Convert nm coordinates to grid indices."""
        return ((x_nm - self.x0 + self.GRID // 2) // self.GRID,
                (y_nm - self.y0 + self.GRID // 2) // self.GRID)

    _g = to_grid

    def to_nm(self, gx, gy):
        """Convert grid indices to nm (snapped to 5nm)."""
        x = self.x0 + gx * self.GRID
        y = self.y0 + gy * self.GRID
        return ((x + 2) // 5) * 5, ((y + 2) // 5) * 5

    _nm = to_nm

    def block_rect(self, x1, y1, x2, y2, layer, margin=0, permanent=False,
                   force_permanent=False):
        """Mark rectangle + margin as obstacle on given layer.

        Args:
            permanent: if True, cells also go into self.permanent and
                       cannot be cleared by any unblock operation.
                       Pin terminal cells are NEVER added to permanent
                       (they must remain clearable for routing).
            force_permanent: if True, overrides pin_terminal exemption.
                       Use for power stubs that must never be routed through.

        Returns:
            set of (gx, gy, layer) cells that were blocked.
        """
        cells = set()
        gx1, gy1 = self.to_grid(min(x1, x2) - margin, min(y1, y2) - margin)
        gx2, gy2 = self.to_grid(max(x1, x2) + margin, max(y1, y2) + margin)
        for gx in range(max(0, gx1), min(self.nx, gx2 + 1)):
            for gy in range(max(0, gy1), min(self.ny, gy2 + 1)):
                cell = (gx, gy, layer)
                self.blocked.add(cell)
                cells.add(cell)
                if permanent and (force_permanent or (gx, gy) not in self.pin_terminals):
                    self.permanent.add(cell)
        return cells

    def safe_discard(self, cell):
        """Remove cell from blocked only if not permanent."""
        if cell not in self.permanent:
            self.blocked.discard(cell)
            return True
        return False


    def unblock_radius(self, x_nm, y_nm, radius=5, layer=None):
        """Unblock cells around a point (respects permanent)."""
        gp = self.to_grid(x_nm, y_nm)
        layers = tuple(range(N_ROUTING_LAYERS)) if layer is None else (layer,)
        for lyr in layers:
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    self.safe_discard((gp[0] + dx, gp[1] + dy, lyr))

    def add_pin_escape(self, pin_nm, bbox_nm, layers=None, width_nm=None,
                       all_directions=False):
        """Clear escape channel(s) from pin through bbox edge.

        By default clears ONE direction (nearest bbox edge).
        With all_directions=True, clears ALL 4 directions — used for
        trapped signal pins that need escape toward distant net-mates.
        Respects permanent blocks — only clears soft (pin access) cells.
        """
        if layers is None:
            layers = tuple(range(N_ROUTING_LAYERS))
        if width_nm is None:
            width_nm = M2_SIG_W
        px, py = pin_nm
        left, bot, right, top = bbox_nm
        half_w = max(1, (width_nm // self.GRID + 1) // 2)

        edges = [
            ('top',    top  - py, 0, +1),
            ('bottom', py - bot,  0, -1),
            ('right',  right - px, +1, 0),
            ('left',   px - left, -1, 0),
        ]
        edges.sort(key=lambda e: e[1])

        gpx, gpy = self.to_grid(px, py)

        for _, dist_nm, dx, dy in edges:
            if dist_nm < 0:
                continue

            n_steps = dist_nm // self.GRID + 3

            for step in range(n_steps + 1):
                cx = gpx + step * dx
                cy = gpy + step * dy
                if not (0 <= cx < self.nx and 0 <= cy < self.ny):
                    break
                for w in range(-half_w, half_w + 1):
                    wx = cx + w * abs(dy)
                    wy = cy + w * abs(dx)
                    if 0 <= wx < self.nx and 0 <= wy < self.ny:
                        for lyr in layers:
                            self.safe_discard((wx, wy, lyr))

            if not all_directions:
                break  # Only use nearest edge

    def _astar(self, start_xy, target_set, start_layer=None):
        """A* from start to nearest point in target_set (grid coords).

        start_xy: (gx, gy) — tries both layers unless start_layer specified.
        target_set: set of (gx, gy) — matches any layer.
        start_layer: if int (M1_LYR or M2_LYR), only start on that layer.
        Returns path [(gx, gy, layer), ...] or None.
        """
        target_list = list(target_set)

        def _passable(cell):
            if cell in self.blocked:
                return False
            if cell in self.used:
                return False
            return True

        def h(gx, gy):
            return min(abs(gx - tx) + abs(gy - ty) for tx, ty in target_list)

        open_set = []
        came_from = {}
        g_score = {}

        layers = (start_layer,) if start_layer is not None else tuple(range(N_ROUTING_LAYERS - 1, -1, -1))
        for layer in layers:
            s = (start_xy[0], start_xy[1], layer)
            if _passable(s):
                g_score[s] = 0
                heapq.heappush(open_set, (h(*start_xy), 0, s))

        while open_set:
            _, cost, cur = heapq.heappop(open_set)
            if cost > g_score.get(cur, float('inf')):
                continue
            if (cur[0], cur[1]) in target_set:
                path = [cur]
                while cur in came_from:
                    cur = came_from[cur]
                    path.append(cur)
                path.reverse()
                return path

            gx, gy, layer = cur
            # Cardinal neighbors — with H/V direction cost bias
            # Layer 0 (M3) prefers HORIZONTAL: vertical steps cost more
            # Layer 1 (M4) prefers VERTICAL: horizontal steps cost more
            # Layer 2 (M5) prefers VERTICAL: horizontal steps cost more
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < self.nx and 0 <= ny < self.ny:
                    nb = (nx, ny, layer)
                    if _passable(nb):
                        # Non-preferred direction: 4x cost penalty
                        is_horizontal = (dx != 0)
                        if layer == M1_LYR and not is_horizontal:  # M3: H preferred
                            nc = cost + 4
                        elif layer in (M2_LYR, M3_LYR) and is_horizontal:  # M4,M5: V preferred
                            nc = cost + 4
                        else:
                            nc = cost + 1
                        if nc < g_score.get(nb, float('inf')):
                            g_score[nb] = nc
                            came_from[nb] = cur
                            heapq.heappush(open_set, (nc + h(nx, ny), nc, nb))
            # Via (layer change) — try all adjacent layers
            for ol in _VIA_NEIGHBORS.get(layer, ()):
                nb = (gx, gy, ol)
                if _passable(nb):
                    nc = cost + self.VIA_COST
                    if nc < g_score.get(nb, float('inf')):
                        g_score[nb] = nc
                        came_from[nb] = cur
                        heapq.heappush(open_set, (nc + h(gx, gy), nc, nb))

        return None

    def route(self, net_name, pin_nms):
        """Route multi-pin net using sequential nearest-neighbor Steiner tree.

        Args:
            net_name: string for debug output
            pin_nms: list of (x_nm, y_nm) or (x_nm, y_nm, layer) pin positions.
                     If layer is given, A* starts only on that layer (M1-only pin).
        Returns:
            list of segments [(x1, y1, x2, y2, layer)]
            layer: 0=M1, 1=M2, -1=VIA
        """
        if len(pin_nms) < 2:
            return []

        grid_pins = []
        pin_layers = []
        for p in pin_nms:
            grid_pins.append(self.to_grid(p[0], p[1]))
            pin_layers.append(p[2] if len(p) > 2 else None)

        tree = {grid_pins[0]}
        paths = []
        remaining = list(range(1, len(grid_pins)))

        while remaining:
            best_idx, best_path = None, None
            for idx in remaining:
                path = self._astar(grid_pins[idx], tree,
                                   start_layer=pin_layers[idx])
                if path and (best_path is None or len(path) < len(best_path)):
                    best_idx, best_path = idx, path
            if best_idx is None:
                for idx in remaining:
                    gp = grid_pins[idx]
                    nm_x, nm_y = self.to_nm(gp[0], gp[1])
                    print(f'    STUCK pin[{idx}] ({nm_x/1000:.1f},{nm_y/1000:.1f})um '
                          f'grid({gp[0]},{gp[1]})')
                print(f'  WARNING: {net_name}: {len(remaining)} pins unreachable')
                return None  # explicit failure (vs [] = success with 0 segments)
            remaining.remove(best_idx)
            paths.append(best_path)
            for pt in best_path:
                tree.add(pt[:2])
            self._mark_used(best_path)

        segs = []
        for path in paths:
            segs.extend(self._simplify(path))
        segs = self._insert_junction_vias(segs)
        # Mark junction via positions (they bypass _mark_used)
        # Only mark Via1 — Via2/Via3 junction vias share grid positions with
        # existing M2/M3 wires already marked, so additional marking is
        # over-aggressive and blocks subsequent net routing.
        for seg in segs:
            if seg[4] == -1:
                self._mark_via_used(seg[0], seg[1])
        # Reconnect disconnected components via A*-routed bridges
        segs = self._reconnect_components(net_name, segs)
        # Re-check junction vias after reconnection (bridge may cross layers)
        segs = self._insert_junction_vias(segs)
        # Mark any new junction vias from reconnection
        for seg in segs:
            if seg[4] == -1:
                self._mark_via_used(seg[0], seg[1])

        return segs

    @staticmethod
    def _insert_junction_vias(segs):
        """Insert missing Via1 at M1/M2 junctions.

        When multi-pin sub-routes share a coordinate on different layers
        (one sub-route passes through on M1, another on M2), the router
        doesn't automatically add a via because each sub-route is routed
        independently.  This pass finds such junctions and inserts vias.
        """
        from collections import defaultdict
        pt_layers = defaultdict(set)
        # Track existing vias by (point, via_code) to avoid duplicates
        via_pts = defaultdict(set)  # pt → set of via codes present
        for seg in segs:
            x1, y1, x2, y2, layer = seg[0], seg[1], seg[2], seg[3], seg[4]
            if layer < 0:
                via_pts[(x1, y1)].add(layer)
            else:
                pt_layers[(x1, y1)].add(layer)
                pt_layers[(x2, y2)].add(layer)
        added = 0
        # Via3: layer 0(M3) ↔ layer 1(M4), code -1
        # Via4: layer 1(M4) ↔ layer 2(M5), code -2
        for pt, layers in pt_layers.items():
            for lo in range(N_ROUTING_LAYERS - 1):
                hi = lo + 1
                via_code = -1 - lo
                if lo in layers and hi in layers and via_code not in via_pts.get(pt, set()):
                    segs.append((pt[0], pt[1], pt[0], pt[1], via_code))
                    added += 1
        if added:
            print(f'    Router: inserted {added} junction via(s)')
        return segs

    def _reconnect_components(self, net_name, segs):
        """Reconnect disconnected segment components using A* mini-routes.

        After multi-pin Steiner routing + simplification, some sub-routes
        may not share exact coordinates. This method:
        1. Finds connected components via shared endpoints
        2. For each pair of disconnected components on the same layer,
           tries A* to bridge them (respects used/blocked)
        3. Marks bridge paths as used for subsequent nets
        """
        from collections import defaultdict

        MAX_ITER = 15
        added = 0

        for _iteration in range(MAX_ITER):
            # Insert junction vias before component analysis
            segs = self._insert_junction_vias(segs)

            # Build components
            pt_seg = defaultdict(set)
            for i, seg in enumerate(segs):
                lyr = seg[4]
                if lyr < 0:
                    # Via codes: -1=Via1(M1↔M2), -2=Via2(M2↔M3), -3=Via3(M3↔M4)
                    # Register on BOTH connected metal layers so the graph
                    # sees cross-layer connectivity.
                    lo = (-lyr) - 1   # -1→0(M1), -2→1(M2), -3→2(M3)
                    hi = lo + 1       # -1→1(M2), -2→2(M3), -3→3(M4)
                    pt_seg[(seg[0], seg[1], lo)].add(i)
                    pt_seg[(seg[0], seg[1], hi)].add(i)
                else:
                    pt_seg[(seg[0], seg[1], lyr)].add(i)
                    pt_seg[(seg[2], seg[3], lyr)].add(i)

            n = len(segs)
            adj = [set() for _ in range(n)]
            for indices in pt_seg.values():
                idx_list = list(indices)
                for a in idx_list:
                    for b in idx_list:
                        if a != b:
                            adj[a].add(b)

            visited = [False] * n
            components = []
            for start in range(n):
                if visited[start]:
                    continue
                comp = []
                stack = [start]
                while stack:
                    node = stack.pop()
                    if visited[node]:
                        continue
                    visited[node] = True
                    comp.append(node)
                    for nb in adj[node]:
                        if not visited[nb]:
                            stack.append(nb)
                components.append(comp)

            if len(components) <= 1:
                break

            # Collect endpoints per component
            comp_endpoints = []
            for comp in components:
                eps = set()
                for idx in comp:
                    seg = segs[idx]
                    lyr = seg[4]
                    if lyr == -1:
                        eps.add((seg[0], seg[1]))
                    else:
                        eps.add((seg[0], seg[1]))
                        eps.add((seg[2], seg[3]))
                comp_endpoints.append(eps)

            # Find closest pair of components and A* route between them
            bridged = False
            best_dist = float('inf')
            best_start = best_end = None

            for ci in range(len(components)):
                for cj in range(ci + 1, len(components)):
                    for pi in comp_endpoints[ci]:
                        for pj in comp_endpoints[cj]:
                            d = abs(pi[0] - pj[0]) + abs(pi[1] - pj[1])
                            if d < best_dist:
                                best_dist = d
                                best_start = pi
                                best_end = pj

            if best_start and best_end:
                g_start = self.to_grid(best_start[0], best_start[1])
                g_end = self.to_grid(best_end[0], best_end[1])

                # Temporarily remove own-net used cells so A* can reach
                # through same-net wires.  Only remove cells directly ON
                # segments (no margin expansion) — margin cells may protect
                # OTHER nets and must not be removed.
                own_used = set()
                for seg in segs:
                    if seg[4] == -1:
                        continue
                    lyr = seg[4]
                    gx1, gy1 = self.to_grid(min(seg[0], seg[2]),
                                            min(seg[1], seg[3]))
                    gx2, gy2 = self.to_grid(max(seg[0], seg[2]),
                                            max(seg[1], seg[3]))
                    for gx in range(gx1, gx2 + 1):
                        for gy in range(gy1, gy2 + 1):
                            cell = (gx, gy, lyr)
                            if cell in self.used:
                                own_used.add(cell)

                self.used -= own_used

                path = self._astar(g_start, {g_end})
                if path:
                    bridge_segs = self._simplify(path)
                    segs.extend(bridge_segs)
                    added += len(bridge_segs)
                    bridged = True
                else:
                    nm_s = self.to_nm(g_start[0], g_start[1])
                    nm_e = self.to_nm(g_end[0], g_end[1])
                    bl_s = any((g_start[0], g_start[1], l) in self.blocked
                               for l in range(N_ROUTING_LAYERS))
                    bl_e = any((g_end[0], g_end[1], l) in self.blocked
                               for l in range(N_ROUTING_LAYERS))
                    print(f'    Router: {net_name} A* failed '
                          f'({nm_s[0]/1000:.1f},{nm_s[1]/1000:.1f})->'
                          f'({nm_e[0]/1000:.1f},{nm_e[1]/1000:.1f}) '
                          f'bl=({bl_s},{bl_e}) cleared={len(own_used)}')

                # Restore own-net used cells + mark new path
                self.used |= own_used
                if path:
                    self._mark_used(path)

            if not bridged:
                if len(components) > 1:
                    print(f'    Router: {net_name} reconnect stuck at '
                          f'{len(components)} components (iter {_iteration})')
                break

        if added:
            print(f'    Router: bridged {added} segment(s) for {net_name}')
        return segs

    def _bridge_crosses_used(self, p1, p2, layer):
        """Check if a bridge from p1 to p2 would cross any used cell."""
        # Check L-shaped path: horizontal then vertical
        if p1[0] == p2[0] and p1[1] == p2[1]:
            return False
        # Build list of bridge segments (manhattan)
        bridge_segs = []
        if p1[0] == p2[0] or p1[1] == p2[1]:
            bridge_segs.append((p1[0], p1[1], p2[0], p2[1]))
        else:
            bridge_segs.append((p1[0], p1[1], p2[0], p1[1]))
            bridge_segs.append((p2[0], p1[1], p2[0], p2[1]))
        margin = MAZE_MARGIN
        for x1, y1, x2, y2 in bridge_segs:
            gx1, gy1 = self.to_grid(min(x1, x2), min(y1, y2))
            gx2, gy2 = self.to_grid(max(x1, x2), max(y1, y2))
            for gx in range(gx1 - margin, gx2 + margin + 1):
                for gy in range(gy1 - margin, gy2 + margin + 1):
                    if (gx, gy, layer) in self.used:
                        return True
                    if (gx, gy, layer) in self.blocked:
                        return True
        return False

    def _bridge_fragments(self, net_name, segs):
        """Bridge disconnected sub-route fragments on the same layer.

        The maze router creates separate paths for each pin-to-pin connection.
        After simplification to nm segments, nearby endpoints on the same layer
        may not share exact coordinates.  This pass finds such pairs and adds
        short bridge segments (same-net, no DRC spacing rule applies).
        """
        from collections import defaultdict
        from shapely.geometry import box as sbox
        from shapely.ops import unary_union

        WIRE_W = M2_SIG_W  # 300 nm — same for M1 and M2
        BRIDGE_THRESHOLD = 5000  # nm — generous; same-net has no min-space

        def _seg_box(seg, hw):
            x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
            return sbox(min(x1, x2) - hw, min(y1, y2) - hw,
                        max(x1, x2) + hw, max(y1, y2) + hw)

        def _build_components(segs):
            pt_seg = defaultdict(set)
            for i, seg in enumerate(segs):
                x1, y1, x2, y2, layer = seg
                if layer == -1:
                    for lyr in range(N_ROUTING_LAYERS):
                        pt_seg[(x1, y1, lyr)].add(i)
                else:
                    pt_seg[(x1, y1, layer)].add(i)
                    pt_seg[(x2, y2, layer)].add(i)
            n = len(segs)
            adj = [set() for _ in range(n)]
            for indices in pt_seg.values():
                idx_list = list(indices)
                for a in idx_list:
                    for b in idx_list:
                        if a != b:
                            adj[a].add(b)
            visited = [False] * n
            components = []
            for start in range(n):
                if visited[start]:
                    continue
                comp = []
                stack = [start]
                while stack:
                    node = stack.pop()
                    if visited[node]:
                        continue
                    visited[node] = True
                    comp.append(node)
                    for nb in adj[node]:
                        if not visited[nb]:
                            stack.append(nb)
                components.append(comp)
            return components

        hw = WIRE_W / 2
        added = 0
        for _iteration in range(10):
            components = _build_components(segs)
            if len(components) <= 1:
                break

            comp_shapes = {}
            for ci, comp in enumerate(components):
                shapes = {lyr: [] for lyr in range(N_ROUTING_LAYERS)}
                for idx in comp:
                    seg = segs[idx]
                    layer = seg[4]
                    if layer in range(N_ROUTING_LAYERS):
                        shapes[layer].append(_seg_box(seg, hw))
                comp_shapes[ci] = shapes

            merged = False
            for ci in range(len(components)):
                if merged:
                    break
                for cj in range(ci + 1, len(components)):
                    if merged:
                        break
                    for layer in range(N_ROUTING_LAYERS):
                        si = comp_shapes[ci][layer]
                        sj = comp_shapes[cj][layer]
                        if not si or not sj:
                            continue
                        ui = unary_union(si)
                        uj = unary_union(sj)
                        if ui.distance(uj) > BRIDGE_THRESHOLD:
                            continue
                        candidates = []
                        for idx_i in components[ci]:
                            seg_i = segs[idx_i]
                            if seg_i[4] != layer:
                                continue
                            for pt_i in ((seg_i[0], seg_i[1]),
                                         (seg_i[2], seg_i[3])):
                                for idx_j in components[cj]:
                                    seg_j = segs[idx_j]
                                    if seg_j[4] != layer:
                                        continue
                                    for pt_j in ((seg_j[0], seg_j[1]),
                                                 (seg_j[2], seg_j[3])):
                                        d = abs(pt_i[0] - pt_j[0]) + \
                                            abs(pt_i[1] - pt_j[1])
                                        candidates.append((d, pt_i, pt_j, layer))
                        candidates.sort()
                        best_pair = None
                        best_d = float('inf')
                        for d, pt_i, pt_j, lyr_c in candidates:
                            if self._bridge_crosses_used(pt_i, pt_j, lyr_c):
                                continue
                            best_d = d
                            best_pair = (pt_i, pt_j, lyr_c)
                            break
                        if best_pair and best_d > 0:
                            p1, p2, lyr = best_pair
                            if p1[0] == p2[0] or p1[1] == p2[1]:
                                segs.append((p1[0], p1[1],
                                             p2[0], p2[1], lyr))
                                added += 1
                            else:
                                segs.append((p1[0], p1[1],
                                             p2[0], p1[1], lyr))
                                segs.append((p2[0], p1[1],
                                             p2[0], p2[1], lyr))
                                added += 2
                            merged = True
                        elif candidates:
                            # All direct bridges cross used/blocked cells.
                            # Use A* to find a collision-free path (any layer).
                            for _, pt_i, pt_j, lyr_c in candidates[:5]:
                                g_start = self.to_grid(pt_i[0], pt_i[1])
                                g_end = self.to_grid(pt_j[0], pt_j[1])
                                # Try same layer first, then any layer
                                path = self._astar(g_start, {g_end},
                                                   start_layer=lyr_c)
                                if not path:
                                    path = self._astar(g_start, {g_end})
                                if path:
                                    bridge_segs = self._simplify(path)
                                    segs.extend(bridge_segs)
                                    self._mark_used(path)
                                    added += len(bridge_segs)
                                    merged = True
                                    break
                            if not merged:
                                merged = True  # give up on this pair

            if not merged:
                break

        if added:
            print(f'    Router: bridged {added} fragment(s) for {net_name}')
        return segs

    def _mark_segments_used(self, segs):
        """Mark nm-coordinate segments as used on the grid (for bridges).

        Converts each segment to grid cells along its length and marks
        them + MAZE_MARGIN, same as _mark_used does for path cells.
        Via segments (layer == -1) are marked on both layers without
        pin_terminal exemption (wider pads).
        """
        margin = MAZE_MARGIN
        for seg in segs:
            x1, y1, x2, y2, layer = seg
            if layer == -1:
                self._mark_via_used(x1, y1)
                continue
            gx1, gy1 = self.to_grid(min(x1, x2), min(y1, y2))
            gx2, gy2 = self.to_grid(max(x1, x2), max(y1, y2))
            for gx in range(gx1, gx2 + 1):
                for gy in range(gy1, gy2 + 1):
                    for dx in range(-margin, margin + 1):
                        for dy in range(-margin, margin + 1):
                            nx, ny = gx + dx, gy + dy
                            if (dx != 0 or dy != 0) and (nx, ny) in self.pin_terminals:
                                continue
                            self.used.add((nx, ny, layer))

    def _mark_via_used(self, x_nm, y_nm, layer=None):
        """Mark a via position with margin on ALL adjacent layers (no pin exemption).

        Via pads are wider than signal wires. At 1-cell distance, via pad
        overlaps adjacent wire. So via margins must NOT exempt pin_terminals.

        If layer is given, marks that layer + its _VIA_NEIGHBORS.
        If None, marks bottom two routing layers (layer 0 + layer 1).
        """
        gx, gy = self.to_grid(x_nm, y_nm)
        margin = MAZE_MARGIN
        if layer is not None:
            layers_to_mark = [layer] + list(_VIA_NEIGHBORS.get(layer, ()))
        else:
            # Default: mark bottom two layers (Via3 junction: M3+M4)
            layers_to_mark = [M1_LYR, M2_LYR]
        for dx in range(-margin, margin + 1):
            for dy in range(-margin, margin + 1):
                for lyr in layers_to_mark:
                    self.used.add((gx + dx, gy + dy, lyr))

    def _mark_used(self, path):
        """Mark path cells + margin as used (enforces DRC spacing).

        Wire cells: margin=MAZE_MARGIN, skips pin_terminals so adjacent
        pins on different nets remain routable.

        Via cells: margin=MAZE_MARGIN on BOTH layers, NO pin_terminal
        exemption (via pads are wider than wires — overlap at 1-cell distance).
        """
        margin = MAZE_MARGIN

        via_cells = set()
        for k in range(len(path) - 1):
            if path[k][:2] == path[k+1][:2] and path[k][2] != path[k+1][2]:
                via_cells.add(path[k][:2])

        for gx, gy, layer in path:
            is_via = (gx, gy) in via_cells

            for dx in range(-margin, margin + 1):
                for dy in range(-margin, margin + 1):
                    nx, ny = gx + dx, gy + dy
                    # Via pads span both layers at full width — no pin exemption
                    if not is_via and (dx != 0 or dy != 0) and (nx, ny) in self.pin_terminals:
                        continue
                    self.used.add((nx, ny, layer))
                    if is_via:
                        for adj_lyr in _VIA_NEIGHBORS.get(layer, ()):
                            self.used.add((nx, ny, adj_lyr))

    def _simplify(self, path):
        """Convert grid path to drawable segments."""
        if len(path) < 2:
            return []
        segs = []
        start = path[0]
        prev = path[0]
        prev_dir = None

        for cur in path[1:]:
            d = (cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2])
            if d[2] != 0:  # layer change
                if start[:2] != prev[:2]:
                    x1, y1 = self.to_nm(*start[:2])
                    x2, y2 = self.to_nm(*prev[:2])
                    segs.append((x1, y1, x2, y2, start[2]))
                vx, vy = self.to_nm(*cur[:2])
                # Encode via type from layer transition:
                # M1↔M2 = -1 (Via1), M2↔M3 = -2 (Via2), M3↔M4 = -3 (Via3)
                _lo_lyr = min(prev[2], cur[2])
                _via_code = -1 - _lo_lyr  # M1(0)→-1, M2(1)→-2, M3(2)→-3
                segs.append((vx, vy, vx, vy, _via_code))
                start = cur
                prev_dir = None
            else:
                xy_dir = (d[0], d[1])
                if prev_dir is not None and xy_dir != prev_dir:
                    x1, y1 = self.to_nm(*start[:2])
                    x2, y2 = self.to_nm(*prev[:2])
                    segs.append((x1, y1, x2, y2, start[2]))
                    start = prev
                prev_dir = xy_dir
            prev = cur

        if start[:2] != prev[:2]:
            x1, y1 = self.to_nm(*start[:2])
            x2, y2 = self.to_nm(*prev[:2])
            segs.append((x1, y1, x2, y2, start[2]))
        return segs
