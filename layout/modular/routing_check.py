"""Pre-route DRC check using KLayout Region API (no external dependencies).

Checks proposed new shapes for spacing violations and parasitic risks
BEFORE inserting into the layout.

Usage in route_*.py:
    from routing_check import RouteChecker
    rc = RouteChecker(ly, cell)
    # Before inserting M1:
    ok, issues = rc.check_m1(x1, y1, x2, y2)
    # Before inserting Poly:
    ok, issues = rc.check_poly_parasitic(x1, y1, x2, y2)
    # Insert only if safe:
    rc.safe_insert(cell, ly, (8,0), x1, y1, x2, y2, label='gnd_stub')
"""
import klayout.db as pya


def _get_region(cell, ly, layer_num, layer_dt=0):
    """Extract merged Region from flattened cell."""
    li = ly.find_layer(layer_num, layer_dt)
    if li is None:
        return pya.Region()
    flat = ly.create_cell('_rc')
    flat.copy_tree(cell)
    flat.flatten(True)
    r = pya.Region(flat.begin_shapes_rec(li)).merged()
    flat.delete()
    return r


class RouteChecker:
    """Pre-route DRC checker using KLayout Region operations."""

    M1_SPACING = 180   # nm
    M2_SPACING = 210
    POLY_SPACING = 180

    def __init__(self, ly, cell):
        self.ly = ly
        self.cell = cell
        self.m1 = _get_region(cell, ly, 8, 0)
        self.m2 = _get_region(cell, ly, 10, 0)
        self.active = _get_region(cell, ly, 1, 0)
        self.poly = _get_region(cell, ly, 5, 0)
        print(f'  RouteChecker: M1={self.m1.count()} M2={self.m2.count()} '
              f'Active={self.active.count()} Poly={self.poly.count()}')

    def check_m1(self, x1, y1, x2, y2):
        """Check M1 spacing. Returns (ok, issues)."""
        return self._check_spacing(x1, y1, x2, y2, self.m1, 'M1', self.M1_SPACING)

    def check_m2(self, x1, y1, x2, y2):
        """Check M2 spacing. Returns (ok, issues)."""
        return self._check_spacing(x1, y1, x2, y2, self.m2, 'M2', self.M2_SPACING)

    def check_poly_parasitic(self, x1, y1, x2, y2):
        """Check if proposed Poly crosses Active (parasitic MOSFET risk).
        Returns (ok, issues).
        """
        new_r = pya.Region(pya.Box(min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2)))
        issues = []

        if self.active.count() == 0:
            return True, issues

        # Does new poly overlap Active?
        overlap = (new_r & self.active)
        if overlap.is_empty():
            return True, issues

        # Key check: does new poly MERGE previously separate gates in Active?
        # If poly-in-Active polygon count decreases, gates are being merged → parasitic
        merged = (self.poly | new_r).merged()
        merged_in_active = (merged & self.active)
        orig_in_active = (self.poly & self.active)

        orig_count = orig_in_active.count()
        new_count = merged_in_active.count()

        if new_count < orig_count:
            ob = overlap.bbox()
            issues.append(
                f'PARASITIC: Poly merges {orig_count - new_count} gate(s) in Active at '
                f'({ob.left/1000:.1f},{ob.bottom/1000:.1f})-'
                f'({ob.right/1000:.1f},{ob.top/1000:.1f}), '
                f'poly-in-Active count {orig_count}→{new_count}'
            )

        return len(issues) == 0, issues

    def _check_spacing(self, x1, y1, x2, y2, existing, layer_name, min_spacing):
        """Check minimum spacing between proposed shape and existing shapes."""
        new_r = pya.Region(pya.Box(min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2)))
        issues = []

        if existing.is_empty():
            return True, issues

        # Merge new with existing, then run space_check
        combined = (existing | new_r)
        violations = combined.space_check(min_spacing)

        # Filter: only violations involving the new shape's area
        new_box = pya.Box(min(x1,x2)-min_spacing, min(y1,y2)-min_spacing,
                          max(x1,x2)+min_spacing, max(y1,y2)+min_spacing)
        for ep in violations.each():
            if ep.bbox().overlaps(new_box):
                b = ep.bbox()
                issues.append(
                    f'{layer_name}.spacing: violation at '
                    f'({b.left/1000:.1f},{b.bottom/1000:.1f})-'
                    f'({b.right/1000:.1f},{b.top/1000:.1f})'
                )

        return len(issues) == 0, issues

    def safe_insert(self, cell, ly, layer_spec, x1, y1, x2, y2, label=''):
        """Insert shape only if DRC-safe. Returns True if inserted."""
        layer_name = {(8,0): 'M1', (10,0): 'M2', (5,0): 'Poly'}.get(layer_spec, '?')

        if layer_name == 'Poly':
            ok, issues = self.check_poly_parasitic(x1, y1, x2, y2)
        elif layer_name in ('M1', 'M2'):
            ok, issues = self._check_spacing(
                x1, y1, x2, y2,
                self.m1 if layer_name == 'M1' else self.m2,
                layer_name,
                self.M1_SPACING if layer_name == 'M1' else self.M2_SPACING)
        else:
            ok, issues = True, []

        if not ok:
            for iss in issues:
                print(f'  ⚠ {label}: {iss}')
            return False

        b = pya.Box(min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2))
        cell.shapes(ly.layer(*layer_spec)).insert(b)
        # Update cached region
        if layer_name == 'M1':
            self.m1 = (self.m1 | pya.Region(b)).merged()
        elif layer_name == 'M2':
            self.m2 = (self.m2 | pya.Region(b)).merged()
        elif layer_name == 'Poly':
            self.poly = (self.poly | pya.Region(b)).merged()
        return True
