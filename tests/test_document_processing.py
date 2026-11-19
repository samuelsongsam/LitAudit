from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest

from src.document_processing import annotate_sections, detect_heading, read_document, render_document_page, document_page_text
from src.fulltext_search import build_fulltext_search, chunk_pages


def test_sections_carry_across_pages_and_change_at_real_heading():
    result = annotate_sections([
        "1 Introduction\nA research question is explained.",
        "The introduction continues.\n2 Methods\nWe randomly assigned participants.",
        "Participants completed a follow-up questionnaire.",
        "3 Results\nThe observed accuracy was reported.\nReferences\nA cited method.",
    ])
    assert result[2]["section"] == "methods"
    assert result[1]["headings"][0]["section"] == "methods"
    assert result[3]["headings"][-1]["section"] == "references"
    assert detect_heading("Methods are useful when collecting data.") is None


def test_chunk_sections_and_cross_page_context_keep_primary_quote_and_hash():
    pages = ["2 Methods\nWe assigned 240 participants using a fixed protocol.",
             "Participants were followed for 12 weeks.\n3 Results\nAccuracy improved."]
    passages = chunk_pages({"p": SimpleNamespace(title="Trial")}, {"p": pages})
    first = passages[0]
    assert first.section == "methods"
    assert first.text_sha256 == sha256(first.abstract.encode()).hexdigest()
    assert any(item["page"] == 2 and item["position"] == "next_page" for item in first.context)
    continued = next(p for p in passages if p.page == 2 and p.abstract.startswith("Participants"))
    assert continued.section == "methods"
    assert "3 Results" not in continued.abstract
    assert "240 participants" not in continued.abstract
    assert any(item["page"] == 1 for item in continued.context)
    assert passages[-1].section == "results"
    assert pages[1][continued.char_start:continued.char_end] == continued.abstract


def test_reference_list_does_not_dominate_method_search(monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    result = build_fulltext_search("randomized method", {"p": SimpleNamespace(title="Trial")}, {
        "p": ["Methods\nOur randomized method assigns subjects to a control group.",
              "References\nRandomized method randomized method randomized method."]})
    assert result["hits"][0]["section"] == "methods"
    assert result["hits"][0]["context"][0]["page"] == 2
    assert result["context_policy"] == "adjacent_text_with_separate_page_locations"


def test_section_filter_keeps_continuation_without_repeating_method_keyword(monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    result = build_fulltext_search("participants protocol", {"p": SimpleNamespace(title="Trial")}, {
        "p": ["2 Methods\nWe designed an experiment.",
              "Participants were assigned to a fixed protocol.",
              "3 Results\nParticipants completed the protocol."]}, section="method")
    assert result["hits"][0]["page"] == 2
    assert all(hit["section"] == "methods" for hit in result["hits"])
    assert result["total_passage_count"] == 3
    assert result["passage_count"] == 2


def _pdf(tmp_path, *, scanned=False):
    fitz = pytest.importorskip("fitz")
    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    if scanned:
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (900, 400), "white")
        ImageDraw.Draw(image).text((40, 70), "Scanned experiment with 120 participants", fill="black")
        stream = BytesIO()
        image.save(stream, format="PNG")
        page.insert_image(fitz.Rect(20, 20, 580, 400), stream=stream.getvalue())
    else:
        page.insert_text((45, 45), "2 Methods", fontsize=16)
        page.insert_text((45, 85), "We used a controlled experiment with 120 participants.", fontsize=11)
        page.insert_text((45, 115), "y = x + 2", fontsize=11)
        # Real vector table with cells and text, not a mocked extractor result.
        for y in (180, 220, 260):
            page.draw_line(fitz.Point(45, y), fitz.Point(445, y))
        for x in (45, 245, 445):
            page.draw_line(fitz.Point(x, 180), fitz.Point(x, 260))
        for pos, value in [((60, 205), "Group"), ((260, 205), "Accuracy"),
                           ((60, 245), "Control"), ((260, 245), "0.72")]:
            page.insert_text(pos, value, fontsize=11)
        second = pdf.new_page(width=600, height=800)
        second.insert_text((45, 45), "Participants were followed for 12 weeks.", fontsize=11)
    target = tmp_path / ("scan.pdf" if scanned else "trial.pdf")
    pdf.save(target)
    pdf.close()
    return target


def test_real_pdf_reports_sections_table_formula_and_page_coverage(tmp_path):
    result = read_document(_pdf(tmp_path), ocr_mode="off")
    assert len(result["pages"]) == 2
    assert result["pages"][1]["section"] == "methods"
    assert "120 participants" in result["pages"][0]["text"]
    assert result["coverage"]["text_page_coverage"] == 1
    assert result["coverage"]["table_count"] >= 1
    table = result["pages"][0]["tables"][0]
    assert table["status"] == "extracted_candidate"
    assert any("Control" in str(row) for row in table["rows"])
    assert result["coverage"]["formula_candidate_count"] >= 1
    assert result["capabilities"]["formula_interpretation"] is False


@pytest.mark.parametrize("layout_detected", [False, True])
def test_text_only_page_still_allows_optional_layout_tables(tmp_path, monkeypatch, layout_detected):
    fitz = pytest.importorskip("fitz")
    from src.document_processing import _layout_features

    calls = []

    def get_layout(page):
        page.layout_information = [(10, 10, 100, 100, "table")] if layout_detected else None

    def find_tables(page):
        calls.append(page.number)
        return SimpleNamespace(tables=[])

    monkeypatch.setattr(fitz.Page, "get_layout", get_layout, raising=False)
    monkeypatch.setattr(fitz.Page, "find_tables", find_tables)
    with fitz.open(_pdf(tmp_path)) as document:
        assert _layout_features(document[1])["tables"] == []
    assert calls == ([1] if layout_detected else [])


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_selectable_word_boxes_align_with_original_page_pixels_and_rotation(tmp_path, rotation):
    fitz = pytest.importorskip("fitz")
    from PIL import Image
    source = tmp_path / f"rotation-{rotation}.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((80, 110), "Controlled experiment included 120 participants.", fontsize=16)
        page.set_rotation(rotation)
        second = pdf.new_page(width=600, height=800)
        second.insert_text((60, 90), "SECOND PAGE TEXT", fontsize=16)
        pdf.save(source)
    before = source.read_bytes()
    layer = document_page_text(source, 1)
    image = Image.open(BytesIO(render_document_page(source, 1))).convert("L")
    assert layer["page"] == 1 and layer["page_count"] == 2
    assert "120 participants" in layer["text"] and "SECOND PAGE" not in layer["text"]
    assert [w["text"] for w in layer["words"]] == ["Controlled", "experiment", "included", "120", "participants."]
    for word in layer["words"]:
        assert 0 <= word["x"] < 1 and 0 <= word["y"] < 1
        assert 0 < word["width"] <= 1 and 0 < word["height"] <= 1
        assert word["x"] + word["width"] <= 1.00001
        assert word["y"] + word["height"] <= 1.00001
        crop = image.crop((word["x"] * image.width, word["y"] * image.height,
                           (word["x"] + word["width"]) * image.width,
                           (word["y"] + word["height"]) * image.height))
        assert crop.getextrema()[0] < 100, word
    assert source.read_bytes() == before


def test_word_text_layer_carries_no_neighbor_page_and_handles_scan_without_fabricating_words(tmp_path):
    source = _pdf(tmp_path)
    first, second = document_page_text(source, 1), document_page_text(source, 2)
    assert "120 participants" in first["text"] and "12 weeks" not in first["text"]
    assert "12 weeks" in second["text"] and "120 participants" not in second["text"]
    scan = document_page_text(_pdf(tmp_path, scanned=True), 1)
    assert scan["words"] == [] and not scan["text"].strip()


@pytest.mark.parametrize("value", [True, 0, -1, "1", 1.5, 3])
def test_word_text_layer_rejects_invalid_page_numbers(tmp_path, value):
    with pytest.raises(ValueError):
        document_page_text(_pdf(tmp_path), value)


def test_word_text_layer_rejects_corrupt_and_encrypted_files(tmp_path):
    fitz = pytest.importorskip("fitz")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 invalid")
    with pytest.raises(ValueError):
        document_page_text(broken, 1)
    encrypted = tmp_path / "encrypted.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((60, 60), "PRIVATE TEXT")
        pdf.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="private", owner_pw="owner")
    with pytest.raises(ValueError):
        document_page_text(encrypted, 1)


def test_scanned_pdf_has_explicit_unprocessed_page_when_ocr_unavailable(tmp_path, monkeypatch):
    from src import document_processing
    original = document_processing.processing_capabilities
    monkeypatch.setattr(document_processing, "processing_capabilities", lambda: {
        **original(), "ocr_available": False, "ocr_engine": None})
    result = read_document(_pdf(tmp_path, scanned=True))
    assert result["pages"][0]["text"] == ""
    assert result["pages"][0]["ocr"]["status"] == "unavailable"
    assert result["coverage"]["ocr_required_pages"] == [1]
    assert result["coverage"]["status"] == "partial"
    assert result["pages"][0]["figures"][0]["interpretation"] == "not_performed"


def test_ocr_success_is_labelled_and_not_conflated_with_native_text(tmp_path, monkeypatch):
    from src import document_processing
    original = document_processing.processing_capabilities
    monkeypatch.setattr(document_processing, "processing_capabilities", lambda: {
        **original(), "ocr_available": True})
    monkeypatch.setattr(document_processing, "_ocr_page", lambda *a, **kw: (
        "Methods\nOCR recovered 120 participants.", {"status": "completed", "engine": "test_ocr"}))
    result = read_document(_pdf(tmp_path, scanned=True))
    assert result["pages"][0]["text_source"] == "ocr"
    assert result["coverage"]["native_text_pages"] == []
    assert result["coverage"]["ocr_text_pages"] == [1]
    assert result["coverage"]["ocr_required_pages"] == []
    assert result["pages"][0]["section"] == "methods"


def test_pymupdf_ocr_fallback_uses_relative_language_data(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    from types import SimpleNamespace
    from src import document_processing

    monkeypatch.chdir(tmp_path)
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").touch()
    monkeypatch.setenv("TESSDATA_PREFIX", "tessdata")
    monkeypatch.setattr(document_processing, "_tesseract_executable", lambda: None)
    calls = []

    def recognize(**kwargs):
        calls.append(kwargs)
        return "recognized-page"

    page = SimpleNamespace(rect=SimpleNamespace(width=612, height=792), get_textpage_ocr=recognize,
                           get_text=lambda option, *, textpage: f"OCR text from {textpage}")
    assert document_processing.processing_capabilities()["ocr_engine"] == "pymupdf_tesseract"
    text, result = document_processing._ocr_page(page, languages="eng")
    assert calls == [{"language": "eng", "dpi": 150, "full": True, "tessdata": "tessdata"}]
    assert text == "OCR text from recognized-page"
    assert result == {"status": "completed", "engine": "pymupdf_tesseract", "languages": "eng"}


def test_original_pdf_page_png_contains_actual_page_and_is_bounded(tmp_path):
    from PIL import Image
    source = _pdf(tmp_path)
    before = source.read_bytes()
    image = Image.open(BytesIO(render_document_page(source, 1))).convert("RGB")
    assert image.width <= 1600 and image.height <= 2200
    assert image.width > 600 and image.height > 800
    # The actual vector table and text must be visible, rather than a blank PNG.
    gray = image.convert("L")
    assert gray.getextrema()[0] < 30
    assert sum(count for count, value in gray.getcolors(image.width * image.height) if value < 160) > 2000
    assert render_document_page(source, 1) == render_document_page(source, 1)
    assert source.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]


def test_pdf_page_render_checks_range_and_missing_file(tmp_path):
    source = _pdf(tmp_path)
    for value in [True, 0, -1, "1", 1.5, 3]:
        with pytest.raises(ValueError):
            render_document_page(source, value)
    with pytest.raises(FileNotFoundError):
        render_document_page(tmp_path / "missing.pdf", 1)


def test_page_png_cache_invalidates_on_pdf_change_and_bounds_landscape(tmp_path):
    fitz = pytest.importorskip("fitz")
    from PIL import Image
    source = tmp_path / "changed.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=4000, height=400)
        page.insert_text((40, 40), "FIRST VERSION", fontsize=20)
        pdf.save(source)
    first = render_document_page(source, 1)
    with fitz.open() as pdf:
        page = pdf.new_page(width=4000, height=400)
        page.insert_text((40, 40), "SECOND VERSION WITH DIFFERENT CONTENT", fontsize=20)
        source.write_bytes(pdf.tobytes())
    second = render_document_page(source, 1)
    assert first != second
    image = Image.open(BytesIO(second))
    assert image.width <= 1600 and image.height <= 2200


def test_pdf_page_render_missing_optional_engine_is_import_error(tmp_path, monkeypatch):
    import builtins
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4")
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("optional PyMuPDF not installed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(ImportError, match="PyMuPDF"):
        render_document_page(source, 1)
