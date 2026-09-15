from dataclasses import dataclass

from src.retrieval_rank import lexical_score, rank_hits


@dataclass
class Hit:
    title: str
    abstract: str
    citation_count: int = 0
    semantic_score: float | None = None
    lexical_score: float | None = None
    ranking_score: float | None = None


def test_lexical_score_rewards_query_terms():
    assert lexical_score("graph retrieval", "Graph based retrieval") == 1.0
    assert lexical_score("graph retrieval", "unrelated philosophy") == 0.0


def test_rank_hits_records_scores_and_backend(monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    hits = [Hit("Unrelated", "other topic"), Hit("Graph retrieval", "semantic search")]
    ranked, metadata = rank_hits("graph retrieval", hits)
    assert ranked[0].title == "Graph retrieval"
    assert ranked[0].ranking_score > ranked[1].ranking_score
    assert metadata["backend"] == "hash"
    assert metadata["weights"] == {"semantic": 0.75, "lexical": 0.20, "citations": 0.05}
