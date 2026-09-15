from __future__ import annotations

import math
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


@dataclass
class Passage:
    passage_id: str
    paper_id: str
    page: int
    section: str | None
    title: str
    abstract: str
    text_sha256: str
    bm25_score: float = 0.0
    semantic_score: float | None = None
    lexical_score: float | None = None
    ranking_score: float | None = None


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+.#-]{1,}|[\u4e00-\u9fff]{2,}", (text or "").lower())


def _section(text: str) -> str | None:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")[:100]
    match = re.match(r"^(?:\d+(?:\.\d+)*)?\s*(abstract|introduction|background|methods?|results?|discussion|conclusions?|摘要|引言|方法|结果|讨论|结论)\b", first, re.I)
    return match.group(1) if match else None


def chunk_pages(papers: dict[str, Any], pages_by_paper: dict[str, list[str]],
                *, max_chars: int = 1200, overlap: int = 160) -> list[Passage]:
    passages: list[Passage] = []
    for paper_id, pages in pages_by_paper.items():
        paper = papers.get(paper_id)
        title = (getattr(paper, "title", None) or paper_id) if paper else paper_id
        for page_number, page_text in enumerate(pages, start=1):
            cleaned = re.sub(r"[ \t]+", " ", page_text or "").strip()
            if not cleaned:
                continue
            start = 0
            part = 0
            while start < len(cleaned):
                end = min(len(cleaned), start + max_chars)
                if end < len(cleaned):
                    boundary = max(cleaned.rfind("\n", start, end), cleaned.rfind(". ", start, end))
                    if boundary > start + max_chars // 2:
                        end = boundary + 1
                text = cleaned[start:end].strip()
                if text:
                    part += 1
                    passages.append(Passage(
                        passage_id=f"{paper_id}:p{page_number}:c{part}", paper_id=paper_id,
                        page=page_number, section=_section(text), title=title, abstract=text,
                        text_sha256=sha256(text.encode("utf-8")).hexdigest()))
                if end >= len(cleaned):
                    break
                start = max(start + 1, end - overlap)
    return passages


def bm25_scores(query: str, passages: list[Passage], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    query_terms = list(dict.fromkeys(_tokens(query)))
    documents = [_tokens(item.abstract) for item in passages]
    if not query_terms or not documents:
        return [0.0] * len(passages)
    average_length = sum(map(len, documents)) / len(documents) or 1.0
    frequencies = {term: sum(term in document for document in documents) for term in query_terms}
    scores = []
    for document in documents:
        counts = {term: document.count(term) for term in query_terms}
        score = 0.0
        for term in query_terms:
            tf = counts[term]
            if not tf:
                continue
            idf = math.log(1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(document) / average_length))
        scores.append(score)
    return scores


def build_fulltext_search(question: str, papers: dict[str, Any], pages_by_paper: dict[str, list[str]],
                          *, top_k: int = 12, semantic_candidates: int = 40) -> dict[str, Any]:
    passages = chunk_pages(papers, pages_by_paper)
    if not passages:
        return {"algorithm": "bm25_specter2_passage_rerank", "passage_count": 0, "hits": [],
                "embedding": {"backend": "not_run", "reason": "no parsed fulltext"}}
    scores = bm25_scores(question, passages)
    for passage, score in zip(passages, scores):
        passage.bm25_score = score
    candidates = sorted(passages, key=lambda item: -item.bm25_score)[:semantic_candidates]
    from src.retrieval_rank import rank_hits
    candidates, embedding = rank_hits(question, candidates)
    max_bm25 = max((item.bm25_score for item in candidates), default=0.0)
    for item in candidates:
        normalized_bm25 = item.bm25_score / max_bm25 if max_bm25 else 0.0
        item.ranking_score = round(0.55 * normalized_bm25 + 0.45 * (item.semantic_score or 0.0), 6)
    candidates.sort(key=lambda item: (-item.ranking_score, item.paper_id, item.page))
    return {
        "algorithm": "bm25_specter2_passage_rerank",
        "weights": {"bm25": 0.55, "specter2": 0.45},
        "passage_count": len(passages),
        "indexed_paper_count": len(pages_by_paper),
        "embedding": embedding,
        "hits": [
            {
                "passage_id": item.passage_id, "paper_id": item.paper_id, "page": item.page,
                "section": item.section, "text": item.abstract, "text_sha256": item.text_sha256,
                "bm25_score": round(item.bm25_score, 6), "semantic_score": item.semantic_score,
                "score": item.ranking_score,
            }
            for item in candidates[:top_k]
        ],
    }
