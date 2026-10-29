# src/rendering — 双语 HTML 渲染

把 `marked_html` + 译文数组渲染成**自包含**（或 assets 目录）的双语 HTML：
注入 TOC 侧栏、中文译文、主题切换、页脚，并保留 ar5iv 原生公式/图表渲染。

## 文件

| 文件 | 职责 |
|---|---|
| `renderer.py` | 主渲染逻辑 + 资源处理 + Zotero 兼容转换 |
| `ui/toc-sidebar.css` | TOC 侧栏 + 工具栏样式（默认隐藏，点 ☰ 展开） |
| `ui/toc-toggle.js` | 动态创建工具栏：TOC 切换（☰）、主题切换（☾）、译文开关 |
| `arxiv_css/` | ar5iv CSS 本地缓存（缺失时自动从 ar5iv 下载，gitignore） |

## 主流程（`render_bilingual_html`）

1. **来源清洗**（`_strip_arxiv_brand`）：arxiv.org/html 来源会剥掉 arXiv 的页面
   chrome —— 整个 `<header class="arxiv-html-header">`（logo、"Why HTML?"、Report/PDF
   按钮；**只删里面的 logo/nav 会留下空 header，被 arXiv CSS 渲染成一条空栏**）、
   公告条 `ds-announcement`、隐藏的 "Report GitHub Issue" `<dialog>`，以及品牌脚本；
   删 `<base>`，把站内 TOC 链接改成文档锚点；正文包进 `<div class="reaper-content">`。
2. **CSS**：`_inline_css` 把 ar5iv CSS 内嵌为 `<style>`（本地缓存优先）。
3. **资源**：`_process_resources` 扫描 `src/data/poster`，下载图片/字体/SVG。
   - `resource_dir` 给定 → 保存到 `{resource_dir}/assets/`，相对路径 + CDN 兜底（Full）。
   - `resource_dir=None` → 只用 CDN 链接（Light，单文件）。
4. **TOC**：ar5iv/ar5ivist 由 blocks 生成嵌套 TOC（`_inject_blocks_toc`，给标题加
   `id="reaper-sec-{N}"`）；arxiv_html 保留原生 `<nav class="ltx_TOC">`，只转换锚点。
5. **页脚**：`replace_footer()` 按来源标注 `HTML from ar5iv / arxiv.org / ar5ivist`。
6. **译文注入**：在 `data-reaper-id="N"` 元素闭合前插入，公式由
   `restore_math_in_translation()` 还原；行内（标题）与块级样式不同。
7. **元数据 / 来源开关**：注入 `reaper-data`（论文 id + 术语）与来源切换 JS。

## 与其他模块的契约

- 输入 `blocks_with_zh` 必须与 `marked_html` 的 `data-reaper-id` **同序同长**（parser 保证）。
- 渲染器**不重新解析** HTML，全靠 `data-reaper-id` 定位。
- 输出给 Zotero 前要过 `zotero_compatible_html()`：`<object>` → `<img>`
  （Zotero 内嵌浏览器不渲染 data URI 的 `<object>`）。
- `save_html()` 自动建目录。

## 用户明确的约定（改渲染器前先读）

1. 正文放在 `reaper-content` 画布内，工具栏/TOC 在画布外。
2. TOC 默认关闭，点 ☰ 展开；层级用 HTML 结构判断，**不要硬编码 section 标题**。
3. 不自己写 CSS 框架，优先 ar5iv 原生 CSS 变量（否则深色主题失效）。
4. `subsection` 包含 `section` 子串 → 判断顺序从长到短。
5. 三个来源统一输出样式。
6. 测试用 HTTP 而非 `file://`；快速预览可以用 fake blocks（`zh: ''`）跳过翻译。
7. Zotero 内置 reader 的 iframe **不执行附件里的 JS**（`toc-toggle.js` 在 reader 里
   可能无效，外部浏览器正常）——若要在 reader 内保功能，需改 CSS-only 方案。

## 已知缺口

- 每个 block 目前只有 `data-reaper-id`，**没有 `id="reaper-block-{N}"`**；
  选中段落提问依赖后者（见 `HANDOFF.md` §7.2）。
