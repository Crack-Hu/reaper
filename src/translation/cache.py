"""Paper cache — unified HTML hash + blocks + translations.

Stores the full pipeline state so that when the HTML hasn't changed,
both parsing AND translation can be skipped entirely.

File: config.translation_cache_dir(arxiv_id)/cache.json

Translations live in *two* places, on purpose:

* ``blocks[].zh``        — the current document's blocks (structure + text + zh)
* ``translations``       — an append-only ``{block_text_hash: zh}`` store

The second one is what makes the cache robust: translations are keyed by the
*paragraph text*, so they survive the document changing shape. Without it, a run
that fetched a different (wrong) source — e.g. arXiv's "specimen" placeholder
page, which has 74 blocks instead of 1029 — replaced ``blocks`` and silently
threw away ~900 translations of the real paper. (Happened with 2111.05176:
a default-order run cost a full re-translation of the 100-page review.)

Structure:
{
  "version": 3,
  "html_hash": "sha256 of raw HTML",
  "src_type": "ar5iv",
  "translations": {"<block hash>": "译文", ...},
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

Version 1 (legacy flat dict: {hash: zh}) and version 2 (translations only inside
``blocks``) are auto-detected and migrated on load.
"""

import json
import hashlib
import threading
from pathlib import Path
from .. import config

# PaperCache stores at `config.translation_cache_dir(arxiv_id) / "cache.json"`.
# PaperCache now stores under `config.translation_cache_dir(arxiv_id) / "cache.json"`.


# 译文库上限：只保留「当前文档用到的」+ 最近的若干条，避免无限增长
# （一篇 100 页论文约 1000 段，2 万条 ≈ 20 篇）。
_MAX_TRANSLATIONS = 20000


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
        self._path = Path(config.translation_cache_dir(arxiv_id)) / "cache.json"
        self.version = 3
        self.html_hash: str = ""
        self.src_type: str = ""
        self.blocks: list[dict] = []
        self._by_hash: dict[str, dict] = {}   # hash → block (current document)
        # 跨文档保留的译文：{段落文本哈希: 译文}（换来源/换 HTML 都不丢）
        self.translations: dict[str, str] = {}
        self._lock = threading.Lock()
        self._loaded = False

    # ── load / save ──

    @classmethod
    def load(cls, arxiv_id: str) -> "PaperCache":
        """Load existing cache or return empty one."""
        cache = cls(arxiv_id)
        cache._path.parent.mkdir(parents=True, exist_ok=True)
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
            # Legacy: flat {hash: zh} dict → migrate to the translations store
            self.version = 1
            self._by_hash = raw
            self.translations = dict(raw)
            self.html_hash = ""
            self.src_type = ""
            self.blocks = []
        else:
            self.version = ver
            self.html_hash = raw.get("html_hash", "")
            self.src_type = raw.get("src_type", "")
            self.blocks = raw.get("blocks", [])
            self._by_hash = {b["hash"]: b for b in self.blocks if b.get("hash")}
            # v3 keeps translations separately; v2 only had them inside blocks
            self.translations = {
                b["hash"]: b["zh"] for b in self.blocks
                if b.get("hash") and b.get("zh")
            }
            self.translations.update(raw.get("translations", {}))

    def save(self):
        with self._lock:
            self._write()

    def _write(self):
        self._prune_translations()
        payload = {
            "version": 3,
            "html_hash": self.html_hash,
            "src_type": self.src_type,
            "translations": self.translations,
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
        self.version = 3
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
            # 译文按段落文本哈希命中（跨文档保留，换来源也不会丢）
            entry["zh"] = self.translations.get(h, "")
            self.blocks.append(entry)

        self._by_hash = {b["hash"]: b for b in self.blocks}

    def merge_translations(self, translated: list[dict]):
        """Write zh back into cache blocks after translation completes."""
        for i, t in enumerate(translated):
            if i < len(self.blocks) and t.get("zh"):
                self.blocks[i]["zh"] = t["zh"]
        self._by_hash = {b["hash"]: b for b in self.blocks}
        for b in self.blocks:
            if b.get("zh"):
                self.translations[b["hash"]] = b["zh"]

    # ── per-block get/put (for on-the-fly translation cache) ──

    def get_zh(self, text: str) -> str | None:
        """Cache hit for a paragraph — by text hash, independent of the document."""
        h = _hash(text)
        zh = self.translations.get(h)
        if zh:
            return zh
        b = self._by_hash.get(h)              # v1 legacy: {hash: zh} 直接存字符串
        return b if isinstance(b, str) and b else None

    def put_zh(self, text: str, zh: str):
        h = _hash(text)
        self.translations[h] = zh
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

    def _prune_translations(self):
        """Keep the store bounded: never drop what the current blocks need."""
        if len(self.translations) <= _MAX_TRANSLATIONS:
            return
        keep = {b.get("hash") for b in self.blocks if isinstance(b, dict)}
        for h in list(self.translations):          # dict 保序：先丢最旧的
            if len(self.translations) <= _MAX_TRANSLATIONS:
                break
            if h not in keep:
                del self.translations[h]

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
    if pc.translations:
        return dict(pc.translations)
    return pc._by_hash if pc.version == 1 else {}


def save(paper_id: str, cache: dict[str, str]):
    """Save translations as {hash: zh} dict (legacy compat)."""
    pc = PaperCache.load(paper_id)
    pc.translations.update(cache)
    for h, zh in cache.items():
        b = pc._by_hash.get(h)
        if isinstance(b, dict):
            b["zh"] = zh
    pc.save()


def get(paper_id: str, text: str) -> str | None:
    h = _hash(text)
    d = load(paper_id)
    return d.get(h)


def put(paper_id: str, text: str, zh: str):
    pc = PaperCache.load(paper_id)
    pc.put_zh(text, zh)
    pc.save()
