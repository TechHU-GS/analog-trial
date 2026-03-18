---
name: pdk_reference
description: IHP SG13G2 complete PDK reference — metal stack, DRC rules, via specs, layer mapping, MIM, density, current limits
type: reference
---

## IHP SG13G2 PDK 完整参考 (2026-03-18 从官方文档提取)

来源: SG13G2_os_layout_rules.pdf Rev 0.4, SG13G2_os_process_spec.pdf Rev 1.2, sg13g2_tech.lef, sg13g2_tech_default.json

### Metal Stack (从下到上)

| Layer | GDS | Thickness | Width | Space | Rsheet | Direction(LEF) | Magic名 |
|-------|-----|-----------|-------|-------|--------|---------------|---------|
| Metal1 | 8/0 | 420nm | ≥160nm | ≥180nm | 110mΩ/sq | H | metal1 |
| Via1 | 19/0 | - | 190nm(fixed) | ≥220nm | 9Ω/via | - | via1 |
| Metal2 | 10/0 | 490nm | ≥200nm | ≥210nm | 88mΩ/sq | V | metal2 |
| Via2 | 29/0 | - | 190nm(fixed) | ≥220nm | 9Ω/via | - | via2 |
| Metal3 | 30/0 | 490nm | ≥200nm | ≥210nm | 88mΩ/sq | H | metal3 |
| Via3 | 49/0 | - | 190nm(fixed) | ≥220nm | 9Ω/via | - | via3 |
| Metal4 | 50/0 | 490nm | ≥200nm | ≥210nm | 88mΩ/sq | V | metal4 |
| Via4 | 66/0 | - | 190nm(fixed) | ≥220nm | 9Ω/via | - | via4 |
| Metal5 | 67/0 | 490nm | ≥200nm | ≥210nm | 88mΩ/sq | H | metal5 |
| TopVia1 | 125/0 | - | 420nm(fixed) | ≥420nm | 2.2Ω/via | - | via5 |
| TopMetal1 | 126/0 | 2000nm | ≥1640nm | ≥1640nm | 18mΩ/sq | V | met6 |
| TopVia2 | 133/0 | - | 900nm(fixed) | ≥1060nm | 1.1Ω/via | - | via6 |
| TopMetal2 | 134/0 | 3000nm | ≥2000nm | ≥2000nm | 11mΩ/sq | H | met7 |

### Via Enclosure Rules

| Via | Below enc | Below endcap | Above enc | Above endcap |
|-----|-----------|-------------|-----------|-------------|
| Via1 | M1: 10nm | M1: 50nm | M2: 5nm | M2: 50nm |
| Via2-4 | Mn: 5nm | Mn: 50nm | Mn+1: 5nm | Mn+1: 50nm |
| TopVia1 | M5: 100nm | M5: 100nm | TM1: 420nm | TM1: 420nm |
| TopVia2 | TM1: 500nm | - | TM2: 500nm | - |

### Wide Metal Spacing Rules (Mn, n=2-5)

| 条件 | Space |
|------|-------|
| 基本 | ≥210nm |
| 一线宽>0.39µm 且平行>1.0µm | ≥240nm |
| 一线宽>10.0µm 且平行>10.0µm | ≥600nm |
| 45度弯线 | ≥240nm |

### Density Rules

| Layer | Min | Max | Window |
|-------|-----|-----|--------|
| M1-M5 | 35% | 60% | 800×800µm |
| TM1 | 25% | 70% | - |
| TM2 | 25% | 70% | - |

Metal filler 必须在 tapeout 前生成。敏感区域用 nofill 层排除。

### Current Density (11 years @105°C)

| Layer | Max (w=0.2-0.3µm) | Max (w>0.3µm) |
|-------|-------------------|---------------|
| M1 | 0.36mA | 1mA/µm |
| M2-M5 | 0.6mA | 2mA/µm |
| TM1 | - | 15mA/µm |
| TM2 | - | 16mA/µm |
| Via1-4 | 0.4mA/via | |
| TopVia1 | 1.4mA/via | |

### MIM Capacitor

- 位置: Metal5 (bottom) ↔ TopMetal1 (top), MIM dielectric 40nm
- GDS: MIM layer 36/0, Vmim layer 129/0
- Caspec: 1.5 fF/µm² (target), 1.35-1.65 range
- Breakdown: 15-23V
- cap_cmim PCell 在 M5 上有 bottom plate geometry → M5 routing 必须绕开

### 层间电介质

| 层间 | 厚度 | εr |
|------|------|-----|
| Activ↔M1 | 640nm | 4.1 |
| M1↔M2 | 540nm | 4.1 |
| M2↔M3 | 540nm | 4.1 |
| M3↔M4 | 540nm | 4.1 |
| M4↔M5 | 540nm | 4.1 |
| M5↔TM1 | 850nm | 4.1 (bulk), 3.95 (near MIM) |
| TM1↔TM2 | 2800nm | 6.6 |

### Grid

- 制造 grid: 5nm (0.005µm)
- 所有坐标必须 5nm 对齐
- Via/Cont: 只允许 90°/180°
- Metal: 允许 90°/135°/180°/225°/270° (45度弯线有额外 DRC)

### Forbidden Layers (0.13µm technologies)

BiWind(3), PEmWind(11), BasPoly(13), DeepCo(35), PEmPoly(53), EmPoly(55), LDMOS(57), PBiWind(58), NoDRC(62), Flash(71), ColWind(139)

### 关键 PDK 文件路径

| 文件 | 路径 | 用途 |
|------|------|------|
| Layout Rules PDF | libs.doc/doc/SG13G2_os_layout_rules.pdf | 权威 DRC 规则 |
| Process Spec PDF | libs.doc/doc/SG13G2_os_process_spec.pdf | 工艺参数、截面图 |
| Tech LEF | libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef | 层方向/pitch/via定义 |
| DRC JSON | libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json | DRC 参数值 |
| GDS Layer Map | libs.tech/klayout/tech/sg13g2.map | GDS layer number 映射 |
| Magic Tech | libs.tech/magic/ihp-sg13g2.tech | Magic 层名定义 |
| Netgen Setup | libs.tech/netgen/ihp-sg13g2_setup.tcl | LVS 配置 |
| DRC Decks | libs.tech/klayout/tech/drc/rule_decks/beol/ | 各层 DRC 脚本 |
| LVS Decks | libs.tech/klayout/tech/lvs/rule_decks/ | LVS 提取规则 |

### 我们的分层策略 (verified)

```
M1/M2    — device PCell (不碰)
M3       — signal routing HORIZONTAL (LEF 一致)
M4       — signal routing VERTICAL (LEF 一致)
M5       — signal routing (LEF=H, 我们可用V，非硬规则)
TopMetal1 — power distribution (Magic: met6, GDS: 126/0)
TopMetal2 — 禁止 (TTIHP power grid)
```

### 验证过的事实

1. PDK PCell KLayout DRC = 0 (single device)
2. Magic DRC ≠ KLayout DRC (Magic 不可靠)
3. Device PCell 无 M3/M4/M5 geometry → device bbox 不是 routing obstacle
4. cap_cmim 有 M5 geometry (bottom plate) → M5 routing 必须绕
5. 电阻 PCell 无 M3/M4/M5 geometry
6. Power via stack TM1→M2: DRC clean + 电气连通 (Magic extract verified)
7. Via2→M3 电气连通 (Magic extract verified)
8. Routing obstacles: 153 power pads (M3/M4/M5) + 3 cap_cmim (M5)
