# Reaper Chat — 产品计划（讨论稿）

> 把 Reaper 从「生成双语 HTML」扩展为「能用 AI 读懂这篇论文」。
> 目标：在 Zotero 里选中一段话，就能围绕它和 agent 对话；agent 手上有这篇论文的 TeX 源码。

---

## 1. 背景

现有 Reaper 已经解决了「把论文变成可读的双语 HTML」：

- 三来源获取（ar5iv / arxiv.org/html / ar5ivist Docker）
- LaTeXML HTML 解析 → `Block` 序列（带 `data-reaper-id` 锚点）
- 按章节 LLM 翻译 + 双层术语表 + 缓存
- 渲染成自包含 HTML，作为附件存进 Zotero

**缺的是「理解」这一环。** 读论文时的真实需求不是「翻译」，而是：

- 「这个公式在说什么？」
- 「他这里说的 baseline 和我熟悉的那篇有什么关系？」
- 「这个方法的关键假设是什么？在什么情况下会失效？」
- 「第 3.2 节的推导我没看懂，帮我拆开」

这类问题需要**围绕论文的对话**，而且需要**论文本身作为依据**（不能凭空编）。

### 与市面产品的差异点

调研了两个参考产品，都只做到一半：

| | alphaXiv | little-alphaxiv | **Reaper（计划）** |
|---|---|---|---|
| 上下文来源 | PDF 逐页抽取文本 | PDF 全文注入 system prompt | **LaTeX 源码**（公式/宏/结构精确） |
| 长文策略 | 长上下文 + 页面过滤检索 | 全文不分块注入 | **大纲入 prompt + agent 按需 read/grep** |
| 引用解析 | ❌ 无 | ❌ 无 | ✅ **`\cite` → 被引论文全文** |
| 段落级选中 | 有（PDF 划线） | 有（选中提问） | 有（**带 block 锚点，可回查 TeX**） |
| 与文献管理器整合 | 无官方集成 | 有（Zotero 笔记同步） | ✅ **原生 Zotero 插件** |

**核心机会：我们是唯一「TeX-grounded + 引用可追溯」的方案。** PDF 抽取文本拿不到宏定义、拿不到被截断的公式、拿不到 `\cite` 到参考文献的精确映射。

---

## 2. 范围

### ⭐ 架构铁律（先读这一条）

**pi 是引擎，我们的插件只是 UI。**

| 职责 | 归属 |
|---|---|
| LLM 调用 / 工具循环 / 重试 / 超时 | **pi** |
| 会话管理（创建、持久化、分支、压缩） | **pi** |
| 上下文管理 / compaction / 历史截断 | **pi** |
| 模型选择 / provider 认证 | **pi** |
| 系统提示词 / 工具定义 / skill | **pi**（通过 `--append-system-prompt` 与扩展） |
| 面板渲染 / 消息展示 / 输入框 / 流式显示 | **我们** |
| 论文数据准备（TeX、blocks.json、大纲） | **我们** |
| Zotero 集成（附件、选中、笔记） | **我们** |

**明确不做**：不自己写 LLM 循环、不自己写工具框架、不自己写流式客户端、不自己建会话存储、不自己写压缩逻辑。

> 调研的参考项目（little-alphaxiv、zotero-ai-sidebar、llmz、paper-chat-for-zotero 等）**各自造了一套简易 agent 框架**。那些部分是**反面教材**，一律不抄。
>
> **但「省 token 的策略」要抄** —— 只不过实现方式不同：它们写在自建循环里，我们写成 **pi 扩展工具**，循环由 pi 跑。

### 面板形态

- **主要形态**：Zotero 侧边栏窗格（item pane section）—— 参考 `yilewang/llm-for-zotero`
- **次要形态**：独立的可浮动窗口，与侧边栏共用同一套 DOM —— 参考 `syt2/paper-chat-for-zotero`
- 用一个 `panelMode` 偏好切换，面板状态（草稿、引用）在切换时保留

### 本期做

1. **pi 桥接服务** —— Python 拉起 `pi --mode rpc`，JSONL ↔ SSE
2. **论文上下文准备** —— TeX 落盘 + 大纲生成 + system prompt
3. **Zotero 对话面板** —— 扩展现有插件，item pane / reader 侧栏
4. **选中段落提问** —— 从 Zotero reader 选中 → 面板（带结构锚点）
5. **引用解析**（差异化功能，Phase 3）

### 本期不做

| 项 | 原因 |
|---|---|
| **多窗口 / 多客户端同步同一会话** | 需要额外开发；等 pi 新版的多客户端能力（`pi-client` 已有 `acquireSession` 租约设计，但当前 CLI 无 server 模式） |
| TUI 镜像 | 同上；且 `pi --session <id>` 的「交接式」恢复已够用 |
| PDF 来源支持（非 arXiv） | 与 `roadmap.md` 的 Phase 2 合并，不在本期 |
| 术语面板 UI 恢复 | 优先级低于对话 |

---

## 3. 架构

### 通信层次（两张网，不要混）

```
┌─ Zotero 插件（JS）──────────┐
│  只能发 HTTP 请求，            │
│  不会 spawn 子进程           │
└────────────┬────────────────┘
             │
             │  ★ HTTP + SSE
             │    请求发起方：插件
             ▼
┌─ Reaper 服务器（Python）─────┐
│  管 pi 进程的生老病死         │
│  将 pi 的事件广播给订阅者     │
└────────────┬────────────────┘
             │
             │  ★ RPC / JSONL over stdio
             │    命令：服务器→pi；事件：pi→服务器（主动推）
             ▼
┌─ pi agent ──────────────────┐
└─────────────────────────────┘
```

**为什么是这两种（都不是自由选，是被两端能力逼出来的）**：
- **插件 ↔ 服务器 = HTTP**：插件是 JS，跨进程通信最自然的就是 HTTP；且我们对这个模式已有成熟用法（`/api/generate` 等）
- **服务器 ↔ pi = stdio RPC**：pi **只提供这一种**（无 serve 命令、无 HTTP/WS 模式），源码只有 `interactive` / `print` / `rpc` 三种模式

### HTTP 那一段的两种姿势（照 pi 自己的设计）

| 端点 | 姿势 | 用途 |
|---|---|---|
| `POST /api/chat` | 普通一问一答，**立刻返回「已接收」** | 发消息 |
| `GET /api/chat/stream` | **SSE**（连接不关，持续吐） | 接收流式回复 |
| `POST /api/chat/abort` | 普通一问一答 | 中断 |

**为什么用「先接受 + 另开流」而不是一个阻塞请求**：不会桂一个巨大请求；中途断线重连不丢消息。这正是 pi 自己 `prompt` 命令的语义。

### ⚠️ 两个实现陷阱

1. **RPC 是双向但不对称**：服务器→pi 发**命令**；pi→服务器推**事件**（主动推，不一定回应某个命令）。所以服务器侧必须有一个**常驻读取线程**盯 pi 的 stdout，否则会出现「发出去的消息没回复」。
2. **一个 pi 进程只能有一个 stdout 读取者**：服务器是多路复用器——统一读、再广播给所有 SSE 订阅者。**不能让每个 SSE 连接各读各的**（两个标签页就会互相抢）。

```
插件（论文 A 面板）──SSE──> 服务器 ──> pi 进程 A
插件（论文 B 面板）──SSE──> 服务器 ──> pi 进程 B
```

### 数据流（论文处理，现有）

```
┌─ Zotero ────────────────────────────────────────────────┐
│  bootstrap.js（现有）                                    │
│    ├─ 菜单：Download / Generate / Complete Resources     │
│    └─ 【新】ItemPaneManager.registerSection("reaper-chat")│
│                                                          │
│  content/chat.xhtml + chat.js（新）                      │
│    └─ 对话面板：消息列表 + 输入框 + 流式渲染              │
└──────────────────────┬───────────────────────────────────┘
                       │ fetch + SSE
                       ▼
┌─ Reaper Python Server (src/server.py) ──────────────────┐
│  现有端点：/api/generate /api/clear /api/terms           │
│            /api/zotero_html/{id}                         │
│  【新】/api/chat/* ──── src/chat/                        │
│                          ├─ session.py   进程注册表      │
│                          ├─ pi_bridge.py JSONL ↔ 事件广播│
│                          └─ context.py   TeX → prompt    │
└──────────────────────┬───────────────────────────────────┘
                       │ subprocess, JSONL over stdio
                       ▼
┌─ pi agent（每篇论文一个进程）────────────────────────────┐
│  pi --mode rpc                                           │
│     --session-dir data/chat/{arxiv_id}/                  │
│     --append-system-prompt <论文大纲>                     │
│     --tools read,grep,find,ls                            │
│  cwd = data/chat/{arxiv_id}/workspace/  ← TeX 在这里     │
│                                                          │
│  扩展（新）：resolve_citation 等论文专用工具              │
└──────────────────────────────────────────────────────────┘
```

**关键点**：论文的 TeX **放在 agent 的工作目录里**，而不是全部塞进 context。agent 用 `read`/`grep` 按需查。

---

## 4. 关键设计决策（需要一起讨论）

### D1. pi 进程模型

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. 每篇论文一个进程 | 上下文隔离；崩溃不影响其他论文 | N 个进程 |
| B. 全局单进程多会话 | 省资源 | 会话切换复杂；一篇论文的上下文污染可能串味 |
| C. 每次对话新建，用完销毁 | 最简单 | 每次都要重新加载论文上下文 |

**建议：A + 空闲回收。** 实测启动只需 0.17s，懒加载成本可忽略。

- 首次提问时 spawn，按 `arxiv_id` 缓存
- 空闲 15 分钟自动回收（可配置）
- 会话持久化在 `data/chat/{arxiv_id}/`，下次用 `--session <id>` 恢复，不丢历史

> **待确认**：一篇论文要不要支持**多个对话**（比如"方法"一个、"实验"一个）？这会变成 (论文 × 会话) 的注册表。建议 Phase 1 先做「一篇论文一个持续对话」，简单且符合直觉。

### D2. 论文上下文怎么给 agent（最重要的一决策）

三种做法：

| 做法 | 说明 | token 成本 |
|---|---|---|
| (a) 全文注入 | `--append-system-prompt paper.tex`，像 little-alphaxiv 那样 | 高，且长论文会爆 |
| (b) 预处理后注入 | 去注释/preamble/宏定义，保留正文 | 中 |
| (c) 大纲进 prompt + 全文放工作目录 | agent 用 `read`/`grep` 按需查 | 低 |

**建议：(c) + 少量 (b)** —— 这正是 agentic 的正确用法：

**system prompt 里放**（小）：
- 论文标题、作者、摘要
- 章节大纲（我们有现成的 `Block` 层级）
- 术语表（复用 `TermDictionary`）
- 一段说明：「完整 LaTeX 源码在工作目录 `paper.tex`；`blocks.json` 是段落索引，每个段落有 `id` 对应渲染 HTML 里的 `data-reaper-id`；用户提问时若指定了段落 id，去 `blocks.json` 查它的上下文」

**工作目录里放**（大，agent 自己读）：
- **`paper.md` —— 主上下文**（从 blocks 生成）
    - 带 `<!-- block:N -->` 锚点 → 与渲染 HTML 的 `id="reaper-block-N"` **同一套编号**
    - 公式还原为 `$...$`（来自 `<annotation encoding="application/x-tex">`）
    - 标题层级天然对应 section 结构
    - **字节稳定**（无时间戳、无不稳定排序）→ 能命中 prompt cache
- `blocks.json` —— 段落索引：`[{id, type, level, text, sentences[], math[]}]`
- `paper.tex` —— **可选**（仅两类用途：① 解析 `\newcommand` 做宏展开；② 引用解析）
- `paper.bbl` —— **可选**，引用索引（Phase 3）
- `metadata.json` —— arxiv id、标题、来源类型、cleanerVersion

#### 为什么主上下文是 `paper.md` 而不是 `paper.tex`

| 维度 | LaTeXML HTML → paper.md | LaTeX 源码 |
|---|---|---|
| **锚点同一性** | ✅ block id 就是用户看到的那个 | ❌ block id → TeX 位置**不是平凡映射**（LaTeXML 会拆并段落、重排公式） |
| 数学精度 | ✅ `<annotation>` 就是作者写的原始 LaTeX | ✅ |
| 体积 | ✅ 173K 字符（同一篇论文，原 HTML 纯文本的 **67%**） | 更大（preamble + 格式命令） |
| 结构 | ✅ 已线性化 | ⚠️ 需处理 `\input{}` 内联 |
| 我们是否已有 | ✅ **生成双语 HTML 的必经路径** | ❌ 额外下载 |
| 可用性 | 三来源（ar5iv/arxiv.org/html/ar5ivist）；都失败时 fallback 是**自己编译 LaTeX** | `e-print` 总是有东西，**但可能是 PDF 而非源码** |

**锚点同一性是决定性论据**，因为它直接服务于「选中段落提问」这个第一号需求。

#### 公式：用 annotation + TeX 宏展开，**不做 MathML→LaTeX 转换**

**已验证**：`<math>` 元素同时带两个东西，且 LaTeXML **内部已经展开了宏**：

```
① annotation（原始源码）  \absolutevalue*{\bias{\est{O}}}
② MathML 内容（展开后）   | Bias[ Ô ]        ← \est{O} → \hat{O}，\bias → Bias
```

做法：

| 优先级 | 来源 | 用途 |
|---|---|---|
| **主** | annotation + 解析 TeX 的 `\newcommand`/`\def` 做**字符串替换** | 给 agent 读 |
| **校验** | MathML 展开结果 | ✅ 用来验证我们展开对了没 |
| 降级 1 | annotation 原样（宏名保留） | TeX 不可用 |
| 降级 2 | MathML → LaTeX 转换 | **不做**，仅理论兜底 |

**为什么不做转换**：宏展开是**字符串替换**（简单、可预测、失败时降级温和——宏名通常自解释）；转换是**语义重建**（复杂，且失败时会**静默产出错误的 LaTeX**，agent 会误读）。

> 同一篇论文实测有 22 个非标准命令，其中真正的作者自定义宏约 7 个（`\absolutevalue`/`\order`/`\outerproduct`/`\sign`/`\bias`/`\est`/`\mean`），且大多名字自解释。

**为什么这样更好**：
- agent 能**精确定位**（「§3.2 公式 12」→ grep 到，读到周围上下文）
- 选中段落时给个 id 就行，不用把全文塞进每条消息
- 上下文留给对话本身，而不是论文的宏定义

> **待确认**：agent 会不会因为「懒得查」而凭记忆编造？需要在 Phase 0 验证 prompt 措辞。可能需要明确要求「回答前必须引用你读到的原文位置」。

### D3. 选中段落机制（已用 Zotero 9.0.6 源码验证）

**结论：能精确拿到段落，而且不需要在附件 HTML 里写 JS。**

Zotero 把 `text/html` 附件当作 **snapshot** 类型放进内置 reader（`item.js:3264-3278`：`text/html → 'snapshot'`）。snapshot 与 PDF/EPUB 共用同一套选区弹窗代码，会派发 `renderTextSelectionPopup`。

插件拿到的 payload 里，`params.annotation` 包含：

```js
{
  type, color, sortIndex, text,
  position: { type: 'CssSelector', value: '<唯一 CSS 选择器>', refinedBy? }
}
```

**`params.annotation` 的精确形状**（W3C Web Annotation Data Model 子集，已实测验证）：

```js
{
  type: 'highlight',
  text: '<innerText(range).trim()>',               // ⚠️ 不能用来算偏移
  position: {
    type: 'CssSelector',
    value: '#reaper-block-7 > span:first-child',   // ⚠️ 不一定就是 #id！
    refinedBy: { type: 'TextPositionSelector', start: 42, end: 62 }
  }
}
```

| # | 事实 | 影响 |
|---|---|---|
| 1 | **`refinedBy` 就是字符偏移** `{start,end}`，单个对象，从不为数组 | ⭐ **第三级锚点免费** —— 不需要模糊文本匹配 |
| 2 | `position.value` **可能是 `#id > span:first-child`**（选区最近元素是内联元素时） | ⚠️ **不能假定整个 value 就是 id**；要取前导 `#id` 并映射到最近的 `[id^="reaper-block-"]` 祖先 |
| 3 | 偏移是 **UTF-16 code unit**（非规范说的 code point），相对**选择器匹配元素的 `textContent`**（拼所有文本节点 `nodeValue`），`[start,end)` 左闭右开 | ✅ 可复现；⚠️ 我们的 HTML 里**中文译文也在 textContent 里** |
| 4 | 选择器由 `getUniqueSelectorContaining()` 生成，**优先用 `id`**，保证全局唯一 | ✅ 我们的 `id="reaper-block-N"` 方案成立 |
| 5 | 只生成 `CssSelector + TextPositionSelector`；`TextQuoteSelector` **从不**生成 | 没有 prefix/suffix 可用 |
| 6 | Zotero **没用 Hypothes.is**，是 `zotero/reader` 自研的 `selector.ts`/`unique-selector.ts` | 以后读源码找对地方 |
| 7 | 选择器描述的是**原始保存的结构**（focus/reading 模式会经 `NodeMapping` 映射回去） | ✅ **可以在 Python 侧对我们自己生成的那份 HTML 做解析**，不需碰 reader 私有 API |

#### 解析算法（已从 Zotero 9.0.6 源码逐字提取）

拿到 `{CssSelector, refinedBy}` 后，Zotero 是这样还原选区的：

```js
function textPositionToRange(selector, root) {
  let iter = root.ownerDocument.createNodeIterator(root, NodeFilter.SHOW_TEXT);
  let pos = 0;
  for (let node of iter) {
    if (!node.nodeValue) continue;
    let so = selector.start - pos, eo = selector.end - pos;
    if (so >= 0 && so <= node.nodeValue.length) range.setStart(node, so);
    if (eo >= 0 && eo <= node.nodeValue.length) range.setEnd(node, eo);
    pos += node.nodeValue.length;
  }
}
```

**四个决定性事实**：

| # | 事实 | 影响 |
|---|---|---|
| 1 | 游走是该元素下**所有文本节点按文档序**（`SHOW_TEXT`），**包括 `<script>`/`<style>`/隐藏/空白节点**，只跳过空串 | 必须完整复现，不能过滤 |
| 2 | 偏移是 **UTF-16 code unit**，`[start,end)` | ⚠️ **Python 必须按 UTF-16 切片**（`text.encode('utf-16-le')[2*s:2*e]`），按 code point 会让 emoji 错位 |
| 3 | 偏移存在 **`preBody` 坐标系**，与显示无关 | ✅ **解析我们自己的附件就能复现选区**，即使 Reading Mode 改写了 DOM |
| 4 | Zotero 加载时会 `DOMParser` → **删 `<base>`/`<noscript>`** → 注入 CSP meta → 序列化成 `srcdoc` → **再解析一次** | ⚠️ 复现时必须用**浏览器等价**的 HTML5 解析器 |

#### 实现位置：**插件侧 JS，不是 Python**

第 4 点意味着 Python 侧需要 HTML5 严格兼容的解析器（foster-parenting、隐式 `<tbody>`、`<template>` 排除、实体解码），而 `lxml` 不一致。两个选择：

| 方案 | 代价 |
|---|---|
| Python 侧解析 | 引入 `html5lib`+`bs4`+`soupsieve`，仍有解析器偏差风险 |
| ✅ **插件侧 JS 解析** | **`DOMParser` 是真浏览器 DOM，零偏差、零依赖、零私有 API** |

**流程**：插件读附件文件（`item.getFilePathAsync()` + `IOUtils.readUTF8`）→ `DOMParser` → `querySelector(position.value)` → 跑同一套文本游走 → 得到精确文本 + block id → POST 给服务器。

#### ⭐ 扩展桥：用 pi 扩展补上 RPC 缺失的命令

**发现**：`/tree` 的**导航**（`ctx.navigateTree`）在 RPC 协议里**没有对应命令**（38 个 RPC 命令全核对过），只存在于 SDK 和 **`ExtensionCommandContext`**。

**但是**：扩展命令**可以**通过 RPC 的 `prompt` 调用（rpc.md 原文："Extension commands: Execute immediately, even during streaming"）。

所以 `pi-extensions/reaper-tree.ts`（通过 `pi --extension <path>` 加载）提供：

| 命令 | 作用 | RPC 原生有？ |
|---|---|---|
| `/goto <entryId> [summary]` | **移动活跃分支**（/tree 导航） | ❌ → 扩展补上 |
| `/label <entryId> <text>` / `/unlabel <entryId>` | 节点标签 | ❌ → 扩展补上 |
| `/where` | 报告当前 leaf | ❌ → 扩展补上 |

**结果回传**：扩展用 `ctx.ui.notify()`，在 RPC 模式下作为 `extension_ui_request`（method=`notify`）出现在 stdout，前端直接显示。

> **这是一个通用模式**：pi 的 RPC 表面并不完整，但**扩展命令是 RPC 可达的**。以后遇到「TUI 能做但 RPC 没暴露」的功能，都可以用这个桥——**不需要引入 SDK 或 Node 服务**。

**已验证**：`/goto` 使 leaf 从 `cffd1276` 移到 `5a3dd5e8`，并收到 notify `"moved to e2520d3d"`。

##### 这个缺口是已知的（官方 issue 调研）

| Issue / PR | 状态 | 内容 |
|---|---|---|
| **pi #8645** `RPC: expose navigate_tree` | **closed（no-action）** | 与我们**完全相同**的请求。作者 `cfpperche` 维护另一个 GUI 客户端 [PiCode](https://github.com/cfpperche/picode)。原话：*"GUI clients can render the tree from `get_tree`, but a click cannot do what TUI `/tree` does. Mapping the click to `fork` changes behavior: new JSONL instead of switching the leaf in the current file."* / *"We do not want to invent a private leaf-pointer in the JSONL."* ⚠️ **关闭原因是机器人自动关新贡献者的 issue，不是维护者否决** |
| **pi #5119** `Expose session tree and tree navigation in RPC` | closed | 拆成了两部分：读侧落地（#5810），**写侧（导航）至今没做** |
| **pi #5810** `get_entries` / `get_tree` | ✅ 已实现（#6078 by @geraschко） | 所以 `get_tree` 能用，但只能**看** |
| **pi #5932** `exposing ctx.navigateTree() to agents` | — | 别人也撞上了同一个限制：`navigateTree` 只在 `ExtensionCommandContext` 上 |
| **pi #7295** `Expose ExtensionAPI.navigateTree` | — | 要求把导航提到扩展工厂 API |
| **oh-my-pi #10026** | **open** | 一个 fork 在 PR 里实现 `get_tree` + 导航树 |
| **dnouri/pi-coding-agent #242** | open | Emacs 插件同一个问题：*"only supports fork (creating a new session), not tree navigation"* |
| **pi-mono PR #1762** | — | "adds five new RPC commands that close that gap" |

**结论**：缺口是真的，已有多人提过。**但没有人给出「扩展命令桥」这个解** —— PiCode 的现状是 *"`/tree` is a viewer; clicking a user prompt calls `fork`"*，也就是**他们只能用 fork 代替导航**。我们的 `--extension` + `/goto` 方案比他们的变通更进一步，而且不用改架构。

##### ⚠️ 同样从 issue 里挖到的陷阱（已加防护）

**pi #5096**：*"Tool results get wrong parentId when /tree navigation happens during tool execution"*

- **触发**：工具执行中导航 → tool result 被挂到错误的 `parentId` → **会话树损坏**
- **后果**：provider 报错 `unexpected tool_use_id found in tool_result blocks`
- **维护者 badlogic 的指导意见**：*"we should disallow structural operations, i.e. operations that operate on the tree, during streaming… user would have to manually abort before invoking those commands. same already applies for /reload."*
- **我们的防护（两层）**：
  1. 扩展侧：`requireIdle(ctx)` — `ctx.isIdle()` 为假时拒绝并提示
  2. API 侧：`_busy(bridge)` — `get_state().isStreaming` 为真时返回 409

> 所以**运行中不能点「跳到这里」**——这不是保守，是 pi 已知的会损坏数据的行为。

#### ⚠️ 已验证的另一个坑：`--session` 静默失败

**`--session` 指向不存在的路径时，pi 会静默开启新会话**（不报错）。后果看起来就是「我的历史消失了」——正是用户抱怨的历史分叉。

已在 `PiBridge.__init__` 加防护：路径必须绝对且存在，否则**拒绝启动**。

#### 需要支持的 CSS 选择器语法

`#id`、`>`、`+`、`:first-child`、`:first-of-type`、`:last-child`、`:last-of-type`、`:only-child`、`:only-of-type`、`:nth-child(n)`（**只数元素兄弟**）。

> 生成算法的唯一性保证是**隐式的**：解析时用 `querySelector`（取第一个匹配）且**不重新校验**——重复 id 会静默绑定到第一个。

> **9.0.6 vs master 差异**：`selector.ts`/`unique-selector.ts`/`moveRangeEndsIntoTextNodes` 三者**完全相同**。master 已无 `_readingMode`，直接用 `_iframeDocument.body.querySelector()` 且不做映射。用户跑的是 9.0.6 的 preBody 规则。

> `moveRangeEndsIntoTextNodes` **只在生成侧调用**，所以收到的偏移已包含它的调整（去首尾 `\n`、Firefox+Windows 会丢一个尾随空白），**直接照着用即可**。

#### 三级锚点

```
① block 级   从 position.value 的前导 #id 取出     →  reaper-block-142
② 字符级     refinedBy.start / end（免费拿到）    →  块内 [42, 62)
③ 句子级     用②的区间查预计算的句子边界          →  第 3 句
```

#### ⚠️ 必须处理的边界情况

| 情况 | 表现 | 处理 |
|---|---|---|
| **只读库** | `!item.isEditable()` → 弹窗**根本不渲染**，事件不派发 | UI 上明确告知，或提供手动粘贴入口 |
| 选区跨多个元素 | `position.value` 指向 `commonAncestorContainer`（可能是包裹 div），偏移相对它整个 textContent | 用**完整选择器**而非只取 `#id`，再向上找最近的 block |
| 找不到唯一选择器 | 降级为裸 `TextPositionSelector`，相对 `document.body` | 也要能处理 |
| 整元素被选中 | `refinedBy` **缺失** | 视为整块 |
| astral 字符（emoji） | UTF-16 vs code point 不符 | 罕见；记录并容错 |

> **需要的渲染器改动**：现在只有 section 标题有 `id="reaper-sec-{N}"`，段落只有 `data-reaper-id="{N}"`。要给**每一个 block 都加 `id="reaper-block-{N}"`**（选择器生成器优先用 `id`）。

插件侧：
```js
Zotero.Reader.registerEventListener("renderTextSelectionPopup", (e) => {
  const { reader, params, append } = e;
  append({ label: "问 Reaper", onCommand() { /* 用 params.annotation.position.value 取出 block id */ } });
}, "reaper@github.io");
```

#### ⚠️ 同时确认的两件事

**1. 附件 HTML 里的 JS 不会执行。** reader 用嵌套 iframe 加载内容，`sandbox` 只加了 `allow-same-origin` 和 `allow-modals`；`allow-scripts` 仅在 `platform !== 'zotero'` 时添加，而 `createReader` 强制 `platform = 'zotero'`。加上 CSP 的 `script-src 'unsafe-eval'`（不含普通脚本）和 `srcdoc` 加载方式。

> **影响**：我们现有的 `toc-toggle.js`（TOC 侧栏 ☰、主题切换 ☾、译文开关）**在 Zotero 内置 reader 里很可能完全不生效**，只有在外部浏览器打开时才工作。**这一点需要你确认**（你实际用过）。
>
> 如果确实不生效，两条路：(a) 主要阅读场景改成外部浏览器，Zotero 只做管理；(b) 把 TOC/主题控件改成 CSS-only（`<details>` 折叠、`:target` 锚点、`prefers-color-scheme`），不依赖 JS。

**2. 已知边界情况**（都来自源码）：
- 条目在**只读库**中（`!item.isEditable()`）→ 弹窗不渲染、不派发事件
- **跨 block 选择**可能让选择器生成器返回 `null` → 无弹窗无事件
- snapshot 的 reading mode 若开启可能影响选择器映射（默认关闭）

#### 逃生通道（万一 `position` 不可靠）

Zotero 自己就用 `reader._internalReader._primaryView._iframeWindow` 操作 snapshot 内容窗口（`reader.js:2285-2289`）。所以插件可以在 handler 里读：
```js
reader._internalReader._primaryView._iframeWindow
      .getSelection().anchorNode.closest('[data-reaper-id]')
```
属于私有 API，作为兜底而非主路径。

**面板里的呈现**：
```
┌────────────────────────────────────┐
│ 📌 正在讨论 §3.2 第 2 段            │  ← 可点 × 取消
│ > "the decoding problem is..."      │
├────────────────────────────────────┤
│ 你：这里的 NP-hard 是指什么？        │
│ AI：……                              │
└────────────────────────────────────┘
```

### D4. 流式协议

**建议 SSE**（`text/event-stream`），不用 WebSocket。

理由：
- pi RPC 本身是单向事件流，SSE 语义吻合
- 发送用普通 POST，中断用 POST `/api/chat/abort`
- 不需要处理 WS 握手/重连

**Zotero 侧注意**（来自此前调研的实证）：
- ⚠️ **不要用 `Zotero.HTTP.request`** —— 它基于 XHR，无法流式，只能整段返回
- ✅ 用沙箱 `fetch()` + `resp.body.getReader()` 逐块读
- ⚠️ **不要在 reader 的 frame 内发请求** —— reader 注册了 `BlockingObserver`，会取消该 frame 的所有 http(s) 请求。请求必须从插件作用域（item pane section 的 JS）发起

### D5. 工具策略与安全

**这是本期最重要的安全决策。**

论文正文是**不可信输入**。`docs/security.md` 明确说 pi 不自带沙箱，**且 RPC/text/json 模式不显示信任提示**——agent 跑 bash 不会问任何人。所以论文里的 prompt injection 可以直接变成 shell 命令。

| 阶段 | 策略 |
|---|---|
| Phase 1 | `--tools read,grep,find,ls`（**只读白名单**，已实测可用）。够用：读 TeX、查 blocks、定位公式都是只读 |
| Phase 3 | 加**审批 UI**：用 pi 的 Extension UI 协议把 `confirm` 对话框隧道到 Zotero 面板。要写扩展，但这是官方支持的正路 |
| 备选 | 容器化（`docs/containerization.md` 有 Docker / Gondolin micro-VM / OpenShell 三种模式） |

> 明确一下：**Phase 1 不做审批 UI**，只靠只读白名单。这样即使被注入，agent 也改不了任何文件。

### D6. 模型与认证 —— 直接用 pi 现有配置

**不做任何配置统一。** pi 有它自己的认证和 provider 配置，那是用户的事，我们不管。

我们只做两件事：
1. spawn `pi --mode rpc`，**不传** `--provider` / `--model` / `--api-key`（除非用户显式要求）
2. 如果将来需要「换个模型聊天」，暴露一个可选的 `--model` 透传参数即可

**职责边界**：Reaper 负责「通信 + UI」，pi 负责「模型 + 工具 + 会话」。端点是否可达、key 是否有效，都是 pi 自己的事（用户能跑 pi 就说明配好了）。

### D7. 会话与数据存储

```
data/chat/{arxiv_id}/
├── workspace/            ← agent 的 cwd
│   ├── paper.tex
│   ├── paper.bbl
│   ├── blocks.json
│   └── metadata.json
└── sessions/             ← pi --session-dir
    └── <session>.jsonl
```

- 用我们自己的目录（不是 `~/.pi/agent/sessions/`），便于 `/api/clear` 一起清理
- `/api/clear?arxiv_id=X` 要扩展成同时清 chat 数据

### D8. 面板挂在哪个位置

**用 `Zotero.ItemPaneManager.registerSection()`**（Zotero 7 API）。

关键收益：**同一个 section 自动出现在 PDF 阅读器的 context pane**——「PDF 右边就是聊天栏」是官方行为，零 hack。

- `header.l10nID` / `sidenav.l10nID` 必填，需要 `.ftl` 文件
- `onRender` 必须同步；重活放 `onAsyncRender`
- section 会被销毁重建，**状态不要放 DOM**，`onDestroy` 里清 notifier

---

## 5. 分期计划

### Phase 0 — 执行计划（spike）

> **执行进度**（2026-09-11）
>
> | 步骤 | 状态 | 产物 |
> |---|---|---|
> | **S1** 论文上下文准备 | ✅ 完成并验证 | `src/chat/context.py`（349 行） |
> | **S2** pi 桥 | ✅ 完成（协议层已验） | `src/chat/bridge.py` + `session.py` |
> | **S3** SSE 端点 | ✅ 完成并验证 | `src/chat/api.py`（278 行） |
> | **S4** 测试页 | ✅ 完成 | `prototype/chat.html`（508 行） |
> | **S5** 准确性验证 | ⏳ **需要你在本机跑** | 见下方五个问题 |
>
> 如何使用：重启 Reaper 服务器 → 打开 `http://127.0.0.1:16625/api/chat/prototype`
>
> ⚠️ 聊天端点**默认仅回环可访问**（服务器默认绑 `0.0.0.0`，而 agent 能读文件）。
> 需要局域网访问时在 config.json 设 `chat.allow_remote: true`。

#### 目标：打掉两个假设

| 假设 | 内容 | 不过的后果 |
|---|---|---|
| **H1（产品价值）** | agent 拿 TeX + 大纲，能给出**可验证准确**的回答而不是编造 | 整个差异化主张不成立 |
| **H2（技术可行）** | Python 桥能驱动 pi RPC，并把事件流式转发到浏览器 | 换轮询方案 |

#### 测试对象

**`2210.00921` — "Quantum Error Mitigation"**（综述；8 个一级章节 / 38 个 section / 183 个含公式 block）

选它的理由：它有 **List of Symbols** 章节。**符号表里的定义不可能靠猜** —— 答对就说明 agent 真的去读了 TeX。

备选：`2604.12841`（"Fast and accurate AI-based pre-decoders for surface codes"，研究型论文）

#### 现状盘点

| 需要的东西 | 状态 |
|---|---|
| HTML（→ blocks.json） | ✅ `data/ar5iv/2210.00921/2210.00921.html` |
| 解析结果 + 翻译 | ✅ `data/translation_cache/2210.00921.json`（328 blocks，323 已翻） |
| **LaTeX 源码** | ❌ **缺**（`data/arxiv_source/` 为空）→ S1 要下载 |

#### 步骤

**S1 — 论文上下文准备** → `src/chat/context.py`

产物 `data/chat/2210.00921/workspace/`：
```
paper.tex        完整 LaTeX 源码（从 arxiv.org/e-print 下载解包）
blocks.json      段落索引 [{id, type, level, text, math_map}]
OUTLINE.md       章节大纲（前导块）
metadata.json    arxiv id / 标题 / 来源 / cleanerVersion
```

关键点：
- `https://arxiv.org/e-print/{id}`；**若返回 PDF → 标记 `status:"no-source"`**（arXiv 有时确实返回 PDF）
- 主 tex 识别：优先含 `\begin{document}` 的文件
- ⚠️ **OUTLINE.md 必须字节稳定**：不含时间戳、不含不稳定排序 → 才能命中 provider 的 prompt cache
- ✅ 验收：连跑两次，`OUTLINE.md` 的 sha256 一致

**S2 — pi 桥** → `src/chat/pi_bridge.py`

- spawn：`pi --mode rpc --session-dir <dir> --append-system-prompt OUTLINE.md --tools read,grep,find,ls`，cwd = workspace
- **常驻 reader 线程**解析 JSONL → 广播给订阅者
- 命令封装：`prompt()` / `abort()` / `get_state()`
- 空闲回收
- ✅ 验收：能 spawn、握手、发 prompt、收到事件、**不阻塞其他请求**

**S3 — SSE 端点**（加进 `src/server.py`）

| 端点 | 作用 |
|---|---|
| `POST /api/chat` | 转发 prompt，立刻返回 accepted |
| `GET /api/chat/stream` | SSE 广播事件 |
| `POST /api/chat/abort` | 中断 |
| `GET /api/chat/health` | 桥/进程状态 |

✅ 验收：`curl -N` 能看到事件逐行流出

**S4 — 最简测试页** → `prototype/chat.html`

纯 HTML+JS，`fetch` + `getReader` 读 SSE，渲染 markdown/公式。
✅ 验收：浏览器能看到流式回复

**S5 — 准确性与体验验证**（⚠️ 需要你在本机跑）

| # | 问题 | 为什么这么设计 |
|---|---|---|
| Q1 | 「List of Symbols 里 $X$、$Z$ 分别代表什么？」 | ⭐ **最强试金石**，符号定义靠猜不可能答对 |
| Q2 | 「这篇综述把方法分成了哪几大类？」 | 对应 III Methods 的结构，可核对 |
| Q3 | 「零噪声外推（ZNE）的基本假设是什么？」 | 必须读对具体章节 |
| Q4 | 「IV Comparisons 里各方法怎么权衡？」 | 跨小节综合 |
| Q5 | 「§III 里第 3 个公式是什么？」 | ⭐ 测试**结构锚点**能否定位 |

每题判定：回答里是否给出**可核对的原文位置**。无出处或答错 → prompt 措辞要改。

#### 交付物

```
prototype/pi_bridge.py      桥的原型
prototype/chat.html         测试页
src/chat/context.py         论文上下文准备（可直接进产品）
data/chat/2210.00921/       测试产物
```

#### 风险与退路

| 如果 | 那么 |
|---|---|
| pi 在沙箱里起不来 | 我只验证协议层，LLM 部分交给你本机跑 |
| agent 不读 TeX 只凭记忆 | 改 prompt 强制要求给出处；或把关键内容移进前导块 |
| e-print 返回 PDF | 标记 `no-source`，退化为用 `blocks.json` 文本（仍比全文注入好） |
| SSE 在插件里不通 | 退路是轮询（每秒拉增量） |

#### 分工：我能验证 vs 需要你验证

| 我（沙箱） | 你（本机） |
|---|---|
| S1 全部 | —— |
| S2 **协议层**（spawn/握手/分帧/广播/回收） | S2 的**真实 LLM 问答** |
| S3 全部 | —— |
| S4 渲染链路 | S4 的真实观感 |
| —— | **S5 全部**（依赖真实模型和你的 pi 配置） |

#### Phase 0.5 — Zotero 侧验证（与上并行）

| # | 验证什么 | 失败的话 |
|---|---|---|
| 0.5a | item pane section 能显示面板并流式读 localhost | 改用浮动窗口 |
| 0.5b | snapshot 的 `renderTextSelectionPopup` 真的触发，且 `position.value` 是 `#reaper-block-N` | 退回私有 API 读 `getSelection()` |

**产出**：一份「验证结果 + 修正后的方案」。

### Phase 1 — 最小可用闭环

**目标**：打开 Zotero 面板 → 问问题 → agent 读 TeX 回答 → 流式显示。

新增：
- `src/chat/pi_bridge.py` — spawn/kill pi、JSONL 分帧、事件解析、广播给多个 SSE 客户端
- `src/chat/session.py` — `arxiv_id → PiSession` 注册表、空闲回收
- `src/chat/context.py` — TeX 准备、大纲生成、system prompt 组装
- `src/server.py` 新端点：
  - `POST /api/chat` `{arxiv_id, message}` → 发消息
  - `GET  /api/chat/stream?arxiv_id=` → SSE 事件流
  - `POST /api/chat/abort`
  - `GET  /api/chat/history?arxiv_id=`
  - `POST /api/chat/reset`
- `zotero-plugin/content/chat.xhtml` + `chat.js` + `chat.css`
- `bootstrap.js` 注册 ItemPaneManager section

**不做**：选中段落、引用解析、审批 UI。

### Phase 2 — 选中段落

- 2a：reader `renderTextSelectionPopup` 加「Ask Reaper」按钮
- 2b：双语 HTML 注入段落级交互（需验证通信链路）
- 面板显示「正在讨论：<段落>」，可取消

### Phase 3 — 引用解析（差异化）

- `src/chat/citations.py`：
  - `.bbl` 解析（**必须同时支持 `\bibitem` 和 biblatex `\entry{key}{type}`**——只匹配 `\bibitem` 会静默得到 0 条）
  - 文内引用映射：LaTeX 的 `\cite*` 家族；HTML 的 `ltx_cite href="#bib.bibN"` → `ltx_bibitem id`
- `resolve_citation` 工具（pi 扩展或自定义 tool）
- 标识符解析：**Crossref 主**（免 key，加 `mailto` 进 polite pool）→ Semantic Scholar → OpenAlex（需免费 key）
  - 注意：OpenAlex 和 S2 现在匿名都返回 429
  - 只有 22/68 条参考文献含 arXiv ID、21/68 含 DOI → **标题+作者+年份兜底是必需的**
- 取被引全文：`arxiv.org/html/{id}` → ar5iv → `e-print/{id}` 的 `.tex`
- ⚠️ **严格校验 + 无法确认就弃权**——最大失败模式是静默解析到错误的论文

### Phase 4 — 打磨

- 工具审批 UI（Extension UI 协议 → 面板 confirm 对话框）
- 上下文占用显示（`ctx.getContextUsage()`）
- 会话列表 / 重命名 / 导出
- 多窗口同步（**等 pi 新版**，届时用 `acquireSession` 租约）

---

## 6. 涉及文件

**新增**
```
src/chat/__init__.py
src/chat/pi_bridge.py
src/chat/session.py
src/chat/context.py
src/chat/citations.py          # Phase 3
src/chat/tools/                # Phase 3，pi 扩展
zotero-plugin/content/chat.xhtml
zotero-plugin/content/chat.js
zotero-plugin/content/chat.css
zotero-plugin/content/locale/*.ftl   # section 的 l10nID 需要
```

**修改**
```
src/server.py                  新端点 /api/chat/*
src/config.py                  chat 配置节（空闲超时、工具白名单、是否启用）
config.json                    同上（加默认值）
zotero-plugin/bootstrap.js     注册 section + reader 事件
zotero-plugin/manifest.json    版本号 + strict_max_version
zotero-plugin/prefs.js         新偏好项
```

**复用（已存在，不重写）**
```
src/ingestion/fetcher.py       _download_arxiv_source()  → TeX 已经有了
src/ingestion/parser.py        Block / mark_and_extract   → blocks.json 的来源
src/translation/dictionary.py  TermDictionary             → prompt 里的术语表
src/task.py                    Task 状态管理               → 可选，用于 chat 会话状态
```

---

## 7. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| **prompt injection → 任意命令**（D5） | 高——安全 | Phase 1 强制只读白名单；Phase 3 加审批 |
| **附件 HTML 里 JS 不执行** → 现有 TOC/主题/译文开关在 reader 里失效（D3） | 中高——影响已有功能 | 需你确认；退路是改 CSS-only 实现，或主要阅读场景改用外部浏览器 |
| agent 不查 TeX 而凭记忆编造（D2） | 中——质量 | Phase 0.1 验证；prompt 里强制要求给出处 |
| Zotero 面板里流式读受限（D4） | 中 | Phase 0.3 验证；退路是轮询 |
| reader frame 拦截请求（D4） | 中 | 请求一律从插件作用域发起，绝不在 reader 内发 |
| 只读库中收不到选区事件（D3） | 低 | 明确提示用户；或在面板里提供手动粘贴入口 |
| `.bbl` 格式多样（Phase 3） | 中 | 同时支持 `\bibitem` 和 biblatex；解析失败就弃权 |
| 静默解析到错误的被引论文 | 中——会污染答案 | 严格校验 + 弃权 + 缓存 |

---

## 8. 验收标准

**Phase 0**：四个验证脚本全部通过，或给出明确的替代方案。

**Phase 1**：
- 在 Zotero 中选中一篇有 Reaper 附件的论文，打开对话面板
- 提问「这篇论文的核心方法是什么」，能在 30 秒内看到流式回答
- 回答里的公式引用与 TeX 一致（人工抽查 3 个问题）
- 关闭 Zotero 再打开，对话历史还在（会话持久化）
- agent 无法写文件（只读白名单生效）

**Phase 2**：
- 在 PDF 里选中一段话 → 点「Ask Reaper」→ 面板显示该段落 → 提问
- 面板能显示段落在论文里的位置（章节 + 段落号）

**Phase 3**：
- 问「参考文献 [12] 讲了什么」→ agent 自动取到被引论文 → 回答带出处
- 对没有 arXiv ID 的引用，明确回答「只能看到摘要」而不是编造

---

## 9. UI 设计

### 技术选型

面板跑在 Zotero 的 **chrome 文档**里（不是沙箱 iframe），所以 **JS 正常执行**。

| 项 | 选择 | 理由 |
|---|---|---|
| 框架 | **无**（原生 HTML/CSS/JS） | 现有 `content/` 就是无构建的静态文件，保持一致 |
| Markdown | 内置精简渲染器 | 避免在 system principal 环境引入第三方 JS |
| 公式 | 内置轻量 LaTeX→HTML | 面板很窄，只需常见符号 + 上下标 + 分式 |
| 主题 | **Zotero CSS 变量** | 自动跟随明暗主题，天然融入 |

> ⚠️ **必须做 LaTeX 分隔符归一化**：LLM 会混用 `$...$`、`\(...\)`、`\[...\]`、`` `$x$` ``。参考项目专门写了 `mathMarkdown.ts` 处理这件事，是踩过的坑。

### 外观：用 Zotero 自己的设计令牌

已从 9.0.6 源码确认的变量：

| 用途 | 变量 |
|---|---|
| 面板底 | `--color-sidepane` |
| 卡片/气泡/输入框 | `--fill-primary` … `--fill-senary`（primary 最强） |
| 正文 | 继承默认文字色 |
| 次要文字 | `--color-quarternary-on-sidepane` |
| 更淡 | `--color-quinary-on-sidepane` |
| 描边 | `--color-border` / `--color-border50` |
| 分隔线 | `--color-panedivider` |
| 强调 / 发送按钮 | `--color-accent` / `--color-accent-text` |
| 焦点框 | `--color-focus-border` / `--color-focus-outer-border` |
| 滚动条 | `--color-scrollbar` / `--color-scrollbar-background` / `--color-scrollbar-hover` |

**不要硬编码颜色**——硬编码会让面板在暗色主题下变成一块突兀的白板。

### 布局

```
┌──────────────────────────────────────┐
│ Reaper Chat          [⋯] [＋]        │ ← header：菜单 / 新会话
├──────────────────────────────────────┤
│                                      │
│  ┌────────────────────────────────┐  │
│  │ §3.2 · 第 2 段            [×] │  │ ← 选中段落 chip（可取消）
│  │ "the decoding problem is..."   │  │
│  └────────────────────────────────┘  │
│                                      │
│  ┌────────────────────────────┐      │
│  │ 这篇论文的核心方法是什么？  │      │ ← 用户消息：淡底 + 圆角，全宽
│  └────────────────────────────┘      │
│                                      │
│  ▸ 读取 paper.tex §3.2        ⌄      │ ← 工具调用：折叠，灰色小字
│                                      │
│  论文提出了一种基于张量网络的……       │ ← AI 回复：无气泡，全宽
│                                      │
│     H = −Σᵥ Aᵥ                       │ ← 公式（居中显示）
│                                      │
│  ┌─ 原文 ────────────────────┐       │
│  │ "we adopt a surface code"  │       │ ← 引用块：左边框
│  └───────────────────────────┘       │
│                                      │
├──────────────────────────────────────┤
│ ┌──────────────────────────────────┐ │
│ │ 问点什么…                        │ │ ← 输入框：多行自适应
│ │                      [📎]  [ ↑ ] │ │
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
```

### 视觉细节（决定「好看」的地方）

1. **AI 回复不用气泡**（全宽、无底），**用户消息用淡底圆角**。侧边栏只有 300-400px，两侧气泡会让长文本和公式挤成一列窄条。
2. **公式居中、独立成行**；行内公式保持基线与字号略缩。
3. **工具调用折叠**：默认只显示一行（「读取 paper.tex §3.2」），点击展开看内容。这是 Claude Code / Cursor 验证过的模式。
4. **思考过程**用更淡的颜色 + 斜体，可折叠，默认收起。
5. **流式光标**：最后一段尾部一个细竖线闪烁，完成后消失。
6. **自动滚动**：默认滚到底，但**用户手动向上滚动后停止**（经典细节，做错了很烦）。
7. **空状态**：一句说明 + 2-3 个建议问题 chip（「核心贡献是什么」「关键假设是什么」「实验设置」）。
8. **代码块**：等宽字体 + `--fill-primary` 背景 + 右上角复制按钮（hover 才显示）。
9. **滚动条**用 Zotero 变量，窄（6-8px），hover 才明显。
10. **不用阴影**，用 `--color-border` 描边。Zotero 的原生 UI 是描边风格，加阴影会显得像外挂。

### 可借鉴的具体案例

| 参考 | 借什么 |
|---|---|
| **little-alphaxiv**（本地已 clone） | `SelectedTextAskAi.tsx` 的浮动按钮定位（`rect.right`, `rect.top - 34`）；`AgentActivity.tsx` 的工具调用展示；`Markdown.tsx` 的 delimiter 归一化 |
| **Claude Code / Cursor** | 工具调用折叠的一行摘要 + 展开详情 |
| **Zotero 自己的 section**（条目信息、摘要） | 间距、字号、描边风格——照抄它的视觉节奏 |
| **`xing-shuyin/pi-web-ui`** | thinking 块与 tool call 的区分显示（MIT） |

---

## 10. 参考实现调研（Zotero AI 对话插件赛道）

调研了 8 个同类插件。**结论：我们的设计方向被现实验证了，且有一批可直接拄的具体代码。**

### 赛道地图

| 仓库 | 形态 | 上下文策略 | 许可 | 对我们的价值 ||---|---|---|---|---|
| **`yilewang/llm-for-zotero`** | 侧边栏 + **独立窗口模式**；**支持 Claude Code / Codex 作为外部后端** | Agent Mode + 9 个内置 skill | **AGPL** | ⭐⭐⭐⭐ **与我们的架构最同构**（读源码时它已 2,944★） |
| **`xuhan-rgb/zotero-ai-sidebar`** | 原生 XUL 列（非 item pane） | **arXiv LaTeX 源码 + 目录前导块 + 按需取章节工具** | AGPL | ⭐⭐⭐ **和我们方案几乎一模一样** |
| **`luisherrmann/llmz`** | ✅ **item pane section**（Zotero 9） | embedding RAG + LLM 选图表 | **MIT** | ⭐⭐⭐ **唯一可用的 item-pane 注册代码** |
| **`syt2/paper-chat-for-zotero`** | ✅ 面板 + **独立浮动窗口** | 全文截断 | AGPL | ⭐⭐ 浮动窗口 + 工具命名 |
| `jetxa/zotero-ai-assistant` | ✅ item pane section | 全文截断（100k 字符） | AGPL | ⭐ item-pane 最简单实现 |
| `text70/zotero_ai` | 浮动 XUL 窗口 | 全文截断 + 摘要 embedding | AGPL | ⭐ KaTeX 打包方式 |
| `bigeagle/aizotero` | 独立 Web 应用（非插件） | 全文塞进首条消息 | **MIT** | ⭐ 布局参考 |
| `givemetarte/chat-with-paper` | 插件 | chunk + embedding RAG | — | 已停更 |
| `windfollowingheart/zotero-paper-agent` | 插件 | — | — | 参考价值低 |

### ⭐ 最重要的发现：D2 的设计被验证了

`xuhan-rgb/zotero-ai-sidebar` 做的**正是我们的 D2 方案**（TeX 放工作目录 + 大纲进 prompt + agent 按需取）。它的注释原文：

> *"…each turn's static prefix stays small (~1 KB) AND byte-stable across turns (good for the prompt cache). The model fetches actual section bodies via the `arxiv_get_section` tool on demand."*

**两个关键洞察可以拄**：
1. **前导块要字节稳定**（byte-stable）——同一个 TOC 每轮完全一致，才能命中 provider 的 prompt cache。我们的 `blocks.json` 导出要避免时间戳等易变字段。
2. **工具描述要教模型省 token**：它的 `arxiv_list_sections` 返回 `{number, level, title, label, bodyChars}`，并在描述里明确要求「先看 bodyChars，别为了 2KB 的内容去拉 30KB 的整节」。

它的工具集命名值得直接拄：
```
arxiv_list_sections / arxiv_get_section / arxiv_get_equation
arxiv_get_figure / arxiv_get_table / arxiv_get_bibliography
```

### arXiv LaTeX 源码处理的完整工程细节（它已踩过坑）

| 环节 | 它的做法 | 对我们的意义 |
|---|---|---|
| 下载 | `Zotero.HTTP.request(..., {responseType:"arraybuffer"})` | ⚠️ **二进制下载用 XHR 是对的**（注释："Zotero's XHR API avoids the Gecko fetch binary-response issue for arXiv"）。**流式用 fetch，二进制用 XHR——两个不同的工具** |
| 解压 | `fflate.gunzipSync` + 手写 512 字节 tar 解析（零依赖） | 我们在 Python 侧用 `tarfile`，更简单 |
| 主 tex 识别 | 优先含 `\begin{document}` 的 `.tex` | 直接拄 |
| 清理流水线 | `inlineInputs → expandMacros → stripTexComments → normalizeCitations → annotateNumberedEquations/Figures/Tables`，带 **`ARXIV_SOURCE_CLEANER_VERSION = 15`** | ⭐ **版本号让缓存失效逻辑变简单**：清理逻辑一变就改版本号 |
| 缓存布局 | `<dataDir>/…/arxiv/<编码 id>/{source/**, meta.json}`，meta 含 `{status:"ok"\|"no-source", mainTexRelPath, files[], cleanerVersion}` | 直接拄（我们用 `data/chat/{id}/workspace/`） |
| 异常 | **PDF 载荷检测 → `status:"no-source"`** | ⚠️ arXiv 的 `e-print` 有时返回 PDF 而不是 tarball，必须显式处理 |
| 安全 | `safeRel()` 拒绝 `..` 和绝对路径 | 直接拄 |

### Item pane 注册：唯一可用的完整例子（`llmz`，MIT）

```js
// core/chat-pane.js:871-898
this.paneID = Zotero.ItemPaneManager.registerSection({
  paneID: "llm-chat-pane", pluginID: this.id,
  header:  { l10nID: "llm-chat-pane-header",  icon: this.rootURI + "res/icons/robot_2_pane.svg" },
  sidenav: { l10nID: "llm-chat-pane-sidenav", icon: …, orderable: true },
  onItemChange: ({ item, setEnabled }) => { this._currentPaneItem = item; setEnabled(!!item); },
  onRender: ({ doc, body }) => {
    body.replaceChildren();
    const style = doc.createElement("style"); style.textContent = this._css; body.appendChild(style);
    …
  },
});
```

配套经验：
- FTL 只要 4 行（`llm-chat-pane-header = .label = …`），放在 `locale/` 自动加载
- CSS 用 `Zotero.File.getContentsFromURL(rootURI + "styles/style.css")` 预取，**在 CSS 就绪后再调 registerSection**
- 卸载：`shutdown()` → `Zotero.ItemPaneManager.unregisterSection(this.paneID)`
- ⚠️ 这两个插件**都只用 `onRender`**，没人用 `onAsyncRender` / `onDestroy`——说明我们的用法不能超出这个范围太多

### 浮动窗口（如果最终选这个形态）

`syt2/paper-chat-for-zotero` 同时支持停靠和浮动：
```ts
floatingWindow = mainWindow.openDialog(
  `chrome://${config.addonRef}/content/chatWindow.xhtml`,
  "paperchat-chat-window",
  `chrome,dialog=no,resizable=yes,centerscreen,width=${width},height=${height},left=${left},top=${top}`,
);
```
`chatWindow.xhtml` 只是一个空的 XHTML 壳，DOM 由插件构建（拖拽栏只在浮动模式显示）。开一个 `panelMode` 偏好就能在两种形态间切换。

### 公式渲染：三种方案，我们选哪种

| 方案 | 代表 | 构建步骤 | 适配我们？ |
|---|---|---|---|
| **vendored 静态文件** | `llmz`：`vendor/marked.min.js` + `vendor/katex.min.js`，用 `Services.scriptloader.loadSubScript` 加载 | ❌ 无 | ✅ **最契合我们无构建的 `content/`** |
| KaTeX 静态资产 + `chrome://` 引入 | `xuhan-rgb`：`content/katex/**`（含字体），`katex.min.css` 走 `chrome://` | ❌ 无 | ✅ 可行 |
| esbuild 打包 | `text70` / `syt2` | ✅ 有 | ❌ 不想引入构建 |

⭐ **一个很聪明的小技巧**（来自 `syt2`）：KaTeX 用 `output: "mathml"` 渲染 → **不需要 katex.css**（Zotero/Gecko 原生支持 MathML）。对无构建方案是大利好。

### ⭐⭐⭐⭐ 最高价值参考：`yilewang/llm-for-zotero`（2,944★，AGPL-3.0）

**它是唯一一个已经在做我们要做的事的项目**：把外部 agent harness 当作引擎，插件只做 UI。

它有 **`src/claudeCode/`、`src/codexAppServer/`、`src/webchat/`** 三套外部后端，以及一个关键的抽象层：

```
src/agent/externalBackendBridge.ts   129 KB / 3731 行
```

#### 它的抽象形状（我们要复刻的）

外部后端被包装成实现 `AgentRuntimeLike` 接口的对象：

```ts
type AgentRuntimeLike = Pick<AgentRuntime,
  "listTools" | "getToolDefinition" | "unregisterTool" | "registerTool" |
  "createActionContractForRequest" | "registerPendingConfirmation" |
  "resolveConfirmation" | "getRunTrace"      // ← 这些是空实现，只为兼容接口
> & {
  runTurn(params: RunTurnParams): Promise<AgentRuntimeOutcome>   // ← 核心
  listExternalActionsSync(): Array<{
    name; description; inputSchema;
    source: "backend"; backendToolName;
    riskLevel: "low"|"medium"|"high";        // ← 工具风险分级
    requiresConfirmation: boolean;
    mutability: "read"|"write";
  }>
  listSlashCommandsSync()                      // ← 把 harness 的斜杠命令搬到 UI
  listModels() / listEfforts(model)            // ← 模型/推理档位从 bridge 拉，不硬编码
  updateRuntimeRetention({mountId, retain, …}) // ← 会话保活
  invalidateSession({conversationKey, …})      // ← 会话失效
  runExternalAction(name, input, {confirmationMode, onProgress, requestConfirmation})
}
```

**这个「shim 子集 + bridge 特有方法」的形状，就是我们包装 pi 的模板。**

#### 传输方式：HTTP，不是 stdio

它用一个**本地 HTTP bridge**，默认 `http://127.0.0.1:19787`，用普通 `fetch()` 调用：

| 端点 | 用途 | pi 的对应 |
|---|---|---|
| `/healthz` | 健康检查 | `get_state` |
| `/run-action` | 执行外部动作 | `prompt` / `bash` |
| `/invalidate-session` | 丢弃会话 | `new_session` |
| `/runtime-retention` | 会话保活/回收 | 我们自己的空闲回收 |

> ⚠️ **这是一个我们应该重新考虑的决定。** 我们的 D1 计划用 stdio 直连 pi RPC，但 HTTP bridge 额外给了我们：健康检查、重连、多客户端（未来多窗口）、更好调试。代价是多一个薄进程。
> **建议**：写一个极薄的 `pi_bridge` HTTP 服务包住 `pi --mode rpc`。反正 Python 服务器已有。

#### 其他直接可拄的细节

| 细节 | 它的做法 | 我们的映射 |
|---|---|---|
| **工具审批重试** | 注释原文："Re-register so the user can retry approval instead of getting stuck" | 审批失败要可重试，不能把用户卡死 |
| **Plan mode** | `permissionMode` 包含 `bypassPermissions` / `plan`；plan mode 提示词："Research and draft a structured plan only. **Do not mutate** Zotero, files, settings, processes, or external systems." | 我们的 D5 只读白名单 + 审批，可以学这个分级 |
| **路径脱敏** | `privacy/localDocumentPathRedaction` + `LocalDocumentPathStreamRedactor` —— 流式输出里的本地文件路径会被**脱敏后才显示** | 我们的 agent 输出也会带 `data/chat/.../paper.tex` 路径，应该脱敏 |
| **写入围栏** | `conversationWriteFence`：`withConversationWriteLock` / `areConversationWritesFrozen` / `getConversationWriteGeneration` | ⚠️ **重要**：这验证了我此前的发现——pi 的会话文件**没有锁**。并发保护必须做在插件/桥这一层 |
| **能力协商** | `assertClaudeBridgeLocalPdfCapability(bridgeUrl)` —— 连上后先问 bridge 支持什么 | 连上 pi 后先 `get_state` + `get_available_models` |
| **连不上时的提示** | `getBridgeQuickFixHint(baseUrl)` | 服务器未启动时要给可操作的提示，不是干等 |
| **历史回填** | `historyLoader.ts` 从 harness 读历史 | 对应 `get_messages` / `get_entries` |
| **skill 同步** | `projectSkills.ts` + `getClaudeProfileSignature()` 侦测 harness 的 skill 变化 | 对应 pi 的 skill/扩展发现，可以做指纹 |

#### 它也有自建的部分（**这些我们不抄**）

它仍然维护自己的消息存储（`store.ts` 121KB！）、自己的会话列表/重命名/删除、自己的 model adapter（`agent/model/*`：`anthropicMessages.ts`、`codexResponses.ts`、`openaiCompatible.ts`）、自己的 MCP 实现。

**根据你定的架构铁律，这些一律不抄** —— pi 已经全部提供了。我们只抄 **bridge 抽象 + 工具映射 + 交互细节**。

> ⚠️ **许可：AGPL-3.0**。只读不抄，学设计然后自己实现。

### ⚠️ 要避开的坑（都是别人踩过的）

| 坑 | 谁踩的 | 说明 |
|---|---|---|
| **私有的 Zotero 内部 API + 轮询** | `syt2`（`_internalReader._lastView._iframeWindow` + 500ms `setInterval`）、`jetxa`（合成 MouseEvent + 2s 轮询）、`xuhan-rgb`（60ms 轮询） | 这是它们 pin 住 `strict_max_version` 才能在 Zotero 升级时不炸的原因。**我们只用公开事件 + `params.annotation`** |
| **每个 token 都重渲染整条消息** | `text70/zotero_ai` | O(n²) DOM 抖动。要节流或只在段落边界重渲染 |
| **手写 SSE 解析器丢数据** | `jetxa`：`chunk.split("\n")` + `catch { /* Ignore partial JSON */ }` | 静默丢文本；且无 AbortController |
| **明文存 API key** | `syt2`（prefs JSON）、`text70`（prefs）、`aizotero`（localStorage） | 正确做法是 `Services.logins` + `OSKeyStore`（`llmz` 这么做，带 `"llmkv1:"` 前缀）。**我们的 key 在 pi 手里，天然规避** |
| **一条 JSON blob 存全部对话** | `aizotero`（`paper_id TEXT PRIMARY KEY, chat_data JSON`） | 搜索/编辑/重发都痛苦。用消息行（`syt2` 的 `sessions`+`messages`）。**我们的会话在 pi 里，也不需要自建** |
| **全文字符截断当上下文** | `jetxa`(100k) / `text70`(30-60k) / `aizotero`(全部) | 正是我们的 read/grep 方案要避免的 |

### 许可提醒

- ✅ **MIT**（可抄代码，带署名）：`luisherrmann/llmz`、`bigeagle/aizotero`
- ⚠️ **AGPL-3.0**（抄代码会让 Reaper 也变 AGPL）：`xuhan-rgb/zotero-ai-sidebar`、`syt2/paper-chat-for-zotero`、`text70/zotero_ai`、`jetxa/zotero-ai-assistant`
    → **AGPL 的项目只读不抄**，学设计模式并重新实现。§13 还有网络提供服务的源码披露义务

---

## 11. 待讨论的问题

1. **D3 的关键确认**：在 Zotero 内置 reader 里打开 Reaper 附件时，**TOC 侧栏 / 主题切换 / 译文开关这几个按钮还有效吗？** 这决定了我们已有的 JS 功能是否要在 reader 场景下重做成 CSS-only。
2. **Phase 顺序**：Phase 0 的四个验证，我建议先做 0.1 和 0.3（一个验最不确定的 agent 行为，一个验最不确定的 UI 链路）。可以并行。
3. **面板是否需要在「浏览器预览」里也能用？** 现在有 `/api/zotero_html/{id}`，浏览器打开是另一套体验。要不要把对话面板也做成可独立打开（方便调试和对比）？
4. **轮次上限**：单次提问允许多少轮工具调用？pi 默认有 6 轮硬上限（little-alphaxiv 的做法），我们要不要显式设一个？
5. **历史保留策略**：会话无限增长（pi 有内置 compaction）。要不要在 UI 上显示上下文占用？
