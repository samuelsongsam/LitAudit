from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class FetchResult:
    url: str
    status: int | None
    body: bytes = b""
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 25,
    mailto: str | None = None,
) -> FetchResult:
    user_agent = f"LitAudit/0.2 (research; mailto:{mailto or 'litaudit-local@example.com'})"
    request_headers = {"User-Agent": user_agent, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)

    def _open(context: ssl.SSLContext | None) -> FetchResult:
        with urlopen(request, timeout=timeout, context=context) as response:
            return FetchResult(url=url, status=int(response.status), body=response.read())

    try:
        return _open(ssl.create_default_context())
    except HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return FetchResult(url=url, status=int(exc.code), body=body)
    except ssl.SSLError as exc:
        try:
            result = _open(ssl._create_unverified_context())
            result.notes.append("ssl_insecure")
            return result
        except Exception as retry_exc:
            return FetchResult(url=url, status=None, error=f"ssl:{exc}; retry:{retry_exc}", notes=["ssl_error"])
    except (URLError, TimeoutError, OSError) as exc:
        return FetchResult(url=url, status=None, error=str(exc), notes=["network_error"])
