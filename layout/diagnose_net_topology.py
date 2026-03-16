#!/usr/bin/env python3
"""Diagnose LVS net topology mismatches: bucket analysis.

Parses the KLayout lvsdb cross-reference to categorize device and net
mismatches into actionable buckets.

Usage:
    cd layout && python3 diagnose_net_topology.py [lvsdb_path]
"""
import os
import sys
import json
from collections import defaultdict, Counter

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import klayout.db as kdb

LVSDB = sys.argv[1] if len(sys.argv) > 1 else '/tmp/lvs_r32d/ptat_vco.lvsdb'

# ── 1. Parse lvsdb cross-reference ──────────────────────────────────────

db = kdb.LayoutVsSchematic()
db.read(LVSDB)
xref = db.xref()

Match = kdb.NetlistCrossReference.Match
Mismatch = kdb.NetlistCrossReference.Mismatch
NoMatch = kdb.NetlistCrossReference.NoMatch
Skipped = kdb.NetlistCrossReference.Skipped

# ── 2. Collect per-circuit-pair data ────────────────────────────────────

for cr in xref.each_circuit_pair():
    # ── 2a. Device pair analysis ────────────────────────────────────────
    dev_matched = []
    dev_mismatched = []
    dev_layout_only = []
    dev_ref_only = []

    for dp in xref.each_device_pair(cr):
        st = dp.status()
        d1 = dp.first()   # layout
        d2 = dp.second()  # reference
        if st == Match:
            dev_matched.append((d1, d2))
        elif st == Mismatch:
            dev_mismatched.append((d1, d2))
        elif st == NoMatch:
            if d1 and not d2:
                dev_layout_only.append(d1)
            elif d2 and not d1:
                dev_ref_only.append(d2)
            else:
                dev_layout_only.append(d1)

    print("=" * 70)
    print("DEVICE ANALYSIS")
    print("=" * 70)
    print(f"  Matched:      {len(dev_matched)}")
    print(f"  Mismatched:   {len(dev_mismatched)}")
    print(f"  Layout-only:  {len(dev_layout_only)}")
    print(f"  Ref-only:     {len(dev_ref_only)}")
    print()

    # ── 2b. Net pair analysis ───────────────────────────────────────────
    net_matched = []
    net_mismatched = []
    net_layout_only = []
    net_ref_only = []

    for np_item in xref.each_net_pair(cr):
        st = np_item.status()
        n1 = np_item.first()   # layout
        n2 = np_item.second()  # reference
        if st == Match:
            net_matched.append((n1, n2))
        elif st == Mismatch:
            net_mismatched.append((n1, n2))
        elif st == NoMatch:
            if n1 and not n2:
                net_layout_only.append(n1)
            elif n2 and not n1:
                net_ref_only.append(n2)
            else:
                net_layout_only.append(n1)

    print("=" * 70)
    print("NET ANALYSIS")
    print("=" * 70)
    print(f"  Matched:      {len(net_matched)}")
    print(f"  Mismatched:   {len(net_mismatched)}")
    print(f"  Layout-only:  {len(net_layout_only)}")
    print(f"  Ref-only:     {len(net_ref_only)}")
    print()

    # ── 2c. Matched net names ───────────────────────────────────────────
    print("--- Matched nets ---")
    matched_names = []
    for n1, n2 in net_matched:
        name1 = n1.name if n1 else '?'
        name2 = n2.name if n2 else '?'
        matched_names.append((name1, name2))
    for name1, name2 in sorted(matched_names):
        tag = "" if name1 == name2 else f" (ref: {name2})"
        print(f"  {name1}{tag}")

    # ── 2d. Mismatched net details ──────────────────────────────────────
    print()
    print("--- Mismatched nets ---")
    mm_nets = []
    for n1, n2 in net_mismatched:
        name1 = n1.name if n1 else '[none]'
        name2 = n2.name if n2 else '[none]'
        mm_nets.append((name1, name2))
    for name1, name2 in sorted(mm_nets):
        tag = "" if name1 == name2 else f" ↔ ref:{name2}"
        print(f"  layout:{name1}{tag}")

    # ── 2e. Layout-only nets ────────────────────────────────────────────
    print()
    print("--- Layout-only nets (no reference match) ---")
    lo_names = []
    for n in net_layout_only:
        lo_names.append(n.name if n else '?')
    # Categorize
    named_lo = [n for n in lo_names if not n.startswith('$')]
    unnamed_lo = [n for n in lo_names if n.startswith('$')]
    if named_lo:
        print(f"  Named ({len(named_lo)}):")
        for n in sorted(named_lo):
            print(f"    {n}")
    if unnamed_lo:
        print(f"  Unnamed/internal ({len(unnamed_lo)}): "
              f"${min(int(n[1:]) for n in unnamed_lo if n[1:].isdigit())} .. "
              f"${max(int(n[1:]) for n in unnamed_lo if n[1:].isdigit())} "
              f"(KLayout auto-numbered)")

    # ── 2f. Ref-only nets ───────────────────────────────────────────────
    print()
    print("--- Ref-only nets (not found in layout) ---")
    ro_names = []
    for n in net_ref_only:
        ro_names.append(n.name if n else '?')
    for n in sorted(ro_names):
        print(f"  {n}")

    # ── 2g. Pin pair analysis ───────────────────────────────────────────
    print()
    print("=" * 70)
    print("PIN ANALYSIS")
    print("=" * 70)
    pin_matched = pin_mm = 0
    for pp in xref.each_pin_pair(cr):
        if pp.status() == Match:
            pin_matched += 1
        else:
            pin_mm += 1
    print(f"  Matched: {pin_matched}, Mismatched: {pin_mm}")

    # ── 3. Bucketing ────────────────────────────────────────────────────

    print()
    print("=" * 70)
    print("MISMATCH BUCKETS")
    print("=" * 70)

    # Bucket: named nets that are in reference but only in layout (or vice versa)
    # These indicate routing connectivity errors

    # Load netlist.json for net classification
    with open('netlist.json') as f:
        netlist = json.load(f)
    net_info = {}
    for net in netlist['nets']:
        net_info[net['name']] = {
            'type': net['type'],
            'pins': net['pins'],
            'fanout': len(net['pins']),
        }

    # Classify ref-only nets
    ref_only_by_type = defaultdict(list)
    for n in sorted(ro_names):
        info = net_info.get(n, {})
        ntype = info.get('type', 'unknown')
        fanout = info.get('fanout', 0)
        ref_only_by_type[ntype].append((n, fanout))

    # Classify layout-only named nets
    layout_only_named_by_type = defaultdict(list)
    for n in sorted(named_lo):
        info = net_info.get(n, {})
        ntype = info.get('type', 'unknown')
        fanout = info.get('fanout', 0)
        layout_only_named_by_type[ntype].append((n, fanout))

    print()
    print("Bucket 1: Ref-only nets (in reference, NOT matched in layout)")
    for ntype in sorted(ref_only_by_type):
        nets = ref_only_by_type[ntype]
        print(f"  [{ntype}] ({len(nets)} nets):")
        for n, fanout in sorted(nets, key=lambda x: -x[1]):
            pins = net_info.get(n, {}).get('pins', [])
            pin_preview = ', '.join(pins[:5])
            if len(pins) > 5:
                pin_preview += f', ... (+{len(pins)-5})'
            print(f"    {n} (fanout={fanout}): {pin_preview}")

    print()
    print("Bucket 2: Layout-only NAMED nets (in layout, no ref match)")
    for ntype in sorted(layout_only_named_by_type):
        nets = layout_only_named_by_type[ntype]
        print(f"  [{ntype}] ({len(nets)} nets):")
        for n, fanout in sorted(nets, key=lambda x: -x[1]):
            print(f"    {n} (fanout={fanout})")

    print()
    print(f"Bucket 3: Layout-only UNNAMED nets: {len(unnamed_lo)}")
    print(f"  These are internal KLayout extraction nodes ($NNN)")
    print(f"  Not necessarily errors — may represent correctly extracted")
    print(f"  internal connections that don't exist as named nets in reference")

    print()
    print("Bucket 4: Mismatched net pairs (both sides exist, topology differs)")
    # These are nets that the comparator found in both but couldn't match fully
    mm_named = [(n1, n2) for n1, n2 in mm_nets
                if not n1.startswith('$') or not n2.startswith('$')]
    mm_internal = [(n1, n2) for n1, n2 in mm_nets
                   if n1.startswith('$') and n2.startswith('$')]
    if mm_named:
        print(f"  Named pairs ({len(mm_named)}):")
        for n1, n2 in sorted(mm_named)[:20]:
            print(f"    layout:{n1} ↔ ref:{n2}")
        if len(mm_named) > 20:
            print(f"    ... and {len(mm_named)-20} more")
    print(f"  Internal ($-$) pairs: {len(mm_internal)}")

    # ── 4. High-impact analysis ─────────────────────────────────────────

    print()
    print("=" * 70)
    print("HIGH-IMPACT NETS: Key analog/control nets status")
    print("=" * 70)

    key_nets = [
        'vco_out', 'vdd', 'gnd', 'vdd_vco',
        'tail', 'mid_p', 'pmos_bias', 'nmos_bias',
        'net_c1', 'net_c2', 'net_rptat', 'vptat',
        'vref_comp', 'vref_ota',
        'sel0', 'sel1', 'sel2', 'sel0b', 'sel1b', 'sel2b',
        'buf1', 'vco1', 'vco2', 'vco3', 'vco4', 'vco5',
        'ns1', 'ns2', 'ns3', 'ns4', 'ns5',
        'vco_b', 'comp_clk', 'comp_outn', 'comp_outp',
        'ota_out', 'f_exc', 'exc_out', 'dac_out',
        'cas1', 'cas2', 'cas3', 'cas_ref', 'vcas',
    ]

    # Build lookup from matched/mismatched/etc
    net_status = {}
    for n1, n2 in net_matched:
        name1 = n1.name if n1 else ''
        name2 = n2.name if n2 else ''
        net_status[name2] = ('MATCH', name1)
        net_status[name1] = ('MATCH', name2)
    for n1, n2 in net_mismatched:
        name1 = n1.name if n1 else ''
        name2 = n2.name if n2 else ''
        net_status[name2] = ('MISMATCH', name1)
        net_status[name1] = ('MISMATCH', name2)
    for n in net_layout_only:
        name = n.name if n else ''
        if name not in net_status:
            net_status[name] = ('LAYOUT_ONLY', '')
    for n in net_ref_only:
        name = n.name if n else ''
        if name not in net_status:
            net_status[name] = ('REF_ONLY', '')

    for net_name in key_nets:
        st, other = net_status.get(net_name, ('UNKNOWN', ''))
        fanout = net_info.get(net_name, {}).get('fanout', '?')
        mark = '✓' if st == 'MATCH' else '✗' if st in ('MISMATCH', 'REF_ONLY') else '?'
        detail = f" (↔ {other})" if other and other != net_name else ""
        print(f"  {mark} {net_name:20s} fanout={fanout:>3}  status={st}{detail}")

    # ── 5. Summary table ────────────────────────────────────────────────

    print()
    print("=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print(f"{'Bucket':<45} {'Count':>6}  {'Priority'}")
    print(f"{'-'*45} {'-'*6}  {'-'*8}")
    print(f"{'Matched devices':<45} {len(dev_matched):>6}")
    print(f"{'Mismatched devices':<45} {len(dev_mismatched):>6}  HIGH")
    print(f"{'Layout-only devices':<45} {len(dev_layout_only):>6}  HIGH")
    print(f"{'Ref-only devices':<45} {len(dev_ref_only):>6}  HIGH")
    print(f"{'':<45} {'':>6}")
    print(f"{'Matched nets':<45} {len(net_matched):>6}")
    print(f"{'Mismatched net pairs (named)':<45} {len(mm_named):>6}  HIGH")
    print(f"{'Mismatched net pairs (internal $-$)':<45} {len(mm_internal):>6}  LOW")
    print(f"{'Layout-only named nets':<45} {len(named_lo):>6}  MEDIUM")
    print(f"{'Layout-only unnamed nets ($NNN)':<45} {len(unnamed_lo):>6}  LOW")
    print(f"{'Ref-only nets':<45} {len(ro_names):>6}  HIGH")
    print(f"{'':<45} {'':>6}")
    print(f"{'Matched pins (ports)':<45} {pin_matched:>6}")
    print(f"{'Mismatched pins':<45} {pin_mm:>6}")

    break  # only one circuit pair
