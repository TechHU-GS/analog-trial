#!/usr/bin/env python3
"""Debug: find all M3 vbars near BUF_I conflict area."""
import json
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
data = json.load(open("output/routing.json"))
drops = data.get("power_drops", [])
for i, d in enumerate(drops):
    if d.get("type") == "via_stack" and "m3_vbar" in d:
        x = d["m3_vbar"][0]
        if True:  # print all
            y1 = min(d["m3_vbar"][1], d["m3_vbar"][3])
            y2 = max(d["m3_vbar"][1], d["m3_vbar"][3])
            inst = d["inst"]
            pin = d["pin"]
            net = d["net"]
            print(f"  [{i}] {inst}.{pin} net={net} x={x} y=[{y1},{y2}] len={y2-y1}")
