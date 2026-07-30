"""Reaper: 科研文章阅读工程"""

from .ingestion import fetch_html, arxiv_id_from_url, mark_and_extract, parse_blocks, Block, restore_math_in_translation
from .translation import translate_text, translate_blocks, TermDictionary
from .rendering import render_bilingual_html, save_html
from . import config
