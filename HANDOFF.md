# Reaper — 项目交接（Current）

> 最后更新：2026-10-10
> 当前分支：`feat/chat-panel`（领先 `main` 15 个提交，尚未合并）
> 最近提交：`e1f60f4`（2026-09-22，chore(config): 模板默认模型改为 hepai/deepseek-v4.1-flash）

**文档导航**

| 文件 | 定位 |
|---|---|
| `AGENTS.md` | Agent 入口：一页硬性约束 + 文档索引（pi 自动加载）|
| `HANDOFF.md`（本文） | **唯一「当前版本」交接文档**：状态、模块地图、运行方式、缺口、约定 |
| `ARCHITECTURE.md` | 架构参考：数据流、协议、模块边界、设计决策 |
| `CHAT_PLAN.md` | AI 对话功能的调研与设计记录（讨论稿）。文件名为早期命名（`pi_bridge.py` → 实际 `bridge.py`、`pi_ext.py` → 实际 `session.py`），落点以代码和模块 README 为准 |
| `roadmap.md` | 最初的四阶段路线图（历史文档，Phase 1 已完成） |
| `<module>/README.md` | 模块级说明，见下方「模块地图」 |

---

## 1. 项目是什么

**Reaper** 把 arXiv 论文自动转换为**中英对照的可读 HTML**，作为附件存入 Zotero；
双击附件即可阅读，公式/图表/表格保留 ar5iv 原生渲染，带可折叠 TOC 侧栏。

当前开发方向：**围绕论文与 AI 对话**（选中段落提问、引用溯源）。
架构铁律（用户已定，见 `CHAT_PLAN.md` §2）：

> **pi 是引擎，Reaper 只是 UI。**
> LLM 调用、工具循环、重试、会话管理、压缩、模型认证全部归 pi；
> Reaper 只做「论文数据准备 + 通信桥 + 面板渲染 + Zotero 集成」。
> **不要自建 LLM 循环 / 会话存储 / 压缩逻辑。**

## 2. 当前状态

| 能力 | 状态 | 位置 |
|---|---|---|
| 三来源获取（arxiv.org/html → ar5iv → ar5ivist Docker） | ✅ 可用 | `src/ingestion/fetcher.py` |
| LaTeXML HTML 解析 → `Block` 序列（含公式/脚注占位） | ✅ 可用 | `src/ingestion/parser.py` |
| 按章节并发 LLM 翻译 + 双层术语表 + 翻译缓存 | ✅ 可用 | `src/translation/` |
| 渲染双语 HTML（TOC / 主题 / 译文开关 / 自包含资源） | ✅ 可用 | `src/rendering/` |
| Zotero 插件：下载 PDF / 生成双语 HTML / 补全资源 | ✅ 可用 | `zotero-plugin/` |
| 对话后端：论文 workspace 准备 | ✅ 完成 | `src/chat/context.py` |
| 对话后端：pi 桥（stdio JSONL ↔ 事件广播） | ✅ 完成 | `src/chat/bridge.py` |
| 对话后端：每论文一进程注册表 + 空闲回收 + 会话索引 | ✅ 完成 | `src/chat/session.py` |
| 对话后端：HTTP/SSE API（含会话列表/切换/重命名/分叉/删除/导出/树导航） | ✅ 完成 | `src/chat/api.py` |
| 对话测试页（浏览器手工验证） | ✅ 可用 | `prototype/chat.html` |
| **Zotero 对话面板（item pane section）** | ❌ **未开始** | 计划：`zotero-plugin/content/chat.xhtml` |
| **选中段落提问**（reader `renderTextSelectionPopup`） | ❌ 未开始，且有前置项 | 见 §7 |
| **引用解析**（`\cite` → 被引论文全文） | ❌ 未开始 | 计划：`src/chat/citations.py` |
| 工具审批 UI（Extension UI 隧道） | ❌ 未开始（Phase 1 用只读白名单替代） | plan §Phase 4 |
| 测试套件 | ⚠️ **部分失效**：fetch/render 相关类仍按 FetchedPage 之前的旧 API 写 | `tests/README.md` |

**分支说明**：`main` 停在插件 setup.sh 修复（`b7be37e`）；`feat/chat-panel` 包含
chat 后端、并发修复、日志系统、插件 202 处理、数据目录分层重构。合并前需要真机
验证 Zotero 端（见 §7）。

## 3. 模块地图

```
reaper/
├── main.py / src/cli.py          命令行入口（单篇论文全流程）
├── src/
│   ├── server.py                 HTTP 后端：论文生成流水线 + /api/chat 挂载
│   ├── config.py                 配置 + data/papers 目录布局（所有路径的唯一来源）
│   ├── task.py                   翻译任务状态机（断点续传 / error_history）
│   ├── logbook.py                并发任务日志：终端状态面板 + 每任务一份日志文件
│   ├── ingestion/                获取 + 解析            → src/ingestion/README.md
│   ├── translation/              翻译 + 术语表 + 缓存    → src/translation/README.md
│   ├── rendering/                双语 HTML 渲染           → src/rendering/README.md
│   └── chat/                     pi 对话桥 + API + 上下文 → src/chat/README.md
├── zotero-plugin/                Zotero 插件             → zotero-plugin/README.md
├── pi-extensions/                补 pi RPC 缺失的扩展命令 → pi-extensions/README.md
├── prototype/chat.html           对话后端手工测试页       → prototype/README.md
├── tools/migrate.py              一次性数据迁移脚本（旧扁平布局 → data/papers）
├── tests/                        测试套件（注意：被 .gitignore 忽略）→ tests/README.md
├── config.json                   本地配置（含 API key，gitignore）
└── data/                         运行时产物（gitignore）
```

## 4. 两条链路

**A. 论文生成（已有，稳定）**

```
Zotero 菜单 / CLI / GET /api/generate
  → fetch_html()   三来源按优先级，缓存 {source_dir}/{id}.html + 图片
  → mark_and_extract()  一次遍历标记 data-reaper-id=N 并抽出 blocks[]
  → translate_blocks()  按章节分组并发，缓存按段落 SHA256，术语表注入 prompt
  → render_bilingual_html()  注入译文/TOC/主题/页脚，资源落 assets/ 或 CDN
  → data/papers/{id}/process/reaper_html/index.html（Zotero 附件来源）
```

**B. 对话（新，后端已完成）**

```
Zotero 面板（未实现） / prototype/chat.html
  → HTTP POST /api/chat（立即返回 accepted）
  → SSE GET /api/chat/stream（常驻订阅，事件广播）
        │  Python: src/chat/api.py
        ▼
  src/chat/session.py  每论文一个 pi 进程（懒加载 + 空闲回收）
  src/chat/bridge.py   stdio JSONL ↔ 队列广播（单读取线程）
        │  pi --mode rpc，cwd = chat/workspace
        ▼
  pi agent（--tools read,grep,find,ls，--append-system-prompt OUTLINE.md）
  读 paper.md / blocks.json 回答，扩展 reaper-tree.ts 提供 /goto /label /where
```

## 5. 数据布局（`src/config.py` 是唯一权威）

```
data/
├── papers/{arxiv_id}/
│   ├── source/                     原始材料：{id}.html + 图片（+ TeX/源码）
│   ├── process/
│   │   ├── translation_cache/cache.json   PaperCache v2（HTML hash + 分段译文）
│   │   ├── state.json                     Task 状态（断点续传）
│   │   └── reaper_html/index.html(+assets/)  最终双语 HTML
│   └── chat/
│       ├── workspace/              agent 上下文：paper.md / blocks.json / OUTLINE.md / metadata.json
│       └── sessions/*.jsonl        pi 会话文件（对话历史本体）
├── dict/                           user_terms.json（高优先）+ llm_terms.json（自动）
└── logs/                           server.log + papers/{id}.log
```

> ⚠️ 旧扁平布局（`data/ar5iv/`、`data/chat/`、`data/tasks/`、`data/translation_cache/`、
> `data/zotero/`）是迁移前遗留，只被 `src/chat/context.py` 的 legacy fallback 引用。
> **删除前注意**：旧 `data/chat/2210.00921/sessions/` 里有 3 个只存在于旧目录的会话文件。

## 6. 如何运行

```bash
# 后端（常驻）
python3 src/server.py                        # → http://localhost:16625

# CLI：单篇论文全流程
python3 main.py 2401.04268

# 测试（需要项目根在 cwd）
python3 tests/run_tests.py

# Zotero 插件：打包 + 安装（重启 Zotero 生效）
bash zotero-plugin/setup.sh

# 对话后端手工验证
#   1. 确保论文已生成过（有 data/papers/{id}/source/{id}.html）
#   2. curl -X POST localhost:16625/api/chat/prepare -d '{"arxiv_id":"2210.00921"}'
#   3. 浏览器打开 http://127.0.0.1:16625/api/chat/prototype → 输入同一个 arxiv id
```

对话端点**默认仅回环可访问**（agent 能读文件）；需要局域网时在 `config.json`
设置 `chat.allow_remote: true`。

## 7. 下一步（按优先级）

1. **Zotero 对话面板**（Phase 1 收尾）
   - 用 `Zotero.ItemPaneManager.registerSection()`（Zotero 7+ API；`llmz` 的 MIT 代码是唯一可用例子）
   - 面板 JS 在 chrome 作用域，**请求必须从插件作用域发**（reader frame 注册了 BlockingObserver）
   - 流式读用 `fetch() + resp.body.getReader()`；**不要用 `EventSource`，也不要用 `Zotero.HTTP.request`**
   - 视觉：用 Zotero CSS 变量（`--color-sidepane`、`--fill-*`、`--color-accent`），不要硬编码颜色
2. **渲染器补 block 锚点**（选中段落的前置条件）
   - 现状：每个 block 只有 `data-reaper-id="{N}"`；只有标题被 `_inject_blocks_toc` 加了 `id="reaper-sec-{N}"`
   - 目标：每个 block 加 `id="reaper-block-{N}"`（Zotero 选择器生成器优先用 `id`）
   - 同时 `src/chat/context.py` / `OUTLINE.md` 已经按 `reaper-block-N` 写文案，需与渲染器对齐
3. **选中段落 → 提问**（Phase 2）
   - `Zotero.Reader.registerEventListener("renderTextSelectionPopup", ...)`
   - 从 `params.annotation.position`（CssSelector + refinedBy 字符偏移）解析 block id
   - 解析算法已在 `CHAT_PLAN.md` §D3 逐字记录（UTF-16 code unit、SHOW_TEXT 游走）
4. **引用解析**（Phase 3，差异化功能）：`.bbl` 支持 `\bibitem` + biblatex，Crossref 优先
5. 打磨：工具审批 UI、上下文占用显示、面板在浏览器预览中的复用

## 8. 跨模块不变量 / 踩过的坑

**pi 桥（`src/chat/bridge.py`）**
- `pi --mode rpc` 只有 stdio JSONL；**一个进程只能有一个 stdout 读取者**（bridge 统一读再广播）
- JSONL **只按 `\n` 分帧**（U+2028/U+2029 在 JSON 字符串里合法，不能当行分隔符）
- stdin 写入必须整行加锁（并发长 prompt 会交错损坏协议）
- `prompt` 返回 `accepted` ≠ 回答完成；完成信号是事件 `agent_settled`
- `--session` 路径不存在时 pi **静默新建会话**（表现为「历史消失」）→ bridge 启动前强制校验存在
- 运行中（streaming）**禁止**做树结构操作（pi issue #5096 会损坏会话树）；API 返回 409，扩展侧 `requireIdle`
- 切换会话用 `respawn`：旧进程标记 `_replaced`，其 `exited` 事件被静默，订阅者迁移到新进程

**对话安全**
- 论文正文是不可信输入；Phase 1 agent 工具白名单固定为 `read,grep,find,ls`（只读）
- reader 内嵌 iframe **不执行附件 HTML 里的 JS**（`allow-scripts` 未开）→ 现有 TOC/主题/译文开关在 Zotero reader 里可能无效（待真机确认；退路是 CSS-only 控件或改用外部浏览器阅读）

**渲染（用户多次强调）**
- 正文包在 `<div class="reaper-content">` 画布内，工具栏/TOC 在画布外
- TOC 默认关闭；不要硬编码 section 标题，用 HTML 结构（h2/h3/h4）识别层级
- 不要自写 CSS 框架，优先用 ar5iv 原生 CSS 变量（否则深色主题失效）
- `subsection` 包含 `section` 子串 → 正则/判断顺序必须从长到短
- 测试用 HTTP 而不是 `file://`（Chrome 安全策略）
- 三来源（ar5iv / arxiv.org/html / ar5ivist Docker）统一输出样式
- **每次修改正常 `git commit`，不要 squash / `reset --soft` 覆盖历史**

## 9. 已知不一致 / 待修小项

- `renderer` 尚未输出 `id="reaper-block-N"`（见 §7.2）；`src/chat/context.py` 的文案已引用它
- `.gitignore` 把 `tests/` 也忽略了 → **测试代码未被 git 跟踪**（建议改为只忽略 `tests/__pycache__/`）
- ~~旧扁平 `data/` 目录~~ → 已于 2026-10-10 清理，见 §11；`src/chat/context.py` 的 legacy
  fallback（`data/ar5iv/`…）现在是死代码，保留仅用于兼容旧机器
- `CHAT_PLAN.md` 中的文件名是设计期命名（`pi_bridge.py`/`pi_ext.py`），实际为 `bridge.py`/`session.py`
- `tests/run_tests.py` 的 fetch/render 用例用的是旧 API（元组解包 + `arxiv_id=`/`source_type=` 参数），
  直接跑会 TypeError；纯单元类（ID 解析、PaperCache v2）仍通过。修复方法见 `tests/README.md`
- `zotero-plugin/setup.sh` 里打包逻辑重复了两遍（可合并）
- `config.json.example` 的 `ar5ivist_dir` 是无人读取的历史字段

## 10. 环境

- 开发机：macOS；Python 3.14（`__pycache__` 可见 cpython-314）
- 依赖：`httpx`（网络）、Zotero 9/10（插件端）；无 Python 依赖清单文件（`requirements.txt` 不存在，按 import 装）
- LLM：兼容 OpenAI `/chat/completions` 的端点；`config.json → api.params` 原样透传
  （如 `reasoning_effort: none`），端点拒绝时会自动去掉参数重试一次
- `config.json` 含真实 API key，已被 gitignore，**不要提交**

## 11. 仓库清理记录（2026-10-10）

删除了可再生成 / 已迁移且有哈希校验的冗余，**论文数据（`data/papers/`）与会话全部保留**：

| 已删除 | 依据 |
|---|---|
| `__pycache__/`、`.DS_Store`、根目录 scratch（`old.html`、`t.html`、`openalex.md`、`parse.rst`、`pyb.py`）、`reaper-for-zotero.xpi` | 可再生成 / 误下载 |
| 测试残留：`TESTPROG*`、`E2E_FLASH*`、`VERIFY_EMPTY`、`9999.99999`、`1708.03684` | 无 process 产物或仅失败任务 |
| 迁移遗留：`data/{ar5iv,chat,tasks,translation_cache,zotero}/` | 逐文件哈希比对确认与 `data/papers/` 等价；旧 chat 里 3 个独有会话已先拷入新位置并校验 |
| 嵌套重复：`source/{id}/{id}.html`、`chat/workspace/data/`（递归空目录） | 与顶层文件哈希一致或纯空目录 |
| `ref_repo/`（180MB，14 个公开 clone） | 研究报告已留存在 `docs/`（含转存的 `little-alphaxiv-vs-alphaxiv-open.md`） |

移入版本管理：`data/migrate.py` → `tools/migrate.py`。
抢救数据：`2404.16130`、`2501.13958` 的 HTML 原先只存在于嵌套目录，已上移到 `source/{id}.html`。

> 注：本机 `trash` 受限，删除为永久操作；所有删除项均已先做等价性校验。
