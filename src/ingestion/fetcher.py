"""HTML 获取模块 — 多来源管道"""

import httpx
import re
import subprocess
import tarfile
import os
import time as _time
import threading
from pathlib import Path
from .. import config


class SourceError(Exception):
    """HTML 来源不可用（单个来源失败，继续尝试下一个）。"""
    pass


# ── arxiv ID 工具 ──────────────────────────────────────────────

def arxiv_id_from_url(url: str) -> str:
    """Extract arxiv ID from various input formats. Preserves version suffix (v2, v3).

    Supported:
        2401.04268, 2401.04268v2
        arxiv:2401.04268v2
        https://arxiv.org/abs/2401.04268v2
        https://arxiv.org/pdf/2401.04268v2(.pdf)
        https://ar5iv.labs.arxiv.org/html/2401.04268v2
    """
    url = url.strip()
    # ar5iv URL
    m = re.search(r'ar5iv\..+?/html/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
    if m:
        return m.group(1)
    # arxiv /abs/ or /pdf/ URL
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
    if m:
        return m.group(1)
    # arxiv: prefix
    if url.startswith('arxiv:'):
        return url[6:].strip()
    # Pure ID (with optional version)
    if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', url):
        return url
    raise ValueError(f"Cannot extract arxiv ID from: {url}")


# ── Source: ar5iv 在线 ─────────────────────────────────────────

def _try_ar5iv(arxiv_id: str) -> str:
    """从 ar5iv.labs.arxiv.org 获取 HTML 并缓存图片。"""
    url = f"{config.AR5IV_BASE}/{arxiv_id}"
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # Redirected to arXiv → paper not on ar5iv
    if 'arxiv.org' in str(resp.url) and 'ar5iv' not in str(resp.url):
        raise SourceError(f"ar5iv does not have {arxiv_id}")

    # Conversion failure
    if 'ltx_ERROR' in html and 'Fatal error' in html:
        raise SourceError(f"ar5iv conversion failed for {arxiv_id}")

    # Not actual ar5iv content
    if '<body' in html and 'ltx_page_main' not in html and 'ltx_ERROR' not in html:
        if 'arxiv.org/abs/' in html[:2000]:
            raise SourceError(f"ar5iv returned arXiv abstract page for {arxiv_id}")

    # Download referenced images to local cache (ar5iv CDN may not persist them)
    _cache_ar5iv_images(html, arxiv_id)

    return html


def _cache_ar5iv_images(html: str, arxiv_id: str):
    """Download all <img> files referenced in ar5iv HTML to local cache.

    ar5iv generates images during LaTeXML conversion as temporary files.
    They may not be available later from CDN, so we cache them immediately.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    img_dir = Path(config.AR5IV_DIR) / arxiv_id
    urls = set(re.findall(r'<img[^>]*src="([^"]+)"', html))
    urls = {u for u in urls if not u.startswith('data:') and not u.startswith('http')}
    if not urls:
        return

    img_dir.mkdir(parents=True, exist_ok=True)
    total = len(urls)
    progress = {"ok": 0, "fail": 0, "lock": threading.Lock()}
    last_milestone = [0]

    # Extract canonical page URL from HTML for Referer
    import re as _re
    _page_url = ""
    _m = _re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html)
    if _m:
        _page_url = _m.group(1)
    else:
        _m = _re.search(r'<meta[^>]*property=["\']og:url["\'][^>]*content=["\']([^"\']+)["\']', html)
        if _m:
            _page_url = _m.group(1)
        else:
            _page_url = f"{config.AR5IV_BASE}/{arxiv_id}"

    def _dl(u):
        fname = u.split('/')[-1]
        local = img_dir / fname
        if local.exists():
            with progress["lock"]:
                progress["ok"] += 1
            return
        try:
            full_url = f"{config.AR5IV_BASE}/{arxiv_id}/{u}"
            headers = {"Referer": _page_url} if _page_url else {}
            img_data = httpx.get(full_url, timeout=15, headers=headers).content
            # Validate: reject HTML error pages pretending to be images
            if img_data[:15].startswith(b'<!') or img_data[:9].lower().startswith(b'<html'):
                with progress["lock"]:
                    progress["fail"] += 1
                return
            local.write_bytes(img_data)
            with progress["lock"]:
                progress["ok"] += 1
        except Exception:
            with progress["lock"]:
                progress["fail"] += 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_dl, u) for u in urls]
        for f in as_completed(futures):
            f.result()  # raise if any exception (ours are caught inside)
            with progress["lock"]:
                done = progress["ok"] + progress["fail"]
                pct = done * 100 // total
                # Print at every 10% milestone (10,20,30...)
                if pct >= last_milestone[0] + 10 or done == total:
                    bar = "#" * (pct // 5) + "-" * ((100 - pct) // 5)
                    print(f"          images [{bar}] {done}/{total}", flush=True)
                    last_milestone[0] = pct - (pct % 10)  # snap to last milestone


# ── Source: ar5ivist Docker ────────────────────────────────────

ARXIV_SOURCE_DIR = os.path.join(config.DATA_DIR, "arxiv_source")
AR5IVIST_OUTPUT_DIR = os.path.join(config.DATA_DIR, "ar5ivist")
AR5IVIST_DOCKER_IMAGE = config.AR5IVIST_DOCKER_IMAGE


def _download_arxiv_source(arxiv_id: str, target_dir: Path) -> Path:
    """下载 arXiv LaTeX 源文件并解压。返回 main.tex 路径。"""
    target_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded
    main_tex = target_dir / "main.tex"
    if main_tex.exists():
        return main_tex

    # Download
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    tar_path = target_dir / "source.tar.gz"
    resp = httpx.get(url, follow_redirects=True, timeout=120)
    resp.raise_for_status()
    tar_path.write_bytes(resp.content)

    # Extract
    with tarfile.open(tar_path, 'r:gz') as tar:
        tar.extractall(path=target_dir)

    # Find main .tex file
    main_tex = target_dir / "main.tex"
    if not main_tex.exists():
        # Try to find any .tex file
        tex_files = list(target_dir.glob("*.tex"))
        if tex_files:
            main_tex = tex_files[0]

    # Clean old docker output in source dir (now outputs to data/ar5ivist/)
    old_html = target_dir / "html"
    if old_html.exists():
        import shutil
        shutil.rmtree(old_html)

    return main_tex


def _try_ar5ivist_docker(arxiv_id: str) -> str:
    """用 ar5ivist Docker 转换 LaTeX → HTML。

    Source: data/arxiv_source/{id}/  (只放 tex 源文件)
    Output: data/ar5ivist/{id}/html/ (Docker 生成的 HTML + 图片)
    """
    source_dir = Path(ARXIV_SOURCE_DIR) / arxiv_id
    output_dir = Path(AR5IVIST_OUTPUT_DIR) / arxiv_id

    # Step 1: Download source
    print(f"          downloading source for {arxiv_id} ...", flush=True)
    main_tex = _download_arxiv_source(arxiv_id, source_dir)

    # Step 2: Run Docker
    log_path = output_dir / "ar5ivist.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"          running ar5ivist (log: {log_path}) ...", flush=True)

    with open(log_path, 'w') as log_f:
        cmd = [
            "docker", "run",
            "-v", f"{source_dir}:/source",
            "-v", f"{output_dir}:/output",
            "-w", "/source",
            "--user", f"{os.getuid()}:{os.getgid()}",
            AR5IVIST_DOCKER_IMAGE,
            "--source", main_tex.name,
            "--destination", f"/output/{arxiv_id}.html",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        idle_timeout = getattr(config, 'AR5IVIST_IDLE_TIMEOUT', 600)

        last_line = [""]
        last_output_at = [_time.time()]

        def _log_progress():
            for line in proc.stdout:
                log_f.write(line)
                log_f.flush()
                last_line[0] = line.rstrip()[-80:]
                last_output_at[0] = _time.time()

        t = threading.Thread(target=_log_progress, daemon=True)
        t.start()

        dots = 0
        while proc.poll() is None:
            t.join(timeout=15)
            dots += 1
            tail = last_line[0]
            idle = _time.time() - last_output_at[0]
            elapsed = dots * 15
            if tail:
                print(f"          [{elapsed}s] {tail}", flush=True)
            else:
                print(f"          [{elapsed}s] waiting... (idle {idle:.0f}s / limit {idle_timeout}s)", flush=True)

            if idle > idle_timeout:
                print(f"          ⚠ idle timeout ({idle_timeout}s) — killing docker container", flush=True)
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                raise SourceError(
                    f"ar5ivist docker timed out after {elapsed}s "
                    f"(no log output for {idle:.0f}s, threshold {idle_timeout}s). "
                    f"Full log: {log_path}"
                )

        t.join(timeout=5)
        print(f"          docker exit: {proc.returncode}", flush=True)

    # Step 3: Read output (images stay as local files, renderer handles embedding)
    output_html = output_dir / f"{arxiv_id}.html"
    if not output_html.exists():
        output_html = output_dir / "main.html"  # fallback for old runs
    if not output_html.exists():
        raise SourceError(f"ar5ivist docker produced no HTML (see {log_path})")

    # Rename old main.html to {id}.html if needed
    if output_html.name == "main.html":
        new_path = output_dir / f"{arxiv_id}.html"
        output_html.rename(new_path)
        output_html = new_path

    html = output_html.read_text(encoding="utf-8")

    # Detect SVG-only output (LaTeXML conversion failure: no text, only graphics)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    svg_paths = html.count('<path ')
    # Heuristic: >50 SVG paths but <200 chars of text → pure graphics, no content
    if svg_paths > 50 and len(text) < 200:
        raise SourceError(
            f"ar5ivist produced SVG-only output ({svg_paths} paths, "
            f"{len(text)} chars text). LaTeXML conversion failed for this paper. "
            f"See raw output: {output_html}"
        )

    return html


# ── Source: arxiv.org/html (official) ──────────────────────────

def _try_arxiv_html(arxiv_id: str) -> str:
    """从 arxiv.org/html 获取官方 HTML（含 TOC 侧边栏 + Bootstrap）。"""
    url = f"https://arxiv.org/html/{arxiv_id}"
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    if resp.status_code == 404:
        raise SourceError(f"arxiv.org/html does not have {arxiv_id}")
    resp.raise_for_status()
    html = resp.text
    if 'ltx_page_main' not in html:
        raise SourceError(f"arxiv.org/html returned non-ar5iv content for {arxiv_id}")
    return html


# Source dispatcher
_SOURCES = {
    "ar5iv": _try_ar5iv,
    "arxiv_html": _try_arxiv_html,
    "ar5ivist_docker": _try_ar5ivist_docker,
}


def fetch_html(arxiv_id_or_url: str, cache_dir: str | None = None,
               force_source: str | None = None) -> tuple[str, str, str]:
    """获取 HTML 内容，按 sources 优先级依次尝试。

    force_source: override the source order (e.g. "ar5iv", "arxiv_html").
                  Skips cache when set since cached content may be from a different source.
    """
    arxiv_id = arxiv_id_from_url(arxiv_id_or_url)

    # 检查缓存
    # Skip cache when forcing a specific source (may differ from cached)
    if cache_dir and not force_source:
        cache_path = Path(cache_dir) / arxiv_id / f"{arxiv_id}.html"
        if cache_path.exists():
            html = cache_path.read_text(encoding="utf-8")
            # Validate cached content
            if 'ltx_ERROR' in html and 'Fatal error' in html:
                raise SourceError(f"cached conversion failed for {arxiv_id}")
            if '<body' in html and 'ltx_page_main' not in html and 'ltx_ERROR' not in html:
                if 'arxiv.org/abs/' in html[:2000]:
                    raise SourceError(f"cached file is arXiv page, not ar5iv HTML ({arxiv_id})")
            # Try to recall original source type from PaperCache
            cached_src = "unknown"
            try:
                from src.translation.cache import PaperCache
                pc = PaperCache.load(arxiv_id)
                if pc.src_type:
                    cached_src = pc.src_type
            except Exception:
                pass
            # Fallback: detect source from HTML content
            if cached_src == "unknown":
                if "ltx_page_navbar" in html or 'arxiv.org/html' in html[:5000]:
                    cached_src = "arxiv_html"
                elif "ltx_page_main" in html:
                    cached_src = "ar5iv"
            print(f"        (cached from {cached_src})", flush=True)
            # Try to cache images even for cached HTML (may have been missed on first fetch)
            _cache_ar5iv_images(html, arxiv_id)
            return arxiv_id, cached_src, html

    # 按优先级尝试各来源
    if force_source:
        sources = [{"type": force_source}]
        print(f"        (forced source: {force_source})", flush=True)
    else:
        sources = config.SOURCES
    errors = []
    for i, src_cfg in enumerate(sources):
        src_type = src_cfg["type"]
        if src_type not in _SOURCES:
            continue
        try:
            print(f"        [{i+1}/{len(sources)}] trying {src_type} ...", flush=True)
            html = _SOURCES[src_type](arxiv_id)

            # Save to cache
            if cache_dir:
                paper_dir = Path(cache_dir) / arxiv_id
                paper_dir.mkdir(parents=True, exist_ok=True)
                (paper_dir / f"{arxiv_id}.html").write_text(html, encoding="utf-8")

            return arxiv_id, src_type, html
        except SourceError as e:
            print(f"             failed: {e}", flush=True)
            errors.append(f"{src_type}: {e}")
        except Exception as e:
            # Non-source errors (network, etc) also try next source
            print(f"             error: {e}", flush=True)
            errors.append(f"{src_type}: {e}")

    raise RuntimeError(f"All sources failed for {arxiv_id}:\n  " + "\n  ".join(errors))
