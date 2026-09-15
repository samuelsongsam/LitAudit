from types import SimpleNamespace

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
