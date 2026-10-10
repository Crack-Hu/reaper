# Zotero 7 / 8 / 9 版本差异与迁移指南

## 版本时间线

| 版本 | Firefox 基础 | 发布时间 | 关键变化 |
|------|-------------|---------|---------|
| Zotero 6 | Firefox 60 ESR | 老版本 | XUL overlays, install.rdf |
| Zotero 7 | Firefox 115 ESR | 2024 | manifest.json, bootstrap.js, 重大平台升级 |
| Zotero 8 | Firefox 140 ESR | 2026.01 | JSM→ESM, 移除 Bluebird, MenuManager API |
| Zotero 9 | Firefox 140+ | 2026.04 | 版本号更新, API 基本兼容 Zotero 8 |

---

## Zotero 6 → Zotero 7 重大变化

### 1. install.rdf → manifest.json

**旧 (Zotero 6)**:
```xml
<!-- install.rdf -->
<RDF>
  <Description>
    <em:id>my-plugin@example.com</em:id>
    <em:name>My Plugin</em:name>
    ...
  </Description>
</RDF>
```

**新 (Zotero 7+)**:
```json
{
  "manifest_version": 2,
  "name": "My Plugin",
  "version": "1.0",
  "applications": {
    "zotero": {
      "id": "my-plugin@example.com",
      "strict_min_version": "6.999",
      "strict_max_version": "9.*"
    }
  }
}
```

### 2. XUL Overlays → bootstrap.js

**旧 (Zotero 6)**: 使用 XUL overlay 注入 UI 元素
```xml
<!-- overlay.xul -->
<overlay id="my-overlay">
  <script src="my-script.js"/>
  <menupopup id="zotero-itemmenu">
    <menuitem label="My Action" oncommand="myAction()"/>
  </menupopup>
</overlay>
```

**新 (Zotero 7+)**: 使用 bootstrap.js 编程式注入
```javascript
// bootstrap.js
function startup({ id, version, rootURI }, reason) {
  // 在 startup 或 onMainWindowLoad 中手动操作 DOM
}

function onMainWindowLoad({ window }) {
  const doc = window.document;
  // 手动创建和插入 UI 元素
}
```

### 3. chrome.manifest → 运行时注册

**旧**: chrome.manifest 文件注册 chrome:// URLs
**新**: 在 startup 中通过 `aomStartup.registerChrome()` 注册

### 4. 本地化变更：.dtd/.properties → Fluent (.ftl)

**旧 (.dtd)**:
```xml
<!ENTITY my-plugin.label "My Label">
```

**新 (.ftl)**:
```ftl
my-plugin-label = 
    .label = My Label
```

### 5. 平台 API 变化 (Firefox 60→115)

- `.xul` → `.xhtml`
- XUL elements → Custom Elements
- `OS.File`/`OS.Path` → `IOUtils`/`PathUtils`
- `<browser>` → `<browser maychangeremoteness="true">`
- XUL `<textbox>` → HTML `<input type="text">`
- XUL `<progressmeter>` → HTML `<progress>`
- `createElement()` → `createXULElement()` (对于 XUL 元素)
- `nsIDOMParser` → `new DOMParser()`
- `nsIDOMSerializer` → `new XMLSerializer()`

---

## Zotero 7 → Zotero 8 变化

### Mozilla 平台变化 (Firefox 115→140)

#### Firefox 128 阶段 (Zotero 7.1 beta):

- 移除手动 `Services.jsm` imports
- 移除 `nsIScriptableUnicodeConverter`，替换 `convertToByteArray()` 和 `convertToInputStream()`
- 移除 `nsIOSFileConstantsService`
- `XPCOMUtils.defineLazyGetter` → `ChromeUtils.defineLazyGetter`
- 移除 `nsIDOMChromeWindow`
- `addLogin` → `addLoginAsync`
- `DataTransfer#types`: `contains()` → `includes()`

#### Firefox 140 阶段 (Zotero 8 正式版):

- **所有 JSM → ESM**：`.jsm` 文件转换为 `.mjs` 或 `.sys.mjs`
  - Zotero 提供自动迁移脚本：`migrate-fx140/migrate.py esmify`
- **移除 Bluebird**：所有 Bluebird Promise 替换为标准 Promise
  - `Zotero.Promise.delay()` 和 `Zotero.Promise.defer()` 仍然可用（兼容）
  - 移除 `Zotero.spawn()`
  - 提供自动迁移脚本：`migrate-fx140/migrate.py asyncify`
- 全局 imports 不再支持
- 所有 ESM 运行在 strict mode
- 移除非 macOS 的 `Services.appShell.hiddenDOMWindow`
- Preference panes 现在有独立全局作用域

### 新增功能

- **MenuManager API**：`Zotero.MenuManager.registerMenu()` 正式 API 用来注册菜单
- **ItemPaneManager API**：`Zotero.ItemPaneManager.registerSection()` / `registerInfoRow()`
- **ItemTreeManager API**：`Zotero.ItemTreeManager.registerColumn()`

---

## Zotero 8 → Zotero 9 变化

### 关键变化

1. **基于 Firefox 128+**（可能 Firefox 140+）: 基础平台与 Zotero 8 类似
2. **ChromeUtils.import 移除**: 代码必须使用 `ChromeUtils.importESModule()`
3. **兼容性版本号**: 插件只需在 manifest.json 中设置 `"strict_max_version": "9.*"` 即可安装
4. **安全性增强**: 添加了对网站触发 Zotero 操作的安全保护
5. **SVG 图标**: 大多数 PNG 图标被移除或替换为 SVG 版本

### 兼容性验证

大多数为 Zotero 8 编写的插件只需要：
1. 更新 `manifest.json` 中 `strict_max_version` 为 `"9.*"`
2. 确保不使用已被移除的 API（如 `ChromeUtils.import`）
3. Smoke test（基本功能测试）

许多社区插件已经通过这个简单的步骤成功迁移到 Zotero 9。

### 已知不兼容

- 使用 `ChromeUtils.import` (而非 `ChromeUtils.importESModule`) 的旧代码需要重构
- 直接依赖旧版 Firefox 特定 API 的插件可能需要更新

---

## manifest.json 版本号设置总结

```json
{
  "applications": {
    "zotero": {
      "strict_min_version": "6.999",
      "strict_max_version": "9.*"
    }
  }
}
```

| 目标版本 | strict_min_version | strict_max_version |
|---------|-------------------|-------------------|
| 仅 Zotero 7 | `"6.999"` | `"7.0.*"` |
| 仅 Zotero 8 | `"7.0"` | `"8.0.*"` |
| 仅 Zotero 9 | `"8.0"` | `"9.*"` |
| Zotero 7-9 (最广兼容) | `"6.999"` | `"9.*"` |

> **建议**：设置 `"9.*"` 覆盖当前最新版本，后续可通过 update manifest 动态更新兼容性而无需发布新版本。

---

## 迁移检查清单

## 信息来源

- Zotero 7 for Developers (官方): https://www.zotero.org/support/dev/zotero_7_for_developers
- Zotero 8 for Developers (官方): https://www.zotero.org/support/dev/zotero_8_for_developers
- Zotero 9 兼容性讨论: https://github.com/windingwind/zotero-plugin-template/issues/314
- Zotero 8 Beta 公告: https://groups.google.com/g/zotero-dev/c/uQhEGkJEzYs

从 Zotero 7 迁移到 8/9：

- [ ] 更新 manifest.json: `strict_max_version` → `"9.*"`
- [ ] 将所有 .jsm imports 转换为 .mjs imports
- [ ] 移除 Bluebird 依赖（使用标准 async/await）
- [ ] 替换 `Services.console` 相关调用
- [ ] 确认 preference panes 不依赖跨 pane 的 var
- [ ] 使用新 MenuManager API 替代手动 DOM 操作（可选但推荐）
- [ ] 测试 SVG 图标在亮/暗主题下的显示
- [ ] 运行 smoke test
