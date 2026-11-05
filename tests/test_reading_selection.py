"""Selections carry original-page context without putting internal IDs in prose."""
from dataclasses import replace
from datetime import date
import threading
import time

import pytest

from src.config import load_settings
from src.conversation import load_conversation
from src.fulltext_search import chunk_pages
from src.io_utils import write_json
from src.pipeline import snapshot_dataset
from src.reading_selection import resolve_reader_selection
from src.research_workspace import _corpus, _hit
from src.schema import Dataset, PaperCard, ScreeningLog, dataset_stats
from src.tasks import TaskManager, check_cancelled
from src.ui.server import LitAuditHandler


SELECTED = "Selected original paragraph describes quantization-aware training."


@pytest.fixture
def selection_research(tmp_path, monkeypatch):
    monkeypatch.setenv("LITAUDIT_RERANK_EMBEDDER", "hash")
    monkeypatch.setenv("LITAUDIT_MAP_EMBEDDER", "hash")
    settings = replace(load_settings(runs_dir=tmp_path), llm_api_key="test-only")
    run = tmp_path / "study"
    papers = [PaperCard(paper_id=pid, title=title, source="local-test", retrieved_at=date(2026, 1, 1),
                        dedup_key=pid, url="https://example.test/" + pid,
                        decision="include", reason="Selected for reading")
              for pid, title in [("p1", "Alpha: controlled experiments"),
                                 ("p2", "Beta: alternative methods"), ("hidden", "Other topic")]]
    screening = [ScreeningLog(screening_id="screen-" + p.paper_id, paper_id=p.paper_id,
        stage="title_abstract", decision="include", reason_code="user_selection", reason=p.reason,
        checked_fields=["title"], reviewer="local_user", reviewed_at=date(2026, 1, 1), scope_version="v0.1")
        for p in papers]
    dataset = Dataset(papers=papers, paper_cards=[p.model_copy(deep=True) for p in papers], screening=screening)
    snapshot_dataset(dataset, run / "output")
    write_json(run / "run_manifest.json", {"run_id": "study", "offline": False, "status": "completed",
        "question": "Explain the selected experiment", "live": {"matched_paper_ids": ["p1", "p2"]}})
    write_json(run / "stats.json", dataset_stats(dataset))
    write_json(run / "output/map.json", {"nodes": [], "edges": [], "tracks": [], "algorithm": "fixture"})
    texts = {
        "p1": ["Introduction. The formula is x-y and uses 120 samples.",
               "The method was quantiza-\ntion aware. The exact original line wraps here.", SELECTED],
        "p2": ["This different paper discusses another experimental protocol."],
        "hidden": ["Hidden research material."]}
    for pid, pages in texts.items():
        write_json(run / f"cache/{pid}-pages.json", [{"page": n, "text": text} for n, text in enumerate(pages, 1)])
    write_json(run / "output/fulltext_audit.json", {"documents": [
        {"paper_id": pid, "status": "parsed", "text_path": f"cache/{pid}-pages.json", "page_count": len(pages)}
        for pid, pages in texts.items()]})
    monkeypatch.setattr("src.ui.server.load_settings", lambda **kwargs: settings)
    return settings, texts


def test_reader_selection_restores_exact_original_span_with_layout_whitespace(selection_research):
    settings, texts = selection_research
    result = resolve_reader_selection(settings.runs_dir, "study", {
        "paper_id": "p1", "page": 2, "quote": "The   method was quantization aware."})
    assert result["quote"] == "The method was quantiza-\ntion aware."
    assert result["quote"] in texts["p1"][1]
    assert result["source"] == "stored_original_page" and result["title"].startswith("Alpha")
    browser_copy = resolve_reader_selection(settings.runs_dir, "study", {
        "paper_id": "p1", "page": 2, "quote": "The method was quantiza- tion aware."})
    assert browser_copy["quote"] == result["quote"]
    assert resolve_reader_selection(settings.runs_dir, "study", None) is None
    page = resolve_reader_selection(settings.runs_dir, "study", {"paper_id": "p1", "page": 3, "quote": ""})
    assert page["quote"] == "" and page["page"] == 3
    # Variables and short numeric selections are legitimate reader operations.
    assert resolve_reader_selection(settings.runs_dir, "study", {"paper_id": "p1", "page": 1, "quote": "x"})["quote"] == "x"


@pytest.mark.parametrize("selection", [
    {"paper_id": "p1", "page": 1, "quote": "The formula is x+y"},
    {"paper_id": "p1", "page": 1, "quote": "uses 12.0 samples"},
    {"paper_id": "p1", "page": 1, "quote": "A fabricated result from the paper"},
    {"paper_id": "p1", "page": 2, "quote": SELECTED},
    {"paper_id": "p2", "page": 1, "quote": SELECTED},
    {"paper_id": "hidden", "page": 1, "quote": "Hidden research material."},
    {"paper_id": "absent", "page": 1, "quote": "text"},
    {"paper_id": "p1", "page": 4, "quote": ""},
    {"paper_id": "p1", "page": True, "quote": ""},
    {"paper_id": "p1", "page": 0, "quote": ""},
    {"paper_id": "p1", "page": "1", "quote": ""},
    {"paper_id": "p1", "page": 301, "quote": ""},
    {"paper_id": "p1", "page": 1, "quote": "x", "url": "https://example.test/override"},
])
def test_reader_selection_rejects_forgery_wrong_page_and_outside_scope(selection_research, selection):
    settings, _ = selection_research
    with pytest.raises(ValueError):
        resolve_reader_selection(settings.runs_dir, "study", selection)


def _model_and_reader_handler(settings, monkeypatch, *, old_history=None):
    calls = []
    def forbidden(*args, **kwargs):
        raise AssertionError("Selected-page reading must use local text and no external retrieval/router")
    monkeypatch.setattr("src.ui.server.classify_intent", forbidden)
    monkeypatch.setattr("src.ui.server.run_pipeline", forbidden)
    monkeypatch.setattr("src.conversation.urlopen", forbidden)
    monkeypatch.setattr("src.http_fetch.urlopen", forbidden)
    if old_history is not None:
        real_load = load_conversation
        monkeypatch.setattr("src.ui.server.load_conversation", lambda *args:
                            {"messages": old_history + real_load(*args).get("messages", [])})
    def searches(*args, **kwargs):
        papers, pages, _ = _corpus(settings.runs_dir, "study", kwargs.get("paper_ids"))
        # Simulate ranking that misses the selected page: the reader context
        # must explicitly insert that page before the generic result.
        first = next(p for p in chunk_pages(papers, pages) if p.page == 1)
        return {"hits": [_hit(first, "study")], "passage_count": 1, "indexed_paper_count": len(papers)}
    monkeypatch.setattr("src.research_workspace.search_fulltext", searches)
    def model(current_settings, system, content):
        calls.append(content)
        if "passages" in content:
            selected = content["selected_original_excerpt"]
            assert selected["paper_id"] == "p1" and selected["page"] == 3 and selected["quote"] == SELECTED
            assert content["passages"][0]["paper_id"] == "p1" and content["passages"][0]["page"] == 3
            assert all(p["paper_id"] == "p1" for p in content["passages"])
            return {"sections": [{"kind": "paper_report", "text": "原文讨论量化感知训练。",
                "question_ids": ["q_main"], "sources": [{"passage_id": content["passages"][0]["passage_id"], "quote": SELECTED}]}]}
        return {"verdicts": [{"id": 0, "verdict": "supported"}],
                "coverage": [{"question_id": "q_main", "status": "answered", "section_ids": [0]}]}
    monkeypatch.setattr("src.grounded_reading._call", model)
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    captured = []
    handler._json = lambda value, status=200: captured.append((status, value))
    return handler, calls, captured


def test_selected_page_is_first_in_model_context_with_natural_question_and_old_history(selection_research, monkeypatch):
    settings, _ = selection_research
    history = [{"role": "assistant", "content": "此前读了另一篇论文", "response": {
        "reading_scope": {"paper_ids": ["p2"]}}}]
    handler, calls, captured = _model_and_reader_handler(settings, monkeypatch, old_history=history)
    question = "解释这段内容的含义"
    handler._chat({"run_id": "study", "message": question,
                   "reading_selection": {"paper_id": "p1", "page": 3, "quote": SELECTED}})
    assert captured[-1][0] == 200
    result = captured[-1][1]
    assert result["action"] == "reuse_run" and result["response"]["reading_scope"]["paper_ids"] == ["p1"]
    assert result["response"]["reading_selection"]["page"] == 3
    assert result["response"]["answer_audit"]["citations"][0]["page"] == 3
    assert len(calls) == 2
    assert calls[0]["question"] == question and "p1" not in question
    assert load_conversation(settings.runs_dir, "study")["messages"][0]["content"] == question


def test_late_selection_on_a_long_page_wins_over_its_first_six_chunks(selection_research, monkeypatch):
    settings, texts = selection_research
    long_page = ("An earlier paragraph provides general background for the experiment. " * 145) + SELECTED
    pages = texts["p1"][:2] + [long_page]
    write_json(settings.runs_dir / "study/cache/p1-pages.json",
               [{"page": n, "text": text} for n, text in enumerate(pages, 1)])
    papers, corpus, _ = _corpus(settings.runs_dir, "study", ["p1"])
    chunks = [p for p in chunk_pages(papers, corpus) if p.page == 3]
    assert len(chunks) > 6 and all(SELECTED not in p.abstract for p in chunks[:6])
    handler, calls, captured = _model_and_reader_handler(settings, monkeypatch)
    handler._chat({"run_id": "study", "message": "解释这段内容的含义", "reading_mode": True,
        "reading_selection": {"paper_id": "p1", "page": 3, "quote": SELECTED}})
    assert captured[-1][0] == 200 and len(calls) == 2
    assert SELECTED in calls[0]["passages"][0]["text"]
    assert captured[-1][1]["response"]["answer_audit"]["citations"][0]["quote"] == SELECTED


@pytest.mark.parametrize("scope", [
    {"reading_paper_id": "p2", "message": "解释这段内容"},
    {"reading_paper_id": "p1", "message": "请解释Beta的方法"},
])
def test_selected_excerpt_cannot_be_combined_with_another_paper_scope(selection_research, monkeypatch, scope):
    settings, _ = selection_research
    handler, calls, captured = _model_and_reader_handler(settings, monkeypatch)
    handler._chat({"run_id": "study", "reading_mode": True, "reading_scope_mode": "selected", **scope,
                   "reading_selection": {"paper_id": "p1", "page": 3, "quote": SELECTED}})
    assert captured[-1][0] == 400 and not calls
    assert not load_conversation(settings.runs_dir, "study")["messages"]


def _terminal(manager, task_id):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        result = manager.get(task_id)
        if result["status"] not in {"queued", "running", "cancel_requested"}:
            return result
        time.sleep(.01)
    raise AssertionError("Task did not finish")


def test_cancelled_reader_task_retries_saved_scope_and_page_after_restart(selection_research, monkeypatch):
    settings, _ = selection_research
    body = {"run_id": "study", "message": "解释这段内容的含义", "reading_mode": True,
            "reading_paper_id": "p1", "reading_scope_mode": "selected",
            "reading_selection": {"paper_id": "p1", "page": 3, "quote": SELECTED},
            "request_id": "old-request", "conversation_context": [{"content": "not persisted"}]}
    descriptor = LitAuditHandler._retry_descriptor("/api/chat", body)
    assert descriptor["body"]["reading_selection"] == body["reading_selection"]
    assert "request_id" not in descriptor["body"] and "conversation_context" not in descriptor["body"]
    ready, release = threading.Event(), threading.Event()
    manager = TaskManager(settings.runs_dir)
    def before_model():
        resolve_reader_selection(settings.runs_dir, "study", body["reading_selection"])
        ready.set()
        assert release.wait(5)
        check_cancelled()
        raise AssertionError("The cancelled model must not execute")
    try:
        first = manager.submit("/api/chat", before_model, retry_descriptor=descriptor)
        assert ready.wait(5)
        manager.cancel(first["task_id"])
        release.set()
        assert _terminal(manager, first["task_id"])["status"] == "cancelled"
        assert "retry_descriptor" not in manager.get(first["task_id"])
    finally:
        release.set()
        manager.close()
    restarted = TaskManager(settings.runs_dir)
    try:
        saved = restarted.get_retry_descriptor(first["task_id"])
        handler, calls, _ = _model_and_reader_handler(settings, monkeypatch)
        child = restarted.submit("/api/chat", lambda: handler._execute_operation("/api/chat", saved["body"]),
                                 retry_descriptor=saved, retry_of=first["task_id"])
        done = _terminal(restarted, child["task_id"])
        assert done["status"] == "completed" and done["retry_of"] == first["task_id"]
        assert done["result"]["response"]["reading_scope"]["paper_ids"] == ["p1"]
        assert done["result"]["response"]["reading_selection"]["page"] == 3
        assert len(calls) == 2 and len(load_conversation(settings.runs_dir, "study")["messages"]) == 2
    finally:
        restarted.close()
