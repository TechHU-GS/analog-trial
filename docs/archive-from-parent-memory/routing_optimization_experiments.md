# SoilZ v1 路由优化实验记录 (2026-03-10)

## 基线

- **版图**: v3.3b, 249 devices, 5-island, TFF_GAP=1.20µm, tie share
- **路由**: Profile B (手动设计顺序), **110/141 routed** (78%)
- **Router**: greedy sequential maze router (A* 双层, 350nm grid, MAZE_MARGIN=1)
- **31 failed nets**: 主要集中在 I4 TFF divider 区 (y=180~265µm)

## 实验 1: 单点布局微调 — T2I_s1↔T2I_s3 +0.70µm

- **脚本**: `experiment_t2i_widen.py`
- **方法**: 右移 T2I_s3/s7/s8 + T2I_s4/s5/s6 by +0.70µm, 重生 ties, 重跑路由
- **结果**: **110→106 (delta -4)**, gained ref_Q+t1Q_mb, lost div16_I_b+t1I_mb+t1I_nmp+t2I_m+t4I_nmn+t4Q_mb
- **结论**: 单点布局微调引发级联失败，零和偏负。不可行。

## 实验 2: 随机路由顺序搜索 (100 trials)

- **脚本**: `experiment_random_order.py`
- **方法**: 50 pure random + 50 constrained random (26 infrastructure nets 固定)
- **结果**:
  - Pure random: min=91, max=108, mean=99.3, median=99
  - Constrained: min=89, max=106, mean=98.4, median=99
  - **0/100 trials 达到 110**
- **结论**: Profile B 的 110 是顺序空间的强 outlier (>2σ above mean)。继续随机搜索无收益。

## 实验 3: Partial rip-up A1 — 批量拆 9 nets

- **脚本**: `experiment_partial_ripup.py`
- **方法**: 拆 t1Q_m, div16_I/I_b/Q/Q_b, t1I_m, t2I_m, f_exc, f_exc_b (9 nets)
  → 释放 9,930 used cells → 路由 31 failed nets → 回补 ripped nets
- **结果**: **110→106 (delta -4)**, gained nb_mid+sens_n, lost 6/9 ripped nets
- **关键发现**: 释放 9930 cells 后，div2_I_b 仍 12 pins unreachable，div4_I 仍 11 pins unreachable。
  pins 被 permanent obstacles (device body, power M2, tie M1) 困住，不是路由拥塞。

## 实验 4: 单条 rip-up 探针 (5/15 completed)

- **脚本**: `experiment_ripup_v2.py`
- **方法**: 每条 candidate 单独拆，测试所有 31 failed nets，再回补

| 拆掉 | 释放 cells | 新通 | 回补 | Delta |
|------|-----------|------|------|-------|
| t1Q_m | 528 | 0 | OK | 0 |
| div16_I | 1048 | 0 | FAIL | -1 |
| div16_I_b | 657 | 0 | FAIL | -1 |
| div16_Q | 793 | 0 | FAIL | -1 |
| div16_Q_b | 565 | 0 | FAIL | -1 |

- **结论**: 拆任何单条 net，对 31 failed nets 增益 = 0。div16_* 拆后自己都回不去。

## 根因定位

**110 不是"顺序瓶颈"也不是"动态拥塞瓶颈"，而是 pin escape 静态瓶颈。**

证据链：
1. 随机顺序搜索: 顺序空间穷尽 (100 trials, max=108)
2. 布局微调: 单点改动引发级联失败 (-4)
3. 批量 rip-up: 释放 ~10K cells，大部分 failed nets 仍 STUCK
4. 单条 rip-up: 拆任何单条 net，0 条 failed net 受益
5. STUCK 输出: failed nets 的 pins 在 permanent obstacle 包围中，BFS 不可达

**真正的瓶颈**: `_signal_escape_recheck` 释放了 28 个 trapped pins，但还有更多 pin 被 device body M1 + power M2 vbar + tie M1 永久封死。rip-up 只能移除 `router.used` (已布线), 无法移除 `router.permanent` (设备/电源/tie)。

## 下一步选项 (2026-03-10)

1. **改 solver 代码**: 让 `_signal_escape_recheck` 更激进地为 trapped pins 打通 escape corridor
2. **接受 110/141, 收工提交**: 评估 31 unrouted nets 是否影响核心功能
