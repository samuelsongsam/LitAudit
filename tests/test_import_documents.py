"""First-use PDF import exercises real local parsing without model/network calls."""
import base64
from dataclasses import replace
from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.config import load_settings
from src.import_documents import import_pdf
from src.io_utils import read_json, write_json
from src.pipeline import snapshot_dataset, upgrade_audit
from src.replay import load_run
from src.research_workspace import method_comparison, search_fulltext, workspace_papers
from src.schema import Dataset, PaperCard, ScreeningLog


def local_research_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 40 740 Td (2 Methods) Tj 0 -24 Td "
                    b"(We used a controlled experiment with 120 participants.) Tj "
                    b"0 -24 Td (Participants were followed for 12 weeks.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def test_new_user_pdf_import_has_zero_schema_errors_and_locatable_methods(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_MAP_EMBEDDER", "hash")
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    settings = replace(load_settings(), root=tmp_path, runs_dir=tmp_path / "runs")
    content = local_research_pdf()
    result = import_pdf(settings, {
        "filename": "controlled-study.pdf", "title": "Controlled study of participant follow-up",
        "question": "试验纳入多少参与者，怎样随访？", "authors": ["Researcher A"], "year": 2024,
        "content_base64": base64.b64encode(content).decode("ascii"),
    })
    assert result["status"] == "completed"
    assert result["stats"]["error_count"] == 0
    loaded = load_run(settings.runs_dir, result["run_id"])
    assert len(loaded["dataset"].papers) == 1
    assert len(loaded["dataset"].screening) == 1
    assert loaded["dataset"].screening[0].paper_id == result["paper_id"]
    run_dir = settings.runs_dir / result["run_id"]
    assert len(list((run_dir / "cache/audit").glob("document-*.pdf"))) == 1
    audit = read_json(run_dir / "output/fulltext_audit.json")
    assert audit["documents"][0]["status"] == "parsed"
    found = search_fulltext(settings.runs_dir, result["run_id"], "participants followed", section="method")
    assert found["hits"] and found["hits"][0]["page"] == 1
    assert "120 participants" in found["hits"][0]["text"]
    methods = method_comparison(settings.runs_dir, result["run_id"])
    candidate = methods["papers"][0]["fields"]["sample_size"]["candidate"]
    assert "120" in candidate["value"]
    assert candidate["quote"] in candidate["text"]
    assert candidate["text_sha256"] == found["hits"][0]["text_sha256"]


def test_selected_pdf_attaches_to_visible_paper_without_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_MAP_EMBEDDER", "hash")
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    settings = replace(load_settings(), root=tmp_path, runs_dir=tmp_path / "runs")
    original = settings.runs_dir / "search-result"
    papers = [PaperCard(
        paper_id=paper_id, title=title, source="openalex", doi_or_arxiv=f"10.1234/{paper_id}",
        url=f"https://doi.org/10.1234/{paper_id}", dedup_key=f"doi:10.1234/{paper_id}",
        retrieved_at=date.today(), decision="include", reason="Catalog result",
    ) for paper_id, title in [("paper-001", "Catalog paper"), ("paper-002", "Hidden paper")]]
    screening = [ScreeningLog(screening_id=f"screen-{p.paper_id}", paper_id=p.paper_id,
                              stage="title_abstract", decision=p.decision, reason_code="catalog", reason=p.reason,
                              checked_fields=["title"], reviewer="test", reviewed_at=date.today(), scope_version="1")
                 for p in papers]
    snapshot_dataset(Dataset(papers=papers, paper_cards=papers, screening=screening), original / "output")
    write_json(original / "run_manifest.json", {
        "run_id": "search-result", "status": "completed", "offline": False, "source": "data",
        "question": "How many participants?", "live": {"matched_paper_ids": ["paper-001"]},
    })
    # A previous PDF saved at a legacy path must not shadow the selected upload.
    old_path = original / "cache" / "legacy.pdf"
    old_path.parent.mkdir()
    old_path.write_bytes(b"old file")
    write_json(original / "output" / "fulltext_audit.json", {
        "documents": [{"paper_id": "paper-001", "response_path": "cache/legacy.pdf"}],
    })
    original_audit = (original / "output" / "fulltext_audit.json").read_bytes()
    source_url = "https://example.org/author-copy.pdf"
    body = {"run_id": "search-result", "paper_id": "paper-001", "title": "Untrusted replacement title",
            "source_url": source_url, "content_base64": base64.b64encode(local_research_pdf()).decode("ascii")}
    with pytest.raises(ValueError, match="不属于当前研究"):
        import_pdf(settings, {**body, "paper_id": "paper-002"})
    assert list(settings.runs_dir.iterdir()) == [original]

    result = import_pdf(settings, body)
    assert result["paper_id"] == "paper-001"
    assert result["run_id"] != "search-result"
    loaded = load_run(settings.runs_dir, result["run_id"])
    assert loaded["manifest"]["question"] == "How many participants?"
    assert loaded["manifest"]["parent_run_id"] == "search-result"
    assert loaded["dataset"].papers == papers
    assert loaded["dataset"].screening == screening
    assert list(workspace_papers(settings.runs_dir, result["run_id"])) == ["paper-001"]
    assert loaded["dataset"].retrieval_runs[0].request == source_url
    assert search_fulltext(settings.runs_dir, result["run_id"], "participants")["hits"]
    assert old_path.read_bytes() == b"old file"
    assert (original / "output" / "fulltext_audit.json").read_bytes() == original_audit

    rerun = upgrade_audit(settings, result["run_id"], paper_ids=["paper-001"])
    assert load_run(settings.runs_dir, rerun["run_id"])["dataset"].retrieval_runs[0].request == source_url
