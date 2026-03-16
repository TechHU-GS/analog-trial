---
name: Rout ECO Lesson
description: IHP rppd polyres_drw blocks MOSFET extraction — physical placement fix, not layer clipping
type: feedback
---

# Rout ECO Lesson (2026-03-13)

## 根因

rppd PCell (Rout 电阻) 放置在 x=36.32 时，其 polyres_drw (128/0) 弯折线穿过 PM3/PM4 MOSFET Activ 区域。
PDK LVS 推导链: `psd_fet = pactiv.and(nwell_drw).interacting(pgate).not(pgate).not_interacting(res_mk)` —
只要 psd_fet 与 polyres_drw **相交**，`.not_interacting(res_mk)` 就排除整个 S/D region。

## 错误路径 (浪费大量 token)

1. 先以为是 salblock_drw (28/0) 阻塞 → 尝试 flatten rppd + clip salblock/extblock
2. Flatten 破坏了 rppd 电阻提取 (46 ports instead of 2)
3. 即使 clip 成功，polyres_drw 仍然阻塞 — salblock 只是 mos_exclude 16 层之一
4. 根因是 **物理布局冲突**，不是标记层问题

## 正确修法

局部 placement ECO: 只移动 Rout 到无冲突 X 窗口 (x=10.0)。
- `diagnose_rout_placement.py` 扫描了合法窗口: x=10-22.5µm, x=74-88.5µm
- 移动后 PM3/PM4 立即恢复 (124/124 PMOS), rppd 提取也正常 (1/1)
- DRC 回退到 188 (全部信号重布线)，但这是可重做的

## 教训

1. **物理冲突不能靠裁剪标记层解决** — 如果实体 poly 穿过 MOSFET 区域，任何层操作都只是骗 LVS
2. **mos_exclude 有 16 个层** — 修 salblock 后还有 polyres、extblock 等层层阻塞
3. **局部 placement ECO 是高杠杆操作** — 和"开 M3/M4"同级别，一步到位解决根因
4. **DRC 回退是可接受的代价** — 物理正确性 > DRC 表面数字
5. **flatten PCell 破坏提取** — KLayout PCell 需要 cell 边界内的标记层结构，flatten 后丢失

## PDK LVS 关键推导链

```ruby
res_mk  = polyres_drw.join(res_drw)                                    # line 54
tgate   = gatpoly.and(activ).not(res_mk)                               # line 65
psd_fet = pactiv.and(nwell_drw).interacting(pgate).not(pgate).not_interacting(res_mk)  # line 75
mos_exclude = pwell_block.join(nsd_drw).join(trans_drw).join(emwind_drw)
             .join(emwihv_drw).join(salblock_drw).join(extblock_drw)
             .join(polyres_drw).join(res_drw)...                        # line 26-29
```

## 前置预检 (防止再犯)

在 placement 完成后、routing 前，应检查:
- 所有 rppd/rhigh PCell 的 polyres_drw/salblock_drw 范围
- 是否与任何 MOSFET Activ/GatPoly 区域有几何交叠
- 使用 `diagnose_rout_placement.py` 扫描合法 X 窗口
