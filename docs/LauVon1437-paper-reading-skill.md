# LauVon1437/paper-reading-skill 分析

> 仓库: https://github.com/LauVon1437/paper-reading-skill

## 1. 项目概述

面向 Codex Agent 平台的论文阅读 Skill。将 PDF 自动转换为图文并茂的中文阅读报告（MD+PDF）。

**核心特质**：将 orzorz1/AI-paper-reading 以 vendor 方式内嵌，LLM 推理全部交给 Codex，脚本只做确定性计算。

## 2. 核心思路

**"脚本做确定性，Agent 做语义"** 的极致实践：

- 脚本负责：PDF解析、版面检测、图表匹配裁剪、渲染、内容深度校验
- Codex Agent 负责：选关键图、解释图表、撰写中文报告正文
- 用户零配置，不需要 API Key

## 3. 架构设计

```
paper-reading-skill/
├── SKILL.md                          # Agent行为定义
├── scripts/paper_reading_agentic.py  # 自包含封装（~600行）
└── vendor/AI-paper-reading/          # vendor的orzorz1项目
    ├── pipeline/ (parser/layout/matcher/pdf_exporter)
    └── models.py
```

工作流：`doctor → analyze → [Codex选图+写作] → render`

## 4. 关键实现

- **三个输出级别**：short(1图) / medium(3图) / long(5图)，各有精确字符数/section门槛
- **三级 fallback**：layout模型 → 规则匹配 → caption关键词裁剪
- **质量门禁**：render阶段 `validate_content_depth` 做量化检查
- **content.json**：Agent和渲染器之间的唯一协议接口

## 5. 亮点

- vendor 策略：不依赖外部仓库，安装即用
- Agent 做 LLM 规避 API Key 分发问题
- 渐进降级保证可用性
- 自包含程度极高

## 6. 对我们的启发

| 维度 | 启发 |
|------|------|
| 分发策略 | vendor模式减少用户配置 |
| 分工模式 | Agent选图+写作，脚本做PDF/图片 |
| 质量门禁 | 硬性字数/section检查 |
| 渐进降级 | 多级fallback保证可用性 |
