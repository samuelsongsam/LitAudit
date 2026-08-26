from pathlib import Path

from src.config import load_settings
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
    assert stats["claim_count"] == 8
    assert stats["evidence_count"] == 10
    assert stats["falsification_count"] == 2
    paper = next(item for item in dataset.papers if item.paper_id == "paper-001")
    assert paper.authors
    assert paper.abstract


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
    reasons = {log.paper_id: log.reason_code for log in replayed["dataset"].screening}
    assert reasons["paper-004"] == "general_web_qa_verified_abstract"
    assert reasons["paper-001"] == "in_scope_verified_abstract"
    assert all(paper.decision.value in {"include", "exclude", "pending"} for paper in replayed["dataset"].papers)
