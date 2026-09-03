from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.ask import ask
from src.config import ROOT, load_settings
from src.eval_metrics import evaluate
from src.io_utils import read_json
from src.map_builder import build_map
from src.replay import list_runs, load_run
from src.run_paths import resolve_run_dir
from src.schema import dataset_stats, latest_screening_by_paper

SCOPE_QUESTION = (
    "在自动科研文献综述或研究问答中，相比无外部检索的 LLM，"
    "检索增强大模型智能体是否提高证据可追溯性与事实/任务质量？"
)


def _dump(model) -> dict:
    return model.model_dump(mode="json")


def _truncate(text: str | None, limit: int = 36) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _format_when_windows(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        local = dt.astimezone()
        return f"{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"
    except ValueError:
        return ""


def _run_kind(run_id: str, manifest: dict) -> str:
    if run_id == "phase2-real":
        return "baseline"
    if run_id == "demo" or manifest.get("source") == "fixture":
        return "demo"
    if run_id.startswith("live_") or manifest.get("offline") is False:
        return "live"
    if run_id.startswith("run_"):
        return "snapshot"
    return "other"


def describe_run(runs_dir: Path, run_id: str) -> dict:
    run_dir = resolve_run_dir(runs_dir, run_id)
    manifest_path = run_dir / "run_manifest.json"
    stats_path = run_dir / "stats.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    stats = read_json(stats_path) if stats_path.exists() else {}
    kind = _run_kind(run_id, manifest)
    when = _format_when_windows(manifest.get("created_at"))
    paper_count = stats.get("paper_count")
    verified = stats.get("verified_evidence_count")
    question = manifest.get("question") or ""

    if kind == "baseline":
        label = "基准核验结果"
        subtitle = f"{paper_count or 7} 篇候选 · {verified or 14} 条已核对页码"
    elif kind == "demo":
        label = "演示数据（测试用）"
        subtitle = "不含真实论文统计"
    elif kind == "live":
        label = f"在线检索 · {when}" if when else "在线检索"
        if question:
            subtitle = _truncate(question, 40)
        else:
            added = (manifest.get("live") or {}).get("added_paper_ids") or []
            subtitle = f"新增 {len(added)} 篇候选" if added else f"共 {paper_count or '—'} 篇候选"
    elif kind == "snapshot":
        label = f"本地快照 · {when}" if when else "本地快照"
        subtitle = f"{paper_count or '—'} 篇候选"
    else:
        label = run_id
        subtitle = f"{paper_count or '—'} 篇候选"

    return {
        "id": run_id,
        "label": label,
        "subtitle": subtitle,
        "kind": kind,
        "when": when,
        "offline": bool(manifest.get("offline", True)),
        "paper_count": paper_count,
        "verified_evidence_count": verified,
    }


def _retrieval_status_label(run) -> str:
    if run.http_status == 429 or run.status == "rate_limited":
        return "Semantic Scholar 暂时限流（未取得该源结果）" if run.source == "semantic_scholar" else "文献库暂时限流（未取得该源结果）"
    if run.status == "success":
        return "成功"
    return "该源请求失败"


def _retrieval_note(run) -> str:
    if run.http_status == 429 or run.status == "rate_limited":
        return "未取得结果，不能当成零篇成功。"
    if run.notes:
        return run.notes
    if run.status != "success":
        return "该源请求失败，其他成功源的结果仍可使用。"
    return ""


def _retrieval_summary(dataset, manifest: dict) -> dict:
    settings = load_settings()
    live = manifest.get("live") or {}
    live_ids = {item.get("retrieval_id") for item in live.get("retrieval", []) if item.get("retrieval_id")}
    is_live = not manifest.get("offline", True) and bool(live)
    if is_live and live_ids:
        round_runs = [run for run in dataset.retrieval_runs if run.retrieval_id in live_ids]
        history_runs = [run for run in dataset.retrieval_runs if run.retrieval_id not in live_ids]
    else:
        round_runs = list(dataset.retrieval_runs)
        history_runs = []

    round_failures = [run for run in round_runs if run.is_failure]
    hints: list[str] = []
    if any(run.source == "semantic_scholar" and run.is_failure for run in round_runs) and not settings.semantic_scholar_api_key:
        hints.append("Semantic Scholar 未配置 API Key，容易触发 429；可在 .env 填写 SEMANTIC_SCHOLAR_API_KEY。")
    if round_failures and any(not run.is_failure for run in round_runs):
        hints.append("部分检索源失败不代表整次检索失败；成功源返回的论文仍可使用。")
    if is_live:
        hints.append("本轮仅为摘要筛选，主问题不会被自动标为已支持。")

    def _serialize(run) -> dict:
        payload = _dump(run)
        payload["status_label"] = _retrieval_status_label(run)
        payload["note_text"] = _retrieval_note(run)
        return payload

    return {
        "round_runs": [_serialize(run) for run in round_runs],
        "history_runs": [_serialize(run) for run in history_runs],
        "round_failure_count": len(round_failures),
        "round_success_count": sum(1 for run in round_runs if not run.is_failure),
        "semantic_scholar_key_configured": bool(settings.semantic_scholar_api_key),
        "hints": hints,
    }


def list_runs_for_ui(runs_dir: Path) -> list[dict]:
    return [describe_run(runs_dir, run_id) for run_id in list_runs(runs_dir)]


def _workspace_context(dataset, manifest: dict, display: dict, stats: dict, map_payload: dict) -> dict:
    scope_version = next(
        (query.scope_version for query in dataset.queries if query.scope_version),
        "v0.1",
    )
    live = manifest.get("live") or {}
    added_ids = set(live.get("added_paper_ids") or [])
    is_live = not manifest.get("offline", True) and bool(live)
    live_retrieval_ids = {item.get("retrieval_id") for item in live.get("retrieval", [])}
    visible_papers = [paper for paper in dataset.papers if not is_live or paper.paper_id in added_ids]
    visible_cards = [paper for paper in dataset.paper_cards if not is_live or paper.paper_id in added_ids]
    pending_claims = [
        {"claim_id": claim.claim_id, "text": claim.text}
        for claim in dataset.claims
        if claim.status.value == "pending"
        and not claim.is_fixture
        and (not is_live or claim.text == manifest.get("question"))
    ]
    pending_papers = [
        {"paper_id": paper.paper_id, "title": paper.title, "reason": paper.reason}
        for paper in visible_papers
        if paper.decision.value == "pending" and not paper.is_fixture
    ]
    abstract_only_papers = [
        {"paper_id": paper.paper_id, "title": paper.title, "parse_status": paper.parse_status}
        for paper in visible_cards
        if paper.parse_status in {"abstract_verified", "live_abstract"} and not paper.is_fixture
    ]
    retrieval_failures = [
        {
            "retrieval_id": run.retrieval_id,
            "source": run.source,
            "status": run.status,
            "http_status": run.http_status,
        }
        for run in dataset.retrieval_runs
        if run.is_failure and (not is_live or run.retrieval_id in live_retrieval_ids)
    ]
    contradictions = [
        {
            "claim_id": item.get("claim_id"),
            "claim_status": item.get("claim_status"),
            "support_or_context_papers": item.get("support_or_context_papers", []),
            "contradict_papers": item.get("contradict_papers", []),
        }
        for item in map_payload.get("contradictions", [])
    ]
    return {
        "run_id": manifest.get("run_id") or display.get("id"),
        "label": display.get("label"),
        "subtitle": display.get("subtitle"),
        "question": manifest.get("question") or SCOPE_QUESTION,
        "scope_version": scope_version,
        "created_at": manifest.get("created_at"),
        "offline": bool(manifest.get("offline", True)),
        "candidate_count": len(visible_papers) if is_live else stats.get("paper_count", 0),
        "decision_counts": (
            {decision: sum(paper.decision.value == decision for paper in visible_papers) for decision in ("include", "exclude", "pending")}
            if is_live else stats.get("decision_counts", {})
        ),
        "verified_evidence_count": (
            sum(evidence.paper_id in added_ids and evidence.extraction_status.value == "verified" for evidence in dataset.evidence)
            if is_live else stats.get("verified_evidence_count", 0)
        ),
        "pending_claims": pending_claims,
        "pending_papers": pending_papers,
        "abstract_only_papers": abstract_only_papers,
        "contradictions": contradictions,
        "retrieval_failures": retrieval_failures,
        "review_item_count": len(pending_claims) + len(pending_papers) + len(abstract_only_papers),
    }


def _visible_live_map(map_payload: dict, manifest: dict) -> dict:
    """Hide inherited baseline nodes from a live map without deleting audit data."""
    live = manifest.get("live") or {}
    added_ids = set(live.get("added_paper_ids") or [])
    if manifest.get("offline", True) or not live:
        return map_payload

    visible = {
        **map_payload,
        "nodes": [node for node in map_payload.get("nodes", []) if node.get("paper_id") in added_ids],
        "edges": [
            edge for edge in map_payload.get("edges", [])
            if edge.get("source") in added_ids and edge.get("target") in added_ids
        ],
        "tracks": [
            {**track, "paper_ids": [paper_id for paper_id in track.get("paper_ids", []) if paper_id in added_ids]}
            for track in map_payload.get("tracks", [])
        ],
        "contradictions": [
            {
                **item,
                "support_or_context_papers": [paper_id for paper_id in item.get("support_or_context_papers", []) if paper_id in added_ids],
                "contradict_papers": [paper_id for paper_id in item.get("contradict_papers", []) if paper_id in added_ids],
            }
            for item in map_payload.get("contradictions", [])
        ],
        "limitations": [
            *map_payload.get("limitations", []),
            "在线地图仅展示本轮新增论文；继承的本地基准论文仍保留在 run 和内部研究上下文中。",
        ],
    }
    visible["tracks"] = [track for track in visible["tracks"] if track["paper_ids"]]
    visible["contradictions"] = [
        item for item in visible["contradictions"]
        if item["support_or_context_papers"] and item["contradict_papers"]
    ]
    return visible


def build_payload(runs_dir, run_id: str) -> dict:
    loaded = load_run(runs_dir, run_id)
    dataset = loaded["dataset"]
    cards = dataset.card_by_id()
    latest = latest_screening_by_paper(dataset.screening)
    papers = []
    for paper in dataset.papers:
        card = cards.get(paper.paper_id)
        log = latest.get(paper.paper_id)
        papers.append(
            {
                **_dump(paper),
                "is_fixture": paper.is_fixture,
                "parse_status": None if card is None else card.parse_status,
                "parse_error": None if card is None else card.parse_error,
                "fields": None if card is None or card.fields is None else _dump(card.fields),
                "latest_screening": None if log is None else _dump(log),
            }
        )
    manifest = loaded.get("manifest") or {}
    display = describe_run(runs_dir, run_id)
    stats = loaded.get("stats") or dataset_stats(dataset)
    map_payload = _visible_live_map(build_map(dataset, run_id), manifest)
    context = _workspace_context(dataset, manifest, display, stats, map_payload)
    retrieval_summary = _retrieval_summary(dataset, manifest)
    return {
        "run_id": run_id,
        "display": display,
        "scope_version": context["scope_version"],
        "question": context["question"],
        "offline": bool(manifest.get("offline", True)),
        "live": manifest.get("live"),
        "manifest": manifest,
        "stats": stats,
        "map": map_payload,
        "workspace": context,
        "retrieval_summary": retrieval_summary,
        "eval": evaluate(ROOT),
        "papers": papers,
        "claims": [_dump(item) for item in dataset.claims],
        "evidence": [_dump(item) for item in dataset.evidence],
        "claim_decisions": [_dump(item) for item in dataset.claim_decisions],
        "falsification": [_dump(item) for item in dataset.falsification],
        "screening": [_dump(item) for item in dataset.screening],
        "retrieval_runs": [_dump(item) for item in dataset.retrieval_runs],
        "queries": [_dump(item) for item in dataset.queries],
    }


def list_available_runs(runs_dir) -> list[str]:
    return list_runs(runs_dir)


def ask_payload(runs_dir, run_id: str, question: str) -> dict:
    dataset = load_run(runs_dir, run_id)["dataset"]
    return ask(dataset, question)


def _md_cell(value: object) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ").strip()


def build_audit_report(runs_dir: Path, run_id: str) -> tuple[str, str]:
    loaded = load_run(runs_dir, run_id)
    dataset = loaded["dataset"]
    manifest = loaded.get("manifest") or {}
    stats = loaded.get("stats") or dataset_stats(dataset)
    map_payload = _visible_live_map(build_map(dataset, run_id), manifest)
    display = describe_run(runs_dir, run_id)
    context = _workspace_context(dataset, manifest, display, stats, map_payload)
    counts = stats.get("decision_counts", {})
    claim_counts = stats.get("claim_status_counts", {})
    lines = [
        f"# 勘文 LitAudit 审计报告：{display.get('label') or run_id}",
        "",
        "> 本报告由已落盘的结构化数据生成。它是可回溯审计报告，不是自动生成的跨论文长综述。",
        "",
        "## 研究上下文",
        "",
        f"- 研究问题：{_md_cell(context['question'])}",
        f"- 研究范围版本：`{_md_cell(context['scope_version'])}`",
        f"- 运行：`{_md_cell(run_id)}`；{_md_cell(context.get('created_at'))}",
        f"- 模式：{'离线快照' if context['offline'] else '在线检索'}",
        "",
        "## 规模与状态",
        "",
        "| 对象 | 状态/数量 |",
        "| --- | ---: |",
        f"| 候选论文 | {stats.get('paper_count', 0)} |",
        f"| 纳入 / 排除 / 待定 | {counts.get('include', 0)} / {counts.get('exclude', 0)} / {counts.get('pending', 0)} |",
        f"| Claim | {stats.get('claim_count', 0)} |",
        f"| Claim 状态 | supported {claim_counts.get('supported', 0)} / partial {claim_counts.get('partial', 0)} / pending {claim_counts.get('pending', 0)} / unsupported {claim_counts.get('unsupported', 0)} |",
        f"| Evidence | {stats.get('evidence_count', 0)}；页码定位 {stats.get('page_locator_count', 0)} |",
        f"| 已核验 Evidence | {stats.get('verified_evidence_count', 0)} |",
        f"| 反证命中 | {stats.get('falsification_count', 0)} |",
        f"| 检索运行 / 失败 | {stats.get('retrieval_run_count', 0)} / {stats.get('retrieval_failure_count', 0)} |",
        "",
        "## 论断核验",
        "",
        "| Claim | 状态 | 论断 | 判决理由 |",
        "| --- | --- | --- | --- |",
    ]
    decisions = {item.claim_id: item for item in dataset.claim_decisions}
    for claim in dataset.claims:
        if claim.is_fixture:
            continue
        decision = decisions.get(claim.claim_id)
        lines.append(
            f"| `{_md_cell(claim.claim_id)}` | {_md_cell(claim.status.value)} | {_md_cell(claim.text)} | {_md_cell(decision.reason if decision else claim.decision_reason)} |"
        )
    lines.extend(["", "## 证据索引", "", "| Evidence | Claim | 论文 | 关系 | 定位 | 状态 |", "| --- | --- | --- | --- | --- | --- |"])
    paper_titles = {paper.paper_id: paper.title for paper in dataset.papers}
    for evidence in dataset.evidence:
        if evidence.is_fixture:
            continue
        locator = evidence.locator
        location = f"第 {locator.page} 页" if locator.page is not None else "；".join(
            str(value) for value in [locator.section, locator.paragraph, locator.char_range, locator.url_anchor] if value
        )
        lines.append(
            f"| `{_md_cell(evidence.evidence_id)}` | `{_md_cell(evidence.claim_id)}` | {_md_cell(paper_titles.get(evidence.paper_id, evidence.paper_id))} | {_md_cell(evidence.verdict.value)} | {_md_cell(location)} | {_md_cell(evidence.extraction_status.value)} |"
        )
    lines.extend(["", "## 反证据", ""])
    if dataset.falsification:
        lines.extend(["| 命中 | 目标 Claim | 论文 | 威胁 | 状态 |", "| --- | --- | --- | --- | --- |"])
        for hit in dataset.falsification:
            if hit.is_fixture:
                continue
            lines.append(
                f"| `{_md_cell(hit.hit_id)}` | `{_md_cell(hit.target_claim)}` | {_md_cell(paper_titles.get(hit.paper_id, hit.paper_id))} | {_md_cell(hit.threat.value)}/{_md_cell(hit.threat_level.value)} | {_md_cell(hit.status.value)} |"
            )
    else:
        lines.append("当前没有反证据命中。")
    lines.extend(["", "## 人工待处理", ""])
    if context["pending_claims"]:
        lines.append("- 待核验论断：" + "；".join(f"`{item['claim_id']}`" for item in context["pending_claims"]))
    if context["pending_papers"]:
        lines.append("- 待定论文：" + "；".join(f"`{item['paper_id']}`" for item in context["pending_papers"]))
    if context["abstract_only_papers"]:
        lines.append("- 仍只有摘要或在线摘要的论文：" + "；".join(f"`{item['paper_id']}`" for item in context["abstract_only_papers"]))
    if context["retrieval_failures"]:
        lines.append("- 检索失败/限流记录：" + "；".join(f"`{item['retrieval_id']}` {item['status']}" for item in context["retrieval_failures"]))
    if not any([context["pending_claims"], context["pending_papers"], context["abstract_only_papers"], context["retrieval_failures"]]):
        lines.append("当前没有额外待处理项。")
    lines.extend(["", "## 限制", ""])
    for limitation in manifest.get("limitations") or map_payload.get("limitations") or []:
        lines.append(f"- {_md_cell(limitation)}")
    lines.extend(["", "---", "", "证据链原则：Claim -> Evidence -> PaperCard。没有有效 Evidence 或存在未解决冲突时，不将 Claim 写成确定支持。", ""])
    filename = f"litaudit-{run_id}-audit.md"
    return "\n".join(lines), filename
