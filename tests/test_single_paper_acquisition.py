"""Acquiring one paper keeps the existing, portable research workspace intact."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.config import load_settings
from src.conversation import load_conversation, save_turn
from src.document_processing import read_document
from src.io_utils import read_json, write_json, write_jsonl
from src.paper_library import library_payload, save_library_item
from src.pipeline import snapshot_dataset, upgrade_audit
from src.research_workspace import save_review, search_fulltext, workspace_payload
from src.run_paths import resolve_run_file
from src.schema import Dataset, PaperCard, RetrievalRun, ScreeningLog, dataset_stats


def _pdf_bytes(text):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                                                      DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 16 Tf 40 740 Td (Methods) Tj 0 -40 Td (" + text + ") Tj ET").encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _fingerprint(directory):
    return {str(p.relative_to(directory)): sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file()}


def _research(tmp_path, monkeypatch, *, canonical, arxiv_version: str | None = None):
    monkeypatch.setenv("LITAUDIT_MAP_EMBEDDER", "hash")
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    settings = replace(load_settings(), root=tmp_path, runs_dir=tmp_path / "runs")
    source = settings.runs_dir / "source"
    papers = [PaperCard(paper_id=pid, title=title, source="local-test", retrieved_at=date(2026, 1, 1),
                        dedup_key=pid, url="https://papers.example/" + pid,
                        open_access_pdf_url="https://papers.example/" + pid + ".pdf",
                        decision="include", reason="Selected for the current research")
              for pid, title in [("wanted", "Target study"), ("existing", "Previously read study"),
                                 ("other", "Another candidate"), ("hidden", "Outside current topic")]]
    if arxiv_version is not None:
        papers[0].doi_or_arxiv = "arXiv:2505.07757"
        papers[0].url = "https://arxiv.org/abs/2505.07757" + arxiv_version
    screening = [ScreeningLog(screening_id="screen-" + p.paper_id, paper_id=p.paper_id,
        stage="title_abstract", decision="include", reason_code="user_selection", reason=p.reason,
        checked_fields=["title"], reviewer="local_user", reviewed_at=date(2026, 1, 1), scope_version="v0.1")
        for p in papers]
    dataset = Dataset(papers=papers, paper_cards=[p.model_copy(deep=True) for p in papers], screening=screening)
    snapshot_dataset(dataset, source / "output")
    write_json(source / "run_manifest.json", {"run_id": "source", "offline": False,
        "question": "How does the experimental method work?", "status": "completed",
        "live": {"matched_paper_ids": ["wanted", "existing", "other"]}})
    write_json(source / "stats.json", dataset_stats(dataset))
    write_json(source / "output/map.json", {"nodes": [], "tracks": [], "edges": [], "algorithm": "fixture"})
    file_name = "cache/audit/document-" + sha256(b"existing").hexdigest()[:16] + ".pdf" if canonical else "cache/uploaded-original.pdf"
    existing = source / file_name
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(_pdf_bytes("Our method used 120 participants and a control baseline."))
    parsed = read_document(existing, ocr_mode="off")
    text_name = "cache/earlier-pages.json"
    write_json(source / text_name, parsed["pages"])
    write_json(source / "output/fulltext_audit.json", {"documents": [{"paper_id": "existing",
        "status": "parsed", "response_path": file_name, "text_path": text_name,
        "page_count": 1, "document_sha256": sha256(existing.read_bytes()).hexdigest()}]})
    hit = search_fulltext(settings.runs_dir, "source", "participants", paper_ids=["existing"])["hits"][0]
    review = save_review(settings.runs_dir, "source", {"paper_id": "existing", "passage_id": hit["passage_id"],
        "field": "method", "status": "accepted", "display_value": "人工核对的方法",
        "note": "保留已确认的实验笔记", "expected_text_sha256": hit["text_sha256"],
        "quote": "Our method used 120 participants and a control baseline."})["review"]
    save_library_item(settings.runs_dir, "source", {"paper_id": "existing", "favorite": True,
        "reading_status": "done", "tags": ["已读", "复现"], "notes": "保留收藏和阅读记录"})
    save_turn(settings.runs_dir, "source", "继续解释原有论文", "已有的中文阅读解读", {
        "overview_mode": "direct_answer", "citation": {"pdf_url": "/api/fulltext/source/existing#page=1"}})
    write_json(source / "output/research_context.json", {"constraints": {"year_from": 2020},
                                                        "user_resources": {"compute": "8GB GPU"}})
    return settings, source, existing.read_bytes(), review


@pytest.mark.parametrize("canonical", [True, False], ids=["audit-cache", "stored-portable-path"])
def test_single_acquisition_preserves_other_fulltext_and_all_human_material(tmp_path, monkeypatch, canonical):
    settings, source, original_pdf, original_review = _research(tmp_path, monkeypatch, canonical=canonical)
    before = _fingerprint(source)
    calls = []
    def download(url, target):
        calls.append(url)
        target.write_bytes(_pdf_bytes("The target method uses a randomized protocol."))
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", download)
    with monkeypatch.context() as guard:
        guard.setattr("src.pipeline.build_map", lambda *args: pytest.fail("Acquisition must reuse the semantic map"))
        guard.setattr("src.fulltext_search._rank_candidates", lambda *args: pytest.fail("Acquisition must not await reranking"))
        result = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    assert calls == ["https://papers.example/wanted.pdf"]
    assert result["run_id"] != "source" and result["stats"]["error_count"] == 0
    assert result["acquisition"]["status"] == "completed"
    assert result["acquisition"]["requested_paper_ids"] == result["acquisition"]["ready_paper_ids"] == ["wanted"]
    assert result["acquisition"]["failed_paper_ids"] == result["acquisition"]["pending_paper_ids"] == []
    destination = settings.runs_dir / result["run_id"]
    assert read_json(destination / "output" / "map.json") == {
        "nodes": [], "tracks": [], "edges": [], "algorithm": "fixture"}
    assert read_json(destination / "output" / "fulltext_index.json")["algorithm"] == "bm25_passage_ranking"
    documents = {d["paper_id"]: d for d in read_json(destination / "output/fulltext_audit.json")["documents"]}
    assert documents["wanted"]["status"] == documents["existing"]["status"] == "parsed"
    assert documents["other"]["status"] == "missing" and "hidden" not in documents
    assert resolve_run_file(destination, documents["existing"]["response_path"]).read_bytes() == original_pdf
    old = next(p for p in library_payload(settings.runs_dir, result["run_id"])["items"] if p["paper_id"] == "existing")
    assert old["notes"] == "保留收藏和阅读记录" and old["favorite"] and old["reading_status"] == "done"
    assert old["tags"] == ["已读", "复现"]
    review = workspace_payload(settings.runs_dir, result["run_id"])["reviews"][0]
    assert review["quote"] == original_review["quote"] and review["text_sha256"] == original_review["text_sha256"]
    assert review["status"] == "accepted" and review["display_value"] == "人工核对的方法"
    messages = load_conversation(settings.runs_dir, result["run_id"])["messages"]
    assert [m["content"] for m in messages] == ["继续解释原有论文", "已有的中文阅读解读"]
    assert f"/api/fulltext/{result['run_id']}/" in messages[1]["response"]["citation"]["pdf_url"]
    assert read_json(destination / "output/research_context.json")["user_resources"]["compute"] == "8GB GPU"
    assert _fingerprint(source) == before


@pytest.mark.parametrize("selected", [[], ["hidden"], ["invented"], "wanted", [True]])
def test_invalid_or_hidden_single_paper_target_is_rejected_before_fork_or_network(tmp_path, monkeypatch, selected):
    settings, source, _, _ = _research(tmp_path, monkeypatch, canonical=True)
    before = _fingerprint(source)
    calls = []
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", lambda *args: calls.append(True))
    with pytest.raises(ValueError):
        upgrade_audit(settings, "source", acquire=True, paper_ids=selected)
    assert not calls and _fingerprint(source) == before
    assert sorted(p.name for p in settings.runs_dir.iterdir()) == ["source"]


def test_existing_fulltext_reference_cannot_read_a_file_outside_its_run(tmp_path, monkeypatch):
    settings, source, _, _ = _research(tmp_path, monkeypatch, canonical=False)
    outside = settings.runs_dir / "private.pdf"
    outside.write_bytes(_pdf_bytes("Private content outside the research run."))
    audit = read_json(source / "output/fulltext_audit.json")
    audit["documents"][0]["response_path"] = "../private.pdf"
    write_json(source / "output/fulltext_audit.json", audit)
    before = _fingerprint(source)
    private_before = outside.read_bytes()
    calls = []
    def download(url, target):
        calls.append(url)
        target.write_bytes(_pdf_bytes("The target method uses a randomized protocol."))
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", download)
    result = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    audit = read_json(settings.runs_dir / result["run_id"] / "output/fulltext_audit.json")
    documents = {d["paper_id"]: d for d in audit["documents"]}
    assert calls == ["https://papers.example/wanted.pdf"]
    assert documents["existing"]["status"] == "missing"
    assert "response_path" not in documents["existing"]
    assert outside.read_bytes() == private_before and _fingerprint(source) == before


def test_download_failure_keeps_previous_fulltext_and_human_records(tmp_path, monkeypatch):
    from urllib.error import HTTPError
    settings, source, original_pdf, _ = _research(tmp_path, monkeypatch, canonical=False)
    before = _fingerprint(source)
    def unavailable(url, target):
        raise HTTPError(url, 429, "Source waiting", {}, None)
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", unavailable)
    result = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    destination = settings.runs_dir / result["run_id"]
    documents = {d["paper_id"]: d for d in read_json(destination / "output/fulltext_audit.json")["documents"]}
    assert documents["wanted"]["status"] == "failed" and documents["wanted"]["error_code"] == "http_429"
    assert result["status"] == result["stages"]["fulltext"]["status"] == "partial"
    assert result["acquisition"]["status"] == "failed"
    assert result["acquisition"]["failed_paper_ids"] == ["wanted"] and not result["acquisition"]["ready_paper_ids"]
    assert read_json(destination / "run_manifest.json")["acquisition"] == result["acquisition"]
    assert documents["existing"]["status"] == "parsed"
    assert resolve_run_file(destination, documents["existing"]["response_path"]).read_bytes() == original_pdf
    assert workspace_payload(settings.runs_dir, result["run_id"])["reviews"][0]["status"] == "accepted"
    assert next(i for i in library_payload(settings.runs_dir, result["run_id"])["items"]
                if i["paper_id"] == "existing")["notes"] == "保留收藏和阅读记录"
    assert len(load_conversation(settings.runs_dir, result["run_id"])["messages"]) == 2
    assert _fingerprint(source) == before


def test_processing_timeout_keeps_downloaded_pdf_available(tmp_path, monkeypatch):
    from src.document_processing import read_document

    settings, _, _, _ = _research(tmp_path, monkeypatch, canonical=True)
    pdf = _pdf_bytes("The target study uses one dataset.")

    def parse(path, **kwargs):
        if path.read_bytes() == pdf:
            assert kwargs["timeout_seconds"] == 60
            raise ValueError("pdf_processing_timeout")
        return read_document(path, **kwargs)

    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", lambda url, target: target.write_bytes(pdf))
    monkeypatch.setattr("src.document_processing.read_document", parse)
    result = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    document = result["acquisition"]["documents"][0]
    assert document["status"] == "failed" and document["error_code"] == "pdf_processing_timeout"
    assert document["pdf_saved"]
    destination = settings.runs_dir / result["run_id"]
    audit = read_json(destination / "output/fulltext_audit.json")
    saved = next(row["response_path"] for row in audit["documents"] if row["paper_id"] == "wanted")
    assert resolve_run_file(destination, saved).read_bytes() == pdf


@pytest.mark.parametrize(("identifier", "expected"), [
    ("arXiv:6926.67557", "https://papers.example/paper.pdf"),
    ("https://doi.org/10.48550/arXiv.2610.33624", "https://arxiv.org/pdf/2610.33624"),
])
def test_fulltext_url_prefers_valid_arxiv_identity(identifier, expected):
    from src.audit_enrichment import fulltext_pdf_url

    paper = SimpleNamespace(doi_or_arxiv=identifier, url="https://papers.example/article",
                            open_access_pdf_url="https://papers.example/paper.pdf")
    assert fulltext_pdf_url(paper) == expected


@pytest.mark.parametrize("version", ["v2", ""], ids=["fixed-version", "unversioned"])
def test_acquisition_only_uses_an_alternate_copy_when_no_arxiv_version_is_fixed(tmp_path, monkeypatch, version):
    from urllib.error import HTTPError
    settings, source, _, _ = _research(tmp_path, monkeypatch, canonical=True, arxiv_version=version)
    calls = []

    def download(url, target):
        calls.append(url)
        if "arxiv.org" in url:
            raise HTTPError(url, 404, "Version PDF unavailable", {}, None)
        target.write_bytes(_pdf_bytes("A method described by this provider copy."))

    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", download)
    result = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    assert calls[0] == "https://arxiv.org/pdf/2505.07757" + version
    document = result["acquisition"]["documents"][0]
    if version:
        assert len(calls) == 1
        assert document["status"] == "failed" and document["error_code"] == "http_404"
        assert not document["pdf_saved"]
    else:
        assert calls[1:] == ["https://papers.example/wanted.pdf"]
        assert document["status"] == "parsed" and document["acquisition"] == "provider_open_access_pdf"
        assert document["pdf_saved"]
        retrievals = (settings.runs_dir / result["run_id"] / "output" / "retrieval_runs.jsonl").read_text(encoding="utf-8")
        assert '"request":"https://papers.example/wanted.pdf"' in retrievals


def test_arxiv_withdrawn_exact_version_uses_saved_official_metadata(tmp_path, monkeypatch):
    settings, source, _, _ = _research(tmp_path, monkeypatch, canonical=True, arxiv_version="v2")
    response = "cache/arxiv.xml"
    (source / response).write_text('''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>https://arxiv.org/abs/2505.07757v2</id><arxiv:comment>Withdrawn due to an error.</arxiv:comment></entry>
    </feed>''', encoding="utf-8")
    write_jsonl(source / "output/retrieval_runs.jsonl", [RetrievalRun(
        retrieval_id="search-1", query_id="query-1", source="arxiv", status="success",
        request="https://export.arxiv.org/api/query?id_list=2505.07757v2",
        response_path=response, retrieved_at=date(2026, 1, 1), result_count=1)])
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", lambda *_: pytest.fail("Withdrawn PDF should not be requested"))

    result = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])

    assert result["acquisition"]["documents"] == [{"paper_id": "wanted", "status": "failed",
        "error_code": "arxiv_withdrawn", "acquisition": None, "pdf_saved": False}]


def test_second_acquisition_from_original_run_reuses_exact_pdf_and_page_text(tmp_path, monkeypatch):
    settings, source, _, _ = _research(tmp_path, monkeypatch, canonical=True, arxiv_version="v2")
    original = _fingerprint(source)
    wanted_name = "document-" + sha256(b"wanted").hexdigest()[:16] + ".pdf"

    def download(url, target):
        assert url == "https://arxiv.org/pdf/2505.07757v2"
        target.write_bytes(_pdf_bytes("The target method uses a randomized protocol."))

    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", download)
    first = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", lambda *_: pytest.fail("Exact version already downloaded"))

    def parse_other_papers(path, **kwargs):
        assert path.name != wanted_name, "The saved, page-located text should be reused"
        return read_document(path, **kwargs)

    monkeypatch.setattr("src.document_processing.read_document", parse_other_papers)
    second = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    assert second["acquisition"]["documents"][0]["acquisition"] == "arxiv_saved_copy"

    def artifacts(result):
        dest = settings.runs_dir / result["run_id"]
        record = next(row for row in read_json(dest / "output/fulltext_audit.json")["documents"]
                      if row["paper_id"] == "wanted")
        return [resolve_run_file(dest, record[key]).read_bytes() for key in ("response_path", "text_path")]

    assert artifacts(first) == artifacts(second)
    assert _fingerprint(source) == original


def test_targeted_acquisition_keeps_page_hashes_without_reparsing_other_papers(tmp_path, monkeypatch):
    settings, _, _, _ = _research(tmp_path, monkeypatch, canonical=True)
    monkeypatch.setattr("src.audit_enrichment.fetch_pdf", lambda url, target: target.write_bytes(_pdf_bytes(url)))
    first = upgrade_audit(settings, "source", acquire=True, paper_ids=["wanted"])
    parsed = []

    def observe_parse(path, **kwargs):
        parsed.append(path.name)
        return read_document(path, **kwargs)

    monkeypatch.setattr("src.document_processing.read_document", observe_parse)
    second = upgrade_audit(settings, first["run_id"], acquire=True, paper_ids=["other"])
    assert parsed == ["document-" + sha256(b"other").hexdigest()[:16] + ".pdf"]
    assert second["acquisition"]["ready_paper_ids"] == ["other"]
