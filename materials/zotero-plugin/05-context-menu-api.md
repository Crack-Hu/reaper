# ⭐ 右键菜单 API（你需求的核心）

## 方式一：MenuManager API（Zotero 8+，推荐）

`Zotero.MenuManager.registerMenu()` 是 Zotero 8 引入的正式 API。

### 基本用法

```javascript
// 在 bootstrap.js 的 startup() 中调用
Zotero.MenuManager.registerMenu({
  menuID: "my-plugin-item-menu",       // 菜单唯一 ID
  pluginID: "my-plugin@example.com",   // 插件 ID
  target: "main/library/item",         // 目标位置
  menus: [
    {
      menuType: "menuitem",            // 菜单项类型
      l10nID: "my-plugin-menu-item",   // 本地化 ID
      onCommand: async (event, context) => {
        // 用户点击时执行
        await myAction(context);
      },
      onShowing: (event, context) => {
        // 菜单显示前调用，可控制可见性
        context.setVisible(
          context.items?.every(item => item.isRegularItem())
        );
      },
    },
  ],
});
```

### 带子菜单的用法

```javascript
Zotero.MenuManager.registerMenu({
  menuID: "my-plugin-menu",
  pluginID: "my-plugin@example.com",
  target: "main/library/item",
  menus: [
    {
      menuType: "submenu",
      l10nID: "my-plugin-submenu",
      menus: [
        {
          menuType: "menuitem",
          l10nID: "my-plugin-action-1",
          onCommand: (event, context) => { /* ... */ },
        },
        {
          menuType: "menuseparator",   // 分隔线
        },
        {
          menuType: "menuitem",
          l10nID: "my-plugin-action-2",
          onCommand: (event, context) => { /* ... */ },
        },
      ],
    },
  ],
});
```

### context 对象

`onCommand` 和 `onShowing` 回调的 `context` 参数提供了关于选中项目的信息：

```javascript
{
  items: [Zotero.Item, ...],     // 选中的条目
  collections: [...],            // 选中的集合
  libraryID: 1,                  // 库 ID
  setVisible(bool),              // 控制菜单项可见性
}
```

### 所有可用的 target

#### 主窗口菜单栏
| target | 位置 |
|--------|------|
| `main/menubar/file` | 文件菜单 |
| `main/menubar/edit` | 编辑菜单 |
| `main/menubar/view` | 查看菜单 |
| `main/menubar/go` | 跳转菜单 |
| `main/menubar/tools` | 工具菜单 |
| `main/menubar/help` | 帮助菜单 |

#### 主窗口库上下文菜单
| target | 位置 |
|--------|------|
| `main/library/item` | **条目的右键菜单** ⭐ |
| `main/library/collection` | **集合的右键菜单** |
| `main/library/addAttachment` | 添加附件按钮/菜单 |
| `main/library/addNote` | 添加笔记按钮/菜单 |

#### 其他
| target | 位置 |
|--------|------|
| `main/tab` | 标签页右键菜单 |
| `itemPane/info/row` | 条目面板信息行右键菜单 |
| `notesPane/addItemNote` | 笔记面板添加条目笔记 |
| `notesPane/addStandaloneNote` | 笔记面板添加独立笔记 |
| `sidenav/locate` | 侧边导航定位按钮 |

#### Reader 窗口
| target | 位置 |
|--------|------|
| `reader/menubar/file` | Reader 文件菜单 |
| `reader/menubar/edit` | Reader 编辑菜单 |
| `reader/menubar/view` | Reader 查看菜单 |
| `reader/menubar/go` | Reader 跳转菜单 |
| `reader/menubar/window` | Reader 窗口菜单 |

### 注销菜单

```javascript
Zotero.MenuManager.unregisterMenu("my-plugin-item-menu");
// 或插件禁用/卸载时自动清理
```

### FTL 本地化

```ftl
# my-plugin.ftl
my-plugin-menu-item =
    .label = 发送到后端

my-plugin-submenu =
    .label = 我的工具

my-plugin-action-1 =
    .label = 生成摘要

my-plugin-action-2 =
    .label = 分析关键词
```

---

## 方式二：手动 DOM 操作（Zotero 7 兼容）

适用于 Zotero 7 或不需 MenuManager API 的场景。

### 添加到条目右键菜单

```javascript
// 在 bootstrap.js 的 onMainWindowLoad() 中
function onMainWindowLoad({ window }) {
  const doc = window.document;
  
  // 获取条目右键菜单
  const itemMenu = doc.querySelector("#zotero-itemmenu");
  
  // 创建菜单项
  const menuItem = doc.createXULElement("menuitem");
  menuItem.setAttribute("label", "发送到后端");
  menuItem.dataset.l10nId = "my-plugin-menu-item"; // Fluent 本地化
  
  // 点击事件
  menuItem.addEventListener("command", async () => {
    const zp = Zotero.getActiveZoteroPane();
    const items = zp.getSelectedItems();
    if (items.length > 0) {
      await myAction(items[0]);
    }
  });
  
  // 插入菜单
  itemMenu.appendChild(menuItem);
  
  // 控制可见性（仅对非笔记的常规条目显示）
  itemMenu.addEventListener("popupshowing", () => {
    const items = Zotero.getActiveZoteroPane().getSelectedItems();
    menuItem.hidden = !items.length || items.some(i => !i.isRegularItem());
  });
}
```

### 添加到集合右键菜单

```javascript
const collectionMenu = doc.querySelector("#zotero-collectionmenu");
const menuItem = doc.createXULElement("menuitem");
menuItem.setAttribute("label", "自定义操作");
menuItem.addEventListener("command", myCollectionAction);
collectionMenu.appendChild(menuItem);
```

### 添加分隔线

```javascript
const separator = doc.createXULElement("menuseparator");
itemMenu.appendChild(separator);
```

### 所有菜单查询选择器

| 选择器 | 位置 |
|--------|------|
| `#zotero-itemmenu` | 条目右键菜单 |
| `#zotero-collectionmenu` | 集合右键菜单 |
| `#menu_FilePopup` | 文件菜单 |
| `#menu_EditPopup` | 编辑菜单 |
| `#menu_viewPopup` | 查看菜单 |
| `#menu_goPopup` | 跳转菜单 |
| `#menu_ToolsPopup` | 工具菜单 |
| `#menu_HelpPopup` | 帮助菜单 |

---

## 方式三：Reader 上下文菜单

通过 `Zotero.Reader.registerEventListener` 注册：

```javascript
// 在 startup() 中
Zotero.Reader.registerEventListener(
  "createAnnotationContextMenu",
  (event) => {
    const { reader, params, append } = event;
    append({
      label: "自定义操作",
      onCommand() {
        reader._iframeWindow.alert("Selected: " + params.ids.join(", "));
      },
    });
  },
  "my-plugin@example.com"
);
```

支持的事件类型：
- `createColorContextMenu` - 颜色选择器菜单
- `createViewContextMenu` - 阅读器右键菜单
- `createAnnotationContextMenu` - 注释右键菜单
- `createThumbnailContextMenu` - 缩略图右键菜单
- `createSelectorContextMenu` - 标签选择器右键菜单

## 信息来源

- Zotero 8 MenuManager API (官方): https://www.zotero.org/support/dev/zotero_8_for_developers
- 社区 Menu 文档: https://windingwind.github.io/doc-for-zotero-plugin-dev/main/menu
- Zotero MenuManager 源码: https://github.com/zotero/zotero/blob/main/chrome/content/zotero/xpcom/pluginAPI/menuManager.js
- Zotero Reader API 源码: https://github.com/zotero/zotero/blob/main/chrome/content/zotero/xpcom/reader.js
- zotero-plugin-toolkit MenuManager: https://windingwind.github.io/zotero-plugin-toolkit/
