"""Cancellable model HTTP calls for source-grounded reading."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from time import monotonic
from urllib.error import URLError
from urllib.request import Request, urlopen


def _write_request(stream, request: bytes) -> None:
    try:
        with stream:
            stream.write(request)
    except OSError:
        # The child may be terminated while sending.
        pass


def run_transport_worker(script: str, request: bytes, *, deadline: float) -> tuple[int, bytes]:
    """Run a cancellable HTTP worker without putting credentials on disk or argv."""
    from src.tasks import check_cancelled

    check_cancelled()
    if monotonic() >= deadline:
        raise TimeoutError("transport_deadline")
    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, "wb") as write_pipe:
        with os.fdopen(read_fd, "rb") as read_pipe:
            process = subprocess.Popen([sys.executable, script], stdin=read_pipe,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Windows communicate(input=...) can block while writing a large prompt.
        sender = Thread(target=_write_request, args=(write_pipe, request), daemon=True)
        try:
            sender.start()
            while True:
                check_cancelled()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("transport_deadline")
                try:
                    result, _ = process.communicate(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            check_cancelled()
            if monotonic() >= deadline:
                raise TimeoutError("transport_deadline")
            return process.returncode, result
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()
            if sender.ident is not None:
                sender.join()


def post_model_json(url: str, key: str, body: dict, *, deadline: float) -> dict:
    """Bound total wall time, including DNS, headers and a slow response body."""
    request = json.dumps({"url": url, "key": key, "body": body}, ensure_ascii=False).encode()
    try:
        code, result = run_transport_worker(str(Path(__file__).resolve()), request, deadline=deadline)
    except TimeoutError as exc:
        raise TimeoutError("grounded_model_deadline") from exc
    if code == 2:
        raise TimeoutError("grounded_model_deadline")
    if code:
        raise ConnectionError("grounded_model_request_failed")
    return json.loads(result)


def _worker() -> int:
    try:
        options = json.load(sys.stdin.buffer)
        request = Request(options["url"], data=json.dumps(options["body"], ensure_ascii=False).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        request.add_unredirected_header("Authorization", "Bearer " + options["key"])
        with urlopen(request, timeout=45) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            return 1
        sys.stdout.buffer.write(data)
        return 0
    except TimeoutError:
        return 2
    except URLError as exc:
        return 2 if isinstance(exc.reason, TimeoutError) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(_worker())
