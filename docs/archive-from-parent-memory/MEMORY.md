# GS_IC 项目记忆

## 项目概况

GS_IC = Ground Station IC，自研 ASIC 项目，服务于农业 IoT 土壤监测系统。
目标：TinyTapeout IHP SG13G2 130nm 流片。仓库：`/Users/techhu/Code/GS_IC`，设计在 `designs/` 子目录。
系统架构：ESP32-S3 HUB + LoRa 通信 + 土壤传感器前端 IC + Watermark/FDR 探针。

## 设计

### LoRaLite Protocol Processor (`designs/tt_loralite`)
- **功能**: LoraLite v0.6 协议处理器 IC，硬件加速 CRC16/帧解析/帧构建/ACK 位图
- **详细记录**: → `memory/loralite_ic.md`

### LoRa Edge SoC (`designs/lora_edge_soc`)
- **目标**: TTIHP 26a (IHP SG13G2 130nm), 截止 2026-03-24
- **架构**: Fork tt10-tinyQV (RV32EC @ 25MHz) + 8 自定义外设 (CRC16/I2C/WDT/Seal/RTC/Timer/SysInfo/latch_mem)
- **GDS**: 0 DRC, 0 timing vio, 0 antenna vio, 65.99% utilization, 854.4×313.74μm
- **状态**: ✅ **已提交 TTIHP 26a** (2026-02-28), revision 可在截止前更新
- **提交 repo**: https://github.com/TechHU-GS/tt_rv32_trial (独立于 GS_IC 主仓库)
- **购买**: 2x PCB kit + 8 tiles = €800, 预计 2026-09 收到 2 颗芯片
- **验证进度** (2026-02-26):
  - 仿真: 14 CI TBs, **619 PASS / 0 FAIL** (80 GROUP bus-level + 12 固件驱动)
  - GLS: **P0-A 5/5 + P0-B 10/10 PASS** (post-route netlist, IHP sg13g2 cells)
  - 形式: **19 条 k-induction** (seal 6, wdt 3, CRC arb 10), Z3 prove 全 PASS
  - 突变: **6/6 检出** (含 2 个历史致命 bug 回归锁定)
  - 覆盖: 8 模块量化 (crc16/wdt/rtc/latch_mem 100%, seal 76%, project 81.8%)
  - CI: **18 步** (timescale + lint + synth×7 + 15 sim)
- **RTL 修复**: read_n→read_complete (I2C/Seal), latch_mem cycle reset, SDA 2FF 同步器
- **关键测试**: tb_project 80 GROUP 268 check, tb_read_clear_regression 18 PASS
- **I2C 经验**: Forencich i2c_master AXI Stream 协议，bridge 须 latch valid 直到 ready
- **待做**: FPGA 验证 (Alchitry Cu V2 板到后), ESP32-S3 主板 PCB 设计
- **验证方法论**: → `docs/verification.md`
- **详细验证知识**: → `memory/lora_edge_soc_verification.md`
- **设计计划**: → `plans/glimmering-jingling-meteor.md`
- **CI**: test.yaml (18 步) + gds.yaml (tt-gds-action@ttihp26a, ihp-sg13g2)
- **GDS 最优配置**: SYNTH_STRATEGY "AREA 0", PL_TARGET_DENSITY_PCT 66.5, GRT_ANTENNA_ITERS 1, GRT_ANTENNA_MARGIN 15
- **GDS 利用率**: 93.1% total (含 fill), 实际逻辑 ~66.1%, 4x2 tile 足够但偏紧
- **GDS 参数调优记录**: → `memory/gds_parameter_tuning.md`
- **GDS 存档**: `output/runs/run{N}/` — 本地用 `scripts/archive_gds_run.sh` 从服务器拉回
- **模块散点图**: `scripts/plot_module_scatter.py` — 双面板 (散点+凸包边界), 基于网表的 cell→module 映射

### Analog Trial (`analog-trial`) — SoilZ v1 土壤传感器前端 IC
- **定位**: SoilZ v1 — 单芯片土壤水分/水势双模传感器前端 (1-bit IQ lock-in ΣΔ 阻抗分析仪)
- **演进**: L0 PTAT → L1 BGR → L2 VCO (30 devices, Phase 0-7 DONE) → **SoilZ v1 (249 devices, 当前)**
- **目标**: TTIHP 26a, 1×2 tile (202.08 × 313.74 µm), 2 analog pins, 截止 **2026-03-24**
- **Repo**: https://github.com/TechHU-GS/analog-trial
- **工作目录**: `/Users/techhu/Code/GS_IC/designs/analog-trial/` (已从 /private/tmp/ 迁回)
- **电路**: CMOS Vittoz (no BJT), 249 devices, 133 nets, 5-island floorplan
- **前仿**: 9/9 corner PASS (9.10–9.57 MHz)
- **版图**: v3.3b, 133/133 routing (M1-M4 四层)
- **DRC**: ⚠️ **7** (M2.b=1, NW.b1=4, M3.b=2), maximal=0, 全 placement-constrained
- **LVS**: devices match, merged nets=0, **net topology ❌ ~54 fragmented nets (BLOCKER)**
- **后仿**: 不可信 (LVS 未 clean)
- **主矛盾**: root-aware connectivity — 后处理到上限，需 router/power topology 层面修改
- **详细状态**: → `designs/analog-trial/` 项目自有 memory (MEMORY.md)
- **关键经验**: → `memory/analog_trial.md`, `memory/issue155_lesson.md`, `memory/rout_eco_lesson.md`

### LoRa Baseband (`designs/lora_baseband`)
- **状态**: 概念阶段，等 FPGA 板到后开始
- **目标**: 替代 SX1268，Level 4 ~80K gates → Level 5 ~200K gates
- **FPGA**: Alchitry Cu V2 (iCE40HX8K) 已购 + ECP5-85K 待购

## 服务器

- **地址**: `root@100.64.0.4` (pve-ubuntu, Tailscale)
- **Docker**: Docker 29.1.2, LibreLane 3.0.0.dev44 镜像 (`ghcr.io/librelane/librelane:3.0.0.dev44`)
- **工作目录**: `/root/GS_IC/designs/lora_edge_soc/`
- **tt-support-tools**: `/root/GS_IC/designs/lora_edge_soc/tt/` (clone from GitHub)
- **Python**: python3.11 (symlinked to `/usr/local/bin/python`)
- **同步**: 从 macOS rsync 到服务器，`tt_tool.py --harden --ihp` 跑 LibreLane

## 工具链

| 工具 | 版本 | 用途 | 运行环境 |
|------|------|------|----------|
| Yosys | 0.62 | RTL 综合 + 门数报告 | macOS (brew) |
| Verilator | 5.044 | C++ 协同仿真 | macOS (brew) |
| Icarus Verilog | - | Verilog TB 仿真 | macOS |
| cocotb | - | Python 随机化测试 | macOS |
| LibreLane | 3.0.0.dev44 | RTL→GDSII 物理实现 | 服务器 Docker |
| ngspice | 45.2 | SPICE 模拟仿真 (IHP OSDI) | macOS (brew) |
| KLayout | 0.30.6 | 版图+DRC+LVS | macOS (brew) |
| OpenVAF | 23.5.0 | Verilog-A→OSDI 编译 | macOS (Julia ARM64 binary) |
| gdstk | 1.0.0 | Python GDS 读写 | macOS (~/pdk/venv/) |
| shapely | 2.1.2 | 几何验证 (M2 短路/间距) | macOS (~/pdk/venv/) |
| matplotlib | 3.10.8 | 版图可视化 debug | macOS (~/pdk/venv/) |
| networkx | 3.6.1 | 网表连通性检查 | macOS (~/pdk/venv/) |

## FPGA 硬件 (已购/待购)

| 板子 | 芯片 | LUT | 价格 | 状态 |
|------|------|-----|------|------|
| Alchitry Cu V2 | iCE40HX8K | 7,680 | NZD $93 | 已购 (DigiKey) |
| Alchitry IO V2 | - | - | NZD $50 | 已购 (IO 扩展板) |
| Alchitry BR V2 | - | - | NZD $45 | 已购 (Breakout 板) |
| ECP5-85K EVN | ECP5-85K | 85,000 | ~NZD $400 | 待购 (LoRa 基带用) |

## 工作纪律

### 对外提交审核 (HARD RULE — issue #155 血的教训)
- **AI 起草的对外内容（issue/PR/comment/邮件）必须由用户逐句审核后才能提交**
- **每个事实断言必须附带实际执行的命令和输出，不能编造"验证结果"**
- **DRC/LVS 归因必须有隔离实验证明，不能推测**
- **语气匹配经验水平：新手用请教语气，不用断言式**
- **不确定的结论用 "likely"/"possibly"，不用 "confirmed"/"definitely"**
- **引用外部 issue 前必须确认其当前状态（是否已修复）**
- **详细记录 → `memory/issue155_lesson.md`**

### 禁止打地鼠 (HARD RULE)
- **如果诊断工具报告 N 个问题，下一步永远是改进诊断工具的输出精度，不是手动调查问题 #1**
- **判断标准**: 如果下一个 tool call 是"读某个坐标附近的 shape"或"检查某个 pin 的连通性"，那就是打地鼠。应该把这个查询写进诊断脚本，让它对所有 N 个问题一次性跑完
- **Python 做内循环，LLM 只做不可替代的 insight**（架构决策、新算法设计、异常模式识别）
- **LLM 不当循环执行器**: 坐标计算、shape 探测、连通性追踪 → 全部是 Python 脚本的活
- **教训来源**: 11 轮 LVS 调试，~70% token 花在机械性几何推算上。根因：用 LLM 手动逐 pin 探测 M1/M2/Via1，而这些全部可以用 30 行 Python 一次性完成

## 关键经验

### Verilator TX 捕获陷阱
- **问题**: `spi_write(CTRL, 0x02)` 触发 TX，但 SPI 写需 ~800 时钟周期，TX builder 在 SPI 事务期间就输出前 4 字节 (DeviceID)
- **症状**: `capture_tx_frame()` 在 SPI 完成后才开始 → 丢失前 4 字节
- **修复**: SPI 写和 TX 捕获必须内联同时进行，每个 SPI half-cycle 检查 tx_valid
- **教训**: 硬件并行执行，软件串行思维会漏掉时序重叠

### LibreLane vs OpenLane
- **OpenLane v1**: 旧版，GS_IC 仓库曾用过，已清理
- **LibreLane v3**: OpenLane 2 继任者，CI 用 `ghcr.io/librelane/librelane:3.0.0.dev44`
- **TTIHP CI 流程**: `tt_tool.py --create-user-config --ihp` (合并 config) → `tt_tool.py --harden --ihp` (跑 LibreLane)
- **Config 合并链**: `src/config.json` (用户) → `src/user_config.json` (tt_tool 自动生成, 含 die area/pin/PDK) → `src/config_merged.json` → LibreLane `resolved.json`
- **RT_MAX_LAYER 注意**: config.json 写 Metal5，但 user_config.json 自动覆盖为 TopMetal1

### TinyQV Bit-Serial Read Bug (CRITICAL — 2026-02-26)
- **问题**: TinyQV 是 4-bit 串行 CPU，32-bit MMIO 读需 8 个时钟周期。`read_n != 2'b11` 在整个 8 周期内都有效。如果用 `data_rd = (read_n != 2'b11)` 触发清除标志位（如 rx_has_data），标志在第 1 周期被清，CPU 在第 3 周期读高位 nibble 时看到旧值 0。
- **症状**: I2C `i2c_wait_rx()` 永远看不到 RX_VALID (bit[10]=0)，固件超时。
- **修复**: 所有 read-side-effect 必须用 `read_complete`（8 周期结束后的单脉冲），不能用 `read_n`。
- **RULE A**: 清除标志/弹出FIFO/推进指针 → 必须 `read_complete`
- **RULE B**: `data_out` 必须在整个 multi-cycle 读期间保持稳定
- **已修复位置**: `i2c_data_rd`, `seal_data_rd` (project.v); 已有正确模式: `uart_rx_read`
- **回归测试**: `tb_read_clear_regression.v` (18/18 PASS) — 验证 I2C + Seal 稳定性
- **教训**: 单元测试 (tb_i2c.v) 用单周期 `data_rd` 脉冲，无法复现此 bug。只有集成测试（CPU 真实驱动 read_n）才能发现。

### TTIHP GDS CI 调试经验 (2026-02-26)
- **DPL-0036 (placement failure)**: 根因是缺少 `SYNTH_STRATEGY: "AREA 0"`，综合出太多 cell 导致 hold buffer 无空间
- **解决**: 完全对齐 MichaelBell 的已验证 TTIHP 配置模板
- **关键参数**: `SYNTH_STRATEGY: "AREA 0"`, default hold margins (0.1/0.05), `EXTRA_EXCLUDED_CELLS: ["sg13g2_sdfbbp_1"]`
- **教训**: IHP PDK 配置不要自己摸索，找已通过的参考项目直接对齐

### RTL 验证四维方法论 (LoRa Edge SoC 总结)
- **仿真**: 4 层 (单元→总线级→集成→固件驱动), iverilog + 行为模型
- **形式**: SymbiYosys + Z3, 用于安全性质 (不可逆/单调/互斥)
- **突变**: 手动注入 → 编译 → 跑 TB → 必须 FAIL → 恢复, 重点锁定历史 bug
- **覆盖**: Verilator --coverage, 单模块 C++ 驱动 + 全 SoC POST 固件
- **详细**: → `docs/verification.md`, `memory/lora_edge_soc_verification.md`

### IHP GLS iverilog 兼容性 (2026-02-26)
- **问题**: IHP sg13g2_stdcell.v 的 DFF/latch 模型用 `$setuphold` specify block 驱动 `delayed_CLK`/`delayed_D` 信号。iverilog 不支持 delayed signal 功能，导致所有 DFF 输出永远为 x，仿真完全无法工作。
- **症状**: GLS 仿真 0 UART bytes, CPU 死机, 全 FAIL
- **修复**: `sed` 全局替换 `delayed_CLK→CLK`, `delayed_D→D`, `delayed_RESET_B→RESET_B`, `delayed_SET_B→SET_B`, `delayed_GATE→GATE`, `delayed_GATE_N→GATE_N`, `delayed_SCD→SCD`, `delayed_SCE→SCE`
- **文件**: `verify/pdk/sg13g2_stdcell_nodelay.v` (patched 版本)
- **结果**: GLS P0-A (5/5 PASS) + P0-B (10/10 PASS)，综合+PnR 无功能错误

### LibreLane 3.0.0.dev44 确定性 (2026-02-27)
- GRT_ANTENNA_ITERS=1 时完全确定性（Run 2=Run 3, Run 10=Run 13）
- ITERS≥2 引入非确定性（GRT 内部随机 rip-up-and-reroute）
- 同一 config 不同 ITERS 值不影响 placement，只影响 routing 和 antenna repair

### Rout ECO: polyres_drw 穿越 MOSFET (2026-03-13)
- **根因**: rppd PCell 的 polyres_drw 弯折线物理穿过 PM3/PM4，PDK LVS `.not_interacting(res_mk)` 排除 S/D
- **错误路径**: flatten + clip salblock → 破坏 rppd 提取 + polyres 仍阻塞
- **正确修法**: 局部 placement ECO (Rout x=36.32→10.0)
- **详细**: → `memory/rout_eco_lesson.md`

### 文件管理
- **output/ gitignore 策略**: 大二进制 (GDS/SPEF/SDF/MAG/ODB/DEF) gitignore，小文件 (metrics/LEF/LIB/netlist/SDC/SPICE) 进 git
- **cocotb/verilator 构建产物**: `sim_build/`, `obj_dir/`, `__pycache__/`, `results.xml` 全部 gitignore
