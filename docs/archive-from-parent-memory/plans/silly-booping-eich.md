# SoilZ v1 布局重构: 垂直堆叠 + 两级求解 + 电阻旋转

## Context

Phase 4 路由失败 (74/141 nets, 52%)。根因已确诊 (**不是** 面积不足):
- 当前 2 列布局 sigma_delta/digital 并排 (y=23-125)，跨区信号需要 **垂直通道** (X 方向间隙)
- ATK 路由器只支持 **水平通道** (Y 方向间隙，行间 routing channel)
- 路由天花板测试: 即使完美排序，理论最大 104/141
- 扩大面积 54% → 零改善，确认瓶颈是结构性的

**目标**: 重新设计布局为垂直堆叠，使所有跨区信号穿越水平通道 (router 支持的方向)。

## 方案: 垂直堆叠 + per-zone 求解 + 电阻旋转

### 堆叠顺序 (bottom → top)

```
Y=310  ┌─────────────────────────────────────────────┐
       │  DIGITAL (138T)  ← uo[0..7] Metal4 顶部      │  ~65µm
       ├── corridor_5 (4T=2.5µm) ── vco_out ─────────┤
       │  VCO_RING (24T)  ← 5级+buffer                │  ~30µm
       ├── corridor_4 (4T=2.5µm) ── nmos/pmos_bias ──┤
       │  BIAS_PTAT (10T+Rptat横置)                    │  ~25µm
       ├── corridor_3 (3T=2.0µm) ── net_c1, vcas ────┤
       │  CURRENT_SRC (15T) ← cascode mirror+TG       │  ~25µm
       ├── corridor_2 (3T=2.0µm) ── exc_out ─────────┤
       │  EXCITATION (26T) ← NOL+H-bridge             │  ~25µm
       ├── corridor_1 (4T=2.5µm) ── f_exc/f_exc_b ───┤
       │  SIGMA_DELTA (35T+Rin/Rdac横置)               │  ~25µm
       │                    ← ua[1] sensor input       │
Y=3    └─────────────────────────────────────────────┘
        x=3                                       x=199
```

**电阻旋转效果** (实测 device_lib.json bbox):
- Rptat: 9.06×135.54µm → 旋转90° → 135.54×9.06µm，放入 bias_ptat 作为一行
- Rin/Rdac: 2.26×22.16µm → 旋转90° → 22.16×2.26µm，sigma_delta 省 ~40µm 高度
- Rout: 3.62×27.36µm → 旋转90° → 27.36×3.62µm
- **消除侧带 → 所有 zone 得到完整 tile 宽度 (196µm)**
- **sigma_delta 高度从 ~55µm 降至 ~25µm** (电阻从 22µm 高变为 2.3µm 高)

估算总高: 25+25+25+25+30+65 = 195µm + 5×~2.3µm + 2×3µm ≈ 213µm。
Tile 313.74µm，余量 ~100µm。

### 关键信号穿越分析

| 信号 | From | To | 穿越通道数 |
|------|------|----|-----------|
| f_exc (14 pins) | excitation | sigma_delta | 1 ✓ |
| f_exc_b (10 pins) | excitation | sigma_delta | 1 ✓ |
| exc_out (8 pins) | current_src | excitation | 1 ✓ |
| nmos_bias (9 pins) | bias_ptat | current_src + VCO | 1↓ + 1↑ ✓ |
| pmos_bias (8 pins) | bias_ptat | VCO | 1 ✓ |
| net_c1 (12 pins) | bias_ptat | current_src | 1 ✓ |
| vco_out (12 pins) | VCO | digital | 1 ✓ |

### 合并 ptat_core + bias_gen

match_group `[PM3, PM4, PM_ref, PM5]` 要求同行 (same_row_equal_spacing)。
PM3/PM4 原属 ptat_core, PM_ref/PM5 原属 bias_gen。
分属不同 zone 时 `add_equal_spacing` (same Y) 与 `add_device_region` (不同 Y 范围) 冲突。
(注: 推测性分析，当前求解器曾返回 OPTIMAL，可能实际 netlist.json 与代码不同步。需验证。)
合并为 bias_ptat (10+1 devices) 消除此风险，电气上也合理。

### 两级求解架构

**为什么 per-zone 独立求解优于单次全局求解:**
- Zone 边界是人为固定的 → 全局 HPWL 拉跨区 device 靠近的行为被 zone bbox 约束阻止 → 浪费优化力
- Per-zone 只优化 intra-zone HPWL → 更有效
- 每 zone 10-35 devices → <1s 求解 (vs 全局 249 devices ~3.4s)
- 可独立调参 (wl_weight, gap, time_limit)
- 调试/迭代只重跑受影响的 zone

## 实现步骤

### Step 1: 修改 gen_soilz_netlist.py

**文件**: `/private/tmp/analog-trial/layout/gen_soilz_netlist.py`

#### 1a. 合并 ZONES + Rptat 归入 bias_ptat

```python
ZONES = {
    "bias_ptat":   [d["name"] for d in ZONE1]   # 含 Rptat
                   + [d["name"] for d in ZONE2],  # 11 devices
    "vco_ring":    [d["name"] for d in ZONE3],    # 24
    "current_src": [d["name"] for d in ZONE4],    # 15
    "excitation":  [d["name"] for d in ZONE5],    # 26
    "sigma_delta": [d["name"] for d in ZONE6],    # 35
    "digital":     [d["name"] for d in ZONE7],    # 138
}
# 不再需要 rptat_res 单独 zone
```

#### 1b. 重写 floorplan (全宽带状，无侧带)

Y 坐标为初步估算，需根据实际求解结果微调:
```python
"floorplan": {
    "sigma_delta": {"x_min": 3, "y_min": 3,   "x_max": 199, "y_max": 28},
    "excitation":  {"x_min": 3, "y_min": 31,  "x_max": 199, "y_max": 56},
    "current_src": {"x_min": 3, "y_min": 59,  "x_max": 199, "y_max": 84},
    "bias_ptat":   {"x_min": 3, "y_min": 87,  "x_max": 199, "y_max": 117},
    "vco_ring":    {"x_min": 3, "y_min": 120, "x_max": 199, "y_max": 150},
    "digital":     {"x_min": 3, "y_min": 153, "x_max": 199, "y_max": 218},
},
```

#### 1c. 更新 row_groups

- PM_ref, PM5 从 `bias_pmos` 行移入 `ptat_mirror` 行 (match_group 要求)
- PM_pdiode 单独行或与其他 bias PMOS 组行
- Rptat 行改为横置 (宽 135µm, 高 9µm)
- 删除旧 `rptat` 单独行

#### 1d. 添加 inter-zone routing channels

```python
# 5 条 inter-zone corridors (连接相邻 zone 的边界行)
{"above": "hbridge", "below": "sr_p", "n_tracks": 4},   # corridor_1: sd↔exc
{"above": "cas_load", "below": "nol_p", "n_tracks": 3}, # corridor_2: exc↔csrc
{"above": "ptat_mirror", "below": "sw_tg", "n_tracks": 3}, # corridor_3: csrc↔bias
{"above": "vco_cs_p", "below": "vittoz", "n_tracks": 4}, # corridor_4: bias↔vco
{"above": "tff_1I_p", "below": "buf_n", "n_tracks": 4}, # corridor_5: vco↔dig
```

注意: above/below 方向需要确认——`add_row_spacing(above, below)` 语义是
`y[above] >= y[below] + h[below] + channel_width(n)`。hbridge 在 excitation (上方 zone)
的最底行，sr_p 在 sigma_delta (下方 zone) 的最顶行，所以 above=hbridge, below=sr_p。

#### 1e. 删除旧的跨区连接

删除 `{"above": "chopper", "below": "hbridge", "n_tracks": 2}` (新布局中无效)。
删除 `zone_order_x` (不再需要水平排列)。

#### 1f. 电阻旋转标记

在 constraints 中添加旋转信息:
```python
"rotation": {
    "Rptat": 90,   # rhigh_ptat: 9×135 → 135×9
    "Rin":   90,   # rhigh_200k: 2.3×22 → 22×2.3
    "Rdac":  90,   # rhigh_200k: 2.3×22 → 22×2.3
    "Rout":  90,   # rppd_out:   3.6×27 → 27×3.6
},
```

### Step 2: solve_placement.py → per-zone 求解

**文件**: 新建 `/private/tmp/analog-trial/layout/solve_placement_v2.py` (保留原文件)

核心逻辑:
```python
for zone_name, zone_devs in ZONES.items():
    # 1. 筛选该 zone 的 devices, rows, channels, match
    zone_nl = filter_netlist_for_zone(netlist, zone_name)

    # 2. 处理旋转: 交换 width/height
    for dev in zone_devs:
        if dev in rotation_map:
            solver_devs[dev]['w'], solver_devs[dev]['h'] = \
                solver_devs[dev]['h'], solver_devs[dev]['w']

    # 3. 创建独立 placer
    placer = ConstraintPlacer(zone_solver_devs, grid=0.10)
    bbox = floorplan[zone_name]
    placer.setup(max_width=bbox_w, max_height=bbox_h)

    # 4. 添加 intra-zone 约束
    # ... rows, channels, match, proximity ...

    # 5. 求解
    result, status = placer.solve(time_limit=60.0)
    zone_results[zone_name] = result

# 6. 合并: zone-local 坐标 → global 坐标
global_placement = merge_zone_placements(zone_results, floorplan)
```

**旋转处理** (简单版，不改 CP-SAT 模型):
- 电阻只有 2 pin (PLUS/MINUS)，旋转 = 交换 w/h + 更新 pin offset
- 在 `load_inputs()` 阶段对标记旋转的 device 交换 bbox 宽高和 pin 坐标
- pin_access mode: 旋转后 rhigh 的 PLUS/MINUS 从 "below"/"below" 变为 "left"/"right"
  → 需要在 route solver 中处理，或统一用 "direct" mode

### Step 3: 验证

```bash
cd /private/tmp/analog-trial/layout/

# 1. 重新生成 netlist.json (含旋转标记)
python3 gen_soilz_netlist.py

# 2. Per-zone 求解
python3 solve_placement_v2.py
# 检查: 每个 zone solver_status = OPTIMAL/FEASIBLE

# 3. 可视化 — 看图确认垂直堆叠 + 电阻横置
# (需要 viz script 支持旋转渲染)

# 4. Ties + Routing
python3 solve_ties.py
python3 solve_routing.py

# 5. 评估
# 目标: >120/141 nets (从 74 大幅提升)
```

## 要修改的文件

| 文件 | 改动 |
|------|------|
| `gen_soilz_netlist.py` | ZONES 合并, floorplan 重写, inter-zone channels, rotation, row_groups |
| `solve_placement_v2.py` | **新建**: per-zone 求解 + 旋转 + 坐标合并 |
| `netlist.json` | 自动生成 |
| `constraint_placer.py` | 可能不改 (per-zone 用现有 API 足够) |

## 风险

| 风险 | 缓解 |
|------|------|
| Zone 高度估算不准 | 估算 213µm << tile 313µm, 100µm 余量 |
| inter-zone corridor 行名方向错 | 代码中验证 above.y > below.y |
| 旋转后 pin access mode 失效 | 电阻只有 2 pin, 改为 "direct" mode |
| match_group 跨 zone 冲突 | 已合并 bias_ptat 消除唯一跨 zone match |
| per-zone HPWL 不含跨区 net | 可接受: 跨区路由由 corridor 结构保证 |
