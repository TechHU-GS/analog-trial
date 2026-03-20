"""§1: Place PCell instances from placement.json."""

import os
import klayout.db

from atk.pdk import UM


def place_pcells(ctx, lib):
    """Instantiate IHP SG13G2 PCells at placement positions.

    Args:
        ctx: AssemblyContext with layout, top, placement, devices_map
        lib: pya.Library for SG13_dev
    """
    print('\n  === Placing devices ===')
    instances = ctx.placement['instances']
    for inst_name, info in instances.items():
        dev_type = info['type']
        dev = ctx.devices_map[dev_type]
        px = info['x_um']
        py = info['y_um']

        pcell_decl = lib.layout().pcell_declaration(dev['pcell'])
        pcell_id = ctx.layout.add_pcell_variant(lib, pcell_decl.id(),
                                                 dev['params'])

        ox_nm = round((px - dev['ox']) * UM)
        oy_nm = round((py - dev['oy']) * UM)
        ox_nm = ((ox_nm + 2) // 5) * 5
        oy_nm = ((oy_nm + 2) // 5) * 5

        rot = dev.get('rotation', 0)
        ctx.top.insert(klayout.db.CellInstArray(
            pcell_id,
            klayout.db.Trans(rot, False, klayout.db.Point(ox_nm, oy_nm))
        ))
        print(f'    {inst_name:8s} ({dev_type:14s}) at ({px:7.2f}, {py:7.2f})')
    print(f'  Placed {len(instances)} devices')

    # Bare mode: PCell-only GDS for baseline
    if os.environ.get('BARE_MODE'):
        bare_out = os.environ.get('GDS_OUTPUT',
                                  os.path.join(os.path.dirname(
                                      os.path.dirname(
                                          os.path.abspath(__file__))),
                                      'output', 'soilz_bare.gds'))
        ctx.layout.write(bare_out)
        print(f'\n  BARE MODE: written {len(instances)} PCells to {bare_out}')
        return True  # signal caller to stop

    return False  # continue with assembly
