import json
import shutil
from pathlib import Path

import pytest

from src.audit_enrichment import enrich_audit
from src.cli import runtime_capabilities
from src.config import load_settings
from src.io_utils import load_dataset, read_json
from src.pipeline import retry_map, run_pipeline
from src.replay import list_runs, load_run
from src.run_paths import as_run_relative, resolve_run_file


def test_relocated_windows_snapshot_resolves_only_local_run_files(tmp_path):
    run = tmp_path / "new-location" / "renamed-run"
    pdf = run / "cache" / "audit" / "document.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF local snapshot")
    assert as_run_relative(run, pdf) == "cache/audit/document.pdf"
    assert resolve_run_file(run, "cache/audit/document.pdf") == pdf
    old = r"C:\Users\original\LitAudit\runs\previous-run\cache\audit\document.pdf"
    assert resolve_run_file(run, old) == pdf
    assert resolve_run_file(run, "/old/LitAudit/runs/previous-run/cache/audit/document.pdf") == pdf
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    for value in (str(outside), "../private.txt", "cache/../../private.txt", "cache/./audit/document.pdf"):
        with pytest.raises(ValueError):
            resolve_run_file(run, value)
    with pytest.raises(ValueError):
        as_run_relative(run, outside)


def test_actual_audit_can_move_to_a_different_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    settings = load_settings()
    original = tmp_path / "source" / "audit-original"
    enriched = enrich_audit(load_dataset(settings.data_dir), root=settings.root,
                            run_dir=original, question="RAG evidence")
    audit = read_json(original / "output" / "fulltext_audit.json")
    parsed = [d for d in audit["documents"] if d["status"] == "parsed"]
    assert len(parsed) >= 4
    moved = tmp_path / "different-project" / "renamed-run"
    shutil.copytree(original, moved)
    for doc in parsed:
        assert not Path(doc["response_path"]).is_absolute()
        assert resolve_run_file(moved, doc["response_path"]).read_bytes().startswith(b"%PDF-")
        assert read_json(resolve_run_file(moved, doc["text_path"]))
    assert all(not Path(s.response_path).is_absolute() for s in enriched.source_snapshots if s.response_path)


def test_map_failure_keeps_checkpoint_and_can_retry(tmp_path, monkeypatch):
    from src.map_builder import build_map
    monkeypatch.setenv("LITAUDIT_MAP_EMBEDDER", "hash")
    monkeypatch.setattr("src.audit_enrichment.enrich_audit", lambda dataset, **kwargs: dataset)
    settings = load_settings(runs_dir=tmp_path, offline=True)

    def fail_map(dataset, run_id):
        manifest = read_json(tmp_path / run_id / "run_manifest.json")
        assert manifest["status"] == "running"
        assert manifest["stage"] == "map"
        assert (tmp_path / run_id / "output" / "papers.jsonl").exists()
        raise RuntimeError("model cache missing")

    monkeypatch.setattr("src.pipeline.build_map", fail_map)
    result = run_pipeline(settings, run_id="map-recovery")
    assert result["status"] == "partial"
    assert "map-recovery" in list_runs(tmp_path)
    replayed = load_run(tmp_path, "map-recovery")
    assert len(replayed["dataset"].papers) == 7
    assert replayed["map"]["embedding"]["backend"] == "unavailable"
    assert replayed["manifest"]["stages"]["map"]["status"] == "failed"
    monkeypatch.setattr("src.pipeline.build_map", build_map)
    retried = retry_map(settings, "map-recovery")
    assert retried["status"] == "completed"
    assert read_json(tmp_path / "map-recovery" / "run_manifest.json")["errors"] == []


def test_failed_retrieval_remains_visible_and_has_failure_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_MAP_EMBEDDER", "hash")
    def fail(*args, **kwargs):
        raise RuntimeError("source temporarily unavailable")
    monkeypatch.setattr("src.live_ingest.ingest_live", fail)
    with pytest.raises(RuntimeError):
        run_pipeline(load_settings(runs_dir=tmp_path, offline=False), run_id="failed-source")
    manifest = read_json(tmp_path / "failed-source" / "run_manifest.json")
    assert manifest["status"] == "failed"
    assert manifest["stage"] == "retrieval"
    assert "failed-source" in list_runs(tmp_path)
    assert (tmp_path / "failed-source" / "output" / "papers.jsonl").exists()
    from src.answer_audit import scoped_payload
    from src.ui.payload import build_payload
    payload = build_payload(tmp_path, "failed-source")
    assert scoped_payload(payload)["papers"] == []
    assert scoped_payload(payload)["evidence"] == []
    assert payload["eval"]["paper_count"] == 0


def test_capabilities_report_local_configuration_without_secrets(tmp_path, monkeypatch):
    from dataclasses import replace
    settings = replace(load_settings(runs_dir=tmp_path), llm_api_key="private-test-key")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-model-cache"))
    report = runtime_capabilities(settings)
    assert report["llm"]["configured"] is True
    assert report["semantic_model"]["ready"] is False
    assert report["semantic_model"]["missing_models"]
    assert "private-test-key" not in json.dumps(report)
