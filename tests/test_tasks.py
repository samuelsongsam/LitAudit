import json
from pathlib import Path
import threading
import time

import pytest

from src.tasks import TaskManager, report_progress


def wait_terminal(manager, task_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = manager.get(task_id)
        if task["status"] not in {"queued", "running", "cancel_requested"}:
            return task
        time.sleep(.01)
    raise AssertionError("Task did not reach a terminal state")


def test_task_progress_result_and_idempotency_are_persisted(tmp_path):
    manager = TaskManager(tmp_path, workers=1)
    calls = []
    def work():
        calls.append(1)
        report_progress("reading", run_id="research-one")
        return {"run_id": "research-one", "value": 2}
    try:
        first = manager.submit("search", work, request_id="request-one")
        complete = wait_terminal(manager, first["task_id"])
        repeated = manager.submit("search", lambda: calls.append(2), request_id="request-one")
        assert repeated["task_id"] == first["task_id"] and calls == [1]
        assert complete["status"] == "completed" and complete["result"]["value"] == 2
        assert complete["run_id"] == "research-one"
        persisted = json.loads((tmp_path / ".tasks" / (first["task_id"] + ".json")).read_text(encoding="utf-8"))
        assert persisted["status"] == "completed"
        assert any(e["stage"] == "reading" for e in persisted["events"])
        assert "result" not in manager.list()[0]
    finally:
        manager.close()


def test_cancellation_at_checkpoint_preserves_research_reference(tmp_path):
    manager = TaskManager(tmp_path, workers=1)
    ready, release = threading.Event(), threading.Event()
    def work():
        report_progress("fulltext", run_id="saved-run")
        ready.set()
        assert release.wait(5)
        report_progress("map")
        raise AssertionError("cancelled work must not continue past checkpoint")
    try:
        task = manager.submit("audit", work)
        assert ready.wait(5)
        assert manager.cancel(task["task_id"])["status"] == "cancel_requested"
        release.set()
        final = wait_terminal(manager, task["task_id"])
        assert final["status"] == "cancelled" and final["run_id"] == "saved-run"
        assert "result" not in final
    finally:
        release.set()
        manager.close()


def test_queued_cancellation_never_starts_work(tmp_path):
    manager = TaskManager(tmp_path, workers=1)
    started, release = threading.Event(), threading.Event()
    calls = []
    def first():
        started.set()
        assert release.wait(5)
        return {}
    try:
        running = manager.submit("first", first)
        assert started.wait(5)
        queued = manager.submit("second", lambda: calls.append("ran"))
        manager.cancel(queued["task_id"])
        release.set()
        wait_terminal(manager, running["task_id"])
        assert wait_terminal(manager, queued["task_id"])["status"] == "cancelled"
        assert calls == []
    finally:
        release.set()
        manager.close()


def test_restart_marks_unfinished_tasks_interrupted(tmp_path):
    root = tmp_path / ".tasks"
    root.mkdir()
    for i, status in enumerate(["running", "queued", "cancel_requested"]):
        (root / f"task{i}.json").write_text(json.dumps({"task_id": f"task{i}", "status": status,
            "operation": "search", "created_at": "2026-11-04T00:00:00Z"}), encoding="utf-8")
    manager = TaskManager(tmp_path)
    try:
        assert all(t["status"] == "interrupted" for t in manager.list())
        assert json.loads((root / "task0.json").read_text(encoding="utf-8"))["status"] == "interrupted"
        assert manager.cancel("task0")["status"] == "interrupted"
    finally:
        manager.close()


def test_idempotency_key_cannot_alias_another_operation(tmp_path):
    manager = TaskManager(tmp_path)
    try:
        first = manager.submit("search", lambda: {}, request_id="same-id")
        wait_terminal(manager, first["task_id"])
        with pytest.raises(ValueError):
            manager.submit("import_pdf", lambda: {}, request_id="same-id")
    finally:
        manager.close()


def test_acknowledged_cancellation_wins_over_result_publication(tmp_path):
    """Make the return/cancel race deterministic without sleeps."""
    manager = TaskManager(tmp_path, workers=1)
    returning, publishing, release = threading.Event(), threading.Event(), threading.Event()
    class PublishGate:
        def __init__(self): self.inner = threading.RLock()
        def __enter__(self):
            if returning.is_set() and threading.current_thread().name.startswith("litaudit-task"):
                publishing.set()
                assert release.wait(5)
            self.inner.acquire()
            return self
        def __exit__(self, *args): self.inner.release()
    manager.lock = PublishGate()
    def work():
        returning.set()
        return {"run_id": "finished-before-cancel"}
    try:
        task = manager.submit("reading", work)
        assert publishing.wait(5)
        assert manager.cancel(task["task_id"])["status"] == "cancel_requested"
        release.set()
        final = wait_terminal(manager, task["task_id"])
        assert final["status"] == "cancelled"
    finally:
        release.set()
        manager.close()
