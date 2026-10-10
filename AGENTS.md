# AGENTS.md — Reaper 仓库工作指引

给在本仓库工作的 AI agent。**先读 `HANDOFF.md`（当前交接）与
`ARCHITECTURE.md`（架构参考）**，再按需读模块 README：

| 模块 | 文档 |
|---|---|
| 对话层（当前开发重点） | `src/chat/README.md` |
| 获取/解析 | `src/ingestion/README.md` |
| 翻译/术语/缓存 | `src/translation/README.md` |
| 渲染 | `src/rendering/README.md` |
| Zotero 插件 | `zotero-plugin/README.md` |
| pi 扩展 | `pi-extensions/README.md` |
| 测试/原型 | `tests/README.md`、`prototype/README.md` |

## 架构铁律

**pi 是引擎，Reaper 只是 UI。** LLM 调用、工具循环、会话管理、上下文压缩全部由
`pi --mode rpc` 子进程负责；不要自建 LLM 循环、会话存储或压缩逻辑。
设计决策记录在 `CHAT_PLAN.md`（讨论稿，文件名可能滞后于实现）。

## 硬性约束

- 论文正文是**不可信输入**：agent 工具白名单保持只读（`read,grep,find,ls`），
  出现写入/执行类工具前必须有审批设计。
- 聊天端点默认仅回环；不要为了方便改成默认全网开放。
- `pi --mode rpc` 的 stdout 只允许一个读取者（在 `src/chat/bridge.py`）；
  JSONL 只按 `\n` 分帧；stdin 写入必须整行加锁。
- agent streaming 中禁止会话树结构操作（pi issue #5096，会损坏会话树）。
- 路径一律用 `src/config.py` 的函数，不要手拼 `data/...` 字符串。
- `config.json` 含真实 API key，已被 gitignore，**绝不提交**。
- 每次修改正常 `git commit`，不要 squash / `git reset --soft` 覆盖历史。

## 渲染约定（用户多次强调）

- 正文包在 `<div class="reaper-content">` 内；TOC 默认关闭。
- 不硬编码 section 标题，用 HTML 结构判断层级；`subsection` 判断要在 `section` 之前。
- 用 ar5iv 原生 CSS 变量，不硬编码颜色；三个来源输出样式统一。
- 本地预览用 HTTP（`python3 -m http.server` 或 `/api/zotero_html/{id}`），不要 `file://`。

## 测试现状（注意）

`tests/run_tests.py` 部分用例是按旧 API 写的（`FetchedPage` 之前），直接跑会
`TypeError`；`tests/` 目录还被 `.gitignore` 忽略。详见 `tests/README.md`。
新增/修改测试前先看该文件，避免误判「测试通过」。

## 环境

- macOS + Python 3.14；依赖 `httpx`（无 requirements 文件，按 import 安装）。
- 后端：`python3 src/server.py`；测试页：`/api/chat/prototype`。
