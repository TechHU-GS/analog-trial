# analog-trial 版图规则 (强制)

## ATK Workflow 强制执行

完整 Workflow 定义: `layout/atk/WORKFLOW.md`

### 当前 Phase

查看 Memory 文件 `memory/atk_phase_state.md` 获取当前 Phase 和 Gate 状态。

### 禁止操作

1. **禁止跳过 Gate**: Phase N 的 Gate checklist 全部通过后才能进入 Phase N+1
2. **禁止跨 Phase 修改**: 当前 Phase = N 时，不得修改 Phase N+1 的产物文件
3. **禁止打地鼠**: 同一类 DRC violation 连续 3 次微调 → 必须停止，退后分析根因
4. **禁止魔数**: 所有 DRC 数值必须从 pdkdb.json / pdk.py 引用，不可硬编码
5. **禁止 ad-hoc 修改**: 每次修改必须说明属于哪个 Phase、满足哪条 Gate 约束

### Phase 文件所有权

| Phase | 可写文件 | 只读文件 |
|-------|---------|---------|
| 0 | atk/data/*.json, atk/pdk.py | - |
| 1 | netlist.json | Phase 0 产物 |
| 2 | placement.json, solve_placement.py | Phase 0-1 产物 |
| 3 | tie 相关代码 | Phase 0-2 产物 |
| 4 | routing 相关代码, l2_autoplace.py | Phase 0-3 产物 |
| 5 | 无 (只验证) | 所有 |

### 回退规则

DRC violation 分类后按类型回退:
- NW.b1/tie 空间不足 → 回 Phase 2
- LU/NBL/tie M1 冲突 → 回 Phase 3
- M1.b/M2.b routing → 回 Phase 4
- CntB.h1 PCell 内部 → waiver (IHP #662)

回退时必须更新 Memory 中的 Phase 状态。

### 数学模式 vs 惯性模式

| | 惯性模式 (禁止) | 数学模式 (要求) |
|---|---|---|
| 方法 | 改→跑→看→改 | 提取规则→建模→证明→改一次 |
| 判断 | "试试看" | "数学上保证" |
| 结果 | 不收敛 | 根治 |

遇到 DRC violation 时：
1. 提取所有相关 DRC 规则值到 pdkdb.json
2. 提取所有相关几何形状（PCell probe）
3. 用数学证明根因
4. 计算参数值使约束全满足
5. 一次修改到位

### 执行入口

```bash
cd /Users/techhu/Code/GS_IC/designs/analog-trial/layout
source ~/pdk/venv/bin/activate
bash run_all.sh
```

**不要直接跑 assemble_gds.py 或单独跑 DRC。用 run_all.sh。**
