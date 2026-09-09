"""Bilingual HTML renderer — translates ar5iv HTML into a self-contained Zotero attachment.

All external resources (CSS, images, fonts) are embedded inline.
No network access needed after generation.
"""

import json
import os
import re
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..ingestion.parser import restore_math_in_translation
from .. import config

AR5IV_BASE = "https://ar5iv.labs.arxiv.org"
UI_DIR = Path(__file__).parent / "ui"  # toc-sidebar.css, toc-toggle.js
CSS_CACHE = Path(__file__).parent / "arxiv_css"  # src/rendering/arxiv_css/
CSS_FILES = {
    "core": "/assets/ar5iv.0.8.5.css",
    "fonts": "/assets/ar5iv-fonts.0.8.4.css",
}

# ── Generic resource scanning ──────────────────────────────────────
# Instead of enumerating tag types, we scan for attributes that commonly
# hold external resource URLs. This avoids whack-a-mole with new tag types.

RESOURCE_ATTRS = {'src', 'data', 'poster'}

# Match any tag that has one of the resource attributes.
# Captures: (tag_name, attr_name, attr_value)
_RESOURCE_PATTERN = re.compile(
    r'<(\w+)\b[^>]*(?:' + '|'.join(RESOURCE_ATTRS) + r')="([^"]+)"[^>]*>'
)

_CSS_LINK_PATTERN = re.compile(r'<link\b[^>]*href="([^"]*)"[^>]*>')


def _is_downloadable_url(value: str) -> bool:
    """Check if an attribute value is a downloadable external resource."""
    if not value:
        return False
    if value.startswith('data:'):
        return False
    if value.startswith('#'):
        return False
    if value.startswith('javascript:'):
        return False
    if value.startswith('mailto:'):
        return False
    return True


def _is_image_data(data: bytes) -> bool:
    """Check if raw bytes look like an image, not an HTML error page."""
    if not data:
        return False
    # Common image magic bytes
    if data[:4] == b'\x89PNG':    # PNG
        return True
    if data[:2] == b'\xff\xd8':   # JPEG
        return True
    if data[:3] == b'GIF':        # GIF
        return True
    if data[:4] == b'<svg':       # SVG (text)
        return True
    # Reject HTML, XML declarations
    if data[:15].startswith(b'<!') or data[:9].lower().startswith(b'<html'):
        return False
    # Unknown — accept (could be a new image format)
    return True


def _resolve_image_url(url: str, fp: "FetchedPage") -> str:
    """Convert a relative image URL to an absolute CDN URL.

    Uses fp.page_url as the base for resolving relative URLs.
    """
    if url.startswith("http") or url.startswith("data:"):
        return url
    if url.startswith("/"):
        # Absolute path — prepend domain
        domain = "https://arxiv.org" if fp.source_type == "arxiv_html" else AR5IV_BASE
        return domain + url
    # Relative path — resolve against the source's HTML root
    # Strip any arxiv ID prefix (with or without version) from the path
    clean_url = url
    # Remove leading arxiv ID pattern like "2307.14989" or "2307.14989v6"
    m = re.match(r'^\d{4}\.\d+(v\d+)?/', clean_url)
    if m:
        clean_url = clean_url[m.end():]
    domain = "https://arxiv.org" if fp.source_type == "arxiv_html" else AR5IV_BASE
    return f"{domain}/html/{fp.arxiv_id}/{clean_url}"


def _fetch(url: str, referer: str = "") -> bytes:
    """Fetch a URL, return bytes. Optionally set Referer header."""
    import httpx
    headers = {"User-Agent": "Reaper/1.0"}
    if referer:
        headers["Referer"] = referer
    resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _inline_css(html: str) -> tuple[str, str]:
    """Get ar5iv CSS (cached to data/css/) and embed as <style>. Returns (html, css_block)."""
    CSS_CACHE.mkdir(parents=True, exist_ok=True)
    styles = []
    for name, path in CSS_FILES.items():
        cache_path = CSS_CACHE / path.rsplit("/", 1)[-1]
        if cache_path.exists():
            data = cache_path.read_text(encoding="utf-8")
            print(f"        css {cache_path.name} (cached)", flush=True)
        else:
            try:
                data = _fetch(AR5IV_BASE + path).decode("utf-8")
                cache_path.write_text(data, encoding="utf-8")
                print(f"        css {cache_path.name} downloaded ({len(data):,} bytes)", flush=True)
            except Exception as e:
                print(f"        css fetch failed {path}: {e}", flush=True)
                continue
        styles.append(f"/* ar5iv-{name} */\n{data}")

    # Remove all ar5iv CSS <link> tags
    html = _CSS_LINK_PATTERN.sub(
        lambda m: "" if "ar5iv" in m.group(1) or "ar5iv-site" in m.group(1) else m.group(0),
        html
    )

    css_block = "<style>\n" + "\n".join(styles) + "\n</style>"
    return html, css_block


def _strip_arxiv_brand(html: str) -> str:
    """Remove arXiv-specific JS/CSS, keep TOC sidebar structure."""
    # Remove ALL external scripts from arxiv CDN (they are branding, not content)
    html = re.sub(r'<script[^>]*src="https?://[^"]*arxiv[^"]*"[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*src="[^"]*\/static\/[^"]*"[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    # Remove specific known scripts
    html = re.sub(r'<script[^>]*addons_new[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*feedbackOverlay[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*html2canvas[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<link[^>]*latexml_styles[^>]*>', '', html)
    # Remove arXiv announcement banner
    html = re.sub(r'<div\b[^>]*class="[^"]*ds-announcement[^"]*"[^>]*>.*?</div>', '', html, flags=re.DOTALL)
    # Remove arXiv logo header
    html = re.sub(r'<div\b[^>]*class="[^"]*html-header-logo[^"]*"[^>]*>.*?</div>', '', html, flags=re.DOTALL)
    # Remove arXiv header navigation (Back to Abstract, Report Issue, Download PDF)
    html = re.sub(r'<nav\b[^>]*class="[^"]*html-header-nav[^"]*"[^>]*>.*?</nav>', '', html, flags=re.DOTALL)
    # Remove license footer and watermark
    html = re.sub(r'<a\b[^>]*id="license-tr"[^>]*>.*?</a>', '', html, flags=re.DOTALL)
    html = re.sub(r'<div\b[^>]*id="watermark-tr"[^>]*>.*?</div>', '', html, flags=re.DOTALL)
    return html


# ── Resource processing ───────────────────────────────────────────

def _process_resources(html: str, fp: "FetchedPage",
                      resource_dir: str | None = None) -> str:
    """Download external resources and embed with CDN fallback.

    When resource_dir is set:
      - Download resources, save to {resource_dir}/assets/
      - Use local path as src, CDN URL as data-cdn onerror fallback
      - Works offline when assets/ exists, falls back to CDN otherwise

    When resource_dir is None:
      - Just use CDN URLs (no local assets, "Light mode")
    """
    from ..ingestion.fetched_page import FetchedPage
    img_dir = fp.img_dir
    source_type = fp.source_type

    # Collect all unique external resource URLs
    url_to_attrs = {}  # url -> [(full_match, attr_name, attr_value)]
    for m in _RESOURCE_PATTERN.finditer(html):
        tag_name = m.group(1)
        if tag_name == 'script':
            continue
        url = m.group(2)
        if not _is_downloadable_url(url):
            continue
        if url not in url_to_attrs:
            url_to_attrs[url] = []
        url_to_attrs[url].append((m.group(0), m.group(2)))

    if not url_to_attrs:
        return html

    all_urls = list(url_to_attrs.keys())
    total = len(all_urls)

    # Prepare local assets directory
    assets_dir = None
    if resource_dir:
        assets_dir = Path(resource_dir) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

    print(f"        processing {total} resources from {source_type} ...", flush=True)

    # url -> (local_path or None, cdn_url)
    url_to_result = {}

    def download_one(url):
        cdn_url = _resolve_image_url(url, fp)
        local_path = None
        try:
            raw = None
            if source_type == "ar5ivist_docker" or img_dir.exists():
                fname = url.split("/")[-1] if "/" in url else url
                local = img_dir / fname
                if local.exists():
                    raw = local.read_bytes()
            if raw is None and resource_dir:
                full_url = cdn_url
                raw = _fetch(full_url, referer=fp.page_url)
                if not _is_image_data(raw):
                    raise ValueError(f"not an image: {full_url}")
                # Cache to fp.img_dir for future runs
                img_dir.mkdir(parents=True, exist_ok=True)
                fname = url.split("/")[-1]
                (img_dir / fname).write_bytes(raw)

            if raw is not None and assets_dir:
                ext = "." + url.rsplit(".", 1)[-1].lower() if "." in url else ".png"
                fname = hashlib.md5(url.encode()).hexdigest()[:16] + ext
                dest = assets_dir / fname
                dest.write_bytes(raw)
                local_path = f"assets/{fname}"
        except Exception:
            pass  # Fallback: use CDN URL

        return url, (local_path, cdn_url)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download_one, u): u for u in all_urls}
        done_count = 0
        last_pct = 0
        for f in as_completed(futures):
            url, (local_path, cdn_url) = f.result()
            url_to_result[url] = (local_path, cdn_url)
            done_count += 1
            pct = done_count * 100 // total
            if pct >= last_pct + 10 or done_count == total:
                bar = "#" * (pct // 5) + "-" * ((100 - pct) // 5)
                saved = sum(1 for v in url_to_result.values() if v[0] is not None)
                print(f"        embed [{bar}] {done_count}/{total} ({saved} saved)", flush=True)
                last_pct = pct - (pct % 10)

    saved = sum(1 for v in url_to_result.values() if v[0] is not None)
    print(f"        done: {saved}/{total} saved locally, rest use CDN", flush=True)

    # Replace tags: add local src + data-cdn fallback
    def replacer(m):
        tag = m.group(0)
        attr_value = m.group(2)
        result = url_to_result.get(attr_value)
        if result is None:
            return tag
        local_path, cdn_url = result

        if local_path:
            # Add local src + data-cdn (onerror removed — Zotero browser crashes)
            tag = tag.replace(f'="{attr_value}"', f'="{local_path}"', 1)
            tag = tag.rstrip(' >')
            tag += f' data-cdn="{cdn_url}"'
            if not tag.endswith('>'):
                tag += '>'
        else:
            # No local asset, use CDN URL directly
            tag = tag.replace(f'="{attr_value}"', f'="{cdn_url}"', 1)
        return tag

    html = _RESOURCE_PATTERN.sub(replacer, html)
    return html


_SOURCE_TOGGLE_JS = """
<script id="reaper-source-toggle">
(function(){
  var mode = localStorage.getItem('reaper_source') || 'auto';
  function applyMode(m) {
    mode = m;
    localStorage.setItem('reaper_source', m);
    document.querySelectorAll('[data-cdn]').forEach(function(el) {
      var localSrc = el.getAttribute('src');
      var cdnSrc = el.getAttribute('data-cdn');
      if (m === 'cdn' && localSrc && cdnSrc && !localSrc.startsWith('http')) {
        el.setAttribute('src', cdnSrc);
      } else if (m === 'local' && cdnSrc && localSrc && localSrc.startsWith('http')) {
        el.setAttribute('src', localSrc);
      }
    });
    var btn = document.getElementById('reaper-source-btn');
    if (btn) {
      btn.textContent = m === 'cdn' ? '\u25C9' : '\u25CE';
      btn.title = m === 'cdn' ? 'Switch to local assets' : 'Switch to CDN';
      btn.classList.toggle('active', m === 'local');
    }
  }
  applyMode(mode);
  window.toggleReaperSource = function() {
    applyMode(mode === 'cdn' ? 'local' : 'cdn');
  };
})();
</script>
"""


def replace_footer(html: str, arxiv_id: str, source_type: str = "ar5iv") -> str:
    """Replace footer with source-specific Reaper footer."""
    html = re.sub(r'<div\b[^>]*class="[^"]*ar5iv-footer[^"]*"[^>]*>.*?</div>', '', html, flags=re.DOTALL)
    html = re.sub(r'<footer\b[^>]*>.*?</footer>', '', html, flags=re.DOTALL)
    html = re.sub(r'<div[^>]*style="[^"]*text-align:center[^"]*"[^>]*>.*?Reaper.*?</div>', '', html, flags=re.DOTALL)

    # Source-specific credit
    if source_type == "ar5ivist_docker":
        credit = 'generated by <a href="https://github.com/dginev/ar5ivist" style="color:#888">ar5ivist</a>'
    elif source_type == "arxiv_html":
        credit = f'HTML from <a href="https://arxiv.org/html/{arxiv_id}" style="color:#888">arxiv.org</a>'
    else:
        credit = f'HTML from <a href="https://ar5iv.labs.arxiv.org/html/{arxiv_id}" style="color:#888">ar5iv</a>'

    footer = (
        f'<div style="text-align:center;padding:20px;font-size:12px;color:#888;'
        f'border-top:1px solid #eee;margin-top:40px;font-family:sans-serif">'
        f'<a href="https://arxiv.org/abs/{arxiv_id}" style="color:#888">arxiv:{arxiv_id}</a>'
        f' · {credit} · Modified by Reaper'
        f'</div>'
    )
    return html.replace('</body>', f'{footer}</body>')


# === Translation injection ===

def _inject_blocks_toc(html: str, toc_entries: list[tuple[int, dict]]) -> str:
    """Insert TOC sidebar with nested collapsible hierarchy."""
    parts = []
    stack = []

    for i, (idx, b) in enumerate(toc_entries):
        anchor = f"reaper-sec-{idx}"
        text = b.get("text", b.get("en", ""))[:80].strip()
        if not text:
            continue

        level = b.get("level", 1)
        next_level = toc_entries[i+1][1].get("level", 1) if i+1 < len(toc_entries) else 0

        # Close levels that are >= current
        while stack and stack[-1][0] >= level:
            lv, _ = stack.pop()
            parts.append('</li></ol>')

        cls_names = {1: 'section', 2: 'subsection', 3: 'subsubsection'}
        cls = cls_names.get(min(level, 3), 'subsection')
        has_kids = next_level > level and level >= 1
        toggle = '<span class="reaper-toc-toggle-icon">&#9660;</span>' if has_kids else ''
        parts.append(
            f'<li class="ltx_tocentry ltx_tocentry_{cls}">'
            f'{toggle}<a class="ltx_ref" href="#{anchor}">{text}</a>'
        )

        if has_kids:
            parts.append('<ol class="ltx_toclist' + (' collapsed' if level >= 2 else '') + '">')
            stack.append((level, 'open'))

        # Add id to heading tag
        marker = f'data-reaper-id="{idx}"'
        pos = html.find(marker)
        if pos == -1:
            continue
        tag_start = html.rfind('<', 0, pos)
        tag_end = html.index('>', pos) + 1
        tag = html[tag_start:tag_end]
        if ' id=' not in tag.replace('data-reaper-id=', ''):
            new_tag = tag.replace('>', f' id="{anchor}">', 1)
            html = html[:tag_start] + new_tag + html[tag_end:]

    while stack:
        stack.pop()
        parts.append('</li></ol>')

    if not parts:
        return html

    toc_html = (
        '<nav class="ltx_page_navbar"><nav class="ltx_TOC">'
        '<ol class="ltx_toclist">' + ''.join(parts) + '</ol>'
        '</nav></nav>'
    )
    html = html.replace('<body>', '<body>\n' + toc_html + '\n<div class="reaper-content">', 1)
    html = html.replace('</body>', '</div></body>', 1)
    return html
def _inject_translation(html: str, block_index: int, zh_text: str, inline: bool = False) -> str:
    marker = f'data-reaper-id="{block_index}"'
    cls = 'reaper-zh reaper-zh-inline' if inline else 'reaper-zh'
    wrapper = (
        f'<span class="{cls}">'
        f'{"&nbsp;&nbsp;" if inline else "<br>"}<span class="reaper-zh-text">{zh_text}</span>'
        f'</span>'
    )
    pos = html.find(marker)
    if pos == -1:
        return html
    tag_beg = html.rfind('<', 0, pos)
    tag_match = re.match(r'<(\w+)', html[tag_beg:])
    if not tag_match:
        return html
    tag_name = tag_match.group(1)
    close = _find_close_tag(html, tag_beg, tag_name)
    if close == -1:
        return html
    if 'reaper-zh' in html[tag_beg:close]:
        return html
    # Insert the translation just before the element's closing tag
    return html[:close] + wrapper + html[close:]


def _find_close_tag(html: str, tag_beg: int, tag_name: str) -> int:
    """Return the start index of the matching close tag for an opening tag."""
    open_re = re.compile(rf'<{re.escape(tag_name)}\b')
    close_re = re.compile(rf'</{re.escape(tag_name)}\s*>')
    depth = 0
    pos = tag_beg + len(f'<{tag_name}')
    while True:
        next_open = open_re.search(html, pos)
        next_close = close_re.search(html, pos)
        if next_close is None:
            return -1
        if next_open is not None and next_open.start() < next_close.start():
            # Skip self-closing tags (e.g. <span/>)
            gt = html.find('>', next_open.start())
            if gt != -1 and html[gt - 1:gt] == '/':
                pos = gt + 1
                continue
            depth += 1
            pos = gt + 1 if gt != -1 else next_open.end()
            continue
        if depth == 0:
            return next_close.start()
        depth -= 1
        pos = next_close.end()


# === Main ===

def render_bilingual_html(
    marked_html: str,
    blocks_with_zh: list[dict],
    fp: "FetchedPage",
    term_dict: dict[str, str] | None = None,
    resource_dir: str | None = None,
    embed_images: bool = True,
) -> str:
    """Generate bilingual HTML.

    resource_dir:  if set, save resources to {resource_dir}/assets/ and use
                   relative paths with CDN fallback (Zotero-compatible).
                   If None, use CDN URLs only ("Light mode").
    embed_images:  deprecated, kept for backward compatibility.
    fp: FetchedPage with source_type, arxiv_id, img_dir, page_url
    """
    from ..ingestion.fetched_page import FetchedPage
    html = marked_html
    source_type = fp.source_type
    arxiv_id = fp.arxiv_id
    is_arxiv = (source_type == "arxiv_html" or
                ("ltx_page_navbar" in marked_html))

    # 1. arxiv_html: strip arXiv brand scripts, fix TOC links, wrap content
    if is_arxiv:
        html = _strip_arxiv_brand(html)
        # Convert arxiv.org TOC links to document anchors
        base_id = arxiv_id.split("v")[0]
        html = re.sub(
            rf'href="https://arxiv\.org/html/{re.escape(base_id)}(v\d+)?(#[^"]*)"',
            r'href="\2"',
            html
        )
        # Remove <base> tag (interferes with anchor links)
        html = re.sub(r'<base\b[^>]*>', '', html)
        # Wrap content in reaper-content canvas (TOC nav already in HTML)
        html = html.replace('<body>', '<body>\n<div class="reaper-content">', 1)
        html = html.replace('</body>', '</div></body>', 1)

    # 2. Embed ar5iv CSS inline
    html, core_css = _inline_css(html)

    # 3. External resources: download + embed with CDN fallback
    html = _process_resources(html, fp, resource_dir=resource_dir)

    # 3. Build TOC from blocks (ar5iv/ar5ivist: generate; arxiv_html: already in HTML)
    toc_entries = [(i, b) for i, b in enumerate(blocks_with_zh)
                   if b.get("type") in ("section", "title")]
    if toc_entries and not is_arxiv:
        html = _inject_blocks_toc(html, toc_entries)

    # 4. Replace footer
    html = replace_footer(html, arxiv_id, source_type)

    # 5. Inject TOC CSS/JS + translation colors
    toc_css = (UI_DIR / "toc-sidebar.css").read_text(encoding="utf-8")
    toc_js = (UI_DIR / "toc-toggle.js").read_text(encoding="utf-8")
    
    if is_arxiv or toc_entries:
        # TOC sidebar present — inject sidebar CSS/JS
        override_css = (
            '<style>' + toc_css + '</style>'
            '<script>' + toc_js + '</script>'
        )
    else:
        override_css = (
            '<style>'
            '.ltx_page_main{max-width:52rem;margin:3rem auto 6rem;padding:0 1.5rem}'
            'body{font-family:"Noto Serif",Georgia,serif;line-height:1.65}'
            '.ltx_title_abstract{font-size:1.3rem;font-weight:700;text-transform:none;letter-spacing:0}'
            '.ltx_cite{font-style:normal}.ltx_note_mark{font-style:normal}'
            '.ltx_title_keywords{font-size:1.3rem;font-weight:700}'
            '.reaper-zh-text{color:#2563eb;font-size:.92em}'
            '@media(prefers-color-scheme:dark){.reaper-zh-text{color:#60a5fa}}'
            '.ltx_page_footer,.ltx_page_logo,.ar5iv-footer{display:none!important}'
            '</style>'
        )
    html = html.replace('</head>', f'{core_css}\n{override_css}\n</head>', 1)

    # 5. Inject Chinese translations
    for i, b in enumerate(blocks_with_zh):
        zh = b.get("zh", "").strip()
        if not zh:
            continue
        # Footnote placeholders (FN_N) refer to <sup> marks already present in the
        # original HTML; drop them from the rendered Chinese text.
        zh = re.sub(r'\s*FN_\d+\s*', '', zh).strip()
        math_map = b.get("math_map", {})
        if math_map:
            zh = restore_math_in_translation(zh, math_map)
        inline = b.get("type") == "section"
        html = _inject_translation(html, i, zh, inline=inline)

    # 6. Embed paper metadata
    data_json = json.dumps({"paper_id": arxiv_id, "terms": term_dict or {}}, ensure_ascii=False)
    html = html.replace("</head>",
        f'<script id="reaper-data" type="reaper/metadata">{data_json}</script>\n</head>', 1)

    # 7. Inject source toggle JS (before </body>)
    html = html.replace('</body>', f'{_SOURCE_TOGGLE_JS}\n</body>', 1)

    return html


def save_html(html: str, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def zotero_compatible_html(html: str) -> str:
    """Convert <object> tags to <img> for Zotero internal browser compatibility.

    Zotero's embedded browser does not render <object> tags with data URIs.
    Call this before saving to the Zotero output directory.
    """
    html = re.sub(r'<object\b', '<img', html)
    html = re.sub(r' type="[^"]*"', '', html)
    html = html.replace(' data="', ' src="')
    return html