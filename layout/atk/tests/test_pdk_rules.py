"""PDK rule self-consistency tests.

Every derived value and routing parameter must satisfy DRC rules.
These tests catch parameter regressions at CI time, not at DRC time.
"""

from atk.pdk import (
    M1_MIN_W, M1_MIN_S, M1_VIA_ENC,
    M2_MIN_W, M2_MIN_S, M2_VIA_ENC,
    V1_SIZE, V1_MIN_S,
    VIA1_PAD, VIA1_PAD_MIN, VIA1_SZ,
    M1_SIG_W, M2_SIG_W, M1_PWR_W, M2_PWR_W,
    VIA_CLEAR,
    MAZE_GRID, MAZE_MARGIN,
)


class TestViaEnclosure:
    """Bug 2026-03-01: VIA1_PAD=400nm gave M2 enclosure=105nm < M2.d=144nm.
    15 V1.a violations. Fixed to 480nm."""

    def test_m2_enclosure(self):
        enc = (VIA1_PAD - V1_SIZE) / 2
        assert enc >= M2_VIA_ENC, (
            f"M2 enclosure {enc}nm < M2.d={M2_VIA_ENC}nm"
        )

    def test_m1_enclosure(self):
        enc = (VIA1_PAD - V1_SIZE) / 2
        assert enc >= M1_VIA_ENC, (
            f"M1 enclosure {enc}nm < M1.d={M1_VIA_ENC}nm"
        )

    def test_pad_min_derived(self):
        assert VIA1_PAD_MIN == V1_SIZE + 2 * M2_VIA_ENC

    def test_pad_ge_min(self):
        assert VIA1_PAD >= VIA1_PAD_MIN


class TestWireWidths:
    """Signal wire widths must satisfy minimum width rules."""

    def test_m1_signal_width(self):
        assert M1_SIG_W >= M1_MIN_W

    def test_m2_signal_width(self):
        assert M2_SIG_W >= M2_MIN_W

    def test_m1_power_width(self):
        assert M1_PWR_W >= M1_MIN_W

    def test_m2_power_width(self):
        assert M2_PWR_W >= M2_MIN_W


class TestMazeRouterSpacing:
    """Bug 2026-03-01: _mark_used had margin=0, adjacent routes at 200nm
    center-to-center with 300nm wires → 100nm overlap. 97 M2.b violations.
    Fixed with GRID=350nm, margin=1 → 700nm center-to-center."""

    def test_m2_spacing(self):
        cc = (MAZE_MARGIN + 1) * MAZE_GRID
        gap = cc - M2_SIG_W
        assert gap >= M2_MIN_S, (
            f"M2 gap {gap}nm < M2.b={M2_MIN_S}nm "
            f"(cc={cc}, wire={M2_SIG_W})"
        )

    def test_m1_spacing(self):
        cc = (MAZE_MARGIN + 1) * MAZE_GRID
        gap = cc - M1_SIG_W
        assert gap >= M1_MIN_S, (
            f"M1 gap {gap}nm < M1.b={M1_MIN_S}nm"
        )

    def test_via_pad_spacing(self):
        cc = (MAZE_MARGIN + 1) * MAZE_GRID
        gap = cc - VIA1_PAD
        assert gap >= V1_MIN_S, (
            f"Via pad gap {gap}nm < V1.b={V1_MIN_S}nm"
        )

    def test_grid_divides_cleanly(self):
        """Grid should produce coordinates on 5nm manufacturing grid."""
        # GRID * n should be divisible by 5 for any integer n
        assert MAZE_GRID % 5 == 0, f"GRID={MAZE_GRID} not on 5nm grid"
