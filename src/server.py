"""Reaper Backend Server — injects UI into content HTML.

Usage:
    python3 server.py
    → http://localhost:{port}/papers/1907.11157

All generated files stored in data/. See config.json for settings.
"""

import os
import sys
import json
import threading
import http.server
import urllib.parse
from pathlib import Path

# Allow imports from project root (src.ingestion, src.translation, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

PAPERS_DIR = Path(config.PAPERS_DIR)  # all papers live under data/papers/

# 日志：每个任务一份独立文件 + 紧凑行格式（见 src/logbook.py）
from src import logbook
logbook.configure(config.LOG_DIR)

print(f"=== Reaper Server started ===")
print(f"Log: {logbook.merged_log_path()}")
print(f"Per-paper logs: {config.LOG_DIR}/papers/")

def paper_html_path(paper_id: str) -> Path | None:
    """Newest generated bilingual HTML for a paper, or None.

    A normal run writes `process/reaper_html/index.html`; forcing a source adds a
    suffix (`process/reaper_html_<source>/index.html`), and light mode writes a
    single `process/reaper_html*.html`. Serve whichever was written last.
    """
    if not paper_id or "/" in paper_id or "\\" in paper_id or paper_id.startswith("."):
        return None                       # keep the endpoint inside data/papers/
    process = PAPERS_DIR / paper_id / "process"
    candidates = [f for f in process.glob("reaper_html*/index.html") if f.is_file()]
    candidates += [f for f in process.glob("reaper_html*.html") if f.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.stat().st_mtime)


from src.translation.dictionary import TermDictionary

_term_dict_instance = None
_term_dict_lock = threading.Lock()

def get_term_dict():
    global _term_dict_instance
    with _term_dict_lock:
        if _term_dict_instance is None:
            _term_dict_instance = TermDictionary()
        return _term_dict_instance

def load_term_dict() -> dict:
    return get_term_dict().user

def save_term_dict(data: dict):
    td = get_term_dict()
    for en, zh in data.items():
        td.set_user(en, zh)


# 客户端在响应写完前离开（长任务里很常见：标签页关闭、Zotero 重载、请求超时）。
# 这类 socket 错误和论文处理无关，绝不能当成流水线失败，也不该打 traceback。
_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class ReaperHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # /api/chat/* (implemented in src/chat/api.py)
        if parsed.path.startswith("/api/chat"):
            from src.chat import api as chat_api
            if chat_api.handle_get(self, parsed, urllib.parse.parse_qs(parsed.query)):
                return

        # /api/zotero_html/<paper_id> — serve the newest generated bilingual HTML
        if parsed.path.startswith("/api/zotero_html/"):
            paper_id = parsed.path.split("/api/zotero_html/")[1].strip("/")
            path = paper_html_path(paper_id)
            if path is None:
                self._respond_json({"error": f"no generated HTML for {paper_id}"}, 404)
            else:
                self._respond_html(path.read_text(encoding="utf-8"))
            return

        # /api/terms
        if parsed.path == "/api/terms":
            terms = load_term_dict()
            self._respond_json(terms)
            return

        # / → list papers that have generated HTML
        if parsed.path == "/" or parsed.path == "":
            names = sorted(d.name for d in PAPERS_DIR.iterdir()
                           if d.is_dir() and paper_html_path(d.name) is not None)
            html = "<h2>Reaper Papers</h2><ul>" + "".join(
                f'<li><a href="/api/zotero_html/{n}">{n}</a></li>' for n in names
            ) + "</ul>"
            self._respond_html(html)
            return

        # /api/clear?arxiv_id=XXXX
        if parsed.path == "/api/clear":
            qs = urllib.parse.parse_qs(parsed.query)
            arxiv_id = qs.get("arxiv_id", [None])[0]
            if not arxiv_id:
                self._respond_json({"error": "missing arxiv_id"}, 400)
                return
            # Clear caches (excluding dictionary)
            import os as _os, glob as _glob, shutil as _shutil
            paths = [
                config.source_dir(arxiv_id),  # source material
                config.translation_cache_dir(arxiv_id) + "/cache.json",  # translation cache
                config.task_state_path(arxiv_id),  # task state
                config.reaper_html_dir(arxiv_id) + "/index.html",  # reaper HTML
                config.reaper_html_dir(arxiv_id),  # directory format
                config.reaper_html_dir(arxiv_id) + "_files",  # legacy _files dir (keep for migration)
            ]
            cleared = []
            for p in paths:
                if _os.path.exists(p):
                    if _os.path.isdir(p):
                        _shutil.rmtree(p)
                    else:
                        _os.remove(p)
                    cleared.append(_os.path.basename(p))
            print(f"  [{arxiv_id}] Cleared: {', '.join(cleared) if cleared else 'nothing to clear'}", flush=True)
            self._respond_json({"ok": True, "cleared": cleared})
            return

        # /api/generate?arxiv_id=XXXX&embed_images=0&source=ar5iv
        if parsed.path == "/api/generate":
            qs = urllib.parse.parse_qs(parsed.query)
            arxiv_id = qs.get("arxiv_id", [None])[0]
            embed = qs.get("embed_images", ["1"])[0] != "0"
            source = qs.get("source", [None])[0]  # None = use default order
            if not arxiv_id:
                self._respond_json({"error": "missing arxiv_id"}, 400)
                return

            # 并发生成守卫：第二个请求直接被告知「正在处理中」，不重复跑流水线
            if not try_begin_generation(arxiv_id):
                self._respond_json({
                    "ok": False,
                    "status": "processing",
                    "arxiv_id": arxiv_id,
                    "message": f"{arxiv_id} 正在处理中，请等待完成",
                }, status=202, headers={"X-Reaper-Status": "processing"})
                return

            # Generate complete HTML, save to directory, return path
            try:
                from src.rendering.renderer import save_html, zotero_compatible_html
                import os as _os, shutil as _shutil
                # Output directory: config.reaper_html_dir(arxiv_id)[_{source}]/
                out_dir = config.reaper_html_dir(arxiv_id)
                if source:
                    out_dir += f"_{source}"
                
                # Use out_dir as resource_dir directly — saves assets to out_dir/assets/
                resource_dir = out_dir if embed else None
                html = self._generate_paper(arxiv_id, embed_images=embed, force_source=source,
                                            resource_dir=resource_dir)
                html = zotero_compatible_html(html)
                
                if embed and resource_dir:
                    # Save HTML alongside assets: out_dir/index.html + out_dir/assets/
                    _os.makedirs(out_dir, exist_ok=True)
                    save_html(html, _os.path.join(out_dir, "index.html"))
                else:
                    # Light mode: single file
                    _os.makedirs(_os.path.dirname(out_dir + ".html"), exist_ok=True)
                    save_html(html, out_dir + ".html")
                
                # Respond with JSON + output path header (no giant HTML body)
                headers = ({"X-Output-Dir": _os.path.abspath(out_dir)}
                           if embed and resource_dir else {})
                self._respond_json({"ok": True, "arxiv_id": arxiv_id}, headers=headers)
            except _CLIENT_GONE:
                # 客户端先走了：论文已经生成并落盘，这不是处理失败
                print(f"  [{arxiv_id}] client disconnected before the response was sent",
                      flush=True)
            except Exception as e:
                # Save error to task for diagnostics
                from src.task import Task
                from src import config as cfg
                try:
                    task = Task.load(arxiv_id)
                    if not task.is_done:
                        task.set_error(str(e))
                except Exception:
                    pass
                err = f"<html><body><h1>Error</h1><p>{e}</p></body></html>"
                self._respond_html(err)
            finally:
                end_generation(arxiv_id)
            return

        # /api/stop
        if parsed.path == "/api/stop":
            self._respond_json({"ok": True, "msg": "server stopping"})
            print("\n[server] Stop requested, saving state...", flush=True)
            # Save all active caches and tasks
            for pid, cache in list(_active_caches.items()):
                try:
                    cache.save()
                    print(f"  saved cache: {pid}", flush=True)
                except Exception as exc:
                    print(f"  cache save err {pid}: {exc}", flush=True)
            for pid, task in list(_active_tasks.items()):
                try:
                    task.save()
                    print(f"  saved task: {pid}", flush=True)
                except Exception as exc:
                    print(f"  task save err {pid}: {exc}", flush=True)
            print("[server] Done. Exiting.", flush=True)
            import os as _os
            _os._exit(0)

        # 404
        self._respond_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/stop":
            self._respond_json({"ok": True, "msg": "server stopping"})
            print("\n[server] Stop requested, saving state...", flush=True)
            for pid, cache in list(_active_caches.items()):
                try:
                    cache.save()
                    print(f"  saved cache: {pid}", flush=True)
                except Exception as exc:
                    print(f"  cache save err {pid}: {exc}", flush=True)
            for pid, task in list(_active_tasks.items()):
                try:
                    task.save()
                    print(f"  saved task: {pid}", flush=True)
                except Exception as exc:
                    print(f"  task save err {pid}: {exc}", flush=True)
            print("[server] Done. Exiting.", flush=True)
            import os as _os
            _os._exit(0)

        self._respond_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        data = json.loads(body)

        # /api/chat/* (implemented in src/chat/api.py)
        if parsed.path.startswith("/api/chat"):
            from src.chat import api as chat_api
            if chat_api.handle_post(self, parsed, data):
                return

        # /api/terms
        if parsed.path == "/api/terms":
            save_term_dict(data.get("terms", {}))
            self._respond_json({"ok": True})
            return

        self._respond_json({"error": "not found"}, 404)

    def _generate_paper(self, arxiv_id: str, embed_images: bool = True,
                       force_source: str | None = None,
                       resource_dir: str | None = None) -> str:
        """Run the pipeline with per-task logging context.

        All output produced while this runs is tagged with `arxiv_id` and
        mirrored into `logs/papers/{arxiv_id}.log`, so concurrent tasks stay
        readable even though they interleave on stdout.
        """
        with logbook.task(arxiv_id):
            return self._generate_paper_impl(
                arxiv_id, embed_images=embed_images,
                force_source=force_source, resource_dir=resource_dir)

    def _generate_paper_impl(self, arxiv_id: str, embed_images: bool = True,
                             force_source: str | None = None,
                             resource_dir: str | None = None) -> str:
        """The actual pipeline. Callers go through `_generate_paper`."""
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.translation.translator import translate_blocks
        from src.translation.dictionary import TermDictionary
        from src.translation.cache import PaperCache, html_hash
        from src.rendering.renderer import render_bilingual_html
        from src.task import Task
        from src import config

        task = Task.load(arxiv_id)
        _active_tasks[arxiv_id] = task

        # Step 1: Fetch
        logbook.set_progress(phase="[1/4] 获取 HTML")
        print(f"  [1/4] Fetching HTML ...", flush=True)
        task.set_fetching()
        fp = fetch_html(arxiv_id, force_source=force_source)   # caches under source_dir(arxiv_id)
        raw_html = fp.html
        print(f"         {len(raw_html):,} bytes", flush=True)

        # Load unified paper cache
        paper_cache = PaperCache.load(arxiv_id)
        term_dict = TermDictionary()

        # Check if HTML hash matches and ALL blocks are translated → skip parse + translate
        all_done = paper_cache.match(raw_html) and paper_cache.translated_count == len(paper_cache)
        if all_done:
            logbook.set_progress(phase="[2+3/4] 缓存命中")
            print(f"  [2+3/4] HTML unchanged — restoring {len(paper_cache)} blocks from cache ({paper_cache.translated_count} translated)", flush=True)
            task.set_parsing()
            task.set_translating()
            marked_html, _ = mark_and_extract(raw_html)  # re-parse for markers only
            cached_blocks = paper_cache.restore()
            translated = [{"en": b["en"], "zh": b["zh"], "type": b["type"],
                           "level": b["level"], "label": b["label"],
                           "math_map": b.get("math_map", {})}
                          for b in cached_blocks]
            # Update task for UI progress
            hashes = [b["hash"] for b in cached_blocks]
            if not task.blocks or len(task.blocks) != len(hashes):
                task.set_blocks(hashes)
                done_indices = [i for i, b in enumerate(cached_blocks) if b.get("zh")]
                for i in done_indices:
                    task.mark_done(i)
        else:
            # Step 2: Parse
            logbook.set_progress(phase="[2/4] 解析段落")
            print(f"  [2/4] Parsing blocks ...", flush=True)
            task.set_parsing()
            marked_html, blocks = mark_and_extract(raw_html)
            print(f"         {len(blocks)} blocks extracted", flush=True)

            # Update cache with new HTML hash + blocks (merges old translations by hash)
            # NOTE: Do NOT save() here — only save after merge_translations() so that
            # a crash during translation does not persist a cache with 0 translations.
            paper_cache.update(raw_html, fp.source_type, blocks)
            matched = sum(1 for b in paper_cache.blocks if b.get("zh"))
            if matched:
                print(f"         {matched}/{len(blocks)} blocks matched from previous cache", flush=True)

            # Compute hashes and init task blocks
            hashes = [b["hash"] for b in paper_cache.blocks]
            if not task.blocks or len(task.blocks) != len(hashes):
                # Block structure changed (e.g. new note blocks) → rebuild,
                # preserving done status by block hash.
                old_done = {b["hash"] for b in task.blocks if b.get("done")}
                task.set_blocks(hashes)
                for i, h in enumerate(hashes):
                    if h in old_done:
                        task.blocks[i]["done"] = True
                        task.translated += 1
                task._touch()
                task._save()

            # Step 3: Translate
            # 起始百分比 = 缓存命中比例；翻译过程中由 on_progress 实时更新
            _pre_total = len(paper_cache) or 1
            _pre_done = getattr(paper_cache, "translated_count", 0)
            logbook.set_progress(phase="[3/4] 翻译中",
                                 pct=_pre_done / _pre_total * 100,
                                 note=f"{_pre_done}/{_pre_total}")
            print(f"  [3/4] Translating ...", flush=True)
            task.set_translating()

            _active_caches[arxiv_id] = paper_cache
            print(f"         {paper_cache.translated_count} cached translations loaded", flush=True)

            translated = translate_blocks(
                blocks, term_dict=term_dict, paper_id=arxiv_id,
                api_key=config.LLM_API_KEY,
                model=config.LLM_MODEL,
                base_url=config.LLM_BASE_URL,
                executor=get_translation_pool(),
                cache=paper_cache,
                # 实时进度：已翻段落 / 可翻译段落数（不含标题，所以分母
                # 会比 task.progress 的「全部块」略小，标签里说清楚）
                on_progress=lambda d, t: logbook.set_progress(
                    pct=d / t * 100, note=f"段落 {d}/{t}"),
            )

            # Update task progress from results
            _active_caches.pop(arxiv_id, None)
            for i, t in enumerate(translated):
                t["math_map"] = blocks[i].math_map if i < len(blocks) else {}
                if t.get("zh") and t["zh"] != t.get("en", ""):
                    if i < len(task.blocks) and not task.blocks[i]["done"]:
                        task.mark_done(i)

            # Merge translations back into cache and save to disk
            paper_cache.merge_translations(translated)
            paper_cache.save()

            cnt = sum(1 for t in translated if t.get("zh") and t["zh"] != t.get("en", ""))
            if task.total:
                logbook.set_progress(pct=task.translated / task.total * 100)
            print(f"         {cnt} blocks translated (task: {task.progress})", flush=True)

        # Step 4: Render
        logbook.set_progress(phase="[4/4] 渲染 HTML")
        print(f"  [4/4] Rendering HTML ...", flush=True)
        task.set_rendering()
        result = render_bilingual_html(
            marked_html=marked_html,
            blocks_with_zh=translated,
            fp=fp,
            term_dict=term_dict.all_terms,
            embed_images=embed_images,
            resource_dir=resource_dir,
        )
        print(f"         {len(result):,} bytes", flush=True)

        # Clear interrupted flag (we successfully completed this run)
        task.interrupted = False
        task.set_done()
        _active_tasks.pop(arxiv_id, None)
        print(f"  ✅ Done", flush=True)
        return result

    def _respond_html(self, html: str):
        data = html.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            # Write in chunks with flush
            chunk = 65536
            for i in range(0, len(data), chunk):
                self.wfile.write(data[i:i+chunk])
                self.wfile.flush()
        except _CLIENT_GONE:
            pass          # 客户端已经不在，没有对象可回

    def _respond_json(self, data: dict, status: int = 200,
                      headers: dict | None = None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except _CLIENT_GONE:
            pass

    def log_message(self, format, *args):
        print(f"  {' '.join(args)}")

# ── Shared translation pool (one per server process) ──
_translation_pool = None
_pool_lock = threading.Lock()
_active_caches: dict[str, "PaperCache"] = {}  # paper_id → cache
_active_tasks: dict[str, "Task"] = {}  # paper_id → task

# ── 并发生成守卫 ──
# /api/generate 很贵（下载 + 解析 + LLM 翻译）。同一篇论文的两个并发请求会
# 重复每个阶段并把 API 花费翻倍，所以后到的调用者被告知「正在处理中」。
_inflight_lock = threading.Lock()
_inflight: set[str] = set()


def try_begin_generation(arxiv_id: str) -> bool:
    """预约一篇论文的生成。已在处理中则返回 False。"""
    with _inflight_lock:
        if arxiv_id in _inflight:
            return False
        _inflight.add(arxiv_id)
        return True


def end_generation(arxiv_id: str) -> None:
    with _inflight_lock:
        _inflight.discard(arxiv_id)


def inflight_papers() -> list[str]:
    with _inflight_lock:
        return sorted(_inflight)


def get_translation_pool():
    from concurrent.futures import ThreadPoolExecutor
    global _translation_pool
    with _pool_lock:
        if _translation_pool is None:
            _translation_pool = ThreadPoolExecutor(max_workers=config.TRANSLATION_CONCURRENCY)
            print(f"  Translation pool: {config.TRANSLATION_CONCURRENCY} workers", flush=True)
        return _translation_pool

def main():
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)

    # Background reaper: stops idle pi processes so they don't accumulate.
    from src.chat.session import registry as _chat_registry
    _chat_registry.start_reaper()
    print(f"Reaper Backend")
    print(f"  Zotero output: {PAPERS_DIR}")
    print(f"\n  → http://localhost:{config.SERVER_PORT}")
    print(f"  paper data root: {config.PAPERS_DIR}\n")

    server = http.server.ThreadingHTTPServer((config.SERVER_HOST, config.SERVER_PORT), ReaperHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()

if __name__ == "__main__":
    main()
