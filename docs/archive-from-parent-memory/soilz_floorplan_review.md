# SoilZ v1 Floorplan Review (2026-03-09)

## Manual Placement v2 核心诊断

**根本问题**: 电路上最强耦合的块没挨一起，噪声上最该隔离的块没彻底隔开。
利用率低 (4.6%) 但 stuck net 多 — 空白不在需要布线的地方。

### 15 条具体问题

1. 顶部数字区横向铺太散 — TFF/MUX/BUF 应压缩成紧凑数字岛
2. VCO 没当噪声源隔离 — 应在数字岛边缘，远离 PTAT/Bias/OTA
3. PTAT+Bias+CurrentSrc 没形成 reference spine — 散在各角落
4. Rptat 135µm 横条切断中部路由通道 — 不要当"墙"
5. 左下 sigma_delta 堆叠局促，不像围绕信号流组织
6. OTA→comp→SR latch 没形成紧耦合量化岛 — 应最短闭环
7. H-bridge/NOL 开关噪声源没和 bias/OTA 隔离
8. Current source + H-bridge 没形成线性驱动岛
9. I/Q 时钟从顶部散射 — 需要"时钟接口带"统一下送
10. 匹配关系 (mirror/pair/cascode) 没在 floorplan 级固化
11. pin-facing 方向没为 routing 优化 — stuck net 根因
12. 空白不能转化为有效通道 — 需定向通道，不是零散空地
13. 供电回流路径没在 floorplan 体现 — AVDD/DVDD/AGND/DGND
14. guard ring / well isolation 没预留
15. 输出端口没朝 pad 摆

## 5 岛重构方案

### 岛 1: 参考核心岛 (Reference Spine)
- PTAT core (PM3/PM4/MN1/MN2)
- Rptat + Rout
- Bias gen (PM_ref/MN_diode/MN_pgen/PM_pdiode/PM5)
- 位置: 中部，全芯片 bias 根
- 原则: bias 像树干往外分，不从角落互拉

### 岛 2: 量化前端岛 (Quantization Core)
- Chopper → OTA → Cfb → Strong-arm → SR latch → DAC feedback
- 紧贴参考核心，最短闭环
- 差分节点左右对称
- OTA 输出到 comp 直接相邻
- DAC 反馈走最短回路到 sum_n
- 极敏感，需隔离

### 岛 3: 驱动输出岛 (Drive Output)
- Programmable current source (cascode mirror + TG switches)
- Non-overlap clock generator
- H-bridge
- 靠近 probe pads (ua[0])，线性链: bias→casmir→H-bridge→pad
- 大电流回路与前端分区

### 岛 4: 数字时钟岛 (Digital Clock)
- VCO ring + buffer
- 7× TFF divider
- 3× MUX + output buffers
- 放单角 (右上或左上)，单独供电
- VCO 靠近 divider，远离模拟核心
- 时钟树在岛内闭合

### 岛 5: 接口带 (Interface Strip)
- Bitstream output buffer
- VPTAT test buffer
- Ref clock output buffer
- 靠边界，不穿核心

## 岛间接口 (仅 7 条跨区信号)

| 信号 | 从 | 到 | 规划 |
|------|----|----|------|
| f_exc / f_exc_b | 数字岛 | 驱动岛 + 量化岛 | 时钟接口带统一下送 |
| net_c1 | 参考岛 | 驱动岛 (casmir) | 直接相邻 |
| nmos_bias / pmos_bias | 参考岛 | 数字岛 (VCO) | 短 trunk |
| vco_out | 数字岛 | 数字岛内部 | 岛内闭合 |
| exc_out | 驱动岛内部 | 驱动岛内部 | 岛内闭合 |

## 诊断脚本重点 (针对 stuck nets)

不只看距离，要查:
1. pin 可达性: 周围可用 track 数、朝向、遮挡
2. 曼哈顿通道连续性: bbox 间是否有直通走廊
3. 高扇出控制网 (f_exc/bias/clock) 单独标红
4. connectivity-weighted 邻接图
5. pin density / boundary length 比值 heatmap

## 设计原则

- 功能块先组岛，岛间留定向通道
- pin-facing 决定块朝向，不是美观
- 匹配/对称在 floorplan 级固化
- 供电 trunk 和 floorplan 同步规划
- 数字时钟不穿模拟核心
- 大电流回路和敏感节点分区
- Rptat 不当墙 — 按电气关系决定位置
