# MinerU (opendatalab) 技术分析报告

> 分析时间：2026-07-20  
> 仓库地址：https://github.com/opendatalab/mineru  
> 类型：**技术手段仓库** — PDF 结构化解析引擎

---

## 1. 项目概述

### 1.1 是什么

MinerU 是上海人工智能实验室 OpenDataLab 开源的高性能文档解析引擎。支持将 PDF、图片、DOCX、PPTX、XLSX 等格式转换为结构化 Markdown、JSON、DOCX、HTML、LaTeX。能处理复杂排版（多栏、表格、公式、扫描件），支持 109 种语言 OCR。

### 1.2 核心能力

- 版面分析：识别标题、段落、表格、公式、图片、脚注、页眉页脚
- 公式识别：LaTeX 格式输出
- 表格提取：HTML 格式保留结构
- 多模态：pipeline（传统OCR）、vlm-engine（视觉语言模型）、hybrid-engine（混合）
- 多语言 OCR：109 种语言

### 1.3 精度

| 后端 | 精度 | 硬件需求 |
|------|------|----------|
| pipeline | ~86% | CPU 即可（4GB 显存或无 GPU） |
| vlm-engine | ~95% | 需要 GPU |
| hybrid-engine | ~95% | CPU/GPU 均可 |

---

## 2. 三种调用方式

### 2.1 REST API（在线服务）

**Agent API（免费，无需 Token）**：
- 轻量级，IP 限频
- 文件限制：≤10MB，≤20 页
- 适用：快速测试、小文件

**Precision API（需 Token）**：
- 更大文件：≤200MB，≤200 页
- 批量处理：≤200 个文件
- 支持后端选择：pipeline / vlm
- 异步任务模式：提交 → 轮询 → 下载

**API 调用流程**：
```
POST /api/v4/file-urls/batch    →  获取上传 URL + batch_id
PUT  {presigned_url}             →  上传 PDF 文件
GET  /api/v4/extract-results/batch/{batch_id}  →  轮询结果
     ↓
  下载 ZIP（含 Markdown + JSON + images）
```

### 2.2 Python SDK

```bash
pip install mineru-open-sdk
```

```python
from mineru_open_sdk import MinerUClient

client = MinerUClient(token="your-token")

# Flash Extract（免登录，轻量）
result = client.flash_extract("paper.pdf")
print(result.markdown)

# Precision Extract（精准解析）
result = client.precision_extract(
    "paper.pdf",
    backend="pipeline",  # 或 "vlm" / "hybrid"
)
# 下载结果 ZIP
result.download("output/")
```

### 2.3 CLI 命令行

**Python CLI（全功能）**：
```bash
pip install mineru
mineru --backend pipeline paper.pdf  # CPU 模式
mineru --backend vlm paper.pdf       # GPU 高精度
```

**mineru-open-api CLI（零依赖二进制）**：
```bash
# 免登录快速提取
mineru-open-api flash-extract paper.pdf

# 精准解析
mineru-open-api precision-extract paper.pdf --token YOUR_TOKEN -b hybrid
```

---

## 3. 输出格式

### 3.1 标准输出结构

```
output/{pdf_name}/
├── full.md              # 完整 Markdown 文档
├── full.json            # 结构化 JSON（含 layout 信息）
├── images/              # 提取的图片文件
└── layout.pdf           # 版面分析可视化
```

### 3.2 Markdown 输出示例

```markdown
# Section Title

Paragraph text with **bold** and *italic*.

![figure_1](images/figure_1.jpg)
*Figure 1: Model architecture overview*

| Method | Accuracy | F1 |
|--------|----------|----|
| Baseline | 0.85 | 0.82 |

$$E = mc^2$$
```

### 3.3 JSON 结构（关键字段）

```json
{
  "pages": [{
    "page_num": 1,
    "blocks": [{
      "type": "text|title|table|image|equation|footer",
      "bbox": [x0, y0, x1, y1],
      "content": "...",
      "meta": {}
    }]
  }]
}
```

---

## 4. 在文献阅读助手中的集成分析

### 4.1 适用场景

| 场景 | 推荐后端 | 说明 |
|------|----------|------|
| 快速预览论文结构 | flash-extract (pipeline) | 免费、快速 |
| 深度阅读（含公式） | precision (hybrid/vlm) | 公式识别准确 |
| 批量处理论文库 | precision 批量模式 | 最多 200 篇 |
| 离线/隐私敏感 | 本地部署 CLI | 数据不出本地 |

### 4.2 集成架构建议

```
用户上传 PDF
    ↓
MinerU API/SDK 解析
    ↓
full.md + full.json + images/
    ↓
下游处理：
  ├── 全文翻译（LLM）
  ├── 图表理解（多模态 LLM）
  ├── 结构化笔记生成
  ├── 知识图谱构建（从 JSON layout 提取关系）
  └── 向量化检索（chunk 切分）
```

### 4.3 关键集成点

1. **统一入口封装**：封装 API + CLI + SDK 三种调用方式，根据环境自动选择
2. **输出标准化**：参考 huicod 的 `_normalize_output()` 设计，处理不同后端输出差异
3. **进度追踪**：异步 API 轮询 + progress.json 记录状态
4. **错误处理**：API 限频退避、文件大小检查、页数限制检查

### 4.4 成本考量

- **Flash Extract**：免费，适合日常使用，但有频率和大小限制
- **Precision API**：需要 Token（官方提供免费额度），按文件或页数计费
- **本地部署**：需要 GPU（vlm）或 CPU（pipeline），无调用限制

---

## 5. 关键技术点

### 5.1 三后端架构

```
用户请求 → 路由层
           ├── pipeline: DocLayout-YOLO + OCR + 规则匹配
           ├── vlm-engine: 视觉语言模型端到端
           └── hybrid-engine: pipeline + vlm 混合（推荐）
```

### 5.2 混合引擎的优势

- pipeline 处理简单版面（单栏、无公式）
- vlm 处理复杂区域（多栏、公式密集、表格）
- 自动决策：版面分析 → 复杂度评估 → 路由

### 5.3 与同类工具对比

| 特性 | MinerU | Unstructured | marker |
|------|--------|-------------|--------|
| 开源 | ✅ | ✅ | ✅ |
| 公式识别 | ✅ LaTeX | ❌ | ✅ |
| 表格保留 | ✅ HTML | ✅ | ❌ |
| 多语言 OCR | ✅ 109种 | 有限 | 有限 |
| API 服务 | ✅ 免费层 | 付费 | ❌ |
| GPU 部署 | ✅ vlm | ❌ | ✅ |

---

## 6. 注意与限制

- v2.5 vlm 后端输出不向后兼容 pipeline
- 项目相对"年轻"，与商业方案相比可能有局限
- Flash Extract 仅输出 Markdown（CDN 图片链接），无 JSON
- Precision API 异步模式需要轮询等待
