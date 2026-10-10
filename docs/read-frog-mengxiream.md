# read-frog (mengxi-ream) HTML 翻译技术分析

> 仓库: https://github.com/mengxi-ream/read-frog

## 1. 项目概述

read-frog 是开源的浏览器扩展（Chrome/Edge/Firefox），核心定位：**AI 驱动的整页沉浸式翻译 + 语言学习工具**。支持双语对照、划词翻译、字幕翻译、TTS、闪卡等。

技术栈：WXT + React 19 + Vercel AI SDK + Jotai + TailwindCSS v4。

## 2. HTML 翻译核心技术

### 2.1 整体流程

```
DOM 遍历标记 → 文本提取与翻译请求 → 译文回插 DOM
```

**三阶段**：

1. `walkAndLabelElementChunked()` — 时间切片遍历 DOM，打标记
   - `data-read-frog-paragraph` / `block-node` / `inline-node`
2. `IntersectionObserver` 观察已标记段落，进入视口时触发翻译
3. `translateNodes()` → 提取文本 → API 翻译 → 回插 DOM

### 2.2 保持原网站结构（核心）

#### a) 双语模式 — 包装器策略

- **原 DOM 完全不修改**：原文保留在原位置
- **译文插入在原文后**：`<span class="notranslate read-frog-translated-content-wrapper">`
- `notranslate` class 防止 Google 翻译二次翻译
- 块级：译文前加 `<br>`；内联：译文前加 `&nbsp;&nbsp;`

#### b) Translation-Only 模式 — 原地文本交换

最精妙的设计！`translation-text-swap.ts`：

1. 创建临时 `<template>` 解析翻译后 HTML
2. 将源文本节点与翻译结果按层级对齐（对比标签名、href/src/id 属性）
3. **直接修改原始 Text Node 的 `.data`**：`node.data = translatedValue`
4. 元素身份完全不变 → 不破坏任何框架的 fiber/事件监听器

#### c) HTML 属性标记系统

`html-attribute-markers.ts`：

- 将 `<a href title="提示">文本</a>` 转换为带 `data-rf-attr` 标记的 HTML
- 翻译后**验证标记完整性**：marker id 一一对应、marker 没移动到错误标签
- 用翻译后的属性值替换回原始元素
- DeepLX 等不支持的 API 自动回退到发送完整 HTML

#### d) 虚拟段落分割

`paragraph-segmentation.ts` 处理 `white-space: pre` 元素：通过空行分割虚拟段落，每个独立翻译但共享 layout source。

#### e) MutationObserver 动态内容

- `characterData`：译文被脚本修改时重翻译
- `childList`：新增节点自动翻译
- `attributes`：style/class/hidden 变化检查阻塞状态
- 重翻译防抖：同一 source 10s 内最多 6 次

### 2.3 元素分类决策

```
siteRuleForceBlock > forceInline > forceBlock >
  shortInline > isInlineTransNode > isBlockTransNode
```

通过 `getComputedStyle` 判断 display + 强制块级标签（P/DIV/H1-H6/LI）+ 首字母浮动大写特殊处理。

**保护机制**：`<a>`/`<button>` 中插入边界自动提升（`liftEdgeBoundary`），不在链接/按钮内部插入译文。

## 3. 翻译 API 调用

### 3.1 支持的后端

- **免费内建**：Google Translate、Microsoft Translate
- **纯 API**：DeepL、DeepLX（非官方）
- **LLM**（Vercel AI SDK 20+ 提供者）：OpenAI、Claude、Gemini、DeepSeek、Groq、Mistral、Ollama 等

### 3.2 调用链路

```
Content Script → sendMessage("enqueueTranslateRequest")
  → Background SW: IndexedDB 缓存检查
  → BatchQueue (批次合并)
  → RequestQueue (令牌桶限流)
  → executeTranslate() → AI/DeepL/Google
```

### 3.3 批次合并（BatchQueue）

- `batchDelay=100ms`，`maxItemsPerBatch=4`，`maxCharsPerBatch=1000`
- 动态延迟：查询 RequestQueue 预计可用时间，有空位立即 flush，繁忙则等待（最多60s）
- 批次格式：`texts.join("\n\n==========\n\n")`，规则约束返回相同数量段落

### 3.4 上下文感知

LLM 翻译时注入网页上下文（标题+摘要+内容），通过 `defuddle` 提取正文 + LLM 生成摘要并缓存 IndexedDB。

### 3.5 令牌桶限流（RequestQueue）

```
rate: 8/s, capacity: 20, timeoutMs: 20s, maxRetries: 2
```

- 批处理超时 = `20s + 字符数 * 15ms`（最大120s）
- 多标签页同 hash 请求去重

### 3.6 重试策略

| 错误 | 策略 |
|------|------|
| 429 Rate Limit | pause-and-retry：暂停队列，5s*2^n 退避，最多暂停5次 |
| Timeout/Network | retry：指数退避(1s*2^n + 10% jitter)，最大5min |
| 400-499 | fail：不重试 |
| 401/403/404 | fail+failQueue：清空队列 |
| 批次数量不匹配 | retry 3次→fallback逐条翻译 |

### 3.7 取消机制

每个请求关联 `scope = ${tabId}:${sessionId}`，用户取消时从 BatchQueue 和 RequestQueue 同时移除。选项卡关闭时 `tabs.onRemoved` 自动清理。

## 4. 架构

```
src/
├── entrypoints/
│   ├── background/translation-queues.ts   # 队列核心
│   ├── host.content/                      # Content Script
│   │   └── translation-control/
│   │       ├── page-translation.ts        # 页面翻译管理器
│   │       └── traversal.ts              # DOM 遍历与标记
│   └── popup/                             # 弹出窗口 UI
├── utils/host/translate/
│   ├── api/                               # API 适配器
│   ├── dom/
│   │   ├── translation-insertion.ts       # 译文插入
│   │   ├── translation-text-swap.ts       # 原地文本交换
│   │   ├── html-attribute-markers.ts      # 属性标记保护
│   │   └── paragraph-segmentation.ts      # 虚拟段落
│   └── core/
├── utils/request/
│   ├── request-queue.ts                   # 令牌桶
│   ├── batch-queue.ts                     # 批次合并
│   └── retry-policy.ts                    # 重试策略
└── utils/prompts/translate.ts             # 翻译 Prompt
```

## 5. 对 reaper 的启发

| 维度 | 可复用 |
|------|--------|
| **原地文本交换** | 直接修改 TextNode.data，不破坏 DOM 结构 |
| **属性标记保护** | 翻译前后验证 HTML 标签完整性 |
| **批次合并+令牌桶** | 翻译多段落时的性能优化核心 |
| **MutationObserver** | 处理动态内容的关键 |
| **虚拟段落分割** | 代码块等 `pre` 内容的分段翻译 |
| **上下文注入** | 翻译时注入页面标题/摘要提升质量 |
| **notranslate class** | 防止工具链二次翻译 |
| **IndexedDB 缓存** | 翻译结果去重+离线可用 |
