from types import SimpleNamespace

from src.research_eval import evaluate_reference, legacy_search, run_reference_evaluation


def test_location_metrics_keep_paper_page_and_quote_distinct():
    reference = {"arxiv_id": "1404.1100", "pages": [9], "quote": "Subtract off the mean"}
    hits = [{"paper_id": "wrong", "page": 9, "text": reference["quote"]},
            {"paper_id": "pca", "page": 9, "text": "Other sentence"},
            {"paper_id": "pca", "page": 10, "text": "SUBTRACT\nOFF THE mean before projection"}]
    result = evaluate_reference(reference, hits, {"1404.1100": "pca"})
    assert result["page_rank"] == 2 and result["quote_rank"] == 3
    assert result["page_hit@1"] == result["quote_hit@1"] == 0
    assert result["page_hit@3"] == result["quote_hit@3"] == 1


def test_legacy_baseline_really_limits_reranking_to_first40(monkeypatch):
    import src.retrieval_rank
    observed = []
    def rank(query, passages):
        observed.extend(p.passage_id for p in passages)
        for p in passages:
            p.semantic_score = 0
        return passages, {"backend": "test_double"}
    monkeypatch.setattr(src.retrieval_rank, "rank_hits", rank)
    result = legacy_search("needle", {"p": SimpleNamespace(title="Example")},
                           {"p": [f"Page {i} has needle." for i in range(55)]})
    assert result["passage_count"] == 55
    assert result["candidate_count"] == len(observed) == 40
    assert "p:p55:c1" not in observed


def test_eval_search_errors_count_as_misses(monkeypatch):
    import src.fulltext_search
    import src.research_eval
    reference = {"id": "test", "task": "pca", "language": "zh", "arxiv_id": "1404.1100",
                 "question": "问题", "pages": [9], "quote": "mean"}
    def broken(*args, **kwargs):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(src.research_eval, "legacy_search", broken)
    monkeypatch.setattr(src.fulltext_search, "build_fulltext_search", broken)
    result = run_reference_evaluation([reference], {"pca": {"papers": {}, "pages": {}, "paper_ids": {}}})
    for summary in result["summary"].values():
        assert summary["questions"] == summary["errors"] == 1
        assert summary["completed"] == 0
        assert summary["metrics"]["page_hit@12"] == 0
        assert summary["by_language"]["zh"]["metrics"]["quote_hit@3"] == 0
