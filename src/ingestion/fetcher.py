"""HTML 获取模块 — 多来源管道"""

import httpx
import re
import subprocess
import tarfile
import os
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
    """从 ar5iv.labs.arxiv.org 获取 HTML。"""
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

    return html


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

        last_line = [""]
        def _log_progress():
            for line in proc.stdout:
                log_f.write(line)
                log_f.flush()
                last_line[0] = line.rstrip()[-80:]

        t = threading.Thread(target=_log_progress, daemon=True)
        t.start()

        dots = 0
        while proc.poll() is None:
            t.join(timeout=15)
            dots += 1
            tail = last_line[0]
            if tail:
                print(f"          [{dots*15}s] {tail}", flush=True)

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


def _cache_ar5iv_css(css_path: Path):
    """Copy ar5iv CSS from global cache to paper directory."""
    import shutil
    css_dir = Path(config.DATA_DIR) / "css"
    merged = css_dir / "ar5iv-merged.css"
    if merged.exists():
        shutil.copy(merged, css_path)
    else:
        # Merge individual files on first call
        parts = []
        for f in sorted(css_dir.glob("ar5iv*.css")):
            parts.append(f.read_text(encoding="utf-8"))
        if parts:
            merged.write_text("\n".join(parts), encoding="utf-8")
            shutil.copy(merged, css_path)


# ── 主入口 ─────────────────────────────────────────────────────

# Source dispatcher
_SOURCES = {
    "ar5iv": _try_ar5iv,
    "arxiv_html": _try_arxiv_html,
    "ar5ivist_docker": _try_ar5ivist_docker,
}


def fetch_html(arxiv_id_or_url: str, cache_dir: str | None = None) -> tuple[str, str, str]:
    """获取 HTML 内容，按 sources 优先级依次尝试。

    顺序: ① 缓存 → ② config.sources（逐一下载/生成）→ ③ 全部失败则抛异常
    """
    arxiv_id = arxiv_id_from_url(arxiv_id_or_url)

    # 检查缓存
    if cache_dir:
        cache_path = Path(cache_dir) / arxiv_id / f"{arxiv_id}.html"
        if cache_path.exists():
            html = cache_path.read_text(encoding="utf-8")
            # Validate cached content
            if 'ltx_ERROR' in html and 'Fatal error' in html:
                raise SourceError(f"cached conversion failed for {arxiv_id}")
            if '<body' in html and 'ltx_page_main' not in html and 'ltx_ERROR' not in html:
                if 'arxiv.org/abs/' in html[:2000]:
                    raise SourceError(f"cached file is arXiv page, not ar5iv HTML ({arxiv_id})")
            print(f"        (cached)", flush=True)
            return arxiv_id, "cache", html

    # 按优先级尝试各来源
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
                # Also cache ar5iv CSS if not already present
                css_path = paper_dir / "ar5iv.css"
                if not css_path.exists():
                    _cache_ar5iv_css(css_path)

            return arxiv_id, src_type, html
        except SourceError as e:
            print(f"             failed: {e}", flush=True)
            errors.append(f"{src_type}: {e}")
        except Exception as e:
            # Non-source errors (network, etc) also try next source
            print(f"             error: {e}", flush=True)
            errors.append(f"{src_type}: {e}")

    raise RuntimeError(f"All sources failed for {arxiv_id}:\n  " + "\n  ".join(errors))
