#!/usr/bin/env python3
"""Strip via1 and metal2 from Magic PCell subcells.

IHP SG13G2 PCells draw via1 + M2 enclosure pads at every contact.
These are convenience routing extensions, NOT multi-finger straps
(all devices in this project use nf=1).

Stripping via1+M2 prevents top-level M2 routing from accidentally
shorting to device internal M2 pads during Magic flat extraction.

Connections from routing M2 to device M1 are made through AP via
stacks placed in the parent cell at intentional locations.

Usage:
    python3 -m atk.strip_pcell_m2 /tmp/magic_soilz
"""

import os
import sys


def strip_mag_file(path):
    """Remove << via1 >> and << metal2 >> sections from a .mag file."""
    with open(path) as f:
        lines = f.readlines()

    out = []
    skip = False
    stripped_layers = {'via1', 'metal2'}

    for line in lines:
        stripped = line.strip()

        # Check for layer header
        if stripped.startswith('<< ') and stripped.endswith(' >>'):
            layer = stripped[3:-3]
            if layer in stripped_layers:
                skip = True
                continue
            else:
                skip = False

        if not skip:
            out.append(line)

    with open(path, 'w') as f:
        f.writelines(out)

    return len(lines) - len(out)


def main(mag_dir):
    total_removed = 0
    file_count = 0
    skipped = 0

    # Skip resistors and capacitors — their via1/M2 is functional
    # (connects terminal polycont/MIM to routing metal)
    skip_prefixes = ('dev_rin', 'dev_rout', 'dev_rptat', 'dev_rdac',
                     'dev_c_fb', 'dev_cbyp_n', 'dev_cbyp_p')

    for fn in sorted(os.listdir(mag_dir)):
        if fn.startswith('dev_') and fn.endswith('.mag'):
            if any(fn.startswith(sp) for sp in skip_prefixes):
                skipped += 1
                continue
            path = os.path.join(mag_dir, fn)
            removed = strip_mag_file(path)
            if removed > 0:
                file_count += 1
                total_removed += removed

    print(f'  Stripped via1+M2 from {file_count} device subcells '
          f'({total_removed} lines removed, {skipped} R/C skipped)')


if __name__ == '__main__':
    mag_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/magic_soilz'
    main(mag_dir)
