# ATK — Analog Layout Toolkit

IHP SG13G2 130nm 模拟版图的代码驱动工具箱。
LLM+PY 架构：LLM 生成约束，Python 求解+验证。

## 架构总览

```
.sp 网表 ──→ atk/spice/parser.py ──→ parsed_spice.json
                                          │
                                          ▼
                                  ┌──────────────┐
                                  │  LLM (Claude) │  ← CONSTRAINT_SCHEMA.md + device_lib.json
                                  └──────────────┘
                                          │
                                          ▼ netlist.json
                                  ┌──────────────┐
                                  │  run_all.sh   │  ← Phase 2→6 一键
                                  └──────────────┘
                                          │
                    ┌─────────┬───────────┼───────────┬──────────┐
                    ▼         ▼           ▼           ▼          ▼
              placement   ties.json   routing.json   GDS     results
              .json                                          _summary
                                                             .json
```

**双进程架构**:
- `solve_*.py` 用 venv Python (有 ortools/shapely/gdstk)
- `assemble_gds.py` 用 KLayout Python (有 pya，无 ortools)
- 验证/可视化用 venv Python

## 运行入口

```bash
cd /private/tmp/analog-trial/layout
source ~/pdk/venv/bin/activate
bash run_all.sh    # Phase 2→6 全自动 (推荐)
bash run.sh        # Phase 2→5 (旧入口，无 LVS)
```

`run_all.sh` 执行:
1. CP-SAT placement → `placement.json`
2. Tie placement → `ties.json`
3. Signal routing → `routing.json`
4. GDS assembly → `ptat_vco.gds`
5. KLayout DRC
6. KLayout LVS
7. Results summary → `results_summary.json`

## 模块清单

### `atk/spice/` — SPICE 解析 + 约束验证

| 模块 | 功能 |
|------|------|
| `parser.py` | .sp → structured JSON (M/Q/R/X prefix, topology detection) |
| `validate.py` | netlist.json 完整性检查 (12 项: device/pin/row/power/routing) |

```bash
python -m atk.spice.parser input.sp              # → parsed JSON
python -m atk.spice.validate [netlist.json]       # → PASS/FAIL + 缺失项
```

**Parser 能力**: 电流镜检测、环振检测、反相器链检测、power net 识别。

### `atk/CONSTRAINT_SCHEMA.md` — 约束参考文档

netlist.json 每个字段的 type/required/default。LLM 生成约束时的手册。

### `atk/place/constraint_placer.py` — CP-SAT 摆放器

OR-tools CP-SAT 约束求解器，模拟版图专用:

```python
placer = ConstraintPlacer(devices, grid=0.10)
placer.setup(max_width=120.0, max_height=80.0)
placer.add_row('pmos_mirror', ['M1','M2','M3','M5'], gap=1.0)
placer.add_row_spacing('pmos_mirror', 'hbt', n_tracks=3)
placer.add_nwell_spacing(islands, min_gap_um=1.8)
placer.add_zone_isolation(zones, min_gaps)           # 隔离区强制
placer.set_nets(signal_nets, device_pins)            # 线长感知
placer.minimize_area_and_wirelength(wl_weight=0.5)   # HPWL 目标
result = placer.solve(time_limit=60.0)               # seed=42, 1 worker
```

**约束类型** (14 种):
- `add_row()` — 同类器件成行
- `add_row_spacing()` — 行间距 (routing track 数)
- `add_tie_strip()` — Tie 空间预留
- `add_same_y()` / `add_x_align()` — 对齐
- `add_x_order()` / `add_y_range()` — 序/距离约束
- `add_no_overlap()` — 全局无重叠 + 路由间距
- `add_nwell_spacing()` — NWell 岛间距
- `add_equal_spacing()` — 匹配组等间距
- `add_symmetry_y()` / `add_adjacent()` — 对称/邻近
- `add_zone_isolation()` — 隔离区最小间距 (NEW)
- `set_nets()` + `minimize_area_and_wirelength()` — HPWL 线长感知 (NEW)

**确定性**: `random_seed=42` + `num_workers=1` (必须，否则非确定性导致 LVS 失败)

### `atk/route/` — 路由引擎

| 模块 | 功能 |
|------|------|
| `maze_router.py` | A* 双层迷宫路由 (M1+M2, 350nm grid) |
| `access.py` | Pin access 计算 (6 种模式) |
| `power.py` | M3 power rail + Via drop + vbar jog + via_stack |
| `solver.py` | 路由编排 (obstacle map + maze 调度) |

### `atk/tie/tie_placer.py` — Tie 自动放置

Strip-based per-device。每个 PMOS 上方 ntap，每个 NMOS 下方 ptap，X 对齐 source pin。
自动 M1 冲突避让 (`_resolve_m1_clear_x`)。

### `atk/verify/` — 快速 DRC 预检

| 模块 | 功能 | 速度 |
|------|------|------|
| `routing_check.py` | M1.b/M2.b/V1.b + shorts + connectivity + diagonals | < 2s |
| `spacing_check.py` | M1.b/M2.b/V1.b 间距 | < 1s |
| `short_check.py` | M2 短路检测 | < 1s |
| `connectivity_audit.py` | UnionFind 链式连通性 | < 1s |

### `atk/viz/` — 可视化

| 模块 | 功能 |
|------|------|
| `layout_plot.py` | GDS matplotlib 渲染 (按层/网着色) |
| `placement_plot.py` | 摆放结果可视化 |
| `drc_debug.py` | DRC violation 坐标叠加 |

### `atk/summary.py` — 结果汇总

```bash
python -m atk.summary --placement=placement.json --drc-dir=/tmp/drc_run --lvs-dir=/tmp/lvs_run --cell=ptat_vco
```

输出 `results_summary.json`: placement status + DRC markers + LVS pass/fail。

### `atk/device.py` — Device Library 加载器

统一 device_lib.json 访问接口。

### `atk/paths.py` — 路径常量 (SSOT)

所有 JSON 文件路径的单一真相源。

### `atk/pdk.py` — PDK 常量

DRC 规则、层定义、路由参数。Import 时自动断言一致性。

## 三层金属架构

```
  Metal3 (M3):  ═══════ VDD_VCO ═══════  3µm power rails (horizontal)
                ═══════ VDD     ═══════
                ═══════ GND     ═══════
                        │ Via2 drops
  Metal2 (M2):  ────────┤ signal routing (free)
                        │ Via1
  Metal1 (M1):  ────────┘ local connections (PCell + stub)
```

## 数据文件

| 文件 | 内容 | 阶段 |
|------|------|------|
| `atk/data/device_lib.json` | 15 种器件几何 (bbox, pins, shapes) | Phase 0 |
| `atk/data/pdkdb.json` | 375 DRC 规则 | Phase 0 |
| `netlist.json` | 30 devices + 20 nets + 全部约束 | Phase 1 |
| `placement.json` | CP-SAT 求解结果 | Phase 2 |
| `ties.json` | 24 tie cells | Phase 3 |
| `routing.json` | 17 signal nets + power topology | Phase 4 |
| `results_summary.json` | 全流程汇总 | Phase 6 |
