from pathlib import Path

from src.config import ROOT, load_settings
from src.http_fetch import FetchResult
from src.io_utils import load_dataset
from src.live_ingest import ingest_live
from src.pipeline import run_pipeline
from src.retrieve import parse_arxiv, retrieval_status
from src.schema import PaperDecision, dataset_stats
from src.screen_rules import screen_title_abstract

MINI_XML = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2312.07559v2</id>
    <title>PaperQA: Retrieval-Augmented Generative Agent for Scientific Research</title>
    <summary>A RAG agent for answering questions over the scientific literature.</summary>
    <published>2023-12-08T18:50:20Z</published>
    <link href="https://arxiv.org/abs/2312.07559v2" rel="alternate" type="text/html"/>
    <author><name>Jakub Lala</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2601.00001v1</id>
    <title>PaperQA-Next: Retrieval-Augmented Generative Agent for Scientific Literature</title>
    <summary>We present an LLM retrieval-augmented agent for answering questions over the scientific literature and report LitQA results.</summary>
    <published>2026-01-02T00:00:00Z</published>
    <link href="https://arxiv.org/abs/2601.00001v1" rel="alternate" type="text/html"/>
    <author><name>Ada Example</name></author>
  </entry>
</feed>
"""


def test_screen_rules_match_gold_boundaries():
    dataset = load_dataset(load_settings().data_dir)
    expected = {
        "paper-001": PaperDecision.include,
        "paper-002": PaperDecision.exclude,
        "paper-003": PaperDecision.include,
        "paper-004": PaperDecision.exclude,
        "paper-005": PaperDecision.exclude,
        "paper-006": PaperDecision.exclude,
        "paper-007": PaperDecision.exclude,
    }
    for paper in dataset.papers:
        result = screen_title_abstract(paper.title, paper.abstract, paper.year)
        assert result.decision == expected[paper.paper_id], (paper.paper_id, result)


def test_screen_rules_pending_when_scope_unclear():
    result = screen_title_abstract(
        "Retrieving scientific papers with lexical search",
        "We index past scientific papers for nearest-neighbor retrieval without a language model.",
        2024,
    )
    assert result.decision == PaperDecision.pending


def test_http_429_is_rate_limited_not_success():
    assert retrieval_status(429, None) == "rate_limited"
    assert retrieval_status(200, None) == "success"
    assert retrieval_status(None, "timeout") == "failed"
    assert retrieval_status(500, None) == "failed"


def test_keeps_429_when_retry_fails(monkeypatch):
    from src.retrieve import _fetch_with_fallback

    monkeypatch.setattr("src.retrieve.time.sleep", lambda _: None)
    calls = {"n": 0}

    def fake_fetch(url: str, **_: object) -> FetchResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchResult(url=url, status=429, body=b"Too Many Requests")
        return FetchResult(url=url, status=None, error="timeout")

    result = _fetch_with_fallback(
        ["https://example.test/search"],
        fetch=fake_fetch,
        headers=None,
        mailto=None,
        timeout=5,
    )
    assert result.status == 429
    assert retrieval_status(result.status, result.error) == "rate_limited"


def test_parse_arxiv_cache_finds_paperqa():
    xml = (ROOT / "data/cache/retrieval-2026-08-26/arxiv/q-001-main.xml").read_bytes()
    hits, total = parse_arxiv(xml)
    assert hits
    assert total == 158
    assert any("PaperQA" in hit.title and hit.dedup_key == "arxiv:2312.07559" for hit in hits)


def test_live_ingest_merges_new_paper_and_records_429(tmp_path: Path):
    def fake_fetch(url: str, **_: object) -> FetchResult:
        if "semanticscholar" in url:
            return FetchResult(url=url, status=429, body=b'{"message":"Too Many Requests"}')
        if "openalex" in url:
            return FetchResult(url=url, status=200, body=b'{"meta":{"count":0},"results":[]}')
        return FetchResult(url=url, status=200, body=MINI_XML.encode("utf-8"))

    settings = load_settings(runs_dir=tmp_path, offline=False)
    dataset = load_dataset(settings.data_dir)
    from src.cache import FileCache

    merged, report = ingest_live(
        dataset,
        settings,
        question="检索增强是否提高科学文献问答的证据可追溯性？",
        cache=FileCache(tmp_path / "cache"),
        run_dir=tmp_path,
        fetch=fake_fetch,
    )
    stats = dataset_stats(merged)
    assert stats["error_count"] == 0
    assert "paper-008" in report["added_paper_ids"]
    assert report["added_decisions"]["paper-008"] == "include"
    assert report["skipped_duplicates"] >= 1
    paper = next(item for item in merged.papers if item.paper_id == "paper-001")
    assert paper.decision.value == "include"
    new_paper = next(item for item in merged.papers if item.paper_id == "paper-008")
    assert new_paper.parse_status == "live_abstract"
    claim_008 = next(item for item in merged.claims if item.claim_id == "claim-008")
    assert claim_008.status.value == "pending"
    assert report["claim_008"] == "pending"
    limited = [item for item in report["retrieval"] if item["http_status"] == 429]
    assert limited
    assert all(item["status"] == "rate_limited" for item in limited)
    assert all(item["result_count"] is None for item in limited)
    assert any(item.decision.value == "exclude" for item in merged.papers)


def test_online_run_does_not_overwrite_phase2_real(tmp_path: Path, monkeypatch):
    def fake_ingest(dataset, settings, **_: object):
        return dataset, {
            "added_paper_ids": [],
            "skipped_duplicates": 0,
            "retrieval": [],
            "claim_008": "pending",
        }

    monkeypatch.setattr("src.live_ingest.ingest_live", fake_ingest)
    settings = load_settings(runs_dir=tmp_path, offline=False)
    result = run_pipeline(settings, source="data", run_id="phase2-real", question="live")
    assert result["run_id"] != "phase2-real"
    assert result["run_id"].startswith("live_")
    assert result["offline"] is False
    assert not (tmp_path / "phase2-real").exists()
