"""Bilingual HTML renderer — translates ar5iv HTML into a self-contained Zotero attachment.

All external resources (CSS, images, fonts) are embedded inline.
No network access needed after generation.
"""

import base64
import json
import os
import re
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..ingestion.parser import restore_math_in_translation
from .. import config

AR5IV_BASE = "https://ar5iv.labs.arxiv.org"
UI_DIR = Path(__file__).parent / "ui"  # toc-sidebar.css, toc-toggle.js
CSS_CACHE = Path(__file__).parent.parent.parent / "data" / "css"  # data/css/
CSS_FILES = {
    "core": "/assets/ar5iv.0.8.5.css",
    "fonts": "/assets/ar5iv-fonts.0.8.4.css",
}
SITE_CSS = "/assets/ar5iv-site.0.2.2.css"  # removed — navigation chrome only

_IMG_PATTERN = re.compile(r'<img\b[^>]*src="([^"]+)"[^>]*>')
_CSS_LINK_PATTERN = re.compile(r'<link\b[^>]*href="([^"]*)"[^>]*>')
_BASE64_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml", ".gif": "image/gif"}


def _fetch(url: str) -> bytes:
    """Fetch a URL, return bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": "Reaper/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


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
    # Remove JS scripts only (navbar/TOC stays intact)
    html = re.sub(r'<script[^>]*addons_new[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*feedbackOverlay[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*html2canvas[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<link[^>]*latexml_styles[^>]*>', '', html)
    return html


def _inline_images(html: str, arxiv_id: str = "", source_type: str = "ar5iv") -> str:
    """Download images and embed as base64 data URIs.

    ar5iv/arxiv_html: download from CDN, cache to data/ar5iv/{id}/
    ar5ivist_docker: read from data/ar5ivist/{id}/
    """
    if source_type == "ar5ivist_docker":
        img_dir = Path(config.AR5IVIST_OUTPUT_DIR) / arxiv_id
    else:
        img_dir = Path(config.AR5IV_DIR) / arxiv_id

    url_to_b64 = {}
    urls = [u for u in set(_IMG_PATTERN.findall(html)) if not u.startswith("data:")]  # skip already-base64
    if not urls:
        print(f"        no external images to embed", flush=True)
        return html
    print(f"        embedding {len(urls)} images from {source_type} ...", flush=True)

    def download_one(url):
        try:
            # Resolve local or remote path
            if source_type == "ar5ivist_docker" or img_dir.exists():
                fname = url.split("/")[-1] if "/" in url else url
                local = img_dir / fname
                if local.exists():
                    ext = local.suffix.lower()
                    mime = _BASE64_MIME.get(ext, "image/png")
                    data = base64.b64encode(local.read_bytes()).decode()
                    return url, f"data:{mime};base64,{data}"
            # Resolve to absolute if needed (URL from HTML is already correct)
            if url.startswith("http"):
                full_url = url
            elif url.startswith("/"):
                domain = "https://arxiv.org" if source_type == "arxiv_html" else AR5IV_BASE
                full_url = domain + url
            else:
                domain = "https://arxiv.org" if source_type == "arxiv_html" else AR5IV_BASE
                full_url = f"{domain}/html/{arxiv_id}/{url}"
            ext = url.rsplit(".", 1)[-1].lower()
            mime = _BASE64_MIME.get("." + ext, "image/png")
            data = base64.b64encode(_fetch(full_url)).decode()
            # Cache to disk
            img_dir.mkdir(parents=True, exist_ok=True)
            fname = url.split("/")[-1]
            (img_dir / fname).write_bytes(base64.b64decode(data))
            return url, f"data:{mime};base64,{data}"
        except Exception:
            return url, url

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download_one, u) for u in urls]
        for f in as_completed(futures):
            url, b64 = f.result()
            url_to_b64[url] = b64

    embedded = sum(1 for v in url_to_b64.values() if v.startswith("data:"))
    print(f"        {embedded}/{len(urls)} embedded", flush=True)

    def replacer(m):
        src = m.group(1)
        new_src = url_to_b64.get(src, src)
        return m.group(0).replace(f'src="{src}"', f'src="{new_src}"')

    return _IMG_PATTERN.sub(replacer, html)


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
    pattern = re.compile(
        rf'(<(\w+)\b[^>]*{re.escape(marker)}[^>]*>.*?)(</\2\s*>)',
        re.DOTALL
    )

    def replacer(m):
        inner, close = m.group(1), m.group(3)
        if 'reaper-zh' in inner + close:
            return m.group(0)
        return inner + wrapper + close

    return pattern.sub(replacer, html, count=1)


# === Main ===

def render_bilingual_html(
    marked_html: str,
    blocks_with_zh: list[dict],
    term_dict: dict[str, str] | None = None,
    arxiv_id: str = "",
    embed_images: bool = True,
    source_type: str = "ar5iv",
) -> str:
    """Generate bilingual HTML.

    embed_images=True:  base64 inline images (offline, ~10MB)
    embed_images=False: images load from CDN (needs network, ~2MB)
    source_type: "ar5iv"|"arxiv_html"|"ar5ivist_docker"|"cache"
    """
    html = marked_html
    is_arxiv = (source_type == "arxiv_html" or
                (source_type == "cache" and "ltx_page_navbar" in marked_html))

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

    # 3. Images: embed or fix paths to absolute
    if embed_images:
        html = _inline_images(html, arxiv_id, source_type)
    else:
        # Fix relative image paths to absolute for standalone HTML
        if source_type == "arxiv_html":
            html = html.replace('src="/', 'src="https://arxiv.org/')
        else:
            html = html.replace('src="/', f'src="{AR5IV_BASE}/')

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
        math_map = b.get("math_map", {})
        if math_map:
            zh = restore_math_in_translation(zh, math_map)
        inline = b.get("type") == "section"
        html = _inject_translation(html, i, zh, inline=inline)

    # 6. Embed paper metadata
    data_json = json.dumps({"paper_id": arxiv_id, "terms": term_dict or {}}, ensure_ascii=False)
    html = html.replace("</head>",
        f'<script id="reaper-data" type="reaper/metadata">{data_json}</script>\n</head>', 1)

    return html


def save_html(html: str, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path
