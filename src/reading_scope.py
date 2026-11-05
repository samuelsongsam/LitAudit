"""Resolve a reading question against current visible papers, without a model."""
from __future__ import annotations

import re
import unicodedata

from src.answer_audit import scoped_payload


_AGENDA_ZH = re.compile(
    r'(?:哪些|什么)(?:具体|有价值的|研究)?(?:问题|方向|议题|课题|方面|角度)'
    r'[^。!?]{0,12}(?:值得|适合|有必要|可以)[^。!?]{0,8}(?:分析|研究|探讨|验证|比较|追问)'
    r'|(?:值得|适合|有必要)[^。!?]{0,8}(?:分析|研究|探讨|验证|比较|追问)'
    r'[^。!?]{0,12}(?:问题|方向|议题|课题|角度)'
    r'|(?:^|[，,。；;!?]|请|帮我)\s*(?:提出|拟定|设计|推荐|给出|提炼)\s*'
    r'(?:若干|几个|一些|一组|[一二两三四五六七八九十\d]+[个条项]?)?\s*(?:可检验的?|潜在的?|后续的?|有价值的?)?'
    r'(?:研究问题|研究方向|分析议题|分析方向|分析角度|假设)'
    r'|从\s*(?:哪些|什么)[^。!?]{0,7}(?:角度|方面|方向|切入点)[^。!?]{0,12}(?:分析|研究|入手|验证)'
    r'|(?:下一步|接下来|后续)[^。!?]{0,10}(?:可以|应当|应该|应|该)'
    r'[^。!?]{0,5}(?:分析|研究|验证|探讨|比较)(?:什么|哪些)'
)
_AGENDA_EN = re.compile(
    r'\b(?:questions?|topics?|issues?|directions?)\b[^.!?]{0,34}\b(?:worth|worthwhile to)'
    r'\s+(?:investigat\w*|analy[sz]\w*|pursu\w*|explor\w*|test\w*)'
    r'|\b(?:what|which)\b[^.!?]{0,28}\b(?:should|could)\s+(?:we|i)\s+'
    r'(?:investigate|explore|analy[sz]e|study|test|pursue)\b'
    r'|(?:^|[,;:.!?]\s*|\b(?:please|could you|can you)\s+)(?:suggest|propose|formulate|generate|recommend)'
    r'(?:\s+(?:a|an|some|several|one|two|three|four|five|\d+|new|testable|promising|follow-up)){0,4}\s+'
    r'(?:research questions?|research directions?|hypotheses|research agenda)\b'
    r'|\b(?:what|which)\b[^.!?]{0,24}\b(?:promising|testable|follow-up)\s+'
    r'(?:research\s+)?(?:questions?|directions?|hypotheses)\b',
    re.I,
)
_CURRENT_LITERATURE = re.compile(
    r'(?:当前|本轮|这[些组几篇批份]|上述|上面|已有)[^。!?]{0,9}(?:文献|论文|研究|证据)'
    r'|\b(?:these|those|the above|the current|our selected)\s+(?:papers|studies|articles|sources|literature)\b',
    re.I,
)


def is_research_agenda_question(message: str, *, scoped_reading: bool = True) -> bool:
    """Identify a request to formulate investigation directions within the resolved scope."""
    text = ' '.join(unicodedata.normalize('NFKC', message).split())
    return bool((_AGENDA_ZH.search(text) or _AGENDA_EN.search(text))
                and (scoped_reading or _CURRENT_LITERATURE.search(text)))


def _aliases(paper: dict) -> list[str]:
    title = unicodedata.normalize('NFKC', str(paper.get('title') or '')).strip()
    values = [str(paper.get('paper_id') or ''), title, str(paper.get('doi_or_arxiv') or '')]
    # A distinctive named method before a colon is useful; generic first words
    # such as "A" or "Deep" must not become a paper identifier.
    prefix = re.split(r'[:：]', title, maxsplit=1)[0].strip()
    if prefix != title and 3 <= len(prefix) <= 55:
        values.append(prefix)
    values.extend(re.findall(r'\(([A-Z][A-Za-z0-9-]{2,15})\)', title))
    return list(dict.fromkeys(v for v in values if len(v) >= 2))


def _message_papers(message: str, papers: dict) -> tuple[list[str], bool, list[str]]:
    text = unicodedata.normalize('NFKC', message)
    identifiers = re.findall(r'(?<![A-Za-z0-9_-])paper-\d+(?![A-Za-z0-9_-])', text, re.I)
    unknown = [value for value in identifiers if value.casefold() not in {p.casefold() for p in papers}]
    if unknown:
        raise ValueError('本轮指定的论文不属于当前研究：' + '、'.join(unknown))
    found = []
    for paper_id, paper in papers.items():
        for alias in _aliases(paper):
            pattern = r'(?<![A-Za-z0-9])' + re.escape(alias) + r'(?![A-Za-z0-9])'
            for match in re.finditer(pattern, text, re.I):
                found.append((match.start(), match.end(), paper_id))
    # Attention U-Net also contains U-Net: prefer the longer name at that
    # location, while a separately mentioned U-Net still selects both papers.
    matches = [m for m in found if not any(a <= m[0] and b >= m[1] and b-a > m[1]-m[0]
                                          for a, b, _ in found)]
    excluded = list(dict.fromkeys(p for start, _, p in matches if re.search(
        r'(?:不要|不再|别|忽略|排除)(?:再)?(?:看|读|阅读|使用|参考)?\s*$|'
        r'\b(?:ignore|exclude|skip|do not read|do not use|do not look at)\s*$', text[max(0, start-28):start], re.I)))
    ids = list(dict.fromkeys(p for _, _, p in sorted(matches) if p not in excluded))
    ambiguous = any(len({p for a, b, p in matches if a == left and b == right}) > 1
                    for left, right, _ in matches)
    return ids, ambiguous, excluded


def resolve_reading_scope(payload: dict, message: str, *, selected=None,
                          all_papers: bool = False, history: list | None = None) -> dict:
    papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
    if selected is None:
        selected = []
    elif isinstance(selected, str):
        selected = [selected] if selected else []
    if not isinstance(selected, list) or any(not isinstance(p, str) or p not in papers for p in selected):
        raise ValueError('所选论文不属于当前研究范围')
    explicit, ambiguous, excluded = _message_papers(message, papers)
    if explicit:
        ids, source = explicit, 'message'
    elif excluded:
        ids, source = [p for p in papers if p not in excluded], 'message_exclusion'
        if not ids:
            raise ValueError('当前可用论文均被本轮排除，请选择需要阅读的论文')
    elif all_papers:
        ids, source = list(papers), 'all_selected'
    elif selected:
        ids, source = list(dict.fromkeys(selected)), 'selection'
    else:
        last = next((m for m in reversed(history or []) if isinstance(m, dict) and m.get('role') == 'assistant'), {})
        response = last.get('response') or {}
        audit = response.get('answer_audit') or {}
        previous = (response.get('reading_scope') or {}).get('paper_ids') or [
            c.get('paper_id') for c in audit.get('citations', []) if isinstance(c, dict)]
        previous = list(dict.fromkeys(p for p in previous if p in papers))
        refers_back = bool(re.search(r'这篇|该文|这两篇|刚才|上述|它|该方法|这项方法|\b(?:this paper|these papers|previous|it|its|they)\b', message, re.I))
        ids, source = (previous, 'history_reference') if previous and refers_back else (list(papers), 'current_research')
    return {'paper_ids': ids, 'titles': [papers[p].get('title') or p for p in ids],
            'source': source, 'ambiguous_name': ambiguous, 'excluded_paper_ids': excluded,
            'notice': '本轮论文名称匹配到多个候选，请选择具体论文。' if ambiguous else
                      ('本轮按问题中明确提到的论文检索正文。' if source == 'message' else '本轮只使用当前所示论文范围内的正文。')}
