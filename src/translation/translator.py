"""LLM Translation — section-by-section with abstract context + concurrent + auto terms"""

import re
import json
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from .. import config
from .dictionary import TermDictionary
from ..ingestion.parser import Block
from . import cache as translation_cache

SYSTEM_PROMPT = '''You are a professional academic translator specializing in scientific papers.
Your task is to translate English academic text into accurate, fluent, and natural Chinese.

CRITICAL RULES:
1. Preserve ALL MATH_0, MATH_1, MATH_2 and FN_0, FN_1, FN_2 etc. placeholders EXACTLY as-is.
2. Preserve ALL citations like [1], [2,3,4], [5, p.23]
3. Preserve figure/table references like "Fig. 1", "Figure 2", "Table 3"
4. Preserve proper nouns: person names, algorithm names, software names
5. Maintain the academic tone — use formal, precise Chinese
6. Translate naturally — the result should read like it was originally written in Chinese
7. Do NOT add explanations, notes, or commentary

OUTPUT FORMAT:
- Use REAPER_PARA_N as separator before each paragraph translation
- After all paragraphs, add REAPER_TERMS section with newly discovered terminology
- Example:
  REAPER_PARA_1
  (translation of paragraph 1)
  REAPER_PARA_2
  (translation of paragraph 2)
  REAPER_TERMS
  "english term" -> "Chinese term"
  "another term" -> "another Chinese term"'''

REAPER_PARA_RE = re.compile(r'REAPER_PARA_(\d+)\s*\n(.*?)(?=REAPER_PARA_|REAPER_TERMS|$)', re.DOTALL)
REAPER_TERMS_RE = re.compile(r'REAPER_TERMS\s*\n(.+)$', re.DOTALL)
TERM_LINE_RE = re.compile(r'"(.+?)"\s*→\s*"(.+?)"')

MAX_SECTION_CHARS = 10000  # ~3000 tokens, leaves room for context + response


def build_section_prompt(heading, paragraphs, paper_title, abstract_text, term_dict,
                         part_info="", shared_label="", is_first=True):
    """Build user prompt for one section (or sub-part)."""
    parts = [f"PAPER TITLE: {paper_title}", ""]
    if abstract_text:
        parts.append(f"ABSTRACT: {abstract_text}")
        parts.append("")
    if term_dict:
        parts.append("KEY TERMINOLOGY (use these translations consistently):")
        for en, zh in sorted(term_dict.items(), key=lambda x: -len(x[0])):
            parts.append(f'  "{en}" → "{zh}"')
        parts.append("")

    heading_label = heading or "Front Matter"
    if part_info:
        heading_label += f" ({part_info})"
    parts.append(f"SECTION: {heading_label}")
    if shared_label:
        parts.append(f"[CONTEXT: this paragraph {shared_label}]")
    parts.append("")

    if len(paragraphs) == 1:
        parts.append("Translate this paragraph:")
        parts.append("")
        parts.append(f"REAPER_PARA_1")
        parts.append(paragraphs[0].text)
    else:
        parts.append(f"Translate these {len(paragraphs)} paragraphs.")
        parts.append("")
        for i, b in enumerate(paragraphs, 1):
            parts.append(f"REAPER_PARA_{i}")
            parts.append(b.text)
            parts.append("")

    return "\n".join(parts)


def call_llm_api(system_prompt, user_prompt, api_key="", base_url="", model="", temperature=0.1):
    key = api_key or config.LLM_API_KEY
    url = base_url or config.LLM_BASE_URL
    model_name = model or config.LLM_MODEL
    if not key:
        raise RuntimeError("No API key configured. Set key in config.json.")

    import time
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = httpx.post(
                f"{url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model_name, "temperature": temperature, "max_tokens": 4096,
                       "messages": [{"role": "system", "content": system_prompt},
                                     {"role": "user", "content": user_prompt}]},
                timeout=300,
            )
            resp.raise_for_status()
            text = resp.text.strip()
            try:
                body = json.loads(text)
                content = body["choices"][0]["message"]["content"]
                if content is None or not content.strip():
                    print(f"      ⚠ API returned empty content", flush=True)
                    print(f"      raw (first 500): {text[:500]}", flush=True)
                    raise ValueError("API returned empty content")
                return content.strip()
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                print(f"      ⚠ API response parse error: {e}", flush=True)
                print(f"      raw (first 500): {text[:500]}", flush=True)
                raise
        except Exception as e:
            if attempt < max_retries:
                print(f"      ⚠ API call failed (attempt {attempt+1}/{max_retries+1}): {e}", flush=True)
                print(f"      retrying ...", flush=True)
            else:
                raise


def group_blocks_by_section(blocks):
    """Group blocks into sections by heading boundaries.

    Returns (abstract_text, [{heading, paragraphs: [Block]}]).
    abstract_text: all blocks before first section heading.
    """
    sections = []
    abstract_parts = []
    current = None
    in_abstract = True

    for b in blocks:
        is_heading = (b.type == "title" and b.level >= 1) or b.type == "section"
        if is_heading:
            in_abstract = False
            if current:
                sections.append(current)
            current = {"heading": b.text, "paragraphs": []}
        elif in_abstract:
            if b.text.strip():
                abstract_parts.append(b.text)
            if current is None:
                current = {"heading": "", "paragraphs": []}
            current["paragraphs"].append(b)  # also add to current section
        elif current is not None:
            current["paragraphs"].append(b)

    if current and current["paragraphs"]:
        sections.append(current)

    # If no sections created, make one "body" section from all non-title blocks
    if not sections:
        body_paras = [b for b in blocks if b.type != "title" and b.text.strip()]
        if body_paras:
            sections = [{"heading": "", "paragraphs": body_paras}]

    return " ".join(abstract_parts), sections


def _split_long_section(heading, paragraphs, abstract_text, paper_title, term_dict,
                        max_chars=MAX_SECTION_CHARS):
    """Split into balanced sub-parts at paragraph boundaries.

    Uses closest-to-target heuristic so each part is roughly equal size.
    Adjacent parts share 1 overlapping paragraph for continuity.
    """
    total = sum(len(b.text) for b in paragraphs)
    if total <= max_chars:
        return [{"heading": heading, "part_info": "", "paragraphs": list(paragraphs), "shared_label": ""}]

    num_parts = (total + max_chars - 1) // max_chars
    target = total / num_parts

    # ── balanced greedy: split at paragraph boundary closest to target ──
    batches = []
    current_chars = 0
    current_batch = []

    for b in paragraphs:
        gap_stop = abs(current_chars - target)
        gap_add = abs(current_chars + len(b.text) - target)

        if current_chars > 0 and gap_stop <= gap_add:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(b)
        current_chars += len(b.text)

    if current_batch:
        batches.append(current_batch)

    # ── wrap into part dicts with overlap ──
    parts = []
    for i, batch in enumerate(batches):
        shared_label = ""
        if i > 0:
            # Insert overlap: first paragraph of this batch = last of previous
            prev_last = parts[-1]["paragraphs"][-1]
            batch.insert(0, prev_last)
            shared_label = f"appears in both part {i} and part {i+1}"
            parts[-1]["shared_label"] = f"appears in both part {i} and part {i+1}"

        parts.append({
            "heading": heading,
            "part_info": f"part {i+1}/{len(batches)}",
            "paragraphs": batch,
            "shared_label": shared_label,
        })

    return parts


def _parse_llm_response(response, num_expected):
    """Parse REAPER_PARA_N blocks and REAPER_TERMS from LLM response.

    Returns ({para_num: translation}, {en: zh_terms}).
    """
    translations = {}
    terms = {}

    for match in REAPER_PARA_RE.finditer(response):
        num = int(match.group(1))
        zh = match.group(2).strip()
        if zh:
            translations[num] = zh

    terms_match = REAPER_TERMS_RE.search(response)
    if terms_match:
        for line in terms_match.group(1).strip().split("\n"):
            m = TERM_LINE_RE.search(line)
            if m:
                terms[m.group(1).strip()] = m.group(2).strip()

    return translations, terms


def _translate_one_section(args):
    """Worker: translate one section (or sub-part). Called by thread pool."""
    (sec_idx, total_secs, heading, part_info, paragraphs, shared_label,
     paper_title, abstract_text, term_dict, api_key, base_url, model, paper_id,
     block_index_map, num_paras, progress_counter, cache) = args

    SKIP_TYPES = {"figure", "table", "equation"}
    translatable = [(i, b) for i, b in enumerate(paragraphs)
                    if b.type not in SKIP_TYPES and len(b.text) >= 10]

    if not translatable:
        print(f"      ({sec_idx}/{total_secs}) {heading[:50]} — 0 translatable, skipped")
        return sec_idx, {}, {}

    label = f"({sec_idx}/{total_secs})"
    heading_short = heading[:50] if heading else "Front Matter"
    part_tag = f" ({part_info})" if part_info else ""
    # Add 5 spaces before label to align ( with done lines' pct column
    print(f"      {' '*5}{label} {heading_short}{part_tag} — sending {len(translatable)} paras ...", flush=True)

    user_prompt = build_section_prompt(
        heading, [b for _, b in translatable],
        paper_title, abstract_text, term_dict.flattened,
        part_info, shared_label,
    )

    try:
        response = call_llm_api(SYSTEM_PROMPT, user_prompt, api_key, base_url, model)
    except Exception as e:
        print(f"      {label} {heading_short}{part_tag} FAILED: {e}")
        return sec_idx, {}, {}

    translations, terms = _parse_llm_response(response, len(translatable))

    # Map paragraph numbers back to block indices
    result = {}
    for para_num, zh in translations.items():
        if 1 <= para_num <= len(translatable):
            orig_block_idx = block_index_map.get(id(paragraphs[translatable[para_num-1][0]]), -1)
            if orig_block_idx >= 0:
                if orig_block_idx not in result:
                    result[orig_block_idx] = zh
                    if cache is not None:
                        cache.put_zh(paragraphs[translatable[para_num-1][0]].text, zh)
                    elif paper_id:
                        translation_cache.put(paper_id, paragraphs[translatable[para_num-1][0]].text, zh)

    term_count = len(terms)
    term_info = f", +{term_count} terms" if term_count else ""
    # Thread-safe progress update
    cum_done = len(result)
    if progress_counter is not None:
        with progress_counter["lock"]:
            progress_counter["done"] += len(result)
            cum_done = progress_counter["done"]
    pct = f"{cum_done/progress_counter['total']*100:.0f}%" if progress_counter and progress_counter['total'] else ""
    # Done: pct right-aligned in 4 chars, then task ID, so ( aligns across all lines
    if cum_done > 0:
        print(f"      {pct:>4s} ({sec_idx}/{total_secs}) {heading_short}{part_tag} — {len(result)} paras done{term_info}")
    return sec_idx, result, terms


def _translate_by_sections(blocks, results, paper_title, term_dict, api_key, base_url, model, paper_id, cache_hits, executor=None, cache=None):
    SKIP_TYPES = {"figure", "table", "equation"}
    print(f"      Grouping sections ...", flush=True)
    abstract_text, sections = group_blocks_by_section(blocks)
    print(f"      {len(sections)} sections, building index ...", flush=True)

    block_to_idx = {}
    for i, b in enumerate(blocks):
        block_to_idx[id(b)] = i

    def _idx(b):
        return block_to_idx.get(id(b), -1)

    uncached = 0
    for s in sections:
        for b in s["paragraphs"]:
            idx = _idx(b)
            if idx >= 0 and b.type not in SKIP_TYPES and len(b.text) >= 10 and not results[idx]["zh"]:
                uncached += 1

    print(f"      Cache hits: {cache_hits}, remaining: {uncached} uncached paras across {len(sections)} sections", flush=True)
    if uncached == 0:
        return

    # Step 1: build flat list of (section_idx, block_idx, Block) for all uncached blocks
    import threading
    flat_uncached = []  # [(para_num, block_idx, Block)]
    para_num = 1
    for s in sections:
        for b in s["paragraphs"]:
            idx = _idx(b)
            if idx >= 0 and b.type not in SKIP_TYPES and len(b.text) >= 10 and not results[idx]["zh"]:
                flat_uncached.append((para_num, idx, b, s))
                para_num += 1

    # Step 2: group into batches by section, splitting long ones
    work_items = []
    batch = []
    current_section = None
    current_chars = 0
    total_new = 0

    for pnum, idx, b, s in flat_uncached:
        if current_section is not None and s["heading"] != current_section:
            # Flush previous section's batch
            work_items.append(list(batch))
            batch = []
            current_chars = 0
        current_section = s["heading"]
        batch.append((pnum, idx, b, s))
        current_chars += len(b.text)

        # Split if batch exceeds max_chars (balanced: start new batch at paragraph boundary)
        if current_chars > MAX_SECTION_CHARS and len(batch) > 1:
            batch.pop()  # remove last para, keep for next batch
            work_items.append(list(batch))
            batch = [batch.pop()] if False else [(pnum, idx, b, s)]
            current_chars = len(b.text)

    if batch:
        work_items.append(batch)

    total_work = len(work_items)

    # Step 3: convert batches to full work_item tuples
    progress_counter = {"done": cache_hits, "total": cache_hits + uncached, "lock": threading.Lock()}
    full_items = []
    for wi, batch in enumerate(work_items):
        total_new += len(batch)
        heading = batch[0][3]["heading"] if batch else ""
        paras = [b for _, _, b, _ in batch]
        block_map = {}
        for _, idx, b, _ in batch:
            block_map[id(b)] = idx
        full_items.append((
            wi + 1, total_work, heading, f"part {wi+1}/{total_work}",
            paras, "", paper_title, abstract_text, term_dict,
            api_key, base_url, model, paper_id, block_map, len(batch), progress_counter, cache,
        ))

    if total_work == 0:
        return

    print(f"      Plan: {total_work} task(s) ({total_new} new + {cache_hits} cached = {cache_hits+uncached} total), pool size {config.TRANSLATION_CONCURRENCY}", flush=True)
    # Per-section stats for logging
    section_stats = {}  # heading -> (total_translatable, cached, uncached)
    for s in sections:
        heading = s["heading"]
        total = 0
        cached_cnt = 0
        for b in s["paragraphs"]:
            idx = _idx(b)
            if idx >= 0 and b.type not in SKIP_TYPES and len(b.text) >= 10:
                total += 1
                if results[idx].get("zh"):
                    cached_cnt += 1
        section_stats[heading] = (total, cached_cnt, total - cached_cnt)

    for i in range(total_work):
        w = full_items[i]
        heading = w[2]
        label = heading[:60]
        if w[3]:
            label += f" ({w[3]})"
        batch_size = w[14]
        total_t, cached_t, _ = section_stats.get(heading, (0, 0, 0))
        print(f"        ({i+1}) {label} — {batch_size} to translate, {cached_t}/{total_t} cached", flush=True)

    print(f"      Starting concurrent ...", flush=True)
    own_pool = (executor is None)
    if own_pool:
        executor = ThreadPoolExecutor(max_workers=config.TRANSLATION_CONCURRENCY)

    futures = {executor.submit(_translate_one_section, w): w[0] for w in full_items}
    for future in as_completed(futures):
        sec_idx, r, t = future.result()
        for block_idx, zh in r.items():
            results[block_idx]["zh"] = zh
        if t:
            term_dict.add_llm_terms(t)

    if own_pool:
        executor.shutdown(wait=True)

    translated = sum(1 for r in results if r["zh"] and r["zh"] != r["en"])
    print(f"      Done: {translated} blocks translated", flush=True)


def _translate_in_batches(blocks, results, paper_title, term_dict, api_key, base_url, model, batch_size, paper_id, cache_hits, cache=None):
    """Legacy fixed-size batch mode."""
    SKIP_TYPES = {"figure", "table", "equation"}
    uncached = [(i, blocks[i]) for i in range(len(blocks))
                if blocks[i].type not in SKIP_TYPES and len(blocks[i].text) >= 10
                and not results[i]["zh"]]

    if cache_hits:
        print(f"  Cache hits: {cache_hits}, remaining: {len(uncached)}")
    if not uncached:
        return

    previous_zh = ""
    for batch_start in range(0, len(uncached), batch_size):
        batch = uncached[batch_start:batch_start + batch_size]
        batch_blocks = [b for _, b in batch]

        parts = [f"PAPER TITLE: {paper_title}", ""]
        if term_dict.all_terms:
            parts.append("KEY TERMINOLOGY:")
            for en, zh in sorted(term_dict.all_terms.items(), key=lambda x: -len(x[0])):
                parts.append(f'  "{en}" → "{zh}"')
            parts.append("")
        if previous_zh:
            parts.append(f"[PREVIOUS CONTEXT]: {previous_zh}")
            parts.append("")

        parts.append(f"Translate {len(batch_blocks)} paragraphs. Use REAPER_PARA_N separators.")
        parts.append("")
        for i, b in enumerate(batch_blocks, 1):
            parts.append(f"REAPER_PARA_{i}")
            parts.append(b.text)
            parts.append("")

        user_prompt = "\n".join(parts)

        try:
            response = call_llm_api(SYSTEM_PROMPT, user_prompt, api_key, base_url, model)
            translations, terms = _parse_llm_response(response, len(batch_blocks))
            for para_num, zh in translations.items():
                if 1 <= para_num <= len(batch):
                    idx = batch[para_num - 1][0]
                    results[idx]["zh"] = zh
                    if cache is not None:
                        cache.put_zh(blocks[idx].text, zh)
                    elif paper_id:
                        translation_cache.put(paper_id, blocks[idx].text, zh)
            previous_zh = translations.get(len(batch_blocks), "")
            if terms:
                term_dict.add_llm_terms(terms)
        except Exception as e:
            print(f"  Batch {batch_start // batch_size + 1} failed: {e}")

        print(f"  Batch {batch_start // batch_size + 1}: {len(batch)} paras")


def translate_blocks(blocks, term_dict=None, api_key="", base_url="", model="",
                     batch_size=0, paper_id="", executor=None, cache=None):
    """Translate parsed blocks.

    batch_size > 0: legacy fixed-size batch mode.
    batch_size = 0 (default): section-by-section with abstract context + concurrent.
    executor: shared ThreadPoolExecutor from server. If None, creates local pool.
    """
    term_dict = term_dict or TermDictionary()
    SKIP_TYPES = {"figure", "table", "equation"}

    paper_title = ""
    for b in blocks:
        if b.type == "title" and b.level == 0:
            paper_title = b.text
            break

    results = [{"en": b.text, "zh": "", "type": b.type, "level": b.level, "label": b.label}
               for b in blocks]

    cache_hits = 0
    if paper_id or cache is not None:
        for i, b in enumerate(blocks):
            if b.type in SKIP_TYPES or len(b.text) < 10:
                continue
            if cache is not None:
                cached = cache.get_zh(b.text)
            else:
                cached = translation_cache.get(paper_id, b.text)
            if cached:
                results[i]["zh"] = cached
                cache_hits += 1

    try:
        if batch_size > 0:
            _translate_in_batches(blocks, results, paper_title, term_dict,
                                  api_key, base_url, model, batch_size, paper_id, cache_hits, cache=cache)
        else:
            _translate_by_sections(blocks, results, paper_title, term_dict,
                                   api_key, base_url, model, paper_id, cache_hits, executor, cache=cache)
    except Exception as e:
        print(f"  ✗ translate_blocks FAILED: {e}", flush=True)
        raise

    return results


def translate_text(text, term_dict=None, api_key="", base_url="", model=""):
    """Convenience: translate a single text string."""
    term_dict = term_dict or TermDictionary()
    user_prompt = build_section_prompt("", [Block(type="para", text=text, level=0)],
                                       "", "", term_dict.flattened)
    return call_llm_api(SYSTEM_PROMPT, user_prompt, api_key, base_url, model)
