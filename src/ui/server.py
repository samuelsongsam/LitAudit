from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.config import load_settings
from src.conversation import build_chat_response, classify_intent, delete_conversation, list_conversations, load_conversation, rename_conversation, save_message
from src.pipeline import run_pipeline
from src.ui.payload import ask_payload, build_audit_report, build_payload, list_runs_for_ui

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
        if path.startswith("/api/fulltext/"):
            self._fulltext(path)
            return
        if path.startswith("/api/run/"):
            run_id = path.split("/api/run/", 1)[1].strip("/")
            if run_id.endswith("/report"):
                run_id = run_id[: -len("/report")].rstrip("/")
                try:
                    content, filename = build_audit_report(self.settings.runs_dir, run_id)
                    self._json({"run_id": run_id, "filename": filename, "content": content})
                except FileNotFoundError as exc:
                    self._json({"error": str(exc)}, status=404)
                except ValueError as exc:
                    self._json({"error": str(exc)}, status=400)
                return
            try:
                self._json(build_payload(self.settings.runs_dir, run_id))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path == "/api/ask":
            run_id = (query.get("run_id") or [self.default_run_id])[0]
            question = (query.get("q") or [""])[0]
            if not run_id:
                self._json({"error": "缺少 run_id"}, status=400)
                return
            self._json(ask_payload(self.settings.runs_dir, run_id, question))
            return
        if path.startswith("/api/chat/"):
            run_id = path.split("/api/chat/", 1)[1].strip("/")
            if not run_id:
                self._json({"error": "缺少 run_id"}, status=400)
                return
            try:
                self._json(load_conversation(self.settings.runs_dir, run_id))
            except Exception as exc:
                self._json({"error": str(exc)}, status=500)
            return
        if path == "/api/conversations":
            self._json({"conversations": list_conversations(self.settings.runs_dir)})
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
        if path == "/api/chat":
            self._chat(body)
            return
        if path == "/api/audit/upgrade":
            from src.pipeline import upgrade_audit
            try:
                result = upgrade_audit(self.settings, str(body.get("run_id") or ""), acquire=body.get("acquire") is True)
                self._json(result)
            except (ValueError, FileNotFoundError) as exc:
                self._json({"error": str(exc)}, status=400)
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

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")
        if not path.startswith("/api/chat/"):
            self._json({"error": f"not found ({self.command} {path})"}, status=404)
            return
        run_id = path.split("/api/chat/", 1)[1].strip("/")
        if not run_id:
            self._json({"error": "缺少 run_id"}, status=400)
            return
        try:
            deleted = delete_conversation(self.settings.runs_dir, run_id)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
            return
        self._json({"run_id": run_id, "deleted": deleted})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")
        if not path.startswith("/api/chat/"):
            self._json({"error": f"not found ({self.command} {path})"}, status=404)
            return
        run_id = path.split("/api/chat/", 1)[1].strip("/")
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8"))
            result = rename_conversation(self.settings.runs_dir, run_id, str(body.get("title") or ""))
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)
            return
        except (FileNotFoundError, ValueError) as exc:
            self._json({"error": str(exc)}, status=400)
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

    def _chat(self, body: dict) -> None:
        message = str(body.get("message") or body.get("question") or "").strip()
        if not message:
            self._json({"error": "缺少 message"}, status=400)
            return
        requested_run = str(body.get("run_id") or "").strip() or None
        settings = load_settings(offline=False)
        try:
            current_payload = build_payload(settings.runs_dir, requested_run) if requested_run else None
            intent = classify_intent(message, current_payload, settings, body.get("clarification_context") or [], body.get("clarification_topic"))
            if intent.route_error:
                response = build_chat_response(current_payload or {"run_id": None, "papers": []}, message, intent, settings)
                self._json({"conversation_id": None, "run_id": None, "status": "llm_unavailable", "response": response})
                return
            if intent.direct_answer or intent.needs_clarification:
                response = build_chat_response(current_payload or {"run_id": None, "papers": []}, message, intent, settings)
                if response.get("overview_mode") == "llm_error":
                    self._json({"conversation_id": requested_run, "run_id": requested_run, "status": "llm_unavailable", "action": "reuse_run" if requested_run else "no_run", "response": response})
                    return
                if intent.direct_answer and requested_run:
                    save_message(settings.runs_dir, requested_run, "user", message)
                    save_message(settings.runs_dir, requested_run, "assistant", response["overview"], response)
                response_run = requested_run if intent.direct_answer else None
                self._json({"conversation_id": response_run, "run_id": response_run, "status": "completed" if intent.direct_answer else "needs_clarification", "action": "reuse_run" if response_run else "no_run", "response": response})
                return
            if current_payload is None or intent.needs_retrieval:
                result = run_pipeline(settings, source="data", question=intent.expanded_query or message, live=True)
                run_id = result["run_id"]
                current_payload = build_payload(settings.runs_dir, run_id)
                for previous in body.get("conversation_context") or []:
                    if isinstance(previous, dict) and previous.get("role") in {"user", "assistant"} and isinstance(previous.get("content"), str):
                        save_message(settings.runs_dir, run_id, previous["role"], previous["content"], previous.get("response"))
            else:
                run_id = requested_run
            response = build_chat_response(current_payload, message, intent, settings)
            if intent.needs_clarification:
                self._json({"conversation_id": None, "run_id": None, "status": "needs_clarification", "response": response})
                return
            save_message(settings.runs_dir, run_id, "user", message)
            save_message(settings.runs_dir, run_id, "assistant", response["overview"], response)
            if not run_id:
                raise RuntimeError("检索完成但未生成可回放的 run")
            self._json({"conversation_id": run_id, "run_id": run_id, "status": "completed", "action": "new_run" if intent.needs_retrieval else "reuse_run", "response": response})
        except FileNotFoundError as exc:
            self._json({"error": str(exc)}, status=404)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def _fulltext(self, path: str) -> None:
        from src.run_paths import resolve_run_dir
        from src.io_utils import read_json
        try:
            run_id, paper_id = path[len("/api/fulltext/"):].split("/", 1)
            run_dir = resolve_run_dir(self.settings.runs_dir, run_id).resolve()
            audit = read_json(run_dir / "output" / "fulltext_audit.json")
            document = next(d for d in audit["documents"] if d["paper_id"] == paper_id and d.get("response_path"))
            target = Path(document["response_path"]).resolve()
            target.relative_to(run_dir)
            data = target.read_bytes()
        except (ValueError, OSError, StopIteration, KeyError):
            self._json({"error": "全文尚不可用"}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path: str) -> None:
        if path in {"/", "/index.html"}:
            target = STATIC_DIR / "index.html"
        elif path.startswith("/static/"):
            target = (STATIC_DIR / path[len("/static/") :]).resolve()
            try:
                target.relative_to(STATIC_DIR.resolve())
            except ValueError:
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
