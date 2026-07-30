# Reaper — 科研文章双语阅读工具

## 概述

Reaper 将 arxiv 论文自动转换为**中英对照的可读 HTML**，作为附件存入 Zotero。用户在 Zotero 中管理论文，双击即可在浏览器中阅读双语版本，原文公式、图表、表格完整保留。

核心流程：下载 ar5iv HTML → 解析段落 → LLM 按章节翻译 → 渲染双语 HTML → 导入 Zotero。

## 架构

```
Zotero 插件 (bootstrap.js)
       │  HTTP API
       ▼
Reaper Server (src/server.py)
       │
       ├── src/ingestion/    获取 + 解析
       │   ├── fetcher.py    下载 ar5iv HTML
       │   └── parser.py     提取段落，数学公式占位
       │
       ├── src/translation/  翻译引擎
       │   ├── translator.py 按章节 + 并发
       │   ├── dictionary.py 术语表（用户 + LLM 自动）
       │   └── cache.py      SHA256 去重
       │
       └── src/rendering/    输出
           └── renderer.py   拼接双语 HTML + CSS
```

## 目录结构

```
reaper/
├── config.json                    # 用户配置
├── main.py                        # CLI 入口
├── src/                           # 服务端代码
│   ├── server.py                  # HTTP 后端
│   ├── cli.py                     # 命令行工具
│   ├── config.py                  # 配置加载
│   ├── task.py                    # 任务状态管理
│   ├── ingestion/
│   ├── translation/
│   └── rendering/
├── zotero-plugin/                 # Zotero 插件
│   ├── bootstrap.js               # 入口逻辑
│   ├── manifest.json              # 元数据
│   ├── prefs.js                   # 默认设置
│   ├── setup.sh                   # 构建安装脚本
│   └── content/preferences.xhtml  # 设置页面
└── data/                          # 运行时产物（gitignore）
    ├── ar5iv/{id}.html            # ar5iv 原始 HTML 缓存
    ├── zotero/{id}.html           # 双语 HTML（本地副本）
    ├── translation_cache/{id}.json
    ├── tasks/{id}.json            # 任务状态
    ├── dict/                      # 术语字典
    └── logs/server.log
```

## Server API

### `GET /api/generate?arxiv_id=<ID>`

执行完整流水线（下载 → 解析 → 翻译 → 渲染），返回完整双语 HTML。

- 首次请求：完整流程（下载 ~15s + 翻译 ~2-5min）
- 重复请求：秒级返回（ar5iv 缓存 + 翻译缓存全部命中）
- 通过 Task 状态文件支持中断恢复

### `GET /api/clear?arxiv_id=<ID>`

清除指定论文的所有缓存（ar5iv HTML、翻译缓存、任务状态、输出 HTML）。用于强制重新生成。术语词典不受影响。

### `GET /api/terms` / `POST /api/terms`

读写用户术语词典。

### `GET /papers/{id}`

Web 预览——返回注入完整 UI（工具栏、术语面板）的双语页面。

## Zotero 插件

### 右键菜单

**条目右键 → Reaper → Download from Arxiv**：自动检测 arxiv ID，弹窗确认后下载 PDF 并附加到条目。

**条目右键 → Reaper → Generate Bilingual HTML**：调用 Server API 生成双语 HTML，作为子附件存入 Zotero。

- 已有附件时弹出确认对话框，可选择清除缓存后重新生成
- 条目无 arxiv ID 时弹窗允许手动输入

### 设置页面

路径：Zotero → 偏好设置 → Reaper

- **Attachment Name**：附件命名模板，`{arxiv_id}` 为占位符，默认 `"Reaper: {arxiv_id}"`
- **Server Port**：后端端口，默认 `16625`

### arxiv ID 自动检测

插件在条目的以下字段中查找 arxiv ID，保留版本后缀（`v2`/`v3`）：

1. URL — `arxiv.org/abs/1907.11157v2`
2. Extra — `arxiv: 1907.11157v2`
3. DOI — `10.48550/arxiv.1907.11157v2`

### 安装

```bash
cd zotero-plugin && bash setup.sh
# 重启 Zotero
```

## 翻译流水线

### 1. 获取原始 HTML

```
输入: arxiv ID 或 URL
 → 构造 ar5iv URL: https://ar5iv.labs.arxiv.org/html/{id}
 → 下载 HTML → 缓存至 data/ar5iv/{id}.html
 → 下次请求直接读缓存
```

**异常**：
- ar5iv 无此论文（重定向到 arxiv.org）→ `Ar5ivError`：论文太新，ar5iv 尚未转换
- ar5iv 转换失败（`ltx_ERROR`）→ `Ar5ivError`：LaTeXML 转换异常

### 2. 解析段落

```
ar5iv HTML → 一次遍历匹配 h1(title) / hN(section) / p(para) / figcaption
          → 插入 data-reaper-id="N" 标记
          → 提取纯文本 + <math> 替换为 MATH_N 占位符
          → 返回 marked_html（带标记的 HTML） + blocks[]（段落数组）
```

每个 Block 包含 `type`（title/section/para）、`level`（标题层级）、`text`（纯文本）、`math_map`（占位符 → 原始公式映射）。

### 3. 翻译

**整体策略**：按章节分组，每节一次 LLM 调用，多节并发翻译。

```
blocks[] → 按章节标题分组 sections[]
         → 超过 10000 字符的节以段落边界平衡拆分
         → 提交到全局线程池（并发数由 config.translator.concurrency 控制）
         → 每节 prompt 包含：论文标题 + 摘要 + 术语词典 + 所有段落
         → LLM 返回 REAPER_PARA_N 编号的译文
```

**段落对齐**：提示词中每段标注 `REAPER_PARA_1`、`REAPER_PARA_2`……LLM 返回相同编号的译文。按编号匹配，不依赖数量一致。

**术语管理**：双层结构——用户手动定义（`dict/user_terms.json`，高优先级）+ LLM 翻译时自动提取（`dict/llm_terms.json`，低优先级）。合并后注入 prompt，用户定义覆盖 LLM 建议。

**翻译缓存**：`SHA256(英文段落) → 中文翻译`，按论文 ID 分文件存储。再次请求同一段落时秒级命中，无需重复翻译。

**进度显示**：终端输出累计进度百分比，包含缓存命中数。

### 4. 渲染

```
marked_html + 翻译结果
 → 在 data-reaper-id="N" 标记处插入对应中文翻译
 → CSS 覆盖：引用字体修正、摘要标题字号统一、页面宽度限制
 → 保留 ar5iv 原生 CSS（公式/表格/图注渲染）
 → 输出保存至 data/zotero/{id}.html
```

## 配置

`config.json`（项目根目录）：

```json
{
  "api": {
    "key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  },
  "server": {
    "host": "0.0.0.0",
    "port": 16625
  },
  "translator": {
    "concurrency": 3
  }
}
```

`translator.concurrency` 控制**全局**翻译线程池大小。所有论文共享此池，同时最多 N 个 LLM 请求。过大可能触发 API 限流。

## 启动

```bash
# 后端服务（常驻）
python3 src/server.py

# 命令行（一次性处理单篇论文）
python3 main.py 1907.11157

# Zotero 插件
bash zotero-plugin/setup.sh
```

## 任务状态

每个论文一个 `data/tasks/{id}.json`：

```json
{
  "arxiv_id": "1907.11157v2",
  "state": "translating",
  "blocks": [
    {"idx": 0, "hash": "a3f8c92d", "done": true},
    {"idx": 1, "hash": "b7e2c441", "done": false}
  ],
  "total": 183,
  "translated": 105,
  "error": null,
  "interrupted": false
}
```

**状态机**：`pending → fetching → parsing → translating → rendering → done`

**中断恢复**：加载时检测 state 是否为中间状态 → 标记 `interrupted = true` → 未完成的 block 继续翻译。

**错误追踪**：每次异常记录到 `error_history`，保留最近 10 条。

## 设计要点

1. **保留 ar5iv 原生 CSS**：公式、表格、图注由 LaTeXML 渲染，自写 CSS 无法覆盖所有边缘情况
2. **按章节翻译**：LLM 看到完整章节上下文，翻译更连贯
3. **编号对齐**：`REAPER_PARA_N` 按编号匹配，LLM 少输出或合并输出时也不会错位
4. **平衡章节拆分**：在段落边界处按最接近目标大小的方式切分，避免极端不均匀
5. **双层术语表**：用户定义优先，LLM 翻译时自动积累新术语，逐步丰富
6. **全局线程池**：各任务共享翻译并发配额，由配置文件控制上限
7. **版本 ID 区分**：`1907.11157v2` 和 `1907.11157v3` 独立缓存，ar5iv 上它们是不同页面

## 已知限制

- ar5iv 不覆盖所有 arxiv 论文，较新的论文或特殊 LaTeX 格式可能无法转换
- 翻译质量依赖 LLM，术语词典可弥补部分一致性；无 API key 时仅使用缓存
- 并发翻译数受 API 限流约束，建议 ≤ 5
- 生成的 HTML 附件约 3MB，首次请求需等待完整翻译和下载
