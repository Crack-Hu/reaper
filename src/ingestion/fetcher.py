"""HTML 获取模块 — 多来源管道"""

import httpx
import re
import subprocess
import tarfile
import os
import threading
import time
from pathlib import Path
from .. import config, logbook as _logbook

# 随程序分发的 LaTeXML bindings（只读挂载进 ar5ivist 容器）
BINDINGS_DIR = Path(__file__).parent / "ar5ivist_bindings"

# 图救援（把 LaTeXML 画不了的图用真 LaTeX 渲染成 SVG）的单次编译上限
RESCUE_TIMEOUT = 600.0

# 救援产物在容器里的路径（= 相对文档目录），与 diagram_rescue.DIAGRAM_DIR 一致
DIAGRAM_DIR_NAME = "reaper-diagrams"


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


def _cache_ar5iv_images(html: str, arxiv_id: str, img_dir: Path | None = None):
    """Download all <img> files referenced in ar5iv HTML to local cache.

    ar5iv generates images during LaTeXML conversion as temporary files.
    They may not be available later from CDN, so we cache them immediately.

    `img_dir` defaults to the paper's standard source directory.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    if img_dir is None:
        img_dir = Path(config.source_dir(arxiv_id))
    urls = set(re.findall(r'<img[^>]*src="([^"]+)"', html))
    urls |= set(re.findall(r'<object[^>]*data="([^"]+)"', html))
    urls = {u for u in urls if not u.startswith('data:') and not u.startswith('http')}
    if not urls:
        return

    img_dir.mkdir(parents=True, exist_ok=True)
    total = len(urls)
    progress = {"ok": 0, "fail": 0, "lock": threading.Lock()}

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
                # 进度只更新状态面板（不产生日志行）：并行时不会刷屏，
                # 日志文件也不会被进度条灌满。非 TTY 下 set_progress 是无害的 no-op。
                _logbook.set_progress(note=f"图片 {done}/{total}",
                                      pct=done * 100.0 / max(total, 1))

    _logbook.set_progress(note="")
    print(f"          images: {progress['ok']}/{total} cached"
          + (f", {progress['fail']} failed" if progress["fail"] else ""), flush=True)


# ── Source: ar5ivist Docker ────────────────────────────────────



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

    # Clean old docker output in the source dir (docker now writes into source_dir)
    old_html = target_dir / "html"
    if old_html.exists():
        import shutil
        shutil.rmtree(old_html)

    return main_tex


def _ensure_image(image: str) -> None:
    """Make sure the container image exists locally, pulling it if needed.

    `docker run` pulls implicitly when the image is missing, which silently
    mixes a multi-GB download into what we report as conversion progress (and,
    worse, into the conversion timeout). Pulling explicitly makes the first run
    look like a download instead of a hang — the user still has to wait, but
    they know why.
    """
    try:
        probe = subprocess.run(["docker", "image", "inspect", image],
                               capture_output=True, timeout=60, check=False)
    except FileNotFoundError as e:
        raise SourceError(
            "找不到 docker 命令：ar5ivist_docker 来源需要本机 Docker 在运行"
        ) from e
    except subprocess.TimeoutExpired:
        probe = None
    if probe is not None and probe.returncode == 0:
        return

    print(f"          image {image} 不在本地 —— 开始拉取"
          f"（首次需要下载数 GB，可能要几分钟到几十分钟）...", flush=True)
    timeout = config.AR5IVIST_PULL_TIMEOUT
    proc = subprocess.Popen(["docker", "pull", image],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last = [""]

    def _drain():
        for line in proc.stdout:
            last[0] = line.rstrip()

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    started = time.monotonic()
    while proc.poll() is None:
        t.join(timeout=15)
        elapsed = int(time.monotonic() - started)
        print(f"          [pull {elapsed}s] {last[0][-90:] if last[0] else '(no output)'}",
              flush=True)
        if timeout and elapsed > timeout:
            proc.kill()
            raise SourceError(
                f"拉取镜像 {image} 超过 {timeout}s 未完成 —— 网络太慢或磁盘空间不足"
                f"（可手动 `docker pull {image}` 后再试）"
            )
    t.join(timeout=5)
    if proc.returncode != 0:
        raise SourceError(
            f"拉取镜像 {image} 失败（docker exit {proc.returncode}）："
            f"{last[0] or '（无输出）'}"
        )
    print(f"          image ready: {image}", flush=True)


def _docker_kill(name: str, timeout: float = 30.0) -> None:
    """Best-effort stop+remove of a container.

    Killing the *docker client* does not stop the container it started, so a
    timeout has to go through the daemon (`docker rm -f`).
    """
    try:
        subprocess.run(["docker", "rm", "-f", name],
                       capture_output=True, timeout=timeout, check=False)
    except Exception:
        pass


def _rescue_diagrams(source_dir: Path, diagrams_dir: Path, main_name: str,
                     output_dir: Path) -> None:
    """Render unsupported diagrams with the container's real LaTeX toolchain.

    `diagram_rescue` prepares one small document per diagram in
    `config.diagrams_dir()` (`process/reaper-diagrams`, *not* next to the paper's
    sources); this runs the container once to turn them into SVGs. The directory
    is mounted at `/source/reaper-diagrams` so the converter — which resolves
    paths relative to the document directory — finds them where it expects.

    Failures are non-fatal: the placeholder stays, the article stays complete.
    """
    from . import diagram_rescue as rescue

    report = rescue.prepare(source_dir, diagrams_dir, main_name)
    if not report.count:
        return
    print(f"          rendering {report.count} diagram(s) with LaTeX ...", flush=True)
    log_path = output_dir / "reaper-diagrams-compile.log"
    cmd = [
        "docker", "run", "--rm", "--entrypoint", "sh",
        "-v", f"{source_dir}:/source",
        "-v", f"{diagrams_dir}:/source/{rescue.DIAGRAM_DIR}",
        "-w", "/source",
        "--user", f"{os.getuid()}:{os.getgid()}",
        config.AR5IVIST_DOCKER_IMAGE,
        "-c", rescue.compile_script(),
    ]
    try:
        with open(log_path, "w") as log_f:
            subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT,
                           timeout=RESCUE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        print(f"          diagram rendering timed out after {RESCUE_TIMEOUT}s"
              f" — keeping placeholders", flush=True)
    except Exception as e:                      # docker missing, etc.
        print(f"          diagram rendering failed ({e}) — keeping placeholders",
              flush=True)

    compiled, failed = rescue.verify(diagrams_dir)
    print(f"          diagrams: {compiled}/{report.count} rendered"
          + (f", {len(failed)} kept as placeholder" if failed else ""), flush=True)


def _try_ar5ivist_docker(arxiv_id: str) -> str:
    """用 ar5ivist Docker 转换 LaTeX → HTML。

    Source + output: config.source_dir(arxiv_id)  (tex 源码 + Docker 生成的 HTML/图片)
    """
    source_dir = Path(config.source_dir(arxiv_id))
    output_dir = Path(config.source_dir(arxiv_id))

    # Step 1: Download source
    print(f"          downloading source for {arxiv_id} ...", flush=True)
    main_tex = _download_arxiv_source(arxiv_id, source_dir)

    # Step 1a: the image may have to be downloaded first (see _ensure_image)
    _ensure_image(config.AR5IVIST_DOCKER_IMAGE)

    # Step 1b: render the diagrams LaTeXML cannot handle (Xy-pic/Qcircuit …)
    # with the real TeX Live that ships in the same image, so the binding can
    # include them instead of dropping them. Purely additive: when nothing is
    # found, or the render fails, the diagram falls back to a placeholder.
    diagrams_dir = Path(config.diagrams_dir(arxiv_id))
    if config.AR5IVIST_RENDER_DIAGRAMS and config.AR5IVIST_XYPIC_STUB:
        _rescue_diagrams(source_dir, diagrams_dir, main_tex.name, output_dir)

    # Step 2: Run Docker
    log_path = output_dir / "ar5ivist.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"          running ar5ivist (log: {log_path}) ...", flush=True)

    timeout = config.AR5IVIST_TIMEOUT
    container = f"reaper-{arxiv_id.replace('.', '-').replace('/', '-')}-{os.getpid()}"
    timed_out = False

    with open(log_path, 'w') as log_f:
        cmd = [
            "docker", "run", "--rm", "--name", container,
            "-v", f"{source_dir}:/source",
            "-v", f"{output_dir}:/output",
            "-w", "/source",
            "--user", f"{os.getuid()}:{os.getgid()}",
        ]
        # 随程序分发的 LaTeXML bindings（只读挂载）。它们修正转换器自身的行为，
        # 不需要改论文源码：抬高 100 错误上限 / 让 Xy-pic 图表不吞掉后续内容。
        preloads = []
        if config.AR5IVIST_MAX_ERRORS > 0:
            preloads.append("reaper-maxerrors.ltxml")
        if config.AR5IVIST_XYPIC_STUB:
            preloads.append("reaper-qcircuit.sty")
        if preloads:
            cmd += [
                "-v", f"{BINDINGS_DIR}:/reaper-bindings:ro",
                "-e", f"REAPER_MAX_ERRORS={config.AR5IVIST_MAX_ERRORS}",
            ]
        # 救援出来的图放在 process/ 下，但转换器只能按"相对文档目录"找文件
        if diagrams_dir.exists():
            cmd += ["-v", f"{diagrams_dir}:/source/{DIAGRAM_DIR_NAME}"]
        cmd += [
            config.AR5IVIST_DOCKER_IMAGE,
            "--source", main_tex.name,
            "--destination", f"/output/{arxiv_id}.html",
        ]
        if preloads:
            cmd += ["--path=/reaper-bindings"]
            cmd += [f"--preload={name}" for name in preloads]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        last_line = [""]

        def _log_progress():
            for line in proc.stdout:
                log_f.write(line)
                log_f.flush()
                last_line[0] = line.rstrip()[-80:]

        t = threading.Thread(target=_log_progress, daemon=True)
        t.start()

        started = time.monotonic()
        while proc.poll() is None:
            t.join(timeout=15)
            elapsed = time.monotonic() - started
            tail = last_line[0]
            print(f"          [{int(elapsed)}s] {tail if tail else '(no output)'}",
                  flush=True)
            # LaTeXML 会卡在个别宏包上（上游有过 infinite-loop 报告）；没有上限
            # 就会永久挂起，所以到点就杀掉容器并让这个来源失败。
            if timeout and elapsed > timeout:
                timed_out = True
                print(f"          ⏱ 超过 {timeout}s 仍在跑，停掉容器"
                      f"（最后一行：{tail or '无输出'}）", flush=True)
                _docker_kill(container)
                break

        t.join(timeout=5)
        print(f"          docker exit: {proc.returncode}", flush=True)

    if timed_out:
        raise SourceError(
            f"ar5ivist 转换超时（{timeout}s）：LaTeXML 没有跑完。"
            f"最后一行：{last_line[0] or '（无输出）'}；完整日志见 {log_path}"
        )

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
               force_source: str | None = None) -> "FetchedPage":
    """获取 HTML 内容，按 sources 优先级依次尝试。

    Returns a FetchedPage with html, source_type, arxiv_id, img_dir, page_url.

    cache_dir: **该论文自己的目录**（不是所有论文共用的父目录）。缓存的 HTML
               放在 `{cache_dir}/{arxiv_id}.html`，引用的图片放在 `{cache_dir}/`。
               默认使用 `config.source_dir(arxiv_id)`。
    force_source: override the source order (e.g. "ar5iv", "arxiv_html").
                  Skips cache when set since cached content may be from a different source.
    """
    from .fetched_page import FetchedPage

    arxiv_id = arxiv_id_from_url(arxiv_id_or_url)
    paper_dir = Path(cache_dir) if cache_dir else Path(config.source_dir(arxiv_id))

    def _build_fp(src_type: str, html: str) -> FetchedPage:
        img_dir = paper_dir
        # Derive page_url from HTML metadata first, then fall back to source type
        page_url = ""
        # Try <link rel="canonical">
        m = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html)
        if m:
            page_url = m.group(1)
        # Try <base href="...">
        if not page_url:
            m = re.search(r'<base\s+href="([^"]+)"', html)
            if m:
                page_url = m.group(1)
        # Fall back to source type
        if not page_url:
            if src_type == "arxiv_html":
                page_url = f"https://arxiv.org/html/{arxiv_id}"
            elif src_type == "ar5iv":
                page_url = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
            else:
                page_url = f"https://arxiv.org/abs/{arxiv_id}"
        return FetchedPage(
            arxiv_id=arxiv_id,
            source_type=src_type,
            html=html,
            img_dir=img_dir,
            page_url=page_url,
        )

    # 检查缓存
    # Skip cache when forcing a specific source (may differ from cached)
    if not force_source:
        cache_path = paper_dir / f"{arxiv_id}.html"
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
            _cache_ar5iv_images(html, arxiv_id, paper_dir)
            return _build_fp(cached_src, html)

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

            # Save to cache (one file per paper inside its own directory)
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / f"{arxiv_id}.html").write_text(html, encoding="utf-8")

            return _build_fp(src_type, html)
        except SourceError as e:
            print(f"             failed: {e}", flush=True)
            errors.append(f"{src_type}: {e}")
        except Exception as e:
            # Non-source errors (network, etc) also try next source
            print(f"             error: {e}", flush=True)
            errors.append(f"{src_type}: {e}")

    raise RuntimeError(f"All sources failed for {arxiv_id}:\n  " + "\n  ".join(errors))
