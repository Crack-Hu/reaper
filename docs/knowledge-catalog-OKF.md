# knowledge-catalog (GoogleCloudPlatform) OKF 深度分析

> 仓库: https://github.com/GoogleCloudPlatform/knowledge-catalog  
> 核心关注: okf/ 目录 — Open Knowledge Framework

## 1. 项目概述

knowledge-catalog 包含两个核心：

1. **Open Knowledge Format (OKF)** — 人与 agent 均友好的知识表示规范 (v0.1)。核心理念：如果我能 `cat` 一个文件就读懂知识，如果我能 `git clone` 就分发知识。

2. **Reference Agent** — 基于 OKF 规范的知识生成 agent，能从 BigQuery 元数据和 Web 文档自动构建知识库。

## 2. 核心思路：如何让 agent 掌握知识

### 三层架构

**第一层 — 知识的"形状"约定**

一切知识建模为 **Concept**（概念文档）。每个 Concept 是一个 `.md` 文件：
```yaml
---
type: Paper
title: Attention Is All You Need
description: Proposes the Transformer architecture...
resource: https://arxiv.org/abs/1706.03762
tags: [nlp, transformer, attention]
timestamp: 2026-01-01T00:00:00Z
---
# Markdown 正文...
```

**第二层 — 知识的组织结构**

```
bundle/
├── index.md              # 渐进式索引
├── datasets/
│   ├── index.md
│   └── <dataset>.md
├── tables/
│   ├── index.md
│   └── <table>.md        # 含完整 Schema
└── references/
    ├── metrics/           # 指标定义（带SQL）
    └── joins/             # Join路径（带ON子句）
```

**第三层 — 知识的注入路径（两阶段）**

**Pass 1 — 结构化元数据提取**
- `list_concepts()` → 列出所有概念
- `read_concept_raw()` → 获取源元数据（schema + 采样）
- `read_existing_doc()` → 检查已有文档
- `write_concept_doc()` → 生成 OKF 文档

**Pass 2 — Web 知识增强**
- Agent 爬取 Web 文档
- 三种决策：增强已有 Concept / 创建新 Reference / 跳过
- 严格防护：max_pages、allowed_hosts、depth、Schema保护、Citation保护

### 关键设计模式

1. **工具即能力**：5个 FunctionTool 暴露给 LLM
2. **Prompt 引导**：严格的步骤式工作流（不是让 Agent 随意探索）
3. **安全防护层**：write_concept_doc 内嵌多层校验
4. **渐进式索引用 LLM 合成**：用 Gemini 为每个子目录生成摘要

## 3. 在文献阅读场景的应用分析

### 概念映射

| OKF 原本 | 文献阅读场景 |
|----------|------------|
| BigQuery Dataset | 文献集合（领域/期刊） |
| BigQuery Table | 单篇论文 |
| Schema 字段 | 论文的关键发现、方法、指标 |
| Reference (metric) | 领域内指标定义 |
| Reference (join) | 论文间引用关系、方法对比 |

### 建议的文献 OKF 结构

```
literature_bundle/
├── index.md
├── domains/
│   └── nlp/papers/
│       ├── index.md
│       └── attention_is_all_you_need.md
└── references/
    ├── metrics/    (bleu.md, rouge.md, perplexity.md)
    ├── datasets/   (imagenet.md, squad.md)
    ├── architectures/ (transformer.md, resnet.md)
    └── comparisons/   (transformer_vs_lstm.md)
```

### 单个论文 Concept 结构

```markdown
---
type: Paper
title: Attention Is All You Need
description: Proposes the Transformer...
tags: [nlp, transformer, attention]
---

# Overview / Key Contributions / Method / Results / Comparisons / Citations
```

### 两阶段知识注入（文献场景）

**Pass 1 — 论文元数据抽取**：list_papers → read_metadata → read_full_text → write_concept_doc

**Pass 2 — 交叉引用增强**：search_papers → get_citations → fetch_web → enrich existing concepts

## 4. 可直接复用的设计原则

1. **渐进式披露**：index.md 让 agent 按需加载知识
2. **交叉链接作为知识图谱**：Markdown 链接表达关系
3. **结构化 + 自由文本**：frontmatter 可索引 + body 自由
4. **增量增强**：先有基础信息，逐步添加解读
5. **防护层**：Schema/Citation 保护防止知识丢失
6. **Git 原生**：PR review、版本对比、协作编辑
7. **无供应商锁定**：OKF 不绑定任何模型或框架

## 5. 对 reaper 的建议

1. **直接采纳 OKF 规范**作为知识表示层
2. **参考两阶段模式**：第一阶段从论文源提取，第二阶段从 citation 网络增强
3. **复用渐进式索引**：让 agent 按需加载而非一次塞所有论文
4. **利用 viz.html**：生成论文引用关系图谱

## 6. 总结

Google 的核心思路：

> **知识 = 结构化元数据（frontmatter）+ 自由文本（markdown body）+ 交叉链接（知识图谱）**

Agent 掌握知识的方式：
1. 定义通用格式（OKF）
2. 用 agent 自身作为生产者（两阶段）
3. 严格的 Prompt 工作流引导
4. 工具封装限操作界面
5. 渐进式索引避免过载

**Agent 既是知识的消费者，也是知识的生产者**，OKF 是它们之间的桥梁。
