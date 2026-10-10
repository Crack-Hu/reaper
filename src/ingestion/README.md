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

### ⚠️ 有些论文的 HTML 不可用（需要本地编译）

arXiv / ar5iv 的 HTML 是 LaTeXML 转换 LaTeX 源码的产物，**转换不总是成功**，
而且失败时常常返回 HTTP 200 的"看起来像页面"的东西：

- **模板样张**：投稿里混有期刊模板（如 `cas-sc-template.tex` 与真正的 `main.tex`
  并存）时，转换器可能挑错文件，返回模板样张（案例 `2111.05176`）。
- **空壳页**：LaTeXML 有硬编码的 100 错误上限（`Fatal:too_many_errors`），
  超出即**中止整篇转换**、写出一个空 HTML。最常见的触发者是 **qcircuit /
  Xy-pic 电路图**（`\Qcircuit` 体内的每个 `_`/`^` 都是一个错误）。

**Reaper 不做内容嗅探**（特征防不完，也不优雅）：拿到什么就用什么。
遇到这类论文，由用户显式换来源——直接指定本地 Docker 编译：

```bash
curl 'http://localhost:16625/api/generate?arxiv_id=2111.05176&source=ar5ivist_docker'
```

插件里对应「Reaper → Generate Bilingual HTML → 重试菜单选 **ar5ivist**」。
`source=` 的语义：跳过 HTML 缓存、只尝试该来源；已解压的源码
（`_download_arxiv_source` 优先 `main.tex`）会被复用，不重复下载。

前提：本机 Docker 在运行、镜像已拉取（`config.ar5ivist_docker_image`，如
`latexml/ar5ivist:2512.17`）；编译**没有超时**，大论文可能跑很久，进度看
`source/ar5ivist.log`。

**对第二种情况，Reaper 在编译侧做了通用处理**：`ar5ivist_docker` 会把仓库自带的
binding `src/ingestion/ar5ivist_bindings/reaper-maxerrors.ltxml` 只读挂载进容器，
并用 `--preload` 加载它，把 LaTeXML 的错误上限抬高（`config.ar5ivist_max_errors`，
默认 100000，设 0 则保持原样）。理由：错误很多的文档往往照样能转换完，只是被这个
硬上限中止了——提高上限让它像平时一样"带错跑完"，而不是去改论文的源码。
`MAX_ERRORS` 不是命令行选项而是 LaTeXML 的内部状态值，所以只能用 binding 设置。

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
