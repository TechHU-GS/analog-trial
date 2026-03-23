"""Common PCell utilities for module builders.

Usage:
    from pcell_utils import create_nmos, create_pmos, probe_device, place_device, box
"""

import klayout.db as pya

# Layer definitions (IHP SG13G2)
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
M1 = (8, 0)
M2 = (10, 0)
PSD = (14, 0)
NSD = (7, 0)
NWELL = (31, 0)
VIA1 = (19, 0)

# DRC values (nm)
M1_W = 160
M1_S = 180
M2_W = 210
M2_S = 210
VIA1_SZ = 190
CONT_SZ = 160


def box(x1, y1, x2, y2):
    return pya.Box(x1, y1, x2, y2)


def create_nmos(ly, w_um, l_um, ng=1):
    """Create NMOS PCell. Returns cell object."""
    return ly.create_cell("nmos", "SG13_dev", {
        "l": l_um * 1e-6, "w": w_um * 1e-6, "ng": ng
    })


def create_pmos(ly, w_um, l_um, ng=1):
    """Create PMOS PCell. Returns cell object."""
    return ly.create_cell("pmos", "SG13_dev", {
        "l": l_um * 1e-6, "w": w_um * 1e-6, "ng": ng
    })


def probe_device(ly, pcell):
    """Probe PCell geometry. Returns dict with bbox, strips (M1 S/D), gates."""
    bb = pcell.bbox()
    info = {'bbox': bb, 'w': bb.width(), 'h': bb.height()}

    # M1 strips (tall narrow rectangles = S/D)
    li_m1 = ly.find_layer(*M1)
    strips = []
    if li_m1 is not None:
        for si in pcell.begin_shapes_rec(li_m1):
            b = si.shape().bbox()
            if b.height() > 500:
                strips.append(b)
    strips.sort(key=lambda b: b.left)
    info['strips'] = strips

    # Gate poly (tall rectangles crossing active)
    li_gat = ly.find_layer(*GATPOLY)
    gates = []
    if li_gat is not None:
        for si in pcell.begin_shapes_rec(li_gat):
            b = si.shape().bbox()
            if b.height() > 500:
                gates.append(b)
    gates.sort(key=lambda b: b.left)
    info['gates'] = gates

    return info


def place_device(cell, pcell, x, y, flip_x=False):
    """Place PCell instance at (x, y) in nm. Returns instance.
    flip_x: mirror in X (for complementary pairs).
    Origin is placed at PCell bbox bottom-left + offset.
    """
    bb = pcell.bbox()
    if flip_x:
        # Mirror: place right edge at x
        ox = x + bb.right
        trans = pya.Trans(pya.Trans.M0, ox, y - bb.bottom)
    else:
        ox = x - bb.left
        oy = y - bb.bottom
        trans = pya.Trans(0, False, ox, oy)
    return cell.insert(pya.CellInstArray(pcell.cell_index(), trans))


def abs_strips(info, x, y, flip_x=False):
    """Get absolute strip positions after placement at (x,y).
    Returns list of (xl, xr, yb, yt) tuples.
    """
    bb = info['bbox']
    result = []
    for s in info['strips']:
        if flip_x:
            # Mirror: new_x = x + (bb.right - s.right) for left edge
            xl = x + bb.right - s.right
            xr = x + bb.right - s.left
        else:
            xl = s.left - bb.left + x
            xr = s.right - bb.left + x
        yb = s.bottom - bb.bottom + y
        yt = s.top - bb.bottom + y
        result.append((xl, xr, yb, yt))
    if flip_x:
        result.sort(key=lambda t: t[0])
    return result


def abs_gates(info, x, y, flip_x=False):
    """Get absolute gate positions after placement. Returns list of (xl, xr, yb, yt)."""
    bb = info['bbox']
    result = []
    for g in info['gates']:
        if flip_x:
            xl = x + bb.right - g.right
            xr = x + bb.right - g.left
        else:
            xl = g.left - bb.left + x
            xr = g.right - bb.left + x
        yb = g.bottom - bb.bottom + y
        yt = g.top - bb.bottom + y
        result.append((xl, xr, yb, yt))
    if flip_x:
        result.sort(key=lambda t: t[0])
    return result


def add_ptap(cell, ly, cx, y1, y2):
    """Add a ptap tie at center x, y range."""
    cell.shapes(ly.layer(*ACTIV)).insert(box(cx - 250, y1, cx + 250, y2))
    cell.shapes(ly.layer(*M1)).insert(box(cx - 250, y1, cx + 250, y2))
    cell.shapes(ly.layer(*PSD)).insert(box(cx - 350, y1 - 100, cx + 350, y2 + 100))
    cell.shapes(ly.layer(*CONT)).insert(box(cx - 80, (y1 + y2) // 2 - 80,
                                            cx + 80, (y1 + y2) // 2 + 80))


def add_ntap(cell, ly, cx, y1, y2):
    """Add an ntap tie at center x, y range. Caller must ensure NWell coverage."""
    cell.shapes(ly.layer(*ACTIV)).insert(box(cx - 250, y1, cx + 250, y2))
    cell.shapes(ly.layer(*M1)).insert(box(cx - 250, y1, cx + 250, y2))
    cell.shapes(ly.layer(*CONT)).insert(box(cx - 80, (y1 + y2) // 2 - 80,
                                            cx + 80, (y1 + y2) // 2 + 80))


def quick_drc(ly, cell):
    """Run quick M1/M2 DRC on cell. Returns (m1_space, m1_width, m2_space, m2_width)."""
    flat = ly.create_cell('_drc_tmp')
    flat.copy_tree(cell)
    flat.flatten(True)

    li_m1 = ly.find_layer(*M1)
    m1r = pya.Region(flat.begin_shapes_rec(li_m1))
    m1s = m1r.space_check(M1_S).count()
    m1w = m1r.width_check(M1_W).count()

    m2s = m2w = 0
    li_m2 = ly.find_layer(*M2)
    if li_m2 is not None:
        m2r = pya.Region(flat.begin_shapes_rec(li_m2))
        m2s = m2r.space_check(M2_S).count()
        m2w = m2r.width_check(M2_W).count()

    flat.delete()
    print(f'  Quick DRC: M1.b={m1s} M1.a={m1w} M2.b={m2s} M2.a={m2w}')
    return m1s, m1w, m2s, m2w
