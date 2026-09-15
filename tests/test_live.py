from pathlib import Path

from src.config import ROOT, load_settings
from src.http_fetch import FetchResult
from src.io_utils import load_dataset
from src.live_ingest import ingest_live
from src.retrieve import (
    LiveHit,
    build_query_plan,
    expand_question,
    merge_duplicate_hits,
    parse_openalex,
    parse_semantic_scholar,
    to_arxiv_query,
    to_provider_query,
)
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


def test_provider_parsers_keep_fulltext_and_discovery_metadata():
    openalex = b'''{"meta":{"count":1},"results":[{"id":"https://openalex.org/W1","display_name":"A Study","doi":"https://doi.org/10.1/example","publication_year":2025,"primary_location":{"landing_page_url":"https://doi.org/10.1/example","source":{"display_name":"Journal"}},"best_oa_location":{"pdf_url":"https://repository.example/paper.pdf"},"cited_by_count":9,"referenced_works":["W2","W3"],"topics":[{"display_name":"Information Retrieval"}],"type":"article"}]}'''
    oa_hits, _ = parse_openalex(openalex)
    assert oa_hits[0].open_access_pdf_url == "https://repository.example/paper.pdf"
    assert oa_hits[0].citation_count == 9
    assert oa_hits[0].reference_count == 2
    assert oa_hits[0].fields_of_study == ["Information Retrieval"]

    semantic = b'''{"total":1,"data":[{"paperId":"S1","title":"A Study","url":"https://www.semanticscholar.org/paper/S1","externalIds":{"DOI":"10.1/example"},"openAccessPdf":{"url":"https://publisher.example/paper.pdf"},"citationCount":11,"referenceCount":3,"fieldsOfStudy":["Computer Science"],"publicationTypes":["JournalArticle"],"tldr":{"text":"A concise result."}}]}'''
    s2_hits, _ = parse_semantic_scholar(semantic)
    assert s2_hits[0].source_id == "S1"
    assert s2_hits[0].semantic_scholar_id == "S1"
    assert s2_hits[0].open_access_pdf_url == "https://publisher.example/paper.pdf"
    assert s2_hits[0].tldr == "A concise result."


def test_duplicate_provider_hits_merge_richer_metadata():
    common = dict(title="A Study", authors=[], year=2025, venue=None, doi_or_arxiv="10.1/example", url="https://doi.org/10.1/example", dedup_key="doi:10.1/example")
    first = LiveHit(source="openalex", abstract=None, citation_count=9, fields_of_study=["Retrieval"], **common)
    second = LiveHit(source="semantic_scholar", abstract="A longer abstract.", open_access_pdf_url="https://publisher.example/paper.pdf", citation_count=11, tldr="Summary", **common)
    merged = merge_duplicate_hits([first, second])
    assert len(merged) == 1
    assert merged[0].abstract == "A longer abstract."
    assert merged[0].open_access_pdf_url == "https://publisher.example/paper.pdf"
    assert merged[0].citation_count == 11
    assert merged[0].fields_of_study == ["Retrieval"]


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
    assert len(merged.research_questions) == 1
    assert merged.research_questions[0].text.startswith("检索增强")
    assert len(merged.query_plans) == 1
    assert merged.query_plans[0].status.value == "executed"
    assert set(merged.query_plans[0].query_ids) == {item.query_id for item in merged.queries if item.query_id.startswith("q-live-")}
    assert len(merged.source_snapshots) == len(report["retrieval"])
    assert any(item.status.value == "success" and item.content_sha256 for item in merged.source_snapshots)
    assert any(item.status.value == "zero_results" for item in merged.source_snapshots)
    assert any(item.status.value == "rate_limited" and item.error_code == "http_429" for item in merged.source_snapshots)


def test_expand_question_removes_chat_instructions():
    expanded = expand_question("请检索 ai agent 中自审查 debug 对 vibe coding 质量的影响，比较人工审查，限定 CCFA 类会议论文，输出论文列表")
    assert "请检索" not in expanded
    assert "输出论文列表" not in expanded
    assert "ai agent" in expanded
    assert "vibe coding" in expanded


def test_custom_topic_does_not_add_default_rag_query():
    specs = build_query_plan("核心概念：理性、自由、绝对精神")
    assert specs[0].query_id == "q-live-arxiv-user"
    assert all("retrieval-augmented" not in spec.query for spec in specs)
    assert all(spec.query_id != "q-live-risk" for spec in specs)
    arxiv = next(spec for spec in specs if spec.source == "arxiv")
    openalex = next(spec for spec in specs if spec.source == "openalex")
    assert "reason" in arxiv.query or "rationality" in arxiv.query
    assert "freedom" in openalex.query or "reason" in openalex.query


def test_gpu_topic_uses_broad_english_provider_queries():
    specs = build_query_plan("现代GPU微架构（如NVIDIA Hopper/Ada、AMD RDNA/CDNA）的技术细节与性能对比")
    arxiv = next(spec for spec in specs if spec.source == "arxiv")
    openalex = next(spec for spec in specs if spec.source == "openalex")
    assert " OR " in arxiv.query
    assert "all:hopper" in arxiv.query
    assert "all:rdna" in arxiv.query
    assert "all:microarchitecture" not in arxiv.query
    assert "现代" not in openalex.query
    assert "gpu" in openalex.query
    assert "hopper" in openalex.query


def test_custom_gpu_screening_does_not_require_rag_terms():
    result = screen_title_abstract(
        "Dissecting the NVIDIA Hopper GPU Architecture",
        "We analyze the H100 GPU microarchitecture, tensor cores, and memory hierarchy.",
        2024,
        research_query="modern GPU microarchitecture NVIDIA Hopper AMD RDNA CDNA",
    )
    assert result.decision == PaperDecision.include
    assert result.reason_code == "custom_gpu_architecture_match"

    unrelated = screen_title_abstract(
        "Air pollution modelling using a graphics processing unit with CUDA",
        "A general CUDA implementation on an NVIDIA GPU accelerates simulation.",
        2024,
        research_query="modern GPU microarchitecture NVIDIA Hopper AMD RDNA CDNA",
    )
    assert unrelated.decision == PaperDecision.exclude
    assert unrelated.reason_code == "custom_gpu_application_only"

    hardware_usage_only = screen_title_abstract(
        "A Deep Learning Pipeline for Epilepsy Genomic Analysis Using NVIDIA H100",
        "The workload runs on an NVIDIA H100 Tensor Core GPU based on Hopper architecture.",
        2025,
        research_query="modern GPU microarchitecture NVIDIA Hopper AMD RDNA CDNA",
    )
    assert hardware_usage_only.decision == PaperDecision.pending
    assert hardware_usage_only.reason_code == "custom_gpu_model_only"


def test_multi_agent_debate_query_avoids_generic_review_terms():
    question = "multi-agent debate 综述 经典论文 方法原理 数学逻辑推理 框架设计"
    expanded = expand_question(question)
    assert "literature review" not in expanded
    assert "classical" not in expanded
    specs = build_query_plan(question)
    arxiv = next(spec for spec in specs if spec.source == "arxiv")
    provider = next(spec for spec in specs if spec.source == "openalex")
    assert "literature review" not in arxiv.query.lower()
    assert "classical" not in arxiv.query.lower()
    assert "debate" in arxiv.query.lower()
    assert "debate" in provider.query
    assert "multi-agent" in provider.query or "multi" in provider.query


def test_unrelated_literature_review_excluded_for_debate_topic():
    research_query = expand_question("multi-agent debate 综述 经典论文")
    unrelated = screen_title_abstract(
        "Erdheim-Chester Disease: review of the literature",
        "We review the published literature on this rare histiocytic disorder.",
        2013,
        research_query=research_query,
    )
    assert unrelated.decision == PaperDecision.exclude
    assert unrelated.reason_code == "custom_topic_mismatch"


def test_debate_paper_included_for_debate_topic():
    research_query = expand_question("multi-agent debate 方法原理 框架设计")
    debate_paper = screen_title_abstract(
        "Multi-Agent Debate for LLM Reasoning and Verification",
        "We propose a multi-agent debate framework where language models argue and refine answers.",
        2024,
        research_query=research_query,
    )
    assert debate_paper.decision == PaperDecision.include
    assert debate_paper.reason_code == "custom_topic_match"


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


def test_existing_hit_visible_across_run_modules(tmp_path, monkeypatch):
    import re
    from src.answer_audit import scoped_payload
    from src.ui.payload import build_payload, build_audit_report, ask_payload
    from src.conversation import build_chat_response, Intent, classify_intent
    import src.live_ingest as live_module
    xml = re.sub(r"  <entry>\s*<id>http://arxiv.org/abs/2601[\s\S]*?</entry>", "", MINI_XML)
    def fetch(url, **kwargs):
        body = b'{"meta":{"count":0},"results":[]}' if "openalex" in url else b'{"total":0,"data":[]}' if "semanticscholar" in url else xml.encode()
        return FetchResult(url=url, status=200, body=body)
    original = live_module.ingest_live
    monkeypatch.setattr(live_module, "ingest_live", lambda *a, **k: original(*a, **k, fetch=fetch))
    settings = load_settings(runs_dir=tmp_path, offline=False)
    result = run_pipeline(settings, question="PaperQA scientific literature")
    assert result["live"]["added_paper_ids"] == []
    assert result["live"]["matched_paper_ids"] == ["paper-001"]
    payload = build_payload(tmp_path, result["run_id"])
    assert [p["paper_id"] for p in scoped_payload(payload)["papers"]] == ["paper-001"]
    assert payload["workspace"]["candidate_count"] == payload["eval"]["paper_count"] == 1
    assert {n["paper_id"] for n in payload["map"]["nodes"]} == {"paper-001"}
    assert payload["map"]["algorithm"] == "specter2_cosine_network"
    assert ask_payload(tmp_path, result["run_id"], "SciMON")["papers"] == []
    assert ask_payload(tmp_path, result["run_id"], "PaperQA")["papers"][0]["paper_id"] == "paper-001"
    report, _ = build_audit_report(tmp_path, result["run_id"])
    assert "PaperQA" in report
    assert "SciMON" not in report
    def route(message, visible, *args):
        assert [p["paper_id"] for p in visible["papers"]] == ["paper-001"]
        return {"action": "direct_answer"}
    monkeypatch.setattr("src.conversation._llm_route", route)
    assert classify_intent("PaperQA", payload).direct_answer
    monkeypatch.setattr("src.conversation._llm_overview", lambda *a: ("overview", "llm"))
    chat = build_chat_response(payload, "PaperQA", Intent("requery", 1, "test", True), settings)
    assert [p["paper_id"] for p in chat["papers"]] == ["paper-001"]
    assert chat["paper_selection"]["added_count"] == 0
    assert chat["paper_selection"]["matched_count"] == 1
    from src.pipeline import upgrade_audit
    upgraded = upgrade_audit(settings, result["run_id"])
    audit = build_payload(tmp_path, upgraded["run_id"])
    assert audit["live"]["matched_paper_ids"] == ["paper-001"]
    assert audit["eval"]["paper_count"] == 1
    assert {d["paper_id"] for d in audit["fulltext_audit"]["documents"]} == {"paper-001"}
