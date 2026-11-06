"""Page-grounded PDF processing with explicit coverage and optional OCR.

Text extraction, layout detection and human understanding are separate states.
No detected table, figure or formula region is treated as a verified claim.
"""
from __future__ import annotations

import importlib.util
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import threading
from hashlib import sha256
from time import monotonic
from typing import Any


SECTION_TITLES = [
    ("abstract", r"abstract|摘要"),
    ("introduction", r"introduction|引言|绪论"),
    ("background", r"background|背景"),
    ("related_work", r"related works?|literature review|相关工作|文献综述"),
    ("methods", r"materials? and methods?|methods?|methodology|approach|proposed method|方法|研究方法|材料与方法"),
    ("experimental_setup", r"experimental setup|experiments?|experimental design|implementation details|实验设置|实验设计|实验"),
    ("data", r"data(?:sets?)?|data collection|participants|数据集|数据|样本|受试者"),
    ("results", r"results?(?: and discussion)?|evaluation|evaluation results|实验结果|结果|评估"),
    ("discussion", r"discussion|讨论"),
    ("limitations", r"limitations?(?: and future work)?|limitations? and (?:broader )?impacts?|局限性|研究局限|局限"),
    ("conclusion", r"conclusions?(?: and future work)?|concluding remarks|结论|总结"),
    ("references", r"references|bibliography|参考文献"),
    ("appendix", r"appendix(?:\s+[a-z0-9]+)?|appendices|supplementary (?:material|information)|附录|补充材料"),
]
_PREFIX = r"(?:(?:\d+(?:\.\d+)*[.)]?|[IVXivx]+[.)]?|[A-Z][.)])\s*)?"
_cache: OrderedDict[tuple, dict] = OrderedDict()
_cache_lock = threading.Lock()
_ocr_lock = threading.Lock()


def detect_heading(line: str) -> dict[str, str] | None:
    value = re.sub(r"\s+", " ", line).strip().strip("·• ")
    if not value or len(value) > 110:
        return None
    for section, title in SECTION_TITLES:
        # Numbered subheadings may include a short descriptive subtitle.
        if re.fullmatch(_PREFIX + rf"(?:{title})(?:\s*[:：—–-]\s*[^.!?。]{{1,60}})?", value, re.I):
            return {"section": section, "title": value}
    return None


def page_headings(text: str) -> list[dict[str, Any]]:
    result = []
    offset = 0
    for line in (text or "").splitlines(keepends=True):
        heading = detect_heading(line)
        if heading:
            result.append({**heading, "char_offset": offset})
        offset += len(line)
    return result


def annotate_sections(pages: list[str]) -> list[dict[str, Any]]:
    """Carry a recognised section across pages and preserve heading offsets."""
    active = None
    result = []
    for number, text in enumerate(pages, start=1):
        headings = page_headings(text)
        start_section = active
        if headings and not text[:headings[0]["char_offset"]].strip():
            start_section = headings[0]["section"]
        if headings:
            active = headings[-1]["section"]
        result.append({"page": number, "section": start_section or active,
                       "start_section": start_section, "end_section": active, "headings": headings})
    return result


def _tesseract_executable() -> str | None:
    configured = os.getenv("LITAUDIT_TESSERACT_CMD", "").strip()
    return configured if configured and Path(configured).is_file() else shutil.which("tesseract")


def _mupdf_tessdata() -> str | None:
    configured = os.getenv("TESSDATA_PREFIX", "").strip()
    if configured and Path(configured).is_dir() and any(Path(configured).glob("*.traineddata")):
        # On Windows an ASCII relative path also works under a Unicode workspace.
        return configured
    return None


def processing_capabilities() -> dict[str, Any]:
    fitz = importlib.util.find_spec("fitz") is not None
    ocr_engine = None
    if fitz and _tesseract_executable() and importlib.util.find_spec("pytesseract") is not None:
        ocr_engine = "tesseract"
    elif fitz and _mupdf_tessdata():
        ocr_engine = "pymupdf_tesseract"
    return {"text_extraction": "pypdf", "layout_detection": fitz,
            "table_extraction": fitz, "image_region_detection": fitz,
            "pdf_page_render": fitz,
            "ocr_available": ocr_engine is not None, "ocr_engine": ocr_engine,
            "ocr_setup": "Install optional documents dependencies and either Tesseract or local language data in TESSDATA_PREFIX.",
            "formula_interpretation": False, "figure_interpretation": False}


@lru_cache(maxsize=12)
def _render_document_page_cached(path: str, mtime_ns: int, file_size: int, page: int) -> bytes:
    """Keep only bounded original-page PNGs; metadata arguments invalidate cache."""
    import fitz  # Optional documents dependency; preserve ImportError for callers.

    try:
        document = fitz.open(path)
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise ValueError("invalid_pdf_document") from exc
    with document:
        if document.needs_pass:
            raise ValueError("pdf_password_required")
        if page > document.page_count:
            raise ValueError("pdf_page_out_of_range")
        original = document.load_page(page - 1)
        rect = original.rect
        if rect.is_empty or rect.is_infinite:
            raise ValueError("invalid_pdf_page_dimensions")
        # One-pixel margin accounts for rasterizer rounding on unusual page sizes.
        # Bound allocation before rendering, including landscape and rotated pages.
        scale = min(1599 / max(rect.width, 1), 2199 / max(rect.height, 1), 3.0)
        pixmap = original.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
        return pixmap.tobytes("png")


def render_document_page(pdf_path: str | Path, page: int) -> bytes:
    """Render an actual PDF page as PNG bytes without writing research materials.

    Page numbering starts at one. The optional PyMuPDF dependency raises
    ImportError when unavailable; invalid page numbers raise ValueError. Each
    image is at most 1600x2200 pixels, and at most 12 pages are cached in memory.
    """
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("pdf_page_must_be_positive_integer")
    path = Path(pdf_path).resolve(strict=True)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    stat = path.stat()
    return _render_document_page_cached(str(path), stat.st_mtime_ns, stat.st_size, page)


def _ocr_page(page, *, languages: str, timeout: float = 30) -> tuple[str, dict]:
    from src.tasks import check_cancelled, TaskCancelled
    check_cancelled()
    engine = processing_capabilities()["ocr_engine"]
    if not engine:
        return "", {"status": "unavailable", "engine": None, "reason": "tesseract_not_available"}
    try:
        # Bound raster size even for an unusually large PDF page.
        scale = min(150/72, 2600/max(page.rect.width, page.rect.height, 1))
        if engine == "pymupdf_tesseract":
            dpi = int(scale * 72)
            if dpi < 1:
                raise ValueError("invalid_pdf_page_dimensions")
            with _ocr_lock:
                check_cancelled()
                recognized = page.get_textpage_ocr(language=languages, dpi=dpi, full=True, tessdata=_mupdf_tessdata())
                text = page.get_text("text", textpage=recognized)
        else:
            from PIL import Image
            import pytesseract
            import fitz
            pytesseract.pytesseract.tesseract_cmd = _tesseract_executable() or "tesseract"
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            text = pytesseract.image_to_string(image, lang=languages, timeout=timeout)
        check_cancelled()
        return text, {"status": "completed" if text.strip() else "empty", "engine": engine, "languages": languages}
    except Exception as exc:
        if isinstance(exc, TaskCancelled):
            raise
        return "", {"status": "failed", "engine": engine, "reason": type(exc).__name__}


def _layout_features(page) -> dict:
    import fitz

    features = {"tables": [], "figures": [], "formula_candidates": []}
    try:
        # Region metadata does not need image hashes, xrefs or pixel buffers.
        for i, item in enumerate(page.get_image_info()):
            features["figures"].append({"region_id": f"image-{i+1}", "bbox": [round(v, 2) for v in item["bbox"]],
                                        "width": item.get("width"), "height": item.get("height"),
                                        "status": "region_detected", "interpretation": "not_performed"})
    except Exception:
        features["image_detection_status"] = "unavailable"
    try:
        text_flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
        for block in page.get_text("dict", flags=text_flags).get("blocks", []):
            for line in block.get("lines", []):
                value = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if 2 < len(value) < 250 and (re.search(r"[∑∫√≈≠≤≥∂∇∞]", value) or re.search(r"[A-Za-zα-ωΑ-Ω]\s*=\s*[^=]", value)):
                    features["formula_candidates"].append({"text": value, "bbox": [round(v, 2) for v in line["bbox"]],
                                                            "status": "text_pattern_candidate", "interpretation": "not_performed"})
    except Exception:
        features["formula_detection_status"] = "unavailable"
    if hasattr(page, "find_tables"):
        try:
            # The default table strategies need vector lines. Avoid parsing every
            # glyph on pages with no drawings unless optional layout can find a table.
            try:
                no_drawings = not page.rotation and not page.get_cdrawings()
            except Exception:
                no_drawings = False
            if no_drawings:
                if hasattr(page, "get_layout"):
                    page.get_layout()
                if not getattr(page, "layout_information", None):
                    return features
            tables = page.find_tables().tables
            for i, table in enumerate(tables[:20]):
                features["tables"].append({"table_id": f"table-{i+1}", "bbox": [round(v, 2) for v in table.bbox],
                                           "rows": table.extract(), "row_count": table.row_count,
                                           "column_count": table.col_count, "status": "extracted_candidate"})
        except Exception:
            features["table_extraction_status"] = "unavailable"
    return features


def _read_document(pdf_path: str | Path, *, ocr_mode: str = "auto", max_pages: int = 300,
                   max_ocr_pages: int = 12, ocr_languages: str | None = None,
                   deadline: float | None = None) -> dict:
    """Extract native page text first; use optional layout/OCR without hiding gaps."""
    from src.tasks import check_cancelled

    def remaining_time() -> float:
        remaining = float("inf") if deadline is None else deadline - monotonic()
        if remaining <= 0:
            raise ValueError("pdf_processing_timeout")
        return remaining

    if ocr_mode not in {"auto", "off"}:
        raise ValueError("ocr_mode must be auto or off")
    remaining_time()
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    if len(reader.pages) > max_pages:
        raise ValueError("page_limit_exceeded")
    capabilities = processing_capabilities()
    layout = None
    if capabilities["layout_detection"]:
        try:
            import fitz
            layout = fitz.open(pdf_path)
        except Exception:
            capabilities = {**capabilities, "layout_detection": False, "table_extraction": False,
                            "image_region_detection": False}
    rows = []
    attempts = 0
    languages = ocr_languages or os.getenv("LITAUDIT_OCR_LANG", "eng")
    try:
        for i, page in enumerate(reader.pages):
            check_cancelled()
            remaining_time()
            extraction_error = None
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                text = ""
                extraction_error = type(exc).__name__
            source = "native_text" if text.strip() else "none"
            if not text.strip() and layout is not None:
                try:
                    text = layout[i].get_text("text") or ""
                    if text.strip():
                        source = "native_layout_text"
                except Exception:
                    pass
            remaining_time()
            features = _layout_features(layout[i]) if layout is not None else {
                "tables": [], "figures": [], "formula_candidates": [], "layout_status": "not_available"}
            # Sparse native text plus a large image is often a scanned page.
            sparse = len(re.sub(r"\s", "", text)) < 35
            needs_ocr = sparse and bool(features["figures"] or not text.strip())
            ocr = {"status": "not_needed", "engine": None}
            if needs_ocr:
                if ocr_mode == "off":
                    ocr = {"status": "disabled", "reason": "ocr_disabled"}
                elif layout is None or not capabilities["ocr_available"]:
                    ocr = {"status": "unavailable", "reason": "ocr_engine_or_layout_not_available"}
                elif attempts >= max_ocr_pages:
                    ocr = {"status": "deferred", "reason": "ocr_batch_limit"}
                else:
                    attempts += 1
                    extracted, ocr = _ocr_page(layout[i], languages=languages, timeout=min(30, remaining_time()))
                    if extracted.strip():
                        # OCR has its own source label; don't merge it into native
                        # text and accidentally imply native positional precision.
                        text = extracted
                        source = "ocr"
            rows.append({"page": i+1, "text": text, "text_sha256": sha256(text.encode()).hexdigest(),
                         "text_source": source, "text_extraction_error": extraction_error,
                         "ocr": ocr, **features})
    finally:
        if layout is not None:
            layout.close()
    for row, section in zip(rows, annotate_sections([r["text"] for r in rows])):
        row.update(section)
    remaining_time()
    pending = [r["page"] for r in rows if r["ocr"]["status"] in {"unavailable", "disabled", "deferred", "failed", "empty"}]
    text_pages = [r["page"] for r in rows if r["text"].strip()]
    return {"backend": "pypdf_with_optional_pymupdf", "pages": rows, "capabilities": capabilities,
            "coverage": {"page_count": len(rows), "text_pages": text_pages,
                         "native_text_pages": [r["page"] for r in rows if r["text_source"] in {"native_text", "native_layout_text"}],
                         "ocr_text_pages": [r["page"] for r in rows if r["text_source"] == "ocr"],
                         "no_text_pages": [r["page"] for r in rows if not r["text"].strip()],
                         "ocr_required_pages": pending, "ocr_attempted_pages": attempts,
                         "text_extraction_error_pages": [r["page"] for r in rows if r["text_extraction_error"]],
                         "text_page_coverage": len(text_pages)/len(rows) if rows else 0,
                         "table_count": sum(len(r["tables"]) for r in rows),
                         "figure_region_count": sum(len(r["figures"]) for r in rows),
                         "formula_candidate_count": sum(len(r["formula_candidates"]) for r in rows),
                         "status": "partial" if pending else "text_extracted",
                         "scope": "extraction_coverage_not_reading_or_semantic_verification"}}


def document_page_text(pdf_path: str | Path, page: int) -> dict:
    """Return original PDF words in normalized coordinates for selectable reading."""
    import fitz
    from src.tasks import check_cancelled
    check_cancelled()
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("invalid_page")
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        document = fitz.open(path)
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise ValueError("invalid_pdf_document") from exc
    with document:
        if document.needs_pass:
            raise ValueError("pdf_password_required")
        if page > len(document):
            raise ValueError("invalid_page")
        original = document[page - 1]
        bounds = original.rect
        if bounds.is_empty or bounds.is_infinite:
            raise ValueError("invalid_pdf_page_dimensions")
        words = []
        for word in original.get_text("words", sort=True)[:16000]:
            rectangle = fitz.Rect(word[:4]) * original.rotation_matrix
            words.append({"text": word[4], "x": rectangle.x0 / bounds.width,
                          "y": rectangle.y0 / bounds.height,
                          "width": rectangle.width / bounds.width,
                          "height": rectangle.height / bounds.height,
                          "block": word[5], "line": word[6]})
        check_cancelled()
        return {"page": page, "page_count": len(document), "width": bounds.width,
                "height": bounds.height, "words": words, "text": original.get_text("text")}


def read_document(pdf_path: str | Path, *, ocr_mode: str = "auto", max_pages: int = 300,
                  max_ocr_pages: int = 12, ocr_languages: str | None = None,
                  timeout_seconds: float | None = None) -> dict:
    """Cache content-addressed extraction, returning independent editable metadata."""
    from src.tasks import check_cancelled
    check_cancelled()
    deadline = monotonic() + timeout_seconds if timeout_seconds is not None else None
    content_hash = sha256(Path(pdf_path).read_bytes()).hexdigest()
    languages = ocr_languages or os.getenv("LITAUDIT_OCR_LANG", "eng")
    key = (content_hash, ocr_mode, max_pages, max_ocr_pages, languages,
           os.getenv("LITAUDIT_TESSERACT_CMD", ""), os.getenv("TESSDATA_PREFIX", ""),
           json.dumps(processing_capabilities(), sort_keys=True))
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return deepcopy(_cache[key])
    result = _read_document(pdf_path, ocr_mode=ocr_mode, max_pages=max_pages,
                            max_ocr_pages=max_ocr_pages, ocr_languages=languages, deadline=deadline)
    with _cache_lock:
        _cache[key] = deepcopy(result)
        _cache.move_to_end(key)
        while len(_cache) > 8:
            _cache.popitem(last=False)
    return result
