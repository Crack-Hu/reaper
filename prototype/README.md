# prototype — 对话后端手工测试页

`chat.html` 是 Phase 0 的验证页，**不是产品 UI**：用来在没有 Zotero 面板时
手工验证「浏览器 → HTTP/SSE → Reaper 服务器 → pi」整条链路。
同时它也是**面板 UI 的参考实现**（全部交互已跑通，无框架、无构建）。

## 打开方式

```bash
# 1. 服务器已启动、论文已有 data/papers/{id}/source/{id}.html
# 2. 准备 workspace
curl -s -X POST localhost:16625/api/chat/prepare \
     -H 'Content-Type: application/json' -d '{"arxiv_id":"2210.00921"}'
# 3. 打开（顶部输入框填 arxiv id）
open http://127.0.0.1:16625/api/chat/prototype
```

## 正确做法（产品面板要照抄）

- **一条常驻 SSE 订阅**（不是每条消息一个请求）：多个面板能同时看到同一轮回答。
- `fetch() + resp.body.getReader()` 读流；不用 `EventSource`，更不能用 `Zotero.HTTP.request`。
- 会话列表 / 切换 / 重命名 / 删除、会话树导航（`/goto` `/label`）、分叉/克隆、导出、
  上下文用量统计，全部直接调用产品 API。

## 移植映射（→ Zotero 面板）

| 要移植的能力 | prototype 里的实现 |
|---|---|
| SSE 读取 + 事件分发（`agent_*` / `reaper_bridge`） | 页面底部的流循环（`fetch` + `getReader`） |
| 流式增量渲染 + 自动滚动策略 | `paint()`、`ensureRun()`、`showThinking()`、`scroll()`（用户上滚后停止） |
| markdown 渲染 | `renderMarkdown()`（注意 **LaTeX 分隔符归一化**：LLM 会混用 `$…$`、`\(…\)`、`` `$x$` ``） |
| 公式渲染 | `renderMath()`（原型是轻量实现；面板若用 KaTeX，建议 `output:"mathml"` 免 CSS） |
| 历史回填 | `loadHistory()`、`renderHistoryMessage()`（含工具调用折叠、thinking 折叠） |
| 会话列表 UI | `loadSessions()`、`renderSessions()`、`openSessionById()`、`renameSessionById()`、`deleteSessionById()` |
| 会话树 + 导航/标签 | `loadTree()`、`flattenTree()`（TUI 风格连接线）、`navigateTo()`、`labelEntry()`、`forkFrom()` |
| 状态/用量条 | `renderStats()`（`/api/chat/tree` 的 stats） |

移植时注意：面板在 **Zotero chrome 作用域**（JS 正常执行），但**渲染不能用第三方 JS**
（system principal 环境），markdown/公式要自己实现精简版；颜色全用 Zotero CSS 变量。

## 与产品 UI 的差别

视觉与交互是原型级；正式面板要求 Zotero 的视觉节奏（描边、变量、字号），
设计细节见 `CHAT_PLAN.md` §9。保留它的意义：出问题时可以先用浏览器排除
「是 pi 的问题还是 Zotero 的问题」。
