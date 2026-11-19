"""Reuse locally saved PDFs when the research identifies an exact revision."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re

from src.io_utils import read_json, read_jsonl
from src.pdf_download import _MAX_PDF_BYTES
from src.run_paths import resolve_run_dir, resolve_run_file
from src.schema import RetrievalRun, SourceSnapshot


_VERSIONED_ARXIV_URL = re.compile(
    r"https://arxiv\.org/pdf/(?:\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|[a-z.-]+/\d{7})v[1-9]\d*"
)
_MAX_RECENT_WORKSPACES = 32


@dataclass(frozen=True)
class SavedArxivPdf:
    path: Path
    run_dir: Path
    document: dict
    retrieved_at: datetime


def _download_record(run_dir: Path, paper_id: str, url: str) -> SavedArxivPdf | None:
    audit = read_json(resolve_run_file(run_dir, "output/fulltext_audit.json"))
    documents = audit.get("documents") if isinstance(audit, dict) else None
    if not isinstance(documents, list):
        return None
    document = next((row for row in documents if isinstance(row, dict) and row.get("paper_id") == paper_id), None)
    if (not document or document.get("acquisition") not in ("arxiv_download", "arxiv_saved_copy")
            or not document.get("snapshot_id")):
        return None

    snapshot_rows = read_jsonl(resolve_run_file(run_dir, "output/source_snapshots.jsonl"))
    snapshot = next((SourceSnapshot.model_validate(row) for row in snapshot_rows
                     if isinstance(row, dict) and row.get("snapshot_id") == document["snapshot_id"]), None)
    if (not snapshot or snapshot.source != "arxiv_download" or snapshot.status != "success"
            or snapshot.content_sha256 != document.get("document_sha256")):
        return None

    retrieval_rows = read_jsonl(resolve_run_file(run_dir, "output/retrieval_runs.jsonl"))
    retrieval = next((RetrievalRun.model_validate(row) for row in retrieval_rows
                      if isinstance(row, dict) and row.get("retrieval_id") == snapshot.retrieval_id), None)
    if not retrieval or retrieval.source != "arxiv_download" or retrieval.is_failure or retrieval.request != url:
        return None

    pdf = resolve_run_file(run_dir, document.get("response_path"))
    if any(resolve_run_file(run_dir, stored) != pdf for stored in (snapshot.response_path, retrieval.response_path)):
        return None
    with pdf.open("rb") as stream:
        content = stream.read(_MAX_PDF_BYTES + 1)
    if len(content) > _MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
        return None
    if sha256(content).hexdigest() != snapshot.content_sha256:
        return None
    return SavedArxivPdf(pdf, run_dir, document, snapshot.retrieved_at)


def find_versioned_arxiv_pdf(runs_dir: Path, source_run: str, paper_id: str, url: str) -> SavedArxivPdf | None:
    """Find a verified PDF in the source run or one of its recent finished copies."""
    if not _VERSIONED_ARXIV_URL.fullmatch(url):
        return None
    recent = sorted((path.name for path in runs_dir.glob("workspace_*") if path.name != source_run), reverse=True)
    for run_id in [source_run, *recent[:_MAX_RECENT_WORKSPACES]]:
        try:
            run_dir = resolve_run_dir(runs_dir, run_id)
            if run_dir.name != run_id:
                continue
            if run_id != source_run:
                manifest = read_json(resolve_run_file(run_dir, "run_manifest.json"))
                if (not isinstance(manifest, dict) or manifest.get("parent_run_id") != source_run
                        or manifest.get("stage") != "finished" or manifest.get("status") not in ("completed", "partial")):
                    continue
            saved = _download_record(run_dir, paper_id, url)
            if saved:
                return saved
        except (OSError, ValueError):
            # A missing or malformed prior artifact simply cannot be reused.
            continue
    return None
