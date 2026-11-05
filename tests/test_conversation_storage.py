import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import src.conversation as conversation


def test_concurrent_messages_and_rename_keep_all_updates(tmp_path, monkeypatch):
    original = conversation.load_conversation
    def slow_read(*args):
        value = original(*args)
        time.sleep(0.01)
        return value
    monkeypatch.setattr(conversation, "load_conversation", slow_read)
    barrier = threading.Barrier(17)
    def save(index):
        barrier.wait(timeout=5)
        conversation.save_message(tmp_path, "chat", "user", str(index))
    def rename():
        barrier.wait(timeout=5)
        conversation.rename_conversation(tmp_path, "chat", "Research")
    with ThreadPoolExecutor(max_workers=17) as pool:
        futures = [pool.submit(save, index) for index in range(16)] + [pool.submit(rename)]
        for future in futures:
            future.result(timeout=10)
    saved = original(tmp_path, "chat")
    assert {m["content"] for m in saved["messages"]} == {str(i) for i in range(16)}
    assert len(saved["messages"]) == 16
    assert saved["title"] == "Research"


def test_failed_atomic_write_preserves_previous_conversation(tmp_path, monkeypatch):
    conversation.save_message(tmp_path, "chat", "user", "original")
    path = tmp_path / "chat" / "output" / "conversation.json"
    before = path.read_bytes()
    def fail(*args):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(conversation.os, "replace", fail)
    with pytest.raises(OSError):
        conversation.save_message(tmp_path, "chat", "user", "new")
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_corrupt_conversation_not_silently_overwritten(tmp_path):
    path = tmp_path / "chat" / "output" / "conversation.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"messages":')
    with pytest.raises(ValueError, match="损坏"):
        conversation.save_message(tmp_path, "chat", "user", "new")
    assert path.read_bytes() == b'{"messages":'
