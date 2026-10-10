# ⭐ 快速上手：针对你的需求实现 Zotero 插件

## 你的需求描述

> 右键条目 → 弹出按钮 → 点击按钮与后端程序通信 → 生成一些资料 → 将资料添加回条目

这是一个典型的 Zotero 插件工作流。下面给出完整的实现方案。

---

## 第一步：创建插件骨架

### 推荐方案：使用 zotero-plugin-template

```bash
git clone https://github.com/windingwind/zotero-plugin-template.git my-zotero-plugin
cd my-zotero-plugin
npm install
```

这是社区最成熟的 TypeScript 模板，提供：
- TypeScript 支持
- 热重载开发
- 自动打包 XPI
- 内置常用工具类

### 最小文件结构

```
my-plugin/
├── manifest.json        # 插件元信息（必须）
├── bootstrap.js         # 插件入口（必须）
├── prefs.js             # 默认偏好设置
├── locale/
│   └── en-US/
│       └── my-plugin.ftl  # Fluent 本地化
└── icons/
    └── icon.svg
```

---

## 第二步：manifest.json 配置

```json
{
  "manifest_version": 2,
  "name": "My Zotero Plugin",
  "version": "1.0.0",
  "description": "Right-click to call backend and add data",
  "author": "Your Name",
  "icons": {
    "48": "icons/icon.svg",
    "96": "icons/icon.svg"
  },
  "applications": {
    "zotero": {
      "id": "my-plugin@example.com",
      "strict_min_version": "6.999",
      "strict_max_version": "9.*"
    }
  }
}
```

> **关键**：`strict_max_version: "9.*"` 确保兼容 Zotero 9。

---

## 第三步：bootstrap.js - 核心逻辑

```javascript
// bootstrap.js - Zotero 插件入口

// ===== 插件生命周期 =====

function install(data, reason) {
  // 插件安装/升级时调用
}

async function startup({ id, version, rootURI }, reason) {
  Zotero.debug("MyPlugin: startup");
  
  // 注册新菜单（Zotero 8+ 推荐方式）
  // 这里注册在条目右键菜单
  try {
    Zotero.MenuManager.registerMenu({
      menuID: "my-plugin-item-menu",
      pluginID: "my-plugin@example.com",
      target: "main/library/item",
      menus: [
        {
          menuType: "menuitem",
          l10nID: "my-plugin-send-to-backend",
          onCommand: async (event, context) => {
            await handleSendToBackend(context);
          },
        },
      ],
    });
  } catch (e) {
    Zotero.debug("MyPlugin: MenuManager not available, using legacy method");
    // 降级到 Zotero 7 的传统方式（在 onMainWindowLoad 中处理）
  }
}

function onMainWindowLoad({ window }) {
  // 主窗口加载时的 UI 初始化
  // 如果 MenuManager 不可用（Zotero 7），在这里手动添加菜单
  const doc = window.document;
  
  // 插入本地化文件
  window.MozXULElement.insertFTLIfNeeded("my-plugin.ftl");
  
  // Zotero 7 传统方式：手动添加右键菜单
  if (!Zotero.MenuManager) {
    const itemMenu = doc.querySelector("#zotero-itemmenu");
    if (itemMenu) {
      const menuItem = doc.createXULElement("menuitem");
      menuItem.setAttribute("label", "发送到后端生成资料");
      menuItem.addEventListener("command", async () => {
        await handleSendToBackend();
      });
      itemMenu.appendChild(menuItem);
    }
  }
}

function onMainWindowUnload({ window }) {
  // 清理窗口相关引用
}

function shutdown() {
  Zotero.debug("MyPlugin: shutdown");
  // 清理资源
  try {
    Zotero.MenuManager.unregisterMenu("my-plugin-item-menu");
  } catch (e) {}
}

function uninstall(data, reason) {
  // 清理卸载
}

// ===== 核心业务逻辑 =====

async function handleSendToBackend(context) {
  // 获取当前选中的条目
  const zp = Zotero.getActiveZoteroPane();
  const selectedItems = zp.getSelectedItems();
  
  if (!selectedItems.length) {
    Zotero.debug("MyPlugin: No items selected");
    return;
  }
  
  const item = selectedItems[0];
  
  // 从条目中提取需要的数据
  const itemData = {
    id: item.id,
    title: item.getField('title'),
    abstract: item.getField('abstractNote'),
    creators: item.getCreators().map(c => ({
      firstName: c.firstName,
      lastName: c.lastName,
      creatorType: c.creatorType,
    })),
    date: item.getField('date'),
    url: item.getField('url'),
  };
  
  Zotero.debug(`MyPlugin: Sending to backend: ${JSON.stringify(itemData)}`);
  
  try {
    // 与后端通信
    const response = await fetch('http://localhost:8080/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(itemData),
    });
    
    if (!response.ok) {
      throw new Error(`Backend error: ${response.status}`);
    }
    
    const result = await response.json();
    
    // 将后端返回的资料添加回条目
    await addDataToItem(item, result);
    
    // 显示成功提示
    zp.displayCannotFindLibraryIDs
      ? null
      : null;
    
  } catch (error) {
    Zotero.debug(`MyPlugin: Error: ${error.message}`);
    // 可以在这里添加错误通知
  }
}

async function addDataToItem(item, result) {
  // 根据后端返回的结果更新条目
  await Zotero.DB.executeTransaction(async () => {
    // 示例：添加摘要
    if (result.summary) {
      item.setField('abstractNote', result.summary);
    }
    
    // 示例：添加标签
    if (result.tags) {
      for (const tag of result.tags) {
        item.addTag(tag);
      }
    }
    
    // 示例：添加笔记
    if (result.note) {
      const noteItem = new Zotero.Item('note');
      noteItem.libraryID = item.libraryID;
      noteItem.parentID = item.id;
      noteItem.setNote(result.note);
      await noteItem.save();
    }
    
    // 示例：添加附件
    if (result.attachmentPath) {
      const attachmentItem = await Zotero.Attachments.linkFromFile({
        file: result.attachmentPath,
        parentItemID: item.id,
      });
    }
    
    await item.save();
  });
  
  Zotero.debug("MyPlugin: Data added to item successfully");
}
```

---

## 第四步：locale 本地化

`locale/en-US/my-plugin.ftl`:

```ftl
my-plugin-send-to-backend =
    .label = 发送到后端生成资料
```

支持中文可以直接在 FTL 中使用中文字符，或者创建 `locale/zh-CN/my-plugin.ftl`。

---

## 第五步：与后端通信的几种方式

### 方式 1：通过 fetch() 直接 HTTP 调用（推荐）

```javascript
const response = await fetch('http://localhost:8080/api/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
});
```

### 方式 2：通过 Zotero 内置 HTTP Server 注册端点

```javascript
// 注册自定义端点
var myEndpoint = Zotero.Server.Endpoints["/myPlugin/generate"] = function() {};
myEndpoint.prototype = {
  "supportedMethods": ["POST"],
  "init": function(postData, sendResponseCallback) {
    // 处理逻辑
    var result = doSomethingWithData(postData);
    sendResponseCallback(200, "application/json", JSON.stringify(result));
  }
};
```

这允许外部程序通过 `http://127.0.0.1:23119/myPlugin/generate` 调用你的插件。

> 需要在 Zotero 设置中启用 "Allow other applications on this computer to communicate with Zotero"

### 方式 3：通过子进程

```javascript
// Zotero 可以执行子进程
var { Subprocess } = ChromeUtils.import("resource://gre/modules/Subprocess.jsm");

var proc = await Subprocess.call({
  command: '/path/to/python',
  arguments: ['/path/to/script.py', '--data', JSON.stringify(data)],
});
```

---

## 第六步：打包与安装

### 开发模式（推荐使用 zotero-plugin-template）

```bash
npm run start    # 启动开发模式，自动加载到 Zotero
npm run build    # 构建生产版本 XPI
```

### 手动打包

```bash
cd my-plugin
zip -r my-plugin.xpi manifest.json bootstrap.js prefs.js locale/ icons/
```

### 安装

1. Zotero → Tools → Plugins → 齿轮图标 → Install Plugin From File
2. 选择 .xpi 文件

---

---

## 信息来源

- Zotero 7 for Developers (官方): https://www.zotero.org/support/dev/zotero_7_for_developers
- Zotero 8 for Developers (官方): https://www.zotero.org/support/dev/zotero_8_for_developers
- Zotero JS API (官方): https://www.zotero.org/support/dev/client_coding/javascript_api
- 社区开发者文档: https://windingwind.github.io/doc-for-zotero-plugin-dev/
- zotero-plugin-template: https://github.com/windingwind/zotero-plugin-template
- Zotero MenuManager 源码: https://github.com/zotero/zotero/blob/main/chrome/content/zotero/xpcom/pluginAPI/menuManager.js

## 重要注意事项

1. **Zotero 9 兼容性**：`strict_max_version: "9.*"` 即可兼容
2. **MenuManager API**：Zotero 8+ 才有，Zotero 7 需要手动 DOM 操作
3. **异步操作**：所有数据库操作必须是 async/await
4. **事务**：修改数据时使用 `Zotero.DB.executeTransaction()`
5. **调试**：使用 `Zotero.debug()` 输出到 Zotero 调试日志
   - 启用方式：Help → Debug Output Logging → Enable
