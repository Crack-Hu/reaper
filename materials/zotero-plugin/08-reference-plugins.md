# 参考插件与模板

## 官方/社区脚手架

### 1. zotero-plugin-template（最推荐）
- **地址**: https://github.com/windingwind/zotero-plugin-template
- **语言**: TypeScript
- **特点**:
  - 最成熟的社区模板
  - 自动构建/打包 XPI
  - 热重载开发
  - 内置 zotero-plugin-toolkit 工具库
  - 支持 GitHub Actions 自动发布
  - 持续维护，兼容 Zotero 7/8/9
- **适用场景**: 新插件的首选模板

### 2. zotero-plugin-scaffold
- **地址**: https://github.com/northword/zotero-plugin-scaffold
- **语言**: JavaScript/TypeScript
- **特点**:
  - 更轻量的构建工具
  - CI/CD 集成
  - 支持 npm 和 yarn

### 3. zotero-addon-template
- **地址**: https://github.com/MuiseDestiny/zotero-addon-template
- **语言**: TypeScript
- **特点**:
  - 简化模板，减少 boilerplate
  - 适合快速原型

### 4. zotero-plugin-toolkit
- **地址**: https://github.com/windingwind/zotero-plugin-toolkit
- **文档**: https://windingwind.github.io/zotero-plugin-toolkit/
- **特点**: 工具库，简化 DOM 操作、菜单管理、快捷键注册等
- **API 示例**:
```typescript
import { MenuManager } from "zotero-plugin-toolkit";
const menuManager = new MenuManager();
menuManager.register("item", {
  tag: "menuitem",
  label: "My Action",
  commandListener: () => { /* ... */ }
});
```

---

## 官方示例插件

### 5. Make It Red（官方）
- **地址**: https://github.com/zotero/make-it-red
- **特点**:
  - Zotero 官方开发团队维护
  - 演示 bootstrap.js 基本结构
  - 演示 Zotero 6 ↔ Zotero 7 兼容
  - 演示 MenuManager API
  - 多个版本展示不同兼容策略

---

## 推荐研究的社区插件

### 6. zotero-open-pdf
- **地址**: https://github.com/retorquere/zotero-open-pdf
- **维护者**: retorquere (也是 Better BibTeX 作者)
- **特点**:
  - 有 Zotero 7 和 Zotero 8/9 两个版本分支
  - 通过右键菜单添加操作
  - **非常适合学习如何在条目右键菜单中添加自定义操作**
- **兼容性**: Zotero 7/8/9

### 7. zotero-better-bibtex
- **地址**: https://github.com/retorquere/zotero-better-bibtex
- **特点**:
  - 最复杂的 Zotero 插件之一
  - TypeScript 编写
  - 大量使用 Zotero JS API
  - 右键菜单、偏好设置、导出功能
  - **学习复杂插件架构的最佳参考**

### 8. zotero-ai-explain
- **地址**: https://github.com/vishnutskumar/zotero-ai-explain
- **特点**:
  - AI 相关功能，类似你的需求
  - 右键菜单调用外部 API
  - 演示与后端通信的模式

### 9. ZotSeek
- **地址**: https://github.com/introfini/ZotSeek
- **特点**:
  - 在 Zotero HTTP Server 上注册自定义端点
  - 提供 MCP server 和 REST API
  - **学习如何利用 Zotero 内置 HTTP Server**

### 10. zotero-mcp (kujenga)
- **地址**: https://github.com/kujenga/zotero-mcp
- **特点**:
  - Python 实现的外部服务
  - 通过 Zotero Local API 通信
  - **学习外部程序如何访问 Zotero 数据**

---

## 关键社区资源

| 资源 | 地址 |
|------|------|
| 社区开发者文档 | https://windingwind.github.io/doc-for-zotero-plugin-dev/ |
| Zotero 官方插件文档 | https://www.zotero.org/support/dev/client_coding/plugin_development |
| Zotero 7 for Developers | https://www.zotero.org/support/dev/zotero_7_for_developers |
| Zotero 8 for Developers | https://www.zotero.org/support/dev/zotero_8_for_developers |
| Zotero JS API | https://www.zotero.org/support/dev/client_coding/javascript_api |
| Connector HTTP Server | https://www.zotero.org/support/dev/client_coding/connector_http_server |
| Zotero 开发论坛 | https://groups.google.com/g/zotero-dev |
| 插件开发网站 | https://zotero-plugin.dev/ |

---

## 针对你需求的推荐学习路径

1. **克隆并构建** `zotero-plugin-template`
2. **研读** `examples.ts` 中的 `registerRightClickMenuItem()` 示例
3. **参考** `zotero-open-pdf` 的 bootstrap.js 了解右键菜单实现
4. **参考** `zotero-ai-explain` 了解与后端通信的模式
5. **使用** `Zotero.MenuManager.registerMenu()` API（target: `"main/library/item"`）
6. **使用** `fetch()` 向本地后端发 HTTP 请求
7. **使用** `item.setField()` + `item.saveTx()` 将结果写回条目

## 信息来源

- GitHub 仓库（见上文各插件链接）
- Zotero 社区开发者文档: https://windingwind.github.io/doc-for-zotero-plugin-dev/
- Zotero 插件开发社区: https://zotero-plugin.dev/
- Zotero 开发邮件列表: https://groups.google.com/g/zotero-dev
