import subprocess
from time import monotonic

import pytest

from src.grounded_transport import post_model_json
from src.tasks import TaskCancelled


def _substitute_worker(monkeypatch, program):
    spawn = subprocess.Popen
    processes = []

    def substitute(args, **kwargs):
        assert "test-model-key" not in str(args)
        process = spawn([args[0], "-c", program], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("src.grounded_transport.subprocess.Popen", substitute)
    return processes


def test_grounded_transport_passes_request_via_pipe_and_decodes_response(monkeypatch):
    _substitute_worker(monkeypatch, "import json, sys, time; "
                       "request = json.load(sys.stdin); "
                       "assert request['key'] == 'test-model-key'; "
                       "assert request['body'] == {'model': 'model-test'}; "
                       "time.sleep(0.25); "
                       "print(json.dumps({'choices': []}))")
    result = post_model_json("https://example.invalid", "test-model-key", {"model": "model-test"},
                             deadline=monotonic() + 3)
    assert result == {"choices": []}


@pytest.mark.parametrize("cancel", [False, True], ids=["deadline", "cancellation"])
def test_stalled_model_process_is_terminated(monkeypatch, cancel):
    processes = _substitute_worker(monkeypatch, "import time; time.sleep(30)")
    if cancel:
        def check():
            if processes:
                raise TaskCancelled("stop model")
        monkeypatch.setattr("src.tasks.check_cancelled", check)
    with pytest.raises(TaskCancelled if cancel else TimeoutError):
        post_model_json("https://example.invalid", "test-model-key", {"prompt": "x" * 100_000},
                        deadline=monotonic() + (3 if cancel else 0.5))
    assert processes and processes[0].poll() is not None
