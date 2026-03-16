# LoRa Edge SoC GDS 参数调优记录 (2026-02-27)

> 服务器: root@100.64.0.4, LibreLane 3.0.0.dev44, IHP SG13G2
> 固定参数: SYNTH_STRATEGY "AREA 0", GRT_ANTENNA_MARGIN 15, CLOCK_PERIOD 40

## 实验矩阵

| Run | DENSITY | ITERS | Antenna | Setup WS (ns) | Std Cells | Result |
|-----|---------|-------|---------|---------------|-----------|--------|
| 2/3 | 66.0 | 1 | 2 | 10.24 | 14,596 | PASS (确定性验证) |
| 4 | 66.0 | 3 | 7 | 10.24 | 14,596 | PASS (ITERS↑ antenna↑) |
| 5 | 66.0 | 1 | - | - | - | GPL-0302 (MARGIN=10) |
| 6 | 66.0 | default | - | - | - | GPL-0302 |
| 7 | 66.0 | default | - | - | - | GPL-0302 |
| 8 | 66.0 | 1 | - | - | - | GPL-0302 |
| 9 | 67.0 | default(3) | 6 | 10.37 | 14,663 | PASS |
| **10** | **66.5** | **1** | **1** | **10.30** | **14,679** | **PASS (最优)** |
| 11 | 66.4 | 1 | 3 | 10.30 | 14,679 | PASS |
| 12 | 66.6 | 1 | 4 | 10.39 | 14,682 | PASS |
| 13 | 66.5 | 2 | 1 | 10.30 | 14,679 | PASS (=Run 10) |

## 关键发现

### 1. Density 窄窗口
- 实际利用率 ~66.1% (python3.11 环境下)
- density < 66.1% → GPL-0302 (target < actual)
- density > 68% → DPL-0036 (hold buffer 无空间)
- 安全范围: 66.5 ~ 67.0

### 2. ITERS 影响
- ITERS=1: 确定性，antenna 最少 (Run 10: 1 个)
- ITERS=2: 与 ITERS=1 结果完全一致 (第二轮无修复)
- ITERS=3/default: 非确定性，antenna 反而增多 (6-7 个)
- 结论: ITERS=1 是最优选择

### 3. Density 微调效果
- 0.1% 的 density 变化改变 placement seed
- 66.5 恰好是 antenna 谷底 (1 个)
- 66.4 (3 个) 和 66.6 (4 个) 都更差

### 4. Run 5-8 GPL-0302 根因
- python3 从 3.10 改为 3.11 后 tt_tool.py config 合并行为微变
- 实际利用率从 ~65.99% 漂移到 66.10%
- density=66 时超标 0.1% 触发 GPL-0302
- 解决: 提高 density 到 66.5

## 最终配置 (config.json)

```json
{
  "PL_TARGET_DENSITY_PCT": 66.5,
  "GRT_ANTENNA_ITERS": 1,
  "GRT_ANTENNA_MARGIN": 15,
  "SYNTH_STRATEGY": "AREA 0",
  "CLOCK_PERIOD": 40,
  "PL_RESIZER_HOLD_SLACK_MARGIN": 0.1,
  "GRT_RESIZER_HOLD_SLACK_MARGIN": 0.05
}
```

## 最优结果 (Run 10 = Run 13)

- DRC: 0, LVS: 0, Magic DRC: 0
- Setup violations: 0 (WS = 10.30 ns, 25.7% margin)
- Hold violations: 0 (WS = 0.113 ns)
- Antenna violations: 1
- Std cells: 14,679, Hold buffers: 2,412
- Utilization: 93.1%
- Route wirelength: 600,822 nm
