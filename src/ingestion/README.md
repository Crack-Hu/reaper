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

### ⚠️ 有些论文的 HTML 不可用（改用本地编译）

arXiv / ar5iv 的 HTML 是 LaTeXML 转换 LaTeX 源码的产物，**转换不总是成功**，
而且失败时常常返回 HTTP 200 的"看起来像页面"的东西：

- **模板样张**：投稿里混有期刊模板（如 `cas-sc-template.tex` 与真正的 `main.tex`
  并存）时，转换器可能挑错文件，返回模板样张（案例 `2111.05176`）。
- **截断 / 空壳**：LaTeXML 对 **Xy-pic / Qcircuit 图表**（`\Qcircuit` 就是
  `\xymatrix`）支持不全——图表里每个 `_`/`^` 报一个错，而且**图表之后的全部内容
  会被吞掉**（实测 `2111.05176`：文档在第 7 节后截断，第 8-10 节、参考文献、附录
  全丢，LaTeXML 却报告"转换完成"）。它还有硬编码的 100 错误上限
  （`Fatal:too_many_errors`），超出即整篇中止。

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

**编译侧的处理**（`src/ingestion/ar5ivist_bindings/`，随程序分发、只读挂载、
`--preload` 注入，**不修改论文源码**）：

| 组件 | 作用 | 开关 |
|---|---|---|
| `reaper-qcircuit.sty` | 把 `\xymatrix` 换成"跳过选项、吞掉图表体"的宏：有救援图就插图，否则 `[diagram omitted]` 占位符 | `ar5ivist_xypic_stub`（默认开） |
| `reaper-maxerrors.ltxml` | 抬高 LaTeXML 的 100 错误上限 | `ar5ivist_max_errors`（默认 100000，0 = 关） |
| `diagram_rescue.py`（宿主）+ 容器里的 `latex`/`dvisvgm` | **图救援**：把画不了的图用真 LaTeX 渲染成 SVG，再插回 HTML | `ar5ivist_render_diagrams`（默认开） |

注意：**光抬高上限不够**——它只让 LaTeXML 别中止，被 Xy-pic 破坏的解析照样静默
丢内容；真正解决问题的是 qcircuit stub，而图救援把丢弃的图找回来。详见该目录的
`README.md`。

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
