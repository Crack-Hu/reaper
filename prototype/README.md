# prototype — 对话后端手工测试页

`chat.html` 是 Phase 0 的验证页，**不是产品 UI**：用来在没有 Zotero 面板时
手工验证「浏览器 → HTTP/SSE → Reaper 服务器 → pi」整条链路。

## 打开方式

```bash
# 1. 服务器已启动、论文已生成过 source/{id}.html
# 2. 准备 workspace
curl -s -X POST localhost:16625/api/chat/prepare \
     -H 'Content-Type: application/json' -d '{"arxiv_id":"2210.00921"}'
# 3. 打开
open http://127.0.0.1:16625/api/chat/prototype
```

页面顶部的输入框填 arxiv id，然后像聊天一样提问。

## 它演示了正确做法（产品面板要照抄）

- **一条常驻 SSE 订阅**（不是每条消息一个请求）：多个面板能同时看到同一轮回答。
- `fetch() + resp.body.getReader()` 读流；不用 `EventSource`，更不能用 `Zotero.HTTP.request`。
- 会话列表 / 切换 / 重命名 / 删除、会话树导航（`/goto`）、分叉/克隆、导出、
  上下文用量统计——都是直接调用产品 API，UI 可整体替换。

## 与产品 UI 的差别

视觉与交互是原型级；正式面板要求用 Zotero CSS 变量、Zotero 的视觉节奏、
markdown/公式自带渲染器（不引第三方 JS）。设计细节见 `CHAT_PLAN.md` §9。

保留它的意义：出问题时可以先用浏览器排除「是 pi 的问题还是 Zotero 的问题」。
