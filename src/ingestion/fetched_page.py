"""FetchedPage dataclass — result of fetching a paper's HTML.

Carries the raw HTML, source type, and metadata needed by the
downstream parse → translate → render pipeline.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FetchedPage:
    """Result of a successful HTML fetch.

    Attributes:
        arxiv_id:     arXiv paper ID (e.g. "2307.14989")
        source_type:  "ar5iv" | "arxiv_html" | "ar5ivist_docker" | "cache"
        html:         Raw HTML content
        img_dir:      Directory where cached images are stored
        page_url:     Base URL of the source page (for resolving relative URLs)
    """
    arxiv_id: str
    source_type: str
    html: str
    img_dir: Path = field(default_factory=lambda: Path())
    page_url: str = ""