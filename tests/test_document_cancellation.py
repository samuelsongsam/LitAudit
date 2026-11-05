import subprocess

import pytest
from pypdf import PdfWriter

from src.tasks import TaskCancelled


def _substitute_pdf_worker(monkeypatch, command):
    spawn = subprocess.Popen
    processes = []

    def substitute(args, **kwargs):
        process = spawn([args[0], "-c", command, args[-1]], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("src.pdf_download.subprocess.Popen", substitute)
    return processes


def test_pdf_download_cancelled_after_response_does_not_write_document(tmp_path, monkeypatch):
    from src.pdf_download import fetch_pdf

    processes = _substitute_pdf_worker(monkeypatch,
        "import sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(b'%PDF-test')")

    def check():
        if processes and processes[0].poll() is not None:
            raise TaskCancelled("stop after response")

    monkeypatch.setattr("src.tasks.check_cancelled", check)
    target = tmp_path / "document.pdf"
    with pytest.raises(TaskCancelled):
        fetch_pdf("https://example.invalid/paper.pdf", target)
    assert not list(tmp_path.iterdir())


def test_stalled_pdf_transfer_is_killed_at_wall_clock_deadline(tmp_path, monkeypatch):
    from src.pdf_download import PdfDownloadError, fetch_pdf

    processes = _substitute_pdf_worker(monkeypatch,
        "import time; time.sleep(30)")
    monkeypatch.setattr("src.pdf_download._DOWNLOAD_SECONDS", 0.4)
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"existing file")
    with pytest.raises(PdfDownloadError, match="^pdf_timeout$"):
        fetch_pdf("https://example.invalid/paper.pdf", target)
    assert processes[0].poll() is not None
    assert target.read_bytes() == b"existing file"
    assert list(tmp_path.iterdir()) == [target]


def test_completed_pdf_transfer_receives_url_and_publishes_file(tmp_path, monkeypatch):
    from src.pdf_download import fetch_pdf

    url = "https://example.invalid/paper.pdf"
    _substitute_pdf_worker(monkeypatch,
        "import sys; from pathlib import Path; "
        f"assert sys.stdin.buffer.read() == {url.encode()!r}; "
        "Path(sys.argv[1]).write_bytes(b'%PDF-test')")
    target = tmp_path / "document.pdf"
    fetch_pdf(url, target)
    assert target.read_bytes() == b"%PDF-test"
    assert list(tmp_path.iterdir()) == [target]


def test_native_document_processing_can_stop_between_pages(tmp_path, monkeypatch):
    from src.document_processing import read_document
    writer=PdfWriter();writer.add_blank_page(width=120,height=120);writer.add_blank_page(width=120,height=120)
    document=tmp_path/'two-pages.pdf'
    with document.open('wb') as stream:writer.write(stream)
    calls=[]
    def check():
        calls.append(1)
        if len(calls)==3:raise TaskCancelled('stop before second page')
    monkeypatch.setattr('src.tasks.check_cancelled',check)
    with pytest.raises(TaskCancelled):read_document(document,ocr_mode='off')


def test_fulltext_enrichment_does_not_hide_cancel_as_document_parse_failure(tmp_path, monkeypatch):
    from src.audit_enrichment import enrich_audit
    from src.config import load_settings
    from src.io_utils import load_dataset
    settings=load_settings()
    def stop(*args,**kwargs):raise TaskCancelled('stop fulltext extraction')
    monkeypatch.setattr('src.document_processing.read_document',stop)
    with pytest.raises(TaskCancelled):
        enrich_audit(load_dataset(settings.data_dir),root=settings.root,run_dir=tmp_path/'audit',question='evidence')


def test_pipeline_records_user_cancel_without_marking_it_as_system_failure(tmp_path, monkeypatch):
    from src.config import load_settings
    from src.pipeline import run_pipeline
    from src.io_utils import read_json
    def stop(*args,**kwargs):raise TaskCancelled('user stopped')
    monkeypatch.setattr('src.audit_enrichment.enrich_audit',stop)
    with pytest.raises(TaskCancelled):
        run_pipeline(load_settings(runs_dir=tmp_path,offline=True),run_id='cancelled-research')
    manifest=read_json(tmp_path/'cancelled-research/run_manifest.json')
    assert manifest['status']=='cancelled' and manifest['stages']['fulltext']['status']=='cancelled'
    assert (tmp_path/'cancelled-research/output/papers.jsonl').exists()
