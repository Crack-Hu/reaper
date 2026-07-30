# Reaper — 科研文章阅读工程 路线图

> 一个多模态论文输入 → 结构化解析 → AI翻译 → 中英对照阅读 → LLM对话 的全流程系统

---

## 整体架构

```
输入层                   解析层                  处理层                 展示层
┌──────────┐     ┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│ arxiv链接 │ ──> │ ar5iv HTML (现成) │ ──> │ 段落结构化提取 │ ──> │ 中英对照HTML   │
│ PDF文档   │ ──> │ MinerU 解析      │ ──> │ LLM 翻译      │     │ 术语可编辑     │
│ 网页资料  │ ──> │ 直接提取文本     │ ──> │ 术语字典管理   │     │ (可存入Zotero) │
│ Tex源码   │ ──> │ 编译+解析       │     │               │     │               │
└──────────┘     └──────────────────┘     └──────────────┘     └──────────────┘
                                                                    │
                                                              第四部分 (暂缓)
                                                              ┌──────────────┐
                                                              │ LLM 梳理文章  │
                                                              │ LLM 对话理解  │
                                                              │ 引用溯源验证  │
                                                              └──────────────┘
```

---

## 四个部分

### 第一部分：整理文章（Paper Ingestion）
**目标**：将不同来源的论文统一为结构化的中间格式（HTML/MD + 图片/表格）

| 来源 | 方案 | 状态 |
|------|------|------|
| arxiv (LaTeX源码) | 直接使用 ar5iv 的 HTML | ✅ 当前阶段 |
| PDF | MinerU 解析 → MD/JSON | 🔲 后续 |
| 网页 | 直接提取文本 | 🔲 后续 |
| Tex 源码 | 编译 → HTML 或直接解析 | 🔲 后续 |

### 第二部分：翻译（Translation）
**目标**：结合语境逐段落翻译，维护术语字典

- 段落级翻译（保持上下文连贯）
- 术语字典：`{"sub-agent": "子代理", "attention": "注意力"}`
- 支持 LLM API 调用
- 字典可编辑、可持久化

### 第三部分：浏览（Reading View）
**目标**：生成中英对照的可交互 HTML

- 左侧原文 / 右侧译文（段落对齐）
- 术语高亮 + 点击可修改翻译
- 修改自动保存回术语字典
- 参考 ar5iv 样式，保持学术感
- **可行性评估**：ar5iv 使用 LaTeXML 生成的 class 命名体系（`ltx_section`, `ltx_para`, `ltx_figure` 等），DOM 结构清晰，CSS 样式独立。在其上叠加自定义功能（术语高亮、编辑弹窗、中英对照）完全可行，只需注入额外的 JS/CSS 层。

### 第四部分：LLM 交互（暂缓）
**目标**：LLM 帮助理解和讨论文章

- 文章结构梳理 / 核心观点提取
- 基于引用的问答（不会捏造）
- 调用上述流程了解新内容

---

## 当前阶段：Phase 1 — arxiv 快速通道

**范围**：给定 arxiv 链接/ID → 生成中英对照 HTML

### 实现步骤

```
arxiv ID (如 2401.04268)
    │
    ▼
┌─────────────────────┐
│ 1. fetcher.py       │  构造 ar5iv URL，下载 HTML
│    arxiv → ar5iv    │  https://ar5iv.labs.arxiv.org/html/{id}
└────────┬────────────┘
         │ raw HTML
         ▼
┌─────────────────────┐
│ 2. parser.py        │  解析 ltx_* 类名，提取结构化段落
│    HTML → blocks[]  │  保留: 标题层级、段落文本、公式、图表引用
└────────┬────────────┘
         │ blocks (list of dict)
         ▼
┌─────────────────────┐
│ 3. translator.py    │  逐段落调用 LLM 翻译
│    blocks → zh_text │  应用术语字典替换
└────────┬────────────┘
         │ translated blocks
         ▼
┌─────────────────────┐
│ 4. renderer.py      │  生成中英对照 HTML
│    → output.html    │  左侧原文、右侧译文、术语可点击编辑
└─────────────────────┘
```

### 文件结构

```
reaper/
├── roadmap.md              # 本文件
├── reaper/
│   ├── __init__.py
│   ├── fetcher.py          # 获取 ar5iv HTML
│   ├── parser.py           # 解析段落
│   ├── translator.py       # LLM 翻译 + 术语字典
│   ├── renderer.py         # 生成中英对照 HTML
│   ├── dictionary.py       # 术语字典管理 (CRUD)
│   └── config.py           # 配置 (API keys, 路径等)
├── dict/
│   └── default_terms.json  # 默认术语映射
├── main.py                 # CLI 入口
└── output/                 # 输出目录
```

### 术语字典格式 (`dict/default_terms.json`)

```json
{
  "autonomous underwater vehicle": "自主水下航行器",
  "reinforcement learning": "强化学习",
  "attention mechanism": "注意力机制"
}
```

---

## 后续扩展

### Phase 2：PDF 支持
- 集成 MinerU (API/CLI/SDK 三种模式)
- 统一输出为与 ar5iv 兼容的中间格式
- 复用 Phase 1 的翻译和渲染

### Phase 3：渲染增强
- 图表单独展示
- 公式 MathJax/KaTeX 渲染
- 移动端适配

### Phase 4：LLM 交互
- 文章自动梳理
- 基于引用的问答
- 对话历史管理

---

## ar5iv HTML 结构分析

ar5iv 使用 LaTeXML 将 LaTeX 转为 HTML，class 命名规范：

| 元素 | CSS Class | 说明 |
|------|-----------|------|
| 文档容器 | `ltx_document` | 顶层 article |
| 标题 | `ltx_title` | 论文标题 |
| 摘要 | `ltx_abstract` | Abstract |
| 章节 | `ltx_section` | Section 标题 |
| 段落 | `ltx_para` | 正文段落 |
| 公式 | `ltx_Math` / `ltx_equation` | 数学公式 |
| 图表 | `ltx_figure` / `ltx_table` | 图片和表格 |
| 引用 | `ltx_cite` / `ltx_ref` | 参考文献引用 |
| 参考文献 | `ltx_bibitem` | 文献条目 |

**结论**：ar5iv HTML 结构清晰，易于解析，适合作为第一阶段的输入源。
