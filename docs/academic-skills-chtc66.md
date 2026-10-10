# academic-skills (chtc66) 深度分析报告

> 分析时间：2026-07-20  
> 仓库地址：https://github.com/chtc66/academic-skills

---

## 1. 项目概述

这是一个面向 **中文科研工作流** 的 ChatGPT Skills 集合，8 个 skill 覆盖从"发现论文→精读→综述→benchmark抽取→gap分析→实验总结→审稿回复→周报"的完整闭环。目标用户是 AI/NLP/LLM 方向的研究生和科研工程师。

---

## 2. 核心思路

### 2.1 方法论的三大支柱

- **可串联的工作流**：8 个 skill 不是孤立工具，而是按研究流程自然串联
- **严格的证据约束**：每个 skill 都有"证据与表述约束"，禁止编造、标注边界、区分证据/推测
- **模板驱动的结构化输出**：所有输出都由 `references/` 中的模板驱动

### 2.2 8 个 Skill 概览

| Skill | 功能 | 输入 | 输出 |
|-------|------|------|------|
| paper-discovery | 发现相关论文 | 研究兴趣 | 论文列表+分类 |
| paper-deep-read | 深度阅读单篇 | PDF/URL | 结构化笔记 |
| paper-survey | 综述多篇论文 | 论文集合 | 综述文档 |
| benchmark-extraction | 抽取benchmark信息 | 论文 | 标准化benchmark表 |
| gap-analysis | 分析研究空白 | 综述 | gap报告 |
| experiment-summary | 实验总结 | 实验记录 | 实验报告 |
| review-response | 审稿回复 | 审稿意见+论文 | 回复草稿 |
| paper-feishu-digest | 飞书论文速递 | arxiv ID | 飞书消息 |

---

## 3. 架构设计

### 3.1 统一四层结构

```
skill-name/
  SKILL.md          # 定义层: 工作流、规则、约束
  agents/openai.yaml # 配置层: display_name、default_prompt
  references/       # 模板层: 输出模板、判断标准、分类法
  scripts/          # 执行层: 确定性 Python 脚本
```

### 3.2 设计特点

- **SKILL.md 设计模式**：声明式规则 + "何时读引用文件"的跳转机制，让 AI 按需加载上下文
- **层层引用**：SKILL.md 保持短而清晰，详细模板在 references/ 中按需加载

---

## 4. 实现方式

### 4.1 arxiv_digest.py

唯一确定性脚本。使用规则推断（纯关键词匹配）而非 LLM 来做评分、贡献推断、局限判断。零外部依赖。

### 4.2 validate_repo_structure.py

声明式结构校验，用字典定义期望文件树，自动化检查防止仓库腐烂。

### 4.3 package_all_skills.py

批量打包为 zip 供 ChatGPT Skills 上传。

### 4.4 证据约束体系

- 信息来源分级
- 用"未知"替代猜测
- 证据/推测二分标注
- 每个 skill 都有"证据与表述约束"章节

---

## 5. 使用方式

- 本地打包后上传到 ChatGPT Skills 使用
- arxiv_digest.py 支持命令行独立运行，可输出 Markdown/JSON/飞书 Webhook
- GitHub 协作流程：独立分支→先改 references/→改 SKILL.md→补 scripts→PR→校验+打包

---

## 6. 亮点与特色

1. **系统化证据约束**：这是最大特色。"仅基于摘要判断""未知"作为合法字段、证据/推测二分——直接回应 AI 幻觉问题
2. **可串联工作流**：从发现到产出形成闭环
3. **可校验工程规范**：声明式校验防止仓库腐烂
4. **规则 vs. LLM 分离**：arxiv_digest.py 纯规则推断，结果可复现
5. **LLM 优化的文档组织**：SKILL.md 短而清晰，按需跳转 references
6. **学术场景深度适配**：review_taxonomy（8 种 concern 分类）、tone_guidelines（改写原则）、comparison_dimensions（四维比较框架）

---

## 7. 对我们项目的启发

1. **分层设计范式**：AI Skill = SKILL.md + references/ + scripts/ + agents/
2. **证据约束体系**：信息来源分级、用"未知"替代猜测、证据/推测二分
3. **模板驱动+工作流编排**：每步骤独立模板，SKILL.md 作为"宪法"
4. **规则与 LLM 分离**：确定性部分用脚本，LLM 保留给深度语义
5. **声明式校验**：用字典定义结构，自动化检查
6. **组件串联思维**：模块独立但可按流程组合
7. **领域深度适配**：为目标领域建立分类法、比较维度和写作模式
