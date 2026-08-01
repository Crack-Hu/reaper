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
    type: str           # "title" | "section" | "para"
    text: str           # plain text with math replaced by ⟨N⟩ placeholders
    level: int = 0
    label: str = ""
    math_map: dict[str, str] = field(default_factory=dict)  # ⟨N⟩ → original math HTML

    def __repr__(self):
        preview = self.text[:60].replace("\n", " ") + ("..." if len(self.text) > 60 else "")
        return f"<Block {self.type} L{self.level} \"{preview}\">"


# Unified regex: matches h1 title, hN section headings, p paragraphs, figcaption in one left-to-right pass
_TAG_PATTERN = re.compile(
    r'(<h1\b[^>]*class="[^"]*ltx_title_document[^"]*"[^>]*>)'       # title
    r'|(<h\d\b[^>]*class="[^"]*ltx_title_(?:sub)*section[^"]*"[^>]*>)' # section/subsection/subsubsection
    r'|(<p\b[^>]*class="[^"]*ltx_p[^"]*"[^>]*>)'                       # paragraph
    r'|(<figcaption\b[^>]*class="[^"]*ltx_caption[^"]*"[^>]*>)',       # figure caption
)

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

    text = _MATH_PATTERN.sub(replace_math, inner_html)
    text = _FOOTNOTE_STRIP.sub(replace_footnote, text)
    text = _TAG_STRIP.sub(' ', text)
    text = ' '.join(text.split())
    return text, math_map


def mark_and_extract(html: str) -> tuple[str, list[Block]]:
    """Mark translatable elements AND extract their text in one deterministic pass.

    For each matched element (h1/h2-h6/p) in DOM order:
    1. Insert data-reaper-id="N" marker into the opening tag
    2. Find the element's closing tag, extract inner HTML
    3. Compute plain text with ⟨N⟩ math placeholders
    4. Also record the full text content of heading elements

    Returns:
        (marked_html, blocks) — blocks[i] ↔ element with data-reaper-id="i"
    """
    blocks: list[Block] = []
    positions: list[tuple[int, int, int]] = []  # (tag_start, inner_start, close_end)

    # ---- Pass 1: mark all elements ----
    def tag_replacer(m: re.Match) -> str:
        idx = len(blocks)
        full_tag = m.group(0)
        tag_start = m.start()

        # Determine type
        if 'ltx_title_document' in full_tag:
            btype, level = "title", 0
        elif 'ltx_title_subsubsection' in full_tag:
            btype, level = "section", 3
        elif 'ltx_title_subsection' in full_tag:
            btype, level = "section", 2
        elif 'ltx_title_section' in full_tag:
            btype, level = "section", 1
        elif 'ltx_caption' in full_tag:
            btype, level = "figcaption", 0
        else:
            btype, level = "para", 0

        tagged = full_tag.replace('>', f' data-reaper-id="{idx}">', 1)
        # Record tentative position (will be adjusted after full marking)
        blocks.append(Block(type=btype, text="", level=level))

        # Store the match position so pass 2 can locate this element
        # We'll re-scan marked_html to find positions after all replacements
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
