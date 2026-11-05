from __future__ import annotations

import json
import os
import ssl
import sys
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
PROVIDER_TIMEOUT = "provider_request_timeout"


@dataclass
class FetchResult:
    url: str
    status: int | None
    body: bytes = b""
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 25,
    mailto: str | None = None,
    bypass_provider_cache: bool = False,
    provider_wait_budget: float = 12.0,
    deadline: float | None = None,
) -> FetchResult:
    from src.provider_runtime import runtime
    if deadline is not None:
        from src.tasks import check_cancelled
        check_cancelled()
        remaining = deadline - monotonic()
        if remaining <= 0:
            return _timed_out(url)
        provider_wait_budget = min(provider_wait_budget, remaining)
    return runtime.request(url, headers, lambda: _network_get(url, headers=headers,
        timeout=timeout, mailto=mailto, provider_wait_budget=provider_wait_budget, deadline=deadline),
        max_wait=provider_wait_budget, bypass_cache=bypass_provider_cache)


def _safe_response_headers(response) -> dict[str, str]:
    values = getattr(response, "headers", None) or {}
    allowed = {"retry-after", "content-type", "etag", "last-modified", "date"}
    return {str(k).lower(): str(v)[:300] for k, v in values.items() if str(k).lower() in allowed}


def _request(url, headers, mailto) -> Request:
    user_agent = f"LitAudit/0.2 (research; mailto:{mailto or 'litaudit-local@example.com'})"
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    for key, value in (headers or {}).items():
        if key.lower() in {"authorization", "x-api-key"}:
            request.add_unredirected_header(key, value)
        else:
            request.add_header(key, value)
    return request


def _read_result(url, response, status, *, has_body=True, check=None) -> FetchResult:
    if check:
        check()
    body = response.read(_MAX_RESPONSE_BYTES + 1) if has_body else b""
    if check:
        check()
    headers = _safe_response_headers(response)
    if len(body) > _MAX_RESPONSE_BYTES:
        return FetchResult(url, int(status), error="response_too_large", headers=headers)
    return FetchResult(url, int(status), body, headers=headers)


def _timed_out(url) -> FetchResult:
    return FetchResult(url, None, error=PROVIDER_TIMEOUT, notes=["network_error"])


def _bounded_get(url, headers, mailto, timeout, deadline, *, verify_tls) -> FetchResult:
    from src.grounded_transport import run_transport_worker

    arguments = json.dumps({"url": url, "headers": headers, "mailto": mailto,
                            "timeout": timeout, "verify_tls": verify_tls}).encode()
    try:
        code, result = run_transport_worker(str(Path(__file__).resolve()), arguments, deadline=deadline)
    except TimeoutError:
        return _timed_out(url)
    if code == 2:
        return _timed_out(url)
    if code == 3:
        raise ssl.SSLError("provider TLS handshake failed")
    if code:
        return FetchResult(url, None, error="provider_connection_failed", notes=["network_error"])
    metadata, _, body = result.partition(b"\n")
    return FetchResult(url, body=body, **json.loads(metadata))


def _network_get(url, *, headers, timeout, mailto, provider_wait_budget, deadline=None) -> FetchResult:
    from src.tasks import check_cancelled, TaskCancelled
    check_cancelled()
    request = _request(url, headers, mailto)
    opened = False

    def _open(*, verify_tls: bool) -> FetchResult:
        nonlocal opened
        check_cancelled()
        if opened:
            # The optional certificate fallback is another actual request.
            from src.provider_runtime import runtime, provider_for_url
            source = provider_for_url(url)
            if source:
                wait_budget = provider_wait_budget if deadline is None else min(provider_wait_budget, deadline - monotonic())
                runtime.acquire(runtime.scope(source, headers), runtime.clock() + wait_budget)
        opened = True
        if deadline is not None:
            return _bounded_get(url, headers, mailto, timeout, deadline, verify_tls=verify_tls)
        context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            return _read_result(url, response, response.status, check=check_cancelled)

    try:
        return _open(verify_tls=True)
    except HTTPError as exc:
        return _read_result(url, exc, exc.code, has_body=exc.fp is not None, check=check_cancelled)
    except ssl.SSLError as exc:
        check_cancelled()
        if os.getenv("LITAUDIT_ALLOW_INSECURE_TLS", "0") != "1":
            return FetchResult(url=url, status=None, error=f"ssl:{exc}", notes=["ssl_error"])
        try:
            result = _open(verify_tls=False)
            result.notes.append("ssl_insecure")
            return result
        except TaskCancelled:
            raise
        except Exception as retry_exc:
            check_cancelled()
            return FetchResult(url=url, status=None, error=f"ssl:{exc}; retry:{retry_exc}", notes=["ssl_error"])
    except (URLError, TimeoutError, OSError) as exc:
        check_cancelled()
        return FetchResult(url=url, status=None, error=str(exc), notes=["network_error"])


def _worker() -> int:
    try:
        options = json.load(sys.stdin.buffer)
        url = options["url"]
        request = _request(url, options["headers"], options["mailto"])
        context = ssl.create_default_context() if options["verify_tls"] else ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=options["timeout"], context=context) as response:
                result = _read_result(url, response, response.status)
        except HTTPError as exc:
            result = _read_result(url, exc, exc.code, has_body=exc.fp is not None)
        metadata = json.dumps({"status": result.status, "error": result.error, "headers": result.headers}).encode()
        sys.stdout.buffer.write(metadata + b"\n" + result.body)
        return 0
    except TimeoutError:
        return 2
    except ssl.SSLError:
        return 3
    except URLError as exc:
        return 2 if isinstance(exc.reason, TimeoutError) else 3 if isinstance(exc.reason, ssl.SSLError) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(_worker())
