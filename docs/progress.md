# Progress & Decision Log

> Read this after compact to restore context.

---

## Current Status (2026-03-15 20:00)

### FREEZE BACKUP FOUND — SoilZ 完整版可恢复

```
/Users/techhu/Code/GS_IC/designs/analog-trial-FREEZE-20260315_013222/
  layout/assemble_gds.py    — 4261 lines (SoilZ 完整版)
  layout/netlist.json       — 143 nets, 249 devices, 25 constraint keys
```

**下一步：从 FREEZE 恢复 assemble_gds.py 和 netlist.json，然后 apply tie trim。**

### 本 session 成果（已验证）

1. **gnd↔vdd 根因 PROVEN**: `connect(pwell, ptap)` 是 bridge trigger
   - 移除全部 ptap PSD → merged=0（custom Ruby LVS 验证）
   - 某些 ptap Conts 坐在 vdd metal chain M1 上
   - binary search 找到 `tie_MBn1_ptap` 是一个具体 bridge

2. **因果 bisection 实验（决定性）**:
   - nwell↔ntap ON + pwell↔ptap OFF → gnd 和 vdd **分开** ✅
   - pwell↔ptap ON + nwell↔ntap OFF → gnd,pmos_bias,vdd **merge** ❌
   - **结论**: ntap 侧排除，bridge 100% 在 ptap 侧

3. **已定位的具体 bridge 点**:
   - **BUF_I ptap** `[100000,249325]-[100300,249965]`: ptap Cont 坐在 vdd M1 chain 上
     - 移除 2 个 Cont → ptap→vdd chain = 0（verified）
     - 位置在 BUF_I_n (y=257) 下方，MUX PMOS (y=250.5) NWell 边缘
   - **pmos_bias M1 bridge** `[50910,143310]-[51390,147680]`: 同一个 480×4370nm M1 shape 同时属于 pmos_bias chain 和 gnd chain
     - 两个 Via1 分别连 pmos_bias M2 (y≈145) 和 gnd M2 (y≈147)
     - 切掉 gnd 侧 Via1 → pmos_bias 逃出 merge（verified）
     - 位置在 PM_pdiode (pmos_cs, 48350,143000) / MN_pgen (nmos_bias, 51000,146500) 区域
   - **tie_MBn1_ptap** `[194470,166295]-[194830,166995]`: binary search 定位的 bridge ptap

4. **merge 收敛过程**（每步已验证）:
   - 起始: 5 nets merged (gnd,pmos_bias,vdd + 其他)
   - via encoding fix + BEOL trim → gnd,pmos_bias,vdd (3 nets)
   - 切掉 pmos_bias↔gnd Via1 bridge → gnd,vdd (2 nets)
   - 移除全部 ptap PSD → merged=0（证明 ptap 是唯一剩余路径）

5. **脏 GDS 状态污染教训**:
   - 在多次 ad-hoc patch (SalBlock + Cont removal + PSD restore) 后
   - 继续删 MBn1_ptap Cont → 反而导致 10-net merge（状态不一致）
   - **结论**: 不能在脏 GDS 上继续打地鼠，必须回到干净 GDS + 系统性 tie trim

6. **Floating M2 vdd label**: trace 从 M2 vdd label 出发结果为空（M2=0, M1=0），不影响 merge

7. **Tie M1 trim 方案 VERIFIED**: 在 L2 assembly 上实现并验证 merged=0
   - routing M1 + signal AP stubs + cross-net power M1 检查
   - tie_net: 'vdd' if 'ntap' else 'gnd'
   - threshold: -200nm
   - 71 ties trimmed → merged=0（但仅在 L2 不完整 build 上验证）

8. **已提交的代码**:
   - maze_router.py via encoding fix（commit 9a69f8f）
   - 11 diagnostic Ruby LVS scripts（commit 730ff10）
   - SoilZ placement + design data（commit c84a142）
   - L2+trim assembly（commit 3cc9df3）— 需要用 FREEZE 版本替换

9. **自定义 LVS diagnostic scripts**（layout/debug_lvs/）:
   - debug_extract.lvs — 自定义 LVS with derived layer logging
   - debug_find_ptap_vdd.lvs — trace ptap→vdd chain
   - debug_find_pmos_bias_taps.lvs — trace pmos_bias chain 到 taps
   - debug_isolated_wells.lvs — bisection: wells disconnected from taps
   - debug_ntap_only.lvs / debug_ptap_only.lvs — 单侧 well↔tap 开关
   - find_all_abutt.lvs — salicide abutment detection

### 本 session 破坏（需修复）

1. **assemble_gds.py**: SoilZ 4261行版本被 `git checkout --` 毁掉
   - **恢复源**: FREEZE 备份 4261行
   - 需要 apply: M3 vbar fix + tie trim（2 edits）

2. **netlist.json**: SoilZ 完整版被 `git checkout --` 毁掉
   - **恢复源**: FREEZE 备份（143 nets, 25 constraint keys）

3. **placement.json**: 被 TFF widening 修改过
   - **恢复源**: FREEZE 备份

### 当前 session 干净基线 (2026-03-15 21:00)

1. **FREEZE 恢复** ✅ — assemble_gds.py 4261行 + 9 edits (6 planned + 3 fixes)
2. **9 edits applied** to assemble_gds.py:
   - M3 vbar 截断 (2) — 用 power.py 截断范围替代 pin_y/rail_y
   - Tie trim threshold -20→-200 (1) + AP stubs/power M1 加入 trim (2)
   - `dir()→globals()` bug fix (1) — __file__ scope in function
   - Cross-net via_stack stub truncation (1) — 未生效，见下
   - Post-process: bridge M1 removal (1) — 也未解决 merge
3. **Pipeline 跑通**: ties 245 GATE 7/7, routing 133/0, assembly OK
4. **LVS**: `gnd,pmos_bias,vdd` 仍然 merged
5. **ptap PSD 全移除 → vdd 逃出** (只剩 gnd,pmos_bias) — 与上 session 一致
6. **pmos_bias↔gnd bridge 确认存在** — 位置与上 session 一致
   - 已知 bridge 区域: PM_pdiode.D (pmos_bias) ↔ MN_pgen.S (gnd) at x≈51150, y≈143000-148000
   - mystery M1 [51020,144845]-[51280,145445] 在 top cell（来源未确认）
   - 移除该 mystery M1 后 **LVS 仍 merge** — 说明不止一条 bridge 路径

### BREAKTHROUGH: merged groups = 0 达成 (2026-03-15 ~22:30)

**4 个定点 patch → 所有 net 完全分离。** 已验证。

| # | Patch | 类型 | 验证 |
|---|-------|------|------|
| 1 | `tie_MN_pgen_ptap` M1 bar 移除 | pmos_bias↔gnd bridge (330nm M1 overlap with PM_pdiode.D) | ✅ pmos_bias 脱离 |
| 2 | `tie_BUF_I_n_ptap` PSD 移除 | vdd-bridge ptap (100150, 249645) BUF area | ✅ paired test |
| 3 | `tie_SW2n_ptap` PSD 移除 | vdd-bridge ptap (141660, 83965) DAC switch area | ✅ paired test |
| 4 | `tie_T1I_s3_ptap` PSD 移除 | vdd-bridge ptap (69350, 190645) TFF divider area | ✅ paired test |

**方法**: ptap PSD binary search + paired testing (MBn1 as gnd background)。
在 121 个 ptap 中找到 3 个 vdd-bridge ptap，每个独立验证。

**LVS 输出**: `Merged groups: 0` — 运行命令和输出见 session 记录。

### 根因完全解析 (2026-03-16)

**两类根因：**

**A. 局部桥（M1 level, 已代码修复 1/2）：**
1. `tie_MN_pgen_ptap` M1 bar (gnd) ↔ PM_pdiode.D m1_pad (pmos_bias): 330nm overlap
   → **代码修复 ✅**: 实重叠检测 trim（assemble_gds.py）
2. `tie_SW2n_ptap` M1 bar (gnd) ↔ `tie_M_ia_p_ntap` M1 bar (vdd): 260×110nm overlap
   → **GDS patch 验证 ✅, 代码修复待做**: tie-vs-tie cross-net overlap trim

**B. 系统性桥（M3 level, GDS patch 验证）：**
- `ptap → pwell`（全局导体）→ 所有 121 ptap → 金属链向上爬升
- M1 → Via1 → M2 → Via2 → M3 → 部分 M3 在 VDD rail 附近（5nm-1000nm）
- KLayout Region merge 将这些 M3 与 VDD rail 视为连通 → gnd=vdd
- **GDS patch 验证 ✅**: 移除 184 个 VDD-adjacent 非 rail M3 → merged=0
- **代码修复待做**: assembly 级 rail-adjacent M3 filter

**完整 bridge 机制：**
```
ptap → pwell (全局) → 121 ptap → Cont → M1 → Via1 → M2 → Via2 → M3
                                                                    ↓
                                              M3 shapes 在 VDD rail 附近
                                                    (5nm-1000nm gap)
                                                         ↓
                                            LVS Region merge → gnd = vdd
```

### 代码修复状态 — MERGED GROUPS = 0 达成 ✅ (2026-03-16 09:21)

**纯代码级修法，无 GDS post-process patch。**

| Fix | 类型 | 状态 | 效果 |
|-----|------|------|------|
| tie M1 实重叠 trim | assemble_gds.py | ✅ | pmos_bias 脱离 |
| tie-vs-tie cross-net overlap | assemble_gds.py | ✅ | SW2n bridge 切断 |
| M3 cross-net rail/vbar cleanup | assemble_gds.py | ✅ | 系统性 M3 bridge 清除 (1 shape) |
| power.py vbar spacing + sandwich | power.py | ✅ | 辅助（减少 M3 proximity） |

**LVS 验证命令和输出：**
```
python3 ~/pdk/IHP-Open-PDK/.../lvs/run_lvs.py --layout=output/ptat_vco.gds \
    --netlist=ptat_vco_lvs.spice --run_dir=/tmp/lvs_v3 \
    --topcell=ptat_vco --allow_unmatched_ports
→ Merged groups: 0
→ 7 M1 trimmed, 1 M3 cross-net shape removed
→ Routing: 133/0 intact
```

### LVS Mismatch 主因：12 disconnected NWell islands (2026-03-16 10:00)

**358 unmatched nets 的主因**：15 PMOS on 12 NWell islands have bulk NOT on vdd.
Pre-existing issue masked by the merge.

**根因**: Signal-only PMOS (transmission gates, cascodes) 没有 vdd power drop。
ntap tie 只到 M1，无 Via1→M2→Via2→M3→vdd rail chain。
NWell island 与有 vdd drop 的 neighbor 没有物理 NWell 连接 → bulk 浮空。

**验证修法**: NWell bridge fill — 画 NWell rectangle 连接 isolated island 到
有 vdd drop 的 neighbor island。PM_cas_diode 单点验证：15→14 wrong bulk ✅。

**NWell bridge 验证结果 (2026-03-16 10:10):**

7 safe bridges tested individually → 6 PMOS fixed (15→9 wrong bulk).
1 bridge (Mchop2p→Mp_load_n) causes merge — too tall, crosses signal routing.
Remaining 9 wrong-bulk PMOS: Mchop2p, Mdac_tg1p/2p, SW1p, + others in islands
without safe bridge paths.

| Bridge | From → To | Size | Safe? |
|--------|-----------|------|-------|
| Mchop1p→Mp_load_p | [43200,70215]-[45000,82000] | 1800×11785 | ✅ |
| Mchop2p→Mp_load_n | [48880,70215]-[50680,82000] | 1800×11785 | ❌ merge |
| PM_cas1→PM_cas_ref | [119800,105215]-[123100,109500] | 3300×4285 | ✅ |
| PM_cas2→PM_mir1 | [127800,106215]-[130900,109500] | 3100×3285 | ✅ |
| PM_cas3→PM_mir1 | [135400,106215]-[139100,109500] | 3700×3285 | ✅ |
| PM_cas_diode→PM_cas_ref | [112000,105215]-[115300,109500] | 3300×4285 | ✅ |
| SW2p→M_db1_p | [147000,82035]-[152070,85500] | 5070×3465 | ✅ |
| SW3p→M_nb_p1 | [151070,82035]-[152870,85500] | 1800×3465 | ✅ |

### Wrong-bulk root cause fully traced (2026-03-16)

**Root cause**: `power.py::_resolve_m3_vbar_rail_conflicts()` truncates 7 vdd
power drops' M3 vbar to avoid crossing gnd rails. Truncation disconnects them
from target vdd rail (gap 10µm+). These drops serve NWell islands for 15 PMOS.

**All fix approaches exhausted at assembly level:**
- M3 vbar full-range: creates pmos_bias,vdd merge (M2 underpass in congested area)
- M2 underpass: gnd_bias corridor occupied by pmos_bias signal routing
- M4 bridge: signal M4 routing fills corridors (60nm gap to existing M4)
- M3 direct segment: signal M3 routing fills corridors
- NWell bridge fill: fixes 12 but creates 6 new wrong-bulk (Region merge topology change)

**Conclusion**: 15 PMOS wrong-bulk is a **placement/routing upstream limitation**.
The devices are placed where no metal corridor exists for vdd power access.
Assembly post-processing cannot fix this.

### Final session status (updated 2026-03-16 14:00)

| Metric | Value | Status |
|--------|-------|--------|
| Merged groups | **0** | ✅ Code-level, stable |
| Device count | 245 MOS + 4 R | ✅ Match |
| Pin count | 143 | ✅ Match |
| PMOS wrong bulk | 15 | ❌ Upstream limitation |
| Unmatched nets | 358 | ❌ Net fragmentation (not wrong-bulk cascade) |
| DRC violations | **216** | ⚠️ Triage done, systematic fixes started |

### DRC/LVS triage findings (2026-03-16)

**DRC 重新分析** (208→216 after first fix round):
- M1.b(34): M1 spacing — routing code systematic
- M3.d(38): M3 min area — stubs too small, partial fix applied
- M4.b(21): M4 spacing — routing code
- NW.c(23): NWell enclosure — placement/assembly
- pSD.c(26): pSD enclosure — PCell/assembly
- Cnt.b(15): Contact spacing — dense arrays
- 硬错误已消除: Cnt.j, Gat.f, V1.a 在重新计数中未出现

**LVS 重新分析**:
- 358 unmatched 是 **net fragmentation**，不是 wrong-bulk 级联
- 99 named nets + 259 anonymous fragments
- 44 SPICE nets 完全未提取（TFF 内部节点）
- 修 routing 连通性可以改善

**已完成的修改**:
1. pdk.py: 添加 M3_MIN_AREA, M4_MIN_AREA = 144000nm²
2. assemble_gds.py: M3 bbox stub min-area enforcement
3. constraint_placer.py: 修 add_max_aspect() + solve() return (placer 可跑但 INFEASIBLE)
4. power.py: 添加 per-drop vbar truncation debug logging
5. **maze_router.py**: 修 `_reconnect_components()` Via2/Via3 graph bug + `_insert_junction_vias()` M2↔M3, M3↔M4 junction 支持

**Placer 状态**: 2 个 bug 已修，但当前约束集 INFEASIBLE。
当前手工 placement (MANUAL_V3.3b) 是折衷方案。

### maze_router Via junction fix 结果 (2026-03-16 15:00)

**根因**: `_reconnect_components()` 只识别 Via1 (layer code -1)，Via2(-2) 和 Via3(-3) 对 graph 不可见 → M2↔M3, M3↔M4 连接断裂 → 79/133 signal nets 碎片化

**修法**: `if lyr == -1:` → `if lyr < 0:`，按 via code 映射到上下两层 metal。同时在 `_insert_junction_vias()` 加 M2/M3 和 M3/M4 junction via 插入。

**验证结果**:
- Routing.json 碎片 nets: 79 → **0** ✅ (connectivity audit 验证)
- LVS unmatched: 358 → **303** (-55) ✅ (lvsdb 解析验证)
- Merged mega-nets: **0** (lvsdb 文本中无逗号分隔的长 net name)
- Routing: 133/0 intact ✅

**⚠️ 未验证**: 硬错误(Cnt.j/Gat.f/V1.a) 在新 DRC 中是否仍存在（需重新跑 DRC 确认）

### 代码审查 + 修复 (2026-03-16 15:00-15:40)

**系统审查发现的 bug（solver.py + access.py + assemble_gds.py）：**

| Bug | 严重性 | 状态 |
|-----|--------|------|
| optimize.py prune_loops 删 Via2/Via3 | 致命 | ✅ 修复 (`s[4] < 0`) |
| optimize.py prune_redundant_vias 错误 layer pair | 致命 | ✅ 修复 (lo/hi decode) |
| access.py 旋转设备 pin 坐标不处理 rotation | 致命 | ⚠️ 已确认，修复尝试失败（坐标系理解有误），需重新调查 |
| 138 AP Via2 被 M3 冲突 skip | 高 | ⚠️ 未验证是否是 303 unmatched 主因 |
| maze_router Via2/Via3 used marking 缺失 | 高 | ❌ 尝试修复但导致 3 net routing failure，已还原 |

**optimize.py 修复效果**: LVS 无变化（303→303），说明当前 routing 中 Via2/Via3 没有被 optimize 误删。修复是防御性的。

**教训**:
1. access.py rotation fix 失败是因为没有先验证坐标数学——直接写代码跳过了 gather→verify 步骤
2. Via2/Via3 used marking 在当前 grid 密度下过度阻塞，需要更精细的 margin 策略

### Next steps

1. ✅ M3 min-area enforcement (partial: 46→38)
2. ✅ maze_router Via junction fix (routing 碎片 79→0, LVS 358→303)
3. ✅ optimize.py Via2/Via3 保留（防御性修复）
4. ⚠️ access.py rotation — 需要先手动验证 3 个旋转电阻的正确 pin 坐标，再写修复
5. ✅ Via2 constraint solver 构建并验证 (atk/solve_via2.py + atk/apply_via2.py)
6. ⬜ Via2 solver 加 M2 bridge conflict check（当前 patch 引入 1 个 merge）
7. ⬜ DRC 系统性修法（M1.b, M4.b, NWell/pSD）
8. ⬜ 最终 DRC + LVS 验证

### Via2 Constraint Solver 结果 (2026-03-16 16:15)

**思路转变**：从"启发式 scan"转为"klayout.db 计算几何求解"。
用 Region boolean ops 计算 M3 可用空间，对每个 pin 搜索最优 Via2 位置。

**结果**：
- 270 个 pin 需要 assembly Via2
- Solver 找到 231 个可行位置（85%），39 个 truly blocked
- Applied to GDS → LVS: 276 → **179** (-97, -35%)

**问题**：patch 引入 1 个 merged net（gnd + 大量信号 net）。
原因：solver 只检查 M3 spacing，没检查 M2 bridge 是否跨越其他 net 的 M2 shapes。
修法：给 solver 加 M2 conflict check（同样用 klayout.db Region）。

**LVS 完整进展**：
| 阶段 | Unmatched | Delta |
|------|-----------|-------|
| Baseline | 358 | — |
| maze_router fix | 303 | -55 |
| SCAN_RADIUS 2000 | 276 | -82 |
| Via2 solver patch | 179 (1 merge) | -179 |

**最终结果 (v6 + greedy merge-safe filter):**
- 178 viable positions found, 51 accepted (greedy filter rejects 127 to prevent merge)
- Applied as GDS post-patch: `python3 -m atk.solve_via2 && python3 -m atk.apply_via2`
- **LVS on patched GDS: 269 (merged=0)** ✅
- Base GDS (without patch): 276

**⚠️ 注意：269 需要跑 solver post-step，不是 assembly 自动生成的。**
Solver 集成到 assembly pipeline 是下一步。

**Solver 约束层**:
1. M3 pad clearance (M3.b = 210nm + pad half = 190nm)
2. M2 bridge cross-net check (connectivity-based net identification)
3. M3 bridge feasibility (Via2→anchor M3 bridge vs cross-net M3)
4. Greedy merge-safety filter (incremental LVS check, accept if merge count ≤ baseline)

### Session 最终状态 (2026-03-16 17:35)

| 指标 | 起始 | Base GDS | Patched GDS | 目标 |
|------|------|----------|-------------|------|
| LVS unmatched | 358 | 276 | **248** | 0 |
| LVS merged (big) | 0 | 0 | 0 | 0 |
| LVS comma-merges | 1 | 1 | 3 | 0 |
| Routing 碎片 | 79 | **0** | 0 | 0 |
| DRC | 208 | ~216 | 未测 | 0 |

**Base GDS = assembly 直接输出 (276)。Patched GDS = solver post-patch (248)。**

### 已定位但未修的 bug（下一 session 可直接修）

1. **5 个 cross-net M2 pad overlap**（精确坐标+net 已知）
   - MBp1.G(vco5) ↔ MBn1.D(buf1): 350×65nm overlap
   - MBp2.G(buf1) ↔ MBn2.D(vco_out): 10nm gap
   - PM_pdiode.D ↔ MN_pgen.S: 160nm gap
   - Mdac_tg2n.S ↔ Mp_load_n.S: 160nm gap
   - Mchop2p.D ↔ Mtail.S2: 160nm gap
   → 修 `_shrink_ap_m2_pads_gds` 添加 cross-net spacing check

2. **access.py rotation bug**（3 设备 4 nets: vptat, dac_out, chop_out, sum_n）
   → 修 `abs_pin_nm` 加 rotation transform（需要先手算坐标验证）

3. **15 wrong-bulk**（placement limitation，power.py vbar truncation）
   → 需要 placement 层面修复

4. **optimize.py M3/M4 straighten_chains 不处理**
   → 扩展 `for ly in (0,1)` 到 `(0,1,2,3)`

### 剩余 246 unmatched 分类 (2026-03-16 18:15)

| 类别 | 数量 | 修法 |
|------|------|------|
| Solver-patched 但仍 unmatched | 39 | Via2→M3 连接不完整，需调查 |
| Signal routing (非 Via2 问题) | 18 | 可能缺 Via2 或 M2 gap |
| TFF 2-pin internal | 11 | stacked FET 内部节点 |
| Wrong-bulk/cascode | 9 | placement 限制 |
| Divider chain | 9 | 高 fanout net 部分 pin 未连通 |
| Comparator/latch | 4 | comp_outn/p, lat_q/qb |
| Single-pin (ext port) | 3 | sel0, sel1b, vref_ota — 无需路由 |
| Excitation/NAND | 3 | 信号连通性 |
| VCO internal | 2 | ns1, vco_out |

### 已修复的 assembly bugs

| Bug | 文件 | 修法 | 效果 |
|-----|------|------|------|
| `_try_shrink` 不处理双轴 overlap | assemble_gds.py:839 | 加 `elif x_gap < 0 and y_gap < 0:` 分支 | +1 pad shrink (48→49) |
| PCell rotation degrees vs code | assemble_gds.py:2045 | 发现但未修（需 pipeline-wide 修改） | — |
| M3_MIN_AREA 缺失 | pdk.py | 加 M3/M4_MIN_AREA = 144000 | M3.d 46→38 |
| SCAN_RADIUS 过小 | assemble_gds.py:1437 | 700→2000nm | skip 137→107 |

### 本 session 教训

1. **先查基线再建工具** — 没提前查 pre-existing comma-merges，导致 merge 检测反复修改
2. **计算几何 >> 启发式** — klayout.db Region ops 秒级完成，assembly heuristic scan 失败率高
3. **Via2 placement 的真正约束是 M3 层累积效应** — 独立安全 ≠ 组合安全
4. **Post-patch 不是最终形态** — solver 结果需要集成到 assembly pipeline
5. **PCell rotation 是 pipeline-wide 问题** — 不能只改一个环节
6. **klayout.db LayoutToNetlist.probe_net 是最精确的 net 查询工具** — 比 Region boolean 更准
7. **Greedy sweep 虽慢（12分钟）但是唯一可靠的 merge-safe 过滤** — 纯几何检查误拒/漏检都有

### Layout 健康检查结果 (2026-03-16 19:20)

**placement 有根本性问题：**
- **105 个 floorplan zone 违反** — 设备不在 netlist.json 定义的区域里
- **3 个电阻旋转 bug** — PCell 未旋转但 bbox 是旋转后的
- **Rout ↔ Rptat 物理重叠** — 9×3.6µm
- **Placer INFEASIBLE** — 约束和实际 placement 不一致

**结论：当前 MANUAL_V3.3b placement 是在有缺陷的基础上手工调整的。继续在这个 placement 上打补丁效率极低（session 已证明：358→240 但每步收益递减）。**

**决策点：推倒重做 placement（修约束→重跑 placer→全 pipeline），还是继续在当前 placement 上修？**

⚠️ "推倒重做半天到一天" 是估计，未验证。placer 放松约束后能否出 FEASIBLE 解待测试。

### Placer INFEASIBLE 根因 (2026-03-16 19:00)

**Rptat = 9.06 × 135.54 µm（占芯片高度 55%）。** 49 rows 垂直堆叠总高 347µm，芯片只有 243µm。Row-based 模型无法表达"Rptat 旁边放设备"的 2D 布局。即使去掉所有约束（floorplan/sub_region/matching/isolation），仍然 INFEASIBLE。当前手工 placement 通过 2D 安排解决了这个问题，但 solver 做不到。

### Pipeline 审计 + L2/SoilZ 分离 (2026-03-16 19:30-20:00)

**文件完整性审计结果：**

| 文件 | L2 | SoilZ | 状态 |
|------|-----|-------|------|
| 前仿 SPICE (原始) | sim/cmos_ptat_vco.sp (37 dev) ✅ | ❌ 分块 SPICE 未找到 | SoilZ 从未有完整前仿 |
| netlist.json | — | ✅ 249 dev (soilz_v1) | SoilZ sole source of truth |
| LVS SPICE | — | ✅ 自动生成 | 从 netlist.json 派生 |
| 前仿验证 | ✅ 9/9 corners | ⚠️ 分块验证 (设计文档记录) | 全电路前仿从未做过 |

**SoilZ 设计来源：LLM 直接写原理图 → 分块验证 → 手工/LLM 合并到 netlist.json。**
分块 SPICE 文件（soilz_current_src.sp 等 6 个）在 soilz_design.md 有记录但文件不在磁盘上。

**已完成的整理：**
- `sim/soilz/soilz.sp` — 从 netlist.json 重建的 249-device SoilZ SPICE（新建）
- `layout/ptat_vco_lvs.spice` — 重新生成的 LVS reference（subckt=ptat_vco 兼容 GDS）
- LVS 验证：重建 SPICE 和旧 SPICE 产生相同结果（276），确认一致性

### Session 最终数字 (2026-03-16 20:00)

| 指标 | Session 起始 | Base GDS | +Solver Patch | 目标 |
|------|-------------|----------|---------------|------|
| LVS unmatched | 358 | **276** | **240** | 0 |
| LVS comma merges | 1 | 2 | 2 | 0 |
| Routing 碎片 | 79 | **0** | 0 | 0 |
| DRC | ~208 | ~216 | 未测 | 0 |
| Routing | 133/0 | 133/0 | 133/0 | 133/0 |

**13 个 git commits 本 session。**

### 下一 session 优先级

1. **重建 SoilZ 分块前仿** — 从 soilz_design.md 重建 6 个 block SPICE + testbench，跑全电路前仿验证 netlist.json 正确性
2. **修 PCell rotation** — pipeline-wide 决定：不旋转（当前行为）或全链路支持旋转
3. **修 Rout↔Rptat 重叠** — 调整 placement
4. **B 类 36 nets 深查** — 这些有 Via2 routing 但 LVS unmatched，可能是 device topology 问题
5. **DRC 系统性修法** — M1.b(34), M3.d(38), M4.b(21)

### 教训（累积，每条都踩过坑）

1. **先验证再定性** — 没有脚本输出/LVS证据不能说"确认"
2. **不怪 PDK** — L2 同 PDK 无 merge，问题在自己的结构
3. **先判方向实验再动刀** — connect 开关实验 > 直接 patch
4. **保干净基线** — 不在脏 GDS 上打地鼠
5. **追完整连接链** — 不要只看一个可疑点就 patch
6. **脚本有边界就换工具** — Python BFS 不够就用 Ruby LVS / GUI
7. **NEVER `git checkout --` on modified files**
8. 修改前先 `cp file file.bak`
9. 每完成 milestone 立即 commit
10. 不在不完整 build 上声称 SUCCESS
