# analog-trial 模拟 IC 设计经验

## 项目信息

- **目标**: TTIHP 26a, 1×2 tile, 2 analog pins (€100)
- **Repo**: https://github.com/TechHU-GS/analog-trial
- **截止**: 2026-03-24
- **设计**: Level 0 PTAT+CTAT → Level 1 Bandgap → Level 2 VCO (梯度推进)
- **计划文件**: `plans/silly-booping-eich.md`

## macOS ARM64 模拟工具链搭建 (2026-02-28)

### 已装工具

| 工具 | 版本 | 位置 |
|------|------|------|
| ngspice | 45.2 | brew, macOS native |
| KLayout | 0.30.6 | brew, macOS native |
| gdstk | 1.0.0 | ~/pdk/venv/ (Python venv) |
| OpenVAF | 23.5.0 | ~/pdk/openvaf/bin/openvaf (Julia ARM64 binary) |
| IHP-Open-PDK | dev branch | ~/pdk/IHP-Open-PDK/ |
| IHP AnalogAcademy | master | ~/IHP-AnalogAcademy/ |

### 环境变量 (~/.zshrc)

```bash
export PDK_ROOT=$HOME/pdk/IHP-Open-PDK
export PDK=ihp-sg13g2
export KLAYOUT_PATH="$HOME/.klayout:$PDK_ROOT/$PDK/libs.tech/klayout"
```

### OSDI 编译经验（macOS ARM64 首次成功路径）

**问题**: openvaf 官方只有 Linux 二进制。macOS 不支持。

**解决方案**: Julia BinaryBuilder 有 ARM64 macOS 二进制

1. 下载: `https://github.com/JuliaBinaryWrappers/OpenVAF_jll.jl/releases/download/OpenVAF-v23.5.0+2/OpenVAF.v23.5.0.aarch64-apple-darwin.tar.gz`
2. 依赖: `brew install llvm@16` (openvaf 动态链接 libLLVM 16.0.6)
3. 运行: `DYLD_LIBRARY_PATH=/opt/homebrew/opt/llvm@16/lib ~/pdk/openvaf/bin/openvaf --version`

**编译 OSDI 的坑**: openvaf 内置 linker 在 macOS 上有 bug，报 `dyld_stub_binder` not found。
但 **编译阶段成功**，生成了 .o 文件。需要手动链接：

```bash
# openvaf 编译 (会失败在 link 阶段，但 .o 文件已生成)
DYLD_LIBRARY_PATH=/opt/homebrew/opt/llvm@16/lib openvaf -D__NGSPICE__ --target aarch64-apple-darwin -o output.osdi input.va

# 手动链接 .o → .osdi
SDK=$(xcrun --show-sdk-path)
ld -dylib -arch arm64 -platform_version macos 11.0 11.0 -syslibroot "$SDK" \
   -o psp103.osdi psp103.o psp103.o1 psp103.o2 psp103.o3 psp103.o4 -lSystem
```

每个 .va 文件会生成 5 个 .o 文件 (.o, .o1, .o2, .o3, .o4)，全部需要传给 ld。

**4 个 OSDI 文件**: psp103.osdi, psp103_nqs.osdi, r3_cmc.osdi, mosvar.osdi
**位置**: `$PDK_ROOT/$PDK/libs.tech/ngspice/osdi/`

### .spiceinit 坑

PDK 自带 `.spiceinit` 使用 `'$PDK_ROOT/$PDK/...'` 单引号包裹路径。
ngspice 的内部变量扩展在某些版本/平台下无法正确解析 shell 环境变量。

**解决**: 创建 `~/.spiceinit`，把路径硬编码为绝对路径（不用 $PDK_ROOT）：
```
osdi /Users/techhu/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/ngspice/osdi/psp103.osdi
```

### IHP SG13G2 器件使用注意

1. **MOSFET/HBT/Resistor 都是 .subckt，不是 .model** → 实例化必须用 `X` 前缀
   - 错: `Mn1 out in 0 0 sg13_lv_nmos ...`
   - 对: `XMn1 out in 0 0 sg13_lv_nmos ...`

2. **HBT npn13G2 端口顺序**: C B E S (collector, base, emitter, substrate)

3. **rppd 电阻端口**: plus, minus, bulk (3 端)

4. **Corner 库用法**: `.lib cornerMOSlv.lib mos_tt` (文件名 + section 名)
   - MOSFET: cornerMOSlv.lib (mos_tt/ss/ff/sf/fs)
   - HBT: cornerHBT.lib (hbt_typ/bcs/wcs)
   - Resistor: cornerRES.lib (res_typ/bcs/wcs)
   - Capacitor: cornerCAP.lib (cap_typ/bcs/wcs)

### 电路设计经验 (2026-02-28)

**L0 → L1-PTAT 进化**: 简单 PMOS 镜像 PTAT 有巨大假阳性风险。温度趋势对但机制错。
- 镜像 VDS 失配 217mV → V(R1) 是 ΔVBE 的 3 倍 → 电流不是真 PTAT
- 弱指标 (R² > 0.995, 单调性) 无法检测到这个问题
- **加 OTA 后**: V(R1)-ΔVBE 从 108mV 降到 1.9mV, PSRR 从 75% 降到 3%

**OTA 反馈极性**: PMOS 电流源 + 差分 HBT 对，正确极性是：
- v+ = net_c2 (Q2+R 那一支，有 emitter degeneration)
- v- = net_c1 (Q1 那一支)
- 当电流太大 → V(net_c2) 涨更快 → OTA 推高 PMOS gate → 减小电流 → 负反馈

**机制验证指标** (替代弱指标):
1. `|V(R1) - ΔVBE| < 5mV` — 验证环路锁定 ΔVBE 到电阻
2. `V(R1)/(VT·ln(N))` 变化 < ±10% — 验证真 PTAT
3. PSRR: VDD±10% 时输出变化 < 10%

**OTA sizing (IHP SG13G2, 1.8V)**:
- Input PMOS diff pair: W=4u L=2u
- NMOS mirror load: W=2u L=2u
- Stage 2 NMOS: W=8u L=2u (L=1u 增益不够)
- Bias PMOS: W=4u L=2u (mirror), W=8u L=2u (output)
- Miller cap: cap_cmim 10u×10u
- Bias current: 20µA

**ngspice "temperature limiting NaN" 警告**: 出现但不影响收敛（dynamic gmin stepping 自动解决）

**L1-BGR 设计 (2026-02-28)**:
- 在 L1-PTAT 基础上加 R_BGR + Q_BGR 堆叠: VREF = VBE + I_PTAT · R_BGR
- K = R_BGR/R1 = 5.9 时 TC 最小 (~7 ppm/°C)
- VREF ≈ 1.05V（不是传统 1.25V，因 npn13G2 VBE 较低）
- R_BGR: rppd w=0.5u l=76.7u (153.4 sq, ~39.9 kΩ)
- 器件清单: 4 PMOS (M1-M3,M5) + 3 HBT (Q1,Q2,Q_BGR) + 3 rppd (R1,R2,R_BGR) + OTA (9 MOSFET + 1 cap) = ~20 器件

**BGR 验证数据**:
- TT corner: TC=7.2 ppm/°C, VREF range=1.2mV, mechanism err=1.9mV
- 9-corner: 7/9 PASS (SS 角 segfault 是 ngspice bug, 不是电路问题)
- PSRR: 1.2% (VDD±10%), 12.9mV range
- 所有 converging corners TC < 25 ppm/°C

**ngspice SS corner segfault**: 4+ PMOS mirror legs 时 SS/WCS corner 偶发 segfault (exit 139)
- 3 legs 正常，4 legs 随机崩溃
- itl1=500 itl4=100 能修复部分情况
- 非电路问题，是 ngspice + IHP MOSFET 模型的 bug

### 验证数据 (smoke test, 27°C, TT corner)

| 器件 | 测试 | 结果 |
|------|------|------|
| sg13_lv_nmos/pmos | Inverter DC sweep | Vout: 1.2V↔0V ✅ |
| npn13G2 | Gummel curve | Ic=0.65mA @ VBE=0.85V ✅ |
| rppd (w=0.5u, l=5u) | DC resistance | 2679Ω (理论 ~2600Ω) ✅ |

### L2 PTAT+VCO 设计 (2026-03-01)

**定位转变**: 原目标是 PTAT 频率传感器 (f∝T)。实际发现 PTAT 电流增加被 MOSFET 迁移率退化精确抵消，VCO 频率温度无关 (±3%)。重新定位为：
- **ua[0]**: 54 MHz 温度补偿时钟（激励源 / FDR 介电测量）
- **ua[1]**: VPTAT 温度电压（0.34~0.41V，温度传感）
- **uo[0..N]**: 数字分频输出 6.6k/52.7k/422k Hz（Watermark 石膏块激励）

**电路拓扑 (v3)**:
- PTAT core: 简单 PMOS 镜像 (M1/M2 w=4u l=2u) + HBT 对 (Q1×1, Q2×8) + R_ptat (rppd 13u)
- NMOS bias: PMOS mirror leg (M3) → NMOS diode (w=2u l=1u) 转换 IPTAT 为 NMOS VGS
- VCO: 5-stage NMOS current-starved ring (bias w=1u l=4u, inv PMOS w=2u/NMOS w=1u l=0.5u)
- Buffer: 2 级 inverter (4u/2u → 8u/4u)
- VPTAT: PMOS mirror leg (M5) + R_out (rppd 5.5u b=2)
- **器件数**: ~28 个 (PTAT 6 + NMOS bias 2 + VPTAT 2 + VCO 15 + buffer 4)

**仿真文件**: `sim/test_ptat_vco_v3.sp` (基准), `sim/ptat_vco.sp` (完整版)

**迭代过程** (v1→v8):
- v1: Cascode mirror → VCO 不振 (cascode bias 建不起来)
- v1 简化: Simple mirror + PMOS current-starved → 407 MHz (太快)
- v1 调参: bias w=1u l=4u → 12.4 MHz (对了)
- v3: NMOS current-starved → **53.4 MHz，全温度可靠** ← 最终选择
- v4~v6: 加强 starving / 加 cap / 双侧 starving → 频率仍平，不改善
- v7: Cascode mirror → 启动失败 (无 OTA 时 cascode 建不起来)
- **结论**: 简单 mirror + NMOS starved ring = 温补时钟，不是 PTAT 频率

**前仿验证结果 (2026-03-01)**:

| 验证项 | 结果 | 备注 |
|--------|------|------|
| 温度扫描 (-40~125°C) | 53.7~56.6 MHz (±3%) | 6 点独立文件温扫 |
| 9-corner | **9/9 PASS** (49.3~59.2 MHz) | SS=49.6, FF=58.7 |
| 起振 (4 种 IC) | **4/4 PASS** | zero/high/mid/random |
| VDD ramp (0→1.8V) | 6.4µs 起振 | 真实上电 |
| 周期一致性 | jitter < 1% (4 连续周期) | 非瞬态假象 |
| 摆幅 | 1.89V pp (buffer 后) | 满摆幅 |
| 级间相位 | 交替正负，符合 5 级环特征 | |
| 对照实验 (bias=0) | **不振荡** (vco_out=1.8V) | 确认依赖 bias |
| VPTAT 耦合 | **0.15 mV pp** | VCO→VPTAT 噪声极小 |

**PTAT 机制诚实评估**:
- V(Rptat) = 260 mV >> ΔVBE = 54 mV → 简单镜像 VDS 失配主导，"假 PTAT"
- VPTAT 温度趋势正确 (单调递增 +20%)，但机制不纯
- 对"温补时钟"定位不影响——频率不依赖 PTAT 纯度
- 如需真 PTAT 频率 → 换弛张振荡器 (relaxation osc) + OTA-based cascode (留给 L3)

**追加验证 (2026-03-01)**:
| 验证项 | 结果 | 评价 |
|--------|------|------|
| VDD sweep (v3) | Δf/f=53% | ❌ FAIL — simple mirror 无 DC PSRR |
| Load boundary | ring 免疫, buffer 1-2pF 极限 | ❌ ua[0] 不可直接探测 |
| MC 50 runs (TT 27°C) | 100% 起振, f=54.3±2.5MHz, VPTAT=361±15mV | ✅ PASS |

**v4 改进 (RC 去耦, 2026-03-01)**:
- VDD → Riso(rppd ~520Ω) → VDD_VCO → PTAT+Ring, Cdec=20pF
- AC ripple: 200mVpp@50MHz → 58mVpp (衰减 -10.8dB)
- DC PSRR 不变（R 对直流透明），但 AC 开关噪声得到有效滤除
- Riso IR drop: ~80mV → VDD_VCO=1.72V, 频率从 54→47 MHz (可接受)
- 温度扫描: 47.2~49.6 MHz (Δf/f=5.1%), VPTAT=268~339mV
- Buffer 改为 global VDD 供电（数字侧，噪声不影响）
- 文件: `test_ptat_vco_v4.sp`

**Gate 结论 (诚实版)**:
- ✅ MC: 50/50 PASS, 无不起振风险
- ✅ Ring core 对负载/温度/corner: PASS
- ❌ Analog pad 输出: FAIL → 改为数字分频输出
- ⚠️ VDD 敏感性: DC PSRR 差 → RC 隔离 + 系统级 LDO 稳压

**v4 改动清单**:
1. VCO output → buffer → 数字分频器 → uo[] (不走 ua[0])
2. VDD → Riso + Cdec → VDD_VCO (RC 隔离)
3. ua[0] → VPTAT, ua[1] → VDD_VCO 监测 (or 空置)
4. spec 标注: freq vs VDD 曲线, 系统供电要求

**ngspice 温度循环 foreach 坑**:
- `foreach` + `set temp` + `destroy all` 有状态泄漏，结果不可靠
- **正确做法**: 每个温度写独立 .sp 文件 + `.temp N`，分别运行
- 或用 `reset` 但注意 meas 变量会被清除

### Phase 3: Tie 自动放置 (2026-03-01)

**算法**: Strip-based per-device — 每个 PMOS 上方 1 个 ntap，每个 NMOS 下方 1 个 ptap，X 对齐 source pin。

**结果**: 24 ties (11 ntap + 13 ptap), 6/6 Gate PASS
- LU.a: 2.6~3.7µm (limit 20µm), LU.b: 2.0~2.5µm
- nBuLay: 780~1120nm (< 2990nm)
- M1 conflict: 0 (MBn1 auto-shifted 64.45→64.14µm)

**关键经验**:

1. **s5() 单位陷阱**: `pdk.py` 的 `s5(val_um)` 接收 µm 再 ×1000 转 nm。tie_placer 内部全 nm 运算时若误调 `s5(nm_val)` 会放大 1000 倍。
   - 解决: 创建 `_snap5(nm)` 纯 nm 函数，tie_placer 内部不调 `s5()`。

2. **M1 冲突自动避让**: `_resolve_m1_clear_x()` — 1D 解析搜索，遍历所有非同网 M1 obstacle，对 Y 重叠的计算 shift_left 和 shift_right，取最小偏移方向。
   - 不能手动硬编码偏移值（"不要又手动坐标了"）
   - 必须对 ntap 和 ptap 都调用（即使当前只有 ptap 触发）

3. **Gate check 设计**: Check 6 从"tie 在 strip 内"改为"tie 在正确侧"（ntap cy > device cy, ptap cy < device cy），因为 tie Y 由 via 几何决定，不精确对齐 strip 预留。

**文件**: `atk/tie/tie_placer.py` (核心), `solve_ties.py` (入口), `ties.json` (输出)

### 版图 DRC 经验

**OffGrid 698→0 修复 (2026-03-01)**:
- 根因: `int()` 截断浮点 → 1nm 偏差 → 698 个 OffGrid.Cont/Via1/Metal1 violations
- 修复: `int((px - ox) * UM)` → `round(...)` + `((val+2)//5)*5` 5nm snap
- 教训: 5nm 制造网格下 1nm 差异 = 0 error vs 698 error
- `$$CONTEXT_INFO$$` cell 不是根因 (最初误判)

**CntB.h1 (28 markers)**: **PDK PCell 已知缺陷，waiver**。
  隔离测试确认：Nx=1 单独=4, Nx=8 单独=24, 两个一起=28, 我们版图=28（严格吻合）。
  根因: npn13G2 PCell 内部 ContBar M1 enclosure 0.04µm < 要求 0.05µm，差 0.01µm。
  我们的路由对 CntB.h1 零贡献。
**LU.a/LU.b (4+9)**: 缺 guard ring，走线阶段加

### 版图策略结论

- **造器件**: PDK PCell 负责 (DRC-clean by construction)，绝不用 gdstk 手搓多边形
- **摆器件**: Python 脚本算相对坐标，common-centroid 阵列是脚本优势场景
- **走线**: A* maze router + safe_vbar_m2 自动 underpass，无需 KLayout GUI
- **DRC 调试**: shapely spacing_check.py 秒级预检 → 有问题再跑 KLayout DRC 精确定位
- **M2 短路检测**: shapely `unary_union` → Polygon=短路, MultiPolygon=安全
- **可视化**: matplotlib 按 net 着色出图，不用开 KLayout GUI
- **原则**: 所有修改在脚本里，不在 GUI 里拖多边形，版图 100% 可复现

### TTIHP 模拟项目提交 (2026-02-28 确认)

**Tile 尺寸** (已验证，tile_sizes.yaml):
- 1×2 = **202.08 × 313.74 µm**（之前误用 213.6 是错的）
- 2×2 = 419.52 × 313.74 µm

**Analog pin 分配机制**:
- 芯片级 16 个 analog pad，TTIHP 26a 无模拟开关，专用连线
- 每项目最多 **6 个** analog pin (ua[0]~ua[5])，ua[6]/ua[7] 永远不连 pad
- `info.yaml` 的 `analog_pins: N` 表示 ua[0]~ua[N-1] 连到 pad，其余浮空
- pin 必须从 ua[0] 开始连续使用，不可跳号
- 分配由 shuttle organizer 在 `modules.yaml` 里就近手动设定

**Pin 物理位置** (来源: tt_um_adex_neuron_ncs LEF + tt_um_oscillating_bones LEF，实锤):
- **ua[0]~ua[7]**: tile 底部 (Y=0~2µm)，**TopMetal1** 层，1.75×2.0µm，间距 24.48µm
- **数字 pin**: tile 顶部 (Y=312.74~313.74)，**Metal4** 层
- **VDPWR/VGND**: tile 左侧竖条，TopMetal1 层
- **TopMetal2 禁止使用** (TT 电源网格)

| Pin | 中心 X (µm) | RECT (µm) |
|-----|-------------|-----------|
| ua[0] (VREF) | 191.04 | (190.165, 0) → (191.915, 2) |
| ua[1] (VPTAT) | 166.56 | (165.685, 0) → (167.435, 2) |
| ua[2] | 142.08 | (141.205, 0) → (142.955, 2) |
| ua[3] | 117.60 | (116.725, 0) → (118.475, 2) |
| ua[4] | 93.12 | (92.245, 0) → (93.995, 2) |
| ua[5] | 68.64 | (67.765, 0) → (69.515, 2) |
| VDPWR | 左侧竖条 | 1×2: (9.9, 0) → (12.1, 310); 2×2: (1.0, 5) → (3.4, 308) |
| VGND | 左侧竖条 | 1×2: (5.9, 0) → (8.1, 310); 2×2: (6.0, 5) → (8.4, 308) |

**提交流程** (custom_gds，模拟项目):
1. `gds.yaml` 用 `tt-gds-action/custom_gds@ttihp26a`（不是标准数字 action）
2. 需提供: `gds/<module>.gds` (或 .oas) + `lef/<module>.lef` + `src/project.v` (黑盒)
3. LEF 定义 pin 位置，precheck 验证 ua pin 在 GDS 中有对应 TopMetal1 金属
4. `project.v` 为空壳 `endmodule`，无内部逻辑

**参考项目** (TTIHP 26a 实锤):
- `tt_um_adex_neuron_ncs`: 2×2, 5 analog pins, `/tmp/tinytapeout-ihp-26a/projects/`
- `tt_um_oscillating_bones`: 1×2, 0 analog pins (但有完整 LEF 结构)

### 版图迭代经验 (2026-02-28, v9~v17)

**最佳版本: v15** — 80.2 × 78.6 µm, R1↔OTA=14µm, symmetry Δ=0

**关键发现**:
- R sandwich 是信号枢纽 (连 HBT + OTA + Q_BGR)，必须在 HBT 和 OTA 之间
- 右列高度匹配: R_sw(14.2) + R2(14.2) + Q_BGR(7.1) + gaps ≈ HBT(43.5)
- Q_BGR 必须靠近 R_BGR（v17 分离后 vref 路由爆到 70µm）
- PCell flatten 后标签泄漏 → 必须 clear+re-add
- HBT 不必居中（很多参考版图都不居中）

**器件尺寸** (PCell 实测):
- HBT npn13G2 Nx=1: 6.7 × 7.1 µm
- 5×5 CC array: 41.5 × 43.5 µm (pitch 8.7×9.1, gap=2)
- pmos w=4u l=2u ng=2: 5.7 × 3.8 µm
- nmos w=2u l=2u ng=1: 4.1 × 3.8 µm
- rppd w=0.5u l=13u b=0: 0.9 × 14.2 µm
- cmim 10×10: 11.2 × 11.2 µm
- 总器件面积: ~1826 µm²，tile 利用率 ~2.7%

### L2 PTAT+VCO 自动版图 (2026-03-01)

**执行入口**: `layout/run.sh` (唯一入口，不要直接跑 l2_autoplace.py)
**输出**: `/private/tmp/claude/ptat_vco.gds`

**双进程架构**:
1. `solve_placement.py` — venv Python (ortools CP-SAT) → `placement.json`
2. `l2_autoplace.py` — KLayout Python (pya) → GDS
3. `atk/verify/*` — venv Python (shapely/gdstk) → DRC pre-check

**ATK 工具箱**: `layout/atk/` — 完整文档见 `layout/atk/README.md`

```
atk/
├── pdk.py              — 层/DRC/路由常量 (单一真相源)
├── place/
│   └── constraint_placer.py  — CP-SAT 摆放器
├── route/
│   ├── maze_router.py  — A* 双层 maze router (350nm grid)
│   │     _reconnect_components: A* bridge (self-used clearance)
│   │     _mark_segments_used: bridge grid marking
│   │     _insert_junction_vias: M1↔M2 same-point via
│   ├── access.py       — Pin access 计算 (6 种模式, 纯数学)
│   ├── power.py        — M3 power rail + via drop + vbar jog + via_stack
│   ├── solver.py       — 路由编排器 (obstacle map + maze 调度)
│   │     _signal_escape_recheck: BFS pin trapping → soft demotion
│   │     _block_power_drops: M1 stub soft + M2 pad permanent
│   └── underpass.py    — ⚠️ DEPRECATED
├── gds/
│   └── gate_extras.py  — 共用 gate contact shape 生成 (assemble + audit 零漂移)
├── tie/
│   └── tie_placer.py   — Strip-based tie 自动放置
├── verify/
│   ├── routing_check.py    — 综合 DRC+短路+连通+对角线检查
│   │     check_routing: M1.b/M2.b/V1.b spacing
│   │     check_all_shorts: M1+M2 exhaustive (含 power+tie)
│   │     check_components: 信号网断线检测
│   │     check_diagonals: 非曼哈顿段检测
│   │     full_check: 一键全检
│   ├── connectivity_audit.py — UnionFind 链式连通性 (替代 mini_audit)
│   ├── coordinate_verify.py  — GDS 前坐标交叉验证
│   ├── placement_check.py    — 摆放 DRC (access pad overlap/spacing)
│   ├── route_diag.py         — 路由失败诊断 (BFS flood + obstacle frontier)
│   ├── pcell_xray.py         — device_lib.json → GateInfo
│   ├── spacing_check.py      — M1.b/M2.b/V1.b 预检 (<1s)
│   ├── short_check.py        — M2 短路检测 (<1s)
│   └── open_check.py         — 开路检测
├── viz/
│   ├── drc_debug.py      — DRC violation 叠加图
│   ├── placement_plot.py — 摆放结果可视化
│   └── layout_plot.py    — GDS matplotlib 渲染
└── tests/
    ├── test_pdk_rules.py  — PDK 常量回归测试
    └── test_regression.py — 回归测试
```

**三层金属架构** (2026-03-01 确立，根本性突破):
- M3: 电源轨 (horizontal, 3µm) — VDD_VCO, VDD, GND
- M2: 信号路由 (自由，无电源障碍)
- M1: 本地连接 (PCell 内部 + stub 到 via)
- Drop path: M3 → Via2 → M2 → Via1 → M1 → device pin

**效果对比**:
| | M2 电源 (旧) | M3 电源 (新) |
|---|---|---|
| 路由成功 | 2/17 nets | **17/17 nets** |
| DRC | 241 violations | **19 violations** |
| Underpass | 必须，复杂 | 不需要 |

**路由感知摆放**:
- PLACE_GAP_1T = 2×DEV_MARGIN + M2_SIG_W = 700nm (1 条信号线能通过)
- 在 pdk.py 定义为派生常量，solver 直接引用

**DRC 状态** (Phase 4 final): **全 PASS**
- M1.b=0, M2.b=0, V1.b=0, M2 shorts=0, all-layer shorts=0, connectivity=0, diagonals=0
- 全检: `routing_check.full_check()` 一键 7 项检查

**KLayout Python 环境**:
- `klayout -n sg13g2 -zz -r script.py` — 内置 Python，无 ortools/shapely
- 验证/可视化用 `~/pdk/venv/` Python + gdstk
- GDS 写入: `/private/tmp/claude/ptat_vco.gds` (sandbox safe)

**IHP DRC 运行**:
```bash
python3 ~/pdk/IHP-Open-PDK/.../drc/run_drc.py --path=<gds> --topcell=<name> --run_dir=<dir> --mp=1 --no_density
```

## atk/ 工具箱使用规则

- 修改走线 → 必跑 `short_check` + `spacing_check`，不可跳过
- 分析 DRC → 先用 `spacing_check` 定位坐标，再看 lyrdb
- 可视化 → `layout_plot.py` 出图
- 新增模块时更新 `atk/README.md`
- **不重构 working code** — 先跑通再整理到 atk/

## 关键教训

**M2 电源架构失败分析**: M2 horizontal rails 将版图切成条带，信号 M2 无法穿越，
M1 underpass 被器件 bbox 阻挡。根本矛盾: 电源和信号抢同一层。
解决: 电源升到 M3，M1+M2 完全归信号。

**路由感知摆放**: 摆放间距必须 ≥ 2×DEV_MARGIN + wire_width，
否则 router 虽有物理间距但被 obstacle margin 吃掉，有效通道为负。

**Pin escape**: 器件 bbox 是路由障碍，pin 在 bbox 内部。
必须从 pin 到 bbox 边缘清除 **M1+M2 双层**通道，否则 A* 起点被困死。

**S-D-S PCell 结构问题 (2026-03-02)**:
PMOS mirror 器件 S1-D-S2 布局，D pin 被 S1/S2 夹在中间，间距仅 440nm。
Power drop M2 vbar 从 S pin 向 M3 rail 延伸，加 510nm blocking half-width (M2_SIG_W/2 + M2_MIN_S + M2_SIG_W/2)，
完全封死 D pin 的 M2 escape。BFS 可达性证明: D pin 仅 7 个 free cell，NOT REACHABLE。
M2 jog 无效: jog 起点 X 仍在 S pin 位置，440nm < 510nm margin → 仍然封死。
**解决**: via_stack — Via1+Via2 在 raw pin 位置 → M3 vbar 到 rail，完全不走 M2。
适用条件: pin 附近有 M3 rail (power pin 天然满足)。

**Terminal margin 教训 (2026-03-02)**:
maze router `_mark_used` 原本对 terminal cell 用 margin=0，依赖"pin 之间物理间距足够"。
但 pin_terminals skip 机制 (margin expansion 跳过相邻 pin grid cell) 才是正确保护。
terminal margin=0 导致 diagonal neighbor 无 used-mark → vco2↔vco3 M2 wire 间距 71nm。
**修复**: ALL cells 用 margin=MAZE_MARGIN，pin_terminals skip 防止同器件 pin 互堵。

**Bridge 段不标 used 导致短路 (2026-03-02)**:
`_bridge_fragments()` 连接断裂的子路由片段，但产生的 bridge 段不在 router `used` set 里。
后续 net 的 A* 直接穿过 bridge 区域 → 3 个短路 (gnd↔ns5, ns5↔vco5, vco1↔vco5)。
**修复**: `_mark_segments_used()` — bridge 段转回 grid cell + margin 标记 used。

**_reconnect_components 替代 _bridge_fragments (2026-03-02)**:
直接 manhattan bridge 不检测碰撞 → 穿越其他 net 的 used/blocked 区域。
即使加碰撞检测 `_bridge_crosses_used()`，太多 bridge 被拒绝 → 8 个断线 net。
**解决**: `_reconnect_components()` — A* pathfinding 绕障碍连接断裂分量。
关键技巧: A* 前临时移除本 net 的 used cells (self-used clearance)，否则 A* 被自己的 margin 堵死。
迭代循环内必须调 `_insert_junction_vias()` 才能正确识别 M1↔M2 连通。

**Signal escape recheck (2026-03-02)**:
Power M1 stub + M2 pad permanent blocking 可能困住信号 pin (BFS 可达 < 20 cells)。
全部 demote → 1708 cells → 8 新短路。只 demote trapped pin 周围 RADIUS=3 → 252 cells → 0 短路。
**原则**: targeted demotion — 只在确认 trapped 时才降级 permanent→soft。

**Power M1 stub 必须 soft blocking (2026-03-02)**:
Permanent blocking 封死同器件信号 pin 的 M1 escape (尤其 D pin 夹在 S1/S2 之间)。
Soft blocking 允许 punch 机制在路由时清除信号 pin 周围的 soft block。

**DRC checker net mapping (2026-03-02)**:
access point 用 `_ap_M1.D` tag 而 route 用 `net_c1` → checker 误判为跨网违规。
**修复**: 从 routing.json 建 pin→net map，access point 用实际 net name tag。
同理 power drop pins 也要 map 到 net name。

**PCell DRC 教训**: CntB.h1 (28 markers) = PCell 内部缺陷，用隔离实验证实可 waiver。
**原则**: 不猜测，用隔离实验区分"PCell 内部"vs"路由侵入"。

**Tool Fixation**: 被困在 KLayout Region API 调试 M2 短路，shapely `unary_union` 一行解决。
**原则**: 遇到重复调试，先问"有没有更适合的库"。

### KLayout LVS 调试经验 (2026-03-02)

**LVS 命令**:
```bash
~/pdk/venv/bin/python3 ~/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/lvs/run_lvs.py \
  --layout=<GDS> --netlist=<CDL> --run_dir=<OUT> --topcell=<NAME> --allow_unmatched_ports
```

**关键发现**:

1. **`--allow_unmatched_ports` 必须加** — PDK 自带 regression runner (`run_regression.py`) 也用此 flag。不加连 PDK 参考 npn13G2 也 FAIL。

2. **BJT 原理图必须含 `le=` 和 `we=` 参数** — KLayout 提取出 AE/PE 值，需要 schematic 有对应参数才能匹配。
   - 错: `Q1 C B E sub! npn13G2 m=1`
   - 对: `Q1 C B E sub! npn13G2 le=900.0n we=70.00n m=1`
   - 来源: PDK 参考 `bjt_devices/netlist/npn13G2.cdl`

3. **根因: M2 路由断线，不是 KLayout 提取 bug** — 11+ 轮绕弯全因只查 M1 层。
   - M1 连通性 ✓ (UF audit 20/20)
   - Via1 存在 ✓ (b_pin→Cont→M1 chain PASS)
   - **M2 pad 是死端** — orphaned M2 pad 无 wire 连到目标 net
   - trace_b_path.py (shapely flood-fill) 一次性暴露 3 处断线

4. **`pre_routed_pins` 陷阱** — netlist.json 有 `"pre_routed_pins": [["Q1", "B"], ["Q2", "B"]]`，
   maze router 跳过这些 pin。但之前的 pre-route 逻辑被禁用（因 emitter 短路），结果 M2 pad 孤立。
   - 修复: `"pre_routed_pins": []`，让 maze router 正常路由 B pin

5. **最小可复现案例二分法** — 高效 debug 策略:
   - Step 1: PDK 参考 PASS (baseline)
   - Step 2: 单 PCell + routing → PASS (排除 PCell 问题)
   - Step 3: 两 PCell + 全 top-cell polygon → FAIL (定位 break point)
   - trace_b_path.py: M1→Via1→M2 flood-fill → 精确定位 M2 gap

**教训**:
- 验证脚本必须覆盖整条链路 (M1+Via1+M2)，不能假设某层没问题
- 最小可复现案例 + 二分法 >> 在复杂设计上猜测
- Python flood-fill (shapely) 一次性定位所有断点，比逐 pin 手动探测效率高 100×

**文件修改记录**:
- `ptat_vco_lvs.spice`: QQ1/QQ2 加 `le=900.0n we=70.00n`
- `netlist.json`: `pre_routed_pins` 从 `[["Q1","B"],["Q2","B"]]` 改为 `[]`
- 结果: Q1.B=net_c1 ✓, Q2.B=net_c2 ✓, 剩 M$34.S=$6 (MMbn2.S2→gnd 断线，同类问题)

6. **MMbn2.S2 power drop 遗漏** — power.py 只给 MBn2.S 建了 via_stack drop，漏了 S2。
   2-finger NMOS S1/S2 是独立 M1 island，各自需要独立 power drop。
   - 修复: power.py 加 `_make_via_stack_drop('gnd', 'MBn2', 'S2', ...)`

7. **2-finger NMOS 合并提取** — S1=S2=gnd 后 KLayout 把 ng=2 NMOS 合并为 1 个 W=4u。
   原理图从 2×W=2u (MMbn2a+MMbn2b) 改为 1×W=4u (MMbn2)。

8. **rppd serpentine 电阻 `ps` 参数** — 有弯曲 (b>0) 的 rppd 提取出 `ps=0.18u`，
   原理图必须加 `ps=0.18e-6` 才能匹配。无弯曲 (b=0) 的 ps=0 不需要。

**最终 LVS 结果**: ✅ "Congratulations! Netlists match" — 2 BJT, 24 MOS, 4 RES 全部匹配

### DRC 路由违规消除 (2026-03-03)

**起点**: 190 DRC violations (42 routing-related: 28 V1.a + 14 M2.c1)
**终点**: 139 violations = 137 PCell-internal (waiver) + 2 boundary + **0 routing**

**根因: Double Via1 creation** — AP (access point) 在精确 pin 位置画 Via1，route endpoint 在 maze-grid-snapped 位置再画一个 Via1，两个正方形偏移 ~100nm → 合并成 L 形 → 不再是 0.19µm 正方形 → V1.a FAIL → M2 endcap 不够 → M2.c1 FAIL。

**修复 1: Proximity-based Via1 dedup** (assemble_gds.py `draw_segments()`):
- `skip_threshold = VIA1_PAD // 2 = 240nm`
- 数学保证: grid 量化误差 < MAZE_GRID/2=175nm < VIA1_PAD/2=240nm → 所有重复 via 必被捕获，不误杀
- `_near_any(x, y, via_set, threshold)` — O(n) scan，n~80 可接受

**修复 2: Gate contact Via1 tracking** — gate strap (ng=2 m1_pin) 和 gate contact (ng=1 m1_pin) 在 section 1b/1c 也画 Via1，但 `drawn_vias` set 在 section 3 才创建 → 这些 Via1 未被 dedup 看到。
- 修复: `drawn_vias = set()` 移到 section 1b 之前，section 1b/1c 各加 `drawn_vias.add(...)`。
- 效果: 82 tracked (was 69), 14 deduped (was 8), V1.a=0, M2.c1=0

**修复 3 (REVERTED): pin_snap** — 尝试在 maze_router 中将 route endpoint snap 到精确 pin 位置。结果制造 OffGrid violations (端点不在 5nm 网格)。**教训: 在数据消费端容忍比在数据源端修改更安全**。

**教训**:
- Via1 dedup 必须覆盖 ALL 来源 (AP/gate strap/gate contact/route)，遗漏任一 = 残留违规
- 数学证明 threshold 有效性，不靠试错调参
- 优先在 consumer (GDS writer) 去重，不在 producer (router) 修改——producer 修改有连锁副作用

### 单一数据源违规修复 (2026-03-03)

**问题**: `solve_routing.py` 读 `layout/placement.json` (MBn at y=11.0, LVS-proven)，`assemble_gds.py` 的 `_find()` fallback 读到 `claude/placement.json` (MBn at y=41.7, 意外重跑产生)。30µm 偏移导致 6 个 route stub (路由终点在幽灵位置)。

**发现过程**: stub_audit.py 报告 6 条 route stub → 增强诊断发现 stub endpoint 坐标 ≠ device position → 追溯到两个文件 MBn Y 坐标不同。

**修复**:
- 创建 `atk/paths.py` — 集中所有 JSON 路径常量 (PLACEMENT_JSON, NETLIST_JSON, ROUTING_JSON, TIES_JSON 等)
- 更新所有脚本: solve_routing.py, solve_ties.py, solve_placement.py, assemble_gds.py, connectivity_audit.py → 统一从 paths.py import
- `claude/placement.json` 从 `layout/placement.json` 同步

**教训**:
- 任何有 fallback 的文件查找 (`_find()`) 都是隐患 — 两个目录有同名但不同内容的文件
- 诊断工具链的递进发现价值: parse_drc → classify_drc → stub_audit → SSOT violation
- **路径必须有唯一真相源 (paths.py)，不允许各脚本自己拼路径**

### stub_audit.py 诊断工具 (2026-03-03)

**位置**: `/private/tmp/claude/stub_audit.py`
**功能**: 收集所有 M1/M2/Via1 shape (routing + AP + gate_extras + ties + power drops)，建 per-net overlap graph，报告 degree-1 = stub, degree-0 = isolated。
**分类**: route stub (潜在 bug) vs structural stub (预期的 AP/gate/power pad)
**用法**: `cd layout && ~/pdk/venv/bin/python3 /private/tmp/claude/stub_audit.py`
**注意**: power drop 格式用 `via_x`/`via_y` 不是 `x_nm`/`y_nm`; `m2_vbar` 是 `[x, y1, x2, y2]`

### Post-Layout Simulation (2026-03-03 → 03-07 最终)

**工具**: KLayout-PEX (kpex) 0.3.9, 2.5D engine, C-only extraction
**安装**: `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org klayout-pex`
**运行**: `kpex --pdk ihp_sg13g2 --2.5D --gds ptat_vco.gds --cell ptat_vco --out_dir /private/tmp/claude/postlayout`
**输出**: `postlayout/ptat_vco__ptat_vco/ptat_vco_k25d_pex_netlist.spice` (113 parasitic C)

**kpex 输出需后处理** (`postlayout/fix_pex_netlist.py`):
1. Q/M/R → X 前缀 (IHP 器件都是 .subckt)
2. rppd 参数 l/ps 从 µm → meters (加 `e-6` 后缀), 补 `w=0.5e-6`
3. VSUBS 加入 .SUBCKT port list (衬底寄生电容引用)
4. Cext 行不动 (ngspice 原生 C 元件)
**⚠️ 必须显式传入正确的输入路径，默认路径可能指向旧 PEX 提取结果**

**初始后仿结果 (MNb L=4u, 原始版图)**:

| 温度 | 前仿 (MHz) | 后仿 (MHz) | 降幅 | VPTAT (V) |
|------|-----------|-----------|------|-----------|
| -40°C | 53.7 | 28.4 | -47% | 0.345 |
| 0°C | ~55 | 27.9 | -49% | 0.383 |
| 27°C | 55.5 | 27.8 | -50% | 0.389 |
| 85°C | ~56 | 28.4 | -49% | 0.440 |
| 125°C | 56.6 | 28.8 | -49% | 0.474 |

**频率修复: MNb L=4u → 2.5u (2026-03-07)**:

排查过程:
1. 版图拓扑优化 (buffer→VCO 旁): vco5 寄生 ↓31%, 但频率仅 ↑2% → 无效
2. 器件 W 修正 (probe 参数错): 必要的正确性修复, 但频率无变化 → 无效
3. **参数扫描** (sweep_mnb_l.sh, 7 值 × 3 温度): L=2.5u → **36 MHz @27°C** → 有效

根因: 电流饥饿型 VCO 频率 ∝ I_bias ∝ 1/L_MNb。寄生 C 只是叠加项。

**最终后仿结果 (MNb L=2.5u, BJT 设计, 2026-03-07) — 已废弃**:

| 温度 | 频率 (MHz) | VPTAT (V) | 状态 |
|------|-----------|-----------|------|
| -40°C | 35.2 | 0.351 | ✅ > 33 MHz |
| 0°C | 35.0 | 0.359 | ✅ > 33 MHz |
| 27°C | 35.2 | 0.375 | ✅ > 33 MHz |
| 85°C | 36.4 | 0.417 | ✅ > 33 MHz |
| 125°C | 37.6 | 0.453 | ✅ > 33 MHz |

**⚠️ 以上结果来自旧 BJT 设计。当前使用 CMOS Vittoz topology (no BJT)。**

**CMOS Vittoz 后仿结果 (2026-03-08, 158 parasitic C)**:

- 频率范围: 5.7–8.1 MHz (-40~125°C)，前仿 7.66–10.74 MHz，~25% degradation
- VPTAT ≈ 0.02V (异常低，前仿数百 mV，需调查)
- **注**: 逐温度精确值需重新跑仿真确认，以上范围来自上次运行的观测

**更新的文件 (MNb L 修改)**:
- `probe_pcells_v2.py` + `probe_pcells_p0.py` — nmos_bias L=2.5e-6
- `ptat_vco_lvs.spice` — MNb l=2.5u
- `sim/test_ptat_vco_v8.sp` — MNb l=2.5u
- `netlist.json` — vco_nb row 加 `"gap_um": 1.8` (MNb bbox 变短导致列间距不足)

**PEX 工具链陷阱汇总**:

| 陷阱 | 症状 | 修复 |
|------|------|------|
| fix_pex 读旧文件 | 频率不变 (旧器件参数) | 显式传入最新 kpex 输出路径 |
| port order 变化 | 不振荡 / 错误频率 | 每次 PEX 后 `grep -A1 .SUBCKT` 检查 |
| 改 L 后 bbox 变 | Phase 4 路由失败 | row_group 加 gap_um |
| device_lib 缺 classification | Phase 3 KeyError | 始终用 probe_pcells_v2.py |

**文件**: `postlayout/fix_pex_netlist.py`, `postlayout/test_postlayout.sp`, `postlayout/sweep_mnb_l.sh`

### ATK 通用化迁移 (2026-03-03)

**目标**: 换电路只改 JSON 不改 Python (device_lib.json + netlist.json 是唯一数据源)

**完成的三个 Phase**:

| Phase | 内容 | 状态 |
|-------|------|------|
| C | probe_pcells_v2.py: 自动提取 bbox_offset, pins, implant_bounds, gate_info, classification, pcell_name | ✅ 180 PASS |
| A | 消费者迁移: access.py, tie_placer.py, assemble_gds.py → device_lib.json | ✅ LVS PASS |
| B | power.py 参数化: rails + drops 从 netlist.json power_topology 读取 | ✅ LVS PASS |

**新文件**:
- `atk/device.py` — 统一 device_lib.json 加载器 (load_device_lib, get_device_info, get_device_pins_nm, get_nwell_tie_info, get_pcell_params, get_ng2_gate_data, is_mosfet)
- `probe_pcells_v2.py` — 增强 PCell 几何探测 (KLayout 脚本)

**已删除的硬编码** (~200 行):
- access.py: `_DEVICES` (70行) + `PIN_ACCESS` (40行) → device_lib.json + netlist.json pin_access
- tie_placer.py: `NTAP_CONFIG` + `NWELL_TIE_INFO` + `DEVICE_PINS_NM` + `MOSFET_TYPES` (30行) → device_lib.json + netlist.json tie_config
- assemble_gds.py: `DEVICES` dict (60行) + `NG2_GATE_DATA` (3行) → device_lib.json
- power.py: compute_power_rails/drops 硬编码实例名 (~80行) → netlist.json power_topology

**netlist.json 新增 constraints**:
- `pin_access`: per-device-type pin access mode (design choice)
- `tie_config`: PMOS tie src_pin + contact config (design choice)
- `hbt_extras`: M2 stub dx offset (design choice)
- `power_topology`: rails (anchors + offsets) + drops (inst/pin/strategy)

**关键发现/修复**:
1. IHP SG13G2 PCells 不放 MOS/resistor pin 文本标签 → 从 M1+GatPoly 几何推断
2. NMOS ng≥2 pin 命名: S/D/S2 (不是 S1/D/S2), PMOS ng≥2: S1/D/S2
3. `get_ng2_gate_data()` 必须过滤 MOSFET-only — resistor 有 GatPoly 但不是 gate, 误画 gate strap 造成 M1/Cont 短路
4. KLayout PCell params 是 TypeString (w='4u'), device_lib.json 存 float → `_format_pcell_params()` 转换
5. `m` multiplier 参数: 显式传 m=1 不影响 LVS (不是短路根因)

**数据分离原则**:
- device_lib.json = 自动生成几何 (Phase C probing output)
- netlist.json constraints = 人工设计选择 (pin_access, tie_config, power_topology)
- Python 只读不存

**残留 TODO**: verify/ 诊断工具 (identify_shape.py, trace_via.py, root_cause_table.py) 仍有旧 DEVICES/PIN_ACCESS 副本

### CMOS Vittoz VCO 重设计 (2026-03-08)

**背景**: 原 L2 电路用 HBT npn13G2 对做 PTAT core。重设计为全 CMOS Vittoz topology (no BJT)，目标减少复杂度。

**电路**: `sim/cmos_ptat_vco.sp`
- Vittoz PTAT: PM3/PM4 (w=0.5u L=100u) mirror + MN1(1x)/MN2(8x) + Rptat
- Dual current-starved 5-stage ring VCO (PMOS top + NMOS bottom)
- Buffer: 2-stage inverter
- VPTAT: PM5 mirror + Rout

**Tile fit resize (rppd → rhigh)**:
- 原 Rptat: `rppd w=0.5u l=769u b=12` → PCell 高 771.5µm > 314µm tile ❌
- 新 Rptat: `rhigh w=0.5u l=133u b=12` → PCell 高 135.5µm ✅
- R 匹配: 两者 R ≈ 5.14 MΩ (SPICE model leff=(b+1)*l + bend corrections)
- **mirror L=100u 必须保持** — L=10u 时 VDS 失配 (1.4V vs 0.01V) 导致频率从 9→60 MHz
- mirror PCell 宽 101.3µm < 202µm tile，可以放得下

**仿真结果 (rhigh resize)**:
- 9/9 corners PASS: 9.10–9.57 MHz (vs 原 rppd 9.31 MHz)
- DC 操作点完全一致: V(net_c1)=0.244V, V(nmos_bias)=0.260V
- 温度: 7.66–10.74 MHz (-40~125°C)

**IHP SPICE ng vs m 关键经验**:
- sg13_lv_pmos/nmos subcircuit: `ng` → PSP `nf` (number of fingers), `m` → PSP `mult`
- PSP model: per-finger width = **w/nf**, total current ∝ w×mult
- `w=2u ng=1 m=8` (1 finger 2µm wide × 8) ≠ `w=2u ng=8 m=1` (8 fingers each 0.25µm wide × 1)
- 正确等效: `w=16u ng=8 m=1` = `w=2u ng=1 m=8` (same per-finger width, same total)
- **SPICE 保持 ng=1 m=8，Layout PCell 用 ng=8** — LVS 工具处理映射
- 错误使用 `ng=8 m=1` (不改 w) 导致电流 1/8，VCO 不振荡

**rhigh model 参数**:
- rsh = 1360 Ω/sq (typ), tc1 = -2300 ppm/°C, xw = -0.04µm
- rppd: rsh = 260 Ω/sq, tc1 = +170 ppm/°C, xw = +0.006µm
- rhigh TC 负 → PTAT 电流温度系数更大 (VT↑ + R↓ = 双重 PTAT)

**文件更新**:
- `sim/cmos_ptat_vco.sp` — rhigh 替换, mirror L 保持 100u
- `layout/probe_pcells_v2.py` — rhigh_ptat 设备, rhigh PCell 支持
- `layout/netlist.json` — Rptat type→rhigh_ptat, pin_access 更新
- `layout/atk/data/device_lib.json` — 15 设备 (含 rhigh_ptat 9.1×135.5µm)
- `layout/verify_netlist_vs_spice.py` — SPICE↔netlist 连通性验证 (PASS)

### DRC 0 markers 达成 (2026-03-08)

**起点**: 26 markers (M1.b=3, Gat.d=4, Cnt.f=2, Cnt.g1=3, Cnt.g2=3, pSD.e=3, LU.a=8)
**终点**: 0 markers, LVS PASS

**修复清单**:

| 修复 | 文件 | 消除的规则 | 根因 |
|------|------|-----------|------|
| Gate contact M1 pad 纳入 fill checker | `assemble_gds.py` | M1.b (3) | gate contact M1 pad 不在 `_fill_via_m1_corners` 的检查范围内，与同网路由线产生 notch |
| GatPoly extension cap (前session) | `assemble_gds.py` | LVS short | pmos_mirror L=100µm → `finger_hws[0]=50000nm`，画了 100µm GatPoly bar 桥接不同网 |
| Tie vs 邻居 GatPoly/pSD 障碍 clamp | `tie_placer.py` | Gat.d(4), Cnt.f(2), Cnt.g1(3), Cnt.g2(3), pSD.e(3), pSD.d1(3) | ntap tie 放在 PMOS 之间的 tie strip 时，靠近上方设备的 GatPoly/pSD 边界 |
| LU.a 多 tie (每 20µm + pin exclusion) | `tie_placer.py` | LU.a(8) | pmos_mirror 100µm 长只有 1 个 tie，>80% Activ 超出 20µm 限制 |

**关键技术细节**:

1. **`_fill_via_m1_corners` 扩展**: 新增 `gate_cont_m1` 参数，section 1c 画 gate contact 时收集 M1 rect，传给 fill checker 纳入同网 notch 检测
2. **`_clamp_act_cy_for_clearance`**: 检查 ALL 设备（不只自身）的 GatPoly + pSD 障碍，约束 tie center Y。包含 Gat.d(70nm) + Cnt.f(110nm) + pSD.d1(30nm) + Cnt.g1(90nm) 四个 DRC rule
3. **`_compute_lu_extra_ties`**: 沿 100µm 设备每 20µm 放一个 1x2 ntap tie，同 Y 不同 X。pin exclusion zone (390nm) 防止 tie M1 与 access point m1_stub 冲突。M1 bus bar 连接所有 tie 到 primary tie 的 vdd

**教训**:
- 第一版 pSD 修复方向错（检查自身设备的 pSD 而非邻居），浪费一轮。根因：没确认 tie 相对于设备的空间关系就动手
- obstacle-based 方法（检查所有设备）比 per-device 计算更可靠，代码量稍大但不容易遗漏
