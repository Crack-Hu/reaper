#!/usr/bin/env python3
"""Generate test HTMLs from all 3 sources for visual comparison.

Usage: python3 tests/gen_3sources.py <arxiv_id>
Example: python3 tests/gen_3sources.py 2406.04124
"""

import sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.ingestion.fetcher import _try_arxiv_html, _try_ar5iv, SourceError, fetch_html
from src.ingestion.parser import mark_and_extract
from src.rendering.renderer import render_bilingual_html

AID = sys.argv[1] if len(sys.argv) > 1 else "2406.04124"
from src import config
ZOTERO = config.reaper_html_dir(AID)
os.makedirs(ZOTERO, exist_ok=True)

def fake_blocks(blocks):
    return [{"zh": "", "en": b.text, "type": b.type, "level": b.level, "math_map": b.math_map} for b in blocks]

results = {}

# ── Source 1: ar5iv ──
print("\n=== Source 1: ar5iv ===")
try:
    aid, src, raw = fetch_html(AID)
    m, b = mark_and_extract(raw)
    h = render_bilingual_html(m, fake_blocks(b), arxiv_id=aid, embed_images=False, source_type=src)
    path = f"{ZOTERO}/{aid}_ar5iv.html"
    open(path, "w").write(h)
    print(f"  OK -> {path} ({len(h):,}B)")
    results["ar5iv"] = path
except Exception as e:
    print(f"  FAIL: {e}")

# ── Source 2: arxiv_html ──
print("\n=== Source 2: arxiv_html ===")
try:
    raw = _try_arxiv_html(AID)
    m, b = mark_and_extract(raw)
    h = render_bilingual_html(m, fake_blocks(b), arxiv_id=AID, embed_images=False, source_type="arxiv_html")
    path = f"{ZOTERO}/{AID}_arxiv.html"
    open(path, "w").write(h)
    print(f"  OK -> {path} ({len(h):,}B)")
    results["arxiv_html"] = path
except Exception as e:
    print(f"  FAIL: {e}")
    for v in ["v1", "v2", "v3"]:
        try:
            raw = _try_arxiv_html(f"{AID}{v}")
            m, b = mark_and_extract(raw)
            h = render_bilingual_html(m, fake_blocks(b), arxiv_id=f"{AID}{v}", embed_images=False, source_type="arxiv_html")
            path = f"{ZOTERO}/{AID}{v}_arxiv.html"
            open(path, "w").write(h)
            print(f"  OK (with {v}) -> {path} ({len(h):,}B)")
            results["arxiv_html"] = path
            break
        except Exception:
            pass

# ── Source 3: ar5ivist_docker ──
print("\n=== Source 3: ar5ivist_docker ===")
try:
    from src.ingestion.fetcher import _try_ar5ivist_docker
    raw = _try_ar5ivist_docker(AID)
    m, b = mark_and_extract(raw)
    h = render_bilingual_html(m, fake_blocks(b), arxiv_id=AID, embed_images=False, source_type="ar5ivist_docker")
    path = f"{ZOTERO}/{AID}_ar5ivist.html"
    open(path, "w").write(h)
    print(f"  OK -> {path} ({len(h):,}B)")
    results["ar5ivist_docker"] = path
except Exception as e:
    print(f"  SKIP (Docker may not be running): {e}")

# ── Summary ──
print(f"\n=== Generated {len(results)}/3 sources ===")
for src, path in results.items():
    size = os.path.getsize(path)
    print(f"  {src}: {path} ({size:,}B)")

if results:
    import subprocess
    for path in results.values():
        subprocess.run(["open", path])
