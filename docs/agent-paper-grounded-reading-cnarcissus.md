# agent-paper-grounded-reading (c-narcissus) 深度分析

> 仓库: https://github.com/c-narcissus/agent-paper-grounded-reading

## 1. 项目概述

面向本地 AI Agent（Codex、Trae、Claude Code 等）的**论文精读 Skill 包**，双重目标：

- **Grounded Auditability**：每个报告结论都能回查到原始证据
- **Research-Generative**：从论文中挖掘新的研究 idea

核心创新：把论文读作"隐藏的设计轨迹"而非"成品说明书"。

## 2. 核心思路

### 双重方法论

| 层次 | 目标 | 方法 |
|------|------|------|
| Grounded Auditability | 每个结论可回查 | claim ID → evidence row → paragraph anchor |
| Research-Generative | 挖掘新研究 idea | Research Equation: 旧成功 + 破缺假设 + 借来工具 → 替代机制 |

### 15 步工作流

```
组装源码 → 准备LaTeX/PDF → 提取段落锚点 → 撰写25节报告 
→ 填写traceability_manifest → 填写research_lens → 验证追溯性
→ 构建静态Reader → 启动本地HTTP服务
```

## 3. 架构设计

双层架构：
```
Platform Adapter (SKILL.md + agents/*.yaml + plugin.json)
        ↓
Reusable Core (scripts/ + templates/ + references/ + assets/)
```

三层定位系统（按优先级降级）：
1. SyncTeX（LaTeX行号 → PDF坐标）
2. PDF fallback（locator_snippets + PyMuPDF搜索）
3. 段落块扩展（命中行 → 包含段落）

## 4. 实现亮点

- **完整的可追溯性体系**：claim ID → evidence row → paragraph anchor 三层结构
- **Research-Generative 方法学**：broken assumption / surrogate mechanism / story pattern 分析框架
- **静态 Evidence Reader**：889行JS构建的交互式论文精读页面（PDF高亮+claim联动）
- **MathML 渲染**：latex2mathml + sanitize + validate 流水线
- **校验链**：traceability → pdf snippets → reader math 三层质量保证
- **本地优先**：不需要外部API

## 5. 对我们的启发

| 维度 | 可复用内容 |
|------|-----------|
| 可追溯性架构 | claim ID + evidence row + paragraph anchor 三层结构 |
| Research-Generative 方法学 | 整个"破缺假设→替代机制→故事模式"框架 |
| 产物标准化 | JSON Schema / template 定义所有产物格式 |
| Evidence Reader | 左右分栏 + PDF高亮 + claim联动交互模式 |
| 源获取策略 | arXiv LaTeX > 用户LaTeX > PDF 优先级链 |
| Skill 包设计 | AI指令 + 脚本 + 模板 + 前端 打包模式 |
