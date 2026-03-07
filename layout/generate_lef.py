"""Generate LEF for tt_um_techhu_analog_trial from the integrated GDS.

Reads pin geometry from the GDS and writes a pin-only LEF with obstruction.
Matches the format expected by tt-gds-action/custom_gds.

Usage:
    klayout -n sg13g2 -zz -r generate_lef.py
"""

import pya
import os

CELL_NAME = 'tt_um_techhu_analog_trial'

# Layer map: (gds_layer, datatype) → LEF layer name
PIN_LAYERS = {
    (126, 2): 'TopMetal1',   # TM1 pin
    (50, 2):  'Metal4',      # M4 pin
}

# Label layers for name lookup
LABEL_LAYERS = {
    (126, 1): 'TopMetal1',
    (50, 1):  'Metal4',
}

# Tile dimensions (µm)
TILE_W_UM = 202.080
TILE_H_UM = 313.740


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gds_path = os.path.join(script_dir, '..', 'gds', CELL_NAME + '.gds')
    lef_path = os.path.join(script_dir, '..', 'lef', CELL_NAME + '.lef')

    layout = pya.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    dbu = layout.dbu  # nm per database unit

    # Collect labels: (layer_key) → {(x,y): name}
    labels = {}
    for (ly, dt), lef_layer in LABEL_LAYERS.items():
        li = layout.layer(ly, dt)
        label_map = {}
        for shape in top.shapes(li).each():
            if shape.is_text():
                t = shape.text
                label_map[(t.x, t.y)] = t.string
        labels[(ly, dt)] = label_map

    # Collect pins: find pin shapes and match to nearest label
    pins = []  # (name, layer_name, x1_um, y1_um, x2_um, y2_um)

    for (ly, dt), lef_layer in PIN_LAYERS.items():
        li = layout.layer(ly, dt)
        label_ly = (ly, 1)  # pin dt=2 → label dt=1 (same GDS layer number)
        label_map = labels.get(label_ly, {})

        for shape in top.shapes(li).each():
            if shape.is_box():
                b = shape.box
                cx = (b.left + b.right) // 2
                cy = (b.bottom + b.top) // 2

                # Find closest label
                best_name = None
                best_dist = float('inf')
                for (lx, ly_), name in label_map.items():
                    d = abs(lx - cx) + abs(ly_ - cy)
                    if d < best_dist:
                        best_dist = d
                        best_name = name

                if best_name:
                    x1 = b.left * dbu
                    y1 = b.bottom * dbu
                    x2 = b.right * dbu
                    y2 = b.top * dbu
                    pins.append((best_name, lef_layer, x1, y1, x2, y2))

    # Deduplicate (keep first occurrence per name)
    seen = set()
    unique_pins = []
    for p in pins:
        if p[0] not in seen:
            seen.add(p[0])
            unique_pins.append(p)

    # Determine pin direction
    def pin_direction(name):
        if name.startswith('VDPWR') or name.startswith('VGND'):
            return 'INOUT'
        if name.startswith('ua'):
            return 'INOUT'
        if name.startswith('uo_out') or name.startswith('uio_out') or name.startswith('uio_oe'):
            return 'OUTPUT'
        if name.startswith('ui_in') or name.startswith('uio_in'):
            return 'INPUT'
        if name in ('clk', 'ena', 'rst_n'):
            return 'INPUT'
        return 'INOUT'

    # Determine pin use
    def pin_use(name):
        if name in ('VDPWR', 'VGND'):
            return 'POWER'
        return 'SIGNAL'

    # Write LEF
    with open(lef_path, 'w') as f:
        f.write(f'VERSION 5.7 ;\n')
        f.write(f'BUSBITCHARS "[]" ;\n')
        f.write(f'DIVIDERCHAR "/" ;\n\n')

        f.write(f'MACRO {CELL_NAME}\n')
        f.write(f'  CLASS BLOCK ;\n')
        f.write(f'  FOREIGN {CELL_NAME} 0.000 0.000 ;\n')
        f.write(f'  ORIGIN 0.000 0.000 ;\n')
        f.write(f'  SIZE {TILE_W_UM:.3f} BY {TILE_H_UM:.3f} ;\n')
        f.write(f'  SYMMETRY X Y ;\n')

        for name, layer, x1, y1, x2, y2 in unique_pins:
            direction = pin_direction(name)
            use = pin_use(name)
            f.write(f'  PIN {name}\n')
            f.write(f'    DIRECTION {direction} ;\n')
            f.write(f'    USE {use} ;\n')
            f.write(f'    PORT\n')
            f.write(f'      LAYER {layer} ;\n')
            f.write(f'        RECT {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f} ;\n')
            f.write(f'    END\n')
            f.write(f'  END {name}\n')

        # Obstruction (full die area on Metal1 — blocks all routing)
        f.write(f'  OBS\n')
        f.write(f'    LAYER Metal1 ;\n')
        f.write(f'      RECT 0.000 0.000 {TILE_W_UM:.3f} {TILE_H_UM:.3f} ;\n')
        f.write(f'  END\n')

        f.write(f'END {CELL_NAME}\n\n')
        f.write(f'END LIBRARY\n')

    print(f'  LEF written: {lef_path}')
    print(f'  Pins: {len(unique_pins)}')
    for p in sorted(unique_pins, key=lambda x: x[0]):
        print(f'    {p[0]:20s} {p[1]:12s} ({p[2]:.3f},{p[3]:.3f})→({p[4]:.3f},{p[5]:.3f})')


if __name__ == '__main__':
    main()
