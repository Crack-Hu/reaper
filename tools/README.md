# tools — 一次性脚本

| 脚本 | 用途 |
|---|---|
| `migrate.py` | 旧扁平 `data/` 布局 → `data/papers/` 层级布局（迁移时用过，保留作参考） |
| `fix_latexml_source.py` | 把下载的 arXiv LaTeX 源码改成 LaTeXML 能消化的版本（见下） |

## fix_latexml_source.py

**问题**：LaTeXML 有 100 个错误的硬上限（`Fatal:too_many_errors`），超出后仍会写出一个
**空 HTML 壳**。最常见的触发者是 **qcircuit / Xy-pic 电路图**：`\Qcircuit` 体内的每个
`_`/`^` 都报一个「Script ... can only appear in math mode」，十几个电路图就能撞上限，
整篇论文（包括正文）转换失败。案例：`2111.05176`（VQE 综述）。

**做法**：把 `\Qcircuit ... { ... }` 整体替换为 `\mbox{[circuit diagram omitted]}`
（图注在 body 之外，会保留），并给 LaTeXML 不认识的文档类宏（`\cortext`、`\sep`）
补 `\providecommand`。

```bash
python3 tools/fix_latexml_source.py data/papers/<id>/source           # dry-run
python3 tools/fix_latexml_source.py data/papers/<id>/source --apply   # 写 .bak + 修改
```

然后重新生成该论文（已解压的源码会被复用，不会重下）：

```bash
curl 'http://localhost:16625/api/generate?arxiv_id=<id>'
```

**代价**：电路图本身不会出现在 HTML 里（可在 arXiv PDF 里看原图）。
**恢复**：同目录的 `*.tex.bak` 是原文；或 `/api/clear` 后重新下载源码。
