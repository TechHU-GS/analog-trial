# TTIHP IHP Analog Tile Integration -- Complete Geometry Reference

## 1. Tile Dimensions (1x2 IHP Analog)

| Parameter | Value (um) | Value (nm / DEF units) |
|-----------|-----------|----------------------|
| **Width** | 202.080 | 202,080 |
| **Height** | 313.740 | 313,740 |
| **DIEAREA** | (0, 0) to (202.080, 313.740) | (0, 0) to (202080, 313740) |

---

## 2. prBoundary Layer

**GDS layer/datatype assignments** (from `sg13g2.lyp` and `check_abutment.py`):

| Purpose | GDS Layer | Datatype | Name |
|---------|-----------|----------|------|
| **prBoundary.drawing** | **189** | **0** | `189/0` |
| **prBoundary.label** | **189** | **1** | `189/1` |
| **prBoundary.boundary** | **189** | **4** | `189/4` |

**Source files confirming this**:
- `/Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp` (lines 5663-5697)
- `/Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.qa/stdcells/check_abutment.py` line 38: `cell.get_polygons(layer=189, datatype=4)` with comment `# prBoundary.bnd (189,4)`
- `/Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2-cifout.tech` line 47: `calma 189 4`
- DRC layers_def.drc line 1461: `prboundary_drw = get_polygons(189, 0)`
- LVS layers_definitions.lvs line 1470: `prboundary_drw = get_polygons(189, 0)`

**Note**: tt-support-tools precheck references `prBoundary.boundary` by name; the actual GDS layer used for boundary checking is **189/4** (`.boundary` subtype). The DRC/LVS scripts use **189/0** (`.drawing` subtype).

---

## 3. Complete GDS Layer Map (IHP SG13G2)

### Metal Stack

| Layer Name | GDS Layer | Datatype (drawing) | pin (dt=2) | label (dt=1) |
|------------|-----------|--------------------|-----------:|-------------:|
| **Metal1** | **8** | 0 | 8/2 | 8/1 |
| **Metal2** | **10** | 0 | 10/2 | 10/1 |
| **Metal3** | **30** | 0 | 30/2 | 30/1 |
| **Metal4** | **50** | 0 | 50/2 | 50/1 |
| **Metal5** | **67** | 0 | 67/2 | 67/1 |
| **TopVia1** | **125** | 0 | - | - |
| **TopMetal1** | **126** | 0 | 126/2 | 126/1 |
| **TopMetal2** | **134** | 0 | 134/2 | 134/1 |

### Valid LEF Port Layers (from precheck `tech_data.py`)

```python
"ihp-sg13g2": {
    "Metal1.pin": (8, 2),
    "Metal2.pin": (10, 2),
    "Metal3.pin": (30, 2),
    "Metal4.pin": (50, 2),
    "Metal5.pin": (67, 2),
    "TopMetal1.pin": (126, 2),
}
```

---

## 4. Analog Pin Geometry (ua[0] - ua[7])

### DEF Pin Definition
- **Layer**: TopMetal1
- **GDS**: 126/0 (drawing), 126/2 (pin)
- **Pin rectangle (relative)**: (-875, -1000) to (875, 1000) = **1.75 um wide x 2.0 um tall**
- **Located at bottom edge** (y_center = 1000 nm = 1.0 um from bottom)
- **Direction**: INOUT

### Exact Pin Positions (DEF PLACED coordinates, in nm)

| Pin | x_center (nm) | y_center (nm) | Absolute rect (nm) |
|-----|---------------|---------------|---------------------|
| ua[0] | 191,040 | 1,000 | (190165, 0) to (191915, 2000) |
| ua[1] | 166,560 | 1,000 | (165685, 0) to (167435, 2000) |
| ua[2] | 142,080 | 1,000 | (141205, 0) to (142955, 2000) |
| ua[3] | 117,600 | 1,000 | (116725, 0) to (118475, 2000) |
| ua[4] | 93,120 | 1,000 | (92245, 0) to (93995, 2000) |
| ua[5] | 68,640 | 1,000 | (67765, 0) to (69515, 2000) |
| ua[6] | 44,160 | 1,000 | (43285, 0) to (45035, 2000) |
| ua[7] | 19,680 | 1,000 | (18805, 0) to (20555, 2000) |

**Pin spacing**: 24,480 nm (24.48 um) between adjacent ua pins.

### Precheck Formula (from `tech_data.py`)
```python
# ihp-sg13g2 analog pin rects
pin_layer = (126, 0)    # TopMetal1.drawing
via_layers = [(125, 0)]  # TopVia1.drawing
for pin_number in range(8):
    x1, y1 = 190.165 - 24.48 * pin_number, 0.0
    x2, y2 = x1 + 1.75, y1 + 2.0
    # rect = ((x1, y1), (x2, y2))  in microns
```

---

## 5. Digital Pin Geometry (ui_in, uo_out, uio_in, uio_out, uio_oe, clk, ena, rst_n)

### DEF Pin Definition
- **Layer**: Metal4
- **GDS**: 50/0 (drawing), 50/2 (pin)
- **Pin rectangle (relative)**: (-150, -500) to (150, 500) = **0.3 um wide x 1.0 um tall**
- **Located at TOP edge** (y_center = 313,240 nm = 313.24 um, i.e. 500 nm from top boundary)
- **Direction**: INPUT (for ui_in, uio_in, clk, ena, rst_n) or OUTPUT (for uo_out, uio_out, uio_oe)
- **Digital pins DO require actual metal geometry** (Metal4 rectangles), not just labels

### Exact Pin Positions (DEF PLACED coordinates, in nm)

**Control signals:**
| Pin | x_center | y_center |
|-----|----------|----------|
| clk | 187,200 | 313,240 |
| ena | 191,040 | 313,240 |
| rst_n | 183,360 | 313,240 |

**ui_in[7:0] (right to left from top-right corner):**
| Pin | x_center |
|-----|----------|
| ui_in[0] | 179,520 |
| ui_in[1] | 175,680 |
| ui_in[2] | 171,840 |
| ui_in[3] | 168,000 |
| ui_in[4] | 164,160 |
| ui_in[5] | 160,320 |
| ui_in[6] | 156,480 |
| ui_in[7] | 152,640 |

**uio_in[7:0]:**
| Pin | x_center |
|-----|----------|
| uio_in[0] | 148,800 |
| uio_in[1] | 144,960 |
| uio_in[2] | 141,120 |
| uio_in[3] | 137,280 |
| uio_in[4] | 133,440 |
| uio_in[5] | 129,600 |
| uio_in[6] | 125,760 |
| uio_in[7] | 121,920 |

**uo_out[7:0]:**
| Pin | x_center |
|-----|----------|
| uo_out[0] | 118,080 |
| uo_out[1] | 114,240 |
| uo_out[2] | 110,400 |
| uo_out[3] | 106,560 |
| uo_out[4] | 102,720 |
| uo_out[5] | 98,880 |
| uo_out[6] | 95,040 |
| uo_out[7] | 91,200 |

**uio_out[7:0]:**
| Pin | x_center |
|-----|----------|
| uio_out[0] | 87,360 |
| uio_out[1] | 83,520 |
| uio_out[2] | 79,680 |
| uio_out[3] | 75,840 |
| uio_out[4] | 72,000 |
| uio_out[5] | 68,160 |
| uio_out[6] | 64,320 |
| uio_out[7] | 60,480 |

**uio_oe[7:0]:**
| Pin | x_center |
|-----|----------|
| uio_oe[0] | 56,640 |
| uio_oe[1] | 52,800 |
| uio_oe[2] | 48,960 |
| uio_oe[3] | 45,120 |
| uio_oe[4] | 41,280 |
| uio_oe[5] | 37,440 |
| uio_oe[6] | 33,600 |
| uio_oe[7] | 29,760 |

**Digital pin spacing**: 3,840 nm (3.84 um) between adjacent digital pins.

---

## 6. Power Stripes (VDPWR / VGND)

### Key Finding: DEF has NO routed power geometry
The DEF template `tt_analog_1x2.def` only declares SPECIALNETS with USE GROUND/POWER but contains **no routed metal segments**. Power stripes must be drawn by the user.

### Magic TCL Script Power Stripe Configuration

From `magic_init_project.tcl`:

```tcl
set POWER_STRIPE_WIDTH 2.4um    ;# Minimum width is 2.1um
set POWER_STRIPES {
    VDPWR 1um      ;# x position
    VGND  6um      ;# x position
}
# Min spacing between stripes: 1.64um

# Stripes are drawn on met6 (= TopMetal1 in Magic's IHP tech mapping)
# Vertical extent: from y=5um to y=308um
# Stripe is VERTICAL (runs N-S)
box $x 5um $x 308um
box width $POWER_STRIPE_WIDTH
paint met6                       ;# met6 = TopMetal1 (GDS 126/0)
```

### Power Stripe Specs Summary

| Parameter | Value |
|-----------|-------|
| **Layer** | TopMetal1 (GDS 126/0, Magic: met6) |
| **Direction** | **Vertical** (running bottom-to-top) |
| **Minimum width** | 2.1 um (precheck), 2.4 um (template default) |
| **Min spacing** | 1.64 um between stripes |
| **Default VDPWR x** | 1.0 um (left edge of stripe) |
| **Default VGND x** | 6.0 um (left edge of stripe) |
| **Y extent** | 5.0 um to 308.0 um (303 um tall) |
| **Not extending to edges** | 5 um gap from bottom, 5.74 um gap from top |

### Precheck Requirements (from `tech_data.py`)
```python
power_pins_layer = {"ihp-sg13g2": "TopMetal1"}
power_pins_min_width = {"ihp-sg13g2": 2100}  # 2100 nm = 2.1 um minimum
```

---

## 7. Forbidden Layers

```python
forbidden_layers = {
    "ihp-sg13g2": [
        "TopMetal2.drawing",   # GDS 134/0
        "TopMetal2.pin",       # GDS 134/2
        "TopMetal2.label",     # GDS 134/1
    ],
}
```

**TopMetal2 (GDS 134) is FORBIDDEN** -- used by TinyTapeout's power grid, similar to how met5 is forbidden on Sky130.

---

## 8. Row and Track Geometry

### Rows
- 81 rows (ROW_0 through ROW_80)
- CoreSite, starting at x=2880, alternating N/FS orientation
- First row y = 3,780; subsequent rows increment by 3,780 nm
- 409 cells per row, step = 480 nm

### Tracks

| Layer | X pitch (nm) | Y pitch (nm) | X start | X count | Y start | Y count |
|-------|-------------|-------------|---------|---------|---------|---------|
| Metal1 | 480 | 420 | 480 | 420 | 420 | 746 |
| Metal2 | 480 | 420 | 480 | 420 | 420 | 746 |
| Metal3 | 480 | 420 | 480 | 420 | 420 | 746 |
| Metal4 | 480 | 420 | 480 | 420 | 420 | 746 |
| Metal5 | 480 | 420 | 480 | 420 | 420 | 746 |
| **TopMetal1** | **2,280** | **2,280** | 1,640 | 88 | 1,640 | 137 |
| **TopMetal2** | **4,000** | **4,000** | 2,000 | 50 | 2,000 | 78 |

---

## 9. gds.yaml Workflow (TTIHP Analog Template)

```yaml
name: gds
on:
  push:
  workflow_dispatch:

jobs:
  gds:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - id: top_module
        run: echo TOP_MODULE=`yq '.project.top_module' info.yaml` | tee $GITHUB_OUTPUT
      - uses: TinyTapeout/tt-gds-action/custom_gds@ttihp26a
        with:
          top_module: ${{ steps.top_module.outputs.TOP_MODULE }}
          gds_path: gds/${{ steps.top_module.outputs.TOP_MODULE }}.gds
          lef_path: lef/${{ steps.top_module.outputs.TOP_MODULE }}.lef
          verilog_path: src/project.v
          pdk: ihp-sg13g2

  precheck:
    needs: gds
    runs-on: ubuntu-24.04
    steps:
      - uses: TinyTapeout/tt-gds-action/precheck@ttihp26a

  viewer:
    needs: gds
    runs-on: ubuntu-24.04
    permissions:
      pages: write
      id-token: write
    steps:
      - uses: TinyTapeout/tt-gds-action/viewer@ttihp26a
```

Key: uses `TinyTapeout/tt-gds-action/custom_gds@ttihp26a` (not regular `tt-gds-action@ttihp26a`).

---

## 10. Magic TCL Init Script (Complete)

Located at: `tt-support-tools/tech/ihp-sg13g2/def/analog/magic_init_project.tcl`

```tcl
set TOP_LEVEL_CELL     tt_um_analog_example
set TEMPLATE_FILE      tt_analog_1x2.def
set POWER_STRIPE_WIDTH 2.4um

set POWER_STRIPES {
    VDPWR 1um
    VGND  6um
}

def read $TEMPLATE_FILE
cellname rename tt_um_template $TOP_LEVEL_CELL

proc draw_power_stripe {name x} {
    global POWER_STRIPE_WIDTH
    box $x 5um $x 308um
    box width $POWER_STRIPE_WIDTH
    paint met6
    label $name FreeSans 0.25u -met6
    port make
    port use [expr {$name eq "VGND" ? "ground" : "power"}]
    port class bidirectional
    port connections n s e w
}

foreach {name x} $POWER_STRIPES {
    puts "Drawing power stripe $name at $x"
    draw_power_stripe $name $x
}

save ${TOP_LEVEL_CELL}.mag
file mkdir gds
gds write gds/${TOP_LEVEL_CELL}.gds
file mkdir lef
lef write lef/${TOP_LEVEL_CELL}.lef -hide -pinonly
```

---

## 11. Summary of Critical Dimensions for analog-trial

| Item | Value |
|------|-------|
| Tile size | 202.08 x 313.74 um |
| prBoundary.boundary | GDS 189/4 |
| prBoundary.drawing | GDS 189/0 |
| Analog pins (ua) | TopMetal1 (126/0), 1.75x2.0 um, bottom edge |
| Digital pins | Metal4 (50/0), 0.3x1.0 um, top edge |
| Power stripes | TopMetal1 (126/0), vertical, min 2.1 um wide |
| Forbidden layer | TopMetal2 (134/0,1,2) |
| Via for analog pins | TopVia1 (125/0) |
| Pin precheck layer | TopMetal1.pin (126/2) |
