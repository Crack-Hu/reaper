#!/usr/bin/env python3
"""Migrate old flat data/ layout to the new hierarchical data/papers/ layout.

Old → new mapping:
  data/ar5iv/{id}/{id}.html + images           → data/papers/{id}/source/
  data/arxiv_source/{id}/*                      → data/papers/{id}/source/
  data/translation_cache/{id}.json              → data/papers/{id}/process/translation_cache/cache.json
  data/tasks/{id}.json                          → data/papers/{id}/process/state.json
  data/zotero/{id}/index.html + assets/         → data/papers/{id}/process/reaper_html/
  data/chat/{id}/workspace/                     → data/papers/{id}/chat/workspace/
  data/chat/{id}/sessions/                      → data/papers/{id}/chat/sessions/

Strategy: copy, never move. Old directories are left intact.
"""

import hashlib
import os
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # project root (/Users/crack/Crack/pi-extension/reaper)
DATA = HERE / "data"
PAPERS = DATA / "papers"


# ---- helpers -----------------------------------------------------------

def paper_ids(*data_dirs: str) -> set[str]:
    """Collect all arxiv IDs that appear in ANY of the listed data/ dirs."""
    ids: set[str] = set()
    for dir_name in data_dirs:
        d = DATA / dir_name
        if not d.exists():
            continue
        for entry in d.iterdir():
            if entry.is_dir() or entry.suffix == ".json":
                stem = entry.stem if entry.is_dir() else entry.name.replace(".json", "")
                # arXiv IDs look like YYYY.NNNNN or YYYY.NNNNNvN
                if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", stem):
                    ids.add(stem)
                # Also handle "test-" prefixed test IDs
                if re.match(r"^test-\d{4}\.\d{4,5}", stem):
                    ids.add(stem)
    return sorted(ids)


def copy_file(src: Path, dst: Path, *, skip_if_exists: bool = True) -> str:
    """Copy a file, creating parent dirs. Returns status string."""
    if not src.exists():
        return "      (source missing)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and skip_if_exists:
        s_src = hashlib.sha256(src.read_bytes()).digest()
        s_dst = hashlib.sha256(dst.read_bytes()).digest()
        if s_src == s_dst:
            return "      (identical, skipped)"
        return f"      (exists, size differs — keeping both; see {dst}.old)"
    try:
        shutil.copy2(src, dst)
        return f"  ✅ {src.name} → {dst.relative_to(HERE)}"
    except Exception as e:
        return f"  ❌ {src.name}: {e}"


def copy_dir(src: Path, dst: Path, *, skip_if_exists: bool = True) -> list[str]:
    """Recursively copy a directory. Returns status lines."""
    lines: list[str] = []
    if not src.exists():
        lines.append("      (source dir missing)")
        return lines
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file():
            rel = item.relative_to(src)
            lines.append(copy_file(item, dst / rel, skip_if_exists=skip_if_exists))
        elif item.is_dir() and item.name not in (".DS_Store", "__pycache__"):
            lines.extend(copy_dir(item, dst / item.name, skip_if_exists=skip_if_exists))
    return lines


# ---- per-paper migrators -----------------------------------------------

def migrate_ar5iv(arxiv_id: str) -> list[str]:
    """Cached ar5iv HTML + images → papers/{id}/source/"""
    src = DATA / "ar5iv" / arxiv_id
    dst = PAPERS / arxiv_id / "source"
    if not src.exists():
        return []
    lines = [f"\n  ar5iv/{arxiv_id}/ → source/"]
    for item in sorted(src.iterdir()):
        if item.is_file():
            lines.append(copy_file(item, dst / item.name))
        elif item.is_dir() and item.name != ".DS_Store":
            sub = copy_dir(item, dst / item.name)
            if sub:
                lines.extend(sub)
    return lines


def migrate_arxiv_source(arxiv_id: str) -> list[str]:
    """LaTeX source tarball → papers/{id}/source/"""
    src = DATA / "arxiv_source" / arxiv_id
    dst = PAPERS / arxiv_id / "source"
    if not src.exists():
        return []
    lines = [f"\n  arxiv_source/{arxiv_id}/ → source/"]
    lines.extend(copy_dir(src, dst))
    return lines


def migrate_translation_cache(arxiv_id: str) -> list[str]:
    """translation_cache/{id}.json → process/translation_cache/cache.json"""
    src = DATA / "translation_cache" / f"{arxiv_id}.json"
    dst = PAPERS / arxiv_id / "process" / "translation_cache" / "cache.json"
    if not src.exists():
        return []
    return [f"\n  translation_cache/{arxiv_id}.json → process/translation_cache/cache.json",
            copy_file(src, dst)]


def migrate_task(arxiv_id: str) -> list[str]:
    """tasks/{id}.json → process/state.json"""
    src = DATA / "tasks" / f"{arxiv_id}.json"
    dst = PAPERS / arxiv_id / "process" / "state.json"
    if not src.exists():
        return []
    return [f"\n  tasks/{arxiv_id}.json → process/state.json",
            copy_file(src, dst)]


def migrate_reaper_html(arxiv_id: str) -> list[str]:
    """zotero/{id}/ → process/reaper_html/"""
    src = DATA / "zotero" / arxiv_id
    dst = PAPERS / arxiv_id / "process" / "reaper_html"
    lines = []
    if src.is_dir():
        lines.append(f"\n  zotero/{arxiv_id}/ → process/reaper_html/")
        lines.extend(copy_dir(src, dst))
    # Also handle legacy single-file format: data/zotero/{id}.html
    single = DATA / "zotero" / f"{arxiv_id}.html"
    if single.exists():
        lines.append(f"\n  zotero/{arxiv_id}.html → process/reaper_html/")
        lines.append(copy_file(single, dst / f"{arxiv_id}.html"))
    return lines


def migrate_chat_workspace(arxiv_id: str) -> list[str]:
    """chat/{id}/workspace/ → papers/{id}/chat/workspace/"""
    src = DATA / "chat" / arxiv_id / "workspace"
    dst = PAPERS / arxiv_id / "chat" / "workspace"
    if not src.exists():
        return []
    lines = [f"\n  chat/{arxiv_id}/workspace/ → chat/workspace/"]
    lines.extend(copy_dir(src, dst))
    return lines


def migrate_chat_sessions(arxiv_id: str) -> list[str]:
    """chat/{id}/sessions/ → papers/{id}/chat/sessions/"""
    src = DATA / "chat" / arxiv_id / "sessions"
    dst = PAPERS / arxiv_id / "chat" / "sessions"
    if not src.exists():
        return []
    lines = [f"\n  chat/{arxiv_id}/sessions/ → chat/sessions/"]
    lines.extend(copy_dir(src, dst))
    return lines


# ---- main --------------------------------------------------------------

def main():
    ids = paper_ids("ar5iv", "arxiv_source", "translation_cache", "tasks", "zotero", "chat")
    print(f"Found {len(ids)} papers in old data directories:\n  {', '.join(ids)}\n")

    total_ok = 0
    total_err = 0

    for arxiv_id in ids:
        lines: list[str] = []
        lines.extend(migrate_ar5iv(arxiv_id))
        lines.extend(migrate_arxiv_source(arxiv_id))
        lines.extend(migrate_translation_cache(arxiv_id))
        lines.extend(migrate_task(arxiv_id))
        lines.extend(migrate_reaper_html(arxiv_id))
        lines.extend(migrate_chat_workspace(arxiv_id))
        lines.extend(migrate_chat_sessions(arxiv_id))

        if not lines:
            continue

        print(f"═══ {arxiv_id} ═══")
        for l in lines:
            print(l)
            if "✅" in l:
                total_ok += 1
            elif "❌" in l:
                total_err += 1
        print()

    print(f"═══ 迁移完成 ═══")
    print(f"  成功: {total_ok}  失败: {total_err}")
    if total_err:
        print("  ⚠️  检查上面的 ❌ 行，可能需要手动处理")
    print(f"\n旧数据未删除。确认新结构正常工作后，可以清理：")
    print(f"  rm -rf data/ar5iv  data/arxiv_source  data/translation_cache")
    print(f"  rm -rf data/tasks  data/zotero  data/chat  data/ar5ivist")
    print(f"  rmdir data/sources 2>/dev/null; true")


if __name__ == "__main__":
    main()