"""Resolve a reader selection against this research's stored original page."""
from __future__ import annotations

from pathlib import Path
import re
import unicodedata


def _characters(text: str, *, unwrap_hyphens=True):
    value, positions = [], []
    for index, char in enumerate(text):
        if char == '\u00ad':
            continue
        # A layout hyphen at a word-wrapping line ending can disappear in a
        # browser selection; mathematical signs and punctuation remain exact.
        if (unwrap_hyphens and char in {'-', '\u2010'} and index
                and re.search(r'[^\W\d_]{2,}$', text[:index])
                and re.match(r'[ \t]*\r?\n[ \t]*[^\W\d_]', text[index + 1:])):
            continue
        for normalized in unicodedata.normalize('NFKC', char).casefold():
            if not normalized.isspace():
                value.append(normalized)
                positions.append(index)
    return ''.join(value), positions


def resolve_reader_selection(runs_dir: Path, run_id: str, value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'paper_id', 'page', 'quote'}:
        raise ValueError('原文选择格式无效')
    paper_id, page, quote = value.get('paper_id'), value.get('page'), value.get('quote', '')
    if (not isinstance(paper_id, str) or type(page) is not int or not 1 <= page <= 300
            or not isinstance(quote, str) or len(quote) > 6000):
        raise ValueError('原文选择的论文、页码或文本无效')
    from src.research_workspace import _corpus
    papers, pages, _ = _corpus(runs_dir, run_id, [paper_id])
    page_texts = pages.get(paper_id) or []
    original = page_texts[page - 1] if page <= len(page_texts) else None
    if not original:
        raise ValueError('所选页没有可用正文')
    exact = ''
    if quote.strip():
        # Browser selections may retain a printed wrap hyphen or omit it.
        # Try both layouts while keeping mathematical signs exact.
        for unwrap in (False, True):
            needle, _ = _characters(quote, unwrap_hyphens=unwrap)
            haystack, positions = _characters(original, unwrap_hyphens=unwrap)
            start = haystack.find(needle) if needle else -1
            if start >= 0:
                exact = original[positions[start]:positions[start + len(needle) - 1] + 1]
                break
        if not exact:
            raise ValueError('选中文本与当前原文页不同，请重新选择')
    return {'paper_id': paper_id, 'page': page, 'quote': exact,
            'title': papers[paper_id].title, 'source': 'stored_original_page'}


def selected_page_passages(passages, selection: dict, original: str):
    """Put the selected span before other chunks from the same original page."""
    own = [p for p in passages if p.paper_id == selection['paper_id'] and p.page == selection['page']]
    quote, _ = _characters(selection.get('quote') or '')
    page_text, _ = _characters(original)
    start = page_text.find(quote) if quote else -1
    if start < 0:
        return own
    end = start + len(quote)
    def rank(passage):
        text, _ = _characters(passage.abstract)
        offset = page_text.find(text)
        overlap = max(0, min(end, offset + len(text)) - max(start, offset)) if offset >= 0 else 0
        return -overlap, passage.char_start
    return sorted(own, key=rank)
