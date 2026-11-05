from src.config import load_settings
from src.ui.server import LitAuditHandler


def test_skip_clarification_uses_original_question_and_ignores_stale_reading_context(tmp_path, monkeypatch):
    settings = load_settings(runs_dir=tmp_path)
    requests = []
    replies = []

    def unexpected_route(*args, **kwargs):
        raise AssertionError("An explicit search must bypass the router")

    def pipeline(_settings, **options):
        requests.append(options)
        return {"run_id": "live-skip"}

    def payload(_runs_dir, run_id):
        assert run_id == "live-skip"
        return {"run_id": run_id, "papers": []}

    monkeypatch.setattr("src.ui.server.load_settings", lambda **kwargs: settings)
    monkeypatch.setattr("src.ui.server.classify_intent", unexpected_route)
    monkeypatch.setattr("src.ui.server.run_pipeline", pipeline)
    monkeypatch.setattr("src.ui.server.build_payload", payload)
    monkeypatch.setattr("src.ui.server.build_chat_response", lambda *args: {"overview": "检索已完成"})
    monkeypatch.setattr("src.ui.server.save_turn", lambda *args: None)
    monkeypatch.setattr(LitAuditHandler, "_attach_fulltext", lambda *args: None)
    monkeypatch.setattr(LitAuditHandler, "_save_research_context", lambda *args: None)
    handler = object.__new__(LitAuditHandler)
    handler._json = lambda body, status=200: replies.append((body, status))

    question = "检索 Astra 在具身智能中的相关研究"
    body = {"message": question, "run_id": "previous-study", "skip_clarification": True,
            "reading_mode": True, "constraints": {"year_from": 2023}}
    handler._chat(body)

    assert requests == [{"source": "data", "question": question, "live": True,
                         "constraints": {"year_from": 2023}}]
    assert replies[0][1] == 200
    assert replies[0][0]["run_id"] == "live-skip"
    assert replies[0][0]["status"] == "completed"
    assert handler._retry_descriptor("/api/chat", body)["body"]["skip_clarification"] is True
