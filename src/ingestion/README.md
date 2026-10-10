# src/ingestion — 获取与解析

把一篇论文变成**可寻址的 `Block` 序列**：多来源下载 HTML → 一次遍历标记并抽取段落。

## 文件

| 文件 | 职责 |
|---|---|
| `fetcher.py` | 按优先级尝试三种来源；缓存 HTML + 图片；arXiv 源码下载 |
| `parser.py` | `mark_and_extract()`：标记 `data-reaper-id="N"` 并同时抽出 `blocks[N]` |
| `fetched_page.py` | `FetchedPage` 数据类：`{arxiv_id, source_type, html, img_dir, page_url}` |

## 来源优先级（`config.SOURCES` 可配）

```
arxiv_html  →  https://arxiv.org/html/{id}       官方 LaTeXML HTML，有原生 TOC
ar5iv       →  https://ar5iv.labs.arxiv.org/html/{id}
ar5ivist_docker → arXiv e-print 源码 → docker 编译（慢，兜底）
```

- 每种来源失败抛 `SourceError`，`fetch_html` 依次降级并聚合错误。
- **缓存语义**：`cache_dir` 是**该论文自己的目录**（默认 `source_dir(id)`），HTML 存
  `{cache_dir}/{id}.html`，图片存同目录。命中缓存会顺带补下缺失图片。
- `force_source="ar5iv"` 会跳过缓存并只试指定来源（用于对比生成）。
- 缓存有效性检查：`ltx_ERROR`、误存成 arXiv 摘要页的 HTML 会被判为无效。
- `_try_ar5ivist_docker` 无超时（复杂论文可能跑很久），日志写 `source/ar5ivist.log`；
  纯 SVG 无文字的失败产物会被识别并抛错。

## 解析（parser.py）

`mark_and_extract(html) -> (marked_html, blocks)`，单次 DOM 序扫描，保证
**blocks[i] ↔ `data-reaper-id="i"` 严格 1:1**（历史上分开 mark 和 extract 两遍会错位）。

匹配的标签与产出类型：

| HTML | Block.type | level | 说明 |
|---|---|---|---|
| `h1.ltx_title_document` | `title` | 0 | 论文标题 |
| `h*.ltx_title_section/subsection/subsubsection` | `section` | 1/2/3 | **判断顺序必须从长到短**（`subsection` 含 `section` 子串） |
| `p.ltx_p` | `para` | 0 | 正文段落 |
| `figcaption.ltx_caption` | `figcaption` | 0 | 图/表标题 |
| `.ltx_note_content` | `note` | 0 | 脚注内容（整块处理，内部元素不再单独标记） |

`Block` 字段：`{type, text, level, label, math_map}`

- 公式在 `text` 里是 `MATH_N` 占位符，`math_map` 保存 `MATH_N → 原始 <math> HTML`；
  渲染时由 `restore_math_in_translation()` 还原（小心 `MATH_1` 与 `MATH_10` 的前缀问题）。
- 脚注在正文明细处留 `FN_N` 占位；脚注内容作为独立 `note` block 参与翻译。
- `parse_blocks(html)` 只是 `mark_and_extract` 的第二返回值。

## 不变量

- **不要新增/调换匹配顺序**而不跑 `tests/run_tests.py`：blocks 与标记错位会让译文串段。
- `marked_html` 会继续被翻译缓存 hash 引用；HTML 变化可能导致缓存整体失效。
- 三来源都产自 LaTeXML（`ltx_*` 类名一致），所以 parser 对三者通用。

## 测试

```bash
python3 tests/run_tests.py          # TestFetchAr5iv / TestFetchArxivHTML / TestParseRealHTML
```
