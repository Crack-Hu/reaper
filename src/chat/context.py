"""Chat layer: paper context preparation for the pi agent.

Turns a paper that Reaper already processed (cached HTML + parsed blocks)
into a small, byte-stable *workspace* the agent can read and grep:

    data/chat/{arxiv_id}/workspace/
    ├── paper.md        Markdown + block anchors + LaTeX math
    ├── blocks.json     paragraph index (ids, sentence spans, math)
    ├── OUTLINE.md      byte-stable TOC front block
    └── metadata.json   paper metadata + cleaner version

Macro expansion
---------------
Annotations preserve the author's original LaTeX, including custom macros.
If a .tex preamble is available, we expand macros here (strings only,
no magic) so the agent sees clean, standard LaTeX.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
from pathlib import Path

from .. import config
from ..ingestion.parser import Block, mark_and_extract
from .expand_macros import build_macro_table, expand_macros

CONTEXT_VERSION = 2

# --------------------------------------------------------------------------- #
# math: extract + restore
# --------------------------------------------------------------------------- #

_TEX_ANNOTATION = re.compile(
    r'<annotation\b[^>]*encoding="application/x-tex"[^>]*>(.*?)</annotation>',
    re.DOTALL,
)
_ALT_TEXT = re.compile(r'\balttext="([^"]*)"')


def math_to_latex(math_html: str, macro_table: dict | None = None) -> str:
    """Extract the author's LaTeX from a LaTeXML `<math>` element.

    When `macro_table` is provided, author macros are expanded.
    """
    m = _TEX_ANNOTATION.search(math_html)
    tex = ""
    if m:
        tex = _html.unescape(m.group(1)).strip()
    if not tex:
        m = _ALT_TEXT.search(math_html)
        if m:
            tex = _html.unescape(m.group(1)).strip()
    if not tex:
        tex = re.sub(r"<[^>]+>", "", math_html).strip()
    if tex and macro_table:
        tex = expand_macros(tex, macro_table)
    return tex


def restore_math(text: str, math_map: dict[str, str],
                 macro_table: dict | None = None) -> str:
    """Replace ``MATH_N`` placeholders with ``$...$`` LaTeX.

    Sorted by key length descending so ``MATH_10`` is replaced before ``MATH_1``.
    """
    out = text
    for key in sorted(math_map, key=len, reverse=True):
        out = out.replace(key, f"${math_to_latex(math_map[key], macro_table)}$")
    return out


# --------------------------------------------------------------------------- #
# footnotes
# --------------------------------------------------------------------------- #

_FN_RE = re.compile(r"\s*FN_\d+\s*")
_CITE_RE = re.compile(r"\[\s(\d+)\s\]")


def _clean_text(text: str) -> str:
    text = _FN_RE.sub(" ", text)
    text = _CITE_RE.sub(r"[\1]", text)
    text = text.replace(" ,", ",").replace(" .", ".")
    return " ".join(text.split())


# --------------------------------------------------------------------------- #
# sentence segmentation
# --------------------------------------------------------------------------- #

_ABBREV = {
    "fig", "figs", "eq", "eqs", "sec", "secs", "ref", "refs", "tab", "tabs",
    "al", "e.g", "i.e", "cf", "vs", "resp", "approx", "ca", "no", "nos",
    "mr", "mrs", "ms", "dr", "prof", "st", "etc", "inc", "ltd", "vol", "pp",
    "ed", "eds", "ch", "chap", "app", "appendix", "supp", "phys", "rev",
}
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def split_sentences(text: str) -> list[dict]:
    """Split ``text`` into sentences with 1-indexed char spans."""
    if not text.strip():
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_BOUNDARY.finditer(text):
        head = text[start:m.start()].rstrip()
        last = re.split(r"[\s(\[]", head)[-1].lower().rstrip(".")
        if last in _ABBREV or (len(last) == 1 and last.isalpha()):
            continue
        spans.append((start, m.start()))
        start = m.start()
    spans.append((start, len(text)))
    out = []
    for i, (a, b) in enumerate(spans, 1):
        seg = text[a:b].strip()
        if not seg:
            continue
        lead = len(text[a:b]) - len(text[a:b].lstrip())
        trail = len(text[a:b]) - len(text[a:b].rstrip())
        out.append({"i": i, "ch": [a + lead, b - trail], "text": seg})
    return out


# --------------------------------------------------------------------------- #
# block index
# --------------------------------------------------------------------------- #

def build_block_index(blocks: list[Block],
                      macro_table: dict | None = None) -> list[dict]:
    """Build the addressable paragraph index for the agent."""
    index: list[dict] = []
    for i, b in enumerate(blocks):
        text = _clean_text(restore_math(b.text, b.math_map, macro_table))
        entry: dict = {
            "id": i,
            "type": b.type,
            "level": b.level,
            "text": text,
            "sentences": split_sentences(text),
        }
        if b.math_map:
            entry["math"] = [
                {"placeholder": k, "tex": math_to_latex(v, macro_table)}
                for k, v in sorted(b.math_map.items())
            ]
        if b.label:
            entry["label"] = b.label
        index.append(entry)
    return index


# --------------------------------------------------------------------------- #
# outline
# --------------------------------------------------------------------------- #

def build_outline(blocks: list[Block],
                  macro_table: dict | None = None) -> str:
    """Byte-stable TOC front block. No ``bodyChars`` — it triggers search loops."""
    lines = ["# Paper outline", ""]
    heads = [
        (i, b) for i, b in enumerate(blocks)
        if b.type == "section" or (b.type == "title" and b.level >= 1)
    ]
    for n, (i, b) in enumerate(heads):
        indent = "  " * max(0, b.level - 1)
        title = _clean_text(restore_math(b.text, b.math_map, macro_table))
        lines.append(f"- {indent}{title} (block {i})")
    lines += [
        "",
        "## How to use this workspace",
        "",
        "- `paper.md` has the full paper with `<!-- block:N -->` anchors.",
        "- N is the same id used by the rendered HTML (`id=\"reaper-block-N\"`).",
        "- When you answer, cite the section or block id you relied on.",
        "- If information is not in `paper.md`, the source files are available.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# markdown rendering
# --------------------------------------------------------------------------- #

def render_paper_md(blocks: list[Block], title: str = "",
                    macro_table: dict | None = None) -> str:
    """Deterministic Markdown output (same blocks → same bytes)."""
    out: list[str] = []
    if title:
        out += [f"# {title}", ""]
    out += ["<!-- generated by Reaper; anchors map to id=\"reaper-block-N\" -->", ""]
    for i, b in enumerate(blocks):
        text = _clean_text(restore_math(b.text, b.math_map, macro_table))
        if not text:
            continue
        if b.type in ("title", "section"):
            lv = min(b.level + 1, 6)
            if b.type == "title" and b.level == 0:
                continue
            out += [f"{'#' * lv} {text}", ""]
        elif b.type == "figcaption":
            out += [f"<!-- block:{i} -->", f"> **Caption.** {text}", ""]
        elif b.type == "note":
            out += [f"<!-- block:{i} -->", f"> **Footnote.** {text}", ""]
        else:
            out += [f"<!-- block:{i} -->", text, ""]
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def workspace_dir(arxiv_id: str) -> Path:
    return Path(config.chat_workspace_dir(arxiv_id))


def _load_source_html(arxiv_id: str) -> str | None:
    """Find cached HTML. New location first, then legacy paths."""
    src = Path(config.source_dir(arxiv_id))
    html = src / f"{arxiv_id}.html"
    if html.exists():
        return html.read_text(encoding="utf-8")
    # Legacy fallback (pre-reorg data/ar5iv/{id}/ etc.)
    for legacy in [
        Path(config.DATA_DIR) / "ar5iv" / arxiv_id / f"{arxiv_id}.html",
        Path(config.DATA_DIR) / "ar5ivist" / arxiv_id / f"{arxiv_id}.html",
    ]:
        if legacy.exists():
            return legacy.read_text(encoding="utf-8")
    return None


def prepare_paper_context(
    arxiv_id: str,
    *,
    source_html: str | None = None,
    tex_dir: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Build the agent workspace for ``arxiv_id``.

    When ``tex_dir`` is given and contains a ``.tex`` file, macros from its
    preamble are expanded in the math output. (Previously: download e-print.)
    """
    ws = workspace_dir(arxiv_id)
    meta_path = ws / "metadata.json"

    if not force and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("context_version") == CONTEXT_VERSION:
            return {"arxiv_id": arxiv_id, "workspace": str(ws),
                    "cached": True, "blocks": meta.get("blocks"),
                    "source_type": meta.get("source_type")}

    html = source_html or _load_source_html(arxiv_id)
    if not html:
        raise FileNotFoundError(
            f"No cached HTML for {arxiv_id}. Generate the bilingual HTML first."
        )

    marked_html, blocks = mark_and_extract(html)

    title = ""
    for b in blocks:
        if b.type == "title" and b.level == 0:
            title = _clean_text(restore_math(b.text, b.math_map))
            break
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
        if m:
            title = _clean_text(_html.unescape(m.group(1)))

    # Macro table — from the TeX source if available.
    macro_table = None
    if tex_dir:
        tex_dir = Path(tex_dir)
        for f in tex_dir.iterdir():
            if f.suffix == ".tex":
                try:
                    macro_table = build_macro_table(str(f))
                except Exception:
                    pass
                break

    src_type = _detect_source_type(html)
    ws.mkdir(parents=True, exist_ok=True)

    _write(ws / "paper.md",
           render_paper_md(blocks, title, macro_table))
    _write(ws / "OUTLINE.md",
           build_outline(blocks, macro_table))
    _write(ws / "blocks.json",
           json.dumps(build_block_index(blocks, macro_table),
                      ensure_ascii=False, indent=1))
    _write(ws / "metadata.json", json.dumps({
        "arxiv_id": arxiv_id,
        "title": title,
        "source_type": src_type,
        "context_version": CONTEXT_VERSION,
        "blocks": len(blocks),
        "macros": bool(macro_table),
    }, ensure_ascii=False, indent=2, sort_keys=True))

    return {"arxiv_id": arxiv_id, "workspace": str(ws), "cached": False,
            "blocks": len(blocks), "title": title, "source_type": src_type,
            "macros": bool(macro_table)}


def _detect_source_type(html: str) -> str:
    if "ltx_page_navbar" in html or "arxiv.org/html" in html[:5000]:
        return "arxiv_html"
    if "ltx_page_main" in html:
        return "ar5iv"
    return "unknown"


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")