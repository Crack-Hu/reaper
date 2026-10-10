# Zotero 插件文件结构

## 核心文件

```
my-plugin/
├── manifest.json          # [必须] 插件元信息
├── bootstrap.js           # [必须] 插件入口脚本
├── prefs.js               # [可选] 默认偏好设置
├── locale/                # [可选] 本地化文件
│   ├── en-US/
│   │   └── my-plugin.ftl
│   └── zh-CN/
│       └── my-plugin.ftl
├── icons/                 # [推荐] 插件图标
│   └── icon.svg
├── content/               # 额外 JS/资源文件
└── style.css              # [可选] 样式文件
```

---

## manifest.json 详解

```json
{
  "manifest_version": 2,           // [必须] 固定值 2
  "name": "My Plugin",             // [必须] 插件名称
  "version": "1.0.0",              // [必须] 语义化版本号
  "description": "Description",    // 描述，显示在插件管理器
  "author": "Your Name",           // 作者名
  "homepage_url": "https://...",   // 主页链接，显示在插件管理器
  "icons": {
    "48": "icons/icon.svg",        // 建议使用 SVG
    "96": "icons/icon.svg"
  },
  "applications": {
    "zotero": {                    // [必须] Zotero 特定配置
      "id": "my-plugin@example.com",     // [必须] 唯一标识符，格式：xxx@domain
      "update_url": "https://.../updates.json",  // 自动更新地址
      "strict_min_version": "6.999",             // 最低兼容版本
      "strict_max_version": "9.*"                // 最高兼容版本
    }
  }
}
```

### 字段说明

| 字段 | 必须 | 说明 |
|-----|------|------|
| `manifest_version` | ✅ | 固定为 `2` |
| `name` | ✅ | 显示在插件管理器的名称 |
| `version` | ✅ | 语义化版本，如 `1.0.0` |
| `applications.zotero.id` | ✅ | 全局唯一标识符，如 `make-it-red@zotero.org` |
| `applications.zotero.strict_min_version` | 推荐 | 最低兼容的 Zotero 版本，Zotero 7+ 最低 `"6.999"` |
| `applications.zotero.strict_max_version` | 推荐 | 最高兼容版本，设置为已测试版本号的 `x.x.*` |
| `description` | 推荐 | 在插件管理器中显示 |
| `homepage_url` | 推荐 | 插件主页 |
| `icons` | 推荐 | 建议使用 SVG 适配亮/暗主题 |
| `applications.zotero.update_url` | 可选 | JSON 格式的自动更新清单 URL |

### SVG 图标最佳实践

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
  <rect width="48" height="48" rx="8" fill="context-fill" stroke="context-stroke"/>
</svg>
```

- 使用 `fill="context-fill"` 和 `stroke="context-stroke"` 适配主题颜色
- 避免硬编码颜色（黑/白）
- 在亮色和暗色主题下都要测试

---

## bootstrap.js 详解

bootstrap.js 是插件入口文件，必须导出以下生命周期函数：

```javascript
// 必须导出的函数

function install(data, reason) {}
// 插件安装或升级时调用

async function startup({ id, version, rootURI }, reason) {}
// 插件启动时调用，在此初始化一切

function onMainWindowLoad({ window }) {}
// 主窗口打开时调用（可能多次）
// 在此处理所有 UI 修改

function onMainWindowUnload({ window }) {}
// 主窗口关闭时调用
// 必须清理所有窗口引用，防止内存泄漏

function shutdown() {}
// 插件关闭/禁用时调用
// 清理所有资源

function uninstall(data, reason) {}
// 插件卸载时调用
```

### 参数说明

**data 参数（startup/install/shutdown/uninstall）**：
```javascript
{
  id: "my-plugin@example.com",  // 插件 ID
  version: "1.0.0",             // 插件版本
  rootURI: "jar:file:///..."    // 指向插件文件的 URL（总是以 / 结尾）
}
```

**reason 参数**：可以使用以下常量判断触发原因：
- `APP_STARTUP` - Zotero 启动
- `APP_SHUTDOWN` - Zotero 关闭
- `ADDON_ENABLE` - 插件被启用
- `ADDON_DISABLE` - 插件被禁用
- `ADDON_INSTALL` - 插件被安装
- `ADDON_UNINSTALL` - 插件被卸载
- `ADDON_UPGRADE` - 插件升级
- `ADDON_DOWNGRADE` - 插件降级

**窗口 hooks 参数**：
```javascript
{ window: Window } // 目标窗口对象
```

### Zotero 7 兼容注意事项

Zotero 6 提供 `resourceURI` (nsIURI) 而非 `rootURI` (string)。兼容方案：

```javascript
function startup(data, reason) {
  let rootURI = data.rootURI || data.resourceURI.spec;
}
```

Zotero 6 中 `Zotero` 对象在 startup 时可能尚未可用，需要等待：
```javascript
// 参考 make-it-red 1.2 版本的处理方式
```

### 使用 rootURI 加载资源

```javascript
// 加载 CSS
var styleURL = rootURI + 'style.css';

// 加载图标
var iconURL = rootURI + 'icons/icon.svg';

// 加载 JS 模块
var moduleURL = rootURI + 'modules/mymodule.mjs';
```

---

## prefs.js - 默认偏好设置

```javascript
// prefs.js
pref("extensions.my-plugin.option1", "default value");
pref("extensions.my-plugin.option2", 42);
pref("extensions.my-plugin.option3", true);
```

- 文件放在插件根目录
- Zotero 7+ 会在安装/启用时和每次启动时读取
- 通过 `Zotero.Prefs.get("extensions.my-plugin.option1")` 读取
- 通过 `Zotero.Prefs.set("extensions.my-plugin.option1", value)` 设置

---

## locale/ - Fluent 本地化

### 文件结构

```
locale/
├── en-US/
│   ├── my-plugin.ftl
│   └── preferences.ftl
├── zh-CN/
│   ├── my-plugin.ftl
│   └── preferences.ftl
└── fr-FR/
    └── my-plugin.ftl
```

### Fluent 语法示例

```ftl
# my-plugin.ftl

# 简单字符串
my-plugin-title = 我的插件

# 属性
my-plugin-menu-item =
    .label = 发送到后端

# 带变量的字符串
my-plugin-greeting = 你好，{ $name }！

# 复数形式
my-plugin-item-count = { $count ->
    [one] 一个条目
   *[other] { $count } 个条目
}
```

### 在 DOM 中使用

```html
<!-- XHTML 中 -->
<link rel="localization" href="my-plugin.ftl"/>
<button data-l10n-id="my-plugin-menu-item"/>

<!-- 带参数 -->
<button data-l10n-id="my-plugin-greeting" data-l10n-args='{"name": "World"}'/>
```

### 在 JS 中动态使用

```javascript
// 插入 Fluent 文件到窗口
window.MozXULElement.insertFTLIfNeeded("my-plugin.ftl");

// 动态设置本地化
document.l10n.setAttributes(element, "my-plugin-menu-item");

// 获取本地化字符串
var msg = await document.l10n.formatValue("my-plugin-greeting", { name: "World" });

// 清理
doc.querySelector('[href="my-plugin.ftl"]').remove();
```

### 注意事项

## 信息来源

- Zotero 7 for Developers (官方): https://www.zotero.org/support/dev/zotero_7_for_developers
- 社区 File Structure 文档: https://windingwind.github.io/doc-for-zotero-plugin-dev/main/plugin-file-structure
- Fluent 文档: https://projectfluent.org/fluent/guide/

- Fluent ID 在 DOM 文档内是全局的，必须用插件名做前缀
- FTL 文件名也是全局的，用插件名命名
- `.dtd` 和 `.properties` 仍支持但将被移除
