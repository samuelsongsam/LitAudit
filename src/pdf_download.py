"""Download an open PDF with a wall-clock limit independent of socket timeouts."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_DOWNLOAD_SECONDS = 45.0
_MAX_PDF_BYTES = 25 * 1024 * 1024


class PdfDownloadError(ValueError):
    pass


def _transfer(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": "LitAudit/0.2", "Accept": "application/pdf"})
    with urlopen(request, timeout=10) as response:
        content = response.read(_MAX_PDF_BYTES + 1)
    if len(content) > _MAX_PDF_BYTES:
        raise PdfDownloadError("pdf_too_large")
    if not content.startswith(b"%PDF-"):
        raise PdfDownloadError("response_not_pdf")
    target.write_bytes(content)


def _worker() -> int:
    # Read the URL through stdin to keep signed provider links out of command lines.
    try:
        _transfer(sys.stdin.buffer.read().decode("utf-8"), Path(sys.argv[1]))
    except HTTPError as exc:
        print(f"http_{exc.code}")
    except TimeoutError:
        print("pdf_timeout")
    except URLError as exc:
        print("pdf_timeout" if isinstance(exc.reason, TimeoutError) else "pdf_connection_failed")
    except PdfDownloadError as exc:
        print(str(exc))
    except Exception:
        print("pdf_connection_failed")
    else:
        return 0
    return 1


def fetch_pdf(url: str, target: Path) -> None:
    """Abort a stalled download and publish only a complete response."""
    from src.tasks import check_cancelled

    check_cancelled()
    deadline = monotonic() + _DOWNLOAD_SECONDS
    with TemporaryDirectory(prefix=".pdf-download-", dir=target.parent) as directory:
        staging = Path(directory) / "document.pdf"
        with TemporaryFile(dir=directory) as request:
            request.write(url.encode("utf-8"))
            request.seek(0)
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), str(staging)],
                stdin=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                while True:
                    check_cancelled()
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise PdfDownloadError("pdf_timeout")
                    try:
                        output, _ = process.communicate(timeout=min(0.2, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                check_cancelled()
                if monotonic() >= deadline:
                    raise PdfDownloadError("pdf_timeout")
                if process.returncode:
                    raise PdfDownloadError(output.decode("ascii", errors="ignore").strip() or "pdf_connection_failed")
                os.replace(staging, target)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == "__main__":
    sys.exit(_worker())
