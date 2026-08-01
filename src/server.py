"""Reaper Backend Server — injects UI into content HTML.

Usage:
    python3 server.py
    → http://localhost:{port}/papers/1907.11157

All generated files stored in data/. See config.json for settings.
"""

import os
import sys
import json
import http.server
import urllib.parse
from pathlib import Path
from datetime import datetime

# Allow imports from project root (src.ingestion, src.translation, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

ROOT = Path(__file__).parent.parent
PAPERS_DIR = Path(config.ZOTERO_DIR)
AR5IV_DIR = Path(config.AR5IV_DIR)
LOG_PATH = Path(config.LOG_DIR) / "server.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_log_file = open(str(LOG_PATH), "a", encoding="utf-8")
_original_print = print

def _log(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    _original_print(line, **kwargs)
    _log_file.write(line + "\n")
    _log_file.flush()

# Replace print globally
import builtins
builtins.print = lambda *a, **kw: _log(*a, **kw) if a and str(a[0]).strip() else _original_print(*a, **kw)

print(f"=== Reaper Server started ===")
print(f"Log: {LOG_PATH}")

from src.translation.dictionary import TermDictionary

_term_dict_instance = None

def get_term_dict():
    global _term_dict_instance
    if _term_dict_instance is None:
        _term_dict_instance = TermDictionary()
    return _term_dict_instance

def load_term_dict() -> dict:
    return get_term_dict().user

def save_term_dict(data: dict):
    td = get_term_dict()
    for en, zh in data.items():
        td.set_user(en, zh)


class ReaperHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # /papers/<paper_id>
        if parsed.path.startswith("/papers/"):
            paper_id = parsed.path.split("/papers/")[1].strip("/")
            # Find matching file
            matches = list(PAPERS_DIR.glob(f"{paper_id}*.html"))
            if matches:
                html = matches[0].read_text(encoding="utf-8")
                self._respond_html(html)
            else:
                self._respond_json({"error": "paper not found"}, 404)
            return

        # /api/terms
        if parsed.path == "/api/terms":
            terms = load_term_dict()
            self._respond_json(terms)
            return

        # / → list papers
        if parsed.path == "/" or parsed.path == "":
            papers = [p.name for p in PAPERS_DIR.glob("*.html")]
            html = "<h2>Reaper Papers</h2><ul>" + "".join(
                f'<li><a href="/papers/{p.replace(".html","")}">{p}</a></li>'
                for p in sorted(papers)
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
                config.AR5IV_DIR + "/" + arxiv_id,  # directory now
                config.CACHE_DIR + "/" + arxiv_id + ".json",
                _os.path.join(config.DATA_DIR, "tasks", arxiv_id + ".json"),
                config.ZOTERO_DIR + "/" + arxiv_id + ".html",
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

        # /api/generate?arxiv_id=XXXX&embed_images=0
        if parsed.path == "/api/generate":
            qs = urllib.parse.parse_qs(parsed.query)
            arxiv_id = qs.get("arxiv_id", [None])[0]
            embed = qs.get("embed_images", ["1"])[0] != "0"
            if not arxiv_id:
                self._respond_json({"error": "missing arxiv_id"}, 400)
                return

            # Generate complete HTML first, then send
            try:
                html = self._generate_paper(arxiv_id, embed_images=embed)
                # Save to papers/
                from src.rendering.renderer import save_html
                import os as _os
                out_path = _os.path.join(config.ZOTERO_DIR, f"{arxiv_id}.html")
                save_html(html, out_path)
                self._respond_html(html)
            except Exception as e:
                # Save error to task for diagnostics
                from src.task import Task
                from src import config as cfg
                try:
                    task = Task.load(arxiv_id, os.path.join(cfg.DATA_DIR, "tasks"))
                    if not task.is_done:
                        task.set_error(str(e))
                except Exception:
                    pass
                err = f"<html><body><h1>Error</h1><p>{e}</p></body></html>"
                self._respond_html(err)
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

        # /api/terms
        if parsed.path == "/api/terms":
            save_term_dict(data.get("terms", {}))
            self._respond_json({"ok": True})
            return

        self._respond_json({"error": "not found"}, 404)

    def _generate_paper(self, arxiv_id: str, embed_images: bool = True) -> str:
        """Run the full pipeline with state tracking."""
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.translation.translator import translate_blocks
        from src.translation.dictionary import TermDictionary
        from src.translation.cache import TranslationCache
        from src.rendering.renderer import render_bilingual_html
        from src.task import Task
        from src import config
        import hashlib

        tag = f"[{arxiv_id}]"
        tasks_dir = os.path.join(config.DATA_DIR, "tasks")
        task = Task.load(arxiv_id, tasks_dir)
        _active_tasks[arxiv_id] = task

        if task.is_done:
            print(f"  {tag} Task already done — using cached data", flush=True)

        # Step 1: Fetch (cached to data/ar5iv/ for instant re-runs)
        print(f"  {tag} [1/4] Fetching ar5iv HTML ...", flush=True)
        task.set_fetching()
        arxiv_id, src_type, raw_html = fetch_html(arxiv_id, cache_dir=str(config.AR5IV_DIR))
        print(f"  {tag}        {len(raw_html):,} bytes", flush=True)

        # Step 2: Parse
        print(f"  {tag} [2/4] Parsing blocks ...", flush=True)
        task.set_parsing()
        marked_html, blocks = mark_and_extract(raw_html)
        print(f"  {tag}        {len(blocks)} blocks extracted", flush=True)

        # Compute hashes and init task blocks
        hashes = [hashlib.sha256(b.text.encode()).hexdigest()[:16] for b in blocks]
        if not task.blocks:
            task.set_blocks(hashes)

        # Step 3: Translate
        print(f"  {tag} [3/4] Translating ...", flush=True)
        task.set_translating()
        term_dict = TermDictionary()

        # Use in-memory translation cache
        zh_cache = TranslationCache(arxiv_id)
        _active_caches[arxiv_id] = zh_cache
        print(f"  {tag}        {len(zh_cache)} cached translations loaded", flush=True)

        translated = translate_blocks(
            blocks, term_dict=term_dict, paper_id=arxiv_id,
            api_key=config.LLM_API_KEY,
            model=config.LLM_MODEL,
            base_url=config.LLM_BASE_URL,
            executor=get_translation_pool(),
        )

        # Update task progress from results
        _active_caches.pop(arxiv_id, None)  # clean registry (already saved per-paragraph)
        for i, t in enumerate(translated):
            t["math_map"] = blocks[i].math_map if i < len(blocks) else {}
            if t.get("zh") and t["zh"] != t.get("en", ""):
                if i < len(task.blocks) and not task.blocks[i]["done"]:
                    task.mark_done(i)

        cnt = sum(1 for t in translated if t.get("zh") and t["zh"] != t.get("en", ""))
        print(f"  {tag}        {cnt} blocks translated (task: {task.progress})", flush=True)

        # Step 4: Render
        print(f"  {tag} [4/4] Rendering HTML ...", flush=True)
        task.set_rendering()
        result = render_bilingual_html(
            marked_html=marked_html,
            blocks_with_zh=translated,
            term_dict=term_dict.all_terms,
            arxiv_id=arxiv_id,
            embed_images=embed_images,
            source_type=src_type,
        )
        print(f"  {tag}        {len(result):,} bytes", flush=True)

        task.set_done()
        _active_tasks.pop(arxiv_id, None)
        print(f"  {tag} ✅ Done", flush=True)
        return result

    def _respond_html(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        # Write in chunks with flush
        chunk = 65536
        for i in range(0, len(data), chunk):
            self.wfile.write(data[i:i+chunk])
            self.wfile.flush()

    def _respond_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        print(f"  {' '.join(args)}")

# ── Shared translation pool (one per server process) ──
_translation_pool = None
_active_caches: dict[str, "TranslationCache"] = {}  # paper_id → cache
_active_tasks: dict[str, "Task"] = {}  # paper_id → task

def get_translation_pool():
    from concurrent.futures import ThreadPoolExecutor
    global _translation_pool
    if _translation_pool is None:
        _translation_pool = ThreadPoolExecutor(max_workers=config.TRANSLATION_CONCURRENCY)
        print(f"  Translation pool: {config.TRANSLATION_CONCURRENCY} workers", flush=True)
    return _translation_pool

UI_DIR = ROOT / "src" / "rendering" / "ui"
_UI_CSS = ""
_UI_JS = ""


def load_ui():
    global _UI_CSS, _UI_JS
    _UI_CSS = (UI_DIR / "toc-sidebar.css").read_text(encoding="utf-8")
    _UI_JS = (UI_DIR / "toc-toggle.js").read_text(encoding="utf-8")


def main():
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    AR5IV_DIR.mkdir(parents=True, exist_ok=True)
    load_ui()
    print(f"Reaper Backend")
    print(f"  ar5iv cache: {AR5IV_DIR}")
    print(f"  Zotero output: {PAPERS_DIR}")
    print(f"  UI CSS: {len(_UI_CSS)} bytes")
    print(f"  UI JS:  {len(_UI_JS)} bytes")
    print(f"\n  → http://localhost:{config.SERVER_PORT}")
    print(f"  ar5iv dir: {AR5IV_DIR}")
    print(f"  zotero dir: {PAPERS_DIR}\n")

    server = http.server.ThreadingHTTPServer((config.SERVER_HOST, config.SERVER_PORT), ReaperHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()

if __name__ == "__main__":
    main()
