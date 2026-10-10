# ar5ivist (dginev) 技术分析

> 仓库: https://github.com/dginev/ar5ivist

## 1. 项目概述

**ar5ivist** 是 LaTeXML 的 Docker 封装，把 LaTeX 源码转为 ar5iv 风格的 HTML5。本质是 `latexmlc` 命令的薄封装。

与 ar5iv.org 的关系：ar5iv.org 是 Web 服务（Rust+Rocket+Redis），论文已**批量预转换**好存在 ZIP 中，访问时从 Redis/ZIP 读取。ar5ivist 是本地复现同样效果的工具。

渲染效果：公式→MathML（浏览器原生渲染）、图片→PNG（ImageMagick转换）、表格→LaTeXML HTML 表格。

## 2. 运行方式

```bash
docker run -v "$(pwd)":/docdir -w /docdir \
  --user "$(id -u):$(id -g)" \
  latexml/ar5ivist:2512.17 --source=main.tex --destination=html/main.html
```

Docker 镜像巨大（含 texlive-full + LaTeXML + ar5iv-bindings，几 GB）。

## 3. ⚠️ 时间成本：不适合实时管道

| 场景 | 时间 |
|------|------|
| 简单短文（2页） | ~30s-2min |
| 典型 CS 论文（8-12页） | ~2-10min |
| 公式密集型 | ~10-45min |
| 最坏情况 | 超时(45min)失败 |

**为什么慢**：
1. LaTeXML 是 Perl 实现，纯解释执行
2. expl3（LaTeX3编程层）加载就需 ~20 分钟（texlive 2023）
3. ImageMagick EPS/PDF→PNG 转换
4. 单线程串行，`--timeout=2700`（45分钟）

## 4. 结论

**ar5ivist 不适合作为实时文献阅读管道的转换后端。** 它的设计目标是**批量离线转换+高质量**，不是低延迟。

推荐替代方案：
- **使用 ar5iv.org 已有数据**：如果论文在 arXiv 且已被处理，直接抓 HTML
- **离线预转换+缓存**：提前批量转换好存起来
- **轻量替代**：Pandoc（快得多）、TeX4ht（老牌方案，速度中等）
- **仅用 LaTeXML 转公式片段**：latexml-runner 适用场景
