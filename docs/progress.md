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

### 待完成

1. **mystery M1 来源确认**: `tie_MN_pgen_ptap` M1 `[51020,144845,51280,145445]` 260×600nm
   已确认是 tie cell 的 M1 bar（在 ties.json 里），与 PM_pdiode.D pad 有 330nm 重叠。
   assembly tie trim threshold -200nm 不够 catch（需要 -400nm）。

2. **3 个 vdd-bridge ptap 机制**: 为什么这 3 个 ptap 各自把 pwell 连到了 vdd？
   - nsd_ptap_abutt = 0（非 salicide abutment）
   - 机制未知，需要逐个调查

3. **Assembly 级修复**: 当前是 GDS post-process patch（删 PSD/M1）。
   需要转化为 assembly 代码级修复（tie trim / SalBlock / 其他）。

4. **BUF_I_n.S M3 80nm gap**: gnd M3 vbar 和 vdd M3 vbar 间距只有 80nm，
   Via2 M3 pad 桥接两边。这是 DRC violation 也可能是 LVS bridge 的一部分。

### 下一步

调查 3 个 vdd-bridge ptap 的 bridge 机制，设计 assembly 级修复。
psd_ntap_abutt = 7 作为交叉验证参考。

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
