"""Optional semantic-map dependencies must not block saved research reading."""
from dataclasses import replace
from datetime import date

from src.config import load_settings
from src.io_utils import read_json, write_json
from src.pipeline import retry_map, snapshot_dataset
from src.schema import Dataset, PaperCard, dataset_stats
from src.ui.payload import build_payload


def _research(tmp_path):
    settings = replace(load_settings(), root=tmp_path, runs_dir=tmp_path / "runs")
    run = settings.runs_dir / "saved-research"
    paper = PaperCard(paper_id="p", title="A saved research paper", abstract="A source abstract.",
                      url="https://example.test/saved-paper",
                      source="local-test", retrieved_at=date(2026, 1, 1), dedup_key="p",
                      decision="include", reason="Saved before optional map dependencies were removed")
    dataset = Dataset(papers=[paper], paper_cards=[paper.model_copy(deep=True)])
    snapshot_dataset(dataset, run / "output")
    write_json(run / "run_manifest.json", {"run_id": run.name, "offline": True,
                                           "status": "completed", "question": "Read a saved study", "errors": []})
    write_json(run / "stats.json", dataset_stats(dataset))
    return settings, run


def test_missing_optional_map_dependencies_preserve_readable_papers(tmp_path, monkeypatch):
    settings, run = _research(tmp_path)
    def unavailable(*args, **kwargs):
        raise ImportError("No module named adapters")
    monkeypatch.setattr("src.ui.payload.build_map", unavailable)
    payload = build_payload(settings.runs_dir, run.name)
    assert payload["papers"][0]["title"] == "A saved research paper"
    assert payload["map"]["status"] == "unavailable"
    assert payload["map"]["embedding"]["backend"] == "unavailable"
    assert "adapters" in payload["map"]["embedding"]["reason"]
    assert payload["map"]["nodes"] == []


def test_map_retry_dependency_failure_saves_partial_and_keeps_dataset(tmp_path, monkeypatch):
    settings, run = _research(tmp_path)
    papers_before = (run / "output/papers.jsonl").read_bytes()
    def unavailable(*args, **kwargs):
        raise ImportError("No module named transformers")
    monkeypatch.setattr("src.pipeline.build_map", unavailable)
    result = retry_map(settings, run.name)
    assert result["status"] == "partial"
    assert result["error"]["stage"] == "map"
    assert result["error"]["type"] == "ImportError"
    assert result["map"]["status"] == "unavailable"
    assert (run / "output/papers.jsonl").read_bytes() == papers_before
    manifest = read_json(run / "run_manifest.json")
    assert manifest["stages"]["map"]["status"] == "failed"
    assert manifest["status"] == "partial"
    assert read_json(run / "output/map.json")["status"] == "unavailable"
    payload = build_payload(settings.runs_dir, run.name)
    assert payload["papers"][0]["paper_id"] == "p"


def test_capability_probe_tolerates_loaded_optional_module_without_spec(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    from src.cli import runtime_capabilities
    settings = replace(load_settings(), runs_dir=tmp_path / "runs")
    monkeypatch.setitem(sys.modules, "adapters", ModuleType("adapters"))
    result = runtime_capabilities(settings)
    assert "adapters" in result["semantic_model"]["missing_dependencies"]
    assert result["semantic_model"]["ready"] is False
    assert result["storage"]["writable"] is True
