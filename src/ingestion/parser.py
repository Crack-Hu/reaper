"""ar5iv HTML parser v3 — mark + extract in one pass, guaranteeing 1:1 alignment.

Key design:
- Single unified regex matches h1(title)/hN(section)/p(paragraph) in DOM order
- Each match gets a data-reaper-id marker AND text extracted simultaneously
- Math blocks get numbered placeholders ⟨N⟩, with original HTML stored for post-translation restore
- This eliminates the alignment bug caused by separate parse+mark passes
"""

import re
from dataclasses import dataclass, field


@dataclass
class Block:
    """A translatable content block extracted from ar5iv HTML."""
    type: str           # "title" | "section" | "para" | "figcaption" | "note"
    text: str           # plain text with math replaced by ⟨N⟩ placeholders
    level: int = 0
    label: str = ""
    math_map: dict[str, str] = field(default_factory=dict)  # ⟨N⟩ → original math HTML

    def __repr__(self):
        preview = self.text[:60].replace("\n", " ") + ("..." if len(self.text) > 60 else "")
        return f"<Block {self.type} L{self.level} \"{preview}\">"


# Unified regex: matches h1 title, hN section headings, p paragraphs, figcaption, footnote content in one left-to-right pass
_TAG_PATTERN = re.compile(
    r'(<h1\b[^>]*class="[^"]*ltx_title_document[^"]*"[^>]*>)'       # title
    r'|(<h\d\b[^>]*class="[^"]*ltx_title_(?:sub)*section[^"]*"[^>]*>)' # section/subsection/subsubsection
    r'|(<p\b[^>]*class="[^"]*ltx_p[^"]*"[^>]*>)'                       # paragraph
    r'|(<figcaption\b[^>]*class="[^"]*ltx_caption[^"]*"[^>]*>)'       # figure caption
    r'|(<(?:span|div)\b[^>]*class="[^"]*ltx_note_content[^"]*"[^>]*>)' # footnote content
)

# Matches footnote content containers (the translatable part of a footnote)
_NOTE_PATTERN = re.compile(r'<(?:span|div)\b[^>]*class="[^"]*ltx_note_content[^"]*"[^>]*>')

# Matches the body container of a footnote (holds duplicate content nested in a paragraph)
_NOTE_OUTER_PATTERN = re.compile(r'<(?:span|div)\b[^>]*class="[^"]*ltx_note_outer[^"]*"[^>]*>')


def _strip_note_outer(inner_html: str) -> str:
    """Remove the full footnote body (ltx_note_outer...) from a text fragment.

    Footnotes are nested inside a paragraph in ar5iv HTML; without stripping the
    whole span, the footnote content would be duplicated in the paragraph text.
    """
    pieces = []
    pos = 0
    for m in _NOTE_OUTER_PATTERN.finditer(inner_html):
        end = _find_matching_close(inner_html, m.start())
        if end == -1:
            end = m.end()
        pieces.append(inner_html[pos:m.start()])
        pieces.append(" ")
        pos = end
    pieces.append(inner_html[pos:])
    return "".join(pieces)


def _find_note_ranges(html: str) -> list[tuple[int, int]]:
    """Locate (start, end) spans of all footnote content containers.

    Inner elements of a footnote (p, hN, ...) should not be marked separately,
    because the whole footnote is translated as one block.
    """
    ranges: list[tuple[int, int]] = []
    for note_m in _NOTE_PATTERN.finditer(html):
        start = note_m.start()
        end = _find_matching_close(html, start)
        if end > start:
            ranges.append((start, end))
    return ranges


def _find_matching_close(html: str, open_pos: int) -> int:
    """Given the '<' of an opening span/div tag, return index just past its matching close tag."""
    m = re.match(r'<(?:span|div)\b', html[open_pos:])
    if not m:
        return -1
    depth = 1
    pos = open_pos + m.end()
    while pos < len(html):
        nxt = re.search(r'<(/?)(?:span|div)\b', html[pos:])
        if not nxt:
            break
        nxt_pos = pos + nxt.start()
        if nxt.group(1) == '/':
            depth -= 1
            if depth == 0:
                close = html.find('>', nxt_pos)
                return close + 1 if close != -1 else -1
        else:
            depth += 1
        pos = nxt_pos + len(nxt.group(0))
    return -1


# For matching math blocks inside extracted inner HTML
_MATH_PATTERN = re.compile(r'<math\b.*?</math>', re.DOTALL)

# For stripping HTML tags (after removing footnotes and math)
_TAG_STRIP = re.compile(r'<[^>]+>')

# Footnote/superscript content to skip during text extraction
# Only strip the numeric markers, keep footnote body text for translation
_FOOTNOTE_STRIP = re.compile(
    r'<sup\b[^>]*class="[^"]*ltx_note_mark[^"]*"[^>]*>[^<]*</sup>'  # inline superscript number
    r'|<span\b[^>]*class="[^"]*ltx_tag_note[^"]*"[^>]*>[^<]*</span>'  # inner tag number
    , re.DOTALL
)


def _extract_text_with_placeholders(inner_html: str) -> tuple[str, dict[str, str]]:
    """Extract plain text from inner HTML fragment.

    <math>...</math> → MATH_N — restored in final output.
    <sup class="ltx_note_mark"> → FN_N — LLM-safe placeholder.
    <span class="ltx_note_outer">...</span> → removed (footnote body handled as its own note block).
    Other HTML tags stripped. Whitespace normalized.

    Returns (clean_text, math_map).
    """
    math_map: dict[str, str] = {}
    counter = [0]

    def replace_math(m: re.Match) -> str:
        key = f"MATH_{counter[0]}"
        math_map[key] = m.group(0)
        counter[0] += 1
        return key

    def replace_footnote(m: re.Match) -> str:
        key = f"FN_{counter[0]}"
        counter[0] += 1
        return f" {key} "

    text = _strip_note_outer(inner_html)
    text = _MATH_PATTERN.sub(replace_math, text)
    text = _FOOTNOTE_STRIP.sub(replace_footnote, text)
    text = _TAG_STRIP.sub(' ', text)
    text = ' '.join(text.split())
    return text, math_map


def mark_and_extract(html: str) -> tuple[str, list[Block]]:
    """Mark translatable elements AND extract their text in one deterministic pass.

    For each matched element (h1/h2-h6/p/figcaption/note) in DOM order:
    1. Insert data-reaper-id="N" marker into the opening tag
    2. Find the element's closing tag, extract inner HTML
    3. Compute plain text with MATH_N/FN_N placeholders
    4. Record the full text content of heading elements

    Footnote content (ltx_note_content) is extracted as a single "note" block;
    elements nested inside a footnote are not marked separately.

    Returns:
        (marked_html, blocks) — blocks[i] ↔ element with data-reaper-id="i"
    """
    blocks: list[Block] = []
    # Pass 0: footnote content spans — inner elements are not marked separately
    note_ranges = _find_note_ranges(html)
    # (the pass-2 loop below re-scans marked_html; rest of the body follows)
    # ---- Pass 1: mark all elements ----
    def tag_replacer(m: re.Match) -> str:
        idx = len(blocks)
        full_tag = m.group(0)
        # Skip elements nested inside footnote content (footnote handled as a whole)
        if any(start < m.start() < end for start, end in note_ranges):
            return full_tag

        # Determine type
        if 'ltx_title_document' in full_tag:
            btype, level = "title", 0
        elif 'ltx_title_subsubsection' in full_tag:
            btype, level = "section", 3
        elif 'ltx_title_subsection' in full_tag:
            btype, level = "section", 2
        elif 'ltx_title_section' in full_tag:
            btype, level = "section", 1
        elif 'ltx_note_content' in full_tag:
            btype, level = "note", 0
        elif 'ltx_caption' in full_tag:
            btype, level = "figcaption", 0
        else:
            btype, level = "para", 0

        tagged = full_tag.replace('>', f' data-reaper-id="{idx}">', 1)
        blocks.append(Block(type=btype, text="", level=level))
        return tagged

    marked_html = _TAG_PATTERN.sub(tag_replacer, html)
    # ---- Pass 2: extract text for each marked element ----
    # Re-scan marked_html for data-reaper-id markers to find element boundaries
    for idx in range(len(blocks)):
        marker = f'data-reaper-id="{idx}"'
        pos = marked_html.find(marker)
        if pos == -1:
            continue

        # Find start of this opening tag
        tag_beg = marked_html.rfind('<', 0, pos)
        if tag_beg == -1:
            continue

        # Determine tag name
        tag_end_bracket = marked_html.index('>', pos) + 1
        tag_match = re.match(r'<(\w+)', marked_html[tag_beg:])
        if not tag_match:
            continue
        tag_name = tag_match.group(1)
        close_tag = f'</{tag_name}>'

        # Find matching closing tag (handle nesting)
        depth = 0
        search_pos = tag_end_bracket
        close_pos = -1

        while search_pos < len(marked_html):
            next_open = marked_html.find(f'<{tag_name}', search_pos)
            next_close = marked_html.find(close_tag, search_pos)

            if next_close == -1:
                break

            # Skip self-closing and void elements
            if next_open != -1 and next_open < next_close:
                # Check if it's a real opening tag (not self-closing)
                gt_pos = marked_html.find('>', next_open)
                # If it's a real tag (has > and doesn't end with />)
                if 'class=' in marked_html[next_open:next_open + min(200, len(marked_html) - next_open)]:
                    depth += 1
                    search_pos = gt_pos + 1 if gt_pos != -1 else next_open + 1
                    continue
                else:
                    search_pos = next_open + 1
                    continue

            if depth > 0:
                depth -= 1
                search_pos = next_close + len(close_tag)
            else:
                close_pos = next_close
                break

        if close_pos == -1:
            continue

        # Extract inner HTML
        inner_html = marked_html[tag_end_bracket:close_pos]
        text, math_map = _extract_text_with_placeholders(inner_html)

        # Clean up
        if blocks[idx].type == "title":
            text = re.sub(r'†+thanks:.*$', '', text).strip()
        elif blocks[idx].type == "abstract":
            if text.lower().startswith("abstract"):
                text = text[len("abstract"):].strip()

        blocks[idx].text = text
        blocks[idx].math_map = math_map

        # Extract id attribute for section headings (used by TOC navigation)
        if blocks[idx].type in ("title", "section"):
            tag_text = marked_html[tag_beg:tag_end_bracket]
            id_match = re.search(r'(?<!data-reaper-)id="([^"]+)"', tag_text)
            if id_match:
                blocks[idx].label = id_match.group(1)

    return marked_html, blocks


def restore_math_in_translation(translation: str, math_map: dict[str, str]) -> str:
    """Replace MATH_0, MATH_1 placeholders with original math HTML.
    Also cleans up any stray braces LLM may have added around formulas."""
    result = translation
    # Sort by key length descending (MATH_10 before MATH_1)
    for key in sorted(math_map.keys(), key=len, reverse=True):
        math_html = math_map[key]
        result = result.replace(key, math_html)
    # Clean up stray braces that LLM may have added around math blocks
    result = re.sub(r'\{(<math\b)', r'\1', result)
    result = re.sub(r'(</math>)\}', r'\1', result)
    return result


def parse_blocks(html: str) -> list[Block]:
    """Convenience: extract blocks without marking HTML (for parse-only mode)."""
    _, blocks = mark_and_extract(html)
    return blocks
