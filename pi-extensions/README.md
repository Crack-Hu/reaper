# pi-extensions — 补 pi RPC 缺口的扩展

## 为什么存在

pi 的 RPC 协议有 `get_tree` / `fork` / `clone`，但**没有 `navigate_tree`**
（TUI 的 `/tree` 导航只在 `ExtensionCommandContext` 上可用）。
而扩展命令**可以**通过 RPC 的 `prompt` 命令调用，所以本扩展把导航桥接出来。

这是通用模式：**以后遇到「TUI 能做但 RPC 没暴露」的功能，优先加扩展命令，
而不是引入 SDK / Node 服务。**

## 命令

| 命令 | 作用 | 结果回传 |
|---|---|---|
| `/goto <entryId> [summary]` | 移动活跃分支（等价 TUI `/tree` 导航） | `ctx.ui.notify()` |
| `/label <entryId> <text>` | 设置节点标签 | 同上 |
| `/unlabel <entryId>` | 清除节点标签 | 同上 |
| `/where` | 报告当前 leaf | 同上 |

RPC 模式下 `ui.notify` 作为 stdout 的 `extension_ui_request`（method=`notify`）到达，
前端显示为系统消息。

## 安全约束（不可移除）

`requireIdle(ctx)`：**agent 运行中（streaming/retry/compaction）一律拒绝结构操作**。
pi issue #5096：工具执行中导航会把 tool result 挂到错误的 `parentId`，供应商会报
`unexpected tool_use_id found in tool_result blocks`。API 层还有一个 409 守卫，两层都保留。

## 加载方式

`config.PI_EXTENSIONS` 默认指向本目录的 `reaper-tree.ts`（文件存在时），
`src/chat/bridge.py` 启动 pi 时传 `--extension <path>`。
命令列表可通过 `GET /api/chat/commands` 查看。

## 新增命令

在 `reaper-tree.ts` 的 `export default function (pi: ExtensionAPI)` 里
`pi.registerCommand(...)`；结构性操作先调 `requireIdle(ctx)`。
