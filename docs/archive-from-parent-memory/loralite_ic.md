# LoRaLite Protocol Processor IC

## 设计概况

- **路径**: `designs/tt_loralite/`
- **目标**: TinyTapeout 4-Tile, Sky130 130nm
- **功能**: LoraLite 协议硬件加速 — CRC16 Modbus、帧解析/构建、ACK 位图、SPI 从机
- **协议版本**: v0.6 (IC 内部), 与 ESP32 固件 `loralite_protocol.hpp` bit-exact 兼容
- **时钟**: 50MHz (20ns period), SPI 1MHz

## RTL 模块 (14 个)

| 模块 | 文件 | 功能 | 面积占比 |
|------|------|------|----------|
| tt_loralite_top | tt_loralite_top.v | 顶层 TinyTapeout wrapper | - |
| loralite_core | loralite_core.v | 核心互连 | - |
| spi_slave | spi_slave.v | SPI 从机顶层 | - |
| spi_sync | spi_sync.v | SPI 跨时钟域同步 | - |
| spi_ctrl | spi_ctrl.v | SPI 控制 FSM | - |
| spi_shift | spi_shift.v | SPI 移位寄存器 | - |
| spi_regs | spi_regs.v | SPI 寄存器桥接 | - |
| reg_file_lite | reg_file_lite.v | 寄存器文件 (32B) | ~23% |
| sync_fifo | sync_fifo.v | 同步 FIFO (×2 实例) | ~23% |
| frame_parser | frame_parser.v | RX 帧解析 FSM | ~20% |
| frame_builder | frame_builder.v | TX 帧构建 FSM | ~10% |
| ack_processor | ack_processor.v | ACK 位图匹配 | ~15% |
| crc16_engine | crc16_engine.v | CRC16-Modbus 引擎 | - |
| seq_manager | seq_manager.v | 序列号管理 | - |

**总代码量**: ~2061 行 Verilog

## TinyTapeout 信号映射

```
ui_in[0]=SCK, [1]=CSN, [2]=MOSI, [3]=rx_valid, [4]=rx_sof, [5]=rx_abort, [6]=loopback_en
uo_out[0]=MISO, [1]=tx_valid, [2]=tx_done, [3]=irq_n
uio_in = rx_data[7:0]
uio_out = tx_data[7:0]
```

## SPI 寄存器映射

| 地址 | 名称 | 功能 |
|------|------|------|
| 0x00 | CTRL | 控制 (bit0=soft_rst, bit1=tx_start) |
| 0x01 | STATUS | 状态 (bit0=irq, bit1=tx_done, bit2=tx_busy, bit3=rx_busy, bit4=rx_valid, bit5=addr_filtered, bit6=frame_oversized) |
| 0x02 | IRQ_FLAGS | 中断标志 (W1C: bit1=CRC_ERR, bit3=TX_DONE, bit4=RX_DONE, bit5=ACK_MATCH) |
| 0x03 | IRQ_ENABLE | 中断使能 |
| 0x04-0x07 | DEV_ID[3:0] | 设备 ID (大端) |
| 0x08 | TX_MSG_TYPE | TX 消息类型 |
| 0x09-0x0A | TX_SEQ | TX 序列号 |
| 0x0B | TX_PLEN | TX 载荷长度 |
| 0x0C | TX_FIFO | TX FIFO (写) |
| 0x10 | RX_FIFO | RX FIFO (读) |
| 0x11 | RX_FIFO_CNT | RX FIFO 计数 |
| 0x14-0x17 | RX_DEV_ID | RX 解析设备 ID |
| 0x18 | RX_MSG_TYPE | RX 解析消息类型 |
| 0x19-0x1A | RX_SEQ | RX 解析序列号 |
| 0x1B | RX_PLEN | RX 解析载荷长度 |
| 0x70 | CRC_DATA | CRC standalone 数据输入 (写) |
| 0x71 | CRC_INIT | CRC standalone 复位 (写) |
| 0x72-0x73 | CRC_RESULT | CRC standalone 结果 (读, H/L) |
| 0x7E | CHIP_ID | 固定 'L' (0x4C) |
| 0x7F | VERSION | 固定 0x30 |

## 验证状态 (全部完成)

### 1. Verilog Testbench (iverilog)
- **13 个 TB + 4 个 edge-case TB = 17 个 TB**
- **256 PASS, 0 FAIL**
- 覆盖: SPI 读写、CRC16、帧解析/构建、ACK 位图、FIFO、loopback、中断、复位

### 2. cocotb 随机化测试
- **19 个测试, ~940+ 测试点, ALL PASS**
- 测试类型: CRC 随机验证、TX 随机帧、loopback、ACK 位图扫描、SPI 寄存器遍历
- Python 帧构建器与 IC CRC 交叉验证
- 文件: `tb/cocotb/test_loralite.py`, helpers: `spi_master.py`, `frame_gen.py`, `reg_map.py`

### 3. Verilator C++ 协同仿真
- **958 PASS, 0 FAIL**
- **核心价值**: 调用 ESP32 真实固件代码 (`loralite_protocol.hpp`) vs Verilog RTL
- 5 组测试:
  - CRC crosscheck: 100 帧 C++ build_frame → 注入 → IC 验证
  - CRC standalone: 50 序列 C++ crc16_modbus vs IC CRC 引擎
  - TX capture: 20 帧 TX → C++ parse_frame 验证 bit-exact
  - Loopback: 10 帧 round-trip 验证
  - ACK bitmap: 64 位扫描 + C++ is_seq_acked 对照
- 文件: `tb/verilator/sim_main.cpp`, `spi_driver.hpp`, `frame_inject.hpp`
- 固件头文件: `/Users/techhu/Code/HUB_Rev1/include/esplte4iot/core/pure/loralite_protocol.hpp`

### 4. Gate-Level Simulation (GLS) — Sky130 网表验证
- **手写 GLS TB**: 4 测试, 30 PASS — SPI R/W, CRC16 standalone, RX 帧解析, Loopback
- **cocotb GLS**: 19 测试, ~940+ 测试点, **19 PASS, 0 FAIL**
- 在 23,029 个 Sky130 标准单元的门级网表上运行 cocotb 全套随机化测试
- Docker: `ghcr.io/librelane/librelane:2.4.13` (iverilog 12.0 + sky130 cells)
- 编译参数: `-DFUNCTIONAL -DUNIT_DELAY="#1"` (功能仿真, 1ps 单位延迟)
- 仿真速度: ~88K ns/s (比 RTL 慢约 10x, 但全部通过)
- 文件: `tb/gls/gls_tb.v`, `tb/gls/Makefile.cocotb_gls`, `tb/gls/run_cocotb_gls.sh`

### 验证总结
| 方法 | 测试点 | 状态 |
|------|--------|------|
| Verilog TB | 256 | ALL PASS |
| cocotb (RTL) | 940+ | ALL PASS |
| Verilator C++ | 958 | ALL PASS |
| GLS 手写 TB | 30 | ALL PASS |
| GLS cocotb | 940+ | ALL PASS |
| **总计** | **~3120+** | **ALL PASS** |

## Yosys 综合结果

### iCE40 目标
- **1929 LUT4, 1678 FF**
- 占 iCE40HX8K (7680 LUT) 的 25%，余量充足

### Generic 门级
- **5782 cells** (technology-independent)

### 脚本
- `tb/yosys/synth_ice40.ys` — iCE40 目标综合
- `tb/yosys/synth_generic.ys` — 通用门级综合
- `tb/yosys/Makefile` — `make ice40` / `make generic`

## LibreLane 物理实现结果 (2026-02-24)

### 运行信息
- **工具**: LibreLane 2.4.13 (Docker on pve-ubuntu)
- **PDK**: Sky130
- **运行时间**: ~7 分钟, 78 步
- **配置**: `config.json` — CLOCK_PERIOD=20.0, FP_CORE_UTIL=40

### 核心指标
| 指标 | 值 |
|------|-----|
| Standard Cells | 14,946 (含 fill/tap) |
| Sequential (FF) | 1,670 |
| Combinational | 3,674 |
| Clock Buffers | 207 buf + 134 inv |
| Cell Area | 101,132 um² |
| Die Size | 456 × 467 um |
| Core Utilization | 51.2% |
| Power | 7.6 mW @ nom (5.5 internal + 2.2 switching) |
| Routing | 5,742 nets, 241,922 um wirelength |

### Timing (全 PVT corner 零违例)
| Corner | Setup Slack | Hold Slack | Violations |
|--------|-------------|------------|------------|
| TT 25°C 1.8V | +8.87 ns | +0.156 ns | 0 |
| SS 100°C 1.6V | +6.20 ns | +0.380 ns | 0 |
| FF -40°C 1.95V | +10.0 ns | +0.095 ns | 0 |
| **最高频率** | **~72 MHz** (20ns period, 6.2ns worst slack) |

### 签核
| 检查 | 结果 |
|------|------|
| DRC (Magic + KLayout) | 0 error |
| LVS | 0 差异 |
| Antenna | 0 violation |
| IR Drop | 0.63 mV worst (0.035%) |
| Power Grid | 0 violation |

### 非阻塞警告
- 878 slew violations @ SS corner (Sky130 正常，TT 不阻塞)
- 21 lint warnings (未使用端口等)
- 158 unannotated nets (电源/地网络)

### 输出文件
- **服务器**: `/root/GS_IC/designs/tt_loralite/runs/RUN_2026-02-24_08-33-02/final/`
- **本地**: `designs/tt_loralite/output/` (已 rsync)
- GDS: 20MB (gitignored), metrics/LEF/LIB/netlist 进 git (~8MB)

## 目录结构

```
designs/tt_loralite/
├── src/                    # 14 个 Verilog RTL 模块
├── config.json             # LibreLane 配置
├── constraints/            # SDC 时序约束
├── output/                 # LibreLane 输出 (rsync from server)
│   ├── metrics.json        # 全指标 (git tracked)
│   ├── lef/                # LEF 抽象 (git tracked)
│   ├── lib/                # 9-corner Liberty (git tracked)
│   ├── nl/, pnl/           # 网表 (git tracked)
│   ├── gds/                # GDSII (gitignored, 20MB)
│   └── spef/, sdf/, ...    # 大文件 (gitignored)
├── tb/
│   ├── *.v, *_tb.v         # Verilog testbench (17 个)
│   ├── cocotb/             # cocotb 随机化测试 (19 个)
│   ├── verilator/          # C++ 协同仿真 (958 PASS)
│   ├── yosys/              # Yosys 综合脚本
│   └── gen_test_vectors.cpp # 测试向量生成器
└── docs/                   # 设计文档
```

## Git 提交历史

```
b0eeed8 feat: Yosys synthesis + Verilator C++ co-simulation (958 PASS, 0 FAIL)
682058e test: cocotb randomized test framework (19 tests, 940+ points, ALL PASS)
8d80bec test: add 4 edge-case Verilog testbenches (256 PASS, 0 FAIL)
695c2b5 feat: docker-compose OpenLane + KLayout scripts + project handoff doc
00dc5c8 feat: TinyTapeout LoRaLite protocol processor (v3, ~2884 gates)
```

## 关键教训

### GLS 调试经验 (2026-02-24)
- **STATUS 寄存器位映射**: bit4=rx_valid (NOT bit0), bit1=tx_done (NOT bit2)
- **IRQ_FLAGS**: bit1=CRC_ERR, bit4=RX_DONE — 用 CRC_ERR==0 判断 CRC 正确
- **CRC standalone 地址**: 0x70-0x73 (NOT 0x0C-0x0D)
- **RX 解析字段地址**: 0x14-0x1B (NOT 0x08-0x0B)
- **rx_valid 脉冲**: 必须只有 1 个时钟周期, 多了会导致字节重复
- **LibreLane Docker**: Nix 容器, 无 pip/make, 需要 `nix-env -iA nixpkgs.gnumake` + `pip3 --break-system-packages`

## 下一步

- [x] 提交 LibreLane 输出到 git
- [x] GLS 验证 (手写 + cocotb 全套)
- [ ] Commit 今天全部工作
- [ ] Push 到远程
- [ ] TinyTapeout 提交准备 (info.yaml, README)
- [ ] FPGA 验证 (Alchitry Cu V2 到货后写 PCF 约束)
- [ ] LoRa 基带处理器 (designs/lora_baseband, ECP5-85K)
