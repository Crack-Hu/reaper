# AI-paper-reading (orzorz1) 项目深度分析

> 分析时间：2026-07-20  
> 仓库地址：https://github.com/orzorz1/AI-paper-reading  
> Stars: 22

---

## 1. 项目概述

AI-paper-reading 是一个**面向 AI 论文的读图理解 CLI 小工具**。核心定位：输入一篇论文 PDF，自动挑出最适合理解动机和方法的 1-3 张关键图，生成一份适合 1-2 分钟直接阅读的 Markdown + PDF。

**解决的痛点**：普通读者（非领域专家）想快速读懂一篇 AI 论文时信息过载。这个工具用"选对图 + 讲明白图"策略，把论文压缩成图文并茂的短文档。

**产品哲学**（来自技术文档）："不做大而全的论文助手，不做复杂 Agent，只做一条精简流水线"。

---

## 2. 核心思路与工作流程

### 2.1 总体方法论

**"先用规则和版面模型把'图是谁'做稳，再让 LLM 负责'图为什么重要'和'怎么讲清楚'"** ——确定性任务给算法，理解任务给 LLM。

### 2.2 主流程 (8 步)

```
PDF解析 -> 版面识别 -> 图表候选匹配 -> LLM选图 -> LLM规划结构 -> 多模态LLM逐图解释 -> LLM生成Markdown -> 导出PDF
```

| 步骤 | 模块 | 关键技术 |
|------|------|----------|
| PDF解析 | parser.py | PyMuPDF提取文本/图片/坐标，渲染页面PNG，自动抽取标题摘要 |
| 版面识别 | layout.py | DocLayout-YOLO检测figure/table/caption/text区域，像素坐标映射回PDF坐标 |
| 图表匹配 | matcher.py | 正则识别caption编号，规则打分(垂直距离0.45+水平重叠0.30+上下bonus+IoU 0.05) |
| 选关键图 | selector.py | 文本LLM选图，支持method/experiment偏好，short/medium/long篇幅 |
| 规划结构 | planner.py | 文本LLM生成StoryOutline：中文译名、背景、方法核心、结果概述、图角色 |
| 逐图解释 | explainer.py | 多模态LLM解释每张图：what_it_shows/how_to_read/why_it_matters |
| 生成Markdown | composer.py | LLM直接写Markdown，fallback规则渲染，后处理兜底 |
| 导出PDF | pdf_exporter.py | reportlab渲染，自实现Markdown解析器，跨平台中文字体 |

---

## 3. 架构设计

### 3.1 代码结构

```
src/paper_reading/
├── cli.py              # Typer CLI入口 (build/batch命令)
├── config.py           # .env + YAML + 环境变量 三层配置
├── models.py           # 15+ Pydantic数据模型
├── llm.py              # OpenAI兼容接口封装 (重试/JSON容错/image base64)
├── errors.py           # 统一异常体系
├── utils.py            # 工具函数
├── logging_utils.py    # 日志配置
└── pipeline/
    ├── orchestrator.py # 总编排器 (串起全部子模块)
    ├── parser.py       # PDF解析 + 标题/摘要抽取
    ├── layout.py       # DocLayout-YOLO封装
    ├── matcher.py      # caption识别 + 候选打分 + 裁图
    ├── selector.py     # LLM选图
    ├── planner.py      # LLM生成阅读骨架
    ├── explainer.py    # 多模态LLM逐图解释
    ├── composer.py     # LLM写作 + 规则兜底
    └── pdf_exporter.py # Markdown->PDF渲染
```

### 3.2 关键数据模型

- `BoundingBox`：带 IoU/距离/重叠/padding 的矩形框
- `ParsedPaper/ParsedPage/PageTextBlock/PageImageBlock`：解析结果
- `LayoutRegion`：版面识别（figure/table/caption/text）
- `FigureCandidate/FigureMatchOption`：候选图和匹配
- `SelectedFigure`：LLM选出的图（含reason/rank）
- `StoryOutline`：阅读骨架中间层
- `FigureExplanation`：单图解释
- `FinalDocument`：最终文档

---

## 4. 关键技术实现

### 4.1 LLM 客户端封装 (llm.py)

三个核心 API，统一的 Pydantic 类型化输出：
```python
client.complete_json(model, system_prompt, user_prompt, response_model=SomeModel)
client.complete_vision_json(model, system_prompt, user_prompt, image_paths=[...], response_model=SomeModel)
client.complete_text(model, system_prompt, user_prompt)
```
特性：429/5xx 自动退避重试、滑动窗口 JSON 片段提取容错、图片自动 base64 编码。

### 4.2 图表匹配算法 (matcher.py)

纯规则+启发式，完全不用 LLM：
- Caption 识别：正则 `fig(ure)?\s*\d+[a-z]?` + 版面 caption 区域交叉验证
- 去重：文本+坐标签名
- 打分公式：`垂直距离(0.45) + 水平重叠(0.30) + 上下关系bonus + IoU(0.05)`
- "图在上 caption 在下" bonus 0.2（vs 0.05），符合多数论文排版
- 裁图：fitz clip 在 PDF 坐标下直接裁剪

### 4.3 选图策略

在 LLM 选图之上加策略层：
- short: 按偏好选1张
- medium: 角色优先级排序后截取
- long: 确保method和result各至少一张

图角色推断：通过 caption 关键词分类
- `result/experiment/benchmark/ablation` → result
- `pipeline/framework/architecture/method/model` → method
- `task/motivation/problem/setting` → problem

### 4.4 PDF 导出

- 自实现 Markdown 解析器（h1/h2/h3/段落/引用/列表/图片/分页）
- 中英混排插入零宽空格（\u2060）防断行
- 跨平台中文字体自动检测

### 4.5 中间产物全量保存

`artifacts/` 下保存所有中间 JSON，便于 prompt 迭代和调试。

---

## 5. 使用方式

```bash
pip install -e .
cp .env.example .env  # 填入API key

# 单篇
paper-read build paper.pdf --focus method --length medium
# 批量
paper-read batch /path/to/papers/
```

输出：`原pdf名-时间/paper_readable.md` + `paper_readable.pdf` + `artifacts/`

---

## 6. 亮点

1. **务实的克制**："不做大而全"，整个 src 约 2000 行
2. **"规则 + 模型"混合**：图表匹配用规则不用 LLM，确定性高
3. **中间层设计**：`StoryOutline` 解耦选图和写作，更稳定可 debug
4. **选图策略可控**：LLM 输出 + 策略层双重保障
5. **全量留存**：所有中间产物 JSON 序列化，便于 prompt 迭代
6. **纯 Python PDF**：不依赖浏览器，跨平台字体自动检测
7. **可测试**：Fake 注入，无需 LLM 即可端到端测试

---

## 7. 对我们项目的启发

| 维度 | 启发 |
|------|------|
| **架构** | Pipeline > Agent；Pydantic 贯穿全流程；依赖注入 + Fake 测试 |
| **策略** | 确定性任务不用 LLM；LLM 输出加后处理兜底；分阶段 LLM（选图/规划/解释/写作各用不同 prompt） |
| **工程** | 统一 LLM 客户端（重试+JSON容错）；自实现 dotenv；遇 References 截断正文；标题抽取过滤干扰项；跨平台字体 |
| **扩展方向** | PPT导出、多语言、公式支持、Web前端、多论文对比、更多版面模型 |

---

**技术栈**：Python 3.9+ / Typer / Pydantic v2 / PyMuPDF / DocLayout-YOLO / httpx / reportlab / YAML
