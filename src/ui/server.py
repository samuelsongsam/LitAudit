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
from src.conversation import build_chat_response, classify_intent, delete_conversation, list_conversations, load_conversation, rename_conversation, save_message, save_turn
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
        if path == "/api/sources":
            from src.provider_runtime import sources_status
            self._json(sources_status(self.settings))
            return
        if path == "/api/tasks" or path.startswith("/api/tasks/"):
            try:
                self._json({"tasks": self.server.tasks.list()} if path == "/api/tasks" else
                           self.server.tasks.get(path[len("/api/tasks/"):]))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            return
        if path == "/api/health":
            from src.cli import runtime_capabilities
            capabilities = runtime_capabilities(self.settings)
            from src.document_processing import processing_capabilities
            from hashlib import sha256
            self._json({"ok": True, "live_search": bool(self.settings.llm_api_key), "pid": os.getpid(),
                        "workspace_id": sha256(str(self.settings.runs_dir.resolve()).encode()).hexdigest()[:20],
                        "capabilities": {**capabilities, "llm_configured": bool(self.settings.llm_api_key),
                                         "documents": processing_capabilities(),
                                         "fulltext_search": True, "method_comparison": True}})
            return
        if path.startswith("/api/pdf-text/"):
            try:
                run_id, paper_id, page_number = path[len("/api/pdf-text/"):].split("/")
                from src.document_processing import document_page_text
                self._json(document_page_text(self._document_file(run_id, paper_id), int(page_number)))
            except (FileNotFoundError, OSError):
                self._json({"error": "原文件不可用"}, status=404)
            except ValueError:
                self._json({"error": "页码或论文位置无效"}, status=400)
            except ImportError:
                self._json({"error": "文本层组件尚未安装"}, status=501)
            return
        if path.startswith("/api/pdf-page/"):
            try:
                run_id, paper_id, page_number = path[len("/api/pdf-page/"):].split("/")
                from src.document_processing import render_document_page
                content = render_document_page(self._document_file(run_id, paper_id), int(page_number))
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            except (FileNotFoundError, OSError) as exc:
                self._json({"error": "当前论文原文件尚不可用"}, status=404)
            except ValueError as exc:
                self._json({"error": "页码或论文位置无效"}, status=400)
            except ImportError:
                self._json({"error": '安装 .[documents] 后可在工作区阅读原页；也可打开原PDF'}, status=501)
            return
        if path.startswith("/api/map-topics/"):
            try:
                from src.map_topics import map_topics
                run_id = path[len("/api/map-topics/"):]
                self._json(map_topics(build_payload(self.settings.runs_dir, run_id), self.settings.runs_dir))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path.startswith("/api/methods/"):
            from src.research_workspace import method_comparison, export_method_csv
            run_id = path[len("/api/methods/"):]
            exporting = run_id.endswith("/export")
            if exporting:
                run_id = run_id[:-len("/export")]
            try:
                paper_ids = query.get("paper_id") or None
                self._json({"filename": f"litaudit-{run_id}-methods.csv",
                            "content": export_method_csv(self.settings.runs_dir, run_id, paper_ids=paper_ids)} if exporting else
                           method_comparison(self.settings.runs_dir, run_id, paper_ids=paper_ids))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path.startswith("/api/library/"):
            from src.paper_library import library_payload, export_library
            run_id = path[len("/api/library/"):]
            exporting = run_id.endswith("/export")
            if exporting:
                run_id = run_id[:-len("/export")]
            try:
                self._json(export_library(self.settings.runs_dir, run_id, format=(query.get("format") or ["bibtex"])[0],
                                          paper_ids=query.get("paper_id") or None) if exporting else
                           library_payload(self.settings.runs_dir, run_id))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except (TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, status=400)
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
        body = self._read_body(max_bytes=36 * 1024 * 1024 if path == "/api/import/pdf" else 1024 * 1024)
        if body is None:
            return
        if path == "/api/sources/test":
            from src.provider_runtime import test_source_connection
            try:
                if set(body) != {"source"} or not isinstance(body.get("source"), str):
                    raise ValueError("请选择要测试的检索来源")
                self._json(test_source_connection(self.settings, body["source"]))
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        async_paths = {"/api/chat", "/api/search", "/api/live", "/api/fulltext/search", "/api/audit/upgrade", "/api/research/related", "/api/research/search-more", "/api/import/pdf", "/api/map-topics/refresh"}
        if path.startswith("/api/tasks/") and path.endswith("/retry"):
            try:
                task_id = path[len("/api/tasks/"):-len("/retry")]
                descriptor = self.server.tasks.get_retry_descriptor(task_id)
                operation = descriptor["path"]
                if operation not in async_paths or operation == "/api/import/pdf":
                    raise ValueError("此任务不能自动恢复输入，请重新选择材料")
                retry_body = descriptor["body"]
                from hashlib import sha256
                digest = sha256(json.dumps(retry_body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                task = self.server.tasks.submit(operation, lambda: self._execute_operation(operation, retry_body),
                    input_digest=digest, retry_descriptor=descriptor, retry_of=task_id)
                self._json({"task_id": task["task_id"], "status": task["status"]}, status=202)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if self.headers.get("Prefer") == "respond-async" and path in async_paths:
            try:
                request_id = body.get("request_id")
                if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 120):
                    raise ValueError("request_id 格式无效")
                from hashlib import sha256
                digest = sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                descriptor = self._retry_descriptor(path, body)
                task = self.server.tasks.submit(path, lambda: self._execute_operation(path, body), request_id=request_id,
                    input_digest=digest, retry_descriptor=descriptor)
                self._json({"task_id": task["task_id"], "status": task["status"]}, status=202)
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path == '/api/map-topics/label':
            try:
                from src.map_topics import save_topic_label
                run_id = body.get('run_id')
                self._json(save_topic_label(build_payload(self.settings.runs_dir, run_id), self.settings.runs_dir,
                                            cluster_id=body.get('cluster_id'), map_version=body.get('map_version'),
                                            label=body.get('label')))
            except FileNotFoundError as exc:
                self._json({'error': str(exc)}, status=404)
            except (ValueError, TypeError) as exc:
                self._json({'error': str(exc)}, status=400)
            return
        if path == "/api/map-topics/refresh":
            try:
                self._json(self._execute_operation(path, body))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path == "/api/query-plan":
            from src.retrieve import build_query_plan
            try:
                from src.research_query import validate_constraints
                constraints = validate_constraints(body.get("constraints"))
                question = body.get("question", "")
                if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                    raise ValueError("请填写2000字以内的研究问题")
                self._json({"constraints": constraints, "queries": [asdict(q) for q in build_query_plan(question, constraints=constraints)]})
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path in {"/api/import/pdf", "/api/research/related", "/api/research/search-more"}:
            try:
                self._json(self._execute_operation(path, body))
            except (ValueError, TypeError, FileNotFoundError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path in {"/api/library/save", "/api/research/guidance"}:
            try:
                if path == "/api/library/save":
                    from src.paper_library import save_library_item
                    result = save_library_item(self.settings.runs_dir, body.get("run_id"), body)
                else:
                    from src.research_assistant import research_guidance
                    result = research_guidance(self.settings.runs_dir, body.get("run_id"),
                                               paper_ids=body.get("paper_ids"), user_resources=body.get("user_resources"))
                    self._save_research_context(body.get("run_id"), resources=body.get("user_resources"))
                self._json(result)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path in {"/api/fulltext/search", "/api/workspace/review", "/api/workspace/fork"}:
            from src.research_workspace import search_fulltext, save_review, fork_workspace
            try:
                run_id = body.get("run_id")
                if not isinstance(run_id, str) or not run_id:
                    raise ValueError("请先选择研究记录")
                if path == "/api/fulltext/search":
                    query = body.get("query", "")
                    if not isinstance(query, str) or len(query) > 12000:
                        raise ValueError("检索问题必须是12000字以内的文本")
                    paper_ids = body.get("paper_ids")
                    if paper_ids is not None and (not isinstance(paper_ids, list) or any(not isinstance(p, str) for p in paper_ids)):
                        raise ValueError("paper_ids 必须为论文编号列表")
                    section = body.get("section")
                    if section is not None and not isinstance(section, str):
                        raise ValueError("section 必须为章节文本")
                    result = search_fulltext(self.settings.runs_dir, run_id, query, paper_ids=paper_ids, section=section)
                elif path == "/api/workspace/review":
                    result = save_review(self.settings.runs_dir, run_id, body)
                else:
                    result = fork_workspace(self.settings.runs_dir, run_id)
                self._json(result)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path in {"/api/live", "/api/search"}:
            self._live(body)
            return
        if path == "/api/chat":
            self._chat(body)
            return
        if path == "/api/map/retry":
            from src.pipeline import retry_map
            try:
                run_id = body.get("run_id")
                if run_id in {"phase2-real", "demo"}:
                    from src.research_workspace import fork_workspace
                    run_id = fork_workspace(self.settings.runs_dir, run_id)["run_id"]
                result = retry_map(self.settings, run_id)
                self._json(result)
            except (ValueError, FileNotFoundError, TypeError, RuntimeError) as exc:
                self._json({"error": str(exc)}, status=400)
            return
        if path == "/api/audit/upgrade":
            from src.pipeline import upgrade_audit
            try:
                result = upgrade_audit(self.settings, str(body.get("run_id") or ""), acquire=body.get("acquire") is True, paper_ids=body.get("paper_ids"))
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
        if path.startswith("/api/tasks/"):
            try:
                self._json(self.server.tasks.cancel(path[len("/api/tasks/"):]))
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
            return
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
        body = self._read_body()
        if body is None:
            return
        try:
            result = rename_conversation(self.settings.runs_dir, run_id, str(body.get("title") or ""))
        except (FileNotFoundError, ValueError) as exc:
            self._json({"error": str(exc)}, status=400)
            return
        self._json(result)

    def _live(self, body: dict) -> None:
        question = body.get("question") or ""
        if not isinstance(question, str) or len(question) > 12000:
            self._json({"error": "question 必须是12000字以内的文本"}, status=400)
            return
        question = question.strip()
        if not question:
            self._json({"error": "缺少 question"}, status=400)
            return
        from src.config import load_settings

        settings = load_settings(offline=False)
        try:
            options = {"constraints": body["constraints"]} if body.get("constraints") else {}
            if body.get("search_supplement"):
                options["search_supplement"] = body["search_supplement"]
            result = run_pipeline(settings, source="data", question=question, live=True, **options)
            result["ask"] = ask_payload(settings.runs_dir, result["run_id"], question)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        self._json(result)

    def _chat(self, body: dict) -> None:
        message = body.get("message") or body.get("question") or ""
        if not isinstance(message, str) or len(message) > 12000:
            self._json({"error": "message 必须是12000字以内的文本"}, status=400)
            return
        message = message.strip()
        if not message:
            self._json({"error": "缺少 message"}, status=400)
            return
        requested_run = str(body.get("run_id") or "").strip() or None
        settings = load_settings(offline=False)
        try:
            from src.research_query import validate_constraints
            skip_clarification = body.get("skip_clarification", False)
            if not isinstance(skip_clarification, bool):
                raise ValueError("skip_clarification 必须是布尔值")
            clarification_topic = body.get("clarification_topic")
            clarification_choices = body.get("clarification_context") or []
            answered_clarification = (isinstance(clarification_topic, str) and bool(clarification_topic.strip())
                                      and isinstance(clarification_choices, list) and bool(clarification_choices)
                                      and all(isinstance(choice, str) and choice.strip() for choice in clarification_choices))
            explicit_search = skip_clarification or answered_clarification
            constraints = validate_constraints(body.get("constraints"))
            resources = body.get("user_resources") or {}
            if (not isinstance(resources, dict) or set(resources) - {"data", "compute", "time"}
                    or any(not isinstance(v, str) or len(v) > 2000 for v in resources.values())):
                raise ValueError("数据、算力和时间条件必须为2000字以内的文本")
            preset = body.get("analysis_preset")
            if preset is not None:
                paper_id = body.get("reading_paper_id")
                if preset != "methods_experiments":
                    raise ValueError("未知的全文分析类型")
                if not requested_run or not isinstance(paper_id, str) or not paper_id.strip():
                    raise ValueError("请选择当前研究中的一篇论文")
                self._json(self._paper_method_chat(settings.runs_dir, requested_run, paper_id, message))
                return
            from src.tasks import report_progress
            report_progress("understand")
            current_payload = build_payload(settings.runs_dir, requested_run) if requested_run and not explicit_search else None
            from src.reading_selection import resolve_reader_selection
            selection = resolve_reader_selection(settings.runs_dir, requested_run, body.get('reading_selection')) if current_payload is not None else None
            if not explicit_search and body.get('reading_selection') is not None and not requested_run:
                raise ValueError('请选择当前研究中的论文')
            if selection:
                current_payload['reading_selection'] = selection
            history = []
            if current_payload is not None:
                history = load_conversation(settings.runs_dir, requested_run).get("messages", [])
                current_payload["conversation_context"] = [
                    {"role": p["role"], "content": p["content"][:1500]} for p in history[-6:]
                    if isinstance(p, dict) and p.get("role") in {"user", "assistant"} and isinstance(p.get("content"), str)]
            from src.map_topics import is_map_question, map_chat_response, validate_map_context, resolve_cluster_reading_scope
            from src.reading_scope import is_research_agenda_question, resolve_reading_scope
            research_agenda = current_payload is not None and is_research_agenda_question(
                message, scoped_reading=body.get("reading_mode") is True or bool(selection))
            map_context = None if explicit_search else validate_map_context(body.get('map_context'))
            cluster_scope = (resolve_cluster_reading_scope(current_payload, message, settings.runs_dir,
                             history=history, context=map_context) if current_payload is not None else None)
            if cluster_scope:
                body = {**body, 'reading_mode': True, 'reading_paper_ids': cluster_scope['paper_ids'],
                        'reading_scope_mode': 'selected'}
            if current_payload is not None and not cluster_scope and not research_agenda and is_map_question(message, history, map_context, current_payload):
                report_progress('map_topics', run_id=requested_run)
                response = map_chat_response(current_payload, message, settings, history=history, context=map_context)
                if requested_run in {'phase2-real', 'demo'}:
                    from src.research_workspace import fork_workspace
                    requested_run = fork_workspace(settings.runs_dir, requested_run)['run_id']
                    response['run_id'] = requested_run
                    response['map_answer']['run_id'] = requested_run
                    from src.map_topics import save_topic_snapshot
                    save_topic_snapshot(response['map_answer'], settings.runs_dir)
                save_turn(settings.runs_dir, requested_run, message, response['overview'], response)
                self._json({'conversation_id': requested_run, 'run_id': requested_run, 'status': 'completed',
                            'action': 'reuse_run', 'response': response})
                return
            if skip_clarification:
                from src.conversation import Intent
                intent = Intent("requery" if requested_run else "new_topic", 1.0, "用户选择按原问题检索", True,
                                expanded_query=message, route_source="user_search")
            elif not explicit_search and (body.get("reading_mode") is True or selection or research_agenda):
                if current_payload is None or (not research_agenda and not current_payload.get("fulltext_audit", {}).get("documents")):
                    raise ValueError("请先导入或获取当前研究的全文")
                from src.conversation import Intent
                mode = body.get("reading_scope_mode", "auto")
                if mode not in {"auto", "all", "selected"}:
                    raise ValueError("正文范围模式无效")
                selected_papers = body.get("reading_paper_ids", body.get("reading_paper_id"))
                if selection and selected_papers is None:
                    selected_papers = selection['paper_id']
                scope = cluster_scope or resolve_reading_scope(current_payload, message,
                    selected=selected_papers,
                    all_papers=mode == "all", history=history)
                current_payload["reading_scope"] = scope
                if research_agenda:
                    current_payload["research_agenda"] = True
                if selection and selection['paper_id'] not in scope['paper_ids']:
                    raise ValueError('选中文本与本轮论文范围不同，请切换论文后提问')
                target = scope["paper_ids"][0] if len(scope["paper_ids"]) == 1 else None
                intent = Intent("paper_explore" if target else "follow_up", 1.0, "用户选择当前正文问答", False,
                                direct_answer=True, target_paper_id=target, route_source="user_reading_scope")
            else:
                intent = classify_intent(message, current_payload, settings, clarification_choices, clarification_topic)
            if intent.route_error:
                response = build_chat_response(current_payload or {"run_id": None, "papers": []}, message, intent, settings)
                if current_payload and current_payload.get("reading_scope"):
                    response["reading_scope"] = current_payload["reading_scope"]
                if current_payload and current_payload.get('reading_selection'):
                    response['reading_selection'] = current_payload['reading_selection']
                self._json({"conversation_id": None, "run_id": None, "status": "llm_unavailable", "response": response})
                return
            if intent.direct_answer or intent.needs_clarification:
                if intent.direct_answer and current_payload:
                    self._attach_fulltext(current_payload, message, intent)
                    current_payload["reading_mode"] = "grounded" if (
                        body.get("reading_mode") is True or selection or cluster_scope or research_agenda
                    ) else "materials"
                    current_payload["user_resources"] = resources
                report_progress("answer")
                response = build_chat_response(current_payload or {"run_id": None, "papers": []}, message, intent, settings)
                if current_payload and current_payload.get("reading_scope"):
                    response["reading_scope"] = current_payload["reading_scope"]
                if selection:
                    response['reading_selection'] = selection
                if response.get("overview_mode") == "llm_error":
                    status = "insufficient_evidence" if response.get("error") in {"no_fulltext", "no_materials"} else "llm_unavailable"
                    self._json({"conversation_id": requested_run, "run_id": requested_run, "status": status, "action": "reuse_run" if requested_run else "no_run", "response": response})
                    return
                if intent.direct_answer and requested_run:
                    if requested_run in {"phase2-real", "demo"}:
                        from src.research_workspace import fork_workspace
                        requested_run = fork_workspace(settings.runs_dir, requested_run)["run_id"]
                        response["run_id"] = requested_run
                    self._save_research_context(requested_run, constraints, resources)
                    save_turn(settings.runs_dir, requested_run, message, response["overview"], response)
                response_run = requested_run if intent.direct_answer else None
                self._json({"conversation_id": response_run, "run_id": response_run, "status": "completed" if intent.direct_answer else "needs_clarification", "action": "reuse_run" if response_run else "no_run", "response": response})
                return
            if current_payload is None or intent.needs_retrieval:
                options = {"constraints": constraints} if constraints else {}
                if body.get("search_supplement"):
                    options["search_supplement"] = body["search_supplement"]
                result = run_pipeline(settings, source="data", question=intent.expanded_query or message, live=True, **options)
                run_id = result["run_id"]
                current_payload = build_payload(settings.runs_dir, run_id)
                saved_history = load_conversation(settings.runs_dir, requested_run).get("messages", []) if requested_run else []
                for previous in saved_history or body.get("conversation_context") or []:
                    if isinstance(previous, dict) and previous.get("role") in {"user", "assistant"} and isinstance(previous.get("content"), str):
                        save_message(settings.runs_dir, run_id, previous["role"], previous["content"], previous.get("response"))
            else:
                run_id = requested_run
            self._attach_fulltext(current_payload, message, intent)
            report_progress("answer", run_id=run_id)
            response = build_chat_response(current_payload, message, intent, settings)
            if intent.needs_clarification:
                self._json({"conversation_id": None, "run_id": None, "status": "needs_clarification", "response": response})
                return
            if not run_id:
                raise RuntimeError("检索完成但未生成可回放的 run")
            if run_id in {"phase2-real", "demo"}:
                from src.research_workspace import fork_workspace
                run_id = fork_workspace(settings.runs_dir, run_id)["run_id"]
                response["run_id"] = run_id
            save_turn(settings.runs_dir, run_id, message, response["overview"], response)
            if requested_run and requested_run != run_id:
                from src.conversation import continue_conversation
                continue_conversation(settings.runs_dir, requested_run, run_id)
            self._save_research_context(run_id, constraints, resources)
            self._json({"conversation_id": run_id, "run_id": run_id, "status": "completed", "action": "new_run" if intent.needs_retrieval else "reuse_run", "response": response})
        except FileNotFoundError as exc:
            self._json({"error": str(exc)}, status=404)
        except (TypeError, ValueError) as exc:
            self._json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    @staticmethod
    def _retry_descriptor(path: str, body: dict):
        fields = {
            "/api/chat": {"message", "question", "run_id", "constraints", "user_resources", "reading_mode", "reading_paper_id", "reading_paper_ids", "reading_scope_mode", "clarification_context", "clarification_topic", "skip_clarification", "search_supplement", "map_context", "reading_selection", "analysis_preset"},
            "/api/map-topics/refresh": {"run_id", "force"},
            "/api/search": {"question", "constraints", "search_supplement"},
            "/api/live": {"question", "constraints", "search_supplement"},
            "/api/fulltext/search": {"run_id", "query", "paper_ids", "section"},
            "/api/audit/upgrade": {"run_id", "acquire", "paper_ids"},
            "/api/research/related": {"run_id", "paper_id", "direction", "constraints"},
            "/api/research/search-more": {"run_id", "failed_only", "search_supplement"},
        }
        if path not in fields:
            return None
        selected = {k: value for k, value in body.items() if k in fields[path]}
        if len(json.dumps(selected, ensure_ascii=False).encode()) > 28 * 1024:
            return None
        return {"path": path, "body": selected}

    def _save_research_context(self, run_id, constraints=None, resources=None):
        if not run_id or run_id in {"demo", "phase2-real"}:
            return
        from src.run_paths import resolve_run_dir
        from src.io_utils import read_json
        from src.conversation import _write_conversation
        from src.research_workspace import _lock
        path = resolve_run_dir(self.settings.runs_dir, run_id) / "output/research_context.json"
        with _lock(path.parent.parent):
            context = read_json(path) if path.exists() else {}
            if constraints is not None:
                context["constraints"] = constraints
            if resources is not None:
                context["user_resources"] = resources
            _write_conversation(path, context)

    @staticmethod
    def _paper_method_chat(runs_dir, run_id, paper_id, message):
        from src.research_workspace import _portable, fork_workspace, paper_method_evidence
        from src.run_paths import resolve_run_dir
        from src.tasks import report_progress

        report_progress("method_evidence", run_id=run_id)
        analysis = paper_method_evidence(runs_dir, run_id, paper_id)
        located = [(field["label"], field["candidate"]) for field in analysis["fields"] if field["candidate"]]
        if located:
            overview = "\n\n".join(f'**{label} · 第 {candidate["page"]} 页**\n\n{candidate["quote"]}'
                                  for label, candidate in located)
        else:
            overview = ("当前正文中没有定位到明确的方法或实验摘录。" if analysis["has_fulltext"]
                        else "请先获取可提取文字的全文或导入本地 PDF。")
        scope = {"paper_ids": [paper_id], "titles": [analysis["title"]], "source": "selection",
                 "ambiguous_name": False, "excluded_paper_ids": []}
        response = {"overview": overview, "overview_mode": "method_evidence", "run_id": run_id,
                    "method_analysis": analysis, "reading_scope": scope}
        if analysis["has_fulltext"]:
            report_progress("answer", run_id=run_id)
            if run_id in {"phase2-real", "demo"}:
                source = resolve_run_dir(runs_dir, run_id)
                run_id = fork_workspace(runs_dir, run_id)["run_id"]
                response = _portable(response, source, run_id)
                response["run_id"] = run_id
            save_turn(runs_dir, run_id, message, overview, response)
        return {"conversation_id": run_id, "run_id": run_id, "action": "reuse_run", "response": response,
                "status": "completed" if analysis["has_fulltext"] else "insufficient_evidence"}

    def _citation_discovery(self, body: dict) -> dict:
        from src.io_utils import read_json
        from src.live_ingest import paper_keys
        from src.pipeline import new_run_id
        from src.research_workspace import workspace_papers
        from src.retrieve import fetch_related_hits, hit_keys, related_paper_identifier
        from src.run_paths import resolve_run_dir
        from src.tasks import report_progress

        run_id, paper_id = body.get("run_id"), body.get("paper_id")
        if not isinstance(paper_id, str):
            raise ValueError("请选择当前研究中的论文")
        direction = body.get("direction", "references")
        runs_dir = self.settings.runs_dir
        report_progress("citation_discovery", run_id=run_id)
        papers = workspace_papers(runs_dir, run_id)
        if paper_id not in papers:
            raise ValueError("请选择当前研究中的论文")
        paper = papers[paper_id]
        identifier = related_paper_identifier(paper)
        if not identifier:
            raise ValueError("该论文尚无可用于 OpenAlex 引文检索的标识")
        cache = resolve_run_dir(runs_dir, new_run_id("discovery")) / "cache"
        bundle = fetch_related_hits(identifier, direction, cache_dir=cache, api_key=self.settings.openalex_api_key,
                                    mailto=self.settings.openalex_mailto, constraints=body.get("constraints"))
        coverage = bundle.coverage.get("openalex") or {}
        source_status = coverage.get("status", "failed")
        if source_status != "success" and bundle.runs:
            last = bundle.runs[-1]
            if last.http_status == 404:
                source_status = "not_found"
            elif last.http_status == 429 or last.status == "rate_limited":
                source_status = "rate_limited"
            elif "timeout" in (last.notes or "").lower():
                source_status = "timeout"

        def preview(status, message, rows=(), added=()):
            return {"status": status, "source_status": source_status, "direction": direction, "message": message,
                    "paper_ids": [row.paper_id for row in rows], "added_paper_ids": list(added), "added_count": len(added),
                    "papers": [{"paper_id": row.paper_id, "title": row.title, "year": row.year, "url": row.url,
                                "reason": row.reason} for row in rows]}

        if source_status != "success":
            message = {"rate_limited": "OpenAlex 暂时限流，请稍后重试。", "not_found": "OpenAlex 未收录这篇论文。",
                       "timeout": "OpenAlex 响应超时，可以重试。"}.get(source_status, "OpenAlex 暂未返回引文结果，可以重试。")
            return {"run_id": run_id, "related": preview("unavailable", message)}
        if not bundle.hits:
            filtered = bundle.filter_report.get("before_filter") or coverage.get("raw_result_count")
            message = "OpenAlex 返回的引文未匹配当前筛选条件。" if filtered else "OpenAlex 本次未返回这一方向的引文。"
            return {"run_id": run_id, "related": preview("empty", message)}

        source_dir = resolve_run_dir(runs_dir, run_id)
        graph_path = source_dir / "output" / "citation_graph.json"
        previous = read_json(graph_path) if graph_path.is_file() else {}
        graph = bundle.citation_graph
        edges = {(edge["source"], edge["target"]): edge for edge in previous.get("edges", [])}
        new_edges = {(edge["source"], edge["target"]): edge for edge in graph.get("edges", [])}
        known_keys = {pid: paper_keys(row) for pid, row in papers.items()}
        matches = [[pid for pid, keys in known_keys.items() if keys & related_keys]
                   for related_keys in map(hit_keys, bundle.hits)]
        if all(matches) and new_edges.keys() <= edges.keys():
            present = [papers[pid] for pid in dict.fromkeys(pid for group in matches for pid in group)]
            return {"run_id": run_id, "related": preview("already_present", "本次查到的论文已在当前研究中。", present)}
        if edges:
            nodes = {node["paper_id"]: node for node in previous.get("nodes", [])}
            for node in graph.get("nodes", []):
                pid = node["paper_id"]
                nodes[pid] = {**nodes.get(pid, {}), **node}
            edges.update(new_edges)
            graph.update(nodes=list(nodes.values()), edges=list(edges.values()), edge_count=len(edges))

        manifest = read_json(source_dir / "run_manifest.json")
        result = run_pipeline(self.settings, source="data", question=manifest.get("question") or paper.title,
                              live=True, constraints=body.get("constraints"), source_run=run_id,
                              search_bundle=bundle, citation_cache=cache)
        added = result["live"]["added_paper_ids"]
        related_ids = list(result["live"]["paper_provenance"])
        related_papers = workspace_papers(runs_dir, result["run_id"], related_ids)
        message = f"已找到 {len(related_papers)} 篇引文，新增 {len(added)} 篇论文。"
        result["related"] = preview("completed", message, list(related_papers.values()), added)
        return result

    def _attach_fulltext(self, payload: dict, message: str, intent) -> None:
        """Search current-run documents for this question, without new acquisition."""
        if payload.get("research_agenda"):
            from src.research_workspace import research_agenda_fulltext
            from src.tasks import report_progress
            scope = payload["reading_scope"]
            report_progress("fulltext_search", run_id=payload["run_id"])
            try:
                index = research_agenda_fulltext(self.settings.runs_dir, payload["run_id"], message, scope["paper_ids"],
                                                 selection=payload.get("reading_selection"))
            except (OSError, ValueError):
                index = {"hits": [], "available_fulltext_paper_ids": []}
            payload["fulltext_index"] = index
            scope["available_fulltext_paper_ids"] = index["available_fulltext_paper_ids"]
            scope["evidence_window_paper_ids"] = list(dict.fromkeys(hit["paper_id"] for hit in index["hits"]))
            return
        if not payload.get("fulltext_audit", {}).get("documents"):
            payload["fulltext_index"] = {"hits": [], "question_searches": []}
            payload["fulltext_search_status"] = {"status": "unavailable", "reason": "no_current_documents"}
            return
        from src.research_workspace import search_fulltext
        target = getattr(intent, "target_paper_id", None)
        try:
            from src.tasks import report_progress
            scope = payload.get("reading_scope") or {}
            paper_ids = scope.get("paper_ids") if "paper_ids" in scope else ([target] if target else None)
            previous_questions = [p["content"] for p in payload.get("conversation_context", []) if p["role"] == "user"]
            search_question = message
            if len(message) < 80 and previous_questions and scope.get("source") == "history_reference":
                search_question = previous_questions[-1][:500] + " " + message
            report_progress("fulltext_search", run_id=payload["run_id"])
            primary = search_fulltext(self.settings.runs_dir, payload["run_id"], search_question[:2000], paper_ids=paper_ids)
            # Allocate evidence to each part of a compound research question.
            # Keep each original passage intact, rather than creating a merged
            # paragraph that no longer has a single original location.
            from src import grounded_reading
            requirements = getattr(grounded_reading, "question_requirements", lambda q: [])(message)
            groups, executed = [], [{"question": search_question[:2000], "kind": "primary"}]
            if len(requirements) > 1:
                for requirement in requirements[:4]:
                    query = requirement.get("query") or requirement.get("label") or message
                    report_progress("fulltext_subquestions", run_id=payload["run_id"])
                    part = search_fulltext(self.settings.runs_dir, payload["run_id"], query[:2000], paper_ids=paper_ids)
                    groups.append(part.get("hits", []))
                    executed.append({"question": query[:2000], "requirement_id": requirement.get("id")})
            groups.append(primary.get("hits", []))
            if paper_ids and 1 < len(paper_ids) <= 4:
                # A comparison needs evidence from each selected paper. A
                # single highly matching paper must not consume the whole
                # model window before another paper receives any passage.
                groups = [[hit for hit in group if hit["paper_id"] == paper_id]
                          for group in groups for paper_id in paper_ids]
            merged, seen = [], set()
            for index in range(12):
                for group in groups:
                    if index < len(group) and group[index]["passage_id"] not in seen:
                        seen.add(group[index]["passage_id"])
                        merged.append(group[index])
            payload["fulltext_index"] = {**primary, "hits": merged[:16], "question_searches": executed}
            # A follow-up launched from a passage must actually include that
            # passage, even when generic method words rank other pages higher.
            from src.research_workspace import _corpus, _hit
            from src.fulltext_search import chunk_pages
            papers, pages, _ = _corpus(self.settings.runs_dir, payload["run_id"], paper_ids)
            selected = [_hit(p, payload["run_id"]) for p in chunk_pages(papers, pages)
                        if p.passage_id in message]
            selection = payload.get('reading_selection')
            if selection:
                from src.reading_selection import selected_page_passages
                own_pages = pages.get(selection['paper_id']) or []
                original = own_pages[selection['page'] - 1] if selection['page'] <= len(own_pages) else ''
                selected = [_hit(p, payload['run_id']) for p in
                    selected_page_passages(chunk_pages(papers, pages), selection, original)[:6]] + selected
            if selected:
                selected = list({p['passage_id']: p for p in selected}.values())
                chosen = {p["passage_id"] for p in selected}
                payload["fulltext_index"]["hits"] = selected + [
                    p for p in payload["fulltext_index"]["hits"] if p["passage_id"] not in chosen]
        except (ValueError, OSError) as exc:
            payload["fulltext_index"] = {"hits": [], "question_searches": []}
            payload["fulltext_search_status"] = {"status": "unavailable", "reason": str(exc)}

    def _document_file(self, run_id: str, paper_id: str) -> Path:
        from src.run_paths import resolve_run_dir
        from src.io_utils import read_json
        from src.research_workspace import workspace_papers
        if paper_id not in workspace_papers(self.settings.runs_dir, run_id):
            raise FileNotFoundError("该论文不属于当前研究范围")
        run_dir = resolve_run_dir(self.settings.runs_dir, run_id).resolve()
        audit = read_json(run_dir / "output" / "fulltext_audit.json")
        document = next((d for d in audit.get("documents", []) if d.get("paper_id") == paper_id and d.get("response_path")), None)
        if document is None:
            raise FileNotFoundError("全文尚不可用")
        from src.run_paths import resolve_run_file
        return resolve_run_file(run_dir, document["response_path"])

    def _fulltext(self, path: str) -> None:
        try:
            run_id, paper_id = path[len("/api/fulltext/"):].split("/", 1)
            target = self._document_file(run_id, paper_id)
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

    def _execute_operation(self, path: str, body: dict) -> dict:
        if path == '/api/map-topics/refresh':
            from src.map_topics import refresh_map_topics
            from src.tasks import report_progress
            from src.ui.payload import build_map_topic_payload
            run_id = body.get('run_id')
            report_progress('map_topics', run_id=run_id)
            return refresh_map_topics(build_map_topic_payload(self.settings.runs_dir, run_id), self.settings,
                                      force=body.get('force', False))
        if path == "/api/research/search-more":
            from src.replay import load_run
            from src.retrieve import search_all
            from src.research_query import ACTIVE_SEARCH_SOURCES, validate_search_supplement
            from src.run_paths import resolve_run_dir
            from src.pipeline import new_run_id
            run_id = body.get("run_id")
            loaded = load_run(self.settings.runs_dir, run_id)
            manifest = loaded["manifest"]
            question = manifest.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError("当前研究尚未保存可用于补查的问题")
            failed_only = body.get("failed_only", False)
            if not isinstance(failed_only, bool):
                raise ValueError("failed_only必须为布尔值")
            previous = manifest.get("live") or {}
            sources = None
            if failed_only:
                coverage = previous.get("coverage") or {}
                sources = [source for source, item in coverage.items()
                           if source in ACTIVE_SEARCH_SOURCES and item.get("status") in {"failed", "partial"}]
                if not sources:
                    sources = list(dict.fromkeys(r.get("source") for r in previous.get("retrieval", [])
                                   if r.get("status") != "success" and r.get("source") in ACTIVE_SEARCH_SOURCES))
                if not sources:
                    raise ValueError("当前研究没有需要重试的失败检索来源")
            supplement = validate_search_supplement(body.get("search_supplement"))
            cache = resolve_run_dir(self.settings.runs_dir, new_run_id("discovery")) / "cache"
            bundle = search_all(question, cache_dir=cache, constraints=previous.get("constraints") or manifest.get("constraints"),
                mailto=self.settings.openalex_mailto,
                openalex_api_key=getattr(self.settings, "openalex_api_key", None),
                base_sources=sources, supplement=supplement)
            result = run_pipeline(self.settings, question=question, live=True, source_run=run_id, search_bundle=bundle)
            result["search_more"] = {"parent_run_id": run_id, "requested_sources": sources, "failed_only": failed_only,
                                     "notice": "已有论文与研究材料保留在独立研究副本中，本次查询范围另行记录。"}
            return result
        """Compute a response independently of a live HTTP connection."""
        from src.tasks import report_progress
        if path == "/api/import/pdf":
            from src.import_documents import import_pdf
            report_progress("import_pdf")
            return import_pdf(self.settings, body)
        if path == "/api/research/related":
            return self._citation_discovery(body)
        if path == "/api/fulltext/search":
            from src.research_workspace import search_fulltext
            report_progress("search_fulltext", run_id=body.get("run_id"))
            return search_fulltext(self.settings.runs_dir, body.get("run_id"), body.get("query", ""),
                                   paper_ids=body.get("paper_ids"), section=body.get("section"))
        if path == "/api/audit/upgrade":
            from src.pipeline import upgrade_audit
            report_progress("fulltext", run_id=body.get("run_id"))
            return upgrade_audit(self.settings, body.get("run_id"), acquire=body.get("acquire") is True, paper_ids=body.get("paper_ids"))
        capture = []
        handler = object.__new__(LitAuditHandler)
        handler.settings = self.settings
        handler._json = lambda value, status=200: capture.append((value, status))
        if path == "/api/chat":
            handler._chat(body)
        else:
            handler._live(body)
        if not capture:
            raise RuntimeError("任务未产生处理结果")
        value, status = capture[-1]
        if status >= 400:
            raise ValueError(value.get("error", "研究任务未完成"))
        return value

    def _read_body(self, max_bytes: int = 1024 * 1024) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0:
                raise ValueError("Content-Length 无效")
            if length > max_bytes:
                self._json({"error": f"请求内容超过{max_bytes // 1024 // 1024}MB"}, status=413)
                return None
            body = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
            if not isinstance(body, dict):
                raise ValueError("请求JSON必须为对象")
            return body
        except (ValueError, UnicodeDecodeError) as exc:
            self._json({"error": str(exc)}, status=400)
            return None

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

    def server_close(self):
        if hasattr(self, "tasks"):
            self.tasks.close()
        super().server_close()

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
    from src.tasks import TaskManager
    server.tasks = TaskManager(settings.runs_dir)
    url = f"http://127.0.0.1:{bound}/"
    if run_id:
        url += f"?run={run_id}"
    return server, url


def serve_ui(*, run_id: str | None = None, port: int = 8787, open_browser: bool = True) -> int:
    server, url = make_server(port=port, run_id=run_id)
    print(f"LitAudit UI  {url}  pid={os.getpid()}", flush=True)
    print("勘验工作台：界面「检索文献」会调用 arXiv / OpenAlex。按 Ctrl+C 结束。", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭界面")
    finally:
        server.server_close()
    return 0
