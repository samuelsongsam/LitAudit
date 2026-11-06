import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.answer_audit import audit_overview_statements
from src.conversation import load_conversation, save_turn
from src.ui.server import make_server


def test_fulltext_quotes_require_visible_paper_and_exact_passage():
    payload = {"run_id": "r", "offline": False, "live": {"matched_paper_ids": ["p"]},
               "papers": [{"paper_id": "p", "title": "Methods"}],
               "fulltext_index": {"hits": [{"passage_id": "s", "paper_id": "p", "page": 3,
                                              "text": "We evaluated on 300 examples."}]}}
    statement = {"passage_id": "s", "quote": "300 examples", "certainty": "fulltext_only"}
    result = audit_overview_statements(payload, [statement])
    assert result["ok"]
    assert "第 3 页" in result["answer"]
    assert result["citations"][0]["page"] == 3
    assert not audit_overview_statements(payload, [{**statement, "quote": "3000 examples"}])["ok"]
    assert not audit_overview_statements(payload, [{**statement, "passage_id": "other"}])["ok"]
    payload["live"] = {"matched_paper_ids": []}
    assert not audit_overview_statements(payload, [statement])["ok"]


def test_concurrent_turns_are_atomically_paired(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: save_turn(tmp_path, "run", f"Q{i}", f"A{i}"), range(16)))
    messages = load_conversation(tmp_path, "run")["messages"]
    assert len(messages) == 32
    assert len({m["turn_id"] for m in messages}) == 16
    for q, a in zip(messages[::2], messages[1::2]):
        assert q["turn_id"] == a["turn_id"]
        assert q["content"][1:] == a["content"][1:]


@pytest.fixture
def api_server(tmp_path, monkeypatch):
    from src.config import load_settings
    monkeypatch.setattr("src.ui.server.load_settings", lambda **kwargs: load_settings(runs_dir=tmp_path))
    server, url = make_server(port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield url, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def request_json(base, path, body):
    request = Request(base + path.lstrip("/"), data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


@pytest.mark.parametrize("body", [None, [], "text", 1])
def test_non_object_json_is_readable_400(api_server, body):
    base, _ = api_server
    with pytest.raises(HTTPError) as exc:
        request_json(base, "api/chat", body)
    assert exc.value.code == 400
    assert "error" in json.loads(exc.value.read())
    assert json.load(urlopen(base + "api/health"))["ok"]


def test_search_api_forwards_filters_and_validates_types(api_server, monkeypatch):
    from src import research_workspace
    base, runs_dir = api_server
    called = []
    def search(*args, **kwargs):
        called.append((args, kwargs))
        return {"run_id": "r", "hits": [{"passage_id": "s", "page": 2}]}
    monkeypatch.setattr(research_workspace, "search_fulltext", search)
    result = request_json(base, "api/fulltext/search", {"run_id": "r", "query": "方法",
                                                        "paper_ids": ["p"], "section": "method"})
    assert result["hits"][0]["page"] == 2
    assert called[0][0] == (runs_dir, "r", "方法")
    assert called[0][1] == {"paper_ids": ["p"], "section": "method"}
    with pytest.raises(HTTPError) as exc:
        request_json(base, "api/fulltext/search", {"run_id": "r", "query": "q", "paper_ids": "p"})
    assert exc.value.code == 400


def test_health_reports_missing_llm_configuration(api_server):
    from dataclasses import replace
    from src.ui.server import LitAuditHandler
    base, _ = api_server
    LitAuditHandler.settings = replace(LitAuditHandler.settings, llm_api_key=None)
    health = json.load(urlopen(base + "api/health"))
    assert health["ok"] is True
    assert health["live_search"] is False
    assert health["capabilities"]["llm_configured"] is False


def test_direct_answer_receives_and_audits_fulltext(monkeypatch):
    from src.conversation import Intent, _llm_direct_answer
    observed = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps({"statements": [
                {"passage_id": "s", "quote": "We used a control group.", "certainty": "fulltext_only"}]})}}]}).encode()
    def answer(request, **kwargs):
        observed.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr("src.conversation.urlopen", answer)
    payload = {"run_id": "r", "papers": [{"paper_id": "p", "title": "Experiment"}],
               "fulltext_index": {"hits": [{"passage_id": "s", "paper_id": "p", "page": 4,
                                              "text": "We used a control group."}]}}
    settings = SimpleNamespace(llm_api_key="test-key", llm_model="test", llm_base_url="https://example.invalid")
    text, audit = _llm_direct_answer(payload, "实验方法是什么", Intent("follow_up", 1, "follow", False), settings)
    assert audit["ok"]
    assert "正文线索" in text and "第 4 页" in text
    compact = json.loads(observed[0]["messages"][1]["content"])
    assert compact["fulltext_passages"][0]["passage_id"] == "s"
