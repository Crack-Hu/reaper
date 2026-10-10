#!/usr/bin/env python3
"""Make a downloaded arXiv LaTeX source LaTeXML-friendly (for the ar5ivist source).

Why this exists
---------------
LaTeXML cannot digest qcircuit/Xy-pic diagrams: every ``_``/``^`` inside a
``\\Qcircuit`` body is reported as *"Script ... can only appear in math mode"*.
After 100 errors LaTeXML aborts with ``Fatal:too_many_errors`` and writes an
**empty** HTML stub (title "Untitled Document"), so the whole paper fails to
convert. Reproduced with arXiv:2111.05176 (a 100-page VQE review full of
circuit diagrams).

Replacing each ``\\Qcircuit ... { ... }`` diagram with a one-line placeholder
drops the error count far below the cap, so the conversion completes and the
rest of the paper (text, equations, captions, bibliography) renders normally.
The figure captions live *outside* the diagram bodies, so they survive.

The document class of such submissions often is Elsevier's ``cas-sc``, which
LaTeXML does not know either (it falls back to OmniBus), leaving a couple of
CAS-only macros undefined. This tool also inserts ``\\providecommand`` shims
for the ones we have seen (``\\cortext``, ``\\sep``).

Usage
-----
    python3 tools/fix_latexml_source.py <source_dir>            # dry-run
    python3 tools/fix_latexml_source.py <source_dir> --apply    # write .bak + edit

Files are edited in place; the first ``--apply`` run keeps a ``<name>.tex.bak``
copy next to each modified file. Re-running the tool is a no-op once the
diagrams are gone. After patching, re-run the generation (or the docker
command) for that paper — Reaper reuses the extracted source, it does not
re-download it unless you clear the cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PLACEHOLDER = r"\mbox{[circuit diagram omitted]}"

# Macros that only the (unknown-to-LaTeXML) document class defines.
SHIMS = r"""
% [Reaper] LaTeXML shims for macros defined by the original document class
% (cas-sc is unknown to LaTeXML, which falls back to OmniBus).
\providecommand{\cortext}[2][]{#2}
\providecommand{\sep}{\textbar\ }
""".strip("\n")

SHIM_MARK = "[Reaper] LaTeXML shims"


def find_qcircuit_spans(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` spans of ``\\Qcircuit ... { ... }`` constructs.

    ``start`` is the backslash of ``\\Qcircuit``; ``end`` is one past the brace
    that closes the diagram body. Commented-out occurrences (``% \\Qcircuit``)
    are ignored, and comments inside the body are skipped while scanning.
    """
    spans: list[tuple[int, int]] = []
    for m in _iter_commands(text, "Qcircuit"):
        # Skip occurrences on a commented-out line.
        line_start = text.rfind("\n", 0, m) + 1
        head = text[line_start:m]
        if _uncommented(head).find("%") != -1:
            continue
        brace = text.find("{", m)
        if brace == -1:
            continue
        end = _matching_brace(text, brace)
        if end == -1:
            continue
        spans.append((m, end + 1))
    return spans


def _iter_commands(text: str, name: str):
    """Yield indexes of ``\\name`` that are not part of a longer control word."""
    needle = "\\" + name
    start = 0
    while True:
        i = text.find(needle, start)
        if i == -1:
            return
        after = i + len(needle)
        if after >= len(text) or not (text[after].isalpha()):
            yield i
        start = after


def _uncommented(text: str) -> str:
    """Drop everything after an unescaped ``%`` (for a single line)."""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "%":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def _matching_brace(text: str, open_idx: int) -> int:
    """Index of the brace closing the one at ``open_idx``, or -1."""
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2                      # escaped char, e.g. \{ \} \%
            continue
        if ch == "%":
            nl = text.find("\n", i)
            if nl == -1:
                return -1
            i = nl + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def strip_qcircuit(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Replace every ``\\Qcircuit`` diagram body with a placeholder."""
    spans = find_qcircuit_spans(text)
    if not spans:
        return text, []
    out = []
    prev = 0
    for start, end in spans:
        out.append(text[prev:start])
        out.append(PLACEHOLDER)
        prev = end
    out.append(text[prev:])
    return "".join(out), spans


def insert_shims(text: str) -> tuple[str, bool]:
    """Insert ``\\providecommand`` shims right after ``\\documentclass{...}``."""
    if SHIM_MARK in text:
        return text, False
    m = None
    for candidate in _iter_commands(text, "documentclass"):
        m = candidate
        break
    if m is None:
        return text, False
    line_end = text.find("\n", m)
    if line_end == -1:
        return text, False
    return text[: line_end + 1] + SHIMS + "\n" + text[line_end + 1 :], True


def brace_balance(text: str) -> int:
    """Number of unclosed ``{`` (comments and escapes ignored)."""
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "%":
            nl = text.find("\n", i)
            i = len(text) if nl == -1 else nl + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return depth


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source_dir", help="directory with the extracted arXiv LaTeX source")
    ap.add_argument("--apply", action="store_true", help="write changes (keeps .bak files); default is dry-run")
    args = ap.parse_args()

    root = Path(args.source_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    tex_files = sorted(root.rglob("*.tex"))
    if not tex_files:
        print(f"no .tex files under {root}", file=sys.stderr)
        return 2

    # The shims go into the file that actually gets compiled — same preference
    # as `fetcher._download_arxiv_source()`: `main.tex`, else the first file
    # with a `\begin{document}`.
    main_file = root / "main.tex"
    if not main_file.exists():
        main_file = next((f for f in tex_files if "\\begin{document}" in
                          f.read_text(encoding="utf-8", errors="ignore")), None)
    print(f"main file: {main_file.relative_to(root) if main_file else '(not found)'}\n")

    changed = total_spans = 0
    for f in tex_files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        new, spans = strip_qcircuit(text)
        line = lambda i: text.count("\n", 0, i) + 1          # noqa: E731
        if spans:
            print(f"[qcircuit] {f.relative_to(root)}: {len(spans)} diagram(s) "
                  f"at lines {', '.join(str(line(s)) for s, _ in spans)}")

        shimmed = False
        if main_file is not None and f == main_file:
            new, shimmed = insert_shims(new)
            if shimmed:
                print(f"[shims]    {f.relative_to(root)}: \\providecommand for \\cortext / \\sep")

        if new != text:
            changed += 1
            total_spans += len(spans)
            if args.apply:
                bak = f.with_suffix(f.suffix + ".bak")
                if not bak.exists():
                    bak.write_text(text, encoding="utf-8")
                f.write_text(new, encoding="utf-8")
            balance = brace_balance(new)
            left = new.count("\\Qcircuit") - new.count("% \\Qcircuit")
            print(f"           -> {'written' if args.apply else 'would write'}"
                  f"; remaining \\Qcircuit: {left}; brace balance: {balance}")

    verb = "changed" if args.apply else "would change"
    print(f"\n{changed} file(s) {verb}, {total_spans} diagram(s) replaced")
    if changed and not args.apply:
        print("dry-run only — re-run with --apply to write the files (.bak kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
