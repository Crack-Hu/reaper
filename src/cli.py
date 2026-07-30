"""Reaper CLI — 科研文章阅读工程"""

import sys
import os
import argparse

from . import (
    fetch_html,
    mark_and_extract,
    parse_blocks,
    translate_blocks,
    TermDictionary,
    render_bilingual_html,
    save_html,
    config,
)


def main():
    parser = argparse.ArgumentParser(
        description="Reaper — 科研文章阅读工程 (arxiv → 中英对照HTML)"
    )
    parser.add_argument("input", help="arxiv ID (如 1907.11157) 或 arxiv URL")
    parser.add_argument("--dict", "-d", default=config.DEFAULT_DICT_PATH,
                        help="术语字典 JSON 路径")
    parser.add_argument("--output", "-o", help="输出 HTML 路径")
    parser.add_argument("--no-translate", action="store_true", help="跳过翻译")
    parser.add_argument("--only-parse", action="store_true", help="仅解析并打印段落")
    parser.add_argument("--api-key", default=config.LLM_API_KEY, help="LLM API Key")
    parser.add_argument("--model", default=config.LLM_MODEL, help="模型名称")
    parser.add_argument("--base-url", default=config.LLM_BASE_URL, help="API Base URL")

    args = parser.parse_args()

    # Step 1: Fetch
    print(f"[1/4] 获取 ar5iv HTML ...")
    try:
        arxiv_id, ar5iv_html = fetch_html(args.input)
        print(f"  ✓ 文章 ID: {arxiv_id}, HTML 大小: {len(ar5iv_html):,} bytes")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")
        sys.exit(1)

    # Step 2: Mark + Extract
    print(f"[2/4] 标记并提取段落 ...")
    marked_html, blocks = mark_and_extract(ar5iv_html)
    print(f"  ✓ 共 {len(blocks)} 个可翻译块")

    if not args.only_parse:
        for b in blocks:
            preview = b.text[:80].replace("\n", " ") + ("..." if len(b.text) > 80 else "")
            math_note = f" [{len(b.math_map)} math]" if b.math_map else ""
            print(f"    [{b.type:8s} L{b.level}]{math_note} {preview}")

    if args.only_parse:
        return

    # Step 3: Translate
    term_dict = TermDictionary(args.dict)
    if args.no_translate:
        print(f"[3/4] 跳过翻译 (--no-translate)")
        translated = [{"en": b.text, "zh": "", "type": b.type, "level": b.level,
                        "label": b.label, "math_map": b.math_map} for b in blocks]
    else:
        print(f"[3/4] 翻译中 (模型: {args.model}) ...")
        print(f"  ✓ 加载术语字典: {len(term_dict)} 条")
        try:
            translated_raw = translate_blocks(
                blocks, term_dict=term_dict,
                api_key=args.api_key, model=args.model, base_url=args.base_url,
                paper_id=arxiv_id,
            )
            translated = []
            for i, t in enumerate(translated_raw):
                t["math_map"] = blocks[i].math_map if i < len(blocks) else {}
                translated.append(t)
            cnt = sum(1 for t in translated if t["zh"] and t["zh"] != t["en"])
            print(f"  ✓ 翻译完成: {cnt} 段已翻译")
        except Exception as e:
            print(f"  ✗ 翻译失败: {e}")
            print(f"  将生成无翻译的 HTML ...")
            translated = [{"en": b.text, "zh": "", "type": b.type, "level": b.level,
                            "label": b.label, "math_map": b.math_map} for b in blocks]

    # Step 4: Render
    print(f"[4/4] 渲染双语 HTML ...")
    output_path = args.output or os.path.join(config.OUTPUT_DIR, f"{arxiv_id}.html")

    html_output = render_bilingual_html(
        marked_html=marked_html,
        blocks_with_zh=translated,
        term_dict=term_dict.all_terms,
        arxiv_id=arxiv_id,
    )
    saved = save_html(html_output, output_path)
    print(f"  ✓ 已保存: {saved}")
    print(f"\n🎉 完成! 用浏览器打开: file://{os.path.abspath(saved)}")


if __name__ == "__main__":
    main()
