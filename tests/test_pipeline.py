from pathlib import Path

import pytest

from src.ask import ask
from src.config import load_settings
from src.eval_metrics import evaluate
from src.io_utils import load_dataset
from src.pipeline import run_pipeline
from src.replay import load_run
from src.schema import dataset_stats


def test_real_data_keeps_pending_and_exclude(tmp_path: Path):
    settings = load_settings(runs_dir=tmp_path)
    dataset = load_dataset(settings.data_dir)
    stats = dataset_stats(dataset)
    assert stats["error_count"] == 0
    assert stats["paper_count"] == 7
    assert stats["decision_counts"]["pending"] == 0
    assert stats["decision_counts"]["exclude"] == 5
    assert stats["decision_counts"]["include"] == 2
    assert stats["paper_card_count"] == 7
    assert stats["claim_count"] == 8
    assert stats["claim_decision_count"] == 8
    assert stats["evidence_count"] == 14
    assert stats["verified_evidence_count"] == 14
    assert stats["page_locator_count"] == 14
    assert stats["falsification_count"] == 2
    assert stats["retrieval_run_count"] == 14
    assert stats["retrieval_failure_count"] >= 3
    assert stats["claim_status_counts"]["pending"] == 2
    paper = next(item for item in dataset.papers if item.paper_id == "paper-001")
    assert paper.authors
    assert paper.abstract
    card = dataset.card_by_id()["paper-001"]
    assert card.parse_status == "pdf_partial_verified"
    limited = next(run for run in dataset.retrieval_runs if run.retrieval_id == "retrieval-010")
    assert limited.http_status == 429
    assert limited.status == "rate_limited"
    assert limited.result_count is None
    claim_008 = next(item for item in dataset.claims if item.claim_id == "claim-008")
    assert claim_008.status.value == "pending"


def test_pipeline_rejects_path_traversal_run_id(tmp_path: Path):
    settings = load_settings(runs_dir=tmp_path, offline=True)
    with pytest.raises(ValueError, match="run_id"):
        run_pipeline(settings, source="fixture", run_id="../outside")


def test_fixture_run_is_offline_and_replayable(tmp_path: Path):
    settings = load_settings(runs_dir=tmp_path, offline=True)
    result = run_pipeline(settings, source="fixture", run_id="demo")
    assert result["run_id"] == "demo"
    replayed = load_run(tmp_path, "demo")
    stats = dataset_stats(replayed["dataset"])
    assert stats["fixture_paper_count"] == 1
    assert stats["paper_count"] == 0
    assert (tmp_path / "demo" / "output" / "map.json").exists()
    assert replayed["manifest"]["offline"] is True


def test_offline_data_run_snapshots_screening_reasons(tmp_path: Path):
    settings = load_settings(runs_dir=tmp_path, offline=True)
    result = run_pipeline(settings, source="data", run_id="from-data")
    replayed = load_run(tmp_path, result["run_id"])
    from src.schema import latest_screening_by_paper

    reasons = {paper_id: log.reason_code for paper_id, log in latest_screening_by_paper(replayed["dataset"].screening).items()}
    assert reasons["paper-004"] == "general_web_qa_verified_abstract"
    assert reasons["paper-001"] == "in_scope_pdf_partial"
    assert all(paper.decision.value in {"include", "exclude", "pending"} for paper in replayed["dataset"].papers)
    assert (tmp_path / result["run_id"] / "output" / "paper_cards.jsonl").exists()
    assert (tmp_path / result["run_id"] / "output" / "claim_decisions.jsonl").exists()
    assert (tmp_path / result["run_id"] / "output" / "retrieval_runs.jsonl").exists()
    map_payload = replayed["map"]
    assert map_payload["edges"]
    assert map_payload["contradictions"]
    assert any(edge["kind"] == "evidence_conflict" for edge in map_payload["edges"])
    assert any(edge["kind"] == "falsification" for edge in map_payload["edges"])
    assert any(track["track_id"] == "sciqa" for track in map_payload["tracks"])
    assert any("verified=" in note for note in replayed["manifest"]["limitations"])


def test_evaluate_reports_traceability_delta():
    metrics = evaluate(load_settings().root)
    assert metrics["question_count"] == 3
    assert metrics["verified_evidence_rate"] == 1.0
    assert metrics["page_locator_rate"] == 1.0
    assert metrics["baseline"]["evidence_locator_rate"] == 0.0
    assert metrics["delta_vs_no_retrieval"]["verified_evidence_rate"] == 1.0
    assert metrics["pending_claim_rate"] > 0


def test_ask_returns_local_hits_without_inventing_papers():
    dataset = load_dataset(load_settings().data_dir)
    result = ask(dataset, "PaperQA LitQA scientific literature RAG agent")
    assert result["papers"]
    assert result["papers"][0]["paper_id"] == "paper-001"
    empty = ask(dataset, "qzxqzxqzxqzx")
    assert empty["papers"] == []
    assert empty["claims"] == []
