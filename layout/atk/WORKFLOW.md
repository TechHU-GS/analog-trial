# ATK Layout Workflow v1.0

## Core Principles

### 1. 约束前置

**Phase N 的输入必须包含 Phase N+1 的全部硬约束。**

违反此原则的后果（L2 实证）：
- Phase 2 不含 NW.b1 → Phase 5 发现 NWell 间距不够 → 回 Phase 2
- Phase 3 不含 PCell M1 位置 → tie M1 和 PCell M1 冲突 → 打地鼠
- Phase 0 layer ID 错误 → 所有 well tie 画错层 → 全部返工

### 2. 目视确认必选

**每个 Phase Gate 必须包含 plot → 人眼确认 这一步。不可省略。**

数学保证约束满足，人眼保证"看起来对"。两者互补。
10 秒看一眼能发现求解器看不到的问题：

- 器件挤在一起走线过不去
- tie 放在了不该放的地方
- NWell 形状不对
- 信号流方向反了

违反此原则的后果（L2 实证）：
- Phase 2 放置完直接跑走线，DRC 炸了才回头看图，发现布局本身就有问题

每个 Phase 的可视化产物：

| Phase | 图 | 工具 | 关注点 |
|-------|---|------|--------|
| 2 | placement_plot | `atk/viz/placement_plot.py` | 行排列、间距、NWell 分离、信号流方向 |
| 3 | tie_plot | `atk/viz/placement_plot.py` + tie overlay | tie 位置、NWell bridge、M1 冲突 |
| 4 | routing_plot | `atk/viz/layout_plot.py` | 走线拥塞、短路风险、层分配 |
| 5 | drc_plot | `atk/viz/drc_debug.py` | DRC 违规位置、分类、回退目标 |

## 产物体系

```
atk/
  data/
    pdkdb.json          # 全量 DRC 规则 (BEOL + FEOL + LU + NBL)
    derived_rules.json  # DRC deck 派生规则 (nBuLay 阈值等)
    device_lib.json     # PCell 几何摘要 (M1/NW/pSD/Act/ports)
    tie_templates.json  # ntap/ptap 最小 footprint (Phase 2 输入)
    layers.json         # 层定义 (验证用, 防止 14↔31 类错误)
  pdk.py                # Python 常量 (从 pdkdb.json 派生)
  place/
    constraint_placer.py
  route/
    maze_router.py
  tie/
    tie_placer.py       # 数学方法放置 tie
  verify/
    spacing_check.py
    short_check.py
    drc_diagnosis.py
    gate_checks.py      # 每个 Phase 的 Gate 自检
  tests/
    test_regression.py
```

所有产物版本化，同输入 + 同 seed → 同输出。

---

## Phase 0: PDK 数据提取

**性质**: 一次性，跨设计复用。IHP SG13G2 做一次，所有 TTIHP 设计共用。

### 0a. DRC 规则 → pdkdb.json

来源: `sg13g2_tech_default.json` + `sg13g2_tech_mod.json`

```json
{
  "version": "sg13g2-v0.1",
  "beol": {
    "M1_a": 160, "M1_b": 180, "M1_d": 90,
    "M2_a": 200, "M2_b": 210, "M2_d": 144,
    "V1_a": 190, "V1_b": 210
  },
  "feol": {
    "NW_e": 240, "NW_b1": 1800, "NW_f": 240,
    "Act_a": 150, "Act_b": 210,
    "Cnt_a": 160, "Cnt_b": 180, "Cnt_c": 70,
    "pSD_d1": 30
  },
  "latchup": {
    "LU_a": 20000, "LU_b": 20000, "LU_d": 6000
  },
  "nbl": {
    "NBL_c": 3200, "NBL_d": 2200
  },
  "units": "nm"
}
```

**要求**: BEOL + FEOL + Latchup + NBL 全量提取，禁止按需补。

### 0b. PCell probe → device_lib.json

用 KLayout API 实例化每种 PCell，提取全部层几何。

```json
{
  "pmos_mirror": {
    "pcell": "sg13_lv_pmos",
    "params": {"w": 4.0, "l": 0.13, "ng": 10, "m": 1},
    "bbox": [0, 0, 5060, 2620],
    "origin_offset": [-310, -310],
    "shapes_by_layer": {
      "M1_8_0":  [[140, 90, 640, 690], ...],
      "NW_31_0": [[-310, -310, 5370, 2310]],
      "pSD_14_0": [[-180, -300, 5240, 2300]],
      "Act_1_0": [[0, 0, 780, 780], ...]
    },
    "ports": {
      "G": {"layer": "M1_8_0", "center": [590, -180]},
      "S": {"layer": "M1_8_0", "center": [150, 1000]},
      "D": {"layer": "M1_8_0", "center": [150, 1360]}
    },
    "keepout_M1": [[...]]
  }
}
```

**每个器件必须有**: bbox, shapes_by_layer (至少 M1/NW/pSD/Act), ports。
**空集显式声明**: `"NW_31_0": []` (NMOS 无 NWell)。

### 0c. DRC deck 派生规则 → derived_rules.json

手动审阅 `ihp-sg13g2.drc` 中所有 `.sized()` / `.not()` / `.join()` 操作。

```json
{
  "nbulay_gen": {
    "description": "nBuLay auto-generated from NWell",
    "formula": "nwell.sized(-1.495um).sized(0.495um)",
    "threshold": "NWell width >= 2990nm to trigger",
    "implication": "NWell extension must be < 2990nm wide to avoid NBL.c/d"
  }
}
```

### 0d. Tie 模板 → tie_templates.json

从 ntap1/ptap1 PCell + 规则推导最小 tie footprint。
**解决 Phase 2↔3 鸡生蛋问题**: Phase 2 用此常量预留空间。

```json
{
  "ntap_min": {
    "description": "Minimum NWell tie (N+ Activ in NWell)",
    "activ": {"w": 640, "h": 640},
    "nwell_extension": {"w": 1120, "h": 1120},
    "m1_pad": {"w": 600, "h": 600},
    "total_keepout": {"w": 1200, "h": 1200},
    "note": "extension width 1120 < 2990 threshold → no nBuLay_gen"
  },
  "ptap_min": {
    "description": "Minimum substrate tie (P+ Activ with pSD)",
    "activ": {"w": 640, "h": 640},
    "psd": {"w": 800, "h": 800},
    "m1_pad": {"w": 600, "h": 600},
    "total_keepout": {"w": 1000, "h": 1000}
  }
}
```

### 0e. 层定义 → layers.json

```json
{
  "ACTIV": [1, 0], "CONT": [6, 0], "NSD": [7, 0],
  "M1": [8, 0], "M2": [10, 0], "M3": [30, 0],
  "PSD": [14, 0], "NWELL": [31, 0], "NBULAY": [32, 0],
  "VIA1": [19, 0], "VIA2": [29, 0],
  "PWELL_BLOCK": [63, 0]
}
```

### Phase 0 Gate

- [ ] pdkdb.json: 每个 rule-id 有值、有单位、有作用层对
- [ ] device_lib.json: 每种器件至少含 M1/NW/pSD 几何或空集声明
- [ ] layers.json: 和 DRC deck `$1` 定义交叉验证
- [ ] tie_templates.json: keepout 尺寸 ≥ activ + enclosure
- [ ] derived_rules.json: 覆盖 DRC deck 中所有 `.sized()` 操作

---

## Phase 1: 电路输入

**性质**: 每次设计。

### 输出: netlist.json

```json
{
  "design": "ptat_vco",
  "devices": [
    {"name": "M1", "type": "pmos_mirror", "params": {}},
    {"name": "Q1", "type": "npn13g2_1x", "params": {"Nx": 1}},
    {"name": "MNb1", "type": "nmos_bias", "params": {}}
  ],
  "nets": [
    {"name": "vdd_vco", "pins": ["M1.S", "M2.S", "MPd1.S"]},
    {"name": "nmos_bias", "pins": ["MNb1.G", "MNb2.G", "MNb3.G", "MNb4.G"]}
  ],
  "constraints": {
    "match_groups": [["M1","M2","M3"], ["MPd1","MPd2","MPd3","MPd4","MPd5"]],
    "symmetry": [{"axis": "x", "devices": ["Q1", "Q2"]}],
    "keep_close": [["MPd1","MPd2","MPd3","MPd4","MPd5"]],
    "critical_nets": ["nmos_bias", "net_vco_ring"],
    "power_nets": ["vdd", "vdd_vco", "gnd"]
  }
}
```

### Phase 1 Gate

- [ ] 匹配对同 type、同参数域
- [ ] critical net 在 nets[] 中存在
- [ ] power net 声明完整
- [ ] **电气约束覆盖率**: 每条 signal net 的连接器件对中，至少有一对被某条约束覆盖 (matching / keep_close / x_align / y_align / same_row / electrical_proximity)。覆盖率 < 100% → WARN (可人工豁免，必须标注理由)
- [ ] **连接器件必须有近邻约束**: 同一 net 上直接串联的器件对 (drain-source / emitter-resistor) 必须有 proximity 约束

---

## Phase 2: CP-SAT 约束布局

**性质**: 每次设计。输入全部来自 Phase 0 + Phase 1 产物。

### 约束清单 (全部硬编码, 不可事后补)

| 类别 | 约束 | 来源 |
|------|------|------|
| 几何 | no-overlap, boundary, grid 量化 (5nm) | 基础 |
| BEOL | routing min_gap ≥ M2_b + wire_width | pdkdb.json |
| FEOL | NWell spacing ≥ NW_b1 (1800nm) between different NWells | pdkdb.json |
| FEOL | 或: 同电位 NWell 合并 (gap=0) | pdkdb.json |
| Tie 预留 | PMOS 上方预留 ntap_keepout.h (1200nm) | tie_templates.json |
| Tie 预留 | NMOS 下方预留 ptap_keepout.h (1000nm) | tie_templates.json |
| Power | M3 rail corridor 预留 (top/bottom) | 设计参数 |
| Analog | match_group 等间距 + 垂直对齐 | netlist.json |
| Analog | VCO stages: PMOS-NMOS 垂直对齐 | netlist.json |
| Analog | symmetry 轴 | netlist.json |

### CP-SAT 求解参数

```python
solver.parameters.random_seed = 42       # 确定性
solver.parameters.max_time_in_seconds = 60
solver.parameters.num_workers = 1         # 单线程确定性
```

### 输出: placement.json

```json
{
  "instances": {
    "M1": {"x": 310, "y": 27510, "type": "pmos_mirror",
           "bbox": [0, 0, 5060, 2620],
           "halo_routing": 700, "halo_tie_top": 1200}
  },
  "channels": [...],
  "tie_strips": {"pmos_top": {"y": 30200, "h": 1200}},
  "rail_corridors": {"vdd": {...}, "gnd": {...}}
}
```

### Phase 2 Gate

- [ ] 所有 instance 间距 ≥ max(routing_gap, NW_b1) (按 well 类型)
- [ ] tie strip 可达每个需 tie 的器件 (LU_a 距离检查)
- [ ] rail corridor 贯通 (x 方向连续)
- [ ] match group 等间距验证
- [ ] INFEASIBLE → 报告哪条约束冲突, 不要静默放宽
- [ ] **电气近邻**: 每条 signal net 的连接器件中心距 flag > 10µm 的为异常
- [ ] **inverter/bias pairing**: 同列 PMOS/NMOS 中心 Y 距离 ≤ max_dy_um
- [ ] **供电路径**: Riso 到 NWell_A 边界距离 ≤ max_distance_um
- [ ] **placement_plot → 人眼确认** (行排列/间距/NWell/信号流/inverter 配对)

---

## Phase 3: Tie + Guard Ring 自动放置

**性质**: 数学方法，约束求解。

### 输入

- placement.json (含 tie_strips 预留区)
- pdkdb.json (FEOL + LU + NBL)
- device_lib.json (PCell 内部 M1/NW/pSD)
- tie_templates.json (最小 footprint)

### 约束

| 规则 | 约束 | 值 |
|------|------|---|
| LU.a | ntap 到 PMOS P+Activ 距离 ≤ 20µm | 20000nm |
| LU.b | ptap 到 NMOS N+Activ 距离 ≤ 20µm | 20000nm |
| NW.e | NWell enclosure of tie Activ ≥ 240nm | 240nm |
| pSD.d1 | pSD to N+Activ in NWell ≥ 30nm | 30nm |
| M1.b | tie M1 to PCell M1 ≥ 180nm | 180nm |
| NBL | NWell extension width < 2990nm | 2990nm |
| Act.b | tie Activ to PCell Activ ≥ 210nm | 210nm |

### NWell bridge 逻辑

```
对同电位 NWell 对 (sorted by x):
  if gap < NW_b1 (1800nm):
    画 NWell bridge (L31/0) 连接两个 NWell
    → NW.b1 不适用于 same-net NWell
```

### 输出: ties.json

```json
{
  "ties": [
    {"inst": "M1", "type": "ntap", "center": [2840, 30180],
     "layers": {"NW_31_0": [...], "Act_1_0": [...], "Cont_6_0": [...], "M1_8_0": [...]},
     "net": "vdd_vco",
     "m1_keepout": [2540, 29880, 3140, 30480]}
  ],
  "bridges": [
    {"from": "M1", "to": "M2", "layer": "NW_31_0", "rect": [...]}
  ]
}
```

**关键**: 输出包含 m1_keepout，Phase 4 routing 用它做 obstacle。

### Phase 3 Gate

- [ ] 每个需 tie 的器件有对应 tie (LU.a/LU.b 覆盖)
- [ ] tie M1 与所有 PCell M1 距离 ≥ M1_b (180nm)
- [ ] NWell extension 宽度 < nBuLay 阈值 (2990nm)
- [ ] NWell bridge 只连同电位 NWell
- [ ] LU.a = 0, LU.b = 0 (几何计算验证)
- [ ] **tie_plot → 人眼确认** (tie 位置/NWell bridge/M1 冲突)

---

## Phase 4: Power + Signal Routing

**性质**: 算法化 (A* maze router + M3 power)。

### 输入

- placement.json
- ties.json (含 m1_keepout)
- pdkdb.json BEOL 规则
- device_lib.json (PCell M1/M2 shapes → obstacle)
- netlist.json (net 列表 + 优先级)

### 执行顺序 (固定)

1. M3 power rail (VDD, VDD_VCO, GND)
2. M2/M1 signal routing (net 排序: critical → 普通 → 按 name 字典序)

### Obstacle map 构成

```
PCell 内部 M1/M2 (from device_lib.json)
+ tie M1 keepout (from ties.json)
+ power rail M3/M2 drops
+ 已路由 net 的 used cells + margin
```

### Router 参数

```python
PIN_VIA_MARGIN_M1 = M1_b + wire_half_w  # 180 + 150 = 330nm
PIN_VIA_MARGIN_M2 = M2_b + wire_half_w  # 210 + 150 = 360nm
VIA1_PAD_M1 = VIA1_SIZE + 2 * M1_d      # 190 + 180 = 370nm
VIA1_PAD_M2 = VIA1_SIZE + 2 * M2_d      # 190 + 288 = 480nm
```

### Pin access 规则

```
NMOS gate (G): 'm1_pin' — 不放 via pad (G-S 距离 440nm < VIA1_PAD_M1 + M1_b = 550nm)
PMOS gate (G): 'gate' — via pad at gate pin position (below bbox, safe)
above/below: via pad + M1 stub outside device bbox
direct: via at pin position (resistors)
```

### Pin escape 不变量

```
escape 清除的 cell 集合 ∩ 其他 pin 的 pad blocking 区域 = ∅
(escape 后必须 re-block 所有 pad zones)
```

### Phase 4 Gate

- [ ] 所有 net routed (17/17)
- [ ] M1.b = 0, M2.b = 0, V1.b = 0 (ATK spacing check)
- [ ] M2 shorts = 0 (ATK short check)
- [ ] regression test 全 PASS
- [ ] **routing_plot → 人眼确认** (走线拥塞/短路风险/层分配)

---

## Phase 5: 全规则 DRC 验证

### 两段式

1. **ATK 快速检查** (秒级): M1.b, M2.b, V1.b, M2 short
2. **KLayout DRC** (分钟级, 权威): 全 deck

### 违规分类

| 分类 | 定义 | 回退 |
|------|------|------|
| real_placement | NW.b1, 无 tie 空间 | → Phase 2 |
| real_tie | LU.a/b, NBL, NW.e, tie M1 冲突 | → Phase 3 |
| real_routing | M1.b, M2.b, V1.b (routing shapes) | → Phase 4 |
| pcell_internal | CntB.h1 等 PCell 本体违规 | → Phase 0 或 waiver |
| layer_mismatch | 层 ID 在 pdkdb 和 device_lib 不一致 | → Phase 0 |
| waiver | IHP 确认的已知问题 | 标注 issue 编号 |

### Phase 5 Gate

- [ ] real_* 类违规 = 0
- [ ] waiver 有 IHP issue 编号
- [ ] pcell_internal 有 PDK 版本标注
- [ ] **drc_plot → 人眼确认** (DRC 违规位置/分类/回退目标)

---

## Phase 6: LVS

KLayout LVS: GDS vs SPICE netlist。

FAIL → 回 Phase 4 (修连接)。不动 placement/tie。

---

## Phase 7: PEX + 后仿

**性质**: 版图验证最终关卡。频率偏移 > 20% 则必须修正。

### 7a. PEX 寄生提取

**工具**: kpex (KLayout-PEX)

```bash
# 确保 venv 激活
source ~/pdk/venv/bin/activate

# kpex 2.5D 提取 (C-only, 无 R)
kpex --pdk ihp_sg13g2 \
     --gds /private/tmp/claude/ptat_vco.gds \
     --cell ptat_vco \
     --2.5D \
     --out_dir /private/tmp/claude/postlayout
```

**输出**: `<out_dir>/<cell>__<cell>/<cell>_k25d_pex_netlist.spice`

**关键指标** — 检查 VCO 节点 VSUBS 寄生:

```bash
grep "VSUBS;vco" <pex_output>.spice
# 各级 vco1-vco5 应接近 (差异 < 20%)
# vco5 (ring→buffer) 最关键, 目标 < 5fF
```

### 7b. PEX 网表修复

**工具**: `fix_pex_netlist.py`

kpex 输出的 SPICE 不能直接被 ngspice 识别 (IHP 器件是 subckt, 需 X 前缀):

```bash
cd /private/tmp/claude/postlayout
python3 fix_pex_netlist.py <kpex_output>.spice ptat_vco_pex.spice
```

**修复内容**:
| 原始 | 修复后 | 原因 |
|------|--------|------|
| `Q$N ...` | `XQ$N ...` | BJT subckt 需 X 前缀 |
| `M$N ...` | `XM$N ...` | MOSFET subckt 需 X 前缀 |
| `R$N net1 net2 <R> rppd ...` | `XR$N net1 net2 0 rppd ...` | rppd 3 端口 (bulk=0) |
| 无 VSUBS | `.SUBCKT ... VSUBS` | 衬底寄生需要端口 |

**⚠️ 陷阱**: `fix_pex_netlist.py` 的默认输入路径必须指向最新 kpex 输出。
如果默认路径指向旧提取结果，修复后的网表将包含旧器件参数，
但寄生电容是新的 → 结果完全错误且难以察觉。
**每次 PEX 后必须显式传入输入路径。**

### 7c. Port Order 同步

**⚠️ 重要**: 每次重新提取 PEX，.SUBCKT port order 可能改变。

```bash
# 1. 检查当前 port order
grep -A1 ".SUBCKT" ptat_vco_pex.spice

# 2. 更新 testbench 的 Xdut 行, 使端口顺序与 .SUBCKT 一致
#    gnd 对应 0, VSUBS 对应 0 (末尾)
```

**示例**:
```spice
* .SUBCKT ptat_vco gnd nmos_bias ns1 ns2 ... VSUBS
Xdut 0 nmos_bias ns1 ns2 ... 0
+    ptat_vco
```

### 7d. 后仿仿真

```bash
cd /private/tmp/claude/postlayout
ngspice -b test_postlayout.sp
```

**test_postlayout.sp 结构**:
```spice
.lib cornerMOSlv.lib mos_tt    * MOSFET 模型
.lib cornerHBT.lib hbt_typ     * BJT 模型
.lib cornerRES.lib res_typ     * 电阻模型
.lib cornerCAP.lib cap_typ     * 电容模型
.include 'ptat_vco_pex.spice'  * PEX 网表

Vdd vdd 0 DC 1.8
Xdut <port_order> ptat_vco

* 多温度仿真: -40, 0, 27, 85, 125°C
* 测量: 周期 → 频率, VPTAT, Vbias
```

### 7e. 频率不达标 → 参数扫描

**原则**: Python 做内循环，不打地鼠。

频率由 MNb (current limiter) 偏置电流主导:
```
f ∝ I_bias ∝ 1/L_MNb
```

**扫描脚本模板** (`sweep_mnb_l.sh`):

```bash
for L_VAL in 4.0 3.5 3.0 2.5 2.0 1.5 1.0; do
    # 1. sed 修改 PEX 网表中 MNb 的 L 参数
    sed "s/sg13_lv_nmos L=<old>U W=1U/sg13_lv_nmos L=${L_VAL}U W=1U/g" \
        ptat_vco_pex.spice > sweep/pex_L${L_VAL}.spice

    # 2. 创建临时 testbench → ngspice -b 运行
    # 3. 提取 3 个温度点频率
    # 4. 打印结果表格
done
```

**决策流程**:
1. 选择全温度 >33 MHz 的最大 L（保守选择）
2. 更新 4 个文件:
   - `probe_pcells_v2.py` — PCell 参数
   - `probe_pcells_p0.py` — PCell 参数 (备份)
   - `ptat_vco_lvs.spice` — LVS 参考网表
   - `sim/test_ptat_vco_v8.sp` — 前仿 testbench
3. 重新生成 device_lib.json → 重跑 pipeline → PEX → 后仿验证

**⚠️ 陷阱**: 改器件尺寸后 PCell bbox 变化 → CP-SAT 列间距可能不足 →
Phase 4 路由失败。修复: 给对应 row_group 加 `"gap_um"` 参数。

### 检查项

| 指标 | 前仿基准 | 后仿标准 |
|------|---------|---------|
| VCO 频率 | 47-54 MHz | 全温度 > 33 MHz |
| 温度系数 | ±5.1% | 偏移 < 2× |
| VPTAT 输出 | 单调递增 | 仍然 PTAT |
| 9-corner | 全振荡 | 全振荡 |
| MC 50/50 | 全起振 | 全起振 |
| VCO stage 寄生匹配 | N/A | 各级 VSUBS 差异 < 20% |

### FAIL 回退决策树

```
后仿频率偏低 (> 20%)
  ├─ vco5 寄生过大 (> 5fF)?
  │   └─ YES → Phase 2: buffer 移至 VCO 旁 (版图拓扑)
  ├─ 全局寄生均匀偏大?
  │   └─ YES → Phase 7e: 参数扫描 (MNb L ↓ 增加偏置电流)
  ├─ 器件参数提取有误?
  │   └─ YES → Phase 0: 重新 probe PCell (device_lib.json)
  └─ routing 耦合过强?
      └─ YES → Phase 4: 调整走线层分配

后仿 VPTAT 异常
  ├─ PTAT core 被干扰?
  │   └─ YES → Phase 2: PTAT 隔离 (增大与 VCO 距离)
  └─ 电阻寄生过大?
      └─ YES → Phase 4: Rout 走线缩短

后仿不振荡
  ├─ port order 错误? (最常见!)
  │   └─ YES → Phase 7c: 检查 .SUBCKT 端口对应
  ├─ fix_pex_netlist.py 读了旧文件?
  │   └─ YES → Phase 7b: 显式传入正确输入路径
  └─ 电路本身问题?
      └─ 检查 Vbias, VPTAT DC 工作点
```

---

## Quick Reference: 端到端命令

```bash
# ── 环境 ──
source ~/pdk/venv/bin/activate
cd /private/tmp/analog-trial/layout

# ── Phase 0: PCell 几何提取 (改器件参数后必须重跑) ──
klayout -n sg13g2 -zz -r probe_pcells_v2.py
# → atk/data/device_lib.json

# ── Phase 2-6: 一键 Pipeline ──
bash run_all.sh
# → placement.json, ties.json, routing.json
# → /private/tmp/claude/ptat_vco.gds
# → DRC + LVS 结果

# ── Phase 7: PEX + 后仿 ──
cd /private/tmp/claude/postlayout

# 提取
kpex --pdk ihp_sg13g2 \
     --gds /private/tmp/claude/ptat_vco.gds \
     --cell ptat_vco --2.5D \
     --out_dir /private/tmp/claude/postlayout

# 修复 (⚠️ 必须显式指定输入路径!)
python3 fix_pex_netlist.py \
    ptat_vco__ptat_vco/ptat_vco_k25d_pex_netlist.spice \
    ptat_vco_pex.spice

# 检查 port order → 更新 test_postlayout.sp
grep -A1 ".SUBCKT" ptat_vco_pex.spice

# 仿真
ngspice -b test_postlayout.sp

# ── 频率不达标? 参数扫描 ──
bash sweep_mnb_l.sh
# 选定 L 后更新: probe_pcells_v2.py, ptat_vco_lvs.spice, test_ptat_vco_v8.sp
# 回到 Phase 0 重跑
```

## 经验教训 (L2 实证)

### 频率偏移根因分析

L2 PTAT+VCO 后仿频率从 47 MHz 降到 28 MHz (42%↓)。排查过程:

1. **版图拓扑优化** (buffer→VCO 旁): vco5 寄生 ↓31%, 但频率仅 ↑2%
2. **器件 W 修正** (probe 参数错误): 必要的正确性修复, 但频率无变化
3. **参数扫描** (MNb L=4u→2.5u): 频率 ↑25% (28→35 MHz), **达标**

**结论**: 电流饥饿型 VCO 的后仿频率由 **偏置电流** 主导, 非版图拓扑。
寄生电容只是叠加项 (intrinsic device cap 仍占主导)。
修正方法是电路级调参 (减小 MNb L 增加偏置电流), 而非版图级微调。

### 工具链陷阱汇总

| 陷阱 | 症状 | 根因 | 修复 |
|------|------|------|------|
| fix_pex 读旧文件 | 频率不变 | 默认路径指向旧 PEX | 显式传入路径 |
| port order 变化 | 不振荡 / 错误频率 | kpex 每次提取端口顺序不同 | 每次检查 .SUBCKT |
| device_lib 缺 classification | Phase 3 KeyError | 用了 probe_p0 而非 v2 | 始终用 probe_pcells_v2.py |
| 改 L 后列间距不足 | Phase 4 路由失败 | PCell bbox 变小, x_align 压缩 | row_group 加 gap_um |
| PMOS ng=2 W 合并 | LVS W mismatch | KLayout 合并 2 finger → W×2 | LVS netlist 用 ng=1, W=total |
