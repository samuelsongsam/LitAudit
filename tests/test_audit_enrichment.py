from hashlib import sha256

from src.answer_audit import audit_answer_statements, audit_overview_statements
from src.audit_enrichment import enrich_audit
from src.config import load_settings
from src.io_utils import load_dataset, read_json
from src.pipeline import upgrade_audit
from src.schema import dataset_stats


def test_real_pdf_audit_freezes_files_and_preserves_gold(tmp_path):
    settings = load_settings()
    gold = settings.data_dir / "evidence.jsonl"
    before = gold.read_bytes()
    dataset = load_dataset(settings.data_dir)
    enriched = enrich_audit(dataset, root=settings.root, run_dir=tmp_path / "audit", question="RAG 科研问答")
    assert gold.read_bytes() == before
    assert dataset_stats(enriched)["error_count"] == 0
    assert len(enriched.evidence_spans) == 14
    assert len(enriched.decision_traces) == 8
    assert next(c for c in enriched.claims if c.claim_id == "claim-008").status.value == "pending"
    audit = read_json(tmp_path / "audit" / "output" / "fulltext_audit.json")
    assert sum(d["status"] == "parsed" for d in audit["documents"]) == 4
    assert any(c["status"] == "matched" for c in audit["checks"])
    for span in enriched.evidence_spans:
        if span.extraction_status.value == "verified":
            snapshot = next(s for s in enriched.source_snapshots if s.snapshot_id == span.snapshot_id)
            from pathlib import Path
            assert sha256(Path(snapshot.response_path).read_bytes()).hexdigest() == span.document_version
    assert any(a.kind.value == "resolve_conflict" for a in enriched.next_actions)


def test_missing_pdf_does_not_create_verified_span(tmp_path):
    dataset = load_dataset(load_settings().data_dir)
    enriched = enrich_audit(dataset, root=tmp_path, run_dir=tmp_path / "audit", question="test")
    assert all(s.extraction_status.value != "verified" for s in enriched.evidence_spans)
    assert all(s.snapshot_id is None for s in enriched.evidence_spans)
    assert any(a.kind.value == "acquire_fulltext" for a in enriched.next_actions)


def test_conflict_cannot_be_hidden_by_omitting_citation():
    payload = {"claims": [{"claim_id": "c", "status": "supported"}], "evidence": [
        {"evidence_id": "yes", "claim_id": "c", "verdict": "supports", "extraction_status": "verified", "locator": {"page": 1}},
        {"evidence_id": "no", "claim_id": "c", "verdict": "contradicts", "extraction_status": "verified", "locator": {"page": 2}},
    ]}
    audit = audit_answer_statements(payload, [{"text": "fact", "claim_id": "c", "evidence_ids": ["yes"], "certainty": "verified"}])
    assert not audit["ok"]
    assert any("conflict" in error for error in audit["errors"])


def test_overview_rejects_invented_abstract_and_other_run_paper():
    payload = {"offline": False, "live": {"added_paper_ids": ["new"]}, "papers": [
        {"paper_id": "new", "title": "New", "abstract": "Exact source sentence."},
        {"paper_id": "old", "title": "Old", "abstract": "Old source sentence."},
    ]}
    good = [{"paper_id": "new", "quote": "Exact source sentence.", "certainty": "abstract_only"}]
    assert audit_overview_statements(payload, good)["ok"]
    assert not audit_overview_statements(payload, [{**good[0], "quote": "Invented result."}])["ok"]
    assert not audit_overview_statements(payload, [{"paper_id": "old", "quote": "Old source sentence.", "certainty": "abstract_only"}])["ok"]


def test_bad_page_match_blocks_verified_prose():
    payload = {"claims": [{"claim_id": "c", "status": "supported"}], "evidence": [
        {"evidence_id": "e", "claim_id": "c", "verdict": "supports", "extraction_status": "verified", "locator": {"page": 1}},
    ], "evidence_spans": [{"evidence_id": "e", "extraction_status": "unverified"}]}
    assert not audit_answer_statements(payload, [{"text": "fact", "claim_id": "c", "evidence_ids": ["e"], "certainty": "verified"}])["ok"]


def test_upgrade_creates_new_run_and_keeps_source(tmp_path):
    import shutil
    settings = load_settings(runs_dir=tmp_path)
    source = load_settings().runs_dir / "phase2-real"
    shutil.copytree(source, tmp_path / "source")
    before = {p.relative_to(tmp_path / "source"): sha256(p.read_bytes()).hexdigest() for p in (tmp_path / "source").rglob("*") if p.is_file()}
    result = upgrade_audit(settings, "source")
    assert result["run_id"] != "source"
    assert result["stats"]["error_count"] == 0
    assert before == {p.relative_to(tmp_path / "source"): sha256(p.read_bytes()).hexdigest() for p in (tmp_path / "source").rglob("*") if p.is_file()}
    assert (tmp_path / result["run_id"] / "output" / "fulltext_audit.json").exists()


def test_model_receives_audit_feedback_before_retry(monkeypatch):
    import json
    from dataclasses import replace
    import src.conversation as conversation
    requests = []
    answers = [
        {"statements": [{"text": "fact", "claim_id": "c", "evidence_ids": ["wrong"], "certainty": "verified"}]},
        {"statements": [{"text": "fact", "claim_id": "c", "evidence_ids": ["e"], "certainty": "verified"}]},
    ]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(answers.pop(0))}}]}).encode()
    def request(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr(conversation, "urlopen", request)
    monkeypatch.setattr(conversation.time, "sleep", lambda *_: None)
    payload = {"claims": [{"claim_id": "c", "status": "supported"}], "evidence": [
        {"evidence_id": "e", "claim_id": "c", "verdict": "supports", "extraction_status": "verified", "locator": {"page": 1}}
    ]}
    result = conversation._llm_direct_answer(payload, "test", conversation.Intent("follow_up", 1, "test", False), replace(load_settings(), llm_api_key="test"))
    assert result[1]["ok"]
    assert len(requests) == 2
    assert "unknown_evidence" in requests[1]["messages"][-1]["content"]


def test_live_report_excludes_inherited_gold(tmp_path):
    import shutil
    from src.io_utils import write_json
    from src.ui.payload import build_audit_report
    source = load_settings().runs_dir / "phase2-real"
    shutil.copytree(source, tmp_path / "live-test")
    manifest = read_json(tmp_path / "live-test" / "run_manifest.json")
    manifest.update(run_id="live-test", offline=False, question="GPU architecture", live={"added_paper_ids": [], "retrieval": []})
    write_json(tmp_path / "live-test" / "run_manifest.json", manifest)
    report, _ = build_audit_report(tmp_path, "live-test")
    assert "PaperQA" not in report
    assert "SciMON" not in report
    assert "claim-008" not in report


def test_fulltext_get_serves_pdf_but_rejects_outside_run(tmp_path, monkeypatch):
    import json
    import threading
    from urllib.request import urlopen
    from urllib.error import HTTPError
    import pytest
    from src.io_utils import write_json
    from src.ui.server import make_server
    run = tmp_path / "audit-test"
    run.mkdir()
    pdf = run / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    write_json(run / "output" / "fulltext_audit.json", {"documents": [
        {"paper_id": "p1", "response_path": str(pdf)},
        {"paper_id": "p2", "response_path": str(outside)},
    ]})
    monkeypatch.setattr("src.ui.server.load_settings", lambda **_: load_settings(runs_dir=tmp_path))
    server, url = make_server(port=0, run_id="audit-test")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = url.split("?")[0] + "api/fulltext/audit-test/"
        with urlopen(base + "p1") as response:
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.read().startswith(b"%PDF-")
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "p2")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
