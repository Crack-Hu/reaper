# zotero-plugin — Zotero 插件

在 Zotero 条目上提供「下载 arXiv PDF / 生成双语 HTML / 补全资源」的菜单，并把
生成的 HTML 作为附件挂到条目下。

## 文件

| 文件 | 职责 |
|---|---|
| `bootstrap.js` | 插件主体：菜单注册、arXiv ID 识别、调后端、附件管理 |
| `manifest.json` | 插件元数据（当前版本 0.9.0；`strict_min_version` 8.0.1） |
| `prefs.js` | 默认偏好：`attachmentName`、`serverPort` |
| `content/preferences.xhtml` | 首选项界面（Zotero → 设置 → Reaper） |
| `setup.sh` | 打包 XPI 并安装到 Zotero profile（Zotero 9/10 profile 名兼容） |

打包产物 `reaper-for-zotero.xpi` 是构建缓存（gitignore），由 `setup.sh` 生成。

## 菜单与流程

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

## 约定

- 插件只发 HTTP，不 spawn 子进程（跨进程通信一律走 `http://localhost:{serverPort}`）。
- 请求必须从**插件作用域**发起：Zotero reader 的 iframe 注册了 `BlockingObserver`，
  会取消 frame 内的 http(s) 请求。
- 流式响应只能用 `fetch() + resp.body.getReader()`；`Zotero.HTTP.request` 基于 XHR，无法流式。

## 规划中（尚未实现）

对话面板：`Zotero.ItemPaneManager.registerSection()`（Zotero 7+），见
`HANDOFF.md` §7 与 `CHAT_PLAN.md` §D8。需要的文件：`content/chat.xhtml`、
`chat.js`、`chat.css`、`content/locale/*.ftl`。

## 安装

```bash
bash zotero-plugin/setup.sh     # 打包 + 安装，重启 Zotero 生效
```
