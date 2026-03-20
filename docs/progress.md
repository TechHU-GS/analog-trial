# Progress & Decision Log

> Read this after compact to restore context.

## ★ Session 8 — LVS Pipeline 闭环 + LVS 112→246/0 merge (2026-03-20 18:10)

### 核心成果

**LVS 112 → 246/257 matched, 9→0 merges, 14→0 wrong-bulk**

根因: `access_points.py` 的 pad-stub merge 逻辑把同一 MOSFET 的 D/G 的 M1 区域
合并成 bounding box → 665x2560nm M1 shape 桥接了不同 net 的 pin。
修法: 只在 pad 和 stub 间距 < M1_MIN_S 时才 merge，否则分开画。

验证: GDS M1 shape 对比（current vs e4b82ae）确认 bridge shape 只在 current 存在。
文件: `assemble/access_points.py` lines 165-179

### lvs_loop.py 工具建成 (LVS 闭环诊断)

`python3 -m atk.lvs_loop --gds ... --routing ... --ties ... --placement ... --lvs-report ... --output ... --prev ...`

功能:
1. L2N merge 检测（metal-only）
2. Via2 审计
3. L2N safe pin 分析（M2 cluster）
4. KLayout LVS 交叉验证 → 区分 real merge vs false positive
5. 分类 action plan: substrate > confirmed metal > via2 > l2n_only
6. Diff 对比（--prev 参数）

关键发现:
- 71 个 L2N merge 中只有 31 个被 KLayout LVS 确认，40 个是 false positive
- same_device_dg 从 34 降到 3 (after KLayout 确认过滤)
- bus_straps Region→interval merge 回退 → 无影响（排除了 bus strap 假设）

### Via2 L2N guard 实现

assemble_gds.py `_add_missing_ap_via2`: 用 M1+Via1+M2 L2N probe 每个 AP 的 M2 cluster。
- Safe (single-net): 搜索 M1_LYR+M3_LYR+M4_LYR (expanded)
- Unsafe (mixed-net): 只搜索 M3_LYR+M4_LYR (conservative)

验证: 无 guard 扩展 M1_LYR → LVS 246→112, 9 merges (cross-device D/G merge)。
L2N guard 后 → safe 283 of 285, Via2 81→127。

### 排除的假设
1. bus_straps Region gap cutting → 回退到 interval merge, gap 21→22, LVS 不变 → 排除
2. 简单扩展 Via2 搜索到 M3 → 9 merges, LVS 112 → 排除 (需要 L2N guard)
3. has_low=False AP 可安全扩展 → 0 个 has_low=False AP with M3 close → 排除

### 当前状态
```
LVS: 246/257 matched, 1 merge (ns3,vco3 substrate), 0 WB
Via2: 130 ok / 504 fail / 155 skip (success rate 20%)
L2N safe: 283/285
DRC: 未重测 (assembly 改动后)
```

### Via3 M4 cross-net check (ns3↔vco3 最后 1 个 merge → 0)

根因: `_add_missing_ap_via2` 在 Mpu3.D(vco3) 放 Via3 → Via3 M4 pad 和 PCell
M4 wire (ns3, 连接 Mpb3.D→Mpu3.S) 重叠 → cross-net merge。
证据链: bare L2N cluster 413≠422(分开), current 353=353(合并), GDS 对比确认
assembly Via3 at (143.3,175.0) 连到 PCell M4 wire (140.6-145.4)。
修法: Via3 placement 前 GDS M4 shape overlap 检查 → 24 个 Via3 被正确拦截。
文件: `assemble_gds.py` need_via3 block

### 最终状态
```
LVS: 246/257, 0 merge, 0 WB ✅ (verified)
DRC (CI-aligned ihp-sg13g2.drc): 273 total (assembly 引入 156 M1.b)
Via2: 107 ok / 527 fail / 155 skip
L2N: 283 safe / 2 unsafe, 16 l2n_only (false positive)
```

### 剩余 11 unmatched devices (全部是 routing 覆盖不足)
- 7 passive (3 cap_cmim + 4 rhigh): 无 route, 4 个 SHARED-M2
- 4 MOSFET: route 覆盖不足 (48/129 routes)
- 不是 assembly 问题，需要 router 输出更多 route

### CI 对齐 (重大发现)

**run_drc.py (maximal) 和 ihp-sg13g2.drc (CI precheck) 结果完全不同：**
- run_drc.py: M1.b=0, total=112
- ihp-sg13g2.drc: M1.b=213, total=327
CI 用的 ihp-sg13g2.drc 才是 TTIHP 提交标准。run_all.sh 已切换。
PDK 更新到 CI 版本 c4b8b4e5。

### DRC 修复: G pin M1 pad skip

M1.b=213 中 85% 来自 access_points phase。根因: gate contact M1 pad (290nm)
在 S/D strip 之间，cross-net gap 100-150nm < M1.b 180nm。
150/250 G pin 有 PCell M1 覆盖 Via1 → 跳过冗余 AP M1 pad。
结果: M1.b 213→156 (-57), DRC 327→273 (-54)。LVS 不变。

### CI precheck 其他失败
- Top cell 名字不对 (soilz vs tt_um_techhu_analog_trial)
- Layer (51,0) = M4 不在允许列表
- Analog pin ua[0] 未连接
- 需要 wrapper cell 或调整 GDS 提交结构

### DRC: 去掉 pad-stub bbox merge → M1.b 156→66 ✅ verified

Session 6 教训（stub-pad merge = DRC disaster）+ 数据验证（532/532 全 overlap）
→ 完全去掉 bbox merge，pad 和 stub 分开画。DRC 引擎自动合并重叠区域。

结果:
- M1.b: 156 → **66** (比 e4b82ae 的 68 还少 2 个)
- CI DRC: 273 → **169**
- LVS: 246/0/0 不变 ✅

PCell DRC clean（Session 4 验证）。BARE flattened M1 space_check = 0。
剩余 66 M1.b 需要进一步分析。

### DRC 深度分析结论

CI DRC 161 全部是 inter-PCell 间距（单个 PCell CI DRC clean 已验证）。
M1.b=57 中 38 个集中在 TFF 数字区 (x=50-100, y=200-250um)。
Gap fill 260nm shapes 贡献 +36 M1.b（去掉后 57→21）。
Y-stretch 对 M1.b 无效（不是 Y 间距问题）。
X 单 device 移动也无效（是 assembly shapes 和 PCell strip 的 notch）。

### 架构转换：模块化 "搭积木" 方案

放弃 flat 257-device 全局 assembly。改为模块化：
1. TFF macro: 16 devices (8 nmos_vco + 8 pmos_vco), 7 个相同实例
2. 各模拟模块 (VCO, OTA, BIAS...) 独立设计
3. 最后拼装

TFF macro baseline 已提取: modular/output/tff_macro.gds
- 64 M1 shapes, M1.b=0, M1.a=0 (PCell only, DRC clean)
- 下一步: 逐步加 bus straps → ties → gate → AP, 每步验证 DRC

### LibreLane 数字 block 生成 ✅ verified

soilz_digital.v → LibreLane 3.0.0.dev44 → soilz_digital.gds
- 23 standard cells: 7 DFF + 3 MUX2 + 2 NAND2 + 11 INV
- 替换 164 custom transistors (TFF+BUF+MUX+NOL)
- 80x30um, M1.b=0, 18 秒 build
- 服务器 100.64.0.4 Docker 跑的

标准单元替换实验结果:
- 替换 TFF 区域后 CI DRC: 161→72 (-55%)
- M1.b: 57→21, M3.b: 46→20

### 模拟区分析

去掉数字区后 CI DRC: 32 (was 161)。80% DRC 来自数字区。
模拟区 11 M1.b: BIAS(6) + DAC(3) + COMP(1) + SR(1)。

### VCO Stage 模块化

PCell 实际尺寸（从 bare GDS child cell 直接测量）:
- Mpb1 (pmos_cs8): pmos$5 = 20.0 x 1.1 um (8-finger 长条)
- Mpu1 (pmos_vco): pmos = 1.8 x 2.6 um (单 finger 小方块)
- Mpd1 (nmos_vco): nmos = 1.2 x 1.4 um (单 finger 小方块)
- Mnb1 (nmos_bias8): nmos$9 = 19.3 x 1.4 um (8-finger 长条)

Compact VCO stage: 20.0 x 12.0 um, M1.b=0
结构: Mpb(长条顶) → Mpu(小方块) → Mpd(小方块) → Mnb(长条底)
文件: modular/output/vco_stage_compact.gds

### VCO Stage CI DRC = 0 ✅ verified (本项目首个 CI DRC clean 模拟模块)

21.0 x 12.7um, 4 PCells (Mpb+Mpu+Mpd+Mnb) + routing + ties
关键修复:
- Mpb 间距 y=11.5um (binary search 找到 NW.b1 临界点)
- ntap/ptap tie cell 解决 LU.b
- M1 routing X 对齐到 PCell strip 消除 M1.a
- 所有 DRC 规则 = 0

方法论突破: 模块化 DRC，每个模块独立 clean 后再组装。
全局调 DRC 不收敛（Session 8 前半段证明），模块化调 DRC 可精确定位和修复。

### 下一步
1. VCO 5 stage 复制 + 环形连接 → 完整 VCO
2. 其他模拟模块 (BIAS, OTA, COMP...) — 同样方法
3. 集成: 数字 block + VCO + 模拟模块
4. 数字增强 (I/Q 相关器, SPI, 扫频) — 模拟完成后

## ★ Session 5 — LVS Gap 根因分析 + DRC Baseline (2026-03-18 22:00)

### 核心发现

1. **Label 层映射 bug 确认修复 (验证)**
   - 原因: assemble_gds.py label 代码把 router layer 0/1 当 M1/M2 → label 放到 M2 text layer 但金属在 M4 → net 无名
   - 修复: label 放在 AP via_pad M2 位置（M2 金属实际存在），通过 Via2→M3→routing wire 传播
   - 验证结果: nets matched 0→13, comma merges 79→0, wrong-bulk PMOS 126→10, devices matched 96→113

2. **对角线 bridge → L 形修复 (验证)**
   - 原因: last-mile bridge 生成对角线段 → KLayout Path 多边形角点 off 5nm grid + 投影宽度 < 200nm
   - 修复: maze_router.py 对角线拆成两段正交 L 形
   - 验证结果: OffGrid 1592→0 ✅, 总 DRC 4227→2157

3. **DRC 仍有 2157 violations**
   - M3.a(width)=1211, M4.a=271, M5.a=137 — 主要是 L 形短边 < 200nm (假设, 未验证)
   - M3.b(spacing)=298, M1.b=74, 其他各类小数
   - OffGrid 全部消除 ✅

4. **LVS 113/404 devices matched**
   - 13 nets matched (从 0 提升)
   - 0 comma merges (从 79 消除)
   - 10 wrong-bulk PMOS (从 126 降低, 可能是需要独立 NW 岛的 PMOS)
   - 291 devices unmatched — 需要继续分析

5. **Reference SPICE 分析**
   - 257 devices: 127 PMOS, 123 NMOS, 4 rhigh, 3 cap_cmim
   - ~40 PMOS 的 bulk 不是 vdd（VCO source-follower, TG, CML latch）→ 需独立 NW 岛
   - 所有 NMOS bulk = gnd
   - KLayout LVS 无 connect_global → bulk 纯靠物理几何

6. **Sweep 判断: 现在不做**
   - 80% DRC violations 是系统性的（wire width, grid snap）→ 每个 seed 都一样
   - 先修 routing DRC，再 sweep

### Pipeline 执行情况

```
solve_placement.py  — INFEASIBLE (已有 placement.json, 跳过)
solve_ties.py       — PASS 7/7 ✅
solve_routing.py    — 131/143 nets, 4 failed (gate 2/6)
optimize.py         — 3203→3198 segments
assemble_gds.py     — soilz.gds written, 131+14+3=148 labels ✅
DRC                 — 2157 violations
LVS                 — 113 matched, 13 nets, 0 merges
```

### 代码修改 (本 session)

| 文件 | 修改 | 状态 |
|------|------|------|
| assemble_gds.py | signal_routes + pre_routes label 放 AP via_pad M2 | ✅ 验证: 0→13 nets |
| maze_router.py | 对角线 bridge → L 形正交 | ✅ 验证: OffGrid 1592→0 |

### M3.a=1211 修复 (验证)
- 原因：L 形 bridge 短边 < 200nm（router grid 350nm，max offset 175nm < 200nm min width）
- 修复：bridge 短边延长到 M3_MIN_W=200nm（pdk.py 引用）
- 验证：M3.a 1211→2, M4.a 271→0, M5.a 137→0, 总 DRC 2157→533

### Power pad 位置修正 (验证)
- 发现：150/153 power drops 的 AP 位置和实际 via 位置差 1430-2180nm (Y方向)
- solver._block_power_pads_m345() 阻塞了 AP 位置（错），没挡实际 pad 位置
- 修复：用 drop['via_x'], drop['via_y'] 替代 ap['x'], ap['y']
- 验证：signal-power overlap 56→0

### Power M3 vbar 分析 (验证)
- 发现：1089 signal-power M3 vbar 重叠 — vbar 完全没被阻塞
- 加 vbar obstacle：GND mega-merge 18→5 nets，但 routing 131→74（M3 空间不够）
- solver 部分 seed 超时 >120s（obstacle 太多，A* 搜索空间爆炸）

### 核心矛盾发现 ⚠️
**M3 power rail/vbar 和 M3 signal routing 冲突**
- 8 条全宽 M3 power rail + 151 条 M3 vbar 占大量 M3 空间
- 分层策略说 M3=signal routing H, TM1=power distribution
- 但 assemble_gds.py 的 power via stack 只到 M3！没有 Via3→M4→Via4→M5→TopVia1→TM1
- Session 4 的 "Power on TM1 ✅" 是独立测试，从未集成到 pipeline
- 这是改分层时欠的技术债

### 快速验证：删 M3 rail/vbar (验证)
- routing: 74→132/135 ✅ (M3 空间释放)
- DRC: 533→246 ✅
- 但 wrong-bulk PMOS: 23→131 ❌ (NW 拿不到 vdd label，因为 M3 rail 是 vdd 的分配通道)
- **结论**：不能简单删 M3 rail，需要 TM1 via stack 替代

### 下一步：TM1 Power Via Stack 集成
1. assemble_gds.py：给每个 power drop 加 Via3→M4→Via4→M5→TopVia1→TM1
2. assemble_gds.py：加 TM1 stripe（共享 Y-band 横条）
3. assemble_gds.py：删 M3 rail + vbar（TM1 接替后不再需要）
4. solver.py：只阻塞 via stack 小 pad（不需要阻塞 M3 rail/vbar 因为不存在了）
5. 验证 DRC + LVS

已知参数（Session 4 验证，pdk.py 有）：
```
Via3  190nm, M3 pad 290nm, M4 pad 290nm
Via4  190nm, M4 pad 370nm, M5 pad 620nm
TV1   420nm, M5 pad 620nm
TM1   ≥1640nm stripe
```

代码现状：
- via3()/via4()/topvia1() 全部实现（commit 27906fb）
- li_m5, li_v4, li_v3, li_tv1, li_tm1 全部定义
- TM1 stripes (8条) + via stack (151 drops) 已集成

### Bare LVS = 245/257 (重要发现)
无 signal routing 时 matched=245（有 routing 仅 112）。
routing 引入 cross-net short（-133 devices）。Wrong-bulk: 无routing=2, 有routing=110。

### Sweep: seed 0/2/5/8 LVS 完全一样 (112/19/2/110)
瓶颈是系统性的，不在 routing ordering。

### gnd-vdd 短路修复 (验证)
- Binary search: 无drops→cm=0, VDD-only/GND-only→cm=0
- 定位: INV_VCO_n.S + BUF_CK_n.S (gnd) TM1 pad 和 vdd_vco TM1 stripe 重叠 580nm
- 原因: topvia1() 在 drop 位置画 TM1 pad (1640nm正方形)，碰到异 net stripe
- 修复: TopVia1 移到 stripe Y 位置 (rail_y)，M5 vbar 从 drop 延伸到 stripe
- 验证: comma merges 2→0, wrong-bulk 110→16, devices matched 112→113

### M5 vbar obstacle blocking (实验 — 未帮助)
- solver.py 加了 M5 vbar blocking → routing 132→130，LVS 不变 (113)
- M5 vbar overlap 不是 LVS drop 的主因

### 132 device drop 根因分析 (进行中)
bare 245 → routed 113 的 drop 分解:
- +124 ref-only PMOS（2→126）— 几乎所有 PMOS 失配
- +10 ref-only NMOS（4→14）
- GND matched pair: `gnd,t1I_m,t1Q_m,t2I_m,t2Q_m,vdd` — routing 把 4 signal merge 进 gnd/vdd
- 所有 PMOS bulk = 这个 merged net → wrong-bulk → unmatch
- routing wire 本身不碰 power geometry（验证: 0 overlap）

**推断（未验证）:** Via2 连接放大了 M2 proximity。bare 时 AP M2 pad 孤立，
routing 加 Via2→M3→wire→M3→Via2→M2 形成 chain，chain 中某 AP M2
离 ntap M2 (vdd) 太近 → 整条 chain merge 进 vdd。

### Session 5 最终结果
```
DRC:     4227 → ~400
Routing: 132/135 → 130/135
Devices: 96 → 113 matched
Nets:    0 → 18 matched
Merges:  79 → 0 (diagnose_lvs count)
WB PMOS: 126 → 16
Bare:    245/257 (无 routing 上限)
```

### 245→113 Drop 根因定位 (验证) ⚠️ 重大突破

**Binary search:** 0→40 routes=246, 60 routes=113. 精确到第 60 条 net=nmos_bias。

**根因:** 4 个 cap/resistor 的 PLUS 和 MINUS pin 共享同一块 M2 pad：
```
Cbyp_n: PLUS(nmos_bias) & MINUS(gnd) → M2=[74860,152830,75340,153310] 完全相同
Cbyp_p: PLUS(pmos_bias) & MINUS(gnd) → 同上
C_fb:   PLUS(ota_out) & MINUS(sum_n) → 同上
Rout:   PLUS(vptat) & MINUS(gnd) → 同上
```
Routing 给 PLUS M2 标 signal name → 同一 M2 也连 MINUS (gnd) → signal=gnd → cascade → 133 devices unmatch

**验证:** 去掉 4 个 conflict net route → **246 matched, 0 wrong-bulk, 20 nets** ✅
```
128 routes (去掉4): matched=246, WB=0, nets=20
132 routes (全部):   matched=113, WB=16, nets=18
```

**修复方向:** solver 排除 shared-M2 cap/res pin。PDK 没问题 — 是我们不该走这个 pin。

### Shared-M2 通用检测 (实现)
- solver.py: 自动检测同位置不同 net AP → shared_m2_exclude (8 pins)
- 排除 pin from routing + output pin list + _add_missing_ap_via2 Via2 skip

### 245→113 真正根因 ⚠️ 重大发现

**_add_missing_ap_via2 失败率 78%** — 101/129 routes 没有 Via2 连接 M2。
routing wire (M3/M4) 画了但浮空（不连 M2）→ 干扰 KLayout LVS extraction → 246→113。

验证:
- 只保留 28 个有 Via2 的 routes → **246 matched, 0 WB** ✅
- GDS 比较 n=76 vs n=77: sum_n 加了 24 shapes 但 0 Via2 → 浮空 wire
- KLayout API 确认 sum_n 在 extracted netlist 有 2 terminals 但 GND mega-net 369→369
- 3D 视图确认: M4 wire 悬在 M2 上方无 Via2

之前的 shared-M2 分析是表面现象。cap dual-pin 的 4 nets 碰巧也是浮空 routes。
真正问题是 _add_missing_ap_via2 的 M3 conflict check 太严格 → 大量 Via2 被跳过。

### Via2 reach threshold 修复 (验证)
- 根因: line 1345 硬编码 500nm gate → 82% Via2 放置失败
- 修复: 500nm → 6*MAZE_GRID=2100nm (TODO flag 加注释)
- Via2 放置: 81→98 (+17), connected routes: 28→51
- 只保留 51 connected routes → 246 matched, 0 WB ✅
- 78 routes 仍浮空 — 196 pins 的 route 完全没 M3/M4 segments (router 层面问题)

### Layer search fix (验证)
- _add_missing_ap_via2 搜索 M3_LYR(=M5 only) → 改为 M1_LYR/M2_LYR/M3_LYR (M3/M4/M5)
- Via2: 98→291, connected routes: 51→117 (91%)
- LVS: 116 matched, 34 nets, 1 merge (ns3,vco3)

### Simple Via2 测试 (失败, 回退)
- 567 Via2 without conflict check → 4 comma merges, 114 matched
- 根因: PCell 内部 M1 连接同 device 的 S/D → Via2 at both → merge
- 和 PMOS source-ntap 问题同类 — PCell M1 connectivity 超出 reference 假设
- 回退到 _add_missing_ap_via2 (conservative conflict check)

### 结论
- _add_missing_ap_via2 的保守性是必要的（防止 PCell M1 短路）
- 51 connected routes = 246 matched 是当前最优解
- 更多 Via2 ≠ 更好 LVS（PCell M1 限制）
- 需要: 只画有 Via2 的 route wire, 跳过浮空 route

### Via2 策略收敛 (验证)
- Layer fix (M3/M4/M5 search) + 2100nm reach: 291 Via2 → LVS 116 (too many → M3 overlap)
- Simple Via2 everywhere: 567 Via2 → LVS 114 + 4 merges (PCell S/D M1 连通)
- **回退到保守版 (M5-only + 500nm): 81 Via2 + 删 floating routes → 246 matched ✅**

两步流程:
1. 跑 assembly (全部 129 routes) → _add_missing_ap_via2 放 81 Via2
2. GDS 检查哪些 route 有 Via2 → 删无 Via2 的 81 routes → 重跑 assembly
→ 48 routes drawn, 246 matched, 0 WB, 0 CM ✅

### DRC 修复进展
- M5.b: 32→6 (same-net M5 vbar merge) ✅
- M1.b: 65 未修 — AP M1 pad extend 逻辑导致（assemble_gds.py L3350-3414）
  routing.json m1_stub 不碰，但 GDS 画的 extended pad 碰
- check_spacing 函数已加，shrink 策略对 spacing 无效（位置不变）
- shift 策略对 M5 有效但断连 Via4（只移 vbar 不移 stack）→ 回退
- M5 merge 策略有效（extend 到 overlap 消除 notch）→ 保留
- 全 metal 利用率 <3%，空间充足

### diagnose_drc.py 工具 (v3, 可靠)
- KLayout RDB API 解析 violations
- LayoutToNetlist probe_net() 查 net ownership
- notch 检测: probe_net cross_net + same AP → notch (非 true cross_net)
- 5 分类: same_net / notch / cross_device / self_ap / unknown

### DRC 275 violations 最终分类 (diagnose_drc 验证数据)
```
M1.b(67):  notch=49 (stub-pad gap), same_net=12, cross_device=6
M3.b(35):  same_net=34, cross_net=1 → merge 可修
V3.b(9):   same_net=9 → merge 可修
M5.b(6):   已通过 merge 从 32 降到 6 ✅
pSD.c(27): self_ap (PSD layer)
NW.c(24):  self_ap (NW enclosure)
Cnt.b(15): self_ap=10
其他(92):  CntB/NW.f/Act.b/TV1/TM1/min-area/fill/jog
```

### DRC 修法 roadmap
1. Merge same_net: M3.b(34)+V3.b(9)+M1.b(12) = 55 → M5 merge 同策略
2. Fix notch: M1.b(49) → stub-pad merge (draw_segments Via1 M1 + AP section pad 合并)
3. Placement: M1.b(6) cross_device → divider 区 device 间距
4. pSD/NW/Cnt(76): self_ap → 需单独分析

### Session 5 最终结果
```
DRC:     4227 → 275 (precheck rules, 275 是最新 diagnose_drc 验证)
LVS:     96 → 246/257 matched (95.7%)
Nets:    0 → 17 matched
Merges:  79 → 0
WB PMOS: 126 → 0
Routes:  48/129 connected (37%)
```

### CI Precheck 结果 (commit ab8ea16)
- GDS job: ✅
- **DRC: 178 violations** (precheck rule set, foundry 强制)
- Cell name mismatch (soilz ≠ tt_um_techhu_analog_trial) — 新 repo 时修
- LVS: precheck 不跑 LVS（模拟设计）
- Layer (51,0) invalid — 需查

### 本地 Precheck DRC: 267 violations 分类
```
M1.b   66  AP M1 stub 碰邻居 PCell M1 (spacing 25-175nm < 180nm)
M3.b   35  routing wire/bridge/Via2 M3 pad spacing
M5.b   32  power M5 vbar spacing
NW.c   23  NWell enclosure
Cnt.b  11  contact spacing
V3.b    9  Via3 spacing (160nm < 220nm)
NW.f    8  NWell rule
Act.b   7  active spacing
Others 76  TV1/TM1/pSD/min-area/fill/jog
```
Routing/assembly 引入: 81 (M3.b+M5.b+V3.b+TV1+TM1)
Placement/device: 115 (M1.b+Cnt.b+Act.b+NW)
M1 利用率只有 1% — spacing 问题不是拥挤，是 AP stub 方向

### Session 6 — 闭环尝试 (2026-03-19 17:30)

**目标**: diagnose → fix → verify → diagnose 闭环

**完成**:
- `_gds_same_net_merge()` 函数加入 assemble_gds.py (line ~733)
  - GDS-level 后处理: 扫实际 GDS shapes, 用 routing.json 分配 net, 填 gap < min_s
  - Assembly 输出: "GDS merge M3: 4 same-net gap fills"

**问题**: 闭环比较无效
- 重跑了 solve_routing.py → routing 变了 → DRC 不可比
- routing_backup2 没有 `_floating` 标记 → 所有 132 routes 都画了（含浮空）
- 之前的 275 baseline 是手动两步流程(48 connected routes) + precheck rules 的结果
- 当前全规则 DRC = 726 violations, 无法和之前 275(precheck) 直接对比

**全规则 DRC 726 分类** (routing_backup2, 132 routes, 含浮空):
```
M1.b  420  (notch=309, cross_device=40, same_net=59, cross_net=12)
M1.e   77  (cross_device=54, cross_net=12, notch=9)
M3.b   45  (same_net=39, notch=5, cross_device=1)
M5.b   32  (notch=10, cross_device=9, same_net=8, cross_net=5)
M3.d   22  (polygon=22, MIN_AREA)
pSD.c  26  NW.c 23  V3.b 10  Cnt.b 11  其他 60
```

**关键发现**:
- 全规则比 precheck 多 ~450 violations (主要 M1.b 66→420, M1.e 新增 77)
- M1.b/M1.e 大量 notch = AP M1 pad 和 PCell M1 之间的 gap
- M3.b same_net 39 个, GDS merge 只修了 4 个 — 大部分 shapes 没被 net assign
- M3.d(22) 是 MIN_AREA violations, ~300x350nm shapes

**已解决**:
- ✅ 浮空 route 检测集成 — `_pre_mark_floating_routes` pre-scan (line ~4679)
  - 验证: `Pre-scan: 61 floating routes detected` + 726→694 violations
- ✅ run_all.sh 跳过 placement/routing (outputs exist 时)
- ✅ `_gds_same_net_merge()` M3 后处理 — 4 fills

**全规则 DRC 694 (浮空跳过后, routing_backup2)**:
```
M1.b  420  (notch=309, cross_device=40, same_net=59, cross_net=12)
M1.e   77  (cross_device=54, cross_net=12, notch=9)
M5.b   32  (notch=10, cross_device=9, same_net=8, cross_net=5)
M3.b   30  (same_net=24, notch=5, cross_device=1)
pSD.c  26  NW.c 23  Cnt.b 11  M3.d 9  V3.b 6
其他   61
```

**⚠️ 未验证**: LVS 是否仍 246（浮空检测改了 route 选择）
**⚠️ 未验证**: Pipeline 重复性（只跑了一次）

### Bare DRC baseline (验证)
```
BARE_MODE=1 → bare PCell-only DRC = 5 violations (NW.b, M1.d, LU.a, NW.b1, LU.b)
Full DRC = 694 → 689 = assembly 步骤引入 (bus straps+ties+NWell+AP+power+routing)
```

### 分析工具建设 (Session 6)
1. `analyze_drc.py` — DBSCAN聚类 + 冲突图 + device-pair + GDS M1 footprint
2. `assemble_gds.py BARE_MODE` — PCell-only GDS baseline
3. `_gds_same_net_merge()` — GDS M3 post-pass (4 fills)
4. `_pre_mark_floating_routes` — 浮空 route 预检测集成
5. `run_all.sh` — 跳过已有 placement/routing

### 系统分析关键发现 (analyze_drc 数据)
- 93% violations 是 self (同一 device) — 不是 device 间距
- M1 PCell 延伸 ~1.05um — PCell 本身 OK (bare DRC=5 证明)
- TFF = 49% violations (339/694)
- M1.b gap 两个峰: 55nm(117) 和 140-160nm(147)
- V3.b 全部 gap=160nm — 系统性

### ⚠️ LVS 回退
48-route routing 恢复后 LVS=112 (应为 246)。
原因: post-e4b82ae 的 assemble_gds.py 改动 (M1 stub-pad merge 等)。
需逐个 revert 确认。

### ECS Placement Sweep (2026-03-19 20:30)
ECS: i-bp1fij0cmmw6daqwakar (192C/384G) IP=101.37.127.154
KLayout 0.29.11 从源码编译 (192核 ~3min)
```
25点 sweep (x_gap 1.0-1.4, y_gap 0-4um, 24并发):
Best:  x=1.40 y=2.0 → total=622 M1.b=406 M3.b=10 pSD=5 NW=5
原始:  x=1.00 y=0.0 → total=684 M1.b=424 M3.b=41 pSD=26 NW=23
改善:  -62 (-9%), M3.b-31, pSD-21, NW-18. M1.b只降4%
```
### 125 点 sweep 最终结果 (5 x_gap × 5 y_gap × 5 seeds, 48 并发, 557s)
```
Best:  x=1.38 y=4.0 seed=3 → score=5125 total=655 M1.b=400 M3.b=12 M5.b=3 pSD=8 NW=7
#2:    x=1.25 y=4.0 seed=4 → score=5147 total=563 M1.b=408 M3.b=14 M5.b=6 pSD=5 NW=5
原始:  x=1.00 y=0.0         → score=5874 total=684 M1.b=424 M3.b=41 M5.b=8 pSD=26 NW=23
```
- Y gap 是最强参数 (y=4.0 统治 top 10)
- Routing seed 有 ~2% 影响
- M1.b 在 ~400 触底 — placement 无法进一步降低
- ECS 已释放 ✅, best placement 拉回本地 ✅
- ⚠️ LVS 未验证
- ⚠️ 本地没有 best routing.json (需重新 routing)

### 125 点 sweep 最终结果 (5×5×5, 48并发, 557s)
```
Best:  x=1.38 y=4.0 seed=3 → score=5125 M1.b=400 M3.b=12 pSD=8 NW=7
#2:    x=1.25 y=4.0 seed=4 → total=563 M1.b=408 M3.b=14 pSD=5 NW=5
```
本地验证 best: 651 total (CntB+76 因手动拉间距破坏 row 结构)

### Solver INFEASIBLE
- CP-SAT 在原始约束下就 INFEASIBLE (0s, 预处理矛盾)
- 194K constraints, 153K variables
- 当前 placement.json 是更早版本约束的产物
- 手动拉间距 → row 结构破坏 → NW/CntB violations 暴增
- 需 debug solver 约束矛盾才能生成合法宽间距 placement

### Session 6 最终状态
```
文件: placement.json = 原始, netlist.json = 原始
DRC: 684 (原始), sweep best 可达 ~563-622
LVS: 未验证 (assembly 改动导致 246→112)
工具: diagnose_drc, analyze_drc, sweep_placement 可用
ECS: 已释放
Sweep 结果: output/sweep_results.json
```

### 构造式 Placer (constructive_placer.py)
绕过 INFEASIBLE 的 CP-SAT solver，直接按参数构造 placement。
首次测试 (row_x_gap=3, row_y_gap=5):
```
M1.b=344 (vs 原始 424, -19%) ← 首次突破 400！
M1.e=15 (vs 77)  pSD.c=6 (vs 26)  NW.c=5 (vs 23)
但 Cnt.j=212  CntB.*=282 ← row 结构不对，tie cell 规则违反
Total: 1223 (vs 684) — metal DRC 下降但 contact 暴增
```
⚠️ 8 个 device 缺失 (不在 row_groups: C_fb, Cbyp_n/p, INV_iso_*, M_bias_mir)
⚠️ placement.json 当前是构造式版本

### Y-Stretch 方法 (保留原始 X 结构，只调 Y gap)
原始 placement 的 row X 结构精确，只拉大 Y 间距。
108 点 sweep (ECS 128C, 48并发, 589s):
```
Best:  x=1.00 pair=1.7 grp=6.0 seed=0 → total=599 M1.b=411 M3.b=29 Cnt=0 score=5412
原始:                                  → total=684 M1.b=424 M3.b=41 Cnt=11 score=5874
改善: -85 (-12%), Cnt 11→0
```
关键发现:
- **X=1.00 统治 top 20** — X 不该拉大！原始 X 是 tie cell 最优
- Y pair_extra=1.7um + group_extra=6.0um 是最优组合
- Cnt=0 只在 X=1.00 时出现
- ECS 已释放, best placement 已拉回本地 ✅

### M1 stub-pad merge REVERT ← 重大突破 (trace_drc 验证)
`trace_drc.py` 溯源: ap_m1_merged 出现在 91% M1.b violations
Revert assemble_gds.py line 3574-3589 的 stub-pad merge 代码:
```
Before revert: DRC=587 M1.b=411 LVS=110matched/8merges
After revert:  DRC=179 M1.b=77  LVS=113matched/1merge ✅ 验证
改善: DRC -408(-70%), M1.b -334(-81%), merges 8→1
```
剩余 M1.b=77, M3.b=29, M5.b=7, pSD=5, NW=5
LVS: 113 matched, 17 wrong-bulk, 1 merge (ns2,vco2)
⚠️ LVS 113 不是 246 — 因为 Y-stretch placement + 新 routing（不是原始 48-route）

### LVS 246 恢复验证 ✅
原始 placement + e4b82ae ties + 48-route routing + e4b82ae assembly = **LVS 246, 0 WB, 0 merge**
关键: ties.json 必须和 placement 配套，重新生成的 ties 导致 LVS 掉

### Y-stretch LVS 调查结果
- Bare LVS: 原始=Y-stretch=**完全相同(103 matched)** → PCell 层面无问题
- Y-stretch + 新 routing(130 routes) = LVS 113 → 问题在 assembly/routing
- merge net `gnd,t2I_m,vdd` — 来自新 routing 的 signal wire 碰 power
- Bus strap 不是原因 (nmos_vco ng=1, 跳过 bus strap)
- M1 shapes 两个 placement 结构一样 (只有 Y 偏移)
- **结论: 新 routing 未经精选 + assembly 有硬编码位置 → LVS 掉**

### 全链路改进 Plan (approved)
详见: `.claude/plans/moonlit-brewing-hamming.md`
7 个 Phase, 总工作量 18-28 sessions:
1. Assembly 模块化 (3-5 sessions) ← 开始执行
2. Inline DRC (1-2 sessions)
3. Region API 替代手写坐标 (4-6 sessions)
4. Placement-Agnostic Assembly (2-3 sessions)
5. Pipeline Schema 验证 (1-2 sessions)
6. 集成 Sweep (3-4 sessions)
7. LVS 集成 (4-6 sessions)

### Phase 1 完成 ✅ (Assembly 模块化)
```
assemble_gds.py: 4823 → 2314 行 (-52%)
8 个模块: context(42), pcell_place(48), bus_straps(607), gate(225),
          ties_nwell(334), access_points(272), power(1015),
          signal_routes(163), labels(157)
DRC 706 = baseline ✅  LVS 112 = baseline ✅
0 runtime errors ✅
```

### Phase 2 完成 ✅ (Inline DRC)
assemble/drc_check.py: Region API space_check/width_check
6 个 checkpoint: bus_straps→gate→ties→AP→power→signal
DRC_INLINE=1 启用，默认关。输出示例:
```
ties_nwell:     M1 spacing=6
access_points:  M1 spacing=290, M2 spacing=2
power:          M1 spacing=400, M2 spacing=48
signal_routes:  M1 spacing=416, M3 spacing=35
```
→ 实时定位哪个 phase 引入 violations

### 当前状态
```
placement.json = 原始
assemble_gds.py = 模块化 + inline DRC
DRC: 706 (全规则, e4b82ae baseline)
LVS: 112 (e4b82ae baseline, 非 246 — 可能需要手动删浮空 routes)
工具: diagnose_drc, analyze_drc, trace_drc, sweep_placement,
      constructive_placer, drc_check (inline)
```

### Phase 4 部分完成
- ✅ debug Via2 check: 用 AP 坐标替代硬编码 (signal_routes.py)
- TODO: _safe_drops 4 组硬编码坐标 → 需 M4 endpoint 检测算法 (Phase 3 依赖)
- TODO: _NW_BRIDGE_A 硬编码 → 需 Region NWell gap 检测 (Phase 3 依赖)
- 结论: Phase 4 依赖 Phase 3 (Region API) 才能正确计算替代坐标

### Phase 3 完成 (Region API — 几何操作部分)
✅ gap_fill.py — Region sized/merged (DRC 706→687 -19, LVS 112 不变)
✅ _draw_gapped_bus — Region boolean (DRC 687 不变, LVS 不变)
TODO: NWell bridge — 需要 connectivity 分析 (LayoutToNetlist)，不是纯几何 → Phase 7
TODO: M4 dead-end — 需要 routing endpoint + M2 enclosure 验证 → 保留硬编码
结论: Region 适合几何操作，拓扑问题需要 L2N API (Phase 7)

### 全链路改进总计
```
DRC: 706 → 687 (-19, -3%) ← Region gap fill 更精确
LVS: 112 → 112 (不变) / merges: 8 → 7 (-1)
代码: assemble_gds.py 4823 → 2314 行 (-52%)
模块: 9 个文件 + drc_check + gap_fill = 11 个文件
工具: inline DRC (6 checkpoints), Region-based gap fill
```

### Phase 6 完成 (集成 sweep)
✅ integrated_sweep.py — subprocess + inline Region DRC (M1.b+M3.b)
   4 点本地测试通过 (256s, ~64s/点)
   inline M1.b=422 vs full DRC M1.b=403 (Region 略严格, 排序一致)
⚠️ 还是 subprocess (assembly exec() 不适合多进程)
⚠️ 未在 ECS 大规模验证

### Session 总结 — 全链路改进
```
P1 模块化:    ✅ 4823→2314行, 9模块, 0 error
P2 inline DRC: ✅ 6 checkpoint, DRC_INLINE=1
P3 Region:    ✅(几何) gap_fill+bus_strap, DRC 706→687 (-19)
P4 去硬编码:  ⚠️ debug check ✅, safe_drops Region ✅(-3 DRC), NWell bridge TODO
P5 Schema:    ✅ placement/ties/routing 结构校验, assembly 开头自动跑
P6 集成sweep: ✅ inline Region DRC, 本地测试通过
P7 LVS proxy:  ✅ L2N power connectivity check, LVS_INLINE=1, 检测到 GND-VDD short

DRC: 706 → 684 (-3%) — Region gap fill -19, safe_drops Region -3
LVS: 112 (一致, merges 8→7)
代码: -52% assemble_gds.py
新工具: drc_check, gap_fill, integrated_sweep
```

### 诊断增强 (4 项全部完成 + 验证)
```
✅ #1 DRC 增量诊断 — DRCTracker，每 phase 报 delta:
     bus_straps:     M1.width +3
     access_points:  M1.spacing +284 ← 最大来源
     power:          M1.spacing +110
     signal_routes:  M1.spacing +3, M3.spacing +29
✅ #2 LVS short 定位 — binary search:
     BARE: clean
     Full assembly, 0 routes: SHORT! ← assembly infrastructure 问题!
     ⚠️ 之前认为是浮空 route 导致 — 错误归因
✅ #3 Via2 审计: 78/789 = 10% 成功率，86/131 routes 0 Via2
✅ #4 功能完整性: 12/13 features present
```

### ⚠️⚠️ 关键发现: LVS proxy 有 bug + 根因纠正
LVS proxy 用 Python id() 比较 net 对象 → false positive "GND-VDD SHORT"
修复: 改用 net.cluster_id → **实际没有 GND-VDD short**
真正的 LVS 问题: **power net fragmentation**
  GND: 79 个分离 components (应为 1)
  VDD: 125 个分离 components (应为 1-2)
→ KLayout 提取碎片化 power net 和 reference 单一 net 对不上 → 0 nets matched
之前所有 "GND-VDD SHORT" 都是 false positive (id() bug + 缺 substrate 层)
LVS proxy 修正: 只报 fragmentation, short 判定交给 KLayout LVS
溯源验证: LVS-246 GDS 的 L2N 也报 57/66/3 但 KLayout LVS = 246/0/0 → 证实 false positive

### Y-stretch 闭环测试
DRC 576 (706→576 = -18%), LVS 110 (有 GND-VDD short)

### 诊断工具链修复完成 (7/7)
```
✅ #1 LVS proxy id()→cluster_id
✅ #2 LVS 11层连接: GND 59 frag, VDD 68 frag, 3 shared (真short)
✅ #3 功能检查: 扫描 assemble_gds.py + assemble/*.py, 15/15 ✅
✅ #4 Via2原因: too_far=302, no_m5=190, via_stack=148, no_route=38, unknown=26
✅ #5 DRC位置: hotspot bbox (如 M1.spacing +284 at (3,63)-(195,274))
✅ #6 check_power_separation 用 cluster_id 验证
✅ #7 Power fragmentation: 3 shared clusters 定位到具体 devices
     Cluster 247: BUF/INV/MB区 14 GND + 36 VDD
     Cluster 29: NOL/OTA区 7 GND + 17 VDD
     Cluster 215: BIAS/SR区 2 GND + 7 VDD
```

### 当前诊断能力总结
| 工具 | 能力 | 可靠性 |
|------|------|--------|
| DRC增量 | 每phase新增violations+位置 | ✅ 验证 |
| LVS proxy | 11层power connectivity+fragmentation | ✅ 验证 |
| Via2 audit | 成功/失败+原因分类 | ✅ 验证 |
| trace_drc | shape溯源到代码路径 | ✅ 验证 |
| analyze_drc | 聚类+冲突图+gap分布 | ✅ 验证 |
| 功能检查 | 15 features 完整性 | ✅ 验证 |
| Schema | JSON结构校验 | ✅ 验证 |

### 下一步
### 模块化 LVS 回退根因溯源 (最终结论)
e4b82ae assembly=LVS 246, 模块化 assembly=LVS 112 (同输入 placement/ties/routing)
GDS MD5 不同 (d24e... vs 8db3...) — Region diff 检测不到差异 (sub-polygon level)
可能原因: bus strap Region gap cutting 产生了不同切割形状 (22→21 gaps)
或: _draw_gapped_bus 的 Region boolean vs 手写 interval merge 精度差异
⚠️ 未定位到具体模块 — 需要逐模块二分排查

### LVS 246 基线条件
- placement: git show e4b82ae:layout/placement.json (hash e95a7a2fc59d)
- ties: git show e4b82ae:layout/output/ties.json (hash 747add90abf7)
- routing: git show e4b82ae:layout/output/routing.json (hash bf2bae3ad668, 48 routes)
- assembly: git show e4b82ae:layout/assemble_gds.py (4823 行)
- ⚠️ placement_original.json hash 不同 (31b91da68184) — 不是 246 的 placement!

诊断链条已扎实。可以开始修实际问题：
1. Power fragmentation (GND 79→1, VDD 125→1-2) — 需要连通 power net
2. Via2 成功率 (10%→?) — 302 too_far + 190 no_m5 = 根因
3. M1.b 397 — access_points 引入 284

## ★ Session 4 — DRC 基线排查 + Placement Sweep (2026-03-18 11:00)

### 关键发现

1. **PDK 没问题（铁律确认）**
   - 单个 PCell KLayout DRC: M1.a/b, M2.a/b, V1.a/b 全 CLEAN
   - 验证: /tmp/pcell_drc_test/ 对照组 vs 实验组，IHP 官方 DRC 值

2. **Magic DRC 不可靠 — 以后只用 KLayout DRC**
   - Magic DRC 对单个正确 PCell 报 18-24 errors（M1.a/M1.b/M2.b）
   - KLayout DRC 同一 PCell 报 0 errors（除 M1.d min area 4 个）
   - 原因: Magic tech file DRC 规则和 IHP signoff 标准不一致

3. **之前的 dev_*.mag 被 strip 过**
   - /tmp/magic_soilz/dev_mn1.mag: 60 行，缺 via1+metal2
   - Fresh PDK PCell: 82 行，完整 via1+metal2
   - "bare placement 8158 errors" 是无效测试（测的被破坏的 PCell）

4. **Placement 基本 clean**
   - Clean PCell bare placement KLayout DRC: M1.b=1, M2.b=5, V1.b=17（共 23 inter-device）
   - M1.d=998, M2.d=995 是 PCell 内部 min area（~4/device × 257）
   - 23 个 inter-device violations 可微调解决，不是硬伤

5. **IHP 官方 DRC 值（从 sg13g2_tech_default.json）**
   - M1: width≥160nm, space≥180nm
   - M2-M5: width≥200nm, space≥210nm
   - V1-V4: width=190nm, space≥220nm
   - TopMetal1: width≥1640nm, space≥1640nm
   - TopMetal2: 禁止使用（TT power grid）

### Placement Sweep (2026-03-18 11:45)

**问题**: bare placement KLayout DRC = 23 inter-device violations (M1.b=1, M2.b=5, V1.b=17)

**热点定位** (KLayout violation 坐标 → 器件映射):
- Hot spot A: MBn2↔MBp2 区域 (X≈197, Y≈168-171) — 20 violations
- Hot spot B: INV_isob_n↔Mpb1 区域 (X≈91, Y≈178) — 3 violations

**Sweep 数据**:
```
Combined sweep: INV_isob dy=+1.0, MBp1+MBp2 dy=+N
MBp_dy  M1.b  M2.b  V1.b  total
  0.0     0     4    16     20
  1.0     0     4     7     11
  2.0     0     4     1      5
  3.0     0     2     0      2
  3.2     0     0     0      0  ← minimum clean
  4.0     0     0     0      0
```

**修复方案** (sweep 验证, 最小位移):
- MBp1 (194.5, 171.515) → (194.5, 174.715) [Y+3.2µm]
- MBp2 (197.0, 171.5) → (197.0, 174.7) [Y+3.2µm]
- INV_isob_n (90.0, 178.0) → (90.0, 179.0) [Y+1.0µm]
- INV_isob_p (90.0, 181.5) → (90.0, 182.5) [Y+1.0µm]

**验收**: bare placement KLayout DRC: M1.b=0, M2.b=0, V1.b=0, **total=0**
**状态**: ⚠️ sweep 验证通过，placement.json 待写入（等用户确认）

### 分区合理性分析 (2026-03-18 11:25)

- 比较器输入对 2.76µm 纯 X 偏移 — 好
- OTA 差分对 10.79µm 无共质心 — 30dB OTA 可接受 (assumption)
- VCO↔OTA 边距 ~105µm — 足够
- 数字分频↔OTA 同 Y 带 75µm — 中等风险，后续可加 guard ring
- **结论: 分区功能合理，无硬伤**

### Metal Stack 全貌
```
M1  (8/0)  — device PCell 占用，不能自由走线
M2  (10/0) — device PCell via1+M2 占用
M3  (30/0) — 当前 power rails
M4  (50/0) — 部分 routing + 数字 pin 层
M5  (67/0) — 空闲（但 cap_cmim bottom plate 在此层）
TM1 (126/0) — analog pin + power stripe（min 1640nm 太粗）
TM2 (134/0) — ❌ 禁止
```

### Metal 分层策略调研 (2026-03-18 12:15)

**Via stack reachability 分析** (M3 power rail 挡住 signal via2):
- 629 signal pins, 546 clear, 83 blocked → **reachability = 86.8%**
- OTA/chopper/H-bridge 关键 pin 被挡 → 不可接受
- 结论: power 必须从 M3 移走，找缝隙是打补丁

**IHP SG13G2 真实 tapeout 参考** (5 个设计, IHP Apr 2025 tapeout):
```
设计         M1    M2    M3    M4    M5    TM1   TM2
Bandgap Ref  2.4%  2.4%  2.4%  2.9%  2.7%  16.0% 26.6%
VCO 130nm    2.1%  6.0%  29.8% 28.2% 31.2%  4.7% 11.1%
Mixer 5GHz   8.2%  8.3%  8.9%  8.1%  8.2%  8.6% 11.4%
40GHz TIA   48.5% 38.8% 38.8% 38.8% 38.1% 37.8% 41.3%
GPS LNA     16.6% 16.7% 15.6% 14.4% 15.6% 16.6% 23.7%
```
- **所有设计都用全部 7 层** — 我们只用 M1-M4 是不正常的
- VCO (最相似): M1-M2 轻用 (2-6%), M3-M5 是信号骨干 (28-31%)
- TM1+TM2 用于 power distribution
- 多级 via stack 是标准做法 (GPS LNA 700K+ vias)

**提出的分层方案:**
```
M1/M2    — device PCell（不碰）
M3       — signal routing + via stack 过渡
M4       — signal routing
M5       — signal routing（cap_cmim 区域被 bottom plate 占用）
TopMetal1 — power distribution（TM2 被 TTIHP 禁了）
TopMetal2 — 禁止（TTIHP power grid）
```

**⚠️ cap_cmim 修正**: soilz_design.md 记载 cap_cmim 用 M5(bottom plate)↔TopMetal1(top plate)，
不是参考设计的 M4↔M5。M5 在 3 个 cap 区域被占用，但 cap 只有 3 个 (27×27µm)，
相对 202×261µm 芯片面积影响小。

### Via Stack 可行性验证 (2026-03-18 12:30)

**测试**: 单个 TM1→M1 power via stack (6 级), KLayout DRC
```
TM1     1640×1640nm (min width)
TopVia1  420×420nm
M5       620×620nm
Via4     190×190nm
M4       290×290nm
Via3     190×190nm
M3       290×290nm
Via2     190×190nm
M2       290×290nm
Via1     190×190nm
M1       290×290nm
```
**结果**: width/space 22/22 CLEAN, enclosure 10/10 CLEAN, **total = 0**
**占地**: 1.64µm × 1.64µm (TM1 min width 决定)

**⚠️ unverified**: 单个孤立 stack 测试。实际器件旁边时 TM1 pad 可能和邻近器件重叠，
需要在真实 placement 上验证 power via stack 的 fit。

**状态**: 分层策略 DRC 可行性确认 ✅ (孤立测试)

### Power Via Stack 实际 Placement 验证 (2026-03-18 12:40)

**V1 (失败)**: 153 drops 各放完整 TM1→M1 via stack → 133 violations
- V1.b=93 (新 Via1 和 device PCell 已有 Via1 冲突)
- TM1.b=40 (TM1 独立 pad 互相太近)

**V2 (成功)**: 两处根因修复:
1. 去掉 Via1+M1（device PCell 已有 M1→Via1→M2，不需要重建）
2. TM1 用 stripe 代替独立 pad（同 Y 带 drops 共享一条横条）

**结果**: 153 power drops + 257 devices, **KLayout DRC = 0** (所有 metal space + via space + TM1 width)

**⚠️ unverified**:
- V2 的 M2 pad 是否真的和 device PCell M2 在同一位置（via_x/via_y 来自 ATK routing.json）
- TM1 stripe 是否和 TTIHP tile 已有的 TM1 power stripe 冲突

**状态**: power on TM1 实际可行性确认 ✅

### Signal Router Step 1: Pin 位置确认 (2026-03-18 13:00)

**发现**: device_lib_magic.json 的 pos_nm 是 M1 级 pin center，NOT M2 pad 位置。
Via2 放在 pos_nm 上无法接触 device M2 geometry（6 种 device type 验证全部 ❌）。

**解决**: 使用 ATK routing.json access_points 的 (x,y) 作为 Via2 连接点。
ATK AP 有 M1 stub + Via1 + M2 pad (880nm)，Via2 直接落在 M2 pad 上。

**验证**: 1268 ATK APs + 257 unstripped devices → KLayout DRC = 0
- M1.b/M2.b/V1.b 全 CLEAN

**结论**: 复用 ATK access_points 位置，废弃的只是 routing segments。

### Signal Router Step 2: Candidate Generation (2026-03-18 13:15)

- signal_router.py: `compute_pin_positions()` 用 ATK AP (x,y)，`generate_candidates()` 生成 L-routes
- 135 nets → 618 candidates (2-pin: 2-3 variants, multi-pin: 6 variants)
- **DRC 验证**: 12 条 candidates (2/4/8-pin, 多种变体) 全部 KLayout DRC = 0 ✅

### Via2→M3 电气连通验证 (2026-03-18 13:25)

**测试**: Mtail device + AP (M1 stub+Via1+M2 pad) + Via2 + M3 pad → Magic extract
**结果**: SPICE output `X0 ... TEST_M3 ...` — Drain terminal = M3 label
**结论**: device M1 → M1 stub → Via1 → M2 → Via2 → M3 电气连通 ✅

### TM1 Power Via Stack 电气连通验证 (2026-03-18 13:35)

**测试**: Mtail device + AP (M1 stub+Via1+M2) + Via2→M3→Via3→M4→Via4→M5→Via5→TM1
**第一次失败**: Magic 输出 `dev_mtail_0.S`（未连通）
**原因**: Magic 层名错误 — `topvia1` 不存在，应为 `via5`
**修正后**: SPICE `X0 PWR_TM1 ...` — Source = TM1 label ✅

**Magic 层名映射 (必须用这些写 .mag)**:
```
Via4     → << via4 >>
Metal5   → << metal5 >>
TopVia1  → << via5 >>      ← 不是 topvia1!
TopMetal1 → << met6 >>     ← 不是 topmetal1!
```

**教训**: KLayout DRC (GDS layer 125/0) clean ≠ Magic .mag 正确。两套体系，都要验。

### Signal Router Step 3: build_soilz_mag() (2026-03-18 13:50)

- genome = {net: 0 for all 135 nets} (candidate 0 for every net)
- 输出: 19423 行 .mag, 257 devices, 1268 APs, 153 power via stacks, 135 route sets
- Magic load ✅, flatten ✅, GDS 1.3MB ✅
- Power drops: 153/153 有匹配 AP ✅, 257/257 devices 在 .mag ✅

### Signal Router Step 4: 本机 LVS Pipeline (2026-03-18 14:05)

**测试**: soilz.mag (candidate 0 for all 135 nets) → Magic extract → SPICE X→M → Netgen LVS
**结果**:
- Magic ext2spice: 成功（macOS 未 hang）, 260 devices extracted
- SPICE 转换: 248 real (241 MOS + 4 R + 3 C), 11 parasitic filtered
- Netgen LVS: **57/255 devices matched** (baseline, 无 GA 优化)
- Mega-net: `dev_rin_0.B` 715 connections (substrate/cross-net merging)

**分析**: 57/255 是 candidate 0 的 baseline。cross-net shorts 来自 135 routes 全选 candidate 0
互相冲突。GA 优化应能显著提高。

### Bare Baseline 分析 (2026-03-18 14:15)

**Bare (devices + APs + power, 无 signal routing) LVS:**
- Extracted: 259 devices → Netgen merged 186 parallel → **73 devices**
- Reference: 257 devices → merged 2 → 255 devices
- 73/255 match

**原因**: 无 signal routing 时，同类型同尺寸 device 电气不可区分 → Netgen parallel merge。
这是**正常行为**，不是 layout bug。signal routing 的作用就是区分这些 device。

**对比**:
- Bare: 73/255 (186 merged)
- Candidate 0: 57/255 (routing cross-net 使 merge 更多)
- GA 目标: >> 73, 趋向 255

**Pipeline 验证 ✅**: 端到端干净，merging 是 Netgen 数学性质，不是 layout 错误。

**assumption**: "GA 搜索空间足够" — L-route candidates + M3/M4 两层能否支撑 135 nets
不 cross-net，需要 ECS 实际跑才知道。

### GA 首跑 + 失败分析 (2026-03-18 15:00)

**GA 跑到 Gen 34, alltime best = 83**（bare baseline = 73）。

**问题 1: score 含义搞错了**
- GA 返回的 83 = extracted circuit 的 post-merge device count（不是 matched device count）
- 255 = reference 的 device count（无 merge）
- 83 意味着 routing 只多区分了 10 个 device（83-73），远不够

**问题 2: ECS 运维失败**
- pop=192 = nproc → SSH daemon 无 CPU → 无法监控
- Popen + poll loop → Magic 僵尸进程累积 → load 6767 → 内存满
- 应该: pop=nproc-4, subprocess.run+timeout, 共享 PCell symlink

**问题 3: L-route candidates 没有严格 H/V 分层**
- Variant C (all M3) 和 Variant D (all M4) 违反 H/V 纪律
- 严格 H/V: M3 只水平, M4 只垂直 → 交叉不 short → 减少 cross-net

**问题 4: evaluate 函数 3 次修改 (mole-whacking)**
- echo→file redirect→poll+kill，根因是没在本机充分测试
- 教训: **在本机完整跑通 evaluate 一次再上 ECS**

**教训汇总:**
1. Score 的含义必须在本机验证后再 GA
2. ECS 运维纪律: pop=nproc-4, 监控≤30s, 高IO云盘
3. 本机完整测试 evaluate → 确认返回值正确 → 再上 ECS
4. L-route 必须严格 H/V 分层

### 当前讨论: 分层策略的正确使用方式
- M3 只水平, M4 只垂直, Via3 在交叉点
- 交叉不 short（不同层）, 冲突只发生在同方向 parallel 线
- M5 作为第三层可进一步缓解拥挤
- 需要重新设计 candidate generator 严格遵守 H/V

### Routability 分析 (2026-03-18 15:55)

**容量 (M3+M4 only):**
- M3 tracks: 636, M4 tracks: 492
- 需要 segments: 476 (nearest-neighbor chain)
- M3 利用率: 74.8%, **M4 利用率: 96.7%** ← 瓶颈！
- M3 无优化 parallel conflicts: 263 对
- 最拥挤 Y-band: 18 segments (VCO 区域 Y≈200µm)

**对比参考设计 (IHP VCO tapeout):**
- M3: 29.8%, M4: 28.2%, M5: 31.2% — 三层均匀使用
- 我们只用 M3+M4 → M4 96.7% → 策略定了但没落实

**加 M5 后:**
- 三层 total tracks: 1764, 需要 476 → **利用率 27%** → 充裕
- M5 上有 cap_cmim 占部分面积 (assumption: 影响小)

### 分层策略确定 (2026-03-18 16:10)

**三层 H/V 分配（routability 分析验证）：**
```
M3 = Horizontal (水平)  — 636 tracks
M4 = Vertical   (垂直)  — 492 tracks
M5 = Vertical   (垂直)  — 492 tracks (cap_cmim 仅占 1.5%)
```

**方案对比（选 M5-V 的原因）：**
| 方案 | H 利用率 | V 利用率 | 判断 |
|------|---------|---------|------|
| M3H+M4V (两层) | 74.8% | 96.7% | M4 爆 ❌ |
| M3H+M4V+M5H | 37.4% | 96.7% | M4 仍爆 ❌ |
| **M3H+M4V+M5V** | **74.8%** | **48.4%** | **平衡 ✅** |

**容量验证：**
- 需要: 476 H-segments + 476 V-segments
- H tracks (M3): 636, 利用率 74.8%
- V tracks (M4+M5): 984, 利用率 48.4%
- cap_cmim 占 M5 面积: 1.5%（3 个 cap, 816 um²/52722 um²）
- **结论: 容量充足，两方向均衡**

### M5-V Route 验证 (2026-03-18 16:15)

**测试**: M3-H → Via3 → M4 pad → Via4 → M5-V → Via4 → M4 → Via3 → M3 → Via2 → M2
**电气连通**: Magic extract `equiv "PIN1_M2" "PIN2_M2"` ✅
**KLayout DRC**: M2-M5 + V2-V4 全 CLEAN ✅

M5-V 需要 Via3+Via4 两级跳，比 M4-V (Via3 一级) 多一级，但无额外 DRC 风险。

### 完整分层策略（冻结）
```
M1/M2    — device PCell（不碰）
M3       — signal routing HORIZONTAL
M4       — signal routing VERTICAL
M5       — signal routing VERTICAL（避开 3 个 cap_cmim 区域）
TopMetal1 — power distribution (TM1 stripes)
TopMetal2 — 禁止 (TTIHP)
```

### 贪心 Track Assignment (2026-03-18 16:25)

**结果**: 476 H + 476 V segments, **0 conflicts** (<1 秒)
- H conflicts (M3): 263 → 0
- M4: 449 segments, M5: 27 segments (5.7%)
- 之前 "M4 96.7% = 瓶颈" 是错误结论（没考虑空间分布）

**⚠️ M5 干预决策点:**
当前不干预。如果后续 M4 via pad DRC 冲突 → 回来把部分 M4 移到 M5。

**⚠️ 0 conflicts ≠ DRC clean:**
只检查了 parallel wire spacing，没检查 via pad 冲突、power via stack 冲突。

### Routing 障碍验证 (2026-03-18 17:00)

**贪心 H/V routing LVS = 51/255** — routing 引入 cross-net 比 bare (73) 更差。

**根因分析 (两个假设验证):**
- H1: Signal M3 wire 碰 power via stack M3 pad → **146 处 overlap ✅ 主因**
- H2: M3/M4 穿过 device bbox → **Device PCell 无 M3/M4 geometry ✅ 不是问题**

**验证：Device PCell M3/M4/M5 geometry**
- MOSFET (mn1, pm3, mtail): 无 M3/M4/M5 ✅
- 电阻 (rptat, rin, rout, rdac): 无 M3/M4/M5 ✅
- **cap_cmim (C_fb, Cbyp_n, Cbyp_p): 有 M5 (bottom plate)** ✅

**Routing 障碍清单 (事实，全部验证):**
```
必须绕开:
1. 153 power via stack pads — M3+M4+M5 上各有 290nm pad
2. 3 cap_cmim — M5 上有 bottom plate geometry
不需要绕开:
3. Device bboxes — PCell 无 M3/M4 geometry，穿过不 short
4. 电阻 PCell — 同上
```

### Obstacle-Aware Greedy Routing 尝试 (2026-03-18 17:20)

**实现**: 贪心 L-route + power pad avoidance + 已 route 线作 obstacle + strict H/V
**结果**: 80/135 nets routed, 55 failed

**LVS**: 171/255 post-merge devices (bare=73, 无 obstacle=51)
**但分析显示问题严重:**
- mega-net dev_rin_0.B: 185 connections（bare=149, 无obstacle=782）→ 改善但没消除
- **528/619 unique nets 只有 1 个 connection（isolated pins）**
- routing 碎片化: 连了一些 pin 但大部分断了
- 55 failed nets 的 pins 完全未 route

**Routing inline 代码迭代 (mole-whacking):**
1. L-route candidates + GA → M3 jog 违反 H/V + cross-net
2. 贪心 track assignment → 无 obstacle → 穿过 power pads → mega-net
3. strict H/V → 修了 jog 但仍穿 power pads
4. obstacle-aware → 好了但 routing 质量不够（碎片化）

**教训**: 临时 inline Python 脚本不是 router。每次修一个问题暴露下一个 = 打地鼠。
需要正式的 router 模块，从设计开始，不是边跑边改。

### Session 4 总结

**已验证确认 (干净的基础):**
- PDK clean ✅
- Placement DRC = 0 ✅ (commit eff808b)
- 分层策略 M3-H M4-V M5-V ✅ (容量 + DRC + 电气连通)
- Power on TM1 ✅ (153 drops DRC clean + 电气连通)
- 障碍清单 ✅ (153 power pads M3/M4/M5 + 3 cap_cmim M5)
- Via2→M3 电气连通 ✅ (Magic extract)
- TM1→M1 power 电气连通 ✅ (Magic extract)
- Magic 层名映射 ✅ (via5=TopVia1, met6=TopMetal1)
- Device PCell 无 M3/M4 geometry → device bbox 不是 routing obstacle ✅

**未完成:**
- ❌ 正式的 obstacle-aware router（需要设计，不是 inline 脚本）
- ❌ 192 核 net ordering sweep
- ❌ LVS clean
- ❌ KLayout DRC clean

### SAGERoute 尝试 + 放弃 (2026-03-18 17:50)
- IHP tech file 创建成功，SAGERoute binary 跑通但 18ms = 没识别 nets
- 黑盒 binary 不可调试 → 放弃

### PDK 完整审计 (2026-03-18 17:30)
- layout_rules.pdf + process_spec.pdf 全读完，DRC 三处交叉验证一致
- 完整参考: docs/pdk_reference.md
- LEF: M5=H（我们用 V，不违反 DRC）

### 最终方案: ATK Maze Router 改造 + 188 核 Sweep

**改造内容 (~80-120 行):**
1. 层重映射: 0→M3, 1→M4, 2→M5 + pdk.py 加 M5/Via4
2. 删 `_block_power_rails_m3()` + 重写 `_block_power_drops()` → 153 power pad obstacles
3. 删 device bbox blocking (PCell 无 M3/M4)
4. Via2 bridge 预画 (M2 AP → M3)
5. H/V direction cost bias
6. 并行: 188 核 random net ordering → A* routing → Magic LVS → 选最优

### ATK Maze Router 改造 (2026-03-18 18:00)

**已完成的代码改动:**
- pdk.py: +M5/Via4/TopVia1/TM1 constants (IHP PDK 值, V4_ENC=50nm not 90nm)
- maze_router.py: 4-layer→3-layer (0=M3, 1=M4, 2=M5), N_ROUTING_LAYERS=3
  - range(4)→range(N_ROUTING_LAYERS)
  - VIA_PAIRS: {(0,1), (1,2)} = Via3 + Via4
  - junction vias 通用化 (不再 hard-code layer 3)
  - **H/V direction cost bias**: M3=H(1x) M4/M5=V(1x), wrong dir=4x penalty
- solver.py: 禁用 device bbox/tie/M3 power 阻塞，加 _block_power_pads_m345()
  - 153 power pad obstacles on M3/M4/M5
  - 3 cap_cmim obstacles on M5

**单 net 测试 (50×50µm grid):**
- Route found: 172 steps, H=85 V=85, Via=1
- H/V discipline: 0 violations ✅
- Obstacle avoidance: power pad avoided ✅

**未完成:**
- assemble_gds.py GDS 层映射 (router code 0→M3, 1→M4, 2→M5, -1→Via3, -2→Via4)
- 真实 135 nets 全量测试
- 188 核并行化脚本

### 全量测试 (2026-03-18 18:45)

**Bug fixes discovered during testing:**
- AP key: string "inst.pin" → tuple (inst, pin) — power pads were 0, now 453 ✅
- H/V bias: 4x penalty → hard block (continue) — violations 325→0 ✅

**结果 (seed=0):**
```
Routed: 127/135 nets (8 failed)
Check 1 H/V: 0 violations ✅
Check 2 Obstacles: 1 overlap (需查原因)
```
8 failed nets: t3_m, t4I_mb, div2_Q, t4I_m, t2Q_nsn, t1Q_m, mxfq_selb, div2_I_b
原因: strict H/V + obstacles 导致部分 pin 不可达 → net ordering sweep 应能改善

### Check 1+2 验证 (2026-03-18 19:00)

**Bug fixes:**
- AP key: string→tuple, power pads 0→453 ✅
- H/V: 4x penalty→hard block (continue), violations 325→0 ✅

**结果 (seed=0, 修正后):**
```
Routed: 127/135 nets (8 failed)
Check 1 H/V: 0 violations ✅
Check 2 Obstacles: 1 overlap (vptat layer=M4, Rout.MINUS pad, grid boundary case)
```

1 overlap 原因: wire 边缘和 pad 边缘重叠 65nm (grid 350nm 量化边界 case, 非结构性问题)
8 failed: VCO 区域 pins stuck (t3_m, t4I_mb, div2_Q, t4I_m, t2Q_nsn, t1Q_m, mxfq_selb, div2_I_b)

### 下一步
1. 输出 routing.json → assemble_gds → GDS
2. Check 3: KLayout DRC
3. Check 4: Magic LVS
4. 188 核 net ordering sweep

---

## ★ COMPACT 入口 (2026-03-18 Session 2+3 成果)

### 核心成果
- **LVS**: 126/255 (49%) → 252/255 (98.8%) [strip PCell M2] 或 230/255 (90%) [no-strip]
- **KLayout DRC**: ~10K [strip] 或 2164-4006 [no-strip]
- **GA 进化路由**: 192-core ECS, 50 gen × 1.6s = 80s 完成
- **Magic + Netgen LVS pipeline 全自动**
- **84 commits**

### 当前瓶颈: Metal 层分配错误

**ATK routing.json 的 signal routing 55% 在 M1+M2 (device 层), 44% 在 M3+M4:**
```
M1: 93 segments  ← device PCell 也用 M1 → 冲突
M2: 747 segments ← device PCell 也用 M2 → 冲突 (核心问题)
M3: 223 segments (主要是 power)
M4: 443 segments
M5-M7: 0 ← 3层完全空闲!
```

**Strip M2 vs No-strip trade-off (不可调和):**
| | Strip PCell M2 | No Strip (正确) |
|---|---|---|
| LVS (GA) | 252/255 ✅ | 230/255 |
| KLayout DRC | ~10K ❌ (M1 geometry broken) | 2164-4006 |
| 可制造 | ❌ 缺 via1+M2 | ✅ PCell 完整 |

**结论: strip 是错误路径。no-strip 是唯一可行方向。但 no-strip 下 M2 routing 和 device M2 冲突导致 LVS-DRC 互斥。**

### 已验证的技术 (可复用)
1. **GA evolutionary router** — 192 population, segment include/exclude, 50 gen 收敛
2. **strip_pcell_m2.py** — PCell via1+M2 strip (LVS 有效但 DRC 不行)
3. **M1 stubs** — device pin → AP via1 连接 (gen_magic_layout.py)
4. **M2 pad size sweep** — 36720 variants, optimal 440nm
5. **KLayout Python DRC** — check_drc.py via subprocess (M1.a/b, M2.a/b, V1.a)
6. **SPICE X→M conversion** — convert_spice_for_netgen()
7. **Parasitic filter** — remove W<100nm or L<100nm devices

### 待解决的核心问题
**Signal routing 需要从 M1/M2 移到更高层 (M4/M5 或 M3/M4)**

这不是参数调优能解决的 — GA 已证明 ATK routing.json 的 Pareto 极限。
需要重新生成 routing 在正确的 metal 层上。

**具体挑战:**
1. Via stack: device M2 → via2 → M3 → via3 → M4 — M3 有 power rails 可能挡路
2. M4+M5 routing 的 cross-net — 需要 H+V 分层或 obstacle avoidance
3. 没有现成的 M4+M5 maze router — ATK 不支持，qrouter 不适合模拟
4. IHP 有 7 层 metal (M1-M5 + TopMetal1/2) 但我们只用了 M1-M4

**可能的方向:**
- A) 改 ATK maze router 的层分配 (M2 routing → M4, 保留 M3 power)
- B) 写新 router 直接在 M4+M5 上 route (用 GA 优化)
- C) Power 移到 M5/TopMetal, 腾出 M3 给 signal via stack
- D) 用 GA 直接进化 routing geometry (不限于现有 segments)

### Pipeline (当前)
```
netlist.json + placement.json + device_lib_magic.json
    ↓
gen_magic_layout.py → soilz.mag (devices + routing from routing.json)
    ↓ (可选)
strip_pcell_m2.py → 去掉 MOSFET via1+M2
    ↓
Magic flatten → extract → ext2spice → soilz_flat.spice
    ↓
convert X→M + parasitic filter → soilz_clean.spice
    ↓
Netgen LVS: soilz_clean vs soilz_lvs.spice → comp.out
    ↓
KLayout Python DRC: check_drc.py on GDS → violation count
```

### ECS 服务器
- **Image**: m-bp12fk5utga3kbvre90j (Magic+Netgen+KLayout+IHP-PDK)
- **推荐**: ecs.c8a.48xlarge (192C/384G) ~3 CNY/h spot
- **Skill**: .claude/skills/ecs-magic.md
- **GA 性能**: 50 gen × 192 pop = 9600 variants in 80s (LVS-only) 或 ~13min (LVS+DRC)

### 关键文件
| 文件 | 作用 |
|------|------|
| layout/atk/gen_magic_layout.py | JSON → soilz.mag (devices + routing) |
| layout/atk/strip_pcell_m2.py | Strip PCell via1+M2 (LVS 用, DRC 不行) |
| layout/atk/ga_router.py | GA evolutionary router |
| layout/atk/magic_net_router.py | Direct chain router (失败, 16/255) |
| layout/output/ga_best_genome.json | GA 最佳 genome (strip 252) |
| layout/output/nostrip_ga_best.json | GA 最佳 genome (no-strip 230) |
| /tmp/check_drc.py | KLayout Python DRC (需要在 server 重建) |

### #155 教训 (HARD RULE)
- 所有 DRC violations 归因于自身 routing/placement, 不归因 PDK
- PDK PCell 正确使用时 DRC clean, 不需要 waiver
- 不编造验证结果, 不改写工具输出

---

## Current Status (2026-03-17 — Session 2, continued)

### Magic Pipeline — LVS 126→197 突破 ✅ (已验证)

**两个上游修法 + 验证结果：**

1. **Strip PCell via1+M2** (`atk/strip_pcell_m2.py`)
   - IHP PCell 在 S/D 画了 via1+M2 enclosure pad (convenience routing)
   - 所有 257 devices 都是 nf=1，M2 不做 multi-finger strap → 100% 安全 strip
   - 效果：消除 routing M2 和 device M2 的意外短路

2. **画 M1 stub** (gen_magic_layout.py AP section)
   - 1011 个 AP 有 m1_stub 字段（连接 device pin M1 到 AP via1）
   - **之前从未画出** → device pin 和 routing 之间没有金属连接
   - 效果：建立正确的 device→AP→routing 连接链

**验证结果 (pipeline 实际输出):**
```
Phase A: 257 device subcells → strip via1+M2 (254 files, 5548 lines)
Phase B: soilz.mag 13204 lines (routing 1388 seg, 220 filtered)
Phase C: flatten → extract → 274 devices (267 MOS + 4R + 3C)
Phase D: X→M conversion → soilz_netgen.spice
Phase E: Netgen LVS → 197 vs 255 (77% match)
```

| 指标 | Session 开始 | 现在 | 改善 |
|------|-------------|------|------|
| After merge | 126 | **197** | **+71 (+56%)** |
| Parallel merges | 148 | **77** | **-71 (-48%)** |
| rptat refs | 14 | **0** | **完全消除** |
| D=G=S devices | 36 | 22 | -14 |
| Match rate | 49% | **77%** | +28pp |
| Comma merges | 0 | 0 | 保持 |

**Pipeline (全自动):**
```
gen_magic_layout.py → soilz.mag (smart filter + M1 stubs)
    ↓
Phase A (PCell subcells) → strip_pcell_m2.py → Phase C (flatten+extract)
    ↓
SPICE X→M conversion → Netgen LVS → comp.out
```

**代码修改 (已验证):**
- gen_magic_layout.py: smart filter (Magic bbox) + M1 stub drawing + SPICE X→M + flat extraction
- atk/strip_pcell_m2.py: 新建，strip device subcell via1+M2

**Hierarchical extraction 进一步改善 (已验证):**
- Inline dev_* subckts → M-format: 257 raw (= reference), 203 after merge, 54 merges
- Flat extraction: 259 raw (去 parasitic), 196 after merge, 63 merges
- **Hierarchical 更好: 203/255 = 80%**

**54 merges 根因分析:**
- 462 extracted nets vs 145 reference — net 碎片化
- .ext merge records: 1065 merges, 1015 ports connected
- ⚠️ 758/764 signal ports appear in merge chains (99%), 但很多连到碎片 net（不是正确的 signal net）
- **主因: 没有 ntap/ptap ties** → NWell/pwell 不连接 vdd/gnd → power topology 不匹配
  - NWell net w_n90_n131# 有 92 fanout 但和 vdd (dev_mpb5_0/S, 39 fanout) 分离
- D=G=S: 只有 5 个（hierarchical 比 flat 的 22 干净很多）
- Parasitic devices: 0（hierarchical 天然无 parasitic）

**尝试过但失败的方向:**
- Physical ties (ntapc/ptapc in .mag): Magic ext2spice 挂起 (10+ min timeout)
- Well net post-process merge: 反效果 (203→197)，合并 well 使更多 PMOS 看起来一样

**结论:** 54 topology-based merges 需要更丰富的 signal routing 区分 devices，
不是 well/power 修法。当前 routing coverage 已 99%，但很多 net 碎片化 (462 vs 145)。

**深层分析 (已验证):**
- Hierarchical extraction 的 203 结果是 M1-M1 direct overlap (不经 via1→M2)
- Parent cell's routing metal (M1/via1/M2) 在 hierarchical mode 不被提取 (parent .ext 只有 M4)
- Flat extraction 中 M1 routing 被 device ndiffc 吸收 — 这是合法连接机制
- 10 个 M1 nodes 有 M2 area → via1 连接在 flat mode 确实工作
- 318 equiv records = 设备间直接连接 (全部通过 M1/ndiffc overlap)
- Via1 size 95→100nm 修复 (避免 180nm rounding) 但对结果无影响

**Endpoint alignment 调查结果 (已验证):**
- routing segment endpoints 0% 精确在 AP 位置上，98% 距离 >50nm
- 根因：maze router 在 grid 上 route，assemble_gds.py 负责 bridge grid→AP gap
- Magic pipeline 没有 assemble_gds.py → gap 无人填
- Snap 修正尝试失败：leaf-only same-net snap (380/387) 导致 163/255 (更差)
- 全量 snap 更差 (124/255) — cross-net + junction 破坏
- qrouter 编译成功但不适用（数字 router，不支持 analog pin layout）
- magic_net_router.py bus routing 也失败 (16/255) — M2 cross-net
- **结论：需要在 Magic pipeline 里实现 grid→AP bridge（类似 assemble_gds 的 M2 pad bridge 功能）**

**Bare-device baseline (关键验证):**
- 完全无 routing（只有 device placement）: 18/255 = 7%
- 有 routing: 204/255 = 80%
- **Routing 贡献 +186 devices (+73pp)** — pipeline 方向正确
- 剩余 51 devices 是 routing coverage 不足，不是架构问题
- 后续尝试均失败 (bus 16, snap 124/163, bridges 202) — guess-and-check 不行
- Bare device baseline: 18/255 (7%) → routing 贡献 +186 devices，pipeline 方向正确
- 诊断方法论验证成功：comp.out→51 unmatched→30 gap→9 safe bridges→204→206
- 9 verified bridges: DRC-safe (M2 spacing 210nm check), +2 NMOS
- 21 bridges rejected (cross-net M2 conflict)
- **新 baseline: 206/255 = 81%** (with 9 verified M2 bridges)

**根因精确定位 (已验证，非猜测)：**
- 51 unmatched devices 全部列出 (comp.out): 44 NMOS + 4R + 3C, 0 PMOS
- 72/132 pins 有 correct M2 overlap (connections exist) 但 devices 仍 unmatched
- 原因：8 对 routing M2 cross-net overlap 将 reference nets 合并
  - freq_sel ↔ ref_I, div16_Q ↔ ref_Q, div2_I_b ↔ div4_I_b, etc.
- 这不是 AP/bridge/filter 问题，是 **routing.json 本身的 M2 wire spacing violation**
- 移除冲突 segment 给 203 (更差) — 因为同时断开了正确连接
- 正确修法：缩短 segment 而不是删除，需要精确几何计算 overlap 起止点

**ECS 服务器 parameter sweep (已验证, 41 变体并行):**
- 实例: ecs.c8a.16xlarge (64C/128G), 镜像: m-bp1ggcaq0hx2jsi2479m
- M2 pad half-size sweep 200-1000nm, step 25nm:
  - pad240 (当前): 193
  - pad400: 196
  - **pad450: 227** ← BEST
  - **pad475: 227** ← BEST (tied)
  - pad500: 223
  - pad600: 218
  - pad800: 108 (太大→cross-net)
- M2 wire width sweep (pad600): w100=219, w150=218, w200=210, w300=170
- Filter on/off: pad400 filter=206 nofilter=206 (相同)
- **最佳: M2 pad 950nm (±475nm) → 227/255 = 89%**
- 从 session 开始 126 → 228 = **+102 devices (+40pp)**

**GA 进化路由 (ECS c8a.48xlarge 192C/384G, 已验证):**
- Genetic Algorithm: 192 population × 50 generations = 9600 variants in 80 seconds
- 进化曲线: 228→235→241→248→252, converged at Gen 29
- **最终: 252/255 = 98.8% — 只差 3 devices!**
- GA 发现: smart filter 过度过滤 + 保留了错误 segments
  - 恢复 91 个被过滤的 segment
  - 移除 225 个通过的 segment
- Best genome saved: output/ga_best_genome.json
- GA script: atk/ga_router.py

**Session 总成果: 126→252, 49%→98.8%, +126 devices**

**ECS 服务器:**
- 实例: ecs.c8a.48xlarge (192C/384G)
- 镜像: m-bp1ggcaq0hx2jsi2479m (ic-magic-20260317)
- 36720-variant parameter sweep: 4 分钟
- GA 50 代进化: 80 秒
- 总费用: <10 CNY

**Combined LVS+DRC GA (192C, 已验证):**
- fitness = LVS×1000 - DRC, 100 generations
- 结果: **LVS:252 + DRC:0** — 全部 100 代一致
- DRC=0 因为 strip PCell M2 消除了 device 内部 DRC 源，routing DRC clean
- 手动 SPICE fix 验证: 修 R/C terminal nets → 256/255 (全 match)
- **255/255 拓扑可达，剩余 3 cap 需 routing 连到 pin (12-15µm gap)**

**服务器已释放。镜像保留: m-bp1ggcaq0hx2jsi2479m (ic-magic-20260317)**
**总费用: ~10 CNY**

**⚠️ 重要修正 (2026-03-18):**
- "DRC=0" 是 Magic DRC，不是 KLayout DRC (signoff standard)
- KLayout DRC (strip): ~10K violations — strip PCell via1+M2 破坏 M1 geometry
- KLayout DRC (no-strip): 2726 violations — PCell 完整，M1.a=0 ✅
- **Strip 是错误路径** — PCell 必须完整才能通过 KLayout DRC
- No-strip + GA best genome: LVS=172 (需要重新 GA 优化)

**No-strip vs Strip 对比 (本地验证):**
| | Strip | No Strip |
|---|---|---|
| LVS | 252 | 172 |
| KLayout M1.a | 5596 | **0** |
| KLayout M1.b | 4310 | 1827 |
| KLayout M2.a | 747 | 549 |
| KLayout total | ~10K | **2726** |

**下一步 (下 session):**
1. 开 ECS (image m-bp12fk5utga3kbvre90j)
2. 跑 **no-strip GA**: fitness = LVS×10000 - KLayout_DRC
3. python_drc 内联到 GA (fix multiprocessing)
4. ✅ No-strip combined GA 已跑 (192C, 50 gen)

**No-strip GA 结果 (PCell 完整, KLayout DRC, 已验证):**
| GA 权重 | LVS | KLayout DRC |
|---------|-----|-------------|
| DRC-only | ~200 | **2164** |
| Balanced (×5000) | **230** | 4006 |
| LVS-heavy (×10000) | 227 | 3638 |

**Pareto 极限已明确：当前 routing.json 下 LVS 和 DRC 互相矛盾。**
- 更多 routing → LVS ↑ 但 DRC ↑（M2 routing 和 device M2 冲突）
- 更少 routing → DRC ↓ 但 LVS ↓（连接断开）
- 突破需要：routing 在 M3+ 层走（避开 device M2），或 placement 调整（M1 spacing）

**下一步：**
1. 分析 DRC 2164 中多少是 M1.b (placement) vs M2 (routing) — 决定是改 placement 还是改 routing 层
2. 考虑 M3 signal routing（device M2 不冲突，但需要 via2 stack）
3. 或调整 placement 增加 device 间距（减少 M1.b violations）

**当前瓶颈: routing solver quality**
- 576 extracted nets vs 145 reference → 太多 low-fanout 碎片 net
- 需要 routing solver 生成更长、更连通的 routes
- 这是 upstream (routing 阶段) 问题，不是 pipeline (Magic 提取) 问题

**下一 session 优先级:**
1. 分析 routing.json 的 segment 覆盖率 — 哪些 net 的路由没到达 device pin
2. 改进 solve_routing.py 在 Magic 坐标系下的 AP 连接
3. 考虑：是否需要重新运行 solve_routing.py with ATK_MAGIC=1
4. 目标: net count 从 576 降到 <200 → device match >90%

---

## Previous Status (2026-03-15 20:00)

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

**KLayout LVS on Magic GDS (2026-03-17 15:07):**
- Netgen: 编译安装但无 Tcl 支持 (non-Tcl mode 不兼容 IHP setup.tcl)
- **用 KLayout LVS 验证 Magic GDS** ← 最快验证路径
- 结果:
  - Devices matched: **115** (vs ATK pipeline 246)
  - **Comma merges: 0** ← 巨大胜利！ATK pipeline 有 2-3 个无法消除
  - Wrong-bulk PMOS: 127 (没画 NWell + ntap ties)
  - Nets matched: 0 (routing connectivity 不足)
  - Pins matched: 501

**结论**: Magic 路线的优势确认:
- ✅ 0 comma merges (well/tap 原生处理)
- ✅ 115 devices matched (device 提取正确)
- ❌ Routing connectivity 需要继续完善
- ❌ NWell ties 需要加入 gen_magic_layout

**NSD/PSD post-processing 成功 (2026-03-17 15:18):**
- Magic GDS export 不写 NSD(7)/PSD(14) — 写 nBuLay(32) 代替
- KLayout post-process: NSD = Activ & NWell, PSD = Activ - NWell
- 结果: **wrong-bulk 127→0, comma merges 0, 151 unmatched nets**
- 255 devices extracted (126P + 122N + 4R + 3C) — 接近 257
- 只有 3 devices matched (3 CAP) — routing connectivity 不足导致 topology 不匹配

**综合对比:**
| 指标 | ATK pipeline (DRC 144) | **Magic pipeline** |
|------|----------------------|-------------------|
| Comma merges | 2 | **0** ✅ |
| Wrong-bulk | 1 | **0** ✅ |
| Devices extracted | 257 | **255** |
| Devices matched | 246 | 3 (routing 限制) |
| Nets unmatched | 315 | **151** |

**结论**: Magic 路线解决了所有 ATK 的根本问题。
**瓶颈**:
1. NSD/PSD layer derivation (MOS 识别): IHP LVS 用 `nactiv = activ.not(psd)`, `pactiv = activ.and(psd)`. PSD 是关键 layer, NSD 次要
2. routing connectivity (KLayout→Magic 坐标对齐)
3. ⚠️ 修正: "255 devices extracted" 实际是 KLayout 只提取了 3 CAP, 252 是 REF 侧 device

**下一步**:
1. routing 坐标对齐 (S-pin shift 已验证 99 devices in Magic extraction)
2. NSD/PSD post-process 集成到自动化
3. 目标: device matched > 200

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
Netgen Tcl LVS working. Full loop: Magic→Netgen. 269 devices extracted, LVS mismatch (routing gap).

### Final Session Results (2026-03-17 16:25)
- abs_pin_nm Magic fix: origin=placement (no bbox offset) → AP delta = (0,0) ✅
- 106 devices fully connected (39%), 19 none (7%), 149 partial
- Netgen LVS: 274 extracted → 122 after merging vs 255 reference
- Mega-net: 168 terminals (rptat routing area, cross-net overlap)
- All milestones committed (57 commits ahead of origin)


### Smart routing filter (2026-03-17 16:45)
- Skip routing segments overlapping wrong-device bboxes (206/1608 = 13%)
- Result: 1 mega-net (substrate 143), 72 multi, 39 well-connected
- Netgen: 126 merged vs 255 reference (from 122 before — less merge = better)
- 81 full devices, 37 none — balanced connectivity vs isolation


### Parallel merge analysis
- Only 4 actual parallel groups (15 merged), not 148 as Netgen reports
- Rptat: 11 NMOS on dev_rptat_0.R1 (residual cross-net)
- OTA: 3+3 NMOS on min_n/min_p (routing overlap)
- VCO: 2 PMOS on mbn2.G
- Netgen 148 merge count likely includes topology-based merges (not just parallel)

Session end: 62 commits, 81 full devices, 15 parallel merges, 0 merges, 0 wrong-bulk.

---

## ★ Session 4 Final Status (2026-03-18 20:30)

### ATK M3+M4+M5 Routing — Working but LVS=92/255

**Code changes (all committed):**
- pdk.py: M5/Via4/TopVia1/TM1 constants (IHP PDK values)
- maze_router.py: 3-layer (M3H+M4V+M5V), strict H/V block, last-mile bridge
- solver.py: power pad obstacles, seed parallel, disabled M1/M2 obstacles
- assemble_gds.py: route layer remapping (0→M3, 1→M4, 2→M5)

**Verified facts:**
- H/V discipline: 0 violations ✅
- Obstacle avoidance: 1 overlap (grid boundary) 
- Via stack: M2→Via2→M3→Via3→M4→Via4→M5 complete ✅
- Magic extraction: correctly extracts M3/M4/M5 (1730 .ext entries) ✅
- seed diversity: seed=0 routes 127, seed=1 routes 129, different net sets ✅
- LVS: 92/255 (bare=73, improvement +19)

**Unresolved:**
- 92 gap analysis: which nets connected, which didn't, why
- KLayout DRC not done
- 188-core sweep not done
- .mag generation is inline script, not reusable module

### Next session priorities
1. Analyze 92 breakdown (connected vs merged vs missing)
2. KLayout DRC
3. Formalize .mag generation as module
4. 188-core ECS sweep
