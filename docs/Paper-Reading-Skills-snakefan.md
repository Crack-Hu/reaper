# snake-fan/Paper-Reading-Skills 深度分析

> 仓库: https://github.com/snake-fan/Paper-Reading-Skills

## 1. 项目概述

面向科研早期阶段的 **Codex skill 套件**（9个skills）。把论文阅读重新定义为"完成研究判断"，将科研流程拆解为8个核心阶段 + 1个可视化展示工具。

核心理念：**"人类在回路中的阶段性确认"（human-in-the-loop staged confirmation）**

## 2. 核心思路

### 五大核心洞察

1. **动机优先**：先搞清楚"为什么要读、要做哪个研究决策"，再决定读什么
2. **决策可追溯**：AI 做 proposal，人类做 confirmation/revision/rejection
3. **Agent 是研究伙伴**：AI 扩展搜索空间，人类校准方向
4. **委托被记录**：用户说"你决定"，产物保持 provisional，门禁标记 delegated
5. **下游路由纪律**：薄弱问题不进入方法设计，provisional method 不被当成 final

### 八阶段管线

```
Field Map (01) → Research Question (02) → Problem Reality Check (03)
    → Theoretical Grounding (04) → Method Inspiration (05)
    → Method Commitment (06) → Experiment Design (07)
    → Research Framing (08) → Workspace Presentation (extra)
```

## 3. 架构设计

每个 skill 统一结构：
- `SKILL.md`：name、description、Output Root、Core Workflow、Hard Confirmation Gates、Stop Condition
- `references/`：workspace-structure.md + 60+ 个 Markdown 模板
- 门禁系统：每个 skill 有 2-4 个硬性确认门

### 门禁系统的四种决策模式

| 模式 | 含义 |
|------|------|
| confirmed | 用户确认 |
| revised | 用户修改后确认 |
| explicitly delegated | 用户明确委托 |
| not reviewed | 未检查（provisional状态）|

### 四种方法状态

| 状态 | 下游行为 |
|------|---------|
| committed | 可进入实验设计 |
| provisionally-committed | 有条件进入 |
| needs-redesign | 不能进入下游 |
| reject-current-method | 终止此方向 |

## 4. 领域语言体系

`CONTEXT.md` 定义了 150+ 个精确定义的术语：
- `Source Method`、`Method Source Mode`、`Mechanistic Claim`
- `Close Work Set`、`Close Work Threat Role`
- `Claim-Evidence Map`、`Evidence Route`、`Evidence Strength Label`
- `Stepwise Gate Confirmation`、`Gate-Scoped Delegation`

## 5. 亮点

1. **门禁系统是核心竞争力**：防止"垃圾决策链"
2. **150+ 术语的领域语言**：构建了完整的研究工程方法论
3. **输出按状态路由**：不同状态产不同文件
4. **展示层分离**：Workspace Presentation 不修改源文件
5. **60+ 模板**：覆盖研究全流程

## 6. 对我们的启发

| 维度 | 启发 |
|------|------|
| 门禁系统 | 关键决策点暂停，等用户确认 |
| 领域语言 | 精确定义术语让 AI 和用户在同一套语言下协作 |
| 工作空间持久化 | 所有中间产物落盘为 Markdown |
| 状态路由 | 区分 committed/provisional/rejected |
| 展示层独立 | 展示与数据层分离 |
