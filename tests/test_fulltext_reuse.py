from datetime import datetime, timezone
from hashlib import sha256

import pytest

from src.fulltext_reuse import find_versioned_arxiv_pdf
from src.io_utils import write_json, write_jsonl


PDF_URL = "https://arxiv.org/pdf/2505.07757v2"
TIMESTAMP = datetime(2026, 11, 5, 11, 39, tzinfo=timezone.utc)


def _saved_pdf(runs, *, parent="live_study", stage="finished", source="arxiv_download", request=PDF_URL,
               acquisition=None):
    child = runs / "workspace_20261105T113935Z_abcdefff"
    path = "cache/document.pdf"
    pdf = child / path
    pdf.parent.mkdir(parents=True)
    content = b"%PDF-1.7\nReference bytes from the versioned source."
    pdf.write_bytes(content)
    digest = sha256(content).hexdigest()
    write_json(child / "run_manifest.json", {"parent_run_id": parent, "stage": stage, "status": "completed"})
    write_json(child / "output/fulltext_audit.json", {"documents": [{"paper_id": "paper-008", "status": "parsed",
        "acquisition": acquisition or source, "snapshot_id": "snapshot-fulltext-abc", "response_path": path,
        "document_sha256": digest}]})
    write_jsonl(child / "output/source_snapshots.jsonl", [{"snapshot_id": "snapshot-fulltext-abc",
        "retrieval_id": "fulltext-abc", "source": source, "status": "success", "retrieved_at": TIMESTAMP.isoformat(),
        "response_path": path, "content_sha256": digest}])
    write_jsonl(child / "output/retrieval_runs.jsonl", [{"retrieval_id": "fulltext-abc",
        "query_id": "fulltext-acquisition", "source": source, "request": request, "retrieved_at": TIMESTAMP.date().isoformat(),
        "status": "success", "response_path": path}])
    return pdf


@pytest.mark.parametrize("acquisition", ["arxiv_download", "arxiv_saved_copy"])
def test_reuse_exact_arxiv_download_from_finished_child(tmp_path, acquisition):
    pdf = _saved_pdf(tmp_path, acquisition=acquisition)
    result = find_versioned_arxiv_pdf(tmp_path, "live_study", "paper-008", PDF_URL)
    assert result is not None
    assert result.path == pdf
    assert result.run_dir == pdf.parent.parent
    assert result.document["status"] == "parsed"
    assert result.retrieved_at == TIMESTAMP
    assert find_versioned_arxiv_pdf(tmp_path, "live_study", "paper-008", PDF_URL.removesuffix("v2")) is None


@pytest.mark.parametrize("overrides", [
    {"request": PDF_URL.removesuffix("v2") + "v1"},
    {"source": "local_copy"},
    {"source": "local_copy", "acquisition": "arxiv_saved_copy"},
    {"parent": "live_another_study"},
    {"stage": "fulltext"},
], ids=["different-version", "local-import", "unproven-reused-copy", "unrelated-workspace", "unfinished-workspace"])
def test_other_pdf_is_not_reused_even_with_matching_file_hash(tmp_path, overrides):
    _saved_pdf(tmp_path, **overrides)
    assert find_versioned_arxiv_pdf(tmp_path, "live_study", "paper-008", PDF_URL) is None


def test_file_corruption_invalidates_saved_pdf(tmp_path):
    pdf = _saved_pdf(tmp_path)
    pdf.write_bytes(b"%PDF-1.7\nDifferent document content")
    assert find_versioned_arxiv_pdf(tmp_path, "live_study", "paper-008", PDF_URL) is None
