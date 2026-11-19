from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from src.io_utils import write_json, write_jsonl
from src.research_workspace import (
    export_method_csv, fork_workspace, method_comparison, save_review,
    search_fulltext, workspace_payload,
)


@pytest.fixture
def research_run(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    runs = tmp_path / "runs"
    run = runs / "study"
    output = run / "output"
    output.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": "study", "offline": True})
    write_json(output / "search_queries.json", [])
    papers = [{"paper_id": key, "title": title, "source": "arxiv", "url": "https://arxiv.org/abs/test",
               "retrieved_at": "2026-11-04", "dedup_key": key, "decision": "include", "reason": "test"}
              for key, title in [("p1", "Retrieval methods"), ("p2", "Other methods")]]
    write_jsonl(output / "papers.jsonl", papers)
    write_jsonl(output / "paper_cards.jsonl", papers)
    cache = run / "cache" / "audit"
    cache.mkdir(parents=True)
    documents = []
    for key in ["p1", "p2"]:
        text = f"Methods\nThe {key} method uses retrieval. Dataset includes 100 samples. Accuracy and recall compare baseline models on GPU hardware."
        write_json(cache / f"{key}.json", [{"page": 1, "text": "Introduction\nResearch objective."}, {"page": 2, "text": text}])
        (cache / f"{key}.pdf").write_bytes(b"%PDF-demo")
        documents.append({"paper_id": key, "text_path": f"cache/audit/{key}.json", "response_path": f"cache/audit/{key}.pdf", "status": "parsed"})
    write_json(output / "fulltext_audit.json", {"documents": documents})
    return runs, run


def test_search_and_section_filter_preserve_real_page(research_run):
    runs, _ = research_run
    result = search_fulltext(runs, "study", "这些论文采用什么方法", ["p1"], "方法")
    assert result["hits"]
    assert all(h["paper_id"] == "p1" and h["page"] == 2 for h in result["hits"])
    assert result["hits"][0]["pdf_url"].endswith("/p1#page=2")
    assert "method" in result["expanded_query"]


def test_live_scope_does_not_leak_inherited_fulltext(research_run):
    runs, run = research_run
    write_json(run / "run_manifest.json", {"run_id": "study", "offline": False, "live": {"matched_paper_ids": ["p2"]}})
    result = search_fulltext(runs, "study", "methods")
    assert {h["paper_id"] for h in result["hits"]} == {"p2"}
    with pytest.raises(ValueError, match="研究范围"):
        search_fulltext(runs, "study", "methods", ["p1"])
    with pytest.raises(ValueError):
        save_review(runs, "study", {"passage_id": "p1:p2:c1", "status": "accepted"})


def test_review_uses_server_original_and_keeps_human_source(research_run):
    runs, _ = research_run
    result = save_review(runs, "study", {"passage_id": "p1:p2:c1", "status": "accepted", "field": "method",
                                         "text": "FAKE", "text_sha256": "FAKE", "claim": "用户记录的方法", "note": "已核对"})
    review = result["review"]
    assert "Dataset" in review["text"] and review["text_sha256"] != "FAKE"
    assert review["review_source"] == "human"
    card = method_comparison(runs, "study", ["p1"])["papers"][0]
    assert card["fields"]["method"]["status"] == "accepted"
    assert card["fields"]["method"]["review"]["note"] == "已核对"
    assert card["fields"]["data"]["status"] == "pending"


def test_review_changes_have_audit_history(research_run):
    runs, _ = research_run
    body = {"passage_id": "p1:p2:c1", "status": "accepted", "field": "method"}
    save_review(runs, "study", body)
    save_review(runs, "study", {**body, "status": "rejected", "note": "重新阅读后修改"})
    review = workspace_payload(runs, "study")["reviews"][0]
    assert review["status"] == "rejected" and review["history"][0]["status"] == "accepted"


def test_protected_review_forks_without_changing_gold(research_run):
    runs, run = research_run
    protected = runs / "phase2-real"
    run.rename(protected)
    before = {p.relative_to(protected): p.read_bytes() for p in protected.rglob("*") if p.is_file()}
    result = save_review(runs, "phase2-real", {"passage_id": "p1:p2:c1", "field": "data", "status": "accepted"})
    assert result["run_id"].startswith("workspace_")
    after = {p.relative_to(protected): p.read_bytes() for p in protected.rglob("*") if p.is_file()}
    assert before == after
    assert workspace_payload(runs, result["run_id"])["reviews"][0]["status"] == "accepted"
    assert search_fulltext(runs, result["run_id"], "method")["hits"]


def test_concurrent_reviews_do_not_lose_fields(research_run):
    runs, _ = research_run
    fields = ["task", "method", "data", "metrics", "resources", "baseline"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda field: save_review(runs, "study", {"passage_id": "p1:p2:c1", "field": field, "status": "accepted"}), fields))
    assert len(workspace_payload(runs, "study")["reviews"]) == len(fields)


def test_missing_fulltext_is_explicit_and_unknown_review_rejected(research_run):
    runs, run = research_run
    (run / "cache/audit/p1.json").unlink()
    result = search_fulltext(runs, "study", "method", ["p1"])
    assert result["hits"] == [] and result["missing_paper_ids"] == ["p1"]
    with pytest.raises(ValueError):
        save_review(runs, "study", {"passage_id": "p1:p2:c1", "status": "accepted"})


def test_export_preserves_human_status_and_escapes_formula(research_run):
    runs, _ = research_run
    save_review(runs, "study", {"passage_id": "p1:p2:c1", "field": "method", "status": "accepted", "note": "=HYPERLINK(test)"})
    output = export_method_csv(runs, "study", ["p1"])
    assert output.startswith("\ufeff")
    assert "accepted" in output and "'=HYPERLINK(test)" in output
