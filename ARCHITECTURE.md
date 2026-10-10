# Reaper — 架构参考

> 本文描述**当前代码**的架构。交接状态与下一步见 `HANDOFF.md`；
> 各模块实现细节见对应目录的 `README.md`。

## 1. 系统边界

Reaper 由三个可独立运行的部分组成：

```
┌────────────────────┐      ┌─────────────────────┐      ┌──────────────────┐
│ Zotero 插件 (JS)    │ HTTP │ Reaper 服务器 (Python)│ stdio│ pi agent (外部)   │
│ 菜单 / 面板 / 附件   │─────▶│ 生成流水线 + chat 桥  │─────▶│ LLM + 工具 + 会话  │
└────────────────────┘      └─────────────────────┘ JSONL└──────────────────┘
                                      │
                                      ▼
                            data/papers/{arxiv_id}/
```

- **插件**：只发 HTTP，不 spawn 子进程；负责 Zotero 集成与 UI（对话面板规划中）。
- **服务器**：唯一有状态的中枢。论文流水线、缓存、pi 进程生命周期、SSE 广播都在这里。
- **pi**：被服务器拉起的子进程。**不实现任何 LLM / 工具 / 会话逻辑**，全部委托给 pi。

## 2. 分层与模块

| 层 | 模块 | 职责 |
|---|---|---|
| 入口 | `main.py` / `src/cli.py` | CLI 单篇处理 |
| 入口 | `src/server.py` | HTTP 后端、生成流水线、chat API 挂载 |
| 基础设施 | `src/config.py` | 配置读取 + **所有数据路径的唯一来源** |
| 基础设施 | `src/task.py` | 任务状态机（pending→fetching→parsing→translating→rendering→done） |
| 基础设施 | `src/logbook.py` | 并发任务日志（终端面板 + 每论文日志文件） |
| 处理 | `src/ingestion/` | 获取（多来源）+ 解析（`Block` 序列） |
| 处理 | `src/translation/` | 翻译引擎 + 双层术语表 + 缓存 |
| 处理 | `src/rendering/` | 双语 HTML 渲染 + UI 注入 |
| 对话 | `src/chat/` | 论文上下文 + pi 桥 + 会话注册表 + HTTP/SSE API |
| 扩展 | `zotero-plugin/` | Zotero 插件 |
| 扩展 | `pi-extensions/` | 补 pi RPC 缺失命令（`/goto`、`/label`、`/where`） |
| 测试 | `tests/` | 单元 + 集成测试（未被 git 跟踪；fetch/render 类按旧 API 写，见 `tests/README.md`） |

## 3. 论文生成流水线

```
GET /api/generate?arxiv_id=X[&source=...&embed_images=0]
        │
        ▼
fetch_html(X)                        src/ingestion/fetcher.py
  ├─ sources 优先级（config.SOURCES）: arxiv_html → ar5iv → ar5ivist_docker
  ├─ 缓存：{source_dir(X)}/X.html + 同目录图片；命中即返回
  └─ 失败逐个降级；全部失败抛 RuntimeError(聚合原因)
        │ raw HTML
        ▼
mark_and_extract(html)               src/ingestion/parser.py
  └─ 一次遍历：插入 data-reaper-id="N" + 抽出 blocks[N]
     Block{type, level, text, math_map, label}
     math → MATH_N 占位；脚注 → FN_N（脚注内容单独成 note block）
        │ marked_html + blocks
        ▼
translate_blocks(blocks, cache=PaperCache)  src/translation/translator.py
  ├─ 命中 PaperCache（HTML hash 一致）→ 跳过解析+翻译
  ├─ 按 section 分组，每节一次 LLM 调用，全局线程池并发
  ├─ prompt 标注 REAPER_PARA_N，按编号对齐译文
  └─ 术语表（user > llm）注入 prompt；LLM 新术语回写
        │ blocks_with_zh
        ▼
render_bilingual_html(marked_html, blocks_with_zh, fp)  src/rendering/renderer.py
  ├─ 7 步注入：来源清洗 → ar5iv CSS 内嵌 → 资源处理 → TOC → 页脚
  │            → 译文 → 元数据/来源开关 JS
  └─ 输出 data/papers/X/process/reaper_html/index.html(+assets/)
```

### 关键设计决策

1. **保留 ar5iv 原生 CSS**：公式/表格/图注由 LaTeXML 渲染，自写 CSS 无法覆盖全部边缘情况；只做增量覆盖。
2. **按章节翻译**：LLM 看到完整章节上下文；超长节在段落边界平衡拆分。
3. **编号对齐**：`REAPER_PARA_N` 按编号匹配，LLM 少输出/合并输出也不错位。
4. **PaperCache v2**：一个文件同时存 HTML hash、blocks、译文，`merge_translations` 后立即落盘；
   崩溃不会留下「0 翻译」的缓存。
5. **画布包裹**：所有来源正文都在 `<div class="reaper-content">` 内，TOC/工具栏在画布外。
6. **三来源统一**：都产自 LaTeXML，类名体系一致；arxiv_html 保留原生 TOC 只改锚点，其余由 blocks 生成 TOC。

## 4. 对话架构（`src/chat/`）

**铁律：pi 是引擎，Reaper 只是通信与 UI。** 不自建 LLM 循环、会话存储、压缩逻辑。

```
插件 / prototype 页
   │  POST /api/chat            → 立即返回 {accepted}
   │  GET  /api/chat/stream     → SSE，常驻订阅（事件广播）
   ▼
src/chat/api.py           HTTP 表面 + 回环限制 + busy 守卫
   │
   ├─ context.py           论文 workspace：paper.md / blocks.json / OUTLINE.md / metadata.json
   ├─ session.py           每论文一个 PiBridge；懒加载 + 空闲回收；会话列表/解析/删除
   └─ bridge.py            spawn `pi --mode rpc`，单读取线程解析 JSONL → 订阅者队列
                              │
                              ▼
                        pi 进程（每论文一个）
                          cwd        = chat/workspace
                          tools      = read,grep,find,ls（只读白名单）
                          session-dir= chat/sessions
                          --session <path>（存在才传）
                          --append-system-prompt OUTLINE.md
                          --extension pi-extensions/reaper-tree.ts
```

### 4.1 上下文策略

完整 `paper.md`（带 `<!-- block:N -->` 锚点、公式还原为 `$...$`）放工作目录，
agent 用 `read`/`grep` 按需查；system prompt 只放**字节稳定**的 `OUTLINE.md`（无时间戳，
可命中 provider 的 prompt cache）。宏展开是字符串替换（`expand_macros.py`），不做
MathML→LaTeX 语义转换。

### 4.2 传输协议要点

| 环节 | 协议 | 关键约束 |
|---|---|---|
| 插件 ↔ 服务器 | HTTP + SSE | 不要用 `EventSource`（读不了自定义重连/中断）；不能用 `Zotero.HTTP.request`（XHR 无法流式） |
| 服务器 ↔ pi | stdio JSONL | 只按 `\n` 分帧；单 stdout 读取者；stdin 写入加锁；`accepted` ≠ 完成 |

### 4.3 会话模型

- **每篇论文一个 pi 进程**（不是每标签页、不是全局单进程）：上下文隔离，崩溃只影响自身；启动 < 1s，懒加载成本可忽略。
- 会话文件由 pi 写在 `chat/sessions/*.jsonl`；**它同时就是对话历史**，UI 的会话列表直接扫目录。
- 恢复用显式 `--session <path>`（可打开任意历史会话），不用 `--continue`。
- 切换/删除会话：`respawn` 迁移订阅者；删除优先系统废纸篓，且不允许删除正在使用的会话（先切走再删）。
- 树操作（navigate/label）走 `pi-extensions/reaper-tree.ts`：pi RPC 没有 `navigate_tree`，
  但扩展命令可通过 `prompt` 调用（已实测）。运行中一律拒绝（pi issue #5096）。

## 5. HTTP API 总表

| 方法 | 路径 | 说明 | 实现 |
|---|---|---|---|
| GET | `/api/generate?arxiv_id=` | 全流水线生成，返回 JSON（HTML 走 `/api/zotero_html/`） | `server.py` |
| GET | `/api/clear?arxiv_id=` | 清理该论文缓存（不动词典） | `server.py` |
| GET/POST | `/api/terms` | 读/写用户术语表 | `server.py` |
| GET | `/api/zotero_html/{id}` | 返回生成的双语 HTML | `server.py` |
| GET | `/` | 已生成论文列表 | `server.py` |
| GET/DELETE | `/api/stop` | 保存状态并退出 | `server.py` |
| POST | `/api/chat` | 发消息（立即返回 accepted） | `chat/api.py` |
| GET | `/api/chat/stream` | SSE 事件流（常驻） | `chat/api.py` |
| POST | `/api/chat/abort` | 中断当前 turn | `chat/api.py` |
| POST | `/api/chat/prepare` | 构建 agent workspace | `chat/api.py` |
| POST | `/api/chat/reset` | 在当前进程内新建会话 | `chat/api.py` |
| GET | `/api/chat/health` | 进程/连接状态 | `chat/api.py` |
| GET | `/api/chat/sessions` | 会话列表（含 current） | `chat/api.py` |
| GET | `/api/chat/messages` | 当前会话消息（来自 pi，权威） | `chat/api.py` |
| GET | `/api/chat/tree` | 会话树 + stats + 可分叉点 | `chat/api.py` |
| GET | `/api/chat/commands` | 扩展/模板/skill 命令 | `chat/api.py` |
| POST | `/api/chat/open` | 切换到指定会话 | `chat/api.py` |
| POST | `/api/chat/new` | 新建会话（fresh） | `chat/api.py` |
| POST | `/api/chat/rename` | 重命名会话 | `chat/api.py` |
| POST | `/api/chat/fork` | 从历史消息分叉 | `chat/api.py` |
| POST | `/api/chat/clone` | 复制当前分支 | `chat/api.py` |
| POST | `/api/chat/delete` | 删除会话（废纸篓优先） | `chat/api.py` |
| POST | `/api/chat/export` | 导出会话 HTML | `chat/api.py` |
| POST | `/api/chat/navigate` | 移动活跃分支（扩展 `/goto`） | `chat/api.py` |
| POST | `/api/chat/label` | 设置/清除节点标签（扩展） | `chat/api.py` |
| GET | `/api/chat/prototype` | 测试页（同源，无 CORS） | `chat/api.py` |

安全：`/api/chat/*` 默认仅回环（agent 可读文件），`chat.allow_remote: true` 才放开。

## 6. 配置

`config.json`（被 gitignore；模板 `config.json.example`）：

```json
{
  "api":      {"key": "...", "base_url": "...", "model": "...",
               "max_tokens": 16384, "params": {"reasoning_effort": "none"}},
  "server":   {"host": "0.0.0.0", "port": 16625},
  "translator": {"concurrency": 3},
  "sources":  [{"type": "arxiv_html"}, {"type": "ar5iv"}, {"type": "ar5ivist_docker"}],
  "ar5ivist_docker_image": "latexml/ar5ivist:2512.17",
  "chat":     {"idle_timeout": 900, "tools": "read,grep,find,ls",
               "pi_bin": "pi", "allow_remote": false,
               "extensions": ["pi-extensions/reaper-tree.ts"],
               "model": null, "thinking": null}
}
```

- `api.max_tokens` 必须覆盖推理 token（推理模型的 reasoning 也算在内）。
- `api.params` 原样合并进请求体；端点返回 400 时自动去掉 params 重试一次。
- `chat.model` / `chat.thinking` 为空即不传，用 pi 自己的配置（不做配置统一）。
- `translator.concurrency` 是**全局**翻译线程池大小，所有论文共享。

## 7. 数据模型

| 数据 | 位置 | 生产者 → 消费者 |
|---|---|---|
| 原始 HTML + 图片 | `papers/{id}/source/` | fetcher → parser/renderer/context |
| PaperCache v2 | `papers/{id}/process/translation_cache/cache.json` | translator ↔ server |
| Task 状态 | `papers/{id}/process/state.json` | task.py ↔ server |
| 双语 HTML | `papers/{id}/process/reaper_html/` | renderer → Zotero 插件 |
| agent workspace | `papers/{id}/chat/workspace/` | context.py → pi |
| pi 会话 | `papers/{id}/chat/sessions/*.jsonl` | pi（唯一写者）→ session.py（只读索引） |
| 术语表 | `dict/user_terms.json` + `dict/llm_terms.json` | dictionary.py（读-合并-写 + 原子替换） |
| 日志 | `logs/server.log` + `logs/papers/{id}.log` | logbook.py |

## 8. 并发模型

- 服务器：`ThreadingHTTPServer`；翻译用全局 `ThreadPoolExecutor(max_workers=translator.concurrency)`。
- 生成去重：`_inflight` 集合，同论文并发请求返回 202「正在处理中」。
- 术语表：跨实例共享锁 + 落盘前 read-merge-write + 原子替换（跨进程仍是「合并后覆盖」）。
- PaperCache / Task：各自带锁，变更即落盘。
- chat：`PiSessionRegistry` 一把 RLock 管进程表；每 bridge 一个 reader 线程 + 一个 stderr 线程；
  空闲回收线程每 60s 扫描一次（`idle_timeout` 默认 900s，有订阅者不回收）。

## 9. 非目标（明确不做）

- 不自建 LLM 调用/工具循环/会话存储/上下文压缩（pi 负责）。
- 不统一模型或 provider 配置（pi 负责）。
- 不实现多窗口/多客户端同步同一会话（等 pi 的多客户端能力）。
- 不做 PDF 解析（非 arXiv 来源是未来阶段）。
