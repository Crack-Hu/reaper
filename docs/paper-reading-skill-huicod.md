# huicod/paper-reading-skill 深度分析报告

> 分析时间：2026-07-20  
> 仓库地址：https://github.com/huicod/paper-reading-skill  

---

## 1. 项目概述

### 1.1 是什么

`huicod/paper-reading-skill` 是一个面向 **Gemini Code Assist / Antigravity** 平台的论文阅读 Skill（`.agents/skills/` 系统）。它不是一个独立应用，而是一套可被 AI Agent 加载并执行的工作流定义，配合 Python 脚本和 Markdown 模板，将论文 PDF 转化为结构化的阅读产出。

### 1.2 解决什么问题

| 痛点 | 解决方案 |
|------|---------|
| PDF 难以直接交给 AI 处理 | Phase 1: MinerU API 将 PDF 转为 Markdown + 提取图片 |
| 英文论文阅读门槛 | Phase 2: 全文逐段翻译为中文（非摘要、非压缩） |
| 读论文没方法、效率低 | Phase 3: 生成"三遍阅读法"结构化指南 |
| 读完不知如何系统总结 | Phase 3: 生成 What/Why/How 研究员级报告 |
| AI 产出质量不可控 | Phase 4: 自动化脚本质量抽检（6 项量化检查） |

---

## 2. 核心思路

### 2.1 总体方法论：四阶段流水线

```
PDF 论文
  → Phase 1: PDF → Markdown (MinerU API 在线批量转换)
  → Phase 2: 全文翻译 (AI 逐段翻译，保持 Markdown 结构)
  → Phase 3: 阅读指南 + 报告 (三遍阅读法 + What/Why/How 报告)
  → Phase 4: 质量抽检 (Python 脚本自动检查 + 修复循环)
```

### 2.2 "三遍阅读法"——方法论核心

| 遍次 | 名称 | 时间 | 目标 | 产出 |
|------|------|------|------|------|
| 第一遍 | 速读 | 15-20 min | 掌握全貌：做了什么、为什么、什么结论 | "核心理解"总结 |
| 第二遍 | 通读 | 45-60 min | 理解论证逻辑、方法框架、实验设计 | "技术洞察"总结 |
| 第三遍 | 精读 | 60-90 min | 深入技术细节，达到"能复现"的理解深度 | "深度评价"总结 |

### 2.3 断点续传设计

通过 `progress.json` 追踪每个论文目录的执行状态，支持跨多次对话的论文阅读流程。

---

## 3. 架构设计

### 3.1 目录结构

```
paper-reading-skill/
├── SKILL.md                          # 核心：Agent 完整行为定义
├── README.md                         # 安装/使用说明
├── install.ps1                       # PowerShell 安装脚本
├── scripts/
│   ├── mineru_convert.py             # PDF → Markdown（MinerU API v4）
│   └── quality_check.py              # 6项自动化质量检查
└── templates/
    ├── reading_guide_template.md     # 三遍阅读法指南标准结构
    └── report_template.md            # 7章节研究报告标准结构
```

### 3.2 关键架构决策

**AI + 脚本混合架构**——确定性任务由脚本处理，语义任务由 AI 处理：

| 脚本负责（确定性） | AI 负责（语义性） |
|-------------------|-------------------|
| PDF 格式转换（MinerU API） | 全文翻译 |
| 文件完整性检查 | 阅读指南生成 |
| 章节结构对比 | 研究报告撰写 |
| 图片路径验证 | QA 答案撰写 |

---

## 4. 实现方式

### 4.1 mineru_convert.py

与 MinerU API v4 交互的 4 步流程：
1. 申请上传 URL (`POST /api/v4/file-urls/batch`)
2. 上传 PDF (PUT presigned_url)
3. 轮询解析结果（最长 10 分钟）
4. 下载 ZIP → 解压 → 标准化 (`_normalize_output()`)

### 4.2 quality_check.py

6 项自动化检查，有明确容差阈值：文件完整性、章节结构对比、图片引用验证、段落数量抽检、阅读指南结构、研究报告结构。

### 4.3 模板设计

- **reading_guide_template.md**：目标 + 时间 + 阅读清单(带§标注) + 概念解读 + 自检QA(折叠答案) + 本遍总结
- **report_template.md**：What/Why/How + 实验设置 + 实验结果 + 优势与局限 + 个人评价

---

## 5. 接口/使用方式

```powershell
git clone https://github.com/huicod/paper-reading-skill.git .agents/skills/paper-reading
.\install.ps1 -WorkspaceRoot (Resolve-Path ..\..\..\..)
$env:MINERU_API_TOKEN = "your-token-here"

# 在对话中使用
/paper-reading docs/my_paper.pdf
```

输出目录结构：
```
paper_reading/{paper_name}_{timestamp}/
├── original.pdf
├── progress.json
├── markdown/full.md + images/
├── translated/full_cn.md
├── reading_guide.md
└── report.md
```

---

## 6. 亮点与特色

1. **方法论工程化**：将 KESHAV 三遍阅读法转化为可被 Agent 执行的工作流
2. **递进式理解深度**：三遍阅读对应三个递进的理解层次
3. **断点续传**：progress.json 支持跨多次对话的长流程
4. **AI + 脚本职责分离**：确定性任务和语义任务边界清晰
5. **模板驱动 + 自由生成**：结构规范而不限制内容深度
6. **质量闭环**：Phase 4 的 6 项量化检查形成质量保障
7. **安全设计到位**：API Key 隔离、日志脱敏

---

## 7. 对我们项目的启发

### 可直接借鉴
- **阶段化流水线 + progress 文件**：论文处理拆分为可恢复的独立阶段
- **模板驱动输出**：模板定义结构规范，AI 负责内容生成
- **AI + 脚本混合架构**：确定性操作用脚本，语义理解用 AI
- **质量抽检机制**：每阶段配套自动化检查脚本

### 可改进方向
- 翻译策略优化：数学推导和代码段应保留原文
- 缺少多论文对比维度
- 缺少知识图谱支持
- 平台绑定过强

### 对 reaper 的具体建议
1. progress.json 机制追踪每篇论文的处理状态
2. 模板 + AI 生成模式做报告产出
3. 质量检查脚本为每个处理阶段提供质检
4. 多阶段流水线：获取 → 解析 → 分析 → 对比 → 综述
5. 三遍阅读法融入报告生成
6. 安全实践参考：API Key 隔离、日志脱敏
