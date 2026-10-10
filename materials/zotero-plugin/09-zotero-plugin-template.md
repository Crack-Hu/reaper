# zotero-plugin-template 脚手架详解

## 基本信息

- **仓库**: https://github.com/windingwind/zotero-plugin-template
- **Build system**: ESBuild / Webpack
- **语言**: TypeScript
- **兼容** Zotero 7, 8, 9
- **活跃维护**，社区首选模板

---

## 快速开始

```bash
git clone https://github.com/windingwind/zotero-plugin-template.git my-plugin
cd my-plugin
npm install
npm run start    # 启动开发模式
```

开发模式下：
- 代码变更自动重载
- 自动重启 Zotero 加载新插件
- 控制台输出调试信息

---

## 目录结构

```
my-plugin/
├── src/
│   ├── index.ts              # 插件入口，定义 bootstrap hooks
│   ├── modules/
│   │   └── examples.ts       # 示例代码（右键菜单、API 调用等）
│   ├── utils/                # 工具函数
│   └── api.ts                # API 封装
├── addon/
│   ├── chrome.manifest       # (可选) 资源注册
│   ├── locale/               # Fluent 本地化
│   │   ├── en-US/
│   │   └── zh-CN/
│   ├── prefs.js              # 默认偏好
│   └── bootstrap.js          # 构建生成的入口文件
├── package.json
├── tsconfig.json
├── zotero-cmd-default.json   # 构建配置
└── .github/workflows/        # CI/CD 自动构建和发布
```

---

## 核心文件

### src/index.ts

TypeScript 入口，定义所有生命周期钩子：

```typescript
import { BasicTool } from "zotero-plugin-toolkit";
import { registerRightClickMenuItem } from "./modules/examples";

let basicTool: BasicTool;

async function startup({ id, version, rootURI }: any) {
  basicTool = new BasicTool();
  basicTool.basicOptions.log.prefix = "[MyPlugin]";
  
  // 等待 Zotero 就绪
  await basicTool.basicOptions.promise;

  // 初始化
  basicTool.log("Plugin starting...");

  // 注册菜单（使用 toolkit）
  registerRightClickMenuItem(basicTool);
  
  // 或直接使用 Zotero API
  Zotero.MenuManager.registerMenu({
    menuID: "my-menu",
    pluginID: id,
    target: "main/library/item",
    menus: [{ menuType: "menuitem", l10nID: "my-item" }]
  });
}

function shutdown() {
  basicTool?.log("Plugin shutting down...");
  // 清理
}
```

### src/modules/examples.ts

社区模板提供的示例代码：

```typescript
import { MenuManager } from "zotero-plugin-toolkit";
import type { BasicTool } from "zotero-plugin-toolkit";

export function registerRightClickMenuItem(basicTool: BasicTool) {
  const menuManager = new MenuManager(basicTool);
  
  menuManager.register(
    "item",  // 条目右键菜单
    {
      tag: "menuitem",
      label: "My Action",
      commandListener: async () => {
        // 获取选中条目
        const items = Zotero.getActiveZoteroPane().getSelectedItems();
        for (const item of items) {
          // 处理条目...
        }
      }
    }
  );
}
```

### 可用的 MenuManager target

```typescript
menuManager.register("item", { ... });         // 条目右键
menuManager.register("collection", { ... });   // 集合右键
menuManager.register("menuTools", { ... });    // 工具菜单
menuManager.register("menuFile", { ... });     // 文件菜单
menuManager.register("menuEdit", { ... });     // 编辑菜单
```

---

## 配置

### package.json 脚本

```json
{
  "scripts": {
    "start": "node scripts/start.js",     // 启动开发
    "stop": "node scripts/stop.js",       // 停止开发
    "build": "node scripts/build.js",     // 构建 XPI
    "release": "node scripts/release.js"  // 发布
  }
}
```

### zotero-cmd-default.json

```json
{
  "zoteroPath": "/Applications/Zotero.app",  // macOS
  "profilePath": "/path/to/dev/profile",
  "dataDir": "/path/to/dev/data"
}
```

---

## Toolkit 常用 API

zotero-plugin-toolkit 封装了常用操作：

```typescript
import {
  BasicTool,
  MenuManager,
  UIHelper,
  ProgressWindowHelper,
  LargePrefHelper,
  KeyboardManager,
  PromptManager,
} from "zotero-plugin-toolkit";

// 基础工具
const basicTool = new BasicTool();
basicTool.log("message");
basicTool.getGlobal("Zotero");

// 菜单管理
const menuManager = new MenuManager(basicTool);

// UI 辅助
const uiHelper = new UIHelper(basicTool);

// 进度窗口
const progressHelper = new ProgressWindowHelper(basicTool);

// 偏好设置
const prefHelper = new LargePrefHelper(basicTool);

// 快捷键
const keyboardManager = new KeyboardManager(basicTool);

// 对话框
const promptManager = new PromptManager(basicTool);
```

---

## 兼容性处理

模板内置了 Zotero 7/8/9 的兼容性处理：

```typescript
// 版本检测
const zoteroVersion = Zotero.version;
const isZotero8 = zoteroVersion.startsWith("8.");
const isZotero9 = zoteroVersion.startsWith("9.");

// 根据版本选择不同的 API 调用方式
if (Zotero.MenuManager) {
  // Zotero 8+ 新 API
  Zotero.MenuManager.registerMenu({...});
} else {
  // Zotero 7 降级方案
  // 手动 DOM 操作
}
```

---

## 构建流程

```
src/index.ts ─┐
src/modules/*  ├── ESBuild/Webpack ──→ addon/bootstrap.js ──→ my-plugin.xpi
src/utils/*   ─┘
```

1. TypeScript 编译为单文件 JavaScript
2. 自动替换 `__rootURI__`、`__version__` 等占位符
3. 打包为 XPI（实际是 ZIP）
4. 复制到 Zotero 插件目录或自动加载

---

## 注意事项

1. **不要在 addon/ 下手动编辑 bootstrap.js**，它是构建生成的
2. **FTL 文件**放在 `addon/locale/` 目录下
3. **SVG 图标**放在 `addon/chrome/content/icons/`
4. **偏好设置**写在 `addon/prefs.js`
5. Zotero 9 兼容性已验证，社区插件大多已迁移成功

## 信息来源

- zotero-plugin-template: https://github.com/windingwind/zotero-plugin-template
- zotero-plugin-toolkit: https://github.com/windingwind/zotero-plugin-toolkit
- zotero-plugin-scaffold: https://github.com/northword/zotero-plugin-scaffold
- 社区开发者文档: https://windingwind.github.io/doc-for-zotero-plugin-dev/
