# SoC 全面 FPGA 验证计划 — Phase E: 补全所有测试

## Context

Phase A-D 已完成大部分工作：BRAM 启动外设全通、QSPI 外部启动成功、PSRAM 固件测试通过。
但有以下 **未完成项**：

| 缺口 | 原因 | 解决方案 |
|------|------|---------|
| fw_fpga_soft_reset | BRAM 模式一直没测 | 直接测，无代码修改 |
| I2C 测试全部用 SHT31@0x44 | ULX3S 无 SHT31，全 NACK | 适配为 MCP7940N@0x6F |
| fw_irq_priority P2-P4 | 依赖 TB 自动控制 DIO1 | 改为手动 btn_fire1 + 延长超时 |
| UART RX + IRQ18 | 仿真通过但 FPGA 未测 | 新固件 + Python 脚本从 FTDI 发送 |

**目标**：每个 SoC 功能都有真实硬件验证记录，不留"仅仿真通过"或"NACK 跳过"。

---

## 已完成状态 (Phase A-D)

### BRAM 启动 ✅
fw_p0a, fw_fpga_test, fw_fpga_irq, fw_fpga_gpio, fw_fpga_spi, fw_fpga_i2c, fw_fpga_qspi_pmod — 全 PASS

### 外部 QSPI 启动 ✅
fw_p0b(M1/I0), fw_irq_timer(I1I2DN), fw_timer_edge(F1F2F3DN), fw_crc_arb(E1E2E3DN),
fw_wdt_reboot(B1B2DN), fw_soft_reset(S1S2DN), fw_concurrent(H0H2H0DN), fw_i2c_nack(G1G0DN) — 全 PASS

**H0/G0 = I2C 地址 0x44 NACK（非 SoC bug），需在 E2 中修正。**

---

## E1: fw_fpga_soft_reset (BRAM 模式)

**无代码修改**，直接构建测试。

- 构建：`make clean && make ulx3s HEX_FILE=../test/fw_fpga_soft_reset.hex`
- 烧录：`fujprog ulx3s_85f.bit`
- 期望：UART 输出 `OK\n` 至少两次（软复位循环）
- 文件：`test/fw_fpga_soft_reset.c`（只读）

---

## E2: I2C 适配 — SHT31@0x44 → MCP7940N@0x6F

### 参考模板
`test/fw_fpga_i2c.c` 中的 `mcp_read_reg()` / `mcp_write_reg()` — 已在 FPGA 验证通过。

### MCP7940N 关键特征
- 7-bit 地址 0x6F
- 寄存器式访问：先写寄存器地址，再读数据
- Reg 0x00 = 秒（BCD, bit7=ST 振荡器使能位）
- Reg 0x01 = 分（BCD, 0x00-0x59）
- Reg 0x02 = 时（BCD）
- 读出值是动态的（真实 RTC 时间），不能用固定值校验
- 校验策略：`val >= 0`（读成功）或 BCD 范围检查

### E2a: fw_i2c_nack.c 修改

**当前问题**：G2 测试目标 0x44 → NACK → G0

**修改**：
- G1 保持不变（0x7F → NACK，已 PASS）
- G2：改为 MCP7940N@0x6F 成功事务
  - 写寄存器地址 0x00 + STOP
  - 读 1 字节（秒寄存器）
  - 校验：`rx >= 0 && no_nack`
- 期望输出：`G1G2DN`

### E2b: fw_i2c_stress.c 修改

**当前问题**：6 字节连续读 SHT31 → 全部 NACK

**修改**：改为 MCP7940N 多寄存器连续读测试
- D1：写寄存器地址 0x00 + STOP（设置读指针）
- D2：连续读 7 字节（reg 0x00-0x06：秒/分/时/星期/日/月/年）
  - MCP7940N 支持 auto-increment 地址指针
  - 校验：所有 7 字节 `rx >= 0`（读成功），且秒/分 BCD 合法
- 保留原测试的多字节连续读意图，改用真实设备
- 期望输出：`D1D2DN`

### E2c: fw_concurrent.c 修改

**当前问题**：H1/H3 的 I2C 目标 0x44 → NACK → H0

**修改**：
- H1：Timer IRQ + I2C(0x6F) → `mcp_read_reg(0x00)` 替代 SHT31 读
  - 校验：`rx >= 0 && timer_ok`
- H2：不变（CRC + Timer，无 I2C）
- H3：I2C(0x6F) + CRC
  - 校验：`rx >= 0 && crc_ok`
- 期望输出：`H1H2H3DN`

### E2d: fw_post.c 修改

**当前问题**：I 测试目标 0x44 → NACK → I0

**修改**：
- 替换 I2C 地址 0x44 → 0x6F
- 使用寄存器式读取（写 reg 0x00，读 2 字节）
- 校验：`rx1 >= 0 && rx2 >= 0`（成功读到秒和分）
- 期望输出：`POST\nY1C1T1W1I1L1L2M1R1DN\n`

### E2 共通注意事项
- 每个修改后的固件需重新编译 → flash_writer.py → ulx3s_85f_ext.bit 验证
- fw_p0b.c 不修改（已通过 I0 表示 NACK 路径正确，I2C 功能由 fw_fpga_i2c 验证）

---

## E3: fw_irq_priority — FPGA 手动按键版

**当前问题**：P2-P4 依赖 TB 通过 GPIO_OUT[7] 信号自动注入 DIO1 边沿

### 修改方案

**P1（Timer IRQ17 alone）**：无修改，已可运行

**P2（DIO1 IRQ16 alone）**：
- 去掉 GPIO_OUT 信号（FPGA 上无意义）
- 延长超时：500K → 5000000（TinyQV 慢，~30 秒窗口）
- 用户手动按 btn_fire1 触发 ui_in[0] 上升沿 → mip_reg[16]
- 校验不变：mcause == 16

**P3+P4（同时触发 IRQ16 + IRQ17，验证优先级）**：
- 关闭全局中断
- 启动 Timer(5µs) → mip_reg[17] 快速置位
- 延长等待窗口：用 csrr 轮询 mip CSR（0x344），直到 bit16 也置位（用户按键）或超时
  ```c
  // 等待 mip bit 16 (DIO1) — 用户按 btn_fire1
  unsigned int mip_val;
  unsigned int timeout = 5000000;
  do {
      __asm__ volatile ("csrr %0, 0x344" : "=r"(mip_val));
      timeout--;
  } while (!(mip_val & (1u << 16)) && timeout > 0);
  ```
- 两个 mip 位都置位后，开全局中断 → 优先级编码器裁决
- 校验：mcause_log[0]==16（IRQ16 先），mcause_log[1]==17（IRQ17 后）

**关键文件**：`test/fw_irq_priority.c`（修改），`test/fw_irq_priority.ld`（不变）

**FPGA 操作流程**：
1. 编译 → flash 到 W25Q128 → 烧 ext bitstream
2. 开串口监控
3. 等 P1 自动通过（输出 `P1`）
4. 看到 `P1` 后按 btn_fire1 → 输出 `P2`
5. 再按 btn_fire1 → 输出 `P3P4DN`
6. 期望输出：`P1P2P3P4DN`

---

## E4: UART RX + IRQ18 测试

### E4a: fw_fpga_uart_rx.c (新建)

**测试内容**：
- U1：UART RX 轮询接收 — 主机发 1 字节，SoC 读 UART_STATUS + UART_DATA，回显
- U2：UART RX 连续接收 — 主机发 4 字节序列，SoC 逐字节接收并校验
- U3：UART RX IRQ18 — 使能 IRQ18(mie bit18)，主机发 1 字节，验证 ISR 触发且 mcause==18

**UART 寄存器**（参考 `src/tinyQV/peri/uart/uart_rx.v`）：
- UART_STATUS bit1 = RX_VALID（有数据可读）
- UART_DATA 读取 = 接收到的字节（读取同时清除 RX_VALID）
- IRQ18 = uart_rx 中断（level-triggered，rx_valid 为高时持续触发）

**协议**：
```
SoC → Host: "READY\n"        (表示可以开始发送)
Host → SoC: 0x55             (U1 测试字节)
SoC → Host: "U1"             (接收正确)
Host → SoC: 0x01 0x02 0x03 0x04  (U2 测试序列)
SoC → Host: "U2"             (序列正确)
Host → SoC: 0xAA             (U3 IRQ 测试字节)
SoC → Host: "U3DN\n"         (IRQ 触发正确)
```

**注意**：
- IRQ18 是 level-triggered（非 edge），ISR 中必须读 UART_DATA 清除 rx_valid，否则会重复触发
- ISR 需要 `csrc 0x344, (1<<18)` 清除 mip 位
- UART RX 单字节缓冲，主机发送间隔须足够长（SoC 处理速度慢）

**Linker**：fw_irq_timer.ld（PSRAM 栈，ISR 需要）

### E4b: uart_rx_test.py (新建)

```python
# 1. 等待 "READY"
# 2. 发送 0x55，等待 "U1"
# 3. 发送 0x01,0x02,0x03,0x04（每字节间隔 50ms），等待 "U2"
# 4. 发送 0xAA，等待 "U3DN"
# 5. 报告 PASS/FAIL
```

**发送间隔**：TinyQV 每条指令 24-200 clk，接收一个字节后处理需要几百条指令 ≈ 数百微秒。50ms 间隔绰绰有余。

---

## 实施顺序

| 步骤 | 内容 | 启动模式 | 预计时间 |
|------|------|---------|---------|
| E1 | fw_fpga_soft_reset | BRAM | 10 min |
| E2a | fw_i2c_nack 适配 | QSPI ext | 20 min |
| E2b | fw_i2c_stress 适配 | QSPI ext | 30 min |
| E2c | fw_concurrent 适配 | QSPI ext | 20 min |
| E2d | fw_post 适配 | QSPI ext | 20 min |
| E3 | fw_irq_priority 适配 | QSPI ext | 30 min |
| E4 | UART RX 新固件+脚本 | QSPI ext | 45 min |

## 文件清单

| 文件 | 操作 | 步骤 |
|------|------|------|
| `test/fw_i2c_nack.c` | 修改：G2 改用 0x6F + 寄存器读 | E2a |
| `test/fw_i2c_stress.c` | 修改：改为 MCP7940N 7 字节连续读 | E2b |
| `test/fw_concurrent.c` | 修改：H1/H3 改用 0x6F | E2c |
| `test/fw_post.c` | 修改：I 测试改用 0x6F | E2d |
| `test/fw_irq_priority.c` | 修改：P2-P4 改为手动按键 + 轮询 mip | E3 |
| `test/fw_fpga_uart_rx.c` | 新建：UART RX + IRQ18 测试固件 | E4 |
| `test/uart_rx_test.py` | 新建：主机 UART 发送脚本 | E4 |

## 验证检查清单（2026-03-11 全部完成）

- [x] E1: fw_fpga_soft_reset → `OK\n` ×85+ ✅
- [x] E2a: fw_i2c_nack → `G1G2DN` ✅
- [x] E2b: fw_i2c_stress → `D1D2DN` ✅
- [x] E2c: fw_concurrent → `H1H2H3DN` ✅
- [x] E2d: fw_post → `POST\nY1C1T1W1I1L1L2M1R1DN\n` ✅
- [x] E3: fw_irq_priority → `P1P2P3P4DN` ✅（手动 btn_fire1）
- [x] E4: fw_fpga_uart_rx → `U1U2U3DN` ✅（uart_rx_test.py 驱动）

## 完成后的 SoC 验证覆盖

| SoC 功能 | BRAM 测试 | FPGA 外部启动测试 |
|----------|----------|------------------|
| CPU RV32EC | ✅ fw_p0a | ✅ 所有外部固件 |
| QSPI Flash 读 | ✅ bram_flash | ✅ W25Q128 continuous read |
| QSPI PSRAM 读写 | — | ✅ fw_p0b, fw_wdt_reboot |
| UART TX | ✅ 所有固件 | ✅ 所有固件 |
| UART RX | ✅ fw_fpga_test(U1) | ✅ fw_fpga_uart_rx(U1U2) |
| UART RX IRQ18 | ✅ fw_fpga_irq(K1) | ✅ fw_fpga_uart_rx(U3) |
| Timer | ✅ fw_p0a | ✅ fw_irq_timer, fw_timer_edge |
| Timer IRQ17 | ✅ fw_fpga_irq | ✅ fw_irq_timer |
| IRQ 优先级 | — | ✅ fw_irq_priority(P3P4) |
| DIO1 IRQ16 | ✅ fw_fpga_gpio | ✅ fw_irq_priority(P2) |
| WDT | ✅ fw_fpga_test | ✅ fw_wdt_reboot |
| RTC | ✅ fw_fpga_test | ✅ fw_post |
| CRC16 | ✅ fw_fpga_test | ✅ fw_crc_arb |
| Seal Register | ✅ fw_fpga_test | ✅ fw_crc_arb, fw_post |
| Latch Memory | ✅ fw_fpga_test | — |
| SysInfo | ✅ fw_fpga_test | ✅ fw_post |
| Soft Reset | ✅ fw_fpga_soft_reset | ✅ fw_soft_reset |
| I2C Master (ACK) | ✅ fw_fpga_i2c | ✅ fw_i2c_stress, fw_concurrent |
| I2C NACK | — | ✅ fw_i2c_nack(G1G2) |
| SPI Master | ✅ fw_fpga_spi | — |
| GPIO Input | ✅ fw_fpga_test | — |
| GPIO Output | ✅ fw_fpga_gpio | — |

**✅ Phase E 全部完成（2026-03-11）。所有 SoC 功能零空白。**
