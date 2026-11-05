import json
import threading
from dataclasses import replace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config import ROOT
from src.ui.payload import build_audit_report, build_payload, describe_run, list_runs_for_ui
from src.conversation import Intent, build_chat_response, classify_intent, _coerce_expanded_query, _normalize_llm_route, _visible_messages
from src.ui.server import STATIC_DIR, make_server


def test_payload_keeps_conflict_and_rate_limit():
    payload = build_payload(ROOT / "runs", "phase2-real")
    assert payload["stats"]["paper_count"] == 7
    assert payload["stats"]["verified_evidence_count"] == 14
    assert payload["display"]["label"] == "基准核验结果"
    claim = next(item for item in payload["claims"] if item["claim_id"] == "claim-008")
    assert claim["status"] == "pending"
    assert payload["map"]["contradictions"]
    evidence_kinds = {edge["kind"] for edge in payload["map"]["edges"]}
    assert payload["map"]["algorithm"] == "specter2_cosine_network"
    assert evidence_kinds <= {"semantic_similarity"}
    assert payload["map"]["similarity_matrix"]["paper_ids"]
    limited = next(item for item in payload["retrieval_runs"] if item["retrieval_id"] == "retrieval-010")
    assert limited["http_status"] == 429
    summary = payload["retrieval_summary"]
    assert "round_failure_count" in summary
    assert summary["round_runs"]
    paper = next(item for item in payload["papers"] if item["paper_id"] == "paper-001")
    assert paper["parse_status"] == "pdf_partial_verified"
    assert payload["workspace"]["scope_version"] == "v0.1"
    assert payload["workspace"]["question"] == payload["question"]
    assert payload["workspace"]["review_item_count"] >= 2


def test_evaluation_isolated_to_empty_and_live_runs(tmp_path):
    import shutil
    from src.io_utils import write_json
    from src.eval_metrics import evaluate_payload
    shutil.copytree(ROOT / "runs" / "phase2-real", tmp_path / "live-review")
    write_json(tmp_path / "live-review" / "run_manifest.json", {
        "run_id": "live-review", "offline": False, "question": "Unrelated topic",
        "live": {"added_paper_ids": [], "retrieval": []}})
    metrics = build_payload(tmp_path, "live-review")["eval"]
    assert metrics["run_id"] == "live-review"
    assert metrics["paper_count"] == metrics["verified_evidence_count"] == 0
    assert metrics["gold_paper_recall"] is None
    assert metrics["delta_vs_no_retrieval"] == {}
    baseline = build_payload(ROOT / "runs", "phase2-real")
    assert baseline["eval"]["verified_evidence_count"] == 14
    other = {**baseline, "run_id": "other", "offline": False, "live": {"added_paper_ids": ["paper-001"]}}
    assert evaluate_payload(other)["paper_count"] == 1


def test_fixture_run_does_not_inherit_real_evaluation(tmp_path):
    from src.config import load_settings
    from src.pipeline import run_pipeline
    result = run_pipeline(load_settings(runs_dir=tmp_path, offline=True), source="fixture")
    metrics = build_payload(tmp_path, result["run_id"])["eval"]
    assert metrics["paper_count"] == metrics["claim_count"] == metrics["verified_evidence_count"] == 0


def test_live_retrieval_summary_counts_current_round_only():
    live_runs = [item for item in list_runs_for_ui(ROOT / "runs") if item["kind"] == "live"]
    if not live_runs:
        return
    payload = build_payload(ROOT / "runs", live_runs[0]["id"])
    summary = payload["retrieval_summary"]
    assert summary["round_runs"]
    assert summary["round_failure_count"] <= len(payload["retrieval_runs"])
    assert summary["round_failure_count"] == sum(1 for run in summary["round_runs"] if run["status"] != "success" or run.get("http_status") == 429)
    assert all("SEMANTIC_SCHOLAR_API_KEY" not in hint for hint in summary["hints"])
    assert any("摘要筛选" in hint for hint in summary["hints"])


def test_live_map_has_semantic_edges_for_added_papers():
    live_runs = [item for item in list_runs_for_ui(ROOT / "runs") if item["kind"] == "live"]
    if not live_runs:
        return
    payload = build_payload(ROOT / "runs", live_runs[0]["id"])
    edges = payload["map"]["edges"]
    kinds = {edge["kind"] for edge in edges}
    assert kinds <= {"semantic_similarity"}
    assert payload["map"]["algorithm"] == "specter2_cosine_network"
    assert all(edge["source"] in {node["paper_id"] for node in payload["map"]["nodes"]} for edge in edges)
    assert all(edge["target"] in {node["paper_id"] for node in payload["map"]["nodes"]} for edge in edges)


def test_live_map_hides_inherited_baseline_papers():
    live_runs = [item for item in list_runs_for_ui(ROOT / "runs") if item["kind"] == "live"]
    if not live_runs:
        return
    run_id = live_runs[0]["id"]
    payload = build_payload(ROOT / "runs", run_id)
    added_ids = set((payload.get("live") or {}).get("added_paper_ids") or [])
    assert all(node["paper_id"] in added_ids for node in payload["map"]["nodes"])
    assert all(edge["source"] in added_ids and edge["target"] in added_ids for edge in payload["map"]["edges"])
    assert not any(node["paper_id"].startswith("paper-00") for node in payload["map"]["nodes"] if node["paper_id"] not in added_ids)


def test_live_payload_marks_inherited_baseline_for_module_filtering():
    live_runs = [item for item in list_runs_for_ui(ROOT / "runs") if item["kind"] == "live"]
    if not live_runs:
        return
    payload = build_payload(ROOT / "runs", live_runs[0]["id"])
    added_ids = set((payload.get("live") or {}).get("added_paper_ids") or [])
    assert added_ids
    assert all(paper["paper_id"] in added_ids or paper["paper_id"].startswith("paper-00") for paper in payload["papers"])


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
    assert "data-clarification-form" in js
    assert "clarification_context" in js
    assert "response_format" in (ROOT / "src" / "conversation.py").read_text(encoding="utf-8")
    assert "正在打开勘文" in html
    assert "--seal" in css
    assert "#boot[hidden]" in css
    assert ".history-bar" in css
    assert "检索文献" in js
    assert 'class="workspace-meta"' in js
    assert "retrieval_failures" in js
    assert "source-status-details" in js
    assert "证据不足/不支持该表述" in js
    assert "SPECTER2 语义星图" in js
    assert "paper-graph" in js
    assert "chat-map-" in js
    assert "data-graph-id" in js
    assert "llmErrorText" in js
    assert "AI 未生成本轮内容，请重试。" in js
    assert "requestAnimationFrame" in js
    assert "specter2_cosine_mds" in js
    assert "pointerenter" in js
    assert "data-open-topic" in js
    assert "选择主题或论文" in js
    assert ".graph-node" in css
    assert ".graph-edge" in css
    assert "claim-008" not in js or "内部编号" in js
    assert "streamlit" not in js.lower()
    assert "new-conversation" in js
    assert "conversation-history" in js
    assert "data-clarification-custom" in js
    assert "clarification-other-input" in js
    assert ".clarification-other" in css
    assert "conversationBeforeRunChange" in js
    assert "state.chat.messages = conversationBeforeRunChange" in js
    assert "chat-compose" in css
    assert "if (result.run_id)" in js
    assert "loadRun(null" not in js
    assert "function renderMarkdown" in js
    assert "inlineMarkdown" in js
    assert ".rich-text ol" in css
    assert ".chat-message.assistant" in css
    assert "sidebarConversations" in js
    assert "data-conversation-rename" in js
    assert "data-workspace-view" in js
    assert "history.pushState" in js
    assert ".conversation-sidebar" in css
    assert 'aria-label="研究工作区"' in js
    assert 'class="nav-more"' in js
    assert ".nav-more" in css
    assert "id=\"search-form\"" in js


def test_ui_server_reuses_current_run_for_direct_follow_up(tmp_path, monkeypatch):
    from src.config import load_settings

    settings_runs = tmp_path / "runs"
    monkeypatch.setattr("src.conversation._llm_direct_answer", lambda *args, **kwargs: ("基于当前数据回答", {"ok": True, "errors": [], "citations": []}))
    (settings_runs / "current-run" / "output").mkdir(parents=True)
    monkeypatch.setattr("src.ui.server.load_settings", lambda **_: load_settings(runs_dir=settings_runs))
    monkeypatch.setattr("src.ui.server.build_payload", lambda *args, **kwargs: {"run_id": "current-run", "papers": [], "claims": [], "stats": {}, "workspace": {}, "question": "当前问题"})
    monkeypatch.setattr("src.ui.server.classify_intent", lambda *args, **kwargs: Intent("follow_up", 0.99, "current data", False, direct_answer=True, answer="基于当前结果回答", route_source="llm"))
    server, url = make_server(port=0, run_id="current-run")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(url.split("?")[0] + "api/chat", data=json.dumps({"message": "继续解释", "run_id": "current-run"}).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
        response = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert response["status"] == "completed"
    assert response["action"] == "reuse_run"
    assert response["run_id"] == "current-run"
    assert response["response"]["intent"]["kind"] == "follow_up"
    assert (settings_runs / "current-run" / "output" / "conversation.json").exists()


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
    assert health["live_search"] is bool(server.RequestHandlerClass.settings.llm_api_key)
    assert health["capabilities"]["llm_configured"] is health["live_search"]
    assert "pid" in health


def test_ui_rejects_run_path_traversal():
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            urlopen(url.split("?")[0] + "api/run/..%2F..%2Fdata", timeout=5)
        except HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("path traversal request should be rejected")
    finally:
        server.shutdown()
        server.server_close()


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


def test_audit_report_is_structured_and_preserves_pending():
    content, filename = build_audit_report(ROOT / "runs", "phase2-real")
    assert filename == "litaudit-phase2-real-audit.md"
    assert "## 研究上下文" in content
    assert "## 证据索引" in content
    assert "`claim-008` | pending" in content
    assert "HTTP 429" in content
    assert "不是自动生成的跨论文长综述" in content


def test_ui_server_serves_audit_report():
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = json.loads(urlopen(url.split("?")[0] + "api/run/phase2-real/report", timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert report["run_id"] == "phase2-real"
    assert report["filename"].endswith("-audit.md")
    assert "## 限制" in report["content"]


def test_ui_server_lists_and_deletes_only_conversation_records(tmp_path, monkeypatch):
    from src.conversation import save_message
    from src.config import load_settings
    settings_runs = tmp_path / "runs"
    save_message(settings_runs, "run-chat", "user", "测试对话")
    monkeypatch.setattr("src.ui.server.load_settings", lambda **_: load_settings(runs_dir=settings_runs))
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conversations = json.loads(urlopen(url.split("?")[0] + "api/conversations", timeout=5).read().decode("utf-8"))
        request = Request(url.split("?")[0] + "api/chat/run-chat", method="DELETE")
        deleted = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert conversations["conversations"][0]["run_id"] == "run-chat"
    assert deleted["deleted"] is True
    assert (settings_runs / "run-chat" / "output").exists()


def test_ui_server_renames_only_target_conversation(tmp_path, monkeypatch):
    from src.conversation import load_conversation, save_message
    from src.config import load_settings

    settings_runs = tmp_path / "runs"
    save_message(settings_runs, "run-a", "user", "A 原名称")
    save_message(settings_runs, "run-b", "user", "B 原名称")
    monkeypatch.setattr("src.ui.server.load_settings", lambda **_: load_settings(runs_dir=settings_runs))
    server, url = make_server(port=0, run_id="run-a")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(url.split("?")[0] + "api/chat/run-a", data=json.dumps({"title": "GPU 架构研究"}).encode("utf-8"), method="PATCH", headers={"Content-Type": "application/json"})
        renamed = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
        conversations = json.loads(urlopen(url.split("?")[0] + "api/conversations", timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert renamed == {"run_id": "run-a", "title": "GPU 架构研究"}
    assert next(item for item in conversations["conversations"] if item["run_id"] == "run-a")["title"] == "GPU 架构研究"
    assert next(item for item in conversations["conversations"] if item["run_id"] == "run-b")["title"] == "B 原名称"
    assert load_conversation(settings_runs, "run-b").get("title") is None


def test_ui_server_does_not_persist_clarification_into_existing_run(tmp_path, monkeypatch):
    from src.config import load_settings
    from src.conversation import Intent

    settings_runs = tmp_path / "runs"
    (settings_runs / "phase2-real" / "output").mkdir(parents=True)
    monkeypatch.setattr("src.ui.server.load_settings", lambda **_: load_settings(runs_dir=settings_runs))
    monkeypatch.setattr("src.ui.server.build_payload", lambda *args, **kwargs: {"run_id": "phase2-real", "papers": [], "stats": {}, "workspace": {}, "question": "基准"})
    monkeypatch.setattr("src.ui.server.classify_intent", lambda *args, **kwargs: Intent("new_topic", 1.0, "clarify", False, needs_clarification=True, clarification_questions=[{"question": "你想研究哪个地区的房地产？", "options": []}]))
    server, url = make_server(port=0, run_id="phase2-real")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(url.split("?")[0] + "api/chat", data=json.dumps({"message": "房地产", "run_id": "phase2-real"}).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
        response = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
    assert response["status"] == "needs_clarification"
    assert response["run_id"] is None
    assert not (settings_runs / "phase2-real" / "output" / "conversation.json").exists()


def test_conversation_intent_routes_only_through_llm(monkeypatch):
    payload = build_payload(ROOT / "runs", "phase2-real")
    routes = iter([
        {"action": "clarify", "questions": [{"question": "你指的是哪个项目？", "options": []}]},
        {"action": "retrieve", "expanded_query": "expanded research query"},
        {"action": "direct_answer", "answer": "generated answer"},
    ])
    monkeypatch.setattr("src.conversation._llm_route", lambda *args, **kwargs: next(routes))
    assert classify_intent("人工智能", payload).needs_clarification is True
    assert classify_intent("已选择范围", payload).expanded_query == "expanded research query"
    assert classify_intent("直接回答", payload).direct_answer is True


def test_conversation_preserves_llm_tool_operation(monkeypatch):
    payload = build_payload(ROOT / "runs", "phase2-real")
    monkeypatch.setattr("src.conversation._llm_route", lambda *args, **kwargs: {"action": "retrieve", "kind": "branch_deepen", "branch": "citation graph", "target_paper_id": "paper-001", "expanded_query": "PaperQA citation graph follow-up"})
    intent = classify_intent("沿 PaperQA 的引用图谱继续找", payload)
    assert intent.kind == "branch_deepen"
    assert intent.needs_retrieval is True
    assert intent.branch == "citation graph"
    assert intent.target_paper_id == "paper-001"


def test_clarification_does_not_generate_search_results():
    payload = build_payload(ROOT / "runs", "phase2-real")
    intent = Intent("new_topic", 1.0, "clarify", False, needs_clarification=True,
                    clarification_questions=[{"question": "你指的是哪个项目？", "options": []}], route_source="llm")
    response = build_chat_response(payload, "帮我看看人工智能在科研中的应用", intent, object())
    assert response["overview_mode"] == "clarification"
    assert response["paper_selection"]["retrieval_status"] == "not_started"
    assert response["papers"] == []


def test_llm_failure_never_returns_fixed_content(tmp_path):
    from src.config import load_settings

    settings = replace(load_settings(runs_dir=tmp_path, offline=False), llm_api_key=None)
    intent = classify_intent("房地产")
    response = build_chat_response({"run_id": None, "papers": []}, "房地产", intent, settings)
    serialized = json.dumps(response, ensure_ascii=False)
    assert response["overview_mode"] == "llm_error"
    assert response["clarification_questions"] if "clarification_questions" in response else True
    assert "软件工程与 Vibe Coding" not in serialized
    assert "科研文献问答与 RAG" not in serialized
    assert "通用 AI Agent" not in serialized


def test_visible_messages_hides_legacy_clarification_pair():
    messages = [
        {"role": "user", "content": "房地产"},
        {"role": "assistant", "content": "旧固定问题", "response": {"overview_mode": "clarification", "intent": {}}},
        {"role": "user", "content": "新的问题"},
        {"role": "assistant", "content": "动态问题", "response": {"overview_mode": "clarification", "intent": {"route_source": "llm"}}},
    ]
    visible = _visible_messages(messages)
    assert [item["content"] for item in visible] == ["新的问题", "动态问题"]


def test_structured_llm_query_is_safe_for_pipeline():
    query = _coerce_expanded_query({
        "original_topic": "房地产",
        "choices": ["市场趋势与价格分析", "海外市场", "实用指南与建议"],
        "scope": "房地产市场研究",
    })
    assert query == "房地产 房地产市场研究 市场趋势与价格分析 海外市场 实用指南与建议"
    assert isinstance(query, str)


def test_llm_route_retries_one_transient_failure(monkeypatch, tmp_path):
    from src.config import load_settings

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            content = json.dumps({
                "action": "clarify",
                "questions": [
                    {"dimension": "focus", "question": "你想研究哪个地区的房地产？", "options": []},
                ],
            })
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    calls = iter([URLError("temporary"), FakeResponse()])

    def fake_urlopen(*args, **kwargs):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    settings = replace(load_settings(runs_dir=tmp_path, offline=False), llm_api_key="test-key")
    monkeypatch.setattr("src.conversation.urlopen", fake_urlopen)
    monkeypatch.setattr("src.conversation.time.sleep", lambda *_: None)
    intent = classify_intent("房地产", settings=settings)
    assert intent.needs_clarification is True
    assert intent.route_error is None


def test_llm_route_retries_one_invalid_response(monkeypatch, tmp_path):
    from src.config import load_settings

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(self.content)}}]}).encode("utf-8")

    valid = {
        "action": "clarify",
        "questions": [
            {"dimension": "focus", "question": "你想研究哪个地区的房地产？", "options": []},
        ],
    }
    responses = iter([FakeResponse({"action": "unknown"}), FakeResponse(valid)])
    settings = replace(load_settings(runs_dir=tmp_path, offline=False), llm_api_key="test-key")
    monkeypatch.setattr("src.conversation.urlopen", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr("src.conversation.time.sleep", lambda *_: None)
    intent = classify_intent("房地产", settings=settings)
    assert intent.needs_clarification is True
    assert intent.route_error is None


def test_malformed_clarify_falls_back_to_retrieve():
    result, error = _normalize_llm_route({"action": "clarify", "questions": []}, "RAG")
    assert error is None
    assert result["action"] == "retrieve"
    assert result["expanded_query"] == "RAG"


def test_clarification_preserves_specific_choices_without_padding():
    question = {"question": "你指的是哪一种图扩散？", "options": ["图上的扩散过程", "生成图结构的扩散模型"]}
    result, error = _normalize_llm_route(
        {"action": "clarify", "questions": [{**question, "dimension": "entity"}]}, "图扩散研究")
    assert error is None
    assert result["action"] == "clarify"
    assert result["questions"] == [question]


def test_clarification_never_fills_or_repeats_generic_options():
    choices = ["综述与经典论文", "方法原理与框架", "实验对比与评测"]
    for questions in (
        ["Astra 是哪个项目？", "关注哪类研究产出？", "希望检索的时间范围是？"],
        [{"dimension": "entity", "question": "你指的是哪个 Astra？", "options": choices}],
        [{"dimension": "focus", "question": "你希望检索的时间范围是？", "options": ["近三年", "不限"]}],
    ):
        result, error = _normalize_llm_route(
            {"action": "clarify", "questions": questions, "expanded_query": "编造的项目"},
            "Astra 在具身智能中的研究")
        assert error is None
        assert result["action"] == "retrieve"
        assert result["expanded_query"] == "Astra 在具身智能中的研究"


def test_clarification_answer_starts_retrieval_without_second_router_round(monkeypatch):
    def unexpected_route(*args, **kwargs):
        raise AssertionError("收到澄清答案后应直接检索")

    monkeypatch.setattr("src.conversation._llm_route", unexpected_route)
    intent = classify_intent("用户补充了项目", clarification_context=["Astra 项目的论文题名"],
                             clarification_topic="Astra 在具身智能中的研究")
    assert intent.needs_retrieval is True
    assert intent.needs_clarification is False
    assert intent.expanded_query == "Astra 在具身智能中的研究 Astra 项目的论文题名"


def test_llm_router_may_delegate_direct_answer_generation(monkeypatch, tmp_path):
    from src.config import load_settings
    import src.conversation as conversation

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            content = json.dumps({"action": "direct_answer", "kind": "paper_explore", "target_paper_id": "paper-001"})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    monkeypatch.setattr(conversation, "urlopen", lambda *args, **kwargs: FakeResponse())
    settings = replace(load_settings(runs_dir=tmp_path, offline=False), llm_api_key="test-key")
    intent = classify_intent("解释 paper-001", {"question": "q", "papers": [{"paper_id": "paper-001", "title": "PaperQA"}]}, settings)
    assert intent.direct_answer is True
    assert intent.kind == "paper_explore"
    assert intent.target_paper_id == "paper-001"
    assert intent.route_error is None


def test_empty_run_direct_answer_is_converted_to_retrieval(monkeypatch):
    monkeypatch.setattr(
        "src.conversation._llm_route",
        lambda *args, **kwargs: {
            "action": "direct_answer",
            "kind": "follow_up",
            "answer": "当前 run 尚无任何结构化数据（papers、claims、evidence 均为空），因此无法基于现有信息回答。",
        },
    )
    intent = classify_intent("RAG")
    assert intent.needs_retrieval is True
    assert intent.direct_answer is False
    assert intent.expanded_query == "RAG"
    assert "无结构化数据" in intent.reason


def test_retrieve_without_expanded_query_uses_user_message():
    result, error = _normalize_llm_route({"action": "retrieve", "kind": "new_topic"}, "RAG 综述")
    assert error is None
    assert result["expanded_query"] == "RAG 综述"
    assert result["action"] == "retrieve"


def test_llm_route_retrieve_without_query_uses_message(monkeypatch, tmp_path):
    from src.config import load_settings

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            content = json.dumps({"action": "retrieve"})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    settings = replace(load_settings(runs_dir=tmp_path, offline=False), llm_api_key="test-key")
    monkeypatch.setattr("src.conversation.urlopen", lambda *args, **kwargs: FakeResponse())
    intent = classify_intent("RAG", settings=settings)
    assert intent.needs_retrieval is True
    assert intent.direct_answer is False
    assert intent.expanded_query == "RAG"
    assert intent.route_error is None


def test_chat_response_does_not_show_all_run_papers_for_unmatched_question(monkeypatch):
    from src.config import load_settings

    payload = build_payload(ROOT / "runs", "phase2-real")
    settings = load_settings(runs_dir=ROOT / "runs", offline=False)
    message = "请检索 quantum banana xyz 相关的科研论文，限定方法和实验结果比较"
    monkeypatch.setattr("src.conversation._llm_overview", lambda *args, **kwargs: ("generated overview", "llm"))
    intent = Intent("new_topic", 1.0, "retrieve", False, expanded_query=message, route_source="llm")
    response = build_chat_response(payload, message, intent, settings)
    assert response["papers"] == []
    assert response["paper_selection"]["total_run_count"] == 7
    assert response["paper_selection"]["matched_count"] == 0
    assert response["paper_selection"]["retrieval_status"] == "partial_failed"


def test_live_overview_excludes_inherited_baseline_papers(monkeypatch):
    from src.config import load_settings
    import src.conversation as conversation

    payload = build_payload(ROOT / "runs", "phase2-real")
    payload["offline"] = False
    payload["question"] = "GPU microarchitecture"
    payload["live"] = {
        "added_paper_ids": [],
        "retrieval": [{"retrieval_id": "retrieval-test", "source": "arxiv", "status": "success", "result_count": 0}],
    }
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "没有新增论文。"}}]}).encode("utf-8")

    def fake_urlopen(request, **kwargs):
        captured.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(conversation, "urlopen", fake_urlopen)
    settings = replace(load_settings(runs_dir=ROOT / "runs", offline=False), llm_api_key="test-key")
    overview, mode = conversation._llm_overview(payload, Intent("new_topic", 1.0, "retrieve", True), settings)
    assert mode == "retrieval_status"
    assert "没有新增候选论文" in overview
    assert "PaperQA" not in overview
    assert captured == {}  # No model call is needed to render observed status.


def test_ui_server_chat_falls_back_without_llm_and_persists_message(tmp_path, monkeypatch):
    from dataclasses import replace
    from src.conversation import build_chat_response
    from src.config import load_settings

    settings = replace(load_settings(runs_dir=ROOT / "runs", offline=False), llm_api_key=None)
    payload = build_payload(ROOT / "runs", "phase2-real")
    response = build_chat_response(payload, "哪些论文有页码证据？", Intent("llm_error", 1.0, "error", False, route_source="llm", route_error="missing_llm_api_key"), settings)
    assert response["overview_mode"] == "llm_error"
    assert response["overview"] == ""
    assert response["actions"] == []
    assert response["papers"] == []
