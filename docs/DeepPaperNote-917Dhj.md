# DeepPaperNote (917Dhj) 深度分析报告

> 分析时间：2026-07-20  
> 仓库地址：https://github.com/917Dhj/DeepPaperNote  
> Stars: 226+ | Version: v2.1.0

---

## 1. 项目概述

DeepPaperNote 是一个运行在 LLM Agent 中的**证据驱动单论文深度阅读技能**，通过 "15 步确定性流水线 + 模型理解写作" 的协作范式，将论文转化为高质量、可长期复用的 Obsidian 笔记。

---

## 2. 核心思路

### 2.1 总体设计哲学：Evidence-First（证据优先）

所有分析输出必须能**回溯到原文具体位置**。模型从完整 PDF 原始文本阅读，不是从摘要生成摘要。这解决了 LLM 分析论文时的幻觉问题。

### 2.2 Source Corpus 概念

将 PDF 完整提取后建立结构化的 `source_corpus`（包含全部文本 + 章节索引 + 图表映射），作为下游所有分析任务的**唯一数据源**。

---

## 3. 架构设计

### 3.1 双层架构

```
Platform Adapter Layer (SKILL.md + agents/*.yaml + plugin.json)
        |
Reusable Core Layer
  ├── Pipeline: resolve → collect → fetch → extract → evidence → assets
  │             → figures → decisions → bundle
  ├── Contracts: 笔记章节、论文类型(5种)、Note Plan、图表规则
  ├── Quality: lint_grounding.py → lint_note.py → quality_review → readability_review
  └── Output: write_obsidian_note.py (Obsidian YAML + 11 fixed sections)
```

### 3.2 核心模块

- **Pipeline**: 15 步确定性流水线
- **Contracts 契约系统**: 结构化 JSON 定义所有输出规范
- **Quality 质量门禁**: 三层递进检查

---

## 4. 实现方式

### 4.1 Scripts + Model 分工

确定性工作交给脚本，理解/判断/写作交给模型。这与 huicod/paper-reading-skill 的理念一致但实现更系统化。

### 4.2 Contracts 契约系统

用结构化 JSON 定义：
- 笔记章节规范
- 论文类型适配（5种类型各有不同结构）
- Note Plan 规划规则
- 图表处理规则

### 4.3 三层质量门禁

1. **Grounding** - 每句陈述是否可回溯到原文？
2. **Lint** - 格式和结构是否符合契约？
3. **Review** - 内容深度和连贯性评估？

### 4.4 Placeholder-First 图表策略

文本正确性优先于图片完整性。图表处理失败时用占位符标记，不做错误的图片匹配。Fail-closed 而非强行插入。

---

## 5. 接口/使用方式

通过 Claude Code/Cursor 等 Agent 平台加载 SKILL.md 使用。输入 PDF 路径，输出 Obsidian 格式的结构化笔记。

---

## 6. 亮点与特色

| # | 设计模式 | 核心价值 |
|---|---------|---------|
| 1 | **Evidence-First + Source Corpus** | 模型从完整 PDF 原始文本阅读，不是从摘要生成摘要 |
| 2 | **Scripts + Model 分工** | 确定性工作交给脚本，理解/判断/写作交给模型 |
| 3 | **Contracts 契约系统** | 用结构化 JSON 定义所有输出规范、论文类型适配、质量门禁 |
| 4 | **三层质量门禁** | Grounding → Lint → Review，层层递进确保输出质量 |
| 5 | **Placeholder-First 图表策略** | 文本正确性优先于图片完整性，fail-closed 而非强行插入 |

---

## 7. 对我们项目的启发

1. 实现 **Source Corpus** 概念——完整文本 + 结构化索引作为下游唯一数据源
2. 用 **TypeScript** 实现类似 `contracts.py` 的契约系统
3. 设计 **Note Plan + Grounding** 机制——先规划再写作，规划需验证
4. 采用 **渐进式质量门禁**——grounding（来源）→ lint（格式）→ review（深度）
5. 保持 **Core + Adapter 双层架构**，核心逻辑与平台解耦
