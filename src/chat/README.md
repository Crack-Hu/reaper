# src/chat — 论文对话层

围绕一篇论文与 pi agent 对话。**架构铁律：pi 是引擎，本模块只做「上下文准备 +
通信桥 + HTTP 表面」。** 不自建 LLM 调用、工具循环、会话存储、压缩。

## 文件

| 文件 | 职责 |
|---|---|
| `context.py` | 把已缓存的论文 HTML 变成 agent workspace；数学公式还原 LaTeX；宏展开 |
| `expand_macros.py` | 解析 `.tex` preamble 的 `\newcommand`/`\DeclareMathOperator` 并做字符串替换 |
| `bridge.py` | 驱动一个 `pi --mode rpc` 子进程：JSONL 分帧、事件广播、命令封装 |
| `session.py` | 每论文一个 pi 进程的注册表（懒加载 + 空闲回收）+ 会话列表/解析/删除 |
| `api.py` | `/api/chat/*` HTTP + SSE 端点，由 `src/server.py` 挂载 |

## workspace（agent 的工作目录）

`prepare_paper_context(arxiv_id)` 在 `data/papers/{id}/chat/workspace/` 生成：

| 文件 | 用途 |
|---|---|
| `paper.md` | **主上下文**。全文 Markdown，带 `<!-- block:N -->` 锚点；公式为 `$...$` |
| `blocks.json` | 段落索引：`{id, type, level, text, sentences[], math[], label?}` |
| `OUTLINE.md` | 章节大纲 + 使用说明。**字节稳定**（无时间戳），作为 system prompt 前导块以命中 prompt cache |
| `metadata.json` | arxiv id / 标题 / 来源 / `context_version`（缓存失效用） |

关键点：

- `block:N` 的 N 与渲染 HTML 的段落标记同源（parser 的 `data-reaper-id="N"`）。
  注意：渲染器目前**还没有**给每个 block 输出 `id="reaper-block-N"`（选中段落功能的前置项，见 `HANDOFF.md` §7）。
- 公式取 `<annotation encoding="application/x-tex">`；若有 TeX 源码则展开自定义宏
  （只做字符串替换，失败时降级为宏名原样，**不做 MathML→LaTeX 语义转换**）。
- 重新 prepare 后 `context_version` 不匹配会自动重建（`force=True` 强制）。

## pi 桥（bridge.py）

启动命令：

```
pi --mode rpc --session-dir <chat/sessions> --tools read,grep,find,ls
   [--session <已存在的绝对路径>] [--extension reaper-tree.ts]
   [--append-system-prompt OUTLINE.md] [--model ...] [--thinking ...]
cwd = chat/workspace
```

必须遵守的不变量（每条都对应一个真实 bug）：

1. **单 stdout 读取者**：reader 线程独占 stdout，解析出的每条事件广播给所有订阅者
   （多个 SSE 客户端不能各读各的）。
2. **只按 `\n` 分帧**：U+2028/U+2029 在 JSON 字符串里合法，按通用行读取会截断消息。
3. **stdin 写入整行加锁**：管道只保证小写入原子，并发长 prompt 会交错损坏协议。
4. **`prompt` 的返回只表示 accepted**，回答完成看 `agent_settled` 事件；
   被拒时 bridge 把 pi 的原话错误返回给 UI，而不是让用户干等。
5. **`--session` 必须存在**：路径不存在时 pi 会静默新建会话（表现为「历史消失」），
   所以 bridge 在 spawn 前校验，不存在直接抛 `PiBridgeError`。
6. **运行中禁止结构操作**：pi issue #5096 —— 工具执行中导航会写坏会话树。
   API 层用 `_busy()` 返回 409，扩展层用 `requireIdle` 再挡一次。
7. **会话切换用 `respawn`**：旧 bridge 标记 `_replaced` 以吞掉它的 `exited` 事件，
   订阅者先迁移到新进程再停止旧进程。

已封装的 RPC 命令：`prompt` / `abort` / `get_state` / `new_session` / `get_session_stats` /
`get_tree` / `get_fork_messages` / `set_session_name` / `fork` / `clone` / `export_html` /
`get_commands` / `get_messages`。

## 进程与会话模型（session.py）

- **每篇论文一个 pi 进程**，按 `arxiv_id` 缓存在注册表里；首次提问时 spawn，空闲
  `chat.idle_timeout`（默认 900s）自动回收（有 SSE 订阅者时不回收）。
- 会话文件由 pi 写在 `chat/sessions/*.jsonl`，`list_sessions()` 直接扫描目录得到
  会话列表（取首个用户消息作标题，读到 `session_name` 就用它）。
- `acquire()` respawn 时恢复**最新**会话，避免进程回收/服务器重启后历史悄悄分叉。
- `delete_session()`：优先系统 `trash`；trash 不可用且未显式允许时**拒绝永久删除**；
  正在使用的会话不能直接删（API 会先切到下一个会话再删）。

## HTTP API

见 `ARCHITECTURE.md` §5 的完整表格。设计要点：

- `POST /api/chat` 立即返回 accepted，回答走 `GET /api/chat/stream`（常驻 SSE 订阅，
  多个面板都能看到每一轮）。断线不丢消息。
- 聊天端点默认**仅回环可访问**（agent 能读文件）；`chat.allow_remote: true` 放开。
- `GET /api/chat/messages`、`/tree` 的返回都以 pi 为权威（`sessionFile` 可能因
  `reset`/切换而变化，不要用 spawn 时的路径做缓存）。

## 扩展桥（pi-extensions/reaper-tree.ts）

pi 的 RPC 没有 `navigate_tree` 命令；扩展命令却可以通过 `prompt` 调用。所以：

| 命令 | 作用 |
|---|---|
| `/goto <entryId> [summary]` | 移动活跃分支（TUI 的 `/tree` 导航） |
| `/label <entryId> <text>` / `/unlabel <entryId>` | 节点标签 |
| `/where` | 报告当前 leaf |

结果通过 `ctx.ui.notify()` 回传（RPC 模式下是 stdout 的 `extension_ui_request`）。
`config.PI_EXTENSIONS` 默认加载该扩展（文件存在时）。

## 调试

```bash
# 准备 workspace（前提：source/{id}.html 已存在）
curl -s -X POST localhost:16625/api/chat/prepare \
     -H 'Content-Type: application/json' -d '{"arxiv_id":"2210.00921"}'

# 看进程状态
curl -s 'localhost:16625/api/chat/health?arxiv_id=2210.00921'

# 发消息 + 看事件流（两个终端）
curl -s -X POST localhost:16625/api/chat -d '{"arxiv_id":"2210.00921","message":"核心方法是什么？"}'
curl -N 'localhost:16625/api/chat/stream?arxiv_id=2210.00921'

# 测试页
open http://127.0.0.1:16625/api/chat/prototype
```

## 尚未实现

- Zotero 插件里的对话面板（`zotero-plugin/content/chat.xhtml`）。
- 渲染器给每个 block 输出 `id="reaper-block-N"`（选中段落提问的前置项）。
- `citations.py`：`\cite` → 被引论文全文（Phase 3，见 `CHAT_PLAN.md`）。
- 工具审批 UI（Phase 4；当前靠只读工具白名单保证安全）。
