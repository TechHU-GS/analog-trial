"""SPICE netlist parser for IHP SG13G2 analog circuits.

Parses flat SPICE netlists (.sp) → structured JSON for LLM constraint generation.
Extracts devices, nets, connectivity, and detects common analog topology patterns.

Usage:
    python -m atk.spice.parser sim/ptat_vco.sp
    python -m atk.spice.parser sim/ptat_vco.sp -o parsed_spice.json
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# IHP SG13G2 SPICE subcircuit terminal order
# Order must match the .subckt definition in the PDK model files
TERMINAL_ORDER = {
    'sg13_lv_pmos': ['D', 'G', 'S', 'B'],
    'sg13_lv_nmos': ['D', 'G', 'S', 'B'],
    'npn13G2':      ['C', 'B', 'E', 'Sub'],
    'npn13G2l':     ['C', 'B', 'E', 'Sub'],
    'npn13G2v':     ['C', 'B', 'E', 'Sub'],
    'pnpMPA':       ['C', 'B', 'E', 'Sub'],
    'rppd':         ['PLUS', 'MINUS', 'Sub'],
    'rsil':         ['PLUS', 'MINUS', 'Sub'],
    'rhigh':        ['PLUS', 'MINUS', 'Sub'],
    'cap_cmim':     ['PLUS', 'MINUS'],
    'SG13_PMOSCM':  ['D', 'G', 'S', 'B'],
}

# Device class inference from PCell name
PCELL_CLASS = {
    'sg13_lv_pmos': 'pmos',
    'sg13_lv_nmos': 'nmos',
    'npn13G2': 'npn', 'npn13G2l': 'npn', 'npn13G2v': 'npn',
    'pnpMPA': 'pnp',
    'rppd': 'resistor', 'rsil': 'resistor', 'rhigh': 'resistor',
    'cap_cmim': 'capacitor',
    'SG13_PMOSCM': 'pmos',
}

# Common power net names
POWER_PATTERNS = {'vdd', 'vss', 'gnd', 'avdd', 'dvdd', 'avss', 'dvss', '0'}


def parse_spice(filepath):
    """Parse a flat SPICE netlist file.

    Args:
        filepath: path to .sp file

    Returns:
        dict with keys: title, devices, nets, power_nets, topology
    """
    lines = _read_and_join_continuations(filepath)
    title = _extract_title(lines)
    devices = _parse_instances(lines)
    nets = _build_nets(devices)
    power_nets = _identify_power_nets(nets, devices)
    topology = _detect_topology(devices, nets, power_nets)

    return {
        'title': title,
        'source_file': str(filepath),
        'devices': devices,
        'nets': nets,
        'power_nets': sorted(power_nets),
        'topology': topology,
    }


def _read_and_join_continuations(filepath):
    """Read SPICE file, join '+' continuation lines, strip comments."""
    raw = Path(filepath).read_text()
    joined = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            # Preserve title line (first non-empty)
            if stripped.startswith('**') or stripped.startswith('*'):
                joined.append(stripped)
            continue
        if stripped.startswith('+'):
            # Continuation of previous line
            if joined:
                joined[-1] += ' ' + stripped[1:].strip()
            continue
        joined.append(stripped)
    return joined


def _extract_title(lines):
    """Extract circuit title from first comment lines."""
    titles = []
    for line in lines:
        if line.startswith('**') or line.startswith('*'):
            text = line.lstrip('*').strip()
            if text and not text.startswith('=') and not text.startswith('-'):
                titles.append(text)
                if len(titles) >= 2:
                    break
        elif not line.startswith('.'):
            break
    return ' '.join(titles) if titles else 'Untitled'


def _parse_instances(lines):
    """Parse device instance lines (X/M/Q/R/C prefixes) into structured dicts."""
    # Prefix → expected terminal count before model name
    # M: D G S B model; Q: C B E Sub model; R: + - model; C: + - [model]
    PREFIX_TERM_COUNT = {'M': 4, 'Q': 4, 'R': 2, 'C': 2}

    devices = []
    for line in lines:
        first_char = line[0].upper() if line else ''
        if first_char not in ('X', 'M', 'Q', 'R', 'C'):
            continue
        if line.upper().startswith('.'):
            continue

        tokens = line.split()
        if len(tokens) < 3:
            continue

        if first_char == 'X':
            # Subcircuit call: Xname net1 net2 ... model_name params
            name = tokens[0][1:]
            pcell = None
            net_tokens = []
            param_tokens = {}

            for i, tok in enumerate(tokens[1:], 1):
                if '=' in tok:
                    k, v = tok.split('=', 1)
                    param_tokens[k] = _parse_param_value(v)
                elif tok in TERMINAL_ORDER:
                    pcell = tok
                elif pcell is None:
                    net_tokens.append(tok)

            if pcell is None:
                continue
        else:
            # Primitive: Mname D G S B model params; Qname C B E S model params; etc.
            prefix = first_char
            name = tokens[0]
            # Strip one prefix letter for clean name (MM1 → M1, QQ1 → Q1, RRiso → Riso)
            name = name[1:] if len(name) > 1 else name

            n_terms = PREFIX_TERM_COUNT.get(prefix, 0)

            # Collect net tokens, model, and params
            net_tokens = []
            pcell = None
            param_tokens = {}
            idx = 1

            # First n_terms tokens after name are nets
            while idx < len(tokens) and len(net_tokens) < n_terms:
                net_tokens.append(tokens[idx])
                idx += 1

            # Next non-param token is model name
            while idx < len(tokens):
                tok = tokens[idx]
                if '=' in tok:
                    k, v = tok.split('=', 1)
                    param_tokens[k] = _parse_param_value(v)
                elif pcell is None:
                    pcell = tok
                idx += 1

            if pcell is None:
                continue
            if pcell not in TERMINAL_ORDER:
                # For R/C: model name might be at end (rppd, cap_cmim)
                # Try matching known models
                if pcell not in TERMINAL_ORDER:
                    continue

        # Map net tokens to terminal names
        term_names = TERMINAL_ORDER.get(pcell, [])
        term_nets = {}
        for j, tname in enumerate(term_names):
            if j < len(net_tokens):
                net = net_tokens[j]
                if net == '0':
                    net = 'gnd'
                term_nets[tname] = net

        devices.append({
            'name': name,
            'pcell': pcell,
            'params': param_tokens,
            'nets': term_nets,
            'class': PCELL_CLASS.get(pcell, 'unknown'),
        })

    return devices


def _parse_param_value(s):
    """Parse a SPICE parameter value string → number or string."""
    # Handle SI suffixes: 4u → 4e-6, 0.5e-6 → float
    s = s.strip()
    suffix_map = {
        'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6,
        'm': 1e-3, 'k': 1e3, 'meg': 1e6, 'g': 1e9,
    }
    # Try direct float first
    try:
        return float(s) if '.' in s or 'e' in s.lower() else int(s)
    except ValueError:
        pass
    # Try suffix
    for suf, mult in suffix_map.items():
        if s.lower().endswith(suf):
            try:
                return float(s[:-len(suf)]) * mult
            except ValueError:
                pass
    return s


def _build_nets(devices):
    """Build net connectivity from device terminal connections."""
    net_pins = defaultdict(list)
    for dev in devices:
        for term, net in dev['nets'].items():
            net_pins[net].append(f"{dev['name']}.{term}")

    nets = []
    for name, pins in sorted(net_pins.items()):
        nets.append({
            'name': name,
            'pins': sorted(pins),
            'fanout': len(pins),
        })
    return nets


def _identify_power_nets(nets, devices):
    """Identify power nets from name patterns and bulk connections."""
    power = set()

    for net in nets:
        name_lower = net['name'].lower()
        # Explicit power names
        if name_lower in POWER_PATTERNS or name_lower.startswith('vdd') or name_lower.startswith('vss'):
            power.add(net['name'])
            continue
        # Bulk connections: if a net connects only to B/Sub terminals, it's power
        all_bulk = all(
            p.split('.')[1] in ('B', 'Sub')
            for p in net['pins']
        )
        if all_bulk and net['fanout'] >= 2:
            power.add(net['name'])

    # Also check: nets connected to voltage sources (V... lines) are power
    return power


def _detect_topology(devices, nets, power_nets):
    """Detect common analog circuit topology patterns."""
    net_map = {n['name']: n for n in nets}
    dev_map = {d['name']: d for d in devices}

    inv_chains, inv_rings = _find_inverter_chains(devices, net_map, power_nets)
    # Merge ring detections (from both methods)
    ring_from_topo = _find_ring_oscillators(devices, net_map, power_nets)
    all_rings = ring_from_topo + inv_rings

    topology = {
        'current_mirrors': _find_current_mirrors(devices, net_map, power_nets),
        'differential_pairs': _find_diff_pairs(devices, net_map, power_nets),
        'ring_oscillators': all_rings,
        'inverter_chains': inv_chains,
    }
    return topology


def _find_current_mirrors(devices, net_map, power_nets):
    """Find current mirrors: same PCell type + shared gate net + ≥2 devices."""
    mirrors = []
    dev_by_name = {d['name']: d for d in devices}
    # Group MOS devices by (pcell, gate_net)
    gate_groups = defaultdict(list)
    for dev in devices:
        if dev['class'] not in ('pmos', 'nmos'):
            continue
        gate_net = dev['nets'].get('G')
        if gate_net and gate_net not in power_nets:
            gate_groups[(dev['pcell'], gate_net)].append(dev['name'])

    for (pcell, gate_net), devs in gate_groups.items():
        if len(devs) >= 2:
            # Check if at least one device is diode-connected (D==G net)
            diode = any(
                dev_by_name[d]['nets'].get('D') == gate_net
                for d in devs if d in dev_by_name
            )
            mirrors.append({
                'devices': devs,
                'gate_net': gate_net,
                'pcell': pcell,
                'has_diode': diode,
            })

    return mirrors


def _find_diff_pairs(devices, net_map, power_nets):
    """Find differential pairs: same type + shared source net + different gates."""
    pairs = []
    # Group by (pcell, source_net)
    src_groups = defaultdict(list)
    for dev in devices:
        if dev['class'] not in ('pmos', 'nmos'):
            continue
        src_net = dev['nets'].get('S')
        if src_net and src_net not in power_nets:
            src_groups[(dev['pcell'], src_net)].append(dev)

    for (pcell, src_net), devs in src_groups.items():
        if len(devs) == 2:
            g0 = devs[0]['nets'].get('G')
            g1 = devs[1]['nets'].get('G')
            if g0 != g1 and g0 not in power_nets and g1 not in power_nets:
                pairs.append({
                    'devices': [devs[0]['name'], devs[1]['name']],
                    'source_net': src_net,
                    'gate_nets': [g0, g1],
                    'pcell': pcell,
                })

    return pairs


def _find_ring_oscillators(devices, net_map, power_nets):
    """Find ring oscillators: chain of inverter stages forming a loop."""
    rings = []

    # Find CMOS inverter pairs: PMOS+NMOS sharing drain and gate nets
    inverters = []
    nmos_devs = [d for d in devices if d['class'] == 'nmos']
    pmos_devs = [d for d in devices if d['class'] == 'pmos']

    for p in pmos_devs:
        for n in nmos_devs:
            pd = p['nets'].get('D')
            nd = n['nets'].get('D')
            pg = p['nets'].get('G')
            ng = n['nets'].get('G')
            if pd and pd == nd and pg and pg == ng and pd not in power_nets:
                inverters.append({
                    'pmos': p['name'], 'nmos': n['name'],
                    'output': pd, 'input': pg,
                })

    if len(inverters) < 3:
        return rings

    # Try to find a ring: follow output→input chain
    # Build output→inverter map
    out_map = {inv['output']: inv for inv in inverters}
    in_map = {inv['input']: inv for inv in inverters}

    visited = set()
    for start_inv in inverters:
        if start_inv['output'] in visited:
            continue
        chain = [start_inv]
        current = start_inv
        seen = {current['output']}

        while True:
            next_net = current['output']
            # Find inverter whose input == current output
            next_inv = in_map.get(next_net)
            if next_inv is None or next_inv == current:
                break
            if next_inv['output'] in seen:
                # Check if it loops back to start
                if next_inv['output'] == start_inv['input']:
                    chain.append(next_inv)
                    # Found a ring!
                    rings.append({
                        'stages': [inv['pmos'] for inv in chain[:-1]],
                        'nmos': [inv['nmos'] for inv in chain[:-1]],
                        'stage_count': len(chain) - 1,
                        'type': 'cmos_ring',
                    })
                break
            seen.add(next_inv['output'])
            chain.append(next_inv)
            current = next_inv
            visited.add(current['output'])

    return rings


def _find_inverter_chains(devices, net_map, power_nets):
    """Find inverter chains (non-ring): PMOS+NMOS pairs with sequential connections."""
    chains = []

    # Find all CMOS inverter pairs
    inverters = []
    nmos_devs = {d['name']: d for d in devices if d['class'] == 'nmos'}
    pmos_devs = {d['name']: d for d in devices if d['class'] == 'pmos'}

    for pname, p in pmos_devs.items():
        for nname, n in nmos_devs.items():
            pd = p['nets'].get('D')
            nd = n['nets'].get('D')
            pg = p['nets'].get('G')
            ng = n['nets'].get('G')
            if pd and pd == nd and pg and pg == ng and pd not in power_nets:
                inverters.append({
                    'pmos': pname, 'nmos': nname,
                    'output': pd, 'input': pg,
                })

    if len(inverters) < 2:
        return chains

    # Build input→inverter map (list-based for multi-fanout inputs)
    in_to_invs = defaultdict(list)
    for inv in inverters:
        in_to_invs[inv['input']].append(inv)

    used_outputs = set()

    for start in inverters:
        if start['output'] in used_outputs:
            continue
        chain = [start]
        chain_outputs = {start['output']}
        current = start

        while True:
            candidates = [
                i for i in in_to_invs.get(current['output'], [])
                if i is not current and i['output'] not in used_outputs
            ]
            if not candidates:
                break
            # Prefer candidate that closes the ring (output already in chain)
            ring_close = [c for c in candidates if c['output'] in chain_outputs]
            if ring_close:
                chain.append(ring_close[0])
                break
            # Otherwise take the candidate with same pcell type as start (stay in same circuit)
            same_type = [c for c in candidates if c['pmos'].rstrip('0123456789') == start['pmos'].rstrip('0123456789')]
            pick = same_type[0] if same_type else candidates[0]
            chain.append(pick)
            chain_outputs.add(pick['output'])
            used_outputs.add(pick['output'])
            current = pick

        if len(chain) < 2:
            continue

        # Check if chain closes a ring (last output == first output)
        is_ring = (len(chain) >= 4 and chain[-1]['output'] == chain[0]['output'])
        if is_ring:
            chains.append({
                'stages': [[inv['pmos'], inv['nmos']] for inv in chain[:-1]],
                'nets': [inv['output'] for inv in chain[:-1]],
                'is_ring': True,
            })
            for inv in chain[:-1]:
                used_outputs.add(inv['output'])
        else:
            chains.append({
                'stages': [[inv['pmos'], inv['nmos']] for inv in chain],
                'nets': [inv['output'] for inv in chain],
                'is_ring': False,
            })

    ring_chains = []
    pure_chains = []
    for c in chains:
        is_ring = c.pop('is_ring', False)
        if is_ring:
            ring_chains.append(c)
        else:
            pure_chains.append(c)
    return pure_chains, ring_chains


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print('Usage: python -m atk.spice.parser <file.sp> [-o output.json]')
        sys.exit(1)

    filepath = sys.argv[1]
    output = None
    if '-o' in sys.argv:
        idx = sys.argv.index('-o')
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    result = parse_spice(filepath)

    # Print summary
    print(f'Title: {result["title"]}')
    print(f'Devices: {len(result["devices"])}')
    for d in result['devices']:
        nets_str = ', '.join(f'{k}={v}' for k, v in d['nets'].items())
        print(f'  {d["name"]:10s} {d["pcell"]:20s} {nets_str}')
    print(f'Nets: {len(result["nets"])}')
    print(f'Power nets: {result["power_nets"]}')
    topo = result['topology']
    if topo['current_mirrors']:
        print(f'Current mirrors: {len(topo["current_mirrors"])}')
        for m in topo['current_mirrors']:
            print(f'  {m["devices"]} gate={m["gate_net"]}')
    if topo['ring_oscillators']:
        print(f'Ring oscillators: {len(topo["ring_oscillators"])}')
        for r in topo['ring_oscillators']:
            n = r.get('stage_count', len(r['stages']))
            print(f'  {n}-stage: {[s[0] for s in r["stages"]]}')
    if topo['inverter_chains']:
        print(f'Inverter chains: {len(topo["inverter_chains"])}')
    if topo['differential_pairs']:
        print(f'Differential pairs: {len(topo["differential_pairs"])}')

    # Write JSON
    if output:
        with open(output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f'\nWritten: {output}')
    else:
        # Default output path
        sp_path = Path(filepath)
        out_path = sp_path.with_suffix('.parsed.json')
        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f'\nWritten: {out_path}')


if __name__ == '__main__':
    main()
