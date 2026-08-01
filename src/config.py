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

# --- ar5iv 来源 ---
AR5IV_BASE = "https://ar5iv.labs.arxiv.org/html"

# HTML 来源配置（按优先级排列）
SOURCES = cfg.get("sources", [{"type": "ar5iv"}])

# ar5ivist Docker 镜像
AR5IVIST_DOCKER_IMAGE = cfg.get("ar5ivist_docker_image", "latexml/ar5ivist:2512.17")

# arxiv source 下载目录（ar5ivist_docker 使用）
ARXIV_SOURCE_DIR = os.path.join(DATA_DIR, "arxiv_source")

# ar5ivist Docker 输出目录
AR5IVIST_OUTPUT_DIR = os.path.join(DATA_DIR, "ar5ivist")

# ar5ivist Docker 空闲超时（秒）：持续无日志输出超过此时间则视为卡死
# 只要还在输出日志就不算超时，适合超长文章的转换
AR5IVIST_IDLE_TIMEOUT = int(cfg.get("ar5ivist_idle_timeout", 120))

# --- 翻译 API ---
LLM_API_KEY = api_cfg.get("key", "")
LLM_BASE_URL = api_cfg.get("base_url", "https://api.deepseek.com/v1")
LLM_MODEL = api_cfg.get("model", "deepseek-chat")

# --- 服务端 ---
SERVER_HOST = srv_cfg.get("host", "0.0.0.0")
SERVER_PORT = int(srv_cfg.get("port", 16625))

# --- 数据目录 (所有中间产物) ---
CACHE_DIR = os.path.join(DATA_DIR, "translation_cache")
DICT_DIR = os.path.join(DATA_DIR, "dict")
LOG_DIR = os.path.join(DATA_DIR, "logs")
AR5IV_DIR = os.path.join(DATA_DIR, "ar5iv")
ZOTERO_DIR = os.path.join(DATA_DIR, "zotero")

# --- 术语字典路径 ---
DEFAULT_DICT_PATH = os.path.join(DICT_DIR, "user_terms.json")

# --- 输出路径 ---
OUTPUT_DIR = ZOTERO_DIR

# --- 翻译设置 ---
TRANSLATION_CONCURRENCY = int(trl_cfg.get("concurrency", 3))
TRANSLATION_BATCH_SIZE = 5
TRANSLATION_MAX_RETRIES = 3
