"""Run a real-PDF, no-LLM deployment smoke check in the active interpreter.

Use a fresh virtual environment and run this script from outside the source
directory to also verify a wheel installation. No credentials are loaded.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from importlib import metadata, resources, util
import json
import os
from pathlib import Path
import platform
import site
import sys
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expect-no-map", action="store_true")
    parser.add_argument("--installation", choices=["editable", "wheel"], default="editable")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    home = output.parent / ("clean-home-" + args.installation + "-" + uuid4().hex[:8])
    home.mkdir()
    # Set an independent workspace before importing config; do not read the
    # repository's real .env or inherit configured service credentials.
    os.environ["LITAUDIT_HOME"] = str(home)
    os.environ["LITAUDIT_RUNS_DIR"] = str(home / "runs")
    os.environ["LITAUDIT_MAP_EMBEDDER"] = "specter2"
    os.environ["LITAUDIT_RERANK_EMBEDDER"] = "auto"
    for key in ["LITAUDIT_LLM_API_KEY", "OPENAI_API_KEY", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"]:
        os.environ.pop(key, None)
    import src
    imported_source = Path(src.__file__).resolve()
    if args.installation == "wheel":
        assert imported_source.is_relative_to(Path(sys.prefix).resolve()), (
            "Wheel verification must import the installed package, not the source checkout", str(imported_source))
    from src.config import Settings
    from src.import_documents import import_pdf
    from src.io_utils import read_json
    from src.paper_library import export_library, library_payload, save_library_item
    from src.research_workspace import method_comparison, search_fulltext, save_review, workspace_payload
    from src.run_paths import resolve_run_file

    settings = Settings(root=home, data_dir=home / "data", fixtures_dir=home / "fixtures",
                        runs_dir=home / "runs", offline=True, log_level="WARNING", llm_api_key=None)
    imported = import_pdf(settings, {
        "filename": args.pdf.name,
        "content_base64": base64.b64encode(args.pdf.read_bytes()).decode(),
        "title": "A Tutorial on Principal Component Analysis", "authors": ["Jonathon Shlens"],
        "year": 2014, "identifier": "arXiv:1404.1100",
        "source_url": "https://arxiv.org/abs/1404.1100",
        "question": "What assumptions does PCA make and how is dimensionality reduction performed?",
    })
    run_id, paper_id = imported["run_id"], imported["paper_id"]
    run = settings.runs_dir / run_id
    manifest = read_json(run / "run_manifest.json")
    audit = read_json(run / "output/fulltext_audit.json")
    document = next(d for d in audit["documents"] if d["paper_id"] == paper_id)
    assert document["status"] == "parsed", document
    local_pdf = resolve_run_file(run, document["response_path"])
    assert local_pdf.read_bytes().startswith(b"%PDF-")
    page_render = {"status": "not_available"}
    if document.get("processing_capabilities", {}).get("pdf_page_render"):
        from io import BytesIO
        from PIL import Image
        from src.document_processing import render_document_page
        png = render_document_page(local_pdf, 1)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        image = Image.open(BytesIO(png)).convert("L")
        dark = sum(count for count, value in image.getcolors(image.width * image.height) if value < 160)
        assert 0 < image.width <= 1600 and 0 < image.height <= 2200
        assert dark > 2000, "Original page PNG must contain actual visible PDF content"
        page_render = {"status": "passed", "width": image.width, "height": image.height,
                       "dark_pixels": dark, "png_bytes": len(png)}
    result = search_fulltext(settings.runs_dir, run_id, "PCA assumptions covariance matrix dimensionality reduction")
    assert result["hits"], result
    assert result["embedding"]["backend"] == "hash", result["embedding"]
    matrix = method_comparison(settings.runs_dir, run_id)
    fields = matrix["papers"][0]["fields"]
    available = {key: value for key, value in fields.items() if value.get("candidate")}
    assert available, fields
    key = "method" if "method" in available else next(iter(available))
    candidate = available[key]["candidate"]
    saved = save_review(settings.runs_dir, run_id, {
        "passage_id": candidate["passage_id"], "expected_text_sha256": candidate["text_sha256"],
        "field": key, "status": "accepted", "quote": candidate.get("quote", candidate["text"]),
        "display_value": candidate.get("value", ""),
        "note": "独立安装验证：已定位原文并保存人工阅读记录。",
    })
    assert saved["review"]["status"] == "accepted"
    assert workspace_payload(settings.runs_dir, run_id)["reviews"]
    save_library_item(settings.runs_dir, run_id, {
        "paper_id": paper_id, "favorite": True, "reading_status": "reading",
        "tags": ["PCA", "clean-install"], "notes": "独立安装中的真实论文阅读笔记。"})
    restored = library_payload(settings.runs_dir, run_id)["items"][0]
    assert restored["favorite"]
    assert restored["reading_status"] == "reading"
    assert restored["tags"] == ["PCA", "clean-install"]
    assert restored["notes"] == "独立安装中的真实论文阅读笔记。"
    exports = {}
    for kind in ["bibtex", "ris", "markdown", "csv"]:
        export = export_library(settings.runs_dir, run_id, kind)
        assert export["paper_count"] == 1
        assert "Principal Component Analysis" in export["content"]
        (output.parent / (args.installation + "-" + export["filename"])).write_text(export["content"], encoding="utf-8")
        exports[kind] = "passed"
    static = {}
    for name in ["index.html", "app.js", "styles.css", "favicon.svg"]:
        data = resources.files("src.ui").joinpath("static", name).read_bytes()
        assert data
        static[name] = len(data)
    no_map = all(util.find_spec(name) is None for name in ["torch", "transformers", "adapters"])
    if args.expect_no_map:
        assert no_map, "Map model dependencies were unexpectedly installed"
        assert imported["status"] == "partial"
        assert read_json(run / "output/map.json")["status"] == "unavailable"
        assert any(e.get("stage") == "map" for e in manifest["errors"])
    versions = {}
    for name in ["litaudit", "pydantic", "python-dotenv", "pypdf", "numpy", "PyMuPDF", "Pillow", "pytesseract", "pytest", "build"]:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    venv_config = Path(sys.prefix) / "pyvenv.cfg"
    config_text = venv_config.read_text(encoding="utf-8") if venv_config.exists() else ""
    system_site = "include-system-site-packages = true" in config_text.lower()
    assert sys.prefix != sys.base_prefix and not system_site
    report = {
        "status": "passed", "installation": args.installation,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "python_executable": sys.executable,
        "virtual_environment": sys.prefix != sys.base_prefix,
        "user_site_enabled": site.ENABLE_USER_SITE,
        "system_site_packages": system_site,
        "imported_source": str(imported_source), "workspace": str(home),
        "credentials_loaded": False, "llm_calls": 0,
        "smoke_test_network_calls": 0, "dependency_installation_network_used": True,
        "versions": versions, "model_dependencies_absent": no_map,
        "pdf_source": "https://arxiv.org/abs/1404.1100", "run_id": run_id,
        "import_status": imported["status"], "document_pages": document["page_count"],
        "text_coverage": document.get("coverage", {}),
        "ocr_engine_available": document.get("processing_capabilities", {}).get("ocr_available", False),
        "pdf_page_render": page_render,
        "passage_count": result["passage_count"], "search_hits": len(result["hits"]),
        "search_backend": result["embedding"],
        "method_field_count": len(fields), "method_fields_with_candidates": sorted(available),
        "manual_review": "passed", "reading_notes": "passed", "exports": exports,
        "installed_static_resources": static,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "installation": args.installation,
                      "python": report["python"], "map_dependencies_absent": no_map,
                      "pdf_pages": document["page_count"], "search_hits": len(result["hits"]),
                      "method_candidates": len(available), "exports": exports}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
