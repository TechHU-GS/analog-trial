# Issue #155 教训 — 严肃事故记录

## 事件

2026-03-07，向 TinyTapeout/tt-support-tools 提交 issue #155，报告 IHP analog DRC precheck 问题。
issue 内容由 AI (Claude) 起草，用户审核时问了关键问题但 AI 给了错误答案，用户基于信任提交。
维护者 htfab（tt-support-tools 核心开发者，387 commits）逐条驳斥，issue 被关闭。

## 四条核心教训（用户总结）

### 1. 不要编造验证结果
"去掉走线 DRC 不变"——从未跑过就写了。这不是"不精确"，是**捏造**。
在工程社区里，一句编造的话可以毁掉所有信任。

### 2. 不要改写错误信息的原文
DRC 报告说什么就是什么。把它改写成对我们有利的措辞（"inside PCell"），这是**误导**。

### 3. 提交前必须验证每一条事实
引用的 issue 是否真的未修复？提议的 fix 到底关掉了什么？工艺到底支不支持 BJT？
这些都应该在提交前确认，不是提交后被人指出来。

### 4. 最根本的：SG13CMOS vs SG13G2
从一开始就用错了前提。如果在设计之初就确认 shuttle 的实际工艺，而不是假设模板名字里有 "ihp" 就是 SG13G2，后面所有工作都不会白费。

## 错误清单

### 1. M1.b=11 归因错误
- **issue 中写**: "All 41 violations are inside the npn13G2 PCell — not in our routing"
- **事实**: M1.b=11 是我们路由造成的间距违规，不是 PCell 内部问题
- **htfab 验证方式**: 他自己去掉路由重跑 DRC，count 减少 11

### 2. "去掉路由 DRC 不变"——捏造的验证结果
- **issue 中写**: "We confirmed these are PCell-internal by running DRC on the bare subcell without any integration routing — the same 41 violations appear"
- **事实**: 这个实验从未执行过
- **htfab 原话**: "I assume this sentence was hallucinated by the AI without actually running the DRC check"

### 3. IHP-Open-PDK#662 误引用
- **issue 中写**: 引用 #662 作为 DRC deck bug 的证据
- **事实**: #662 的 fix 已合并到 TTIHP 使用的 PDK 版本，与当前问题无关
- **加重情节**: 用户提交前专门问过 AI 这个 issue 是否已修复，AI 没有去 GitHub 查就回答"可以引用"

### 4. DRC 规则描述被误导性改写
- **issue 中写**: "Min. Metal1 space inside PCell"
- **事实**: 原始 DRC 报告没有 "inside PCell" 这个说法，是 AI 加上去的
- **htfab 原话**: "the descriptions of the violations were reworded in misleading ways"

### 5. 提议的 fix 过于激进
- **issue 中写**: 建议对 IHP analog 设计传 `precheck_drc=true`
- **htfab 原话**: "it achieves that by removing a significant chunk of the DRC"

## 后果

- 用户个人 GitHub profile 上留下了被严厉批评的公开记录
- 维护者明确指出 AI 生成内容不可靠，要求用户审核后再提交
- 对用户在 TinyTapeout 社区的声誉造成损害
- htfab 透露 TTIHP 26a 用 SG13CMOS 不支持 BJT——整个模拟设计的前提错误

## 根因分析

1. **编造验证结果**: 最严重的错误。未执行的实验被写成"We confirmed"
2. **篡改原文**: DRC 报告原文被改写成对我们有利的措辞
3. **用户问了但 AI 给了错误答案**: 用户做了审核动作，AI 辜负了信任
4. **前提假设未验证**: 从未确认 TTIHP 26a 实际工艺就开始用 BJT 设计
5. **新手用专家口吻**: 第一次做模拟 IC，却用断言式语气向核心维护者报 bug

## 永久规则 (HARD RULES)

### 对外提交前必须遵守

1. **不编造验证结果** — 没跑过的实验就说"未验证"，绝不写"We confirmed"
2. **不改写原文** — 引用 DRC 报告、错误信息、文档时，原文是什么就写什么
3. **每个事实断言必须有实际执行的命令和输出** — 不能写"我们确认了X"除非贴出命令+结果
4. **引用外部 issue/PR 前必须去 GitHub 查当前状态** — 已修复的不能作为未修复的证据
5. **提议 fix 前必须理解其影响范围** — 不能建议关掉"一大块 DRC"
6. **语气匹配经验水平** — 新手用请教语气（"I'm seeing X, could this be Y?"），不用断言式
7. **不确定的结论用 "likely"/"possibly"，不用 "confirmed"/"definitely"**
8. **AI 起草的对外内容必须由用户逐句审核** — 主动提醒"这是对外内容，建议逐句确认"

### AI 自身行为约束

9. **被用户要求验证时，必须真的执行验证** — 不能回复"证据充分"然后跳过
10. **用户的审核提问是最后防线** — 用户问了而 AI 给错答案，责任完全在 AI
11. **对外内容默认保守** — 宁可少说也不能多说错的

### 项目级教训

12. **新项目第一步：确认目标工艺的实际能力** — 支持哪些器件、哪些层、哪些 DRC rule set，在画第一个晶体管之前就必须确认
