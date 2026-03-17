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

### SoilZ 前仿重建 (2026-03-16 20:00-20:30)

**关键发现：SPICE 实例化必须用 X prefix（subcircuit call），不是 M prefix。**
- IHP SG13G2 器件是 `.subckt`（PSP/OSDI compact model），不是 `.model`
- L2 的 cmos_ptat_vco.sp 正确使用了 `X` prefix
- gen_lvs_reference.py 用 `M` prefix（正确用于 KLayout LVS，但 ngspice 前仿需要 `X`）

**已完成：**
- `sim/soilz/` 目录创建，6 block SPICE + flat + presim 重建
- `_soilz_presim.sp` 使用 X prefix，249 devices
- ngspice 首次解析成功（DC OP 开始求解）
- ⚠️ DC OP 收敛状态未确认（ngspice 在 gmin stepping 后进程消失，可能 crash 或 timeout）

### 设计修复 + 前仿验证 (2026-03-16 20:00-21:30)

**发现并修复 5 个设计遗漏：**

| 遗漏 | 影响 | 修法 | 验证 |
|------|------|------|------|
| C_fb 电容 | ΣΔ 不工作 | 加入 netlist.json | ✅ presim 中 |
| Cbyp_n/Cbyp_p | bias 不稳定 | 加 bypass cap | ✅ crash 延长 |
| OTA bias mirror | OTA 无 bias 电流 | **PMOS mirror**（非 NMOS） | ✅ bias_n=0.197V |
| Mirror L | VCO noise coupling | 10→50µm | ✅ VCO 11.9MHz |
| cap_cmim pcell | ngspice 找不到 | "cmim"→"cap_cmim" | ✅ |

**关键发现**：
- OTA bias 需要 **PMOS mirror**（VDD→bias_n），不是 NMOS（两个 drain 都 sink）
- NMOS mirror 被验证不工作：bias_n=0V。PMOS mirror: bias_n=0.197V ✅
- L2 有 bypass cap，SoilZ 合并时遗漏
- 分块前仿用 ideal 电流源，合并时没替换成实际 mirror

**Core analog presim (PTAT+VCO+OTA, ~55 devices, 100µs)：**
- VCO: 11.9 MHz ✅ (目标 7-11 MHz，略高)
- bias_n: 0.197V ✅ (OTA 有 bias)
- ota_out: 0.796V ✅ (OTA 工作)
- sum_n: 0.750V ✅ (积分器稳定)
- VPTAT: 12.3mV ⚠️ (低，需调查)
- 无 crash ✅

**待验证**：全电路 253 devices presim（加数字块+comparator+H桥）
**设备总数**：253 (246 MOS + 4 R + 3 C)

### Session 总成果 (2026-03-16~17, 42 commits)

**设计修复 (6 个遗漏 + 3 个参数修正)：**
1. C_fb 1pF cap_cmim — ΣΔ 反馈电容（缺失）
2. Cbyp_n/Cbyp_p bypass caps — bias 节点稳定（缺失，L2 有）
3. M_bias_mir PMOS mirror — OTA bias 电流源（NMOS 不行，需要 PMOS）
4. INV_iso ×4 — VCO→TFF isolation buffer（TFF charge injection 导致 crash）
5. Mirror L: 10→50µm（频率匹配，PCell 宽度 51µm）
6. Rout: rppd→rhigh l=100（VPTAT 12mV→123mV）
7. cap_cmim pcell_name: cmim→cap_cmim
8. device_lib: bbox, pins, classification 补全

**前仿验证（ngspice 实测）：**
- VCO: 10.4 MHz ✅ (72-dev clean), 4.5 MHz (208-dev cshunt=50fF)
- VPTAT: 123 mV ✅
- OTA: 0.614V ✅
- TFF ÷2: VCO/2 精确 ✅
- Core analog (72 dev): 20µs stable ✅
- 全电路 (208 dev + cshunt): 15µs stable ✅
- Ground bounce: 0.5mV（实测 TFF peak 155µA × 1Ω GND）

**布局更新（257 devices）：**
- Placement: 0 overlap, fits 202×314µm tile ✅
- Ties: 7/7 PASS ✅
- Routing: 133/0 (全通) ✅
- Assembly: ⚠️ BLOCKED — 新器件类型需要 PCell shapes_by_layer probe

**工具：**
- Via2 constraint solver (solve_via2.py + apply_via2.py)
- M2 overlap fix (fix_m2_overlap.py)
- L2/SoilZ 分离，SPICE 重建
- 可视化 (placement_v4.png)

**LVS 进展（在旧 249-dev 设计上）：** 358→240 (-33%)

### Session 2026-03-17: Geometric Solver Pipeline

**完成:**
1. ✅ `ptat_vco` → `soilz` 全链路 rename (7 pipeline 文件 + gen_lvs_reference)
2. ✅ Pipeline 跑通, 真实 baseline: LVS=299, DRC=280, 3 comma merges
3. ✅ `atk/diagnose_geometric.py` — 0.1s 全景诊断 (DRC + L2N + merge)
4. ✅ L2N 全量 probe: 65 connected / 69 fragmented (修正了 id() vs cluster_id bug)
5. ✅ Via2 blocked 60 pins 根因: 46 M2 cross-net, 14 no anchor, 0 no M3 space
6. ✅ 3 comma merge 精确根因:
   - buf1↔vco5: **M2 AP pad overlap** 350×65nm (MBn1.D↔MBp1.G)
   - da1↔f_exc_b: **M2 Via2 bridge** 跨入 AP pad 区域 (2 shapes, 600nm 高)
   - ns5↔vco_out: **M3 cluster 75** 连通 (ns5+vco_out+vco5 三 net M3 合一)
7. ✅ Phase B solve_min_area.py: 73/73 min-area violations fixed (M3.d=67, M1.d=4, M4.d=2)
8. ⚠️ Phase A solve_merges.py: buf1↔vco5 pad shrink applied 但 LVS merge 未消除（多层路径）
9. ✅ Phase A+B applied → DRC 280→217 (-63), M3.d 67→0
10. ❌ Phase C (Via2 solver) 引入 34-net mega-merge — **不能直接 apply**

**验证结果 (Phase A+B, 无 Via2 solver):**
- DRC: 280→**217** (M3.d=0 ✅, 其余不变)
- LVS: 299→299 (pad shrink 不够，merge 有 M1+M3 路径)
- Comma merges: 3→3 (未消除)

**关键发现 (LVS xref API 分析):**

**LVS 299 unmatched 的精确根因分解 (LayoutVsSchematic xref):**
- Device matched: **224/257** (87%)
- Device unmatched: REF-only=32, EXT-only=28
- Net matched: 46, Unmatched REF=302, Unmatched EXT=99

**32 unmatched devices 的根因:**
1. **23 PMOS wrong-bulk**: REF bulk=$internal_net, EXT bulk=VDD
   - 包括 PM_CAS1-3, PM_CAS_DIODE, PM_CAS_REF, PM_MIR1-3, PM_REF, PM_PDIODE,
     MPB1-5, M_BIAS_MIR, MBP2, INV_ISO_P, M_IA_P, MP_LOAD_P, PM3-5
   - 根因: NWell island 没有独立 net, LVS 把所有 PMOS bulk 连到 VDD
   - 修法: placement 级 NWell bridge (之前验证过 6/12 safe)
2. **4 RHIGH terminal=none**: REF 和 EXT 都 A=none B=none
   - 需要查为什么 terminal 为空
3. **3 CAP_CMIM REF-only**: gen_lvs_reference.py 跳过 capacitor
4. **2 NMOS REF-only**: $79 (div8 相关), $80 (ref_Q 相关)

**3 comma merges 的 device-level 根因:**
- buf1↔vco5: MBP1 的 G(=vco5) 和 D(=buf1) 在 GDS 中短路
  (extracted: M$45 G=buf1|vco5 S=buf1|vco5, M$29 REF 同样)
- da1↔f_exc_b: assembly Via2 M2 bridge 跨入其他 net AP pad 区域
- ns5↔vco_out: 需要进一步分析（不是 M3 mega-polygon，L2N≠LVS）

**之前的错误认知 (已修正):**
- ❌ "只有 23 device matched" → ✅ 224 matched (之前误读 xref API)
- ❌ "ns5↔vco_out 是 M3 mega-polygon" → ✅ LVS 有 FEOL 提取，和简单 L2N 不同
- ❌ "M3 separation 能修 merges" → ✅ 反而引入 gnd↔vdd merge (破坏 assembly cleanup)

**已验证的安全修法:**
- Phase B (M3.d min-area): DRC 280→217, 73 violations → 0 ✅
- Via2 solver: 199 found 但直接 apply 引入 mega-merge ❌ (需要 merge-safe)

**IHP LVS Ruby 脚本关键发现:**
- BEOL: pwell_sub→pwell→ptap→cont→M1→Via1→M2→Via2→M3→Via3→M4
- PMOS bulk: nwell_drw→ntap→cont→M1→metal chain→VDD
- RHIGH: 2-terminal (A,B), ports = gatpoly 5nm sliver at rhigh_res edge → poly_con → cont → M1
- Salicide abutment: nsd_fet edge < 1nm from ptap → 直接短路 (可能是 comma merge 隐藏路径)
- polyres_drw = (128,0), extblock_drw = (111,0), salblock_drw = (28,0)

**RHIGH disconnected 精确根因:**
- Rptat: rhigh_res 从 Y=147000 到 Y=149930，GatPoly 只在 Y=149930-150360 (顶端)
- 底端 Y=147000 没有 GatPoly → 没有 rhigh_ports → 没有 poly_con → terminal B disconnected
- 根因: PCell 单端 poly contact，assembly 没有画底端的 poly extension + cont + M1
- 4 个电阻都有同样问题

**3 comma merges:**
- .cir 确认是 physical shorts (extraction 阶段合并)
- .lvsdb 的 EXT 显示分开 (comparison 阶段 split 了)
- 两个来源矛盾但 .cir 是 raw extraction，更可信

**修正：**
- RHIGH 不是 disconnected，是 terminal order 反了（已修 SPICE）+ Rout L=100.0→100.5 校准需加
- 只有 **2 个 wrong-bulk PMOS**（$24 B=$33, $25 B=$151），不是 23 个
- 14 个 PMOS 不匹配是 3 comma merges 的级联效应
- 87 nets matched（加了 CAP+RHIGH fix 后）

**3 comma merge per-layer 定位完成 (FEOL+BEOL L2N):**

| Merge | 层 | 根因 | 修法 |
|-------|-----|------|------|
| da1↔f_exc_b | **M2** (FEOL+BEOL L2N 验证 cluster=1) | M2 assembly bridge shapes | 删除 M2 bridge |
| ns5↔vco_out | **PSD→Cont** (断开 PSD→Cont 后 merge 消失) | ptap PSD bridge | assembly tie trim 增强 |
| buf1↔vco5 | **未检测到** (FEOL L2N 无此 merge) | 可能 salicide abutment | 需加 salicide 层或查 .cir |

**Bug 1 fix 已验证 (M2 bridge cross-net check):**
- `assemble_gds.py::_add_missing_ap_via2()` 加 `_m2_bridge_conflict()` 检查
- FALLBACK + SCAN 两处 M2 bridge 绘制前验证不 overlap cross-net M2
- 启用了之前的死参数 `xnet_m2_wires` + 新增 AP M2 pad obstacles
- **结果**: DRC 280→**144** (-136), da1↔f_exc_b merge **消除**, devices 231→**246** matched
- 57 个有冲突的 bridge 被 skip, fallback_shapes 216→159

**自动化诊断工具:**
- `atk/diagnose_lvs.py` 新建，读 .lvsdb 输出 `output/lvs_report.json`
- `run_all.sh` 集成 Phase 7 自动诊断

### 当前状态 (Bug 1 fix 后)
| 指标 | Before | After | Delta |
|------|--------|-------|-------|
| DRC | 280 | 144 | -136 |
| Devices matched | 231 | 246 | +15 |
| Devices unmatched | 49 | 20 | -29 |
| Comma merges | 3 | 2 | -1 (da1↔f_exc_b 消除) |
| Wrong-bulk PMOS | 2 | 1 | -1 |

### 方向评估 (2026-03-17 11:00)

**ATK pipeline LVS clean 评估**: 当前 LVS 315, DRC 144。
- Bug 1 fix (M2 bridge cross-net) 有效：DRC 280→144, devices 231→246
- Bug 2 fix 尝试失败：ns5↔vco_out overlap 来自多条代码路径，逐路径修是打地鼠
- 结论：assembly 代码为 37-device L2 设计，257-device SoilZ 超出设计能力
- **当前路径 LVS clean 非常困难**

**方向转换**: 探索开源模拟 IC 布局工具

**调研结果**:
- **ALIGN**: 无 IHP port, FinFET 架构不适合 130nm bulk CMOS, 4-8 周适配
- **GLayout (OpenFASoC)**: 有 IHP130 实验性 port, FET 不完善, 2-4 周
- **Coriolis**: 已有 `coriolis-pdk-ihpsg13g2` 包, 零适配, 值得试
- **Magic + Netgen**: IHP 官方支持, 完整 tech file + PCell + DRC + extraction
  - 可 Tcl 批处理脚本化 (LLM 写 Tcl → batch 执行)
  - 天然处理 well/tap/substrate (我们花大量时间解决的问题)
- **GDSFactory**: IHP PDK 支持但不完善 (只有 README)
- **LibreLane**: 数字 flow, shuttle 不支持 digital macro

### Magic Layout Generation 成功 (2026-03-17 12:20)

**工具链安装:**
- Magic 8.3 rev 621 编译安装 ✅ (`~/.local/bin/magic`)
- IHP SG13G2 PDK 加载成功 ✅ (tech version 1.0.0)
- Netgen 编译失败 ⚠️（暂不需要）

**gen_magic_layout.py 三阶段流程:**
- Phase A: Magic Tcl 创建 257 device subcells (PCell .mag 文件) ✅
- Phase B: Python 直接写 soilz.mag (use + transform + metal routing) ✅
- Phase C: Magic 加载 soilz, DRC + hierarchical extract + GDS ✅

**验证结果:**
- 257 device subcells 全部提取 ✅
- soilz.spice: 1292 行, 250 MOS + 4 RHIGH + 3 CAP = 257 devices ✅
- GDS: 1.3 MB ✅
- DRC: 10400 (包含 well/tap 缺失，正常——还没画 ties/guards)
- Extraction warnings: 1705 (inter-cell connectivity)

**关键突破**: Magic 原生处理 FEOL extraction，不需要自己实现 well/tap/substrate connectivity。
device 识别 100% 成功（之前 KLayout LVS 只识别 87%）。

**Routing connectivity 进展:**
- magic_router.py 简单 Manhattan router 写完 ✅
- Flat extraction: 274/257 devices 识别（比 hierarchical 更好）
- 10 nets 连接了多个 terminal（substrate/power 生效）
- 869 single-terminal nets（大部分 routing 还没连上 device contact）
- 根因: 简单 chain routing 的 L-shaped wire 没覆盖所有 device pin

**Routing.json 坐标变换方案验证成功 (2026-03-17 13:00):**
- per-device-type offset table 确认 std=0 (100% 确定性变换) ✅
- routing.json 1662 segments 变换到 Magic 坐标系 ✅
- Flat extraction: 274 devices, **61 multi-terminal nets** (从 10 → 61) ✅
- 32 nets ≥3 terminals (substrate + power + signal connectivity 生效)
- 1 mega-net (210 terminals) — cross-net M2 overlap 导致，和 KLayout 同类问题
- 525 unique nets (目标 ~150) — 碎片 + cross-net merge 混合

**关键突破**: Magic 坐标变换有效，routing.json 的拓扑可以直接复用。
**坐标系不兼容分析 (2026-03-17 14:00):**
- KLayout PCell 和 Magic PCell 的 pin 布局完全不同
- 每个 pin (D, G, S) 的 offset 各不相同，无法用 global shift 对齐
- 结论: 需要从 Magic PCell 提取正确的 device bbox + pin，然后整个 pipeline 用 Magic 坐标

**routing 实验总结:**
| 策略 | Multi-terminal nets | Single | Mega-net | 评价 |
|------|-------------------|--------|----------|------|
| Per-AP transform | 61 | 481 | 1 (210) | cross-net merge 严重 |
| Global coords + stubs | 74 | 494 | 2 (84,142) | 最好但 stubs 太大 |
| Minimal stubs | 74 | 494 | 2 (84,142) | 同上但无 M1 bridge |
| Smart endpoint | 62 | 481 | 1 (149) | 比 global 差 |
| ATK_MAGIC=1 routing | 38 | 754 | 1 (138) | 坐标混乱 |

**Correct bbox extraction + shifted placement (2026-03-17 14:30):**
- device_lib_magic.json bbox 从 geometry layers 提取 (排除 checkpaint) ✅
- Shifted placement: per-type average offset 补偿 KLayout→Magic pin 差异
- 结果: 68 devices fully connected (≥3 terminals), 152 partial, 18 none
  - 1 mega-net (substrate 142) + 1 signal mega (82, net_c1 区域)
  - ⚠️ "fully connected" 未验证是否连到正确 net

**routing 策略实验汇总 (7 次迭代):**
| # | 策略 | Full(≥3) | None | Mega | 评价 |
|---|------|---------|------|------|------|
| 1 | 简单 chain router | 0 | 274 | 0 | M1 覆盖但无 connectivity |
| 2 | Global (无 transform) | 38 | 34 | 2(84,142) | 最佳无 mega |
| 3 | Per-AP transform | - | - | 1(210) | cross-net merge |
| 4 | Global + giant stubs | - | - | 2(481,320) | stubs 太大 |
| 5 | Minimal stubs | 38 | 34 | 2(84,142) | 同 #2 |
| 6 | ATK_MAGIC routing | 29 | 49 | 1(142) | 坐标混乱 |
| 7 | **Shifted placement** | **68** | **18** | 2(82,142) | **最佳 connectivity** |

**下一步**:
1. Per-pin weighted shift (减少 mega-net, 优化 S pin 对齐)
2. 或: 直接用 Magic pin 坐标重写 routing solver
3. 安装 Netgen → LVS 验证已连接 nets 的正确性
4. 迭代直到 LVS 指标稳定下降

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
