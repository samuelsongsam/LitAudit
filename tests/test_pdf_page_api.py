"""Original-page API must return actual pixels and respect research scope."""
from dataclasses import replace
from datetime import date
from io import BytesIO
import json
import struct
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from src.config import load_settings
from src.io_utils import write_json
from src.pipeline import snapshot_dataset
from src.schema import Dataset, PaperCard, dataset_stats
from src.ui.server import make_server


def _small_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 22 Tf 40 740 Td (Methods: Original PDF page) Tj "
                     b"0 -40 Td (The experiment included 120 participants.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    target = BytesIO()
    writer.write(target)
    return target.getvalue()


@pytest.fixture
def pdf_api(tmp_path, monkeypatch):
    settings = replace(load_settings(), root=tmp_path, runs_dir=tmp_path / "runs")
    run = settings.runs_dir / "pdf-run"
    papers = [PaperCard(paper_id=pid, title=title, source="local-test", retrieved_at=date(2026, 1, 1),
                        dedup_key=pid, url="https://example.test/" + pid,
                        decision="include", reason="API regression fixture")
              for pid, title in [("visible", "Current research"), ("hidden", "Another topic")]]
    dataset = Dataset(papers=papers, paper_cards=[p.model_copy(deep=True) for p in papers])
    snapshot_dataset(dataset, run / "output")
    write_json(run / "run_manifest.json", {"run_id": run.name, "offline": False, "status": "completed",
                                          "question": "Read the current paper", "live": {"matched_paper_ids": ["visible"]}})
    write_json(run / "stats.json", dataset_stats(dataset))
    write_json(run / "output/map.json", {"status": "unavailable", "nodes": [], "edges": [], "tracks": []})
    (run / "cache").mkdir()
    for paper in papers:
        (run / "cache" / (paper.paper_id + ".pdf")).write_bytes(_small_pdf())
    write_json(run / "output/fulltext_audit.json", {"documents": [
        {"paper_id": p.paper_id, "status": "parsed", "response_path": "cache/" + p.paper_id + ".pdf", "page_count": 1}
        for p in papers]})
    monkeypatch.setattr("src.ui.server.load_settings", lambda **kwargs: settings)
    server, url = make_server(port=0, run_id=run.name)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield url.split("?")[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_pdf_page_endpoint_returns_a_nonblank_original_page_png(pdf_api):
    fitz = pytest.importorskip("fitz")
    with urlopen(pdf_api + "api/pdf-page/pdf-run/visible/1", timeout=10) as response:
        assert response.status == 200
        assert response.headers.get_content_type() == "image/png"
        image = response.read()
        assert int(response.headers["Content-Length"]) == len(image)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", image[16:24])
    assert 100 < width <= 1600 and 100 < height <= 2200
    pixels = fitz.Pixmap(image).samples
    assert min(pixels) < 200  # Actual black glyphs, rather than an empty white page.
    assert max(pixels) == 255
    assert len(image) > 1000


@pytest.mark.parametrize("page", ["0", "-1", "2", "not-a-number"])
def test_pdf_page_endpoint_rejects_invalid_or_out_of_range_pages(pdf_api, page):
    pytest.importorskip("fitz")
    with pytest.raises(HTTPError) as caught:
        urlopen(pdf_api + "api/pdf-page/pdf-run/visible/" + page, timeout=10)
    assert caught.value.code == 400
    assert "error" in json.loads(caught.value.read())


@pytest.mark.parametrize("route", ["api/pdf-page/pdf-run/hidden/1", "api/fulltext/pdf-run/hidden", "api/pdf-text/pdf-run/hidden/1"])
def test_original_page_and_pdf_cannot_expose_hidden_paper_in_same_snapshot(pdf_api, route):
    with pytest.raises(HTTPError) as caught:
        urlopen(pdf_api + route, timeout=10)
    assert caught.value.code == 404
    assert "error" in json.loads(caught.value.read())


def test_pdf_page_endpoint_reports_optional_renderer_unavailable_without_losing_pdf(pdf_api, monkeypatch):
    def missing_renderer(*args):
        raise ImportError("No module named fitz")
    monkeypatch.setattr("src.document_processing.render_document_page", missing_renderer)
    with pytest.raises(HTTPError) as caught:
        urlopen(pdf_api + "api/pdf-page/pdf-run/visible/1", timeout=10)
    assert caught.value.code == 501
    assert "原PDF" in json.loads(caught.value.read())["error"]
    with urlopen(pdf_api + "api/fulltext/pdf-run/visible", timeout=10) as response:
        assert response.headers.get_content_type() == "application/pdf"
        assert response.read().startswith(b"%PDF-")


def test_pdf_text_endpoint_returns_page_bound_word_coordinates(pdf_api):
    pytest.importorskip("fitz")
    with urlopen(pdf_api + "api/pdf-text/pdf-run/visible/1", timeout=10) as response:
        assert response.headers.get_content_type() == "application/json"
        assert response.headers["Cache-Control"] == "no-store"
        layer = json.load(response)
    assert layer["page"] == layer["page_count"] == 1
    assert "120 participants" in layer["text"]
    assert layer["width"] == 600 and layer["height"] == 800
    assert layer["words"] and all(0 <= w["x"] < 1 and 0 <= w["y"] < 1 for w in layer["words"])


@pytest.mark.parametrize("page", ["0", "-1", "2", "not-a-number"])
def test_pdf_text_endpoint_rejects_invalid_or_out_of_range_page(pdf_api, page):
    pytest.importorskip("fitz")
    with pytest.raises(HTTPError) as caught:
        urlopen(pdf_api + "api/pdf-text/pdf-run/visible/" + page, timeout=10)
    assert caught.value.code == 400 and "error" in json.loads(caught.value.read())


def test_pdf_text_endpoint_reports_missing_engine_and_preserves_original_pdf(pdf_api, monkeypatch):
    def absent(*args):
        raise ImportError("optional text engine")
    monkeypatch.setattr("src.document_processing.document_page_text", absent)
    with pytest.raises(HTTPError) as caught:
        urlopen(pdf_api + "api/pdf-text/pdf-run/visible/1", timeout=10)
    assert caught.value.code == 501
    assert "error" in json.loads(caught.value.read())
    with urlopen(pdf_api + "api/fulltext/pdf-run/visible", timeout=10) as response:
        assert response.read().startswith(b"%PDF-")


def test_corrupt_pdf_text_is_a_readable_error_not_an_aborted_connection(pdf_api, tmp_path):
    pytest.importorskip("fitz")
    (tmp_path / "runs/pdf-run/cache/visible.pdf").write_bytes(b"%PDF-1.7 invalid")
    with pytest.raises(HTTPError) as caught:
        urlopen(pdf_api + "api/pdf-text/pdf-run/visible/1", timeout=10)
    assert caught.value.code == 400 and "error" in json.loads(caught.value.read())
