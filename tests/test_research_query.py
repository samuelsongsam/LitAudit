from dataclasses import replace
from datetime import date
import json
from urllib.parse import parse_qs, urlparse

import pytest

from src.cache import FileCache
from src.config import load_settings
from src.http_fetch import FetchResult
from src.live_ingest import ingest_live
from src.research_query import metadata_check, research_text, validate_constraints
from src.retrieve import (LiveHit, QuerySpec, SearchBundle, _source_urls, build_query_plan,
                          comparison_name_candidates, merge_duplicate_hits, search_all)
from src.schema import Dataset, RetrievalRun, SearchQuery


def hit(title="Federated Learning for Medical Imaging", year=2024, types=None, source="semantic_scholar"):
    return LiveHit(source=source, title=title, authors=["Example"], year=year, venue="Journal",
                   doi_or_arxiv="10.1/test", url="https://doi.org/10.1/test", abstract="A federated learning method for medical imaging.",
                   dedup_key="doi:10.1/test", publication_types=types or [])


def test_constraints_normalize_and_reject_invalid_conditions():
    assert validate_constraints({"year_from": "2020", "year_to": 2025, "method": "  联邦学习  ",
                                 "publication_type": "期刊"}) == {
        "year_from": 2020, "year_to": 2025, "method": "联邦学习", "publication_type": "journal"}
    for value in [[], {"year_from": True}, {"year_from": 2025, "year_to": 2020},
                  {"year_from": 100}, {"publication_type": []}, {"publication_type": "random"},
                  {"unknown": "value"}]:
        with pytest.raises(ValueError): validate_constraints(value)


def test_comparison_plan_preserves_joint_and_independent_named_queries():
    assert comparison_name_candidates("比较LoRA和QLoRA，只有一张GPU") == ["LoRA", "QLoRA"]
    assert comparison_name_candidates("Compare U-Net and Attention U-Net for segmentation") == ["U-Net", "Attention U-Net"]
    assert comparison_name_candidates("Compare methods for biomedical segmentation") == []
    assert comparison_name_candidates("How does LoRA work?") == []
    plan = build_query_plan("Compare U-Net and Attention U-Net", {"year_from": 2015})
    titles = [q for q in plan if "comparison-" in q.query_id]
    assert len(titles) == 2
    assert all("submittedDate:[201501010000" in q.query for q in titles)
    assert 'ti:"U-Net"' in titles[0].query and 'ti:"Attention U-Net"' in titles[1].query
    assert "all:compare" not in plan[0].query


def test_explicit_arxiv_ids_use_exact_lookup_and_keep_postfilters():
    plan = build_query_plan("请补查https://arxiv.org/abs/1505.04597和arXiv:1804.03999", {"year_from": 2015})
    assert len(plan) == 1 and plan[0].query == "id_list:1505.04597,1804.03999"
    params = parse_qs(urlparse(_source_urls(plan[0], limit=6, mailto=None)[0]).query)
    assert params["id_list"] == ["1505.04597,1804.03999"]
    assert "search_query" not in params
    assert plan[0].constraints == {"year_from": 2015}


def test_exact_lookup_no_result_does_not_fallback_to_unrelated_keyword_search(tmp_path):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return FetchResult(url, 200, b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
    bundle = search_all("arXiv:1505.04597", cache_dir=tmp_path, fetch=fetch, sleep_s=0)
    assert len(calls) == len(bundle.queries) == 1
    assert bundle.hits == []
    assert "id_list=" in calls[0]


def test_cross_language_queries_keep_object_method_and_year_constraints():
    conditions = {"year_from": 2020, "year_to": 2025, "research_object": "医学影像", "method": "联邦学习"}
    text = research_text("数据隐私", conditions)
    assert "medical imaging" in text and "federated learning" in text
    queries = build_query_plan("数据隐私", conditions)
    assert "submittedDate:[202001010000 TO 202512312359]" in queries[0].query
    assert any("medical imaging" in q.query and "federated learning" in q.query for q in queries)
    assert all(q.constraints == conditions for q in queries)


def test_provider_filter_parameters_are_explicit():
    conditions = {"year_from": 2020, "year_to": 2025, "publication_type": "journal"}
    oa = _source_urls(QuerySpec("q", "openalex", "federated learning", "search", conditions), limit=15, mailto=None)[0]
    params = parse_qs(urlparse(oa).query)
    assert "from_publication_date:2020-01-01" in params["filter"][0]
    assert "primary_location.source.type:journal" in params["filter"][0]


def test_metadata_unknown_is_not_claimed_as_a_match():
    assert metadata_check(hit(year=2018), {"year_from": 2020})["status"] == "mismatch"
    assert metadata_check(hit(year=None), {"year_from": 2020})["status"] == "unknown"
    assert metadata_check(hit(types=["article"]), {"publication_type": "journal"})["status"] == "unknown"
    assert metadata_check(hit(types=["JournalArticle"]), {"publication_type": "journal"})["status"] == "matched"
    assert metadata_check(hit(types=["preprint"]), {"publication_type": "journal"})["status"] == "mismatch"
    assert metadata_check(hit(types=["Review"]), {"publication_type": "journal"})["status"] == "unknown"


def test_duplicate_hits_keep_all_source_provenance():
    one = hit(source="openalex")
    two = replace(hit(), source_id="S2", abstract="Longer, more informative abstract text.")
    merged = merge_duplicate_hits([one, two])
    assert len(merged) == 1
    assert set(merged[0].matched_sources) == {"openalex", "semantic_scholar"}
    assert {row["source"] for row in merged[0].source_records} == {"openalex", "semantic_scholar"}


def test_search_filters_year_and_records_source_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    def fetch(url, **kwargs):
        if "openalex" in url:
            params = parse_qs(urlparse(url).query)
            if params["search"] != ["medical imaging federated learning"]:
                return FetchResult(url, 200, b'{"meta":{"count":0},"results":[]}')
            return FetchResult(url, 200, json.dumps({"meta": {"count": 2}, "results": [
                {"id": "https://openalex.org/W1", "title": "Old federated learning", "publication_year": 2018},
                {"id": "https://openalex.org/W2", "title": "New federated learning", "publication_year": 2024},
            ]}).encode())
        return FetchResult(url, 200, b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
    bundle = search_all("联邦学习医学影像", cache_dir=tmp_path, fetch=fetch, sleep_s=0,
                        constraints={"year_from": 2020})
    assert [h.title for h in bundle.hits] == ["New federated learning"]
    assert len(bundle.filter_report["excluded"]) == 1
    assert bundle.coverage["openalex"]["raw_result_count"] == 2
    assert bundle.coverage["openalex"]["visible_unique_count"] == 1


def test_unknown_type_is_pending_after_real_topic_screen(tmp_path):
    query = SearchQuery(query_id="q-new", source="semantic_scholar", query="federated learning", scope_version="test")
    bundle = SearchBundle([query], [], [hit(types=["article"])], constraints={"publication_type": "journal"})
    dataset, report = ingest_live(Dataset(), load_settings(runs_dir=tmp_path), question="federated learning medical imaging",
                                  cache=FileCache(tmp_path / "cache"), run_dir=tmp_path,
                                  search_bundle=bundle)
    assert len(dataset.papers) == 1 and dataset.papers[0].decision.value == "pending"
    assert report["paper_provenance"][dataset.papers[0].paper_id]["constraint_check"]["status"] == "unknown"
    assert dataset.research_questions[0].domain_boundary == "文献类型：journal"


def test_repeated_query_ids_are_remapped_in_incremental_discovery(tmp_path):
    query = SearchQuery(query_id="q-repeat", source="semantic_scholar", query="topic", scope_version="test")
    run = RetrievalRun(retrieval_id="r", query_id="q-repeat", source="semantic_scholar", request="https://s2/test",
                       retrieved_at=date.today(), status="success", result_count=1)
    dataset = Dataset(queries=[query])
    result, report = ingest_live(dataset, load_settings(runs_dir=tmp_path), question="federated learning medical imaging",
                                cache=FileCache(tmp_path / "cache"), run_dir=tmp_path,
                                search_bundle=SearchBundle([query], [run], [hit()]))
    assert {q.query_id for q in result.queries} == {"q-repeat", "q-repeat-r2"}
    assert result.retrieval_runs[-1].query_id == "q-repeat-r2"
    assert not [i for i in result.issues if i.level == "error"]


def test_three_independent_research_topics_have_domain_specific_queries():
    cases = [
        ("时间序列异常检测", {"method": "contrastive learning"}, "anomaly"),
        ("医学影像隐私保护", {"method": "联邦学习"}, "federated"),
        ("遥感图像分割", {"method": "transfer learning"}, "segmentation"),
    ]
    for question, conditions, signal in cases:
        plan = build_query_plan(question, conditions)
        assert any(signal in q.query for q in plan)
        assert all("PaperQA" not in q.query for q in plan)
