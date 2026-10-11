"""Rescue figures that LaTeXML cannot render, by rendering them with real LaTeX.

Why
---
LaTeXML has no real support for Xy-pic (and therefore none for Qcircuit — see
``ar5ivist_bindings/README.md``): it reports one error per subscript inside a
diagram and lets the malformed alignment swallow the rest of the document.
Dropping the diagram keeps the paper readable (the binding does that), but the
figures are worth keeping.

How
---
The ar5ivist image ships a full TeX Live, so the *same container* can render the
diagrams with real LaTeX. Three steps, each in a different place:

======================  =======================================================
host (this module)      walk the paper's sources, write one tiny document per
                        diagram: the paper's own preamble + the snippet
docker (compile_script) ``latex`` + ``dvisvgm`` turn each document into SVG
converter (binding)     replaces construct N with ``\\includegraphics{dN.svg}``
======================  =======================================================

The numbering is the only coupling between host and converter, and both walk the
sources in the same order (``\\input`` order). Nothing inspects the *content* of
the converted document: a diagram either has an SVG or the binding falls back to
its placeholder.

Inputs are declared, not guessed: :data:`CONSTRUCTS` lists what to rescue; add
environments to it when LaTeXML turns out to mangle other packages.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# LaTeXML renders none of these: Xy-pic's \xymatrix (which is what \Qcircuit
# expands to) and, in the same family, other TeX-programmed drawing constructs.
CONSTRUCTS: tuple[str, ...] = ("Qcircuit", "xymatrix")

DIAGRAM_DIR = "reaper-diagrams"
PLACEHOLDER_MARK = "reaper-diagram-placeholder"

_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]*)\}")
_DEFINED_MACRO_RE = re.compile(
    r"\\(?:newcommand\*?|renewcommand\*?|providecommand\*?)\s*\{\s*\\([A-Za-z]+)\s*\}"
    r"\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}"
    r"|\\(?:def|edef|gdef|xdef)\s*\\([A-Za-z]+)\s*\{([^{}]*)\}"
)


@dataclass
class Diagram:
    """One rescued construct: where it came from and its source text."""

    index: int
    source_file: str          # path relative to the source dir
    line: int
    tex: str


@dataclass
class RescueReport:
    count: int = 0
    documents: int = 0
    compiled: int = 0         # filled in by `verify()` after the container ran
    directory: str = ""
    diagrams: list[Diagram] = field(default_factory=list)


# ── scanning ──────────────────────────────────────────────────────────────

def _braced_spans(text: str, command: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every ``\\command ... { ... }`` call, comments skipped."""
    out: list[tuple[int, int]] = []
    needle = "\\" + command
    for m in re.finditer(re.escape(needle), text):
        after = m.end()
        if after < len(text) and text[after].isalpha():
            continue                                   # part of a longer control word
        line_start = text.rfind("\n", 0, m.start()) + 1
        if "%" in text[line_start:m.start()]:
            continue                                   # commented out
        brace = text.find("{", m.start())
        if brace < 0:
            continue                                   # no body (e.g. \xymatrix alone)
        end = _matching_brace(text, brace)
        if end >= 0:
            out.append((m.start(), end + 1))
    return out


def _matching_brace(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2                                     # escaped char (\\{ \\} \\%)
            continue
        if ch == "%":                                  # comment runs to end of line
            nl = text.find("\n", i)
            if nl < 0:
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


def _defined_macros(text: str) -> dict[str, str]:
    """Simple ``\\newcommand{\\Name}{value}`` / ``\\def\\Name{value}`` pairs.

    Only used to resolve ``\\input`` paths that are written with a macro
    (papers commonly do ``\\input{\\ProjectRoot/intro.tex}``).
    """
    found = {}
    for m in _DEFINED_MACRO_RE.finditer(text):
        name, value = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = " ".join(value.split())
        if len(value) <= 64 and "\\" not in value:
            found["\\" + name] = value
    return found


def collect_diagrams(source_dir: Path, main_name: str = "main.tex") -> list[Diagram]:
    """Every :data:`CONSTRUCTS` occurrence, in document (``\\input``) order."""
    source_dir = Path(source_dir).resolve()      # macOS /tmp → /private/tmp
    main = source_dir / main_name
    if not main.exists():
        return []

    diagrams: list[Diagram] = []
    read: set[Path] = set()
    macros: dict[str, str] = {}

    def walk(path: Path, depth: int = 0) -> None:
        if depth > 12 or path in read or not path.is_file():
            return
        read.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        macros.update(_defined_macros(text))

        events: list[tuple[int, str, object]] = []
        for m in _INPUT_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            if "%" in text[line_start:m.start()]:
                continue
            events.append((m.start(), "input", m.group(1)))
        for command in CONSTRUCTS:
            for start, end in _braced_spans(text, command):
                events.append((start, "diagram", (path, start, end)))

        for _, kind, payload in sorted(events):
            if kind == "input":
                target = _resolve_input(source_dir, payload, macros)
                if target is not None:
                    walk(target, depth + 1)
            else:
                file, start, end = payload
                diagrams.append(Diagram(
                    index=len(diagrams),
                    source_file=str(file.relative_to(source_dir)),
                    line=text.count("\n", 0, start) + 1,
                    tex=text[start:end],
                ))

    walk(main)
    return diagrams


def _resolve_input(source_dir: Path, spec: str, macros: dict[str, str]) -> Path | None:
    for name, value in macros.items():
        spec = spec.replace(name, value)
    spec = spec.strip()
    if not spec or "\\" in spec:
        return None
    for candidate in (spec, spec + ".tex"):
        path = (source_dir / candidate).resolve()
        if path.is_file():
            return path
    return None


# ── preparation (host side) ───────────────────────────────────────────────

_PLACEHOLDER_SVG = """<?xml version='1.0' encoding='UTF-8'?>
<!-- {mark} -->
<svg xmlns='http://www.w3.org/2000/svg' width='220pt' height='26pt' viewBox='0 0 220 26'>
  <rect x='0.5' y='0.5' width='219' height='25' fill='none' stroke='#999'
        stroke-width='0.7' stroke-dasharray='3 3'/>
  <text x='110' y='17' font-family='Helvetica,Arial,sans-serif' font-size='11'
        fill='#666' text-anchor='middle'>[diagram omitted]</text>
</svg>
"""


def diagram_dir(source_dir: Path) -> Path:
    return Path(source_dir) / DIAGRAM_DIR


def prepare(source_dir: Path, main_name: str = "main.tex") -> RescueReport:
    """Write one document per diagram, plus placeholders, count and index.

    Placeholders are written for *every* index up front, so the converter can
    always reference ``dN.svg``; the container run overwrites the ones that
    compile. Call :func:`verify` afterwards to count the real ones.
    """
    source_dir = Path(source_dir).resolve()
    out = diagram_dir(source_dir)
    docs = out / "src"
    work = out / "work"
    for d in (docs, work):
        d.mkdir(parents=True, exist_ok=True)

    diagrams = collect_diagrams(source_dir, main_name)
    report = RescueReport(count=len(diagrams), directory=str(out), diagrams=diagrams)

    preamble = _paper_preamble(source_dir / main_name)
    for d in diagrams:
        document = (
            preamble
            + "\n\\usepackage[active,tightpage]{preview}\n"
            + "\\begin{document}\n\\thispagestyle{empty}\n\\begin{preview}\n"
            + "\\ensuremath{\n" + d.tex + "\n}\n"
            + "\\end{preview}\n\\end{document}\n"
        )
        (docs / f"d{d.index}.tex").write_text(document, encoding="utf-8")
        (out / f"d{d.index}.svg").write_text(
            _PLACEHOLDER_SVG.format(mark=PLACEHOLDER_MARK), encoding="utf-8")
        report.documents += 1

    (out / "count.tex").write_text(
        f"% [Reaper] how many diagrams the converter should substitute\n"
        f"\\def\\reaperDiagramCount{{{report.count}}}\n", encoding="utf-8")
    (out / "index.json").write_text(json.dumps(
        [{"index": d.index, "file": d.source_file, "line": d.line} for d in diagrams],
        ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _paper_preamble(main_tex: Path) -> str:
    """Everything before ``\\begin{document}`` — the paper's own preamble."""
    if not main_tex.is_file():
        return "\\documentclass{article}"
    text = main_tex.read_text(encoding="utf-8", errors="replace")
    return text.split("\\begin{document}")[0]


def compile_script() -> str:
    """Shell script that renders each prepared document inside the container.

    Run with the paper's source directory as the working directory (it is mounted
    there), so ``\\input`` paths inside the preamble resolve as usual.
    """
    return (
        "set -u\n"
        f"cd /source\n"
        f"for doc in {DIAGRAM_DIR}/src/d*.tex; do\n"
        f"  base=$(basename \"$doc\" .tex)\n"
        f"  latex -interaction=nonstopmode -output-directory={DIAGRAM_DIR}/work \"$doc\""
        f" >/dev/null 2>&1 || continue\n"
        f"  dvisvgm --no-fonts --exact \"{DIAGRAM_DIR}/work/$base.dvi\""
        f" -o \"{DIAGRAM_DIR}/$base.svg\" >/dev/null 2>&1 || true\n"
        f"done\n"
    )


def verify(source_dir: Path) -> tuple[int, list[str]]:
    """Count real (non-placeholder) SVGs; returns ``(compiled, failed_names)``."""
    out = diagram_dir(source_dir)
    compiled, failed = 0, []
    for svg in sorted(out.glob("d*.svg")):
        try:
            text = svg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            failed.append(svg.name)
            continue
        if PLACEHOLDER_MARK in text:
            failed.append(svg.name)
        else:
            compiled += 1
    return compiled, failed


def cleanup(source_dir: Path) -> None:
    """Remove everything :func:`prepare` created (used by tests / --no-rescue)."""
    shutil.rmtree(diagram_dir(source_dir), ignore_errors=True)
