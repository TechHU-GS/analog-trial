# LoRa Edge SoC 验证知识库

> 状态: 2026-02-26 RTL 冻结，GLS 全通过，GDS 多轮稳定性验证中

## 回归测试

完整回归 (bash 脚本模式，cd test/ 后执行):
```bash
# 单元测试 (直接 RTL)
iverilog -g2012 -DSIM -o tb_X.vvp tb_X.v ../src/模块.v
# 项目/集成级 (需 INCS + 全 RTL)
INCS="-I../src -I../src/tinyQV/cpu -I../src/tinyQV/peri/pwm -I../src/tinyQV/peri/spi -I../src/tinyQV/peri/ttgame -I../src/tinyQV/peri/uart"
iverilog -g2012 -DSIM -o tb_X.vvp $INCS tb_X.v [models] ../src/project.v ../src/latch_mem.v ... (全部 src/*.v + tinyQV cpu/*.v + peri/*.v)
vvp tb_X.vvp  # grep "ALL TESTS PASSED"
```

## 测试文件清单

### 单元测试 (5 个, 直接端口驱动)
| 文件 | 被测模块 | PASS | CI |
|------|---------|------|-----|
| tb_crc16.v | crc16_engine + crc16_peripheral | 33 | 是 |
| tb_i2c.v | i2c_peripheral + i2c_master | 57 | 是 |
| tb_seal.v | seal_register + crc16_engine | 169 (含 100 golden) | 是 |
| tb_watchdog.v | watchdog | 21 | 是 |
| tb_rtc.v | rtc_counter | 20 | 是 |

### 总线级测试 (1 个, force/release CPU 总线)
| 文件 | GROUP | check() | CI |
|------|-------|---------|-----|
| tb_project.v | 80 (G1-G80) | 268 | 是 |

G76-G80 为 SPI 路径测试 (本轮新增)。

### 集成测试 (3 个)
| 文件 | 说明 | PASS | CI |
|------|------|------|-----|
| tb_integration.v | P0-A Flash XIP boot | 5 | 是 |
| tb_integration_b.v | P0-B + PSRAM + I2C + WDT + Seal | 10 | 是 |
| tb_read_clear_regression.v | bit-serial read_complete 回归 | 18 | 是 |

### 固件驱动测试 (10 个, CPU 执行真实 C 固件)
| TB | 固件 | UART 签名 | CI |
|----|------|-----------|-----|
| tb_irq_timer.v | fw_irq_timer | I1I2DN | 是 (Test A) |
| tb_wdt_reboot.v | fw_wdt_reboot | B1B2DN | 是 (Test B) |
| tb_soft_reset.v | fw_soft_reset | S1S2DN | 是 (Test C) |
| tb_i2c_stress.v | fw_i2c_stress | D1D2DN | 是 (Test D) |
| tb_crc_arb.v | fw_crc_arb | E1E2E3DN | 是 (Test E) |
| tb_timer_edge.v | fw_timer_edge | F1F2F3DN | 是 (Test F) |
| tb_i2c_nack.v | fw_i2c_nack | G1G2DN | 是 (Test G) |
| tb_concurrent.v | fw_concurrent | H1H2H3DN | 是 (Test H) |
| tb_post.v | fw_post | POST\nY1C1T1W1I1L1L2M1R1DN\n | 否 (需 RISC-V GCC) |
| tb_irq_priority.v | fw_irq_priority | P1P2P3P4DN | 否 (需 RISC-V GCC) |

### 门级仿真 (2 个, 本地, 不在 CI)
| 文件 | 说明 | 结果 |
|------|------|------|
| tb_gls.v | P0-A Flash boot (post-route netlist) | **5/5 PASS** |
| tb_gls_b.v | P0-B PSRAM + 全外设 (post-route netlist) | **10/10 PASS** |

GLS 编译命令:
```bash
cd test/
iverilog -o tb_gls.vvp -DGL_TEST -DUNIT_DELAY="#1" -I ../src \
  ../verify/pdk/sg13g2_stdcell_nodelay.v \
  ../output/runs/run3/netlist/tt_um_MichaelBell_tinyQV.nl.v \
  qspi_flash_model.v tb_gls.v
vvp tb_gls.vvp
```

**关键**: 必须用 `sg13g2_stdcell_nodelay.v`（patched 版），不能用原版。
原版 DFF 模型的 `delayed_CLK`/`delayed_D` 依赖 `$setuphold` specify block 赋值，
iverilog 不支持此特性，导致所有 DFF 输出永远为 x。
Patch 方法: `sed -e 's/delayed_CLK/CLK/g' -e 's/delayed_D/D/g' ...`（共 8 个替换）

**最后回归: 14 CI TBs (619 PASS) + 2 GLS TBs (15 PASS), 0 FAIL**

## 形式验证

### seal_register (6 props, verify/seal_formal.sby, depth=40)
| # | src 行 | 属性 |
|---|--------|------|
| P1 | 252 | mono_count 每周期只能 +0 或 +1 |
| P2 | 258 | S_LATCH→S_IDLE 恰好 +1 |
| P3 | 264 | 非 commit 周期 mono 不变 |
| P4 | 270 | session_locked 后 session_id 不变 |
| P5 | 275 | session_locked 单调 (一旦 1 永远 1) |
| P6 | 282 | IDLE 状态 MMIO 写不改 mono |

### watchdog (3 props, verify/wdt_formal.sby, depth=30)
| # | src 行 | 属性 |
|---|--------|------|
| P1 | 67 | enabled 不可逆 (一旦 1 永远 1) |
| P2 | 73 | counter==0 且无 kick → 保持 0 |
| P3 | 78 | wdt_reset 仅在 counter 1→0 触发 |

### CRC 仲裁 (10 props, verify/crc_arb_formal.sby, depth=5)
verify/crc_arb_wrapper.v lines 27-58:
- seal_using_crc=1 → dv/init/data 全来自 seal (3 asserts)
- seal_using_crc=0 → dv/init/data 全来自 CPU (3 asserts)
- 双方同时非活跃 → 各自 dv=0 (2 asserts)
- 顶层互斥路由 (2 asserts)

**总计: 19 条 k-induction 证明, 全 PASS**

## 覆盖率 (Verilator branch coverage)

| 模块 | Hit Lines | Partial | Zero-Hit | 评估 | 驱动 |
|------|-----------|---------|----------|------|------|
| crc16_engine | 18 | 0 | 0 | 100% | cov_crc16_tb.cpp |
| crc16_peripheral | comb | 2 | 0 | 100% | cov_crc16_tb.cpp |
| watchdog | 17 | 2 | 0 | 100% | cov_wdt_tb.cpp |
| rtc_counter | 10 | 1 | 0 | 100% | cov_rtc_tb.cpp |
| latch_mem | 9 | 7(toggle) | 0 | 100% | cov_latch_tb.cpp |
| i2c_peripheral | 37 | 8 | 1(artifact) | 99.7% | cov_i2c_tb.cpp |
| seal_register | 92/121 | — | 2(default) | 76% | seal_cov_tb.cpp |
| project.v | 65 | 35 | 30 | 81.8% | cov_project_tb.cpp |

project.v zero-hit: SPI 路径 (Icarus G76-G80 已补), boot 配置, GPIO 部分 sel 值。
1PPS 路径本轮已补 (cov_project_wrap.v 加入 pps_gen)。

## 突变测试 (6/6 全检出)

| # | 文件 | 突变 | 检出 TB |
|---|------|------|---------|
| 1 | seal_register.v:226 | mono_count+1 → mono_count | tb_seal |
| 2 | seal_register.v:97 | read_seq 固定为 0 | tb_seal |
| 3 | watchdog.v:45 | enabled<=1 → enabled<=0 | tb_watchdog |
| 4 | project.v:484 | i2c_data_rd read_complete→read_n | tb_read_clear_regression (项目级) |
| 5 | crc16_engine.v:55 | 0xA001 → 0xA000 | tb_crc16 |
| 6 | project.v:449 | seal_data_rd read_complete→read_n | tb_read_clear_regression (项目级) |

#4/#6 是历史致命 bug 精确复现，单元级 tb_i2c 无法检出。

## 行为模型

| 文件 | 位置 | 用途 |
|------|------|------|
| qspi_flash_model.v | test/ | QSPI Flash XIP (HEX_FILE 参数加载) |
| qspi_psram_model.v | test/ | QSPI PSRAM 8KB |
| i2c_slave_model.v | test/ | SHT31 @ 0x44 |
| qspi_flash_model_sync.v | verify/ | 同步版 (Verilator --no-timing) |
| qspi_psram_model_sync.v | verify/ | 同步版 |
| i2c_slave_model_sync.v | verify/ | 同步版 |

Verilator 派生时钟 (spi_clk) 在 --timing 模式下调度异常，需用同步版本 + --no-timing。

## 残余风险

1. SPI Verilator 覆盖仍为 0 (POST 不用 SPI), Icarus G76-G80 已补功能覆盖
2. 无 FPGA 物理验证 — FPGA 到手后第一件事跑 POST 固件
3. ~~GLS 未纳入 CI~~ GLS 已本地通过 (P0-A 5/5 + P0-B 10/10)，但未纳入 CI（需网表产物）
4. tb_post/tb_irq_priority 未进 CI — 需 CI 环境装 RISC-V GCC
5. SX1268 BUSY 轮询路径未测 — 需实际 SX1268
6. Antenna violation 1 个 — 经 13 轮参数调优，从 7 降至 1，density=66.5 为最优点

## 关键调试模式

### bus_write/bus_read (tb_project.v 模式)
绕过 CPU，直接 force/release TinyQV data_addr/write_n/read_n/data_out。
适用于隔离外设 bug，不需编译固件。

### UART 字节监控器
115200 baud @ 25MHz = 217 clk/bit。
检测 start bit falling edge → shift 8 bits → verify stop bit。

### 固件 UART 签名协议
每个测试点输出 2 字节 (tag char + result digit)。
TB 用 check_2char task 逐对验证。以 "DN\n" 标记结束。

### 固件编译
```bash
riscv64-elf-gcc -march=rv32ec_zicsr -mabi=ilp32e -nostdlib -Os -T test/fw_p0b.ld -o fw.elf fw.c
riscv64-elf-objcopy -O verilog --verilog-data-width=4 fw.elf fw.hex
```
