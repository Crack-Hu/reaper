"""TeX macro expansion: parse \newcommand from a .tex preamble and expand them.

Usage:
    table = build_macro_table("paper.tex")
    clean_latex = expand_macros(annotation_latex, table)
"""

from __future__ import annotations

import re as _re

# Pattern for: \newcommand{\name}[n]{body}, \newcommand*{\name}[n]{body},
#             \renewcommand{\name}[n]{body}
_NEWCMD = _re.compile(
    r"\\(?:re)?newcommand\*?"
    r"\{\\([A-Za-z]+)\}"          # macro name
    r"(?:\[(\d+)\])?"             # optional argument count
    r"\{"                         # start of body
    r"((?:[^{}]|\{[^{}]*\})*)"    # body (one level of nesting allowed)
    r"\}",
)

# Pattern for: \DeclareMathOperator{\name}{text}
_DECLARE_OP = _re.compile(
    r"\\DeclareMathOperator\*?"
    r"\{\\([A-Za-z]+)\}"
    r"\{(.*?)\}"
)


def build_macro_table(tex_path: str) -> dict[str, tuple[int, str]]:
    """Parse a .tex file preamble and return {macro_name: (arg_count, body)}."""
    with open(tex_path, encoding="utf-8") as f:
        tex = f.read()
    # Only scan the preamble (before \begin{document}).
    preamble = tex.split(r"\begin{document}")[0]

    table: dict[str, tuple[int, str]] = {}

    for m in _NEWCMD.finditer(preamble):
        name = "\\" + m.group(1)
        nargs = int(m.group(2)) if m.group(2) else 0
        body = m.group(3)
        table[name] = (nargs, body)

    for m in _DECLARE_OP.finditer(preamble):
        name = "\\" + m.group(1)
        table[name] = (0, "\\operatorname{" + m.group(2) + "}")

    return table


def expand_macros(latex: str, table: dict[str, tuple[int, str]]) -> str:
    """Replace known macros, multiple passes (nested macros)."""
    result = latex
    for _pass in range(15):
        prev = result
        for name, (nargs, body) in _sorted_table(table):
            if name not in result:
                continue
            if nargs == 0:
                result = result.replace(name, body)
            else:
                result = _subst_args(result, name, nargs, body)
        if result == prev:
            break
    return result


def _sorted_table(table: dict) -> list:
    r"""Longest name first, so \longmacro is tried before \long."""
    return sorted(table.items(), key=lambda x: -len(x[0]))


def _subst_args(latex: str, name: str, nargs: int, body: str) -> str:
    """Replace \\name{arg1}...{argn} in latex, substituting #1, #2 in body.
    Handles nested braces and the optional ``*`` modifier."""
    escaped = _re.escape(name)
    if name in latex.replace("*" + "{", "{"):
        # Optional `*` before the first argument
        escaped += r"\*?"
    # _nested_brace already starts with \{, no extra needed
    pat = escaped + _nested_brace(nargs)
    def _replacer(m):
        args = [_extract_brace(m.group(0), pos) for pos in range(nargs)]
        return _fill(body, args)
    return _re.sub(pat, _replacer, latex)


def _nested_brace(n: int) -> str:
    """Build regex for n consecutive "{...}" groups, each handling nesting."""
    # Match a { ... } pair where ... can contain more { ... }
    inner = r"(?:[^{}]|\{[^{}]*\})*"  # one level of nesting
    return r"\{" + inner + r"\}" * n


def _extract_brace(text: str, pos: int) -> str:
    """Extract the content of the pos-th {…} group in text."""
    # Find the start of the requested brace group by counting
    depth = 0
    brace_idx = -1
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                brace_idx += 1
                if brace_idx == pos:
                    start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and brace_idx == pos and start >= 0:
                return text[start:i]
    return text


def _fill(body: str, args: list[str]) -> str:
    for i, a in enumerate(args, 1):
        body = body.replace(f"#{i}", a)
    return body