from types import SimpleNamespace

import pytest

from src.fulltext_search import build_fulltext_search, chunk_pages


def test_chunk_pages_preserves_paper_page_and_hash():
    papers = {"p1": SimpleNamespace(title="Dense Retrieval")}
    chunks = chunk_pages(papers, {"p1": ["Introduction\nDense retrieval finds scientific papers."]}, max_chars=40, overlap=5)
    assert chunks
    assert chunks[0].paper_id == "p1"
    assert chunks[0].page == 1
    assert len(chunks[0].text_sha256) == 64


def test_hybrid_fulltext_search_returns_locatable_relevant_passage(monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    papers = {
        "p1": SimpleNamespace(title="Retrieval paper"),
        "p2": SimpleNamespace(title="Philosophy paper"),
    }
    result = build_fulltext_search(
        "scientific retrieval evidence",
        papers,
        {"p1": ["Methods\nScientific retrieval provides traceable evidence."],
         "p2": ["Kant discusses freedom and moral philosophy."]},
    )
    assert result["algorithm"] == "bm25_specter2_passage_rerank"
    assert result["passage_count"] == 2
    assert result["hits"][0]["paper_id"] == "p1"
    assert result["hits"][0]["page"] == 1
    assert len(result["hits"][0]["text_sha256"]) == 64


def test_no_fulltext_has_explicit_empty_result():
    result = build_fulltext_search("query", {}, {})
    assert result["passage_count"] == 0
    assert result["hits"] == []
    assert result["embedding"]["reason"] == "no parsed fulltext"


def test_candidate_recall_covers_papers_after_first_forty_passages(monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    papers = {"p1": SimpleNamespace(title="Early pages"), "p2": SimpleNamespace(title="Research methods")}
    result = build_fulltext_search("研究方法 数据集 指标", papers, {
        "p1": ["Unrelated introduction and history."] * 60,
        "p2": ["Methods\nDataset evaluation compares model accuracy and recall."],
    }, candidate_policy="union")
    assert result["hits"][0]["paper_id"] == "p2"
    assert "dataset" in result["expanded_query"]
    assert result["candidate_policy"] == "bm25_hash_recall_union_with_per_paper_coverage"


def test_specific_chinese_research_terms_are_transparent_and_default_shortlist_bounded(monkeypatch):
    from src.fulltext_search import expand_query
    expanded = expand_query("冻结预训练权重和低秩矩阵，显存量化与数据增强")
    assert all(term in expanded for term in ("frozen", "pretrained", "matrix", "quantization", "augmentation"))
    assert "methodology" not in expanded
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    result = build_fulltext_search("training memory", {"p": SimpleNamespace(title="Research")},
                                   {"p": [f"Training memory procedure number {i}" for i in range(60)]})
    assert result["candidate_count"] == 40
    assert result["candidate_policy"] == "bm25_first40_with_zero_overlap_paper_coverage"


def test_no_lexical_match_still_includes_each_paper_in_model_candidates(monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    from src.fulltext_search import _rank_candidates
    _rank_candidates.cache_clear()
    seen = set()
    def rank(question, hits):
        seen.update(p.paper_id for p in hits)
        for p in hits: p.semantic_score = 1.0 if p.paper_id == "p2" else 0.0
        return hits, {"backend": "test"}
    monkeypatch.setattr("src.retrieval_rank.rank_hits", rank)
    result = build_fulltext_search("完全不同的中文问题", {"p1": SimpleNamespace(title="A"), "p2": SimpleNamespace(title="B")},
                                   {"p1": ["History."] * 60, "p2": ["Later paper."]})
    assert seen == {"p1", "p2"}
    assert result["hits"][0]["paper_id"] == "p2"
    _rank_candidates.cache_clear()


def test_stopping_fulltext_search_skips_remaining_inference_batches(monkeypatch):
    from src.tasks import TaskCancelled

    batches = []

    def rank(question, hits):
        batches.append(len(hits))
        return hits, {"backend": "test"}

    def check():
        if batches:
            raise TaskCancelled("Stop after the first batch")

    monkeypatch.setattr("src.retrieval_rank.rank_hits", rank)
    monkeypatch.setattr("src.tasks.check_cancelled", check)
    with pytest.raises(TaskCancelled):
        build_fulltext_search("stop sample", {"p": SimpleNamespace(title="Research")},
                              {"p": [f"Stop sample report {i}." for i in range(30)]})
    assert batches == [12]
