import json
import subprocess
from time import monotonic

import pytest

from src.http_fetch import PROVIDER_TIMEOUT, FetchResult, http_get
from src.provider_runtime import ProviderRuntime
from src.retrieve import fetch_related_hits
from src.tasks import TaskCancelled


def test_identifier_lookup_and_citations_share_one_provider_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr("src.provider_runtime.runtime", ProviderRuntime())
    calls = []

    def worker(script, payload, *, deadline):
        request = json.loads(payload)
        assert request["headers"] == {"Authorization": "Bearer synthetic-citation-key"}
        assert "synthetic-citation-key" not in script
        calls.append((request["url"], deadline))
        if len(calls) == 1:
            return 0, b'{"status":200,"headers":{}}\n{"id":"https://openalex.org/W1"}'
        return 0, b'{"status":429,"headers":{"retry-after":"4"}}\n{}'

    monkeypatch.setattr("src.grounded_transport.run_transport_worker", worker)
    start = monotonic()
    bundle = fetch_related_hits("DOI:10.1/example", "references", cache_dir=tmp_path,
                                api_key="synthetic-citation-key")

    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    assert 23 <= calls[0][1] - start <= 25
    assert [run.status for run in bundle.runs] == ["success", "rate_limited"]
    assert all("synthetic-citation-key" not in run.model_dump_json() for run in bundle.runs)


def test_citation_timeout_is_a_failed_request_not_an_empty_success(tmp_path):
    def fetch(url, **kwargs):
        return FetchResult(url, None, error=PROVIDER_TIMEOUT)

    bundle = fetch_related_hits("W1", "citations", cache_dir=tmp_path, fetch=fetch)
    assert bundle.hits == [] and bundle.runs[0].result_count is None
    assert bundle.citation_graph["requests"] == [{"step": "citations", "status": "failed",
        "http_status": None, "error_code": PROVIDER_TIMEOUT}]


@pytest.mark.parametrize("cancel", [False, True], ids=["deadline", "cancellation"])
def test_stalled_citation_transport_terminates_worker_and_releases_provider(monkeypatch, cancel):
    runtime = ProviderRuntime()
    monkeypatch.setattr("src.provider_runtime.runtime", runtime)
    url = "https://api.openalex.org/works?filter=cites%3AW1"
    processes = []
    spawn = subprocess.Popen

    def start_worker(args, **kwargs):
        process = spawn([args[0], "-c", "import time; time.sleep(30)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("src.grounded_transport.subprocess.Popen", start_worker)
    if cancel:
        def check_cancelled():
            if processes:
                raise TaskCancelled("stop citation discovery")

        monkeypatch.setattr("src.tasks.check_cancelled", check_cancelled)
        with pytest.raises(TaskCancelled):
            http_get(url, deadline=monotonic() + 3)
    else:
        result = http_get(url, deadline=monotonic() + 0.5)
        assert result.error == PROVIDER_TIMEOUT and result.status is None
    assert processes and processes[0].poll() is not None
    assert not runtime.flights
