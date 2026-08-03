"""Paper cache — unified HTML hash + blocks + translations.

Stores the full pipeline state so that when the HTML hasn't changed,
both parsing AND translation can be skipped entirely.

File: data/translation_cache/{arxiv_id}.json

Structure:
{
  "version": 2,
  "html_hash": "sha256 of raw HTML",
  "src_type": "ar5iv",
  "blocks": [
    {
      "idx": 0,
      "hash": "sha256 of en text",
      "en": "original English",
      "zh": "Chinese translation",
      "type": "title",
      "level": 0,
      "label": "",
      "math_map": {}
    },
    ...
  ]
}

Version 1 (legacy flat dict: {hash: zh}) is auto-detected and converted on load.
"""

import json
import hashlib
import threading
from pathlib import Path
from .. import config

CACHE_DIR = Path(config.CACHE_DIR)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def html_hash(html: str) -> str:
    """Compute cache key for the full HTML content."""
    return hashlib.sha256(html.encode()).hexdigest()


class PaperCache:
    """Unified paper cache: HTML hash + segmented blocks + translations.

    Usage:
        cache = PaperCache.load("2310.05900")
        if cache.match(html):
            blocks, translations = cache.restore()   # skip parse + translate
        else:
            # parse → blocks, then:
            cache.update(html, src_type, blocks)
            cache.save()
    """

    def __init__(self, arxiv_id: str):
        self.arxiv_id = arxiv_id
        self._path = CACHE_DIR / f"{arxiv_id}.json"
        self.version = 2
        self.html_hash: str = ""
        self.src_type: str = ""
        self.blocks: list[dict] = []
        self._by_hash: dict[str, dict] = {}  # hash → block
        self._lock = threading.Lock()
        self._loaded = False

    # ── load / save ──

    @classmethod
    def load(cls, arxiv_id: str) -> "PaperCache":
        """Load existing cache or return empty one."""
        cache = cls(arxiv_id)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if cache._path.exists():
            try:
                cache._read()
                cache._loaded = True
            except Exception:
                pass  # Corrupted → treat as empty
        return cache

    def _read(self):
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        ver = raw.get("version", 1)

        if ver == 1:
            # Legacy: flat {hash: zh} dict → migrate on next save
            self.version = 1
            self._by_hash = raw
            self.html_hash = ""
            self.src_type = ""
            self.blocks = []
        else:
            self.version = ver
            self.html_hash = raw.get("html_hash", "")
            self.src_type = raw.get("src_type", "")
            self.blocks = raw.get("blocks", [])
            self._by_hash = {b["hash"]: b for b in self.blocks if b.get("hash")}

    def save(self):
        with self._lock:
            self._write()

    def _write(self):
        payload = {
            "version": 2,
            "html_hash": self.html_hash,
            "src_type": self.src_type,
            "blocks": self.blocks,
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── match / restore ──

    def match(self, html: str) -> bool:
        """True if cached HTML hash matches current HTML."""
        return bool(self.html_hash) and self.html_hash == html_hash(html)

    def restore(self) -> list[dict]:
        """Return cached blocks — skip parsing AND translation entirely.

        Blocks have all fields: idx, en, zh, type, level, label, math_map.
        """
        return list(self.blocks)

    # ── update ──

    def update(self, html: str, src_type: str, blocks: list):
        """Update cache: compute new html_hash, merge old translations by block hash.

        Args:
            html: raw HTML content
            src_type: source type string
            blocks: list of Block objects (from mark_and_extract)
        """
        new_hash = html_hash(html)
        self.html_hash = new_hash
        self.src_type = src_type
        self.version = 2
        self.blocks = []

        for i, b in enumerate(blocks):
            h = _hash(b.text)
            entry = {
                "idx": i,
                "hash": h,
                "en": b.text,
                "zh": "",
                "type": b.type,
                "level": b.level,
                "label": b.label,
                "math_map": b.math_map,
            }
            # Carry over translation if block hash matches a cached block
            if h in self._by_hash:
                old = self._by_hash[h]
                if isinstance(old, str):
                    entry["zh"] = old  # v1 legacy: {hash: zh}
                else:
                    entry["zh"] = old.get("zh", "")
            self.blocks.append(entry)

        self._by_hash = {b["hash"]: b for b in self.blocks}

    def merge_translations(self, translated: list[dict]):
        """Write zh back into cache blocks after translation completes."""
        for i, t in enumerate(translated):
            if i < len(self.blocks) and t.get("zh"):
                self.blocks[i]["zh"] = t["zh"]
        self._by_hash = {b["hash"]: b for b in self.blocks}

    # ── per-block get/put (for on-the-fly translation cache) ──

    def get_zh(self, text: str) -> str | None:
        h = _hash(text)
        b = self._by_hash.get(h)
        if b is None:
            return None
        if isinstance(b, str):
            return b  # v1 legacy
        return b.get("zh")

    def put_zh(self, text: str, zh: str):
        h = _hash(text)
        b = self._by_hash.get(h)
        if isinstance(b, dict):
            b["zh"] = zh
        elif isinstance(b, str):
            # v1 legacy: convert string value to block dict
            entry = {"idx": len(self.blocks), "hash": h, "en": text, "zh": zh,
                     "type": "para", "level": 0, "label": "", "math_map": {}}
            self.blocks.append(entry)
            self._by_hash[h] = entry
        else:
            entry = {
                "idx": len(self.blocks),
                "hash": h,
                "en": text,
                "zh": zh,
                "type": "para",
                "level": 0,
                "label": "",
                "math_map": {},
            }
            self.blocks.append(entry)
            self._by_hash[h] = entry

    # ── stats ──

    def __len__(self):
        n = len(self.blocks)
        if n == 0 and self.version == 1:
            n = len(self._by_hash)
        return n

    @property
    def translated_count(self):
        n = 0
        for b in self.blocks:
            if isinstance(b, dict) and b.get("zh"):
                n += 1
            elif isinstance(b, str) and b:
                n += 1
        # Also count v1 string entries in _by_hash not yet in blocks
        if self.version == 1:
            n = max(n, sum(1 for v in self._by_hash.values() if isinstance(v, str) and v))
        return n


# ── Legacy API (used by translate_blocks on-the-fly) ──

def load(paper_id: str) -> dict[str, str]:
    """Load translations as {hash: zh} dict (legacy compat)."""
    pc = PaperCache.load(paper_id)
    if pc.version == 1:
        return pc._by_hash  # already {hash: zh}
    return {b["hash"]: b["zh"] for b in pc.blocks if b.get("zh")}


def save(paper_id: str, cache: dict[str, str]):
    """Save translations as {hash: zh} dict (legacy compat)."""
    pc = PaperCache.load(paper_id)
    if pc.version == 1:
        pc._by_hash = cache
    else:
        for h, zh in cache.items():
            if h in pc._by_hash:
                pc._by_hash[h]["zh"] = zh
    pc.save()


def get(paper_id: str, text: str) -> str | None:
    h = _hash(text)
    d = load(paper_id)
    return d.get(h)


def put(paper_id: str, text: str, zh: str):
    pc = PaperCache.load(paper_id)
    pc.put_zh(text, zh)
    pc.save()
