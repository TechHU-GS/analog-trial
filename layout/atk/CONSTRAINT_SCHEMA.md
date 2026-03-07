# netlist.json Constraint Schema

Reference for LLM-generated constraint files.

## Top-Level

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `design` | string | yes | Design name |
| `version` | string | yes | Schema version ("1.0") |
| `phase` | int | yes | ATK phase (always 1) |
| `description` | string | yes | Human-readable description |
| `devices` | array | yes | Device instance list |
| `nets` | array | yes | Net connectivity |
| `constraints` | object | yes | All placement/routing constraints |

## devices[]

Each device instance to be placed.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique instance name (e.g. "M1", "Q1") |
| `type` | string | yes | Key into device_lib.json (e.g. "pmos_mirror", "hbt_1x") |
| `has_nwell` | bool | yes | true for PMOS (device sits in NWell) |
| `nwell_net` | string/null | yes | NWell supply net ("vdd_vco", "vdd") or null for NMOS |

## nets[]

Net connectivity. Every device pin must appear in exactly one net.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Net name (e.g. "vdd_vco", "net_c1") |
| `type` | string | yes | "power" or "signal" |
| `pins` | array[string] | yes | Pin refs as "DEVICE.PIN" (e.g. "M1.D", "Q1.B") |

## constraints

### drc_spacing

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_gap_nm` | int | 700 | Min gap between devices (nm) |
| `hbt_gap_nm` | int | 1200 | Min gap around HBT devices (nm) |
| `hbt_halo_um` | float | 2.0 | HBT substrate ring reservation (µm) |

### well_aware_spacing

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `nwell_islands` | array | yes | Groups of devices sharing NWell |
| `inter_island_min_nm` | int | yes | Min NWell-to-NWell spacing (different nets) |

**nwell_islands[]**:
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Island name (e.g. "NWell_A") |
| `net` | string | NWell supply net |
| `devices` | array[string] | Devices in this NWell |

### tie_reservation

| Field | Type | Description |
|-------|------|-------------|
| `pmos_ntap.applies_to` | array[string] | Device types needing ntap |
| `pmos_ntap.keepout_h_nm` | int | ntap strip height (nm) |
| `nmos_ptap.applies_to` | array[string] | Device types needing ptap |
| `nmos_ptap.keepout_h_nm` | int | ptap strip height (nm) |

### matching

| Field | Type | Description |
|-------|------|-------------|
| `match_groups` | array | Groups of devices with equal spacing |
| `symmetry` | array | Device pairs with Y-axis symmetry |
| `keep_close` | array | Device pairs with max distance |

**match_groups[]**: `{devices: [string], type: string, reason: string}`
**keep_close[]**: `{devices: [string, string], max_distance_um: float}`

### isolation

Optional. Defines isolation zones between circuit blocks.

**zones[]**: `{name: string, devices: [string]}`
**min_zone_gap[]**: `{from: string, to: string, min_gap_um: float}`

### routing_channels.row_channels[]

| Field | Type | Description |
|-------|------|-------------|
| `above` | string | Row name above channel |
| `below` | string | Row name below channel |
| `n_tracks` | int | Number of routing tracks (2 or 3) |

### row_groups

Map of row_name → `{devices: [string], gap_um?: float}`.
Every device must be in exactly one row. Devices in same row share Y coordinate.
`gap_um` overrides default device spacing within the row.

### x_align

Array of arrays. Devices in each sub-array share X coordinate (within 1µm tolerance).
Used for vertical alignment (e.g. VCO PMOS, NMOS, bias in same column).

### y_align

Array of arrays of **row names**. Rows in each sub-array share the same Y baseline.

### x_order

Array of `{a: string, b: string, min_gap_um: float}`.
Device `a` must be to the left of device `b` with at least `min_gap_um` gap.

### electrical_proximity

Optional. Fine-grained proximity constraints.

**inverter_pairs[]**: `{pu: string, pd: string, max_dy_um: float}` — PMOS/NMOS inverter pair max vertical distance.
**bias_pairs[]**: `{inv: string, bias: string, max_dy_um: float}` — Inverter NMOS to bias NMOS.

### edge_keepout

`{margin_um: float}` — Min distance from any device to bounding box edge.

### pin_access

Map of device_type → {pin_name: access_mode}.

Access modes:
- `above`: Via above device (towards higher Y)
- `below`: Via below device (towards lower Y)
- `gate`: Gate contact access (GatPoly → Cont → M1)
- `m1_pin`: Direct M1 pin (no via needed)
- `m2_below`: M2 access below device
- `via_stack`: Via1+Via2 stack to M3

### tie_config

Map of PMOS device_type → `{src_pin: string, cont: string}`.
- `src_pin`: Which source pin the ntap tie aligns to ("S", "S1", "S2")
- `cont`: Contact array size ("1x2", "2x2")

### hbt_extras

Map of HBT device_type → `{m2_stub_dx: int}`.
M2 stub X offset in nm to avoid B→C pre-route conflict.

### power_topology

Defines M3 power rails and M2/Via drops.

**rails[]**: `{net: string, anchor_inst: string, anchor_side: "top"|"bottom", offset_um: float}`
Rail Y = device_top/bottom + offset.

**rail_x**: `{left_margin_um: float, right_anchor_inst: string, right_margin_um: float}`

**drops[]**: `{net: string, inst: string, pin: string, strategy: "via_access"|"via_stack"}`
- `via_access`: Standard M1→Via1→M2→Via2→M3 drop through access point
- `via_stack`: Direct Via1+Via2 stack at pin position (for trapped pins)

### Other Fields

| Field | Type | Description |
|-------|------|-------------|
| `critical_nets` | array[string] | Nets to route first / prioritize |
| `power_nets` | array[string] | Power net names |
| `pre_routed_pins` | array | Pins with pre-existing routes (usually []) |
| `routing_order` | array[string] | Signal net routing order |
| `wirelength_weight` | float | HPWL weight in objective (default 0.5) |

## Validation

Run: `python -m atk.spice.validate netlist.json atk/data/device_lib.json`

Checks: device types exist, pin refs valid, row coverage complete, power drops complete, routing order complete, pin_access complete, tie_config complete, nwell consistency.
