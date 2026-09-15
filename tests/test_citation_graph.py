import json
from types import SimpleNamespace

from src.citation_graph import expand_citation_graph
from src.http_fetch import FetchResult


def test_citation_expansion_preserves_direction_context_and_intent(tmp_path):
    reference = {"citedPaper": {"paperId": "R1", "title": "Foundation", "year": 2020},
                 "contexts": ["We follow Foundation."], "intents": ["methodology"], "isInfluential": True}
    citation = {"citingPaper": {"paperId": "C1", "title": "Later work", "year": 2025},
                "contexts": ["We challenge Seed."], "intents": ["result"], "isInfluential": False}

    def fetch(url, **kwargs):
        row = reference if "/references?" in url else citation
        return FetchResult(url=url, status=200, body=json.dumps({"data": [row]}).encode())

    seed = SimpleNamespace(semantic_scholar_id="S1", title="Seed")
    graph = expand_citation_graph([seed], cache_dir=tmp_path, fetch=fetch)
    assert graph["seed_count"] == 1
    assert graph["edge_count"] == 2
    assert {tuple((edge["source"], edge["target"])) for edge in graph["edges"]} == {("S1", "R1"), ("C1", "S1")}
    assert graph["edges"][0]["contexts"] == ["We follow Foundation."]
    assert graph["edges"][0]["intents"] == ["methodology"]
    assert graph["edges"][0]["is_influential"] is True
    assert len(list((tmp_path / "citations").glob("*.json"))) == 2


def test_citation_expansion_records_rate_limit(tmp_path):
    def fetch(url, **kwargs):
        return FetchResult(url=url, status=429, body=b'{"message":"rate limited"}')

    seed = SimpleNamespace(semantic_scholar_id="S1", title="Seed")
    graph = expand_citation_graph([seed], cache_dir=tmp_path, fetch=fetch)
    assert graph["edge_count"] == 0
    assert graph["failure_count"] == 2
    assert all(row["status"] == "rate_limited" for row in graph["requests"])


def test_citation_expansion_is_empty_without_s2_identity(tmp_path):
    seed = SimpleNamespace(semantic_scholar_id=None, title="Seed")
    graph = expand_citation_graph([seed], cache_dir=tmp_path)
    assert graph["seed_count"] == 0
    assert graph["requests"] == []
