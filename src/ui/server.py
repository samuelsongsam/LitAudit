from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.config import load_settings
from src.pipeline import run_pipeline
from src.ui.payload import ask_payload, build_payload, list_runs_for_ui

STATIC_DIR = Path(__file__).resolve().parent / "static"


class LitAuditHandler(BaseHTTPRequestHandler):
    settings = None
    default_run_id: str | None = None

    def log_message(self, format: str, *args) -> None:
        if self.path.startswith("/api/") or self.path in {"/", "/index.html"}:
            super().log_message(format, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path == "/api/health":
            self._json({"ok": True, "live_search": True, "pid": os.getpid()})
            return
        if path == "/api/runs":
            runs = list_runs_for_ui(self.settings.runs_dir)
            self._json({"runs": runs, "default_run_id": self.default_run_id})
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
        if path == "/api/live":
            question = (query.get("q") or query.get("question") or [""])[0]
            self._live({"question": question})
            return
        self._static(unquote(parsed.path) or "/")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)
            return
        if path in {"/api/live", "/api/search"}:
            self._live(body)
            return
        if path != "/api/run":
            self._json({"error": f"not found ({self.command} {path})"}, status=404)
            return
        source = "fixture" if body.get("source") == "fixture" else "data"
        offline = bool(body.get("offline", True))
        from src.config import load_settings

        settings = load_settings(offline=offline)
        run_id = body.get("run_id") if offline else None
        try:
            result = run_pipeline(
                settings,
                source=source,
                run_id=run_id,
                question=body.get("question"),
                live=not offline,
            )
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        self._json(result)

    def _live(self, body: dict) -> None:
        question = str(body.get("question") or "").strip()
        if not question:
            self._json({"error": "缺少 question"}, status=400)
            return
        from src.config import load_settings

        settings = load_settings(offline=False)
        try:
            result = run_pipeline(settings, source="data", question=question, live=True)
            result["ask"] = ask_payload(settings.runs_dir, result["run_id"], question)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
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


class LitAuditServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(*, port: int = 8787, run_id: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    settings = load_settings()
    runs = [item["id"] for item in list_runs_for_ui(settings.runs_dir)]
    if run_id is None and runs:
        run_id = "phase2-real" if "phase2-real" in runs else runs[0]
    LitAuditHandler.settings = settings
    LitAuditHandler.default_run_id = run_id
    try:
        server = LitAuditServer(("127.0.0.1", port), LitAuditHandler)
    except OSError as exc:
        raise SystemExit(
            f"端口 {port} 已被占用（{exc}）。请先结束所有 python -m src.cli ui 进程，再只启动一次。"
        ) from exc
    bound = server.server_address[1]
    url = f"http://127.0.0.1:{bound}/"
    if run_id:
        url += f"?run={run_id}"
    return server, url


def serve_ui(*, run_id: str | None = None, port: int = 8787, open_browser: bool = True) -> int:
    server, url = make_server(port=port, run_id=run_id)
    print(f"LitAudit UI  {url}  pid={os.getpid()}", flush=True)
    print("勘验工作台：界面「检索文献」会调用 arXiv / OpenAlex / Semantic Scholar。按 Ctrl+C 结束。", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭界面")
    finally:
        server.server_close()
    return 0
