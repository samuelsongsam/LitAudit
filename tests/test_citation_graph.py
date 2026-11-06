import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from src.http_fetch import FetchResult
from src.retrieve import fetch_related_hits, related_paper_identifier


@pytest.mark.parametrize("direction,filter_name,expected_edge", [
    ("references", "cited_by", ("W1", "W2")),
    ("citations", "cites", ("W2", "W1")),
])
def test_related_papers_use_openalex_and_preserve_edge_direction(tmp_path, direction, filter_name, expected_edge):
    def fetch(url, *, headers, **kwargs):
        request = urlparse(url)
        assert request.hostname == "api.openalex.org"
        assert headers == {"Authorization": "Bearer configured-key"}
        assert parse_qs(request.query)["filter"] == [f"{filter_name}:W1"]
        return FetchResult(url, 200, json.dumps({"meta": {"count": 1}, "results": [
            {"id": "https://openalex.org/W2", "display_name": "Adjacent study", "publication_year": 2024},
        ]}).encode())

    bundle = fetch_related_hits("https://openalex.org/W1", direction, cache_dir=tmp_path,
                                api_key="configured-key", fetch=fetch)
    assert [hit.title for hit in bundle.hits] == ["Adjacent study"]
    graph = bundle.citation_graph
    assert graph["algorithm"] == "openalex_one_hop"
    assert graph["seed_count"] == graph["edge_count"] == 1
    edge, = graph["edges"]
    assert (edge["source"], edge["target"]) == expected_edge
    assert bundle.runs[0].status == "success" and Path(bundle.runs[0].response_path).is_file()
    assert "configured-key" not in bundle.runs[0].request


@pytest.mark.parametrize("identifier,expected", [("DOI:10.1/seed", "10.1/seed"),
    ("arXiv:2401.01234v2", "10.48550/arxiv.2401.01234")])
def test_related_papers_resolve_standard_identifier_and_record_both_requests(tmp_path, identifier, expected):
    def fetch(url, **kwargs):
        request = urlparse(url)
        assert request.hostname == "api.openalex.org"
        if request.path == "/works":
            assert parse_qs(request.query)["filter"] == ["cited_by:W1"]
            return FetchResult(url, 200, b'{"results":[],"meta":{"count":0}}')
        assert request.path == f"/works/https://doi.org/{expected}"
        return FetchResult(url, 200, b'{"id":"https://openalex.org/W1"}')

    bundle = fetch_related_hits(identifier, "references", cache_dir=tmp_path, fetch=fetch)
    assert [row["step"] for row in bundle.citation_graph["requests"]] == ["lookup", "references"]
    assert bundle.citation_graph["edge_count"] == 0 and bundle.coverage["openalex"]["status"] == "success"
    assert all(Path(run.response_path).is_file() for run in bundle.runs)


def test_related_rate_limit_remains_a_failed_request_not_zero_results(tmp_path):
    bundle = fetch_related_hits("W1", "references", cache_dir=tmp_path,
                                fetch=lambda url, **kwargs: FetchResult(url, 429, b'{}'))
    assert bundle.hits == [] and bundle.runs[0].status == "rate_limited"
    assert bundle.runs[0].result_count is None and bundle.citation_graph["failure_count"] == 1


def test_retired_only_identifier_is_not_used_for_citation_exploration(tmp_path):
    paper = SimpleNamespace(source_id="s2-only", doi_or_arxiv=None,
                            url="https://www.semanticscholar.org/paper/s2-only")
    assert related_paper_identifier(paper) is None
    with pytest.raises(ValueError, match="OpenAlex ID"):
        fetch_related_hits(paper.source_id, "references", cache_dir=tmp_path,
                           fetch=lambda *args, **kwargs: pytest.fail("Unexpected provider request"))
