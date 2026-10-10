"""Chat layer: paper-grounded conversation driven by the pi agent.

Sub-modules:
    context   build the agent's workspace (paper.md, blocks.json, OUTLINE.md)
    bridge    drive `pi --mode rpc` over stdio and broadcast its events
    session   per-paper pi process registry with idle eviction
    citations (planned) resolve \\cite keys to cited papers' full text
"""

from .bridge import PiBridge, PiBridgeError
from .context import (
    CONTEXT_VERSION,
    build_block_index,
    build_outline,
    math_to_latex,
    prepare_paper_context,
    render_paper_md,
    restore_math,
    split_sentences,
    workspace_dir,
)
from .session import PiSessionRegistry, registry

__all__ = [
    "CONTEXT_VERSION",
    "PiBridge",
    "PiBridgeError",
    "PiSessionRegistry",
    "build_block_index",
    "build_outline",
    "math_to_latex",
    "prepare_paper_context",
    "registry",
    "render_paper_md",
    "restore_math",
    "split_sentences",
    "workspace_dir",
]
