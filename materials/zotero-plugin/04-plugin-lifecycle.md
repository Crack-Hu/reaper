# Zotero 插件生命周期

## 生命周期钩子

```
                    ┌──────────────┐
                    │   Install    │ ← 首次安装/升级
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Startup    │ ← 插件加载/启用时
                    └──────┬───────┘
                           │
            ┌──────────────▼──────────────┐
            │  onMainWindowLoad           │ ← 主窗口打开（可能多次）
            │  (UI 初始化)                 │
            └──────────────┬──────────────┘
                           │
                    ┌──────▼───────┐
                    │  插件运行中   │
                    └──────┬───────┘
                           │
            ┌──────────────▼──────────────┐
            │  onMainWindowUnload         │ ← 主窗口关闭（可能多次）
            │  (清理窗口引用)              │
            └──────────────┬──────────────┘
                           │
                    ┌──────▼───────┐
                    │   Shutdown   │ ← 插件禁用/关闭时
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Uninstall  │ ← 卸载/被更新替换
                    └──────────────┘
```

## 各钩子详解

### install(data, reason)

- 插件**安装**或**升级**时调用
- 仅用于初始设置任务，插件尚未运行
- 例如：创建默认配置、初始化数据库结构

```javascript
function install(data, reason) {
  Zotero.debug("MyPlugin installed: " + reason);
}
```

### startup({ id, version, rootURI }, reason)

- 插件**加载/启用**时调用
- **所有不依赖窗口的初始化操作都应在此完成**
- Zotero 7+ 中，`Zotero`、`Services`、`Cc`、`Ci` 等全局对象在此已可用
- 可在此注册 MenuManager、Reader、ItemPaneManager 等 API

```javascript
async function startup({ id, version, rootURI }, reason) {
  Zotero.debug(`MyPlugin v${version} starting, reason: ${reason}`);
  
  // 初始化插件服务
  MyPlugin.init(rootURI);
  
  // 注册菜单（Zotero 8+ API）
  Zotero.MenuManager.registerMenu({ ... });
  
  // 注册 reader 事件
  Zotero.Reader.registerEventListener("createAnnotationContextMenu", handler, id);
  
  // 如果主窗口已经打开，手动调用 onMainWindowLoad
  await Promise.all(
    Zotero.getMainWindows().map(win => onMainWindowLoad({ window: win }))
  );
}
```

### onMainWindowLoad({ window })

- 主 Zotero **窗口打开**时调用
- 在一次会话中**可能被调用多次**（窗口关闭再打开）
- **所有 UI 修改必须在每次窗口打开时重新应用**
- 菜单注入、按钮添加、DOM 操作都在这里

```javascript
function onMainWindowLoad({ window }) {
  const doc = window.document;
  
  // 插入本地化文件
  window.MozXULElement.insertFTLIfNeeded("my-plugin.ftl");
  
  // 添加右键菜单项
  const itemMenu = doc.querySelector("#zotero-itemmenu");
  // ...
  
  // 添加工具栏按钮
  // ...
}
```

### onMainWindowUnload({ window })

- 主 Zotero **窗口关闭**时调用
- **必须**清理所有窗口引用、取消定时器
- DOM 元素会被自动销毁，但 JS 引用需要手动清理
- **防止内存泄漏**

```javascript
function onMainWindowUnload({ window }) {
  // 取消定时器
  if (window._myPluginTimer) {
    window.clearInterval(window._myPluginTimer);
  }
  
  // 清理事件监听
  // ...
}
```

### shutdown()

- 插件**禁用或 Zotero 关闭**时调用
- **必须清理 startup 中创建的所有资源**
- 可被禁用/卸载而不重启 Zotero，所以必须彻底清理

```javascript
function shutdown() {
  Zotero.debug("MyPlugin shutting down");
  
  // 清理所有窗口中的元素
  const windows = Zotero.getMainWindows();
  for (const win of windows) {
    win.document.querySelector('[href="my-plugin.ftl"]')?.remove();
    win.document.getElementById("my-plugin-style")?.remove();
  }
  
  // 注销菜单
  try {
    Zotero.MenuManager.unregisterMenu("my-plugin-menu");
  } catch (e) {}
  
  // 清理其他资源
  MyPlugin.destroy();
}
```

### uninstall(data, reason)

- 插件**卸载**时调用
- 执行最终清理
- Zotero 6 中 `Zotero` 对象不可用，7+ 中可用

```javascript
function uninstall(data, reason) {
  Zotero.debug("MyPlugin uninstalled");
}
```

---

## Reason 常量参考

```javascript
const {
  APP_STARTUP,
  APP_SHUTDOWN,
  ADDON_ENABLE,
  ADDON_DISABLE,
  ADDON_INSTALL,
  ADDON_UNINSTALL,
  ADDON_UPGRADE,
  ADDON_DOWNGRADE,
} = Components.interfaces.amIAddonManagerStartup;
```

| 常量 | 数值 | 含义 |
|------|-----|------|
| `APP_STARTUP` | 1 | Zotero 应用启动 |
| `APP_SHUTDOWN` | 2 | Zotero 应用关闭 |
| `ADDON_ENABLE` | 3 | 插件被启用 |
| `ADDON_DISABLE` | 4 | 插件被禁用 |
| `ADDON_INSTALL` | 5 | 插件被安装 |
| `ADDON_UNINSTALL` | 6 | 插件被卸载 |
| `ADDON_UPGRADE` | 7 | 插件被升级 |
| `ADDON_DOWNGRADE` | 8 | 插件被降级 |

---

## 调试技巧

## 信息来源

- Zotero 7 for Developers (官方): https://www.zotero.org/support/dev/zotero_7_for_developers
- 社区 Plugin Lifecycle 文档: https://windingwind.github.io/doc-for-zotero-plugin-dev/main/plugin-lifecycle
- Mozilla Bootstrapped Extensions: http://www.devdoc.net/web/developer.mozilla.org/en-US/docs/Mozilla/Add-ons/Bootstrapped_Extensions.html#Bootstrap_entry_points

1. 在 `startup()` 中添加:
```javascript
Zotero.debug("Hello, World! The plugin is loaded.");
```

2. 通过 `Help → Debug Output Logging → Enable` 启用调试输出

3. 启用/禁用插件验证 startup/shutdown 是否正常工作

4. 在 `shutdown()` 中彻底清理，避免多次启用/禁用后出现问题
