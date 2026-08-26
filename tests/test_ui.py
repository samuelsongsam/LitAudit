import json
import threading
from urllib.request import urlopen

from src.config import ROOT
from src.ui.payload import build_payload
from src.ui.server import STATIC_DIR, make_server


def test_payload_keeps_conflict_and_rate_limit():
    payload = build_payload(ROOT / "runs", "phase2-real")
    assert payload["stats"]["paper_count"] == 7
    assert payload["stats"]["verified_evidence_count"] == 14
    claim = next(item for item in payload["claims"] if item["claim_id"] == "claim-008")
    assert claim["status"] == "pending"
    assert payload["map"]["edges"]
    assert payload["map"]["contradictions"]
    limited = next(item for item in payload["retrieval_runs"] if item["retrieval_id"] == "retrieval-010")
    assert limited["http_status"] == 429
    paper = next(item for item in payload["papers"] if item["paper_id"] == "paper-001")
    assert paper["parse_status"] == "pdf_partial_verified"


def test_static_shell_exists():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "勘文" in html
    assert "--seal" in css
    assert "#boot[hidden]" in css
    assert ".workspace" in css
    assert "claim-layout" in js
    assert "claim-008" in js
    assert "streamlit" not in js.lower()


def test_ui_server_serves_index_and_run_json():
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        home = urlopen(url.split("?")[0], timeout=5).read().decode("utf-8")
        payload = urlopen(url.split("?")[0] + "api/run/phase2-real", timeout=5).read().decode("utf-8")
        health = json.loads(urlopen(url.split("?")[0] + "api/health", timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert "勘文" in home
    assert "claim-008" in payload
    assert health["ok"] is True
