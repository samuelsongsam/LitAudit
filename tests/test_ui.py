import json
import threading
from urllib.request import Request, urlopen

from src.config import ROOT
from src.ui.payload import build_payload, describe_run, list_runs_for_ui
from src.ui.server import STATIC_DIR, make_server


def test_payload_keeps_conflict_and_rate_limit():
    payload = build_payload(ROOT / "runs", "phase2-real")
    assert payload["stats"]["paper_count"] == 7
    assert payload["stats"]["verified_evidence_count"] == 14
    assert payload["display"]["label"] == "基准核验结果"
    claim = next(item for item in payload["claims"] if item["claim_id"] == "claim-008")
    assert claim["status"] == "pending"
    assert payload["map"]["edges"]
    assert payload["map"]["contradictions"]
    limited = next(item for item in payload["retrieval_runs"] if item["retrieval_id"] == "retrieval-010")
    assert limited["http_status"] == 429
    paper = next(item for item in payload["papers"] if item["paper_id"] == "paper-001")
    assert paper["parse_status"] == "pdf_partial_verified"


def test_run_labels_are_human_readable():
    runs = list_runs_for_ui(ROOT / "runs")
    assert runs
    baseline = next(item for item in runs if item["id"] == "phase2-real")
    assert baseline["label"] == "基准核验结果"
    assert "篇" in baseline["subtitle"]
    live = next((item for item in runs if item["kind"] == "live"), None)
    if live is not None:
        assert live["label"].startswith("在线检索")


def test_static_shell_exists():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "勘文" in html
    assert "正在打开勘文" in html
    assert "--seal" in css
    assert "#boot[hidden]" in css
    assert ".history-bar" in css
    assert "检索文献" in js
    assert "基准核验结果" in js
    assert "claim-008" not in js or "内部编号" in js
    assert "streamlit" not in js.lower()


def test_ui_server_serves_index_and_run_json():
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        home = urlopen(url.split("?")[0], timeout=5).read().decode("utf-8")
        payload = json.loads(urlopen(url.split("?")[0] + "api/run/phase2-real", timeout=5).read().decode("utf-8"))
        runs = json.loads(urlopen(url.split("?")[0] + "api/runs", timeout=5).read().decode("utf-8"))
        health = json.loads(urlopen(url.split("?")[0] + "api/health", timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert "勘文" in home
    assert payload["display"]["label"] == "基准核验结果"
    assert runs["runs"][0]["label"]
    assert health["ok"] is True
    assert health["live_search"] is True
    assert "pid" in health


def test_ui_live_route_accepts_post(monkeypatch):
    monkeypatch.setattr(
        "src.ui.server.run_pipeline",
        lambda *args, **kwargs: {"run_id": "live_test", "offline": False, "live": {"added_paper_ids": []}},
    )
    monkeypatch.setattr("src.ui.server.ask_payload", lambda *args, **kwargs: {"papers": []})
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            url.split("?")[0] + "api/live",
            data=json.dumps({"question": "PaperQA RAG"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        payload = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert payload["run_id"] == "live_test"
    assert payload["offline"] is False


def test_describe_run_demo():
    info = describe_run(ROOT / "runs", "demo")
    assert info["label"] == "演示数据（测试用）"
