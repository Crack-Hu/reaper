# paper-notes (ZinSheng) 深度分析

> 仓库: https://github.com/ZinSheng/paper-notes

## 1. 项目概述

面向 AI Agent（Codex/Claude Code）的**论文精读 Skill**，将 Zotero 文献管理 + AI 精读 + 可编辑 HTML 页面 + 阅读仪表盘整合成一条完整工作流。

**核心填补的空白**：Zotero 的 `zotero.py` CLI 无法读取 PDF 标注，paper-notes 解决了这个问题。

## 2. 核心思路

### 五阶段流程

```
init (首次设置) → add (添加论文) → generate summary (LLM生成摘要)
    → build dashboard (构建仪表盘) → sync edits (浏览器编辑同步)
```

### 三大设计哲学

1. **证据优先**：LLM 只读取 PyMuPDF 提取的文本，不看 PDF 图片，避免多模态幻觉
2. **用户编辑始终胜出**：AI 生成的是"初稿"，用户在浏览器里的修改永不被覆盖
3. **可脱离 Zotero**：通过 `--manual` 模式零依赖运行

## 3. 架构设计

```
skills/paper-notes/
├── SKILL.md                    # 27KB Agent Skill 规范
├── assets/
│   ├── paper_template.html     # 61KB 单篇论文 HTML
│   ├── dashboard_template.html # 32KB 仪表盘 HTML
│   └── fonts/                  # 自托管离线字体
├── references/
│   ├── summary_schema.md       # 11KB JSON Schema (v4 证据感知版)
│   ├── annotation_fields.md    # Zotero 标注字段映射
│   └── troubleshooting.md
├── scripts/
│   ├── _common.py              # 18KB: Zotero API v3、config、manifest
│   ├── manage_reading_list.py  # 34KB: 核心编排
│   ├── fetch_annotations.py    # Zotero 标注抓取
│   ├── extract_figures.py      # PDF 图片提取
│   ├── extract_sections.py     # PDF 正文提取
│   ├── build_paper_html.py     # 31KB: 单篇渲染
│   └── build_dashboard.py      # 13KB: 仪表盘渲染
└── examples/
```

## 4. 关键实现

- **三层证据区分**：论文直接报告 → 证据支持 → 仍为假设
- **浏览器 ↔ JSON 双向同步**：contenteditable + localStorage + File System Access API
- **9 种论文类型分类**：empirical/theory/method/benchmark/dataset/survey/system/replication/other
- **阅读时间估算**：标注时间戳聚类 + 诚实标注局限性
- **三级 PyMuPDF 解释器发现**：环境变量 → 托管 venv → sys.executable
- **硬约束门控**：`init` 未完成则 `add` 直接 exit code 3

## 5. 亮点

1. 证据优先管道：LLM 只看提取文本
2. 用户编辑 merge 策略：`.edits.json` 持久化 + 重新生成时合并
3. 代码级门控强制执行
4. 完整产品闭环：SKILL.md + 脚本 + HTML + 参考文档
5. 自托管字体 + 离线可用
6. 仪表盘可视化（GitHub 风格 heatmap + collection 树）

## 6. 对我们的启发

| 维度 | 启发 |
|------|------|
| 证据管道 | AI 输入严格限定在 Python 预处理后的结构化文本 |
| 编辑合并 | edits.json 解决"AI生成 vs 用户修改"矛盾 |
| 配置门控 | 代码级强制 init 先于 add |
| 前端能力 | contenteditable + localStorage + File System Access API |
| 分类体系 | 9种论文类型 × 各自阅读引导策略 |
| 仪表盘 | heatmap + collection树 可视化聚合 |
| 阅读时间 | 标注时间戳推算，诚实标注局限 |
