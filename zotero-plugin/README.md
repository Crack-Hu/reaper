# zotero-plugin — Zotero 插件

在 Zotero 条目上提供「下载 arXiv PDF / 生成双语 HTML / 补全资源」的菜单，并把
生成的 HTML 作为附件挂到条目下。**对话面板是本目录的下一步工作**（见文末指南）。

## 文件

| 文件 | 职责 |
|---|---|
| `bootstrap.js` | 插件主体：菜单注册、arXiv ID 识别、调后端、附件管理 |
| `manifest.json` | 插件元数据（当前版本 0.9.0；`strict_min_version` 8.0.1） |
| `prefs.js` | 默认偏好：`attachmentName`、`serverPort` |
| `content/preferences.xhtml` | 首选项界面（Zotero → 设置 → Reaper） |
| `setup.sh` | 打包 XPI 并安装到 Zotero profile（兼容 Zotero 9/10 的 profile 命名） |

打包产物 `reaper-for-zotero.xpi` 是构建缓存（gitignore），由 `setup.sh` 生成。

## 菜单与流程（已有）

```
条目右键 → Reaper
├── Download from Arxiv          下载 PDF 并附加
├── Generate Bilingual HTML      调后端生成 → 作为子附件
│   └── 重试菜单可按来源指定：arxiv.org / ar5iv / ar5ivist
└── Complete Resources           补全缺失的图片等资源
```

- arXiv ID 识别顺序：URL → Extra（`arxiv: ...`）→ DOI（`10.48550/arxiv....`），保留 `v2` 版本后缀。
- 后端调用：`GET /api/generate?arxiv_id=...` → 等 JSON → `GET /api/zotero_html/{id}` 取 HTML。
- **202 处理**：同论文正在生成时后端返回 202「正在处理中」，插件显示等待提示而不是报错。
- 附件命名模板：`attachmentName`（`{arxiv_id}` 占位）。

## 通用约定

- 插件只发 HTTP，不 spawn 子进程（一律走 `http://localhost:{serverPort}`）。
- 请求必须从**插件作用域**发起：Zotero reader 的 iframe 注册了 `BlockingObserver`，
  会取消 frame 内的 http(s) 请求。
- 流式响应只能用 `fetch() + resp.body.getReader()`；`Zotero.HTTP.request` 基于 XHR，
  无法流式，`EventSource` 也不适用（自定义中断/重连语义）。

## 安装

```bash
bash zotero-plugin/setup.sh     # 打包 + 安装，重启 Zotero 生效
```

---

# 对话面板实现指南（下一步工作）

> 目标：在 Zotero 的条目面板（item pane）和 PDF 阅读器的 context pane 中提供对话界面。
> **后端已全部完成**（`src/chat/`），这一步基本只是 UI 工作。
> 设计调研见 `CHAT_PLAN.md` §9（UI 设计）、§10（参考实现）、§D8（面板位置）；
> 交互原型见 `prototype/chat.html`（可直接对照移植）。

## 形态

- **主形态**：`Zotero.ItemPaneManager.registerSection()`（Zotero 7+ API）。
  同一个 section 会自动出现在 PDF 阅读器的 context pane —— 官方行为，无需 hack。
- **可选**：浮动窗口（`mainWindow.openDialog` + 空 xhtml 壳），用偏好 `panelMode` 切换。
  原型 `syt2/paper-chat-for-zotero` 两种形态共用一套 DOM。

## 需要新增/修改的文件

```
content/chat.xhtml        面板结构（消息列表 + 输入框）
content/chat.js           面板逻辑（SSE 读取、会话列表、markdown/公式渲染）
content/chat.css          样式（全部用 Zotero CSS 变量）
content/locale/*.ftl      section 的 l10nID（4 行即可，放 locale/ 自动加载）
bootstrap.js              注册/反注册 section；reader 选区事件（Phase 2）
prefs.js                  面板相关偏好（如 panelMode）
```

## 硬约束（每条都对应真实失败）

1. **请求从插件作用域发起**（reader frame 内会被 BlockingObserver 取消）。
2. **一条常驻 SSE 订阅**：`GET /api/chat/stream?arxiv_id=`，连接不随每轮消息重建，
   多个面板能同时看到每一轮。
3. **颜色用 Zotero CSS 变量**（`--color-sidepane`、`--fill-primary`、`--color-accent`…），
   硬编码会让面板在暗色主题下变成一块白板。
4. **section 会被销毁重建**：状态不要放 DOM，`onDestroy` 里清 notifier；
   `onRender` 必须同步，重活放 `onAsyncRender`。
5. **不要每个 token 重渲染整条消息**（O(n²) 抖动，别人踩过）——节流或在段落边界重渲染。
6. 附件 HTML 里的 `<script>` 在 Zotero reader 里**不执行**（`allow-scripts` 未开，
   且 reader 用 srcdoc 加载）。现有 TOC/主题/译文开关在 reader 内是否可用**待真机确认**；
   若不可用，退路是 CSS-only 控件或主要阅读场景改用外部浏览器。

## 面板要用的端点（全部已实现，见 `ARCHITECTURE.md` §5）

| 用途 | 端点 |
|---|---|
| 发消息 | `POST /api/chat`（立即返回 accepted） |
| 收流 | `GET /api/chat/stream?arxiv_id=`（SSE，常驻） |
| 中断 | `POST /api/chat/abort` |
| 准备论文工作区 | `POST /api/chat/prepare` |
| 历史 | `GET /api/chat/messages` |
| 会话列表 / 切换 / 新建 / 重命名 / 删除 | `GET /api/chat/sessions`、`POST open`、`POST new`、`POST rename`、`POST delete` |
| 会话树 / 跳转 / 标签 | `GET /api/chat/tree`、`POST /api/chat/navigate`、`POST /api/chat/label` |
| 分叉 / 克隆 / 导出 | `POST /api/chat/fork`、`POST /api/chat/clone`、`POST /api/chat/export` |
| 进程状态 | `GET /api/chat/health` |

## 从测试页移植

`prototype/chat.html` 已把全部交互跑通（无框架）。要移植什么、对照哪些函数，
见 `prototype/README.md` 的「移植映射」。

## 参考实现与许可

- ⭐ `yilewang/llm-for-zotero`（**AGPL — 只读不抄**）：把外部 agent harness 当引擎、
  插件只做 UI，与本项目架构最同构。
- ⭐ `luisherrmann/llmz`（**MIT — 可抄**）：唯一可用的 `ItemPaneManager.registerSection`
  完整例子（含 FTL、CSS 预取、卸载）。
- 其余同类插件的坑与许可清单：`CHAT_PLAN.md` §10。

## 验收标准（Phase 1，摘自 `CHAT_PLAN.md` §8）

- [ ] 在 Zotero 打开有 Reaper 附件的论文 → 面板可提问 → 30 秒内看到流式回答
- [ ] 回答里的公式与 TeX 一致（人工抽查 3 问）
- [ ] 关掉 Zotero 再打开，对话历史还在（会话持久化）
- [ ] agent 无法写文件（只读白名单生效）

**前置验证（Phase 0.5，先做再写 UI）**

- [ ] 0.5a：item pane section 能渲染，并能从插件作用域流式读 localhost
- [ ] 0.5b：snapshot 附件的 `renderTextSelectionPopup` 会触发，
      `params.annotation.position.value` 能映射到 `#reaper-block-N`
      （⚠️ 依赖渲染器补 block id，见 `HANDOFF.md` §7.2）
