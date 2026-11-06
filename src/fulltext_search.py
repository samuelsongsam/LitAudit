from __future__ import annotations

import math
import re
from functools import lru_cache
from dataclasses import dataclass, field
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
    char_start: int = 0
    char_end: int = 0
    context: list[dict[str, Any]] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+.#-]{1,}|[\u4e00-\u9fff]{2,}", (text or "").lower())


QUERY_TERMS = {
    "方法": "method methodology approach framework", "实验": "experiment experimental setup",
    "数据": "data dataset sample corpus", "样本": "sample participants population",
    "指标": "metric evaluation accuracy precision recall", "基线": "baseline comparison ablation",
    "算力": "compute gpu hardware training cost", "资源": "resources hardware memory cost",
    "检索": "retrieval search", "证据": "evidence attribution citation",
    "样本量": "sample size number of participants enrollment", "设置": "setup protocol configuration",
    "结果": "results findings performance", "适用": "applicability conditions limitations",
    "局限": "limitations constraints caveats", "消融": "ablation sensitivity analysis",
}

RESEARCH_TERMS = {
    "预训练": "pretrained pre-trained", "冻结": "freeze frozen", "权重": "weights",
    "可训练": "trainable", "低秩": "low-rank rank decomposition", "矩阵": "matrix matrices",
    "量化": "quantization quantized", "显存": "GPU memory", "微调": "finetuning fine-tuning",
    "数据增强": "data augmentation", "弹性形变": "elastic deformation deformations",
    "训练数据": "training data", "中心化": "centering centered subtract mean",
    "均值": "mean", "预处理": "preprocessing", "奇异值分解": "singular value decomposition",
    "协方差": "covariance", "特征值": "eigenvalues", "方差": "variance",
    "收缩路径": "contracting path", "扩展路径": "expanding path",
    "注意力": "attention", "门控": "gating gates", "分割": "segmentation",
}


def expand_query(question: str) -> str:
    """Small transparent terminology expansion; the original question is retained."""
    specific = [value for term, value in RESEARCH_TERMS.items() if term in question]
    # Specific scientific concepts carry more useful intent than generic words
    # such as "method"; broad category expansion remains useful for open queries.
    generic = [] if specific else [value for term, value in QUERY_TERMS.items() if term in question]
    return " ".join([question, *specific, *generic]).strip()


@lru_cache(maxsize=4096)
def _recall_vector(text: str) -> tuple[float, ...]:
    from src.map_builder import _hash_embedding
    return tuple(_hash_embedding(text))


@lru_cache(maxsize=24)
def _rank_candidates(question: str, rows: tuple[tuple, ...]) -> tuple[tuple[tuple[str, float], ...], dict]:
    """Batch model inference and cache repeated interactive queries in this process."""
    from src.retrieval_rank import rank_hits
    from src.tasks import check_cancelled
    scores, metadata = [], {}
    for start in range(0, len(rows), 12):
        check_cancelled()
        batch = [Passage(*row) for row in rows[start:start + 12]]
        ranked, metadata = rank_hits(question, batch)
        scores.extend((p.passage_id, p.semantic_score or 0.0) for p in ranked)
    check_cancelled()
    return tuple(scores), metadata


def _section(text: str) -> str | None:
    from src.document_processing import page_headings
    headings = page_headings(text)
    return headings[0]["section"] if headings else None


def chunk_pages(papers: dict[str, Any], pages_by_paper: dict[str, list[str]],
                *, max_chars: int = 1200, overlap: int = 160) -> list[Passage]:
    from src.document_processing import annotate_sections
    if max_chars < 1 or overlap < 0 or overlap >= max_chars:
        raise ValueError("chunk size must be positive and overlap smaller than chunk size")
    passages: list[Passage] = []
    for paper_id, pages in pages_by_paper.items():
        paper = papers.get(paper_id)
        title = (getattr(paper, "title", None) or paper_id) if paper else paper_id
        texts = [re.sub(r"[ \t]+", " ", (p.get("text", "") if isinstance(p, dict) else p) or "").strip() for p in pages]
        sections = annotate_sections(texts)
        for page_number, (cleaned, metadata) in enumerate(zip(texts, sections), start=1):
            if not cleaned:
                continue
            part = 0
            headings = metadata["headings"]
            cuts = sorted({0, len(cleaned), *(h["char_offset"] for h in headings)})
            active = metadata.get("start_section")
            for segment_start, segment_end in zip(cuts, cuts[1:]):
                for heading in headings:
                    if heading["char_offset"] <= segment_start:
                        active = heading["section"]
                start = segment_start
                while start < segment_end:
                    end = min(segment_end, start + max_chars)
                    if end < segment_end:
                        boundary = max(cleaned.rfind("\n\n", start, end), cleaned.rfind(". ", start, end),
                                       cleaned.rfind("。", start, end), cleaned.rfind("\n", start, end))
                        if boundary > start + max_chars // 2:
                            end = boundary + (1 if cleaned[boundary] in ".。\n" else 0)
                    raw = cleaned[start:end]
                    text = raw.strip()
                    if text:
                        part += 1
                        context = []
                        if start:
                            context.append({"page": page_number, "position": "before", "text": cleaned[max(0, start-350):start]})
                        elif page_number > 1 and texts[page_number-2]:
                            context.append({"page": page_number-1, "position": "previous_page", "text": texts[page_number-2][-500:]})
                        if end < len(cleaned):
                            context.append({"page": page_number, "position": "after", "text": cleaned[end:end+350]})
                        elif page_number < len(texts) and texts[page_number]:
                            context.append({"page": page_number+1, "position": "next_page", "text": texts[page_number][:500]})
                        char_start = start + len(raw) - len(raw.lstrip())
                        passages.append(Passage(
                            passage_id=f"{paper_id}:p{page_number}:c{part}", paper_id=paper_id,
                            page=page_number, section=active, title=title, abstract=text,
                            text_sha256=sha256(text.encode("utf-8")).hexdigest(),
                            char_start=char_start, char_end=char_start+len(text), context=context))
                    if end >= segment_end:
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
                          *, top_k: int = 12, semantic_candidates: int = 40,
                          section: str | None = None, candidate_policy: str = "bm25",
                          semantic_rerank: bool = True) -> dict[str, Any]:
    from src.tasks import check_cancelled
    check_cancelled()
    if candidate_policy not in {"bm25", "union"}:
        raise ValueError("candidate_policy must be bm25 or union")
    passages = chunk_pages(papers, pages_by_paper)
    algorithm = "bm25_specter2_passage_rerank" if semantic_rerank else "bm25_passage_ranking"
    total_passages = len(passages)
    if section and section.strip():
        aliases = {"method": "methods", "方法": "methods", "实验": "experimental_setup",
                   "experiment": "experimental_setup", "experiments": "experimental_setup",
                   "result": "results", "结果": "results", "引言": "introduction",
                   "摘要": "abstract", "结论": "conclusion", "讨论": "discussion",
                   "参考文献": "references", "数据": "data"}
        canonical = aliases.get(section.strip().lower(), section.strip().lower())
        passages = [p for p in passages if p.section == canonical]
    if not passages:
        return {"algorithm": algorithm, "passage_count": 0, "hits": [],
                "total_passage_count": total_passages, "section_filter": section,
                "indexed_paper_count": len(pages_by_paper),
                "embedding": {"backend": "not_run", "reason": "no matching section" if total_passages else "no parsed fulltext"}}
    expanded = expand_query(question)
    scores = bm25_scores(expanded, passages)
    for passage, score in zip(passages, scores):
        passage.bm25_score = score
    # Lexical recall, cheap hashed-vector recall and per-paper coverage are merged
    # before expensive SPECTER2 inference. Hash recall is explicitly labelled;
    # it never masquerades as a SPECTER2 semantic score.
    lexical = sorted(passages, key=lambda item: -item.bm25_score)[:semantic_candidates]
    vector = []
    if candidate_policy == "union":
        query_vector = _recall_vector(expanded)
        vector = sorted(passages, key=lambda p: -sum(a * b for a, b in zip(query_vector, _recall_vector(p.abstract))))[:semantic_candidates]
    coverage, seen_papers = [], set()
    for passage in sorted(passages, key=lambda p: -p.bm25_score):
        if passage.paper_id not in seen_papers:
            coverage.append(passage)
            seen_papers.add(passage.paper_id)
    # Preserve the stable lexical shortlist by default. The wider hashed union
    # is opt-in; it did not consistently improve first-result quality in the
    # developer source-location study. A zero-overlap query still sees each paper.
    additions = coverage if candidate_policy == "union" or not any(scores) else []
    candidates = list({p.passage_id: p for p in lexical + vector + additions}.values())
    embedding = {"backend": "not_run", "reason": "lexical acquisition preview"}
    bm25_weight, semantic_weight = (0.55, 0.45) if semantic_rerank else (1.0, 0.0)
    if semantic_rerank:
        component_scores, embedding = _rank_candidates(expanded, tuple(
            (p.passage_id, p.paper_id, p.page, p.section, p.title, p.abstract, p.text_sha256) for p in candidates))
        check_cancelled()
        semantic_scores = dict(component_scores)
        for item in candidates:
            item.semantic_score = semantic_scores[item.passage_id]
    max_bm25 = max((item.bm25_score for item in candidates), default=0.0)
    for item in candidates:
        normalized_bm25 = item.bm25_score / max_bm25 if max_bm25 else 0.0
        score = bm25_weight * normalized_bm25 + semantic_weight * (item.semantic_score or 0.0)
        if item.section == "references" and not re.search(r"\breferences?\b|bibliograph|参考文献|文献列表", question, re.I):
            score *= 0.2
        item.ranking_score = round(score, 6)
    candidates.sort(key=lambda item: (-item.ranking_score, item.paper_id, item.page))
    # Repeated running text should not consume multiple result positions.
    unique, seen = [], set()
    for item in candidates:
        fingerprint = (item.paper_id, re.sub(r"\s+", " ", item.abstract).strip())
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(item)
    return {
        "algorithm": algorithm,
        "weights": {"bm25": bm25_weight, "specter2": semantic_weight},
        "passage_count": len(passages),
        "total_passage_count": total_passages,
        "section_filter": section,
        "indexed_paper_count": len(pages_by_paper),
        "expanded_query": expanded,
        "candidate_policy": ("bm25_hash_recall_union_with_per_paper_coverage" if candidate_policy == "union"
                             else "bm25_first40_with_zero_overlap_paper_coverage"),
        "candidate_count": len(candidates),
        "section_policy": "reference_downweight",
        "context_policy": "adjacent_text_with_separate_page_locations",
        "embedding": embedding,
        "hits": [
            {
                "passage_id": item.passage_id, "paper_id": item.paper_id, "page": item.page,
                "section": item.section, "text": item.abstract, "text_sha256": item.text_sha256,
                "bm25_score": round(item.bm25_score, 6), "semantic_score": item.semantic_score,
                "score": item.ranking_score,
                "char_start": item.char_start, "char_end": item.char_end,
                "context": item.context,
            }
            for item in unique[:top_k]
        ],
    }
