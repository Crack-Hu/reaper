"""Reaper: 科研文章阅读工程 — 配置模块"""

import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")


def _load_config():
    path = os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


cfg = _load_config()
api_cfg = cfg.get("api", {})
srv_cfg = cfg.get("server", {})
trl_cfg = cfg.get("translator", {})

# ── URL 和纯配置值 ──

AR5IV_BASE = "https://ar5iv.labs.arxiv.org/html"

SOURCES = cfg.get("sources", [
    {"type": "arxiv_html"},
    {"type": "ar5iv"},
    {"type": "ar5ivist_docker"},
])

AR5IVIST_DOCKER_IMAGE = cfg.get("ar5ivist_docker_image", "latexml/ar5ivist:2512.17")

# LaTeXML 硬编码 100 个错误就中止整篇转换（Fatal:too_many_errors），而错误多的
# 文档往往照样能转换。这里通过 --preload 的 binding 把上限抬高（0 = 不改）。
AR5IVIST_MAX_ERRORS = int(cfg.get("ar5ivist_max_errors", 100000))

# LaTeXML 画不了 Xy-pic/Qcircuit 图表，而且会因此吞掉图表之后的全部内容。
# 开启后用一个 binding 把 \xymatrix 换成"跳过选项、吞掉图表体"的宏（不改论文源码）。
AR5IVIST_XYPIC_STUB = bool(cfg.get("ar5ivist_xypic_stub", True))

# LaTeXML 画不了的图（Xy-pic/Qcircuit…），用容器里的真 LaTeX 渲染成 SVG 再插回
# （见 src/ingestion/diagram_rescue.py）。关闭则只留 [diagram omitted] 占位符。
AR5IVIST_RENDER_DIAGRAMS = bool(cfg.get("ar5ivist_render_diagrams", True))
AR5IVIST_IDLE_TIMEOUT = int(cfg.get("ar5ivist_idle_timeout", 120))

LLM_API_KEY = api_cfg.get("key", "")
LLM_BASE_URL = api_cfg.get("base_url", "https://api.deepseek.com/v1")
LLM_MODEL = api_cfg.get("model", "deepseek-chat")

# 单次请求的输出上限。**推理模型的推理 token 也算在这里面**，所以不能给得太小：
# 翻译一个长小节时，推理能轻易吃掉几千 token，正文就没预算了（表现为
# content: null + finish_reason: length）。
LLM_MAX_TOKENS = int(api_cfg.get("max_tokens", 16384))

# 原样合并进 /chat/completions 请求体的额外参数，用于传厂商特定开关。
# 典型用途：关掉推理模型的思考过程（翻译是机械任务，推理纯浪费）：
#   "params": {"reasoning_effort": "none"}
# 若端点不认这些参数（返回 400），代码会自动去掉它们重试一次。
LLM_PARAMS = dict(api_cfg.get("params", {}))

SERVER_HOST = srv_cfg.get("host", "0.0.0.0")
SERVER_PORT = int(srv_cfg.get("port", 16625))

# ── 共用目录（跨论文）───

DICT_DIR = os.path.join(DATA_DIR, "dict")
LOG_DIR = os.path.join(DATA_DIR, "logs")
DEFAULT_DICT_PATH = os.path.join(DICT_DIR, "user_terms.json")

# ── 按论文分片的数据 ──
#
# data/
#   papers/{arxiv_id}/
#     source/                  原始材料（HTML、TeX、图片）
#     process/
#       translation_cache/     翻译缓存（JSON）
#       state.json             任务状态
#       reaper_html/           生成的双语 HTML + assets
#     chat/
#       workspace/             agent 上下文（paper.md、blocks.json…）
#       sessions/              pi 会话文件
#   dict/
#   logs/

PAPERS_DIR = os.path.join(DATA_DIR, "papers")


def _p(arxiv_id: str, *parts: str) -> str:
    return os.path.join(PAPERS_DIR, arxiv_id, *parts)


def source_dir(arxiv_id: str) -> str:
    """原始文件（HTML、TeX、图片）"""
    return _p(arxiv_id, "source")


def process_dir(arxiv_id: str) -> str:
    """处理产物根目录"""
    return _p(arxiv_id, "process")


def translation_cache_dir(arxiv_id: str) -> str:
    return _p(arxiv_id, "process", "translation_cache")


def task_state_path(arxiv_id: str) -> str:
    return _p(arxiv_id, "process", "state.json")


def reaper_html_dir(arxiv_id: str) -> str:
    """生成的双语 HTML + assets"""
    return _p(arxiv_id, "process", "reaper_html")


def chat_dir(arxiv_id: str) -> str:
    """对话数据根目录"""
    return _p(arxiv_id, "chat")


def chat_workspace_dir(arxiv_id: str) -> str:
    """agent 上下文（paper.md / blocks.json / OUTLINE.md / preamble.tex）"""
    return _p(arxiv_id, "chat", "workspace")


def chat_sessions_dir(arxiv_id: str) -> str:
    """pi 会话文件"""
    return _p(arxiv_id, "chat", "sessions")


def ensure_paper_dirs(arxiv_id: str) -> None:
    """Create the full directory tree for a paper."""
    for d in (source_dir, process_dir, reaper_html_dir,
              chat_dir, chat_workspace_dir, chat_sessions_dir):
        os.makedirs(d(arxiv_id), exist_ok=True)


# ── Chat / pi agent ──

CHAT_IDLE_TIMEOUT = int(cfg.get("chat", {}).get("idle_timeout", 900))
CHAT_TOOLS = cfg.get("chat", {}).get("tools", "read,grep,find,ls")
PI_BIN = cfg.get("chat", {}).get("pi_bin", "pi")


def _default_extensions() -> list:
    p = os.path.join(ROOT, "pi-extensions", "reaper-tree.ts")
    return [p] if os.path.exists(p) else []


PI_EXTENSIONS = cfg.get("chat", {}).get("extensions", _default_extensions())
CHAT_ALLOW_REMOTE = bool(cfg.get("chat", {}).get("allow_remote", False))
CHAT_MODEL = cfg.get("chat", {}).get("model") or None
CHAT_THINKING = cfg.get("chat", {}).get("thinking") or None

# ── 翻译设置 ──

TRANSLATION_CONCURRENCY = int(trl_cfg.get("concurrency", 3))
TRANSLATION_BATCH_SIZE = 5
TRANSLATION_MAX_RETRIES = 3


# ── 向后兼容别名（待逐步迁移）───
# 新代码请用上面的函数，旧代码暂时还能工作
AR5IV_DIR = PAPERS_DIR  # 不再使用；旧代码的引用将指向错误路径
CACHE_DIR = os.path.join(DATA_DIR, "translation_cache")
ARXIV_SOURCE_DIR = os.path.join(DATA_DIR, "arxiv_source")
AR5IVIST_OUTPUT_DIR = os.path.join(DATA_DIR, "ar5ivist")
ZOTERO_DIR = os.path.join(DATA_DIR, "zotero")
OUTPUT_DIR = ZOTERO_DIR
CHAT_DIR = os.path.join(DATA_DIR, "chat")