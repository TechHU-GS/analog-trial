# SoilZ v1 复盘 — TTIHP 26a (IHP SG13G2 130nm)

## 结果
- **PR #496 Merged** — 芯片会被制造
- **但 IC 功能不完整** — 数字引脚浮空，sel 未 tie，R_in/R_dac 接错
- DRC=0，LVS 48 unmatched + R_in/R_dac routing 错误

## 时间线
10 天, 13 sessions (2026-03-14 → 2026-03-24)

| 阶段 | 时间 | 产出 |
|---|---|---|
| Session 1-8 (ATK flat-GDS) | 60% | **全部废弃** |
| Session 9-13 (Modular PCell) | 40% | 12 模块 + routing + CI pass |

## 五大失败

### 1. 架构错误坚持了 8 个 session
M1/M2 是器件层，routing 在上面必然碰撞。这个事实 30 分钟能验证，但用了 8 个 session 才放弃。

### 2. 数字引脚没连
Tile pin (y=313) 到内部电路 (y=20-100) 需要 M4-V routing。最后 1 小时才想到，做了但 Verilog VGND/VDPWR 阻止了 submission check，改进版没被 merge。

### 3. sel0/1/2 没 tie
3 分钟的工作。没做 → 电流源不工作 → 无激励 → IC 不可测。

### 4. R_in/R_dac 接错
Auto-router 的 `find_nearest_pad` 按距离选 M2 pad，不验证 net identity。rin/rdac 的 M2 pad 被连到 OTA_OUT 而不是 CHOP_OUT/DAC_OUT。后仿发现时已经提交了。

### 5. 优先级搞反
实际：signal routing → power DRC 循环 → cap → ua → digital pin → (没做 sel tie)
正确：signal routing → digital pin → sel tie → power → LVS verify → DRC

## 核心教训

1. **功能连通性 > DRC clean** — DRC=0 但不工作没有意义
2. **Auto-router 不理解 net identity** — 必须验证每条 route 连的是正确的 net
3. **先验证架构再建工具** — 30 分钟测试 > 8 session 优化错误方案
4. **后仿在提交前跑** — 能发现 R_in/R_dac 接错
5. **Tile pin + control tie 第一天做** — 不是最后一天

## V2 要求

1. Day 1: Verilog 对齐 + PCell 验证 + tile pin routing
2. 每条 route 跑 LVS 验证 net identity
3. sel/control 内部 tie 或连 tile pin
4. 后仿在 submit 前必须跑通
5. 用 Magic 手画版图（实时 DRC + LVS）
6. 提交前 48 小时锁定

## 数据

- 488 → 184 tracked files (清理了 300+ ATK/L2 废文件)
- 12/12 transistor modules LVS pass
- 7/7 passive modules DRC=0
- 23/23 signal nets routed (but R_in/R_dac net identity wrong)
- VCO 前仿 ~4.2MHz confirmed
