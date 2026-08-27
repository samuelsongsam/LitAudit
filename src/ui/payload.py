from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.ask import ask
from src.config import ROOT
from src.eval_metrics import evaluate
from src.io_utils import read_json
from src.replay import list_runs, load_run
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
    manifest_path = runs_dir / run_id / "run_manifest.json"
    stats_path = runs_dir / run_id / "stats.json"
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


def list_runs_for_ui(runs_dir: Path) -> list[dict]:
    return [describe_run(runs_dir, run_id) for run_id in list_runs(runs_dir)]


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
    return {
        "run_id": run_id,
        "display": display,
        "scope_version": "v0.1",
        "question": SCOPE_QUESTION,
        "offline": bool(manifest.get("offline", True)),
        "live": manifest.get("live"),
        "manifest": manifest,
        "stats": loaded.get("stats") or dataset_stats(dataset),
        "map": loaded.get("map") or {},
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
