"""Chat layer: paper context preparation for the pi agent.

Turns a paper that Reaper already processed (cached HTML + parsed blocks)
into a small, byte-stable *workspace* the agent can read and grep:

    data/chat/{arxiv_id}/workspace/
    ├── paper.md        primary context: Markdown + block anchors + LaTeX math
    ├── blocks.json     paragraph index (ids, sentence spans, math)
    ├── OUTLINE.md      byte-stable TOC front block (prompt-cache friendly)
    └── metadata.json   paper metadata + cleaner version

Design notes
------------
* **paper.md is generated from the LaTeXML HTML blocks, not from LaTeX source.**
  This keeps paragraph anchors (`<!-- block:N -->`) identical to the ids in the
  rendered bilingual HTML (`id="reaper-block-N"`), which is what makes
  "user selected this paragraph" resolvable. LaTeX is only an optional
  enhancement for macro expansion and citation parsing.

* **Math is taken from `<annotation encoding="application/x-tex">`** inside each
  `<math>` element — i.e. the author's own LaTeX. LaTeXML already expanded the
  author's macros in the *MathML* body, so we keep that around for verification
  rather than trying to convert MathML to LaTeX.

* **Everything written into the prompt prefix must be byte-stable** (no
  timestamps, no set-iteration order) so that repeated turns hit the provider's
  prompt cache.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
from pathlib import Path

from .. import config
from ..ingestion.parser import Block, mark_and_extract

# Bump when the generated artifacts change shape/semantics; used to invalidate
# cached workspaces (same idea as the reference implementations' cleanerVersion).
CONTEXT_VERSION = 2

# --------------------------------------------------------------------------- #
