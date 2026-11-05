import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, urlopen

import pytest

from src.http_fetch import FetchResult, http_get
from src.provider_runtime import ProviderRuntime, ProviderWaitBudget, retry_after_seconds


class Clock:
    def __init__(self):
        self.value = 100.
        self.waits = []

    def now(self):
        return self.value

    def sleep(self, value):
        self.waits.append(value)
        self.value += value


class Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body=b'{"title":"Study"}'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, *args):
        return self.body


@pytest.fixture
def scheduled(monkeypatch):
    from src import provider_runtime
    clock = Clock()
    runtime = ProviderRuntime(clock=clock.now, sleep=clock.sleep)
    monkeypatch.setattr(provider_runtime, "runtime", runtime)
    return runtime, clock


def test_key_bucket_spans_search_details_and_citations_and_is_private(scheduled, monkeypatch):
    runtime, clock = scheduled
    opened = []
    def connect(request, **kwargs):
        opened.append((request.full_url, clock.now(), request.get_header("Authorization")))
        return Response()
    monkeypatch.setattr("src.http_fetch.urlopen", connect)
    headers = {"Authorization": "Bearer private-key-a"}
    for path in ["works?search=study", "works/W1?select=display_name", "works?filter=cites:W1&per_page=1"]:
        assert http_get("https://api.openalex.org/" + path, headers=headers).status == 200
    assert len(opened) == 3
    assert all(right[1] - left[1] >= .15 - 1e-8 for left, right in zip(opened, opened[1:]))
    assert all(row[2] == "Bearer private-key-a" for row in opened)
    snapshot = runtime.snapshot("openalex", headers=headers)
    assert snapshot["connection"]["status"] == "connected"
    assert "Bearer private-key-a" not in json.dumps(snapshot)
    assert "Bearer private-key-a" not in repr(runtime.buckets)


def test_different_keys_do_not_share_identity_or_cached_results(scheduled, monkeypatch):
    _, clock = scheduled
    calls = []
    monkeypatch.setattr("src.http_fetch.urlopen", lambda request, **kwargs:
        calls.append(request.get_header("Authorization")) or Response())
    url = "https://api.openalex.org/works/W1?select=display_name"
    first = http_get(url, headers={"Authorization": "Bearer one"})
    first.notes.append("consumer mutation")
    cached = http_get(url, headers={"Authorization": "Bearer one"})
    assert "provider_cache_hit" in cached.notes and "consumer mutation" not in cached.notes
    http_get(url, headers={"Authorization": "Bearer two"})
    assert calls == ["Bearer one", "Bearer two"]
    assert clock.value == 100.


def test_concurrent_identical_gets_share_one_network_response(monkeypatch):
    from src import provider_runtime
    runtime = ProviderRuntime()
    monkeypatch.setattr(provider_runtime, "runtime", runtime)
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def connect(request, **kwargs):
        calls.append(request.full_url)
        entered.set()
        assert release.wait(3)
        return Response()
    monkeypatch.setattr("src.http_fetch.urlopen", connect)
    url = "https://api.openalex.org/works/W1"
    def following():
        second_started.set()
        return http_get(url)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(http_get, url)
        assert entered.wait(3)
        second = pool.submit(following)
        assert second_started.wait(3)
        release.set()
        assert first.result(timeout=3).body == second.result(timeout=3).body
    assert len(calls) == 1


def test_retry_after_is_respected_without_spending_a_request_during_long_cooldown(scheduled, monkeypatch):
    runtime, clock = scheduled
    calls = []
    def limited(request, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 429, "Limited", {"Retry-After": "60"}, io.BytesIO(b'{}'))
    monkeypatch.setattr("src.http_fetch.urlopen", limited)
    url = "https://api.openalex.org/works?search=topic"
    result = http_get(url)
    assert result.status == 429 and result.headers["retry-after"] == "60"
    deferred = http_get(url, provider_wait_budget=4)
    assert deferred.status == 429 and "provider_wait_budget" in deferred.notes
    assert len(calls) == 1 and clock.value == 100.
    assert runtime.snapshot("openalex")["rate_limit"]["cooldown_seconds"] == 60


def test_bounded_base_retry_uses_header_and_keeps_429_if_retry_fails(monkeypatch):
    from src import retrieve
    waits, calls = [], []
    def fetch(url, **kwargs):
        calls.append(url)
        return FetchResult(url, 429, headers={"Retry-After": "4"}) if len(calls) == 1 else FetchResult(url, None, error="timeout")
    monkeypatch.setattr(retrieve, "http_get", fetch)
    monkeypatch.setattr("src.provider_runtime.wait_cancelable", lambda duration: waits.append(duration))
    result = retrieve._fetch_with_fallback(["https://example.test"], fetch=fetch, headers=None, mailto=None, timeout=5)
    assert len(calls) == 2 and waits == [4.]
    assert result.status == 429 and "retried_once" in result.notes
    calls.clear()
    def long_wait(url, **kwargs):
        calls.append(url)
        return FetchResult(url, 429, headers={"Retry-After": "30"})
    result = retrieve._fetch_with_fallback(["https://example.test"], fetch=long_wait, headers=None, mailto=None, timeout=5)
    assert len(calls) == 1 and "retry_deferred_provider_cooldown" in result.notes


def test_retry_after_supports_http_date_and_rejects_invalid_values():
    now = datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp()
    assert retry_after_seconds("Thu, 05 Nov 2026 00:00:08 GMT", now=now) == 8
    assert retry_after_seconds("2.5") == 2.5
    assert retry_after_seconds("-1") is None
    assert retry_after_seconds("nan") is None
    assert retry_after_seconds("bad header") is None


def test_waiting_for_another_endpoint_can_be_cancelled_before_network(scheduled, monkeypatch):
    from src.tasks import TaskCancelled
    runtime, clock = scheduled
    scope = runtime.scope("openalex", {"Authorization": "Bearer key"})
    runtime.acquire(scope, clock.now() + 5)
    calls = []
    checks = []
    def check():
        checks.append(True)
        if len(checks) >= 3:
            raise TaskCancelled("controlled stop")
    monkeypatch.setattr("src.tasks.check_cancelled", check)
    with pytest.raises(TaskCancelled):
        runtime.request("https://api.openalex.org/works/W2", {"Authorization": "Bearer key"},
                        lambda: calls.append(True) or FetchResult("url", 200))
    assert not calls and not runtime.flights


def test_cache_is_bounded_and_failures_are_not_reused(scheduled, monkeypatch):
    runtime, clock = scheduled
    runtime.cache_bytes = 15
    runtime.cache_entries = 2
    calls = []
    def perform(request, **kwargs):
        calls.append(request.full_url)
        return Response(b'0123456789')
    monkeypatch.setattr("src.http_fetch.urlopen", perform)
    base = "https://api.openalex.org/works/"
    for path in ["a", "b", "a"]:
        http_get(base + path)
    assert len(calls) == 3 and runtime.cache_size <= 15 and len(runtime.cache) == 1
    clock.value += 301
    http_get(base + "a")
    assert len(calls) == 4


def test_openalex_search_uses_bearer_without_recording_or_forwarding_it(tmp_path, scheduled, monkeypatch):
    from src import retrieve

    calls = []
    def connect(request, **kwargs):
        calls.append(request)
        return Response(b'{"meta":{"count":0},"results":[]}')

    monkeypatch.setattr("src.http_fetch.urlopen", connect)
    monkeypatch.setattr(retrieve, "build_query_plan", lambda *args:
                        [retrieve.QuerySpec("q1", "openalex", "public query", "test")])
    bundle = retrieve.search_all("public query", cache_dir=tmp_path, sleep_s=0,
                                 openalex_api_key="configured-private-key")

    assert len(calls) == 1 and calls[0].get_header("Authorization") == "Bearer configured-private-key"
    assert bundle.runs[0].status == "success"
    assert "configured-private-key" not in json.dumps(bundle.runs[0].model_dump(mode="json"))
    redirected = HTTPRedirectHandler().redirect_request(calls[0], None, 302, "redirect", {}, "https://other.test/")
    assert not redirected.has_header("Authorization")
    runtime, _ = scheduled
    assert runtime.snapshot("openalex")["connection"]["status"] == "untested"
    assert runtime.snapshot("openalex", headers={"Authorization": "Bearer configured-private-key"})["connection"]["status"] == "connected"


def test_search_connection_reports_provider_causes_without_exposing_raw_errors(scheduled, monkeypatch):
    from types import SimpleNamespace
    from src.provider_runtime import test_source_connection as probe

    calls = []
    def connect(request, **kwargs):
        calls.append(request)
        if "openalex.org" in request.full_url and not request.has_header("Authorization"):
            raise HTTPError(request.full_url, 503, "Unavailable", {},
                            io.BytesIO(b'{"message":"Anonymous search is paused while the search cluster recovers"}'))
        if "arxiv.org" in request.full_url:
            raise URLError("[SSL: UNEXPECTED_EOF_WHILE_READING] internal-hostname")
        return Response(b'{"meta":{"count":0},"results":[]}')

    monkeypatch.setattr("src.http_fetch.urlopen", connect)
    anonymous = probe(SimpleNamespace(), "openalex")["source"]
    assert anonymous["connection"]["http_status"] == 503
    assert "暂停了匿名搜索" in anonymous["connection"]["message"]
    assert "search=" in calls[0].full_url
    configured = probe(SimpleNamespace(openalex_api_key="private-key"), "openalex")["source"]
    assert configured["key_configured"] and configured["connection"]["status"] == "connected"
    assert "private-key" not in json.dumps(configured)
    arxiv = probe(SimpleNamespace(), "arxiv")["source"]
    assert arxiv["connection"]["status"] == "failed" and "HTTPS" in arxiv["connection"]["message"]
    assert "internal-hostname" not in json.dumps(arxiv)


def test_extra_pagination_429_still_spends_only_its_single_http_budget(tmp_path, scheduled, monkeypatch):
    from src import retrieve
    calls = []
    monkeypatch.setattr(retrieve, "build_query_plan", lambda *args:
                        [retrieve.QuerySpec("q1", "openalex", "topic", "topic")])
    monkeypatch.setattr("src.retrieval_rank.rank_hits", lambda query, hits: (hits, {"backend": "test"}))
    def perform(request, **kwargs):
        calls.append(request.full_url)
        if len(calls) == 2:
            raise HTTPError(request.full_url, 429, "Limited", {"Retry-After": "1"}, io.BytesIO(b'{}'))
        return Response(json.dumps({"meta": {"count": 3}, "results": [
            {"id": "https://openalex.org/W1", "title": "Topic study", "publication_year": 2024}]}).encode())
    monkeypatch.setattr("src.http_fetch.urlopen", perform)
    result = retrieve.search_all("topic", cache_dir=tmp_path, sleep_s=0, limit_per_source=1,
        supplement={"pages_per_query": 1, "max_requests": 1, "sources": ["openalex"]})
    assert len(calls) == 2 and result.search_budget["additional_requests_used"] == 1
    assert result.runs[-1].http_status == 429 and result.runs[-1].result_count is None


@pytest.fixture
def source_api(tmp_path, monkeypatch, scheduled):
    from src.config import load_settings
    from src.ui.server import make_server
    settings = replace(load_settings(runs_dir=tmp_path), openalex_api_key="private-server-key")
    monkeypatch.setattr("src.ui.server.load_settings", lambda: settings)
    server, base = make_server(port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_source_status_is_offline_and_tests_only_known_server_configuration(source_api, monkeypatch):
    opened = []
    def connect(request, **kwargs):
        opened.append(request)
        return Response()
    monkeypatch.setattr("src.http_fetch.urlopen", connect)
    with urlopen(source_api + "api/sources") as response:
        result = json.load(response)
    assert not opened and {row["id"] for row in result["sources"]} == {"openalex", "arxiv"}
    openalex = next(row for row in result["sources"] if row["id"] == "openalex")
    assert openalex["key_configured"] and openalex["connection"]["status"] == "untested"
    assert "private-server-key" not in json.dumps(result)
    request = Request(source_api + "api/sources/test", data=b'{"source":"openalex"}',
                      headers={"Content-Type": "application/json"})
    with urlopen(request) as response:
        tested = json.load(response)
    assert len(opened) == 1 and opened[0].get_header("Authorization") == "Bearer private-server-key"
    assert tested["source"]["connection"]["status"] == "connected"
    # Explicit tests bypass successful response reuse.
    with urlopen(request):
        pass
    assert len(opened) == 2
    assert "private-server-key" not in json.dumps(tested)


def test_connection_probe_distinguishes_authentication_failure_and_recovery(source_api, monkeypatch):
    calls = []
    def connect(request, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{}'))
        return Response()
    monkeypatch.setattr("src.http_fetch.urlopen", connect)
    request = Request(source_api + "api/sources/test", data=b'{"source":"openalex"}',
                      headers={"Content-Type": "application/json"})
    with urlopen(request) as response:
        failed = json.load(response)
    assert failed["source"]["connection"]["status"] == "authentication_failed"
    with urlopen(request) as response:
        recovered = json.load(response)
    assert recovered["source"]["connection"]["status"] == "connected"
    assert len(calls) == 2


@pytest.mark.parametrize("body", [{"source": "https://attacker.test"},
    {"source": "openalex", "api_key": "user-input"}, {"source": "semantic_scholar"}, {"source": []}, {}])
def test_source_probe_rejects_url_and_secret_injection_before_network(source_api, monkeypatch, body):
    calls = []
    monkeypatch.setattr("src.http_fetch.urlopen", lambda *args, **kwargs: calls.append(True))
    request = Request(source_api + "api/sources/test", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as error:
        urlopen(request)
    assert error.value.code == 400 and not calls
