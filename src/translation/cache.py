"""Translation cache — in-memory during translation, write once at the end."""

import json
import hashlib
import threading
from pathlib import Path
from .. import config

CACHE_DIR = Path(config.CACHE_DIR)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class TranslationCache:
    """In-memory cache: load once, write once."""

    def __init__(self, arxiv_id: str):
        self._path = CACHE_DIR / f"{arxiv_id}.json"
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))

    def get(self, text: str) -> str | None:
        return self._data.get(_hash(text))

    def put(self, text: str, zh: str):
        with self._lock:
            self._data[_hash(text)] = zh
            self._save_locked()

    def save(self):
        with self._lock:
            self._save_locked()

    def _save_locked(self):
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def __len__(self):
        return len(self._data)


# ── Legacy API (used by translate_blocks) ──

def load(paper_id: str) -> dict[str, str]:
    path = CACHE_DIR / f"{paper_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save(paper_id: str, cache: dict[str, str]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{paper_id}.json").write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get(paper_id: str, text: str) -> str | None:
    return load(paper_id).get(_hash(text))


def put(paper_id: str, text: str, zh: str):
    c = load(paper_id)
    c[_hash(text)] = zh
    save(paper_id, c)
