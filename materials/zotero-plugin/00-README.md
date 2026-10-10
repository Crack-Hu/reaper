# Zotero Plugin Development - 调研资料索引

本文件夹包含 Zotero 插件开发的完整调研资料。针对你的需求（右键条目 → 弹出按钮 → 与后端通信 → 生成资料 → 添加回条目），以下是关键文档的导航。

## 文档结构

| 文件 | 内容 |
|------|------|
| `01-quickstart-guide.md` | **⭐ 快速上手：针对你需求的完整指南** |
| `02-zotero7-8-9-differences.md` | Zotero 7/8/9 版本差异与迁移要点 |
| `03-plugin-file-structure.md` | 插件文件结构：manifest.json, bootstrap.js, locale 等 |
| `04-plugin-lifecycle.md` | 插件生命周期：install/startup/shutdown/onMainWindowLoad 等 |
| `05-context-menu-api.md` | **⭐ 右键菜单 API：MenuManager.registerMenu() 完整文档** |
| `06-http-server-backend.md` | HTTP Server 与后端通信：自定义端点、local API |
| `07-javascript-api.md` | Zotero JavaScript API：操作条目、搜索、文件 I/O |
| `08-reference-plugins.md` | 参考插件列表：官方示例与社区推荐 |
| `09-zotero-plugin-template.md` | zotero-plugin-template 脚手架详情 |

## 核心发现总结

### 你的需求实现路径

1. **创建插件骨架**：使用 `zotero-plugin-template` (TypeScript) 或 `zotero-plugin-scaffold`
2. **添加右键菜单**：使用 `Zotero.MenuManager.registerMenu()` API，target 为 `"main/library/item"`
3. **与后端通信**：通过 `fetch()` 或 `XMLHttpRequest` 发送 HTTP 请求到本地后端
4. **获取选中条目**：`Zotero.getActiveZoteroPane().getSelectedItems()`
5. **修改条目数据**：使用 `Zotero.Items.get()`, `item.setField()`, `item.saveTx()`

### 关键版本差异

- **Zotero 7**：基于 Firefox 115 ESR，引入 manifest.json + bootstrap.js，废弃 XUL overlays
- **Zotero 8**：基于 Firefox 140 ESR，所有 JSM → ESM (.mjs)，移除 Bluebird，新增 MenuManager API
- **Zotero 9**：基于 Firefox 140+，主要变化是版本号更新，API 基本兼容 Zotero 8
- **兼容性设置**：`manifest.json` 中 `strict_max_version` 设置为 `"9.*"` 即可兼容 Zotero 9

## 信息来源

| 来源 | URL |
|------|-----|
| Zotero 官方插件文档 | https://www.zotero.org/support/dev/client_coding/plugin_development |
| Zotero 7 for Developers (官方) | https://www.zotero.org/support/dev/zotero_7_for_developers |
| Zotero 8 for Developers (官方) | https://www.zotero.org/support/dev/zotero_8_for_developers |
| Zotero JS API (官方) | https://www.zotero.org/support/dev/client_coding/javascript_api |
| Zotero Connector HTTP Server (官方) | https://www.zotero.org/support/dev/client_coding/connector_http_server |
| 社区开发者文档 (windingwind) | https://windingwind.github.io/doc-for-zotero-plugin-dev/ |
| 社区 Menu 文档 | https://windingwind.github.io/doc-for-zotero-plugin-dev/main/menu |
| 社区 Lifecycle 文档 | https://windingwind.github.io/doc-for-zotero-plugin-dev/main/plugin-lifecycle |
| 社区 File Structure 文档 | https://windingwind.github.io/doc-for-zotero-plugin-dev/main/plugin-file-structure |
| zotero-plugin-template | https://github.com/windingwind/zotero-plugin-template |
| zotero-plugin-scaffold | https://github.com/northword/zotero-plugin-scaffold |
| zotero-addon-template | https://github.com/MuiseDestiny/zotero-addon-template |
| zotero-plugin-toolkit | https://github.com/windingwind/zotero-plugin-toolkit |
| Make It Red（官方示例） | https://github.com/zotero/make-it-red |
| zotero-open-pdf | https://github.com/retorquere/zotero-open-pdf |
| Zotero 开发邮件列表 | https://groups.google.com/g/zotero-dev |
| Zotero 插件开发社区 | https://zotero-plugin.dev/ |
