"""Shared provider scheduling and short-lived response reuse.

The runtime is process-local. Every real GET reaches it through ``http_get``;
the request budget in retrieval code remains responsible for retry counts.
Keys are hashed for bucket identity and are never returned by status endpoints.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import threading
import time
from urllib.parse import urlencode, urlparse


PROVIDERS = {
    "openalex": {"label": "OpenAlex", "interval": .15,
                 "environment_variable": "OPENALEX_API_KEY", "apply_url": "https://openalex.org/settings/api"},
    "arxiv": {"label": "arXiv", "interval": 3.0,
              "environment_variable": None, "apply_url": "https://arxiv.org"},
}


def provider_for_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host == "api.openalex.org":
        return "openalex"
    if host in {"arxiv.org", "export.arxiv.org", "www.arxiv.org"}:
        return "arxiv"
    return None


def retry_after_seconds(value: str | None, *, now: float | None = None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(str(value))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = date.timestamp() - (time.time() if now is None else now)
        except (TypeError, ValueError, OverflowError):
            return None
    if not 0 <= seconds < float("inf"):
        return None
    return min(seconds, 3600.0)


def wait_cancelable(seconds: float, *, sleep=None, clock=None) -> None:
    from src.tasks import check_cancelled
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    end = clock() + max(0, seconds)
    while True:
        check_cancelled()
        remaining = end - clock()
        if remaining <= 0:
            return
        sleep(min(.1, remaining))


class ProviderWaitBudget(Exception):
    def __init__(self, seconds: float):
        self.seconds = max(0.0, seconds)


class ProviderRuntime:
    def __init__(self, *, clock=None, sleep=None, cache_ttl=300.0,
                 cache_bytes=16 * 1024 * 1024, cache_entries=128):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.cache_ttl = cache_ttl
        self.cache_bytes = cache_bytes
        self.cache_entries = cache_entries
        self.lock = threading.RLock()
        self.buckets: dict[tuple[str, str], dict] = {}
        self.cache = OrderedDict()
        self.cache_size = 0
        self.flights: dict[str, threading.Event] = {}

    @staticmethod
    def scope(source: str, headers=None) -> tuple[str, str]:
        credentials = next((str(v) for k, v in (headers or {}).items()
                            if source == "openalex" and k.lower() == "authorization"), "")
        return source, sha256(credentials.encode()).hexdigest() if credentials else "public"

    def interval(self, scope) -> float:
        return PROVIDERS[scope[0]]["interval"]

    def acquire(self, scope, deadline: float) -> None:
        from src.tasks import check_cancelled, report_progress
        announced = False
        while True:
            check_cancelled()
            with self.lock:
                now = self.clock()
                bucket = self.buckets.setdefault(scope, {"next": 0., "cooldown": 0., "failures": 0})
                wait = max(bucket["next"], bucket["cooldown"]) - now
                if wait <= 0:
                    bucket["next"] = now + self.interval(scope)
                    return
                if now + wait > deadline:
                    raise ProviderWaitBudget(wait)
            if not announced:
                report_progress("provider_wait")
                announced = True
            wait_cancelable(min(wait, .2), sleep=self.sleep, clock=self.clock)

    def observe(self, scope, result) -> None:
        with self.lock:
            now = self.clock()
            bucket = self.buckets.setdefault(scope, {"next": 0., "cooldown": 0., "failures": 0})
            status = result.status
            connection, message = connection_diagnostic(scope[0], result, authenticated=scope[1] != "public")
            bucket.update(status=connection, http_status=status, message=message,
                          checked_at=datetime.now(timezone.utc).isoformat())
            if status in {429, 503}:
                bucket["failures"] += 1
                headers = getattr(result, "headers", {}) or {}
                hint = retry_after_seconds(next((v for k, v in headers.items() if k.lower() == "retry-after"), None))
                delay = hint if hint is not None else min(30., 3. * (2 ** min(bucket["failures"] - 1, 4)))
                # Stable small jitter avoids a synchronized retry wave without
                # extending an explicit server Retry-After value.
                if hint is None:
                    delay += int(scope[1][:2], 16) / 255. * .3 if scope[1] != "public" else .15
                bucket["cooldown"] = max(bucket["cooldown"], now + delay)
            elif status == 200:
                bucket.update(failures=0, cooldown=0.)

    def request(self, url, headers, perform, *, max_wait=12.0, bypass_cache=False):
        source = provider_for_url(url)
        if source is None:
            return perform()
        from src.tasks import check_cancelled
        scope = self.scope(source, headers)
        # All headers matter for reuse, including identity and representation.
        fingerprint = sha256((url + "\n" + repr(sorted((str(k).lower(), str(v))
            for k, v in (headers or {}).items()))).encode()).hexdigest()
        deadline = self.clock() + max_wait
        while True:
            check_cancelled()
            with self.lock:
                cached = self.cache.get(fingerprint)
                if cached and cached[0] > self.clock() and not bypass_cache:
                    self.cache.move_to_end(fingerprint)
                    value = cached[1]
                    return replace(value, notes=[*value.notes, "provider_cache_hit"], headers=dict(value.headers))
                flight = self.flights.get(fingerprint)
                if flight is None:
                    flight = self.flights[fingerprint] = threading.Event()
                    break
            if self.clock() >= deadline:
                return self._deferred(url, .2, "provider_duplicate_wait_budget")
            wait_cancelable(.1, sleep=self.sleep, clock=self.clock)
        try:
            try:
                self.acquire(scope, deadline)
            except ProviderWaitBudget as exc:
                return self._deferred(url, exc.seconds, "provider_wait_budget")
            check_cancelled()
            result = perform()
            check_cancelled()
            self.observe(scope, result)
            content_type = result.headers.get("content-type", "").lower()
            cacheable_type = not content_type or "json" in content_type or "xml" in content_type
            if (result.status == 200 and result.body and cacheable_type
                    and len(result.body) <= min(self.cache_bytes, 2 * 1024 * 1024)):
                with self.lock:
                    previous = self.cache.pop(fingerprint, None)
                    if previous:
                        self.cache_size -= len(previous[1].body)
                    # Copy mutable fields: consumers append retry provenance.
                    saved = replace(result, notes=list(result.notes), headers=dict(result.headers))
                    self.cache[fingerprint] = (self.clock() + self.cache_ttl, saved)
                    self.cache_size += len(saved.body)
                    while self.cache and (self.cache_size > self.cache_bytes or len(self.cache) > self.cache_entries):
                        _, expired = self.cache.popitem(last=False)
                        self.cache_size -= len(expired[1].body)
            return result
        finally:
            with self.lock:
                self.flights.pop(fingerprint, None)
                flight.set()

    @staticmethod
    def _deferred(url, seconds, note):
        from src.http_fetch import FetchResult
        return FetchResult(url, 429, notes=[note], headers={"Retry-After": str(round(seconds, 2))})

    def snapshot(self, source: str, *, headers=None) -> dict:
        scope = self.scope(source, headers)
        with self.lock:
            bucket = self.buckets.get(scope, {})
            return {"connection": {"status": bucket.get("status", "untested"),
                                   "message": bucket.get("message", ""),
                                   "http_status": bucket.get("http_status"), "checked_at": bucket.get("checked_at")},
                    "rate_limit": {"minimum_interval_seconds": self.interval(scope),
                                   "cooldown_seconds": round(max(0., bucket.get("cooldown", 0) - self.clock()), 2)}}


runtime = ProviderRuntime()


def connection_diagnostic(source: str, result, *, authenticated: bool) -> tuple[str, str]:
    status = result.status
    if status == 200 and not result.error:
        return "connected", ""
    if status == 429:
        hint = "。配置 API Key 可使用独立配额" if not authenticated and source != "arxiv" else ""
        return "rate_limited", f"HTTP 429，请求已限流{hint}。"
    if status in {401, 403}:
        message = "请检查 API Key 是否有效或已激活" if authenticated else "请检查来源访问权限或配置 API Key"
        return "authentication_failed", f"HTTP {status}，{message}。"
    if source == "openalex" and status == 503 and not authenticated and b"anonymous search is paused" in result.body.lower():
        return "failed", "HTTP 503，OpenAlex 暂停了匿名搜索。可配置免费 API Key 或稍后重试。"
    if status is not None:
        return "failed", f"HTTP {status}，来源暂时未返回可用内容。"
    error = (result.error or "").lower()
    if "certificate_verify_failed" in error or "certificate verify failed" in error:
        return "failed", "HTTPS 证书验证失败，请检查系统证书和网络代理配置。"
    if "ssl" in error or "tls" in error or "ssl_error" in result.notes:
        return "failed", "HTTPS 连接在握手阶段中断，请检查网络或代理后重试。"
    if "timeout" in error or "timed out" in error:
        return "failed", "连接超时，请检查网络或稍后重试。"
    return "failed", "无法连接来源，请检查网络或代理。"


def provider_auth_headers(source: str, key: str | None) -> dict[str, str] | None:
    if key and source == "openalex":
        return {"Authorization": f"Bearer {key}"}
    return None


def source_headers(settings, source: str):
    return provider_auth_headers(source, getattr(settings, f"{source}_api_key", None))


def source_status(settings, source: str) -> dict:
    if source not in PROVIDERS:
        raise ValueError("请选择 arxiv 或 openalex")
    headers = source_headers(settings, source)
    configured = bool(headers)
    metadata = PROVIDERS[source]
    return {"id": source, "label": metadata["label"], "key_configured": configured,
            "authentication": "api_key" if configured else "public",
            **runtime.snapshot(source, headers=headers),
            "configuration": {"environment_variable": metadata["environment_variable"],
                              "apply_url": metadata["apply_url"]}}


def sources_status(settings) -> dict:
    return {"sources": [source_status(settings, source) for source in PROVIDERS]}


def test_source_connection(settings, source: str) -> dict:
    source_status(settings, source)  # Validate before any network work.
    from src.http_fetch import http_get
    urls = {
        "openalex": "https://api.openalex.org/works?" + urlencode(
            {"search": "information retrieval", "per_page": 1, "select": "id"}),
        "arxiv": "https://export.arxiv.org/api/query?id_list=2106.09685&max_results=1",
    }
    # An explicit connection test bypasses cached responses and stays within
    # one real request. It participates in the same rate/cooldown bucket.
    result = http_get(urls[source], headers=source_headers(settings, source), timeout=6,
             mailto=getattr(settings, "openalex_mailto", None), bypass_provider_cache=True,
             provider_wait_budget=4.)
    status = source_status(settings, source)
    if any(note.startswith("provider_") and note.endswith("wait_budget") for note in result.notes):
        status["connection"] = {"status": "rate_limited", "http_status": None,
                                "checked_at": None, "message": "文献来源仍在冷却，连接测试尚未发出。"}
        delay = retry_after_seconds(result.headers.get("Retry-After")) or 0.
        status["rate_limit"]["cooldown_seconds"] = max(delay, status["rate_limit"]["cooldown_seconds"])
    return {"source": status}
