# 模拟版图 Routing Debug 方法论 (2026-03-09)

## 核心原则: 诊断先于修复，Python 做内循环

遇到大量 routing failure 时：
1. **不打地鼠** — 不手动逐个检查失败 net
2. **写诊断脚本** — 对所有 N 个问题一次性批量分析
3. **量化瓶颈** — 把"可能是这个原因"变成"数据说是这个原因"
4. **隔离实验** — 一次只改一个变量，对比 baseline
5. **LLM 只做决策层** — 架构判断、实验设计、模式识别；坐标算/shape 探测/占用统计全交给 Python

## 诊断分层: 从全局到局部

### 第一步: Zone Breakdown (diagnose_failures.py)
- 按功能岛 (I1/I2/I3/I4) 分类失败网络
- 快速定位主要失败区域
- 如果某个岛有 80% 的失败 → 优先处理它

### 第二步: 空间热力图 (diagnose_failures.py)
- Stuck pin 的 X/Y 分布 (5µm buckets)
- 看失败是分散的还是集中的
- 热点集中 → 结构性问题; 分散 → 全局容量问题

### 第三步: 深层阻塞分析 (diagnose_congestion.py)
**关键脚本** — 从 routing.json + placement.json + ties.json 重建 router grid 状态：
- 重建 M1/M2 占用图 (device bbox + tie cell + power + signal wire)
- 对每个 stuck pin 的 radius-3 邻域分类: 被什么类型的障碍封锁
- 区分 **永久障碍** (device/tie/power) vs **信号占用** (已路由 net)
- 按 Y-stripe 画 M1/M2 利用率直方图
- 识别 escape corridor 的 free/used 比例

### 第四步: 残余失败精分 (diagnose_i4_residual.py)
- 失败网络按 TFF stage 分布
- 跨列 vs 本列网络
- 剩余 stuck pin 的设备级归属
- 剩余 tie 对 escape corridor 的影响量化

## 关键洞察: M1 Access Geometry 瓶颈 (SoilZ v1 实证)

### 问题发现过程

v3.3b routing: 93/141 routed, 89 个 I4 stuck pins

**盲目尝试阶段** (浪费 token):
- Exp1: TFF mirror (slave 朝外) → 93/141，无变化
- Exp2: Routing order (高失败网优先) → 77/141，更差

**转折点**: 用户要求"python 来找根本原因"

**diagnose_congestion.py 揭示真因**:
- Stuck pin 邻域: 25% device bbox + 10% tie cell = **35% M1 永久封锁**
- M2 free = **79.6%** — 路由容量充足
- 结论: **不是 routing capacity failure, 是 M1 access failure**
- Pin 连 via 都放不下，自然到不了 M2

### 根因量化

```
device GAP = 0.7µm
DEV_MARGIN = 200nm (router 对 device bbox 的 M1 blocking)
相邻设备间 M1 free = 700 - 200 - 200 = 300nm
MAZE_GRID = 350nm

结论: 0 条可用 M1 routing track。这不是拥塞，是几何上不可达。
```

tie cell 用 tie_margin=505nm 封 M1，在行间隙中进一步吃掉逃逸口。

### 两层修复 (GAP sweep + tie share)

**实验设计原则**:
- 每次只改一个变量
- 先扫少数关键点 (0.70/1.05/1.20/1.40)，不密扫
- 看门槛型变化 (0→1 track 的跳变)
- 检查反向效应 (GAP 增大 → 左右列间距缩小)

**GAP sweep 结果**:
| GAP (µm) | M1 tracks | Routed | I4 stuck |
|-----------|-----------|--------|----------|
| 0.70 | 0.9 | 93/141 | 89 |
| 1.05 | 1.9 | 94/141 | 72 |
| **1.20** | **2.3** | **99/141** | **61** |
| 1.40 | 2.9 | 98/141 | 66 |

**GAP=1.20 最优**: 再大反而变差 — 左右列间距从 9.86→6.86µm，反向效应

**Tie share 结果** (固定 GAP=1.20):
- 每 4 个同行 TFF 设备共享 1 个中心 tie: 245→161 ties (-84)
- LU 距离: worst=8845nm << 20000nm limit
- **99→104/141 (+5), I4 stuck 61→43 (-18)**

**累计**: 93→104 (+11), I4 stuck 89→43 (-46)

### 关键教训

1. **M2 free 很多不代表没问题** — 瓶颈可能在 M1 pin escape 层
2. **GAP 和 tie 是串联瓶颈** — 两个独立有效，可叠加
3. **存在反向效应** — GAP 增大缩小 inter-column gap，有最优点
4. **tie share 安全余量大** — LU 规则 20µm，实际最远 <9µm
5. **盲目的几何操作 (mirror/stagger) 不如先写诊断脚本**

## 诊断脚本清单

| 脚本 | 用途 | 输入 |
|------|------|------|
| `diagnose_failures.py` | Zone breakdown + stuck pin heatmap + routing order analysis | routing.json + netlist.json + /tmp/routing_log.txt |
| `diagnose_congestion.py` | M1/M2 grid occupancy 重建 + per-stuck-pin blocker 分类 | placement.json + routing.json + ties.json |
| `diagnose_i4_residual.py` | Stage-aware failure + tie-vs-corridor + stuck pin device attribution | 同上 + /tmp/routing_log.txt |
| `sweep_tff_gap.py` | GAP 参数扫描自动化 | env TFF_GAP |
| `filter_tff_ties.py` | TFF tie 共享 post-filter | output/ties.json |

## 104→110: Profile B 手动路由顺序 (2026-03-09)

- 手动设计 141 net 路由顺序 (Profile B), 基于 I4 chokepoint 分析
- **104→110** (+6 nets)
- 这是人工经验 + 诊断数据的结果，非随机

## 110 天花板证据链 (2026-03-10)

详细实验数据 → `routing_optimization_experiments.md`

**结论**: 110/141 是当前 layout+router 的 pin escape 静态瓶颈, 不是顺序/拥塞瓶颈。

| 实验 | 变量 | 结果 | 证明了什么 |
|------|------|------|-----------|
| 随机顺序 100 trials | routing_order | max=108, 0 达 110 | 顺序空间穷尽 |
| T2I_s1↔s3 +0.70µm | 布局间距 | -4 (110→106) | 单点布局微调无效 |
| 批量 rip-up 9 nets | 已布线容量 | -4 (110→106) | 拥塞不是根因 |
| 单条 rip-up 5 probes | 单条 blocker | 全部 gained=0 | 任何单条 net 都不是 blocker |

**根因**: failed net pins 被 permanent obstacles (device body M1 + power M2 vbar + tie M1) 封死,
`_signal_escape_recheck` 只释放了 28 个, 还有更多未释放。rip-up 只能移除 `router.used`,
无法移除 `router.permanent`。

## 110→111: I3 Tie Reduction (2026-03-10)

- I3-Drive zone 28 ties → 14 (-14), `filter_analog_ties.py --zone=i3`
- **110→111** (+1, 恢复 `da1`)
- I2 tie reduction 反而 -2 (chop_out/c_di_n/tail 新失败) → I2 对 tie 极敏感，不适合减

## 2 层金属天花板 — 真正的根因 (2026-03-10)

**关键发现**: 所有 2 层内优化 (GAP/tie/order/solver/layout) 都在 110±1 打转。
根因不是布局、不是路由顺序、不是 tie — 是路由器只用 M1+M2 两层金属。

| 尝试 | 结果 | 说明 |
|------|------|------|
| GAP sweep + TFF tie share | 93→110 | 有效但已用完 |
| 5 种 I4 layout 变体 | 全 ≤110 | 零和 |
| Solver escape 扩展 | 110→110 | 无空间 |
| I2 tie reduction | 110→108 | 有害 |
| I3 tie reduction | 110→111 | +1 极限 |
| 大网 order promotion | 111→97 | 灾难 |
| 随机 order 100 trials | max=108 | 穷尽 |

**IHP SG13G2 有 7 层金属 (M1-M5 + TopMetal1/2)，路由器只用了 2 层。**
M3 当前仅用于电源 rail (3µm horizontal)，信号路由从未使用 M3。
M2 free = 79.6% 但 M1 pin escape 被永久障碍封死 → 需要 M3 做信号跨越。

**解决方案**: 扩展 maze router 支持 M1+M2+M3+M4 四层信号路由。

**M3 结果 (2026-03-10)**: 111 → **127/141** (+16), 大 divider nets 全部恢复
- M3 上无 device body / tie 障碍，只有电源 rail (54245 cells) 需要避让
- 5 条仍失败 (db1, probe_p, ref_I, sens_n, vco_out)，各差 1 pin

**M4 结果 (2026-03-10)**: 127 → **133/133 (100%)** (+6, 0 failed!)
- M4 上完全无障碍 (无电源结构)
- 前面 5 条全部恢复，包括 vco_out (67 segments)
- 8 个 single-pin 外部输入 (sel0/sel1/sel2/vref) 无需路由
- Segments: M1=154, M2=559, M3≈300, M4≈300
- Vias: Via1=39, Via2=83, Via3=82

**层数 vs routing 对照表**:
| 层数 | 结果 | 提升 |
|------|------|------|
| M1+M2 | 111/141 | baseline |
| +M3 | 127/141 | +16 |
| +M4 | 133/133 | +6, **100%** |

**教训**: 应该在第一次诊断出 M1 拥塞时就质疑"为什么只用 2 层"，
而不是在 2 层限制内做了 10+ 轮优化实验。问对问题比优化参数重要得多。

## 实验设计模板

```
1. 明确变量: 只改一个 (GAP / tie density / tie position)
2. 冻结其余: I2/I3/全局骨架不动
3. 选关键点: 3-4 个值，不密扫
4. 跑完整 pipeline: placement → ties → routing → diagnosis
5. 对比表: routed, zone breakdown, stuck count, M1 free
6. 检查反向效应: footprint 增大是否挤压其他通道
7. 检查隔离: I2/I3 不应变化
```
