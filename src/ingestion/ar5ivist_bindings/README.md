# ar5ivist_bindings — 转换器侧的预设

随程序分发的 LaTeXML 预设（binding）。运行时**只读挂载**进 ar5ivist 容器，用
`--preload` 注入，**不修改论文源码**。由 `config.json` 控制开关。

| 文件 | 作用 | 开关 |
|---|---|---|
| `reaper-qcircuit.sty` | `\Qcircuit` 只是 `\xymatrix` 的别名。LaTeXML 画不了 Xy-pic 图表，而且图表之后的**全部内容会被吞掉**。这个 sty 在 `\AtBeginDocument` 时把 `\xymatrix` 换成"跳过选项、吞掉图表体、留占位符"的宏。 | `ar5ivist_xypic_stub`（默认 `true`） |
| `reaper-maxerrors.ltxml` | LaTeXML 硬编码 100 个错误就中止整篇（`Fatal:too_many_errors`，仿 TeX；不是命令行选项，而是状态值 `MAX_ERRORS`）。该 binding 用 `AssignValue` 抬高上限。 | `ar5ivist_max_errors`（默认 `100000`，`0` = 不抬高） |

注意两者解决的问题不同：**光抬高上限不够**——它只让 LaTeXML 别中止，被 Xy-pic
破坏的解析照样静默丢内容（实测 `2111.05176`：文档在第 7 节后截断，第 8-10 节、
参考文献、附录全丢）。真正解决问题的是 qcircuit stub。

代价：Xy-pic 图表在 HTML 里显示为 `[diagram omitted]`（LaTeXML 本来也画不了，
要图请看 PDF）。
