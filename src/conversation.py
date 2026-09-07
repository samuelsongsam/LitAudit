from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.ui.payload import build_payload, ask_payload
from src.run_paths import resolve_run_dir


@dataclass
class Intent:
    kind: str
    confidence: float
    reason: str
    needs_retrieval: bool
    target_paper_id: str | None = None
    branch: str | None = None
    needs_clarification: bool = False
    direct_answer: bool = False
    clarification_questions: list[dict] | None = None
    expanded_query: str | None = None
    answer: str | None = None
    route_source: str = "unknown"
    route_error: str | None = None


def _coerce_expanded_query(value) -> str:
    """Accept the string contract and the structured query shape returned by some LLM responses."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("query", "search_query", "expanded_query"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    parts: list[str] = []
    for key in ("original_topic", "scope"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            parts.append(candidate.strip())
    choices = value.get("choices")
    if isinstance(choices, list):
        parts.extend(item.strip() for item in choices if isinstance(item, str) and item.strip())
    return " ".join(parts)


def _parse_llm_json(content):
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise TypeError("llm_content_not_json")
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _coerce_clarification_questions(raw) -> list[dict] | None:
    """Accept nearby LLM shapes and normalize to exactly 3 questions × 3 options."""
    if not isinstance(raw, list):
        return None
    normalized: list[dict] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            normalized.append({"question": item.strip(), "options": ["综述与经典论文", "方法原理与框架", "实验对比与评测"]})
            continue
        if not isinstance(item, dict):
            continue
        question = item.get("question") or item.get("q") or item.get("prompt") or item.get("title")
        if not isinstance(question, str) or not question.strip():
            continue
        options = item.get("options") or item.get("choices") or item.get("answers") or []
        if isinstance(options, str):
            options = [part.strip() for part in re.split(r"[|/；;、]", options) if part.strip()]
        if not isinstance(options, list):
            continue
        cleaned = []
        for option in options:
            if isinstance(option, str) and option.strip():
                cleaned.append(option.strip())
            elif isinstance(option, dict):
                label = option.get("label") or option.get("text") or option.get("option")
                if isinstance(label, str) and label.strip():
                    cleaned.append(label.strip())
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique = []
        for option in cleaned:
            if option in seen:
                continue
            seen.add(option)
            unique.append(option)
        if len(unique) < 3:
            for filler in ("综述与经典论文", "方法原理与框架", "实验对比与评测", "应用场景", "风险与局限"):
                if filler not in seen:
                    unique.append(filler)
                    seen.add(filler)
                if len(unique) >= 3:
                    break
        if len(unique) < 3:
            continue
        normalized.append({"question": question.strip(), "options": unique[:3]})
        if len(normalized) == 3:
            return normalized
    return normalized if len(normalized) == 3 else None


def _normalize_llm_route(result, fallback_query: str = "") -> tuple[dict | None, str | None]:
    if not isinstance(result, dict) or result.get("action") not in {"direct_answer", "clarify", "retrieve"}:
        return None, "invalid_llm_route"
    if result["action"] == "clarify":
        questions = _coerce_clarification_questions(result.get("questions") or result.get("clarification_questions"))
        if questions is None:
            # Prefer continuing with retrieval over failing the whole turn.
            query = _coerce_expanded_query(result.get("expanded_query")) or (fallback_query or "").strip()
            if query:
                result["action"] = "retrieve"
                result["expanded_query"] = query
            else:
                return None, "invalid_llm_questions"
        else:
            result["questions"] = questions
    if result["action"] == "direct_answer" and not isinstance(result.get("answer"), (str, type(None))):
        result["answer"] = None
    if result["action"] == "retrieve":
        expanded_query = _coerce_expanded_query(result.get("expanded_query")) or (fallback_query or "").strip()
        if not expanded_query:
            return None, "missing_expanded_query"
        result["expanded_query"] = expanded_query
    allowed_kinds = {"follow_up", "paper_explore", "branch_deepen", "requery", "new_topic"}
    if result.get("kind") not in allowed_kinds:
        result["kind"] = "new_topic" if result["action"] in {"clarify", "retrieve"} else "follow_up"
    for key in ("target_paper_id", "branch"):
        if result.get(key) is not None and not isinstance(result.get(key), str):
            result[key] = None
    return result, None


def _llm_route(message: str, payload: dict | None, settings, clarification_context: list[str] | None = None, clarification_topic: str | None = None) -> dict | None:
    if not settings or not settings.llm_api_key:
        return {"action": "error", "error": "missing_llm_api_key"}
    request_body = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是 LitAudit 的研究请求路由器，遵守 skills/conversational-research-routing/SKILL.md。只返回 JSON。必须返回 action 和 kind；action 只能是 direct_answer、clarify、retrieve，kind 只能是 follow_up、paper_explore、branch_deepen、requery、new_topic。追问当前结果且现有 papers/claims/evidence 足够时才用 direct_answer。当前 run 为空、新建对话、或 available_papers 为空时，禁止 direct_answer，研究问题必须 retrieve 或 clarify，不得回答“没有数据请先检索”。询问某篇论文时用 paper_explore 并返回 target_paper_id；沿某分支补充文献时用 retrieve+branch_deepen 并返回 branch；明确重新检索时用 retrieve+requery；新主题或无关主题用 retrieve+new_topic。clarify 时必须返回 questions 数组，恰好 3 题，每题恰好 3 个针对当前主题的 options。retrieve 时必须返回包含原始主题、选择和范围的 expanded_query。不得编造论文。"},
            {"role": "user", "content": json.dumps({"message": message, "original_topic": clarification_topic, "previous_choices": clarification_context or [], "current_question": (payload or {}).get("question"), "available_papers": [{"paper_id": p.get("paper_id"), "title": p.get("title")} for p in (payload or {}).get("papers", [])], "available_claims": [{"claim_id": c.get("claim_id"), "text": c.get("text"), "status": c.get("status")} for c in (payload or {}).get("claims", [])]}, ensure_ascii=False)},
        ],
    }
    last_error = "llm_request_failed:UnknownError"
    payload_bytes = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    for attempt in range(2):
        request = Request(settings.llm_base_url.rstrip("/") + "/chat/completions", data=payload_bytes, headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.llm_api_key}"}, method="POST")
        try:
            with urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            result = _parse_llm_json(content)
            normalized, validation_error = _normalize_llm_route(result, message)
            if normalized is not None:
                return normalized
            last_error = validation_error or "invalid_llm_route"
            if attempt == 0:
                time.sleep(0.4)
                continue
            return {"action": "error", "error": last_error}
        except HTTPError as exc:
            last_error = f"llm_request_failed:HTTPError:{exc.code}"
            try:
                exc.read()
            except Exception:
                pass
            if attempt == 0:
                time.sleep(0.4)
        except (URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            last_error = f"llm_request_failed:{type(exc).__name__}"
            if attempt == 0:
                time.sleep(0.4)
    return {"action": "error", "error": last_error}


def _payload_has_research_data(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("papers") or payload.get("claims") or payload.get("evidence"))


def classify_intent(message: str, payload: dict | None = None, settings=None, clarification_context: list[str] | None = None, clarification_topic: str | None = None) -> Intent:
    text = (message or "").strip()
    llm_route = _llm_route(text, payload, settings, clarification_context, clarification_topic)
    action = llm_route["action"]
    if action == "error":
        return Intent("llm_error", 1.0, "DeepSeek 路由未成功", False, route_source="llm", route_error=llm_route.get("error"))
    if action == "direct_answer" and not _payload_has_research_data(payload):
        query = (_coerce_expanded_query(llm_route.get("expanded_query")) or text).strip()
        return Intent(
            llm_route.get("kind") or "new_topic",
            0.95,
            "当前 run 无结构化数据，改为检索",
            True,
            target_paper_id=llm_route.get("target_paper_id"),
            branch=llm_route.get("branch"),
            expanded_query=query or text,
            route_source="llm",
        )
    if action == "direct_answer":
        return Intent(llm_route.get("kind") or ("follow_up" if payload else "new_topic"), 0.95, "LLM 判断现有上下文足以回答", False, target_paper_id=llm_route.get("target_paper_id"), branch=llm_route.get("branch"), direct_answer=True, answer=llm_route.get("answer"), route_source="llm")
    if action == "clarify":
        return Intent(llm_route.get("kind") or "new_topic", 0.95, "LLM 判断研究范围仍需确认", False, target_paper_id=llm_route.get("target_paper_id"), branch=llm_route.get("branch"), needs_clarification=True, clarification_questions=llm_route.get("questions"), expanded_query=llm_route.get("expanded_query"), route_source="llm")
    return Intent(llm_route.get("kind") or ("requery" if payload else "new_topic"), 0.95, "LLM 判断需要调用文献检索", True, target_paper_id=llm_route.get("target_paper_id"), branch=llm_route.get("branch"), expanded_query=llm_route.get("expanded_query"), route_source="llm")


def _clarification_overview(message: str, intent: Intent) -> str:
    return ""


def _llm_direct_answer(payload: dict, message: str, intent: Intent, settings) -> str | None:
    if not settings.llm_api_key:
        return None
    compact = {
        "message": message,
        "question": payload.get("question"),
        "operation": intent.kind,
        "target_paper_id": intent.target_paper_id,
        "branch": intent.branch,
        "papers": [{k: p.get(k) for k in ("paper_id", "title", "year", "decision", "reason", "abstract", "parse_status")} for p in payload.get("papers", [])],
        "claims": [{k: c.get(k) for k in ("claim_id", "text", "status", "decision_reason")} for c in payload.get("claims", [])],
        "evidence": [{k: e.get(k) for k in ("evidence_id", "claim_id", "paper_id", "verdict", "locator", "quote", "extraction_status")} for e in payload.get("evidence", [])],
        "falsification": payload.get("falsification", []),
    }
    system = ("你是勘文 LitAudit 的研究助手。根据当前 run 的结构化数据直接回答用户追问，不要重新检索。"
              "若指定 target_paper_id，只聚焦该论文。不得编造论文、证据、页码或结论；摘要级信息与页码级证据必须明确区分；冲突和 pending 必须保留。"
              "只输出回答正文，不添加固定的总论、论文列表或研究地图格式。先给出一句直接结论，再按信息层级分段；论文较多时使用 Markdown 有序列表，每项只保留标题、年份、核验层级和一项最关键内容。"
              "不要把十余篇论文压成一个长段落，不重复用户问题，不罗列与问题无关的排除论文；默认控制在 800 至 1400 个中文字符，除非用户明确要求更详细。")
    request_body = {"model": settings.llm_model, "temperature": 0.2, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(compact, ensure_ascii=False)}]}
    request = Request(settings.llm_base_url.rstrip("/") + "/chat/completions", data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.llm_api_key}"}, method="POST")
    for attempt in range(2):
        try:
            with urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"].strip()
            if answer:
                return answer
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
            pass
        if attempt == 0:
            time.sleep(0.4)
    return None


def _llm_overview(payload: dict, intent: Intent, settings) -> tuple[str, str]:
    if not settings.llm_api_key:
        return "", "llm_error"
    live = payload.get("live") or {}
    added_ids = set(live.get("added_paper_ids") or [])
    is_live = not payload.get("offline", True) and bool(live)
    papers = [paper for paper in payload.get("papers", []) if not is_live or paper.get("paper_id") in added_ids]
    claims = [
        claim for claim in payload.get("claims", [])
        if not is_live or claim.get("text") == payload.get("question")
    ]
    evidence = [
        item for item in payload.get("evidence", [])
        if not is_live or item.get("paper_id") in added_ids
    ]
    falsification = [
        item for item in payload.get("falsification", [])
        if not is_live or item.get("paper_id") in added_ids
    ]
    overview_stats = payload.get("stats")
    if is_live:
        overview_stats = {
            "retrieved_paper_count": len(papers),
            "decision_counts": {
                decision: sum(paper.get("decision") == decision for paper in papers)
                for decision in ("include", "exclude", "pending")
            },
            "retrieval": live.get("retrieval") or [],
        }
    compact = {
        "question": payload.get("question"),
        "stats": overview_stats,
        "papers": [{k: p.get(k) for k in ("paper_id", "title", "year", "decision", "reason", "parse_status")} for p in papers],
        "claims": [{k: c.get(k) for k in ("claim_id", "text", "status", "decision_reason")} for c in claims],
        "evidence": [{k: e.get(k) for k in ("evidence_id", "claim_id", "paper_id", "verdict", "locator", "extraction_status")} for e in evidence],
        "falsification": falsification,
        "intent": asdict(intent),
    }
    system = ("你是勘文 LitAudit 的研究对话助手，遵守 conversational-research-routing 路由规则。"
              "当前 intent 已由系统判定：follow_up 只解释当前 run，paper_explore 聚焦目标论文，branch_deepen 或 requery 表示需要新检索，new_topic 表示新主题。"
              "只根据提供的结构化数据写中文总论，不能补造论文、数字、证据或因果结论。"
              "明确区分摘要级筛选和页码级核验；存在 pending 或冲突时必须说仍待核验。"
              "不能把关键词匹配、引用邻近或纳入状态当成证据。输出 3-5 段纯文本，不写 Markdown 标题。")
    request_body = {"model": settings.llm_model, "temperature": 0.2, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(compact, ensure_ascii=False)}]}
    request = Request(settings.llm_base_url.rstrip("/") + "/chat/completions", data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.llm_api_key}"}, method="POST")
    for attempt in range(2):
        try:
            with urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            return content, "llm"
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
            if attempt == 0:
                time.sleep(0.4)
    return "", "llm_error"


def build_chat_response(payload: dict, message: str, intent: Intent, settings) -> dict:
    if intent.route_error:
        return {
            "overview": "",
            "overview_mode": "llm_error",
            "intent": asdict(intent),
            "error": intent.route_error,
            "papers": [],
            "paper_selection": {"mode": "llm_error", "matched_count": 0, "total_run_count": 0, "added_count": 0, "added_paper_ids": [], "message": "AI 未生成结果，请重试。", "retrieval_status": "not_started", "retrieval_failures": []},
            "map": {},
            "ask": {"papers": []},
            "run_id": None,
            "actions": [],
            "limitations": [],
        }
    if intent.direct_answer:
        answer = intent.answer or _llm_direct_answer(payload, message, intent, settings)
        if not answer:
            return {"overview": "", "overview_mode": "llm_error", "intent": asdict(intent), "error": "llm_direct_answer_failed", "papers": [], "paper_selection": {"mode": "llm_error", "matched_count": 0, "total_run_count": 0, "added_count": 0, "added_paper_ids": [], "message": "AI 未生成结果，请重试。", "retrieval_status": "not_started", "retrieval_failures": []}, "map": {}, "ask": {"papers": []}, "run_id": payload.get("run_id"), "actions": [], "limitations": []}
        return {"overview": answer, "overview_mode": "direct_answer", "intent": asdict(intent), "papers": [], "paper_selection": {"mode": "direct_answer", "matched_count": 0, "total_run_count": len(payload.get("papers", [])), "added_count": 0, "added_paper_ids": [], "message": "复用当前研究结果，未重新检索。", "retrieval_status": "not_started", "retrieval_failures": []}, "map": {}, "ask": {"papers": []}, "run_id": payload.get("run_id"), "actions": [], "limitations": []}
    if intent.needs_clarification:
        return {
            "overview": _clarification_overview(message, intent),
            "overview_mode": "clarification",
            "intent": asdict(intent),
            "clarification_questions": intent.clarification_questions or [],
            "papers": [],
            "paper_selection": {"mode": "clarification", "matched_count": 0, "total_run_count": len(payload.get("papers", [])), "added_count": 0, "added_paper_ids": [], "message": "尚未检索；请先补充研究边界。", "retrieval_status": "not_started", "retrieval_failures": []},
            "map": {},
            "ask": {"papers": []},
            "run_id": payload.get("run_id"),
            "actions": [],
            "limitations": [],
        }
    overview, overview_mode = _llm_overview(payload, intent, settings)
    if overview_mode == "llm_error":
        return {"overview": "", "overview_mode": "llm_error", "intent": asdict(intent), "error": "llm_overview_failed", "papers": [], "paper_selection": {"mode": "llm_error", "matched_count": 0, "total_run_count": 0, "added_count": 0, "added_paper_ids": [], "message": "AI 未生成结果，请重试。", "retrieval_status": "not_started", "retrieval_failures": []}, "map": {}, "ask": {"papers": []}, "run_id": payload.get("run_id"), "actions": [], "limitations": []}
    ask = ask_payload(settings.runs_dir, payload["run_id"], intent.expanded_query or message)
    target = intent.target_paper_id
    all_papers = payload.get("papers", [])
    live = payload.get("live") or {}
    added_ids = live.get("added_paper_ids") or []
    if target:
        papers = [paper for paper in all_papers if paper.get("paper_id") == target]
    elif added_ids:
        added_id_set = set(added_ids)
        papers = [paper for paper in all_papers if paper.get("paper_id") in added_id_set]
    else:
        matched_ids = {item.get("paper_id") for item in ask.get("papers", [])}
        papers = [paper for paper in all_papers if paper.get("paper_id") in matched_ids]
    live_retrieval_runs = live.get("retrieval") or []
    retrieval_failures = [item for item in live_retrieval_runs if item.get("status") != "success"] if live_retrieval_runs else payload.get("workspace", {}).get("retrieval_failures", [])
    retrieval_runs = live_retrieval_runs or payload.get("retrieval_runs", [])
    all_retrieval_failed = bool(retrieval_runs) and not any(item.get("status") == "success" for item in retrieval_runs)
    return {
        "overview": overview,
        "overview_mode": overview_mode,
        "intent": asdict(intent),
        "papers": papers,
        "paper_selection": {
            "mode": "target_paper" if target else "live_retrieval" if added_ids else "keyword_overlap",
            "matched_count": len(papers),
            "total_run_count": len(all_papers),
            "added_count": len(added_ids),
            "added_paper_ids": added_ids,
            "message": "以下展示本轮在线检索新增并完成摘要级筛选的论文。" if added_ids else "以下仅显示与本轮问题匹配的论文；其余论文仍保留在当前 run 的审计数据中。" if papers else "本轮在线检索没有新增论文；继承的基准论文不会作为本主题结果展示。",
            "retrieval_status": "all_failed" if all_retrieval_failed else "partial_failed" if retrieval_failures else "completed",
            "retrieval_failures": retrieval_failures,
        },
        "map": payload.get("map", {}),
        "ask": ask,
        "run_id": payload["run_id"],
        "actions": [
            {"kind": "funnel", "label": "查看检索与筛选", "href": f"/?run={payload['run_id']}&view=funnel"},
            {"kind": "map", "label": "展开研究地图", "href": f"/?run={payload['run_id']}&view=map"},
            {"kind": "evidence", "label": "证据核验（原有页面）", "href": f"/?run={payload['run_id']}&view=evidence", "deferred": True},
            {"kind": "falsify", "label": "反证检查（原有页面）", "href": f"/?run={payload['run_id']}&view=falsify", "deferred": True},
            {"kind": "eval", "label": "可追溯性评测（原有页面）", "href": f"/?run={payload['run_id']}&view=eval", "deferred": True},
        ],
        "limitations": payload.get("workspace", {}).get("retrieval_failures", []),
    }


def load_conversation(runs_dir: Path, run_id: str) -> dict:
    path = resolve_run_dir(runs_dir, run_id) / "output" / "conversation.json"
    if not path.exists():
        return {"run_id": run_id, "messages": []}
    try:
        conversation = json.loads(path.read_text(encoding="utf-8"))
        conversation["messages"] = _visible_messages(conversation.get("messages") or [])
        return conversation
    except json.JSONDecodeError:
        return {"run_id": run_id, "messages": []}


def save_message(runs_dir: Path, run_id: str, role: str, content: str, response: dict | None = None) -> dict:
    conversation = load_conversation(runs_dir, run_id)
    conversation.setdefault("messages", []).append({"role": role, "content": content, "created_at": datetime.now(timezone.utc).isoformat(), "response": response})
    path = resolve_run_dir(runs_dir, run_id) / "output" / "conversation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(conversation, ensure_ascii=False, indent=2), encoding="utf-8")
    return conversation


def rename_conversation(runs_dir: Path, run_id: str, title: str) -> dict:
    normalized = " ".join((title or "").split()).strip()
    if not normalized:
        raise ValueError("对话名称不能为空")
    if len(normalized) > 80:
        raise ValueError("对话名称不能超过 80 个字符")
    conversation = load_conversation(runs_dir, run_id)
    conversation["title"] = normalized
    path = resolve_run_dir(runs_dir, run_id) / "output" / "conversation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(conversation, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run_id": run_id, "title": normalized}


def _visible_messages(messages: list[dict]) -> list[dict]:
    """Hide clarification messages created by the removed fixed-template fallback."""
    visible = []
    for item in messages:
        is_legacy_clarification = (
            item.get("role") == "assistant"
            and (item.get("response") or {}).get("overview_mode") == "clarification"
            and (item.get("response") or {}).get("intent", {}).get("route_source") != "llm"
        )
        if is_legacy_clarification:
            if visible and visible[-1].get("role") == "user":
                visible.pop()
            continue
        visible.append(item)
    return visible


def list_conversations(runs_dir: Path) -> list[dict]:
    conversations = []
    if not runs_dir.exists():
        return conversations
    for path in runs_dir.glob("*/output/conversation.json"):
        try:
            conversation = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        messages = _visible_messages(conversation.get("messages") or [])
        first_user = next((item for item in messages if item.get("role") == "user"), {})
        last_message = messages[-1] if messages else {}
        conversations.append({
            "run_id": path.parents[1].name,
            "title": (conversation.get("title") or first_user.get("content") or "未命名对话")[:80],
            "message_count": len(messages),
            "updated_at": last_message.get("created_at") or "",
        })
    conversations.sort(key=lambda item: item["updated_at"], reverse=True)
    return conversations


def delete_conversation(runs_dir: Path, run_id: str) -> bool:
    path = resolve_run_dir(runs_dir, run_id) / "output" / "conversation.json"
    if not path.exists():
        return False
    path.unlink()
    return True
