# ar5ivist_bindings — 转换器侧的预设

随程序分发的 LaTeXML 预设（binding）。运行时**只读挂载**进 ar5ivist 容器，用
`--preload` 注入，**不修改论文源码**。开关在 `config.json`。

| 文件 | 作用 | 开关 |
|---|---|---|
| `reaper-qcircuit.sty` | `\Qcircuit` 只是 `\xymatrix` 的别名。LaTeXML 画不了 Xy-pic 图表，而且图表之后的**全部内容会被吞掉**。该 sty 在 `\AtBeginDocument` 把 `\xymatrix` 换成：有救援图就 `\includegraphics`，否则输出 `[diagram omitted]` 占位符。 | `ar5ivist_xypic_stub`（默认 `true`） |
| `reaper-maxerrors.ltxml` | LaTeXML 硬编码 100 个错误就中止整篇（`Fatal:too_many_errors`，仿 TeX；不是命令行选项，而是状态值 `MAX_ERRORS`）。该 binding 用 `AssignValue` 抬高上限。 | `ar5ivist_max_errors`（默认 `100000`，`0` = 不抬高） |

注意二者解决的问题不同：**光抬高上限不够**——它只让 LaTeXML 别中止，被 Xy-pic
破坏的解析照样静默丢内容（实测 `2111.05176`：文档在第 7 节后截断，8-10 节、
参考文献、附录全丢）。

## 图救援：把画不了的图用真 LaTeX 渲染成 SVG

`reaper-qcircuit.sty` 里的占位符可以升级成**真图**——同一个容器里就有完整
TeX Live，所以"用真 LaTeX 画图"和"用 LaTeXML 转 HTML"能一次做完：

```
① 宿主（src/ingestion/diagram_rescue.py）
     walk 论文源码（跟随 \input 顺序）→ 每个 \Qcircuit/\xymatrix 写成一个小文档：
     「论文自己的 preamble + preview + 该片段」→ reaper-diagrams/src/dN.tex
     同时给每个编号写占位 SVG、count.tex(\def\reaperDiagramCount{N})、index.json
② 容器（diagram_rescue.compile_script()，docker run --entrypoint sh）
     latex → dvisvgm --no-fonts → 覆盖成 reaper-diagrams/dN.svg
③ 转换（本目录的 binding）
     第 N 个图 → \includegraphics{reaper-diagrams/dN.svg}；文件不存在 → 占位符
```

要点：

- **编号是两侧唯一的耦合**，两边都按 `\input` 顺序走；不做任何内容嗅探。
- 编译失败的图保留占位符（`verify()` 会统计），不会让整篇失败。
- 输入是**声明式**的：要救援哪些构造写在 `diagram_rescue.CONSTRUCTS`
  （目前是 `\Qcircuit` / `\xymatrix`；以后可以加 `tikzpicture` 之类）。
- 救援文档用 `\ensuremath{...}` 包住片段（图体里的 `_`/`^` 需要在数学模式），
  片段自带的 `$...$` 保持原样（`\raisebox` 之类盒子内部本来就是文本模式）。
- 开关：`ar5ivist_render_diagrams`（默认 `true`）。
