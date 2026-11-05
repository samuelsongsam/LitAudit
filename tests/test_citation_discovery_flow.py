from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from src.config import Settings
from src.http_fetch import FetchResult
from src.io_utils import read_json, write_json
from src.pipeline import snapshot_dataset
from src.replay import load_run
from src.retrieve import fetch_related_hits
from src.schema import Dataset, PaperCard, RetrievalRun, ScreeningLog, SourceSnapshot
from src.ui.payload import build_payload
from src.ui.server import LitAuditHandler


@pytest.fixture
def study(tmp_path):
    root = tmp_path / "application"
    settings = Settings(root=root, data_dir=root / "data", fixtures_dir=root / "fixtures",
                        runs_dir=tmp_path / "runs", offline=True, log_level="WARNING")
    run = settings.runs_dir / "original"
    paper = PaperCard(paper_id="paper-001", title="Robotics motion planning", source="openalex", source_id="W1",
                      url="https://example.org/seed", retrieved_at=date.today(), dedup_key="title:robotics motion planning",
                      decision="include", reason="Original study")
    pdf_path, text_path = "cache/document.pdf", "cache/pages.json"
    pdf = b"%PDF-1.4\n original test bytes"
    (run / "cache").mkdir(parents=True)
    (run / pdf_path).write_bytes(pdf)
    pages = [{"page": 1, "text": "Original motion planning evidence"}]
    write_json(run / text_path, pages)
    snapshot = SourceSnapshot(snapshot_id="snapshot-001", retrieval_id="fulltext-001", source="local_copy",
                              status="success", retrieved_at=datetime.now(timezone.utc), response_path=pdf_path,
                              content_sha256=sha256(pdf).hexdigest())
    retrieval = RetrievalRun(retrieval_id="fulltext-001", query_id="fulltext-acquisition", source="local_copy",
                             request=paper.url, retrieved_at=date.today(), status="success", result_count=1,
                             response_path=pdf_path)
    screening = ScreeningLog(screening_id="screen-001", paper_id=paper.paper_id, stage="title_abstract",
                             decision="include", reason_code="test", reason=paper.reason, checked_fields=["title"],
                             reviewer="test", reviewed_at=date.today(), scope_version="test")
    snapshot_dataset(Dataset(papers=[paper], paper_cards=[paper], screening=[screening],
                             retrieval_runs=[retrieval], source_snapshots=[snapshot]), run / "output")
    write_json(run / "run_manifest.json", {"run_id": run.name, "offline": True, "status": "completed",
                                          "question": "robotics motion planning"})
    write_json(run / "output/fulltext_audit.json", {"documents": [{"paper_id": paper.paper_id, "status": "parsed",
        "response_path": pdf_path, "text_path": text_path, "page_count": 1, "snapshot_id": snapshot.snapshot_id,
        "document_sha256": snapshot.content_sha256}]})
    write_json(run / "output/fulltext_index.json", {"hits": [{"paper_id": paper.paper_id,
        "pdf_url": "/api/fulltext/original/paper-001#page=1", "text": pages[0]["text"]}]})
    write_json(run / "output/paper_library.json", {"version": 1, "run_id": "original", "items": {
        paper.paper_id: {"notes": "My reading note"}}})
    handler = LitAuditHandler.__new__(LitAuditHandler)
    handler.settings = settings
    return handler, run


def mock_provider(monkeypatch, results, status=200, error=None):
    def fetch(url, **kwargs):
        data = json.dumps({"meta": {"count": len(results)}, "results": results}).encode()
        return FetchResult(url, status, data, error=error)

    monkeypatch.setattr("src.retrieve.fetch_related_hits",
                        lambda *args, **kwargs: fetch_related_hits(*args, **kwargs, fetch=fetch))


def related(handler, run_id, direction="references", constraints=None):
    return handler._citation_discovery({"run_id": run_id, "paper_id": "paper-001", "direction": direction,
                                        "constraints": constraints})


@pytest.mark.parametrize("results,http,error,constraints,status,source_status", [
    ([], 200, None, None, "empty", "success"),
    ([{"id": "https://openalex.org/W2", "display_name": "Filtered study", "publication_year": 2000}],
     200, None, {"year_from": 2020}, "empty", "success"),
    ([], 429, None, None, "unavailable", "rate_limited"),
    ([], None, "provider_request_timeout", None, "unavailable", "timeout"),
])
def test_empty_or_failed_citations_keep_current_run(study, monkeypatch, results, http, error, constraints,
                                                   status, source_status):
    handler, run = study
    mock_provider(monkeypatch, results, http, error)
    monkeypatch.setattr("src.ui.server.run_pipeline", lambda *args, **kwargs: pytest.fail("Started a redundant run"))
    result = related(handler, run.name, constraints=constraints)
    assert result["run_id"] == run.name
    assert result["related"]["status"] == status
    assert result["related"]["source_status"] == source_status
    assert result["related"]["papers"] == []
    if constraints:
        assert "筛选条件" in result["related"]["message"]


def test_new_citations_keep_fulltext_and_links_without_model_work(study, monkeypatch):
    handler, source = study
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    mock_provider(monkeypatch, [{"id": "https://openalex.org/W2", "display_name": "Robotics motion planning study",
                                "publication_year": 2024}])

    def slow(*args, **kwargs):
        pytest.fail("Citation discovery must not recompute fulltext or the semantic map")

    for target in ("src.document_processing.read_document", "src.fulltext_search.build_fulltext_search",
                   "src.pipeline.build_map", "src.ui.payload.build_map"):
        monkeypatch.setattr(target, slow)
    first = related(handler, source.name)
    assert first["status"] == "completed"
    assert first["related"]["added_paper_ids"] == ["paper-002"]
    assert first["related"]["papers"][0]["title"] == "Robotics motion planning study"
    child = source.parent / first["run_id"]
    assert (child / "cache/document.pdf").read_bytes() == before[Path("cache/document.pdf")]
    assert read_json(child / "cache/pages.json") == read_json(source / "cache/pages.json")
    assert read_json(child / "output/fulltext_index.json")["hits"][0]["pdf_url"] == f"/api/fulltext/{child.name}/paper-001#page=1"
    assert read_json(child / "output/paper_library.json")["items"]["paper-001"]["notes"] == "My reading note"
    payload = build_payload(source.parent, child.name)
    assert payload["map"]["status"] == "pending"
    assert payload["citation_graph"]["edges"][0]["source"] == "W1"
    snapshots = load_run(source.parent, child.name)["dataset"].source_snapshots
    assert snapshots[0].response_path == "cache/document.pdf"
    assert snapshots[-1].status == "success" and (child / snapshots[-1].response_path).is_file()

    repeat = related(handler, child.name)
    assert repeat["run_id"] == child.name
    assert repeat["related"]["status"] == "already_present"
    assert repeat["related"]["paper_ids"] == ["paper-002"]
    reverse = related(handler, child.name, direction="citations")
    assert reverse["run_id"] != child.name
    assert reverse["related"]["status"] == "completed"
    assert reverse["related"]["added_count"] == 0
    graph = read_json(source.parent / reverse["run_id"] / "output/citation_graph.json")
    assert {(row["source"], row["target"]) for row in graph["edges"]} == {("W1", "W2"), ("W2", "W1")}
    assert {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()} == before
