from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.config import load_settings
from src.pipeline import run_pipeline
from src.ui.payload import ask_payload, build_payload, list_available_runs

STATIC_DIR = Path(__file__).resolve().parent / "static"


class LitAuditHandler(BaseHTTPRequestHandler):
    settings = None
    default_run_id: str | None = None

    def log_message(self, format: str, *args) -> None:
        if self.path.startswith("/api/") or self.path in {"/", "/index.html"}:
            super().log_message(format, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        if path == "/api/health":
            self._json({"ok": True})
            return
        if path == "/api/runs":
            self._json({"runs": list_available_runs(self.settings.runs_dir), "default_run_id": self.default_run_id})
            return
        if path.startswith("/api/run/"):
            run_id = path.split("/api/run/", 1)[1].strip("/")
            try:
                self._json(build_payload(self.settings.runs_dir, run_id))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            return
        if path == "/api/ask":
            run_id = (query.get("run_id") or [self.default_run_id])[0]
            question = (query.get("q") or [""])[0]
            if not run_id:
                self._json({"error": "缺少 run_id"}, status=400)
                return
            self._json(ask_payload(self.settings.runs_dir, run_id, question))
            return
        self._static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self._json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)
            return
        source = "fixture" if body.get("source") == "fixture" else "data"
        run_id = body.get("run_id")
        result = run_pipeline(self.settings, source=source, run_id=run_id)
        self._json(result)

    def _static(self, path: str) -> None:
        if path in {"/", "/index.html"}:
            target = STATIC_DIR / "index.html"
        elif path.startswith("/static/"):
            target = (STATIC_DIR / path[len("/static/") :]).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())):
                self._json({"error": "forbidden"}, status=403)
                return
        elif path == "/favicon.svg":
            target = STATIC_DIR / "favicon.svg"
        else:
            self._json({"error": "not found"}, status=404)
            return
        if not target.exists() or not target.is_file():
            self._json({"error": "not found"}, status=404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def make_server(*, port: int = 8787, run_id: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    settings = load_settings()
    runs = list_available_runs(settings.runs_dir)
    if run_id is None and runs:
        run_id = "phase2-real" if "phase2-real" in runs else runs[0]
    LitAuditHandler.settings = settings
    LitAuditHandler.default_run_id = run_id
    server = ThreadingHTTPServer(("127.0.0.1", port), LitAuditHandler)
    bound = server.server_address[1]
    url = f"http://127.0.0.1:{bound}/"
    if run_id:
        url += f"?run={run_id}"
    return server, url


def serve_ui(*, run_id: str | None = None, port: int = 8787, open_browser: bool = True) -> int:
    server, url = make_server(port=port, run_id=run_id)
    print(f"LitAudit UI  {url}", flush=True)
    print("离线勘验工作台。按 Ctrl+C 结束。", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭界面")
    finally:
        server.server_close()
    return 0
