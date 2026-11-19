"""Small, source-located developer evaluation; not a population recall estimate."""
from __future__ import annotations

import re
import time
from hashlib import sha256
from pathlib import Path
from typing import Any


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold().strip()


def legacy_search(question: str, papers: dict, pages_by_paper: dict, *, top_k: int = 12) -> dict:
    """Frozen HEAD-style baseline: plain page chunks, BM25 first 40, same reranker.

    No bilingual expansion, per-paper candidate coverage, carried sections or
    reference downweight is added. Real model availability is reported by rank_hits.
    """
    from src.fulltext_search import Passage, bm25_scores
    from src.retrieval_rank import rank_hits
    from hashlib import sha256
    passages = []
    for paper_id, pages in pages_by_paper.items():
        title = getattr(papers[paper_id], "title", None) or paper_id
        for page, raw in enumerate(pages, 1):
            text = re.sub(r"[ \t]+", " ", raw or "").strip()
            start, part = 0, 0
            while start < len(text):
                end = min(len(text), start + 1200)
                if end < len(text):
                    boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
                    if boundary > start + 600:
                        end = boundary + 1
                snippet = text[start:end].strip()
                if snippet:
                    part += 1
                    passages.append(Passage(f"{paper_id}:p{page}:c{part}", paper_id, page, None,
                                             title, snippet, sha256(snippet.encode()).hexdigest()))
                if end >= len(text):
                    break
                start = max(start + 1, end - 160)
    if not passages:
        return {"hits": [], "embedding": {"backend": "not_run"}, "passage_count": 0}
    scores = bm25_scores(question, passages)
    for passage, score in zip(passages, scores):
        passage.bm25_score = score
    candidates = sorted(passages, key=lambda p: -p.bm25_score)[:40]
    candidates, embedding = rank_hits(question, candidates)
    maximum = max((p.bm25_score for p in candidates), default=0)
    for passage in candidates:
        passage.ranking_score = .55 * (passage.bm25_score / maximum if maximum else 0) + .45 * (passage.semantic_score or 0)
    candidates.sort(key=lambda p: (-p.ranking_score, p.paper_id, p.page))
    return {"hits": [{"paper_id": p.paper_id, "page": p.page, "text": p.abstract,
                      "passage_id": p.passage_id, "score": p.ranking_score} for p in candidates[:top_k]],
            "embedding": embedding, "passage_count": len(passages), "candidate_count": len(candidates)}


def evaluate_reference(reference: dict, hits: list[dict], paper_ids: dict[str, str]) -> dict:
    target = paper_ids[reference["arxiv_id"]]
    pages = set(reference["pages"])
    quote = normalize(reference["quote"])
    page_rank = quote_rank = None
    for rank, hit in enumerate(hits, 1):
        if hit.get("paper_id") != target:
            continue
        if page_rank is None and hit.get("page") in pages:
            page_rank = rank
        if quote_rank is None and quote in normalize(hit.get("text", "")):
            quote_rank = rank
    return {"page_rank": page_rank, "quote_rank": quote_rank,
            **{f"page_hit@{k}": int(page_rank is not None and page_rank <= k) for k in (1, 3, 5, 12)},
            **{f"quote_hit@{k}": int(quote_rank is not None and quote_rank <= k) for k in (1, 3, 5, 12)}}


def run_reference_evaluation(references: list[dict], corpus_by_task: dict, *, top_k: int = 12) -> dict:
    from src.fulltext_search import build_fulltext_search
    rows = []
    for reference in references:
        corpus = corpus_by_task[reference["task"]]
        row = {"id": reference["id"], "language": reference["language"], "task": reference["task"],
               "question": reference["question"], "reference": {k: reference[k] for k in ("arxiv_id", "pages", "quote")}}
        for name, search in (("legacy_bm25_first40", legacy_search), ("current", build_fulltext_search)):
            start = time.perf_counter()
            try:
                result = search(reference["question"], corpus["papers"], corpus["pages"], top_k=top_k)
                row[name] = {**evaluate_reference(reference, result["hits"], corpus["paper_ids"]),
                             "seconds": round(time.perf_counter()-start, 4), "embedding": result.get("embedding"),
                             "candidate_count": result.get("candidate_count"),
                             "hits": [{k: h.get(k) for k in ("paper_id", "page", "passage_id", "score")} for h in result["hits"]]}
            except Exception as exc:
                row[name] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}",
                             "seconds": round(time.perf_counter()-start, 4)}
        rows.append(row)
        print("EVALUATED", reference["id"], row["legacy_bm25_first40"].get("page_rank"),
              row["current"].get("page_rank"), flush=True)
    summaries = {}
    metric_keys = [f"{kind}_hit@{k}" for kind in ("page", "quote") for k in (1, 3, 5, 12)]
    for name in ("legacy_bm25_first40", "current"):
        valid = [r[name] for r in rows if "error" not in r[name]]
        summaries[name] = {"questions": len(rows), "completed": len(valid), "errors": len(rows)-len(valid),
                           "metric_denominator": "all_questions_errors_count_as_misses",
                           "metrics": {key: round(sum(r.get(key, 0) for r in valid)/len(rows), 4) if rows else None
                                       for key in metric_keys},
                           "by_language": {
                               language: {"questions": len(group),
                                          "metrics": {key: round(sum(r[name].get(key, 0) for r in group)/len(group), 4)
                                                      for key in metric_keys}}
                               for language in sorted({r["language"] for r in rows})
                               if (group := [r for r in rows if r["language"] == language])},
                           "seconds_total": round(sum(row[name].get("seconds", 0) for row in rows), 4)}
    implementation_files = ("fulltext_search.py", "retrieval_rank.py", "map_builder.py", "document_processing.py", "research_eval.py")
    return {"protocol": "developer_curated_source_location_v1", "baseline": "Frozen legacy-style BM25 first40 + same reranker",
            "implementation_sha256": {name: sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                      for name in implementation_files},
            "corpus_policy": "same parsed page text and same target papers for both algorithms; references fixed before scoring",
            "limitations": ["开发者基于公开PDF整理的9题小样本；不是独立双人盲评。",
                            "指标衡量指定已知参考内容的页码和摘录命中，不是开放文献召回率或回答正确率。",
                            "计时包含本机模型加载与缓存影响，不是受控性能基准。",
                            "参考题与算法同属开发环境，结果不能外推为跨学科普遍效果。"],
            "summary": summaries, "questions": rows}
