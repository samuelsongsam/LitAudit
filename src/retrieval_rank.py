from __future__ import annotations

import math
import os
import re
from functools import lru_cache
from typing import Any

from src.map_builder import (
    SPECTER_ADAPTER,
    SPECTER_BASE_MODEL,
    _hash_embedding,
    _normalize,
    cosine_similarity,
    paper_embedding_text,
)

SPECTER_QUERY_ADAPTER = "allenai/specter2_adhoc_query"


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9+.#-]{1,}|[\u4e00-\u9fff]{2,}", (text or "").lower()))


def lexical_score(question: str, text: str) -> float:
    query = _terms(question)
    if not query:
        return 0.0
    document = _terms(text)
    return len(query & document) / len(query)


@lru_cache(maxsize=1)
def _load_query_model():
    from adapters import AutoAdapterModel
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(SPECTER_BASE_MODEL, local_files_only=True)
    model = AutoAdapterModel.from_pretrained(SPECTER_BASE_MODEL, local_files_only=True)
    adapter = model.load_adapter(
        SPECTER_QUERY_ADAPTER, source="hf", local_files_only=True, set_active=True
    )
    model.set_active_adapters(adapter)
    model.eval()
    return tokenizer, model, str(adapter)


def _encode(model: Any, tokenizer: Any, texts: list[str]) -> list[list[float]]:
    import torch

    inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt",
                       return_token_type_ids=False, max_length=512)
    with torch.inference_mode():
        output = model(**inputs)
    return [_normalize(row) for row in output.last_hidden_state[:, 0, :].detach().cpu().tolist()]


def rank_hits(question: str | None, hits: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    """Rank merged candidates and attach transparent component scores."""
    if not question or not hits:
        return hits, {"backend": "not_run", "reason": "question or candidates missing"}
    texts = [paper_embedding_text(hit) for hit in hits]
    backend = "hash"
    reason = None
    mode = os.getenv("LITAUDIT_RERANK_EMBEDDER", "auto").strip().lower()
    if mode not in {"auto", "specter2", "hash"}:
        raise ValueError("LITAUDIT_RERANK_EMBEDDER must be auto, specter2, or hash")
    try:
        if mode == "hash":
            raise RuntimeError("hash explicitly selected")
        query_tokenizer, query_model, query_adapter = _load_query_model()
        query_vector = _encode(query_model, query_tokenizer, [question])[0]
        from src.map_builder import _load_specter2, _encode_specter2_texts
        paper_tokenizer, _, paper_adapter = _load_specter2()
        paper_texts = tuple(paper_embedding_text(hit, separator=paper_tokenizer.sep_token or " ") for hit in hits)
        paper_vectors = [list(row) for row in _encode_specter2_texts(paper_texts)]
        backend = "specter2"
    except Exception as exc:
        if mode == "specter2":
            raise RuntimeError(f"SPECTER2 reranking unavailable: {exc}") from exc
        query_vector = _hash_embedding(question)
        paper_vectors = [_hash_embedding(text) for text in texts]
        query_adapter = None
        paper_adapter = None
        reason = f"{exc.__class__.__name__}: {exc}"

    max_citations = max((getattr(hit, "citation_count", 0) or 0 for hit in hits), default=0)
    for hit, text, vector in zip(hits, texts, paper_vectors):
        semantic = cosine_similarity(query_vector, vector)
        lexical = lexical_score(question, text)
        citations = math.log1p(getattr(hit, "citation_count", 0) or 0) / math.log1p(max_citations) if max_citations else 0.0
        hit.semantic_score = round(semantic, 6)
        hit.lexical_score = round(lexical, 6)
        hit.ranking_score = round(0.75 * semantic + 0.20 * lexical + 0.05 * citations, 6)
    hits.sort(key=lambda item: (-item.ranking_score, (item.title or "").lower()))
    return hits, {
        "backend": backend,
        "base_model": SPECTER_BASE_MODEL if backend == "specter2" else None,
        "query_adapter": SPECTER_QUERY_ADAPTER if backend == "specter2" else query_adapter,
        "paper_adapter": SPECTER_ADAPTER if backend == "specter2" else paper_adapter,
        "weights": {"semantic": 0.75, "lexical": 0.20, "citations": 0.05},
        "reason": reason,
    }
