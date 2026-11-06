from __future__ import annotations

from src.run_scope import visible_paper_ids

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.cache import FileCache
from src.config import Settings
from src.io_utils import load_dataset, read_json, write_json, write_jsonl
from src.logging_setup import setup_logging
from src.map_builder import build_map, write_pyvis_html
from src.run_paths import resolve_run_dir
from src.schema import Dataset, ExtractionStatus, dataset_stats

PROTECTED_RUNS = {"phase2-real", "demo"}


def unavailable_map(run_id: str, error: Exception) -> dict:
    """A truthful placeholder preserves research data without fake vectors."""
    return {
        "run_id": run_id, "status": "unavailable", "algorithm": "unavailable",
        "embedding": {"backend": "unavailable", "reason": str(error)[:240]},
        "layout": "unavailable", "nodes": [], "edges": [], "tracks": [],
        "contradictions": [], "similarity_matrix": {"paper_ids": [], "values": []},
        "legend": {}, "limitations": ["地图暂不可用；论文和证据已保存，可修复模型后单独重试地图。"],
    }


def retry_map(settings: Settings, run_id: str) -> dict:
    from src.replay import load_run
    if run_id in PROTECTED_RUNS:
        raise ValueError("请先创建研究副本，再重试地图")
    loaded = load_run(settings.runs_dir, run_id)
    run_dir = resolve_run_dir(settings.runs_dir, run_id)
    manifest = loaded["manifest"]
    try:
        payload = build_map(loaded["dataset"], run_id)
        write_json(run_dir / "output" / "map.json", payload)
        write_pyvis_html(payload, run_dir / "output" / "map.html")
        manifest.setdefault("stages", {})["map"] = {"status": "completed", "updated_at": datetime.now(timezone.utc).isoformat()}
        manifest["errors"] = [e for e in manifest.get("errors", []) if e.get("stage") != "map"]
        manifest["status"] = "partial" if manifest["errors"] else "completed"
        write_json(run_dir / "run_manifest.json", manifest)
        return {"run_id": run_id, "status": manifest["status"], "map": payload}
    except Exception as exc:
        error = {"stage": "map", "type": type(exc).__name__, "message": str(exc)[:240]}
        manifest.setdefault("stages", {})["map"] = {"status": "failed", "error": error}
        manifest["errors"] = [e for e in manifest.get("errors", []) if e.get("stage") != "map"] + [error]
        manifest["status"] = "partial"
        payload = unavailable_map(run_id, exc)
        write_json(run_dir / "output" / "map.json", payload)
        write_json(run_dir / "run_manifest.json", manifest)
        return {"run_id": run_id, "status": "partial", "map": payload, "error": error}


def _manifest_limitations(dataset: Dataset, *, offline: bool) -> list[str]:
    real_evidence = [item for item in dataset.evidence if not item.is_fixture]
    verified = sum(item.extraction_status == ExtractionStatus.verified for item in real_evidence)
    abstract_only = sum(item.extraction_status == ExtractionStatus.abstract_only for item in real_evidence)
    mode = (
        "本 run 离线读取已落盘的检索缓存与结构化数据，不现场调用 API。"
        if offline
        else "本 run 在金标候选上合并了在线检索结果；结果写入新 run，不回写 data/。"
    )
    return [
        mode,
        "papers.jsonl 是候选主索引；paper_cards.jsonl 是结构化扩展卡片。",
        f"Evidence: verified={verified}, abstract_only={abstract_only}。verified 只表示该摘录与页码已核验，不是整篇全文审阅完毕。",
        "在线新论文只做标题+摘要规则筛选；拿不准标 pending。不会自动生成页码级 Evidence，也不会把 claim-008 改为 supported。",
        "研究地图的边来自 SPECTER2 语义向量余弦相似度，不是引用网络或证据支持关系。",
        "exclude 与 pending 均写入输出；fixture 不计入真实统计。",
        "HTTP 429 / 连接失败保留在 retrieval_runs.jsonl，不改成零结果成功。",
    ]


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid4().hex[:6]}"


def snapshot_dataset(dataset: Dataset, output_dir: Path) -> None:
    write_jsonl(output_dir / "research_questions.jsonl", dataset.research_questions)
    write_jsonl(output_dir / "query_plans.jsonl", dataset.query_plans)
    write_json(output_dir / "search_queries.json", [item.model_dump(mode="json") for item in dataset.queries])
    write_jsonl(output_dir / "papers.jsonl", dataset.papers)
    write_jsonl(output_dir / "paper_cards.jsonl", dataset.paper_cards)
    write_jsonl(output_dir / "screening_log.jsonl", dataset.screening)
    write_jsonl(output_dir / "claims.jsonl", dataset.claims)
    write_jsonl(output_dir / "evidence.jsonl", dataset.evidence)
    write_jsonl(output_dir / "claim_decisions.jsonl", dataset.claim_decisions)
    write_jsonl(output_dir / "falsification.jsonl", dataset.falsification)
    write_jsonl(output_dir / "retrieval_runs.jsonl", dataset.retrieval_runs)
    write_jsonl(output_dir / "source_snapshots.jsonl", dataset.source_snapshots)
    write_jsonl(output_dir / "evidence_spans.jsonl", dataset.evidence_spans)
    write_jsonl(output_dir / "decision_traces.jsonl", dataset.decision_traces)
    write_jsonl(output_dir / "next_actions.jsonl", dataset.next_actions)


def run_pipeline(
    settings: Settings,
    *,
    source: str = "data",
    run_id: str | None = None,
    allow_errors: bool = False,
    question: str | None = None,
    live: bool | None = None,
    constraints: dict | None = None,
    source_run: str | None = None,
    search_bundle=None,
    search_supplement: dict | None = None,
    citation_cache: Path | None = None,
) -> dict:
    from src.research_query import validate_constraints
    constraints = validate_constraints(constraints)
    from src.research_query import validate_search_supplement
    search_supplement = validate_search_supplement(search_supplement)
    citation_only = citation_cache is not None
    if source == "fixture":
        data_dir = settings.fixtures_dir
        offline = True
    else:
        data_dir = settings.data_dir
        offline = settings.offline if live is None else not live

    if run_id in PROTECTED_RUNS:
        run_id = None
    run_id = run_id or new_run_id("run" if offline else "live")

    run_dir = resolve_run_dir(settings.runs_dir, run_id)
    # Reserve the name before writing anything, including logs and caches.
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": run_id, "source": source, "offline": offline,
        "question": question, "data_dir": str(data_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": "cache", "status": "running", "stage": "initializing",
        "stages": {}, "errors": [],
        "constraints": constraints, "parent_run_id": source_run,
        "live": None if offline else {"matched_paper_ids": [], "added_paper_ids": [], "retrieval": []},
    }
    write_json(run_dir / "run_manifest.json", manifest)
    logger = setup_logging(settings.log_level, run_dir / "pipeline.log")
    cache = FileCache(run_dir / "cache")
    dataset = None
    live_report = manifest["live"]

    def stage(name: str, status: str = "running", error: Exception | None = None) -> None:
        manifest["stage"] = name
        item = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
        if error:
            item["error"] = {"stage": name, "type": type(error).__name__, "message": str(error)[:240]}
            manifest["errors"].append(item["error"])
        manifest["stages"][name] = item
        manifest["updated_at"] = item["updated_at"]
        write_json(run_dir / "run_manifest.json", manifest)
        from src.tasks import report_progress
        report_progress(name, status, run_id)

    def checkpoint() -> dict:
        snapshot_dataset(dataset, run_dir / "output")
        stats = dataset_stats(dataset)
        write_json(run_dir / "stats.json", stats)
        write_json(run_dir / "validation_report.json", [issue.model_dump() for issue in dataset.issues])
        manifest.update(stats=stats, live=live_report,
                        limitations=_manifest_limitations(dataset, offline=offline))
        write_json(run_dir / "run_manifest.json", manifest)
        return stats

    try:
        stage("load_data")
        if source_run:
            from src.replay import load_run
            parent = load_run(settings.runs_dir, source_run)
            dataset = parent["dataset"]
            # Carry the user's reading work into supplementary research. These
            # sidecars are independent of the dataset snapshot and were
            # previously omitted when a source_run created a new pipeline run.
            from src.research_workspace import _lock, _portable, _atomic_json
            from src.io_utils import read_json
            source_dir = resolve_run_dir(settings.runs_dir, source_run)
            with _lock(source_dir):
                for filename in ("paper_library.json", "research_workspace.json", "research_context.json"):
                    source_file = source_dir / "output" / filename
                    if source_file.exists():
                        value = _portable(read_json(source_file), source_dir, run_id)
                        if isinstance(value, dict):
                            value["run_id"] = run_id
                        _atomic_json(run_dir / "output" / filename, value)
            from src.conversation import load_conversation, _write_conversation
            if (source_dir / "output/conversation.json").exists():
                history = _portable(load_conversation(settings.runs_dir, source_run), source_dir, run_id)
                history["run_id"] = run_id
                _write_conversation(run_dir / "output/conversation.json", history)
            parent_visible = ({p.paper_id for p in dataset.papers if not p.is_fixture}
                              if parent["manifest"].get("offline", True) else
                              visible_paper_ids(parent["manifest"].get("live") or {}))
        else:
            dataset = load_dataset(data_dir)
        stage("load_data", "completed")
        checkpoint()
        if not offline:
            from src.live_ingest import ingest_live
            stage("retrieval")
            options = {"constraints": constraints} if constraints else {}
            if search_bundle is not None:
                options["search_bundle"] = search_bundle
            if search_supplement:
                options["search_supplement"] = search_supplement
            dataset, live_report = ingest_live(dataset, settings, question=question,
                                               cache=cache, run_dir=run_dir, **options)
            if source_run:
                live_report["parent_visible_paper_ids"] = sorted(parent_visible)
                live_report["matched_paper_ids"] = sorted(parent_visible | visible_paper_ids(live_report))
            checkpoint()
            stage("retrieval", "completed")
        else:
            stage("retrieval", "cached")

        from src.audit_enrichment import enrich_audit
        from src.live_ingest import SCOPE_QUESTION
        audit_stage = "citation_save" if citation_only else "fulltext"
        stage(audit_stage)
        try:
            dataset = enrich_audit(dataset, root=settings.root, run_dir=run_dir,
                                   question=question or SCOPE_QUESTION,
                                   visible_ids=visible_paper_ids(live_report) if live_report else None,
                                   source_dir=resolve_run_dir(settings.runs_dir, source_run) if source_run else None,
                                   citation_cache=citation_cache)
            stage(audit_stage, "completed")
        except Exception as exc:
            # Retrieval remains usable when optional full-text processing fails.
            from src.tasks import TaskCancelled
            if citation_only or isinstance(exc, TaskCancelled):
                raise
            stage(audit_stage, "failed", exc)
            logger.exception("fulltext enrichment failed; preserving retrieved data")
        stats = checkpoint()
        if stats["error_count"] and not allow_errors:
            raise ValueError(f"数据契约校验失败，共 {stats['error_count']} 个错误。详见 {run_dir / 'validation_report.json'}")

        if citation_only:
            map_payload = unavailable_map(run_id, RuntimeError("引文结果已保存，可按需生成包含新增论文的研究地图。"))
            map_payload.update(status="pending", limitations=[])
            write_json(run_dir / "output" / "map.json", map_payload)
            manifest["stages"]["map"] = {"status": "deferred", "updated_at": datetime.now(timezone.utc).isoformat()}
        else:
            stage("map")
            try:
                map_payload = build_map(dataset, run_id)
                write_json(run_dir / "output" / "map.json", map_payload)
                write_pyvis_html(map_payload, run_dir / "output" / "map.html")
                stage("map", "completed")
            except Exception as exc:
                map_payload = unavailable_map(run_id, exc)
                write_json(run_dir / "output" / "map.json", map_payload)
                stage("map", "failed", exc)
                logger.exception("map generation failed; research data remains replayable")
        manifest["status"] = "partial" if manifest["errors"] else "completed"
        manifest["stage"] = "finished"
        write_json(run_dir / "run_manifest.json", manifest)
        return {"run_id": run_id, "run_dir": str(run_dir), "stats": stats,
                "issues": [issue.model_dump() for issue in dataset.issues],
                "offline": offline, "live": live_report,
                "status": manifest["status"], "stages": manifest["stages"], "errors": manifest["errors"]}
    except Exception as exc:
        from src.tasks import TaskCancelled
        status = "cancelled" if isinstance(exc, TaskCancelled) else "failed"
        manifest["status"] = status
        stage(manifest["stage"], status, exc)
        raise


def upgrade_audit(settings: Settings, source_run: str, *, acquire: bool = False,
                  paper_ids: list[str] | None = None) -> dict:
    """Create a new reviewable run, including when the source is protected."""
    from src.audit_enrichment import enrich_audit
    from src.replay import load_run
    from src.live_ingest import SCOPE_QUESTION

    from src.research_workspace import fork_workspace, workspace_papers
    from src.tasks import TaskCancelled, report_progress

    if acquire:
        report_progress("fulltext_prepare", run_id=source_run)
    available = workspace_papers(settings.runs_dir, source_run, paper_ids)
    if paper_ids is not None and not available:
        raise ValueError("请选择论文")
    # Keep reading notes, reviews, conversation and portable files together.
    run_id = fork_workspace(settings.runs_dir, source_run)["run_id"]
    loaded = load_run(settings.runs_dir, run_id)
    manifest = dict(loaded.get("manifest") or {})
    run_dir = resolve_run_dir(settings.runs_dir, run_id)
    manifest.update(run_id=run_id, parent_run_id=source_run, audit_version="v0.2",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    cache_dir="cache", status="running", stage="fulltext", stages={}, errors=[])
    write_json(run_dir / "run_manifest.json", manifest)
    live = manifest.get("live") or {}
    visible_ids = visible_paper_ids(live) if manifest.get("offline") is False else None
    try:
        if acquire:
            report_progress("fulltext_prepare", run_id=run_id)
        dataset = enrich_audit(loaded["dataset"], root=settings.root, run_dir=run_dir,
                              question=manifest.get("question") or SCOPE_QUESTION,
                              visible_ids=visible_ids, acquire=acquire,
                              source_dir=run_dir, acquire_ids=set(available) if paper_ids is not None else None,
                              reuse_from_run=source_run if acquire and paper_ids is not None else None)
        rows = read_json(run_dir / "output" / "fulltext_audit.json").get("documents", [])
        selected = [d for d in rows if d.get("paper_id") in available]
        ready = [d["paper_id"] for d in selected if d.get("status") == "parsed"]
        failed = [d["paper_id"] for d in selected if d.get("status") == "failed"]
        pending = sorted(set(available) - set(ready) - set(failed))
        acquisition_status = ("not_requested" if not acquire else "completed" if len(ready) == len(available)
                              else "partial" if ready else "failed")
        acquisition = {"requested_paper_ids": sorted(available), "download_requested": acquire,
                       "status": acquisition_status, "ready_paper_ids": sorted(ready),
                       "failed_paper_ids": sorted(failed), "pending_paper_ids": pending,
                       "documents": [{**{k: d.get(k) for k in ("paper_id", "status", "error_code", "acquisition")},
                                      "pdf_saved": bool(d.get("response_path"))} for d in selected]}
        manifest["acquisition"] = acquisition
        manifest["stages"]["fulltext"] = {"status": "partial" if acquire and len(ready) < len(available) else "completed"}
        if acquire and len(ready) < len(available):
            manifest["errors"].append({"stage": "fulltext", "type": "AcquisitionIncomplete",
                "message": f"全文获取结果：{len(ready)}/{len(available)} 篇可阅读",
                "paper_ids": sorted(set(available) - set(ready))})
    except Exception as exc:
        error = {"stage": "fulltext", "type": type(exc).__name__, "message": str(exc)[:240]}
        status = "cancelled" if isinstance(exc, TaskCancelled) else "failed"
        manifest.update(status=status, errors=[error])
        manifest["stages"]["fulltext"] = {"status": status, "error": error}
        write_json(run_dir / "run_manifest.json", manifest)
        raise
    stats = dataset_stats(dataset)
    if stats["error_count"]:
        manifest.update(status="failed", stage="validation", stats=stats)
        manifest["errors"].append({"stage": "validation", "type": "ValueError", "message": "增强审计数据未通过校验"})
        write_json(run_dir / "run_manifest.json", manifest)
        raise ValueError("增强审计数据未通过校验")
    snapshot_dataset(dataset, run_dir / "output")
    write_json(run_dir / "stats.json", stats)
    write_json(run_dir / "validation_report.json", [i.model_dump() for i in dataset.issues])
    if acquire and paper_ids is not None:
        # Fulltext changes no title, abstract or map evidence. The fork already
        # contains the prior map with its new run ID.
        map_payload = loaded["map"]
        map_status = map_payload.get("status") if map_payload else "unavailable"
        manifest["stages"]["map"] = {"status": {"pending": "deferred", "unavailable": "unavailable"}.get(map_status, "completed")}
    else:
        try:
            map_payload = build_map(dataset, run_id)
            write_json(run_dir / "output" / "map.json", map_payload)
            write_pyvis_html(map_payload, run_dir / "output" / "map.html")
            manifest["stages"]["map"] = {"status": "completed"}
        except Exception as exc:
            error = {"stage": "map", "type": type(exc).__name__, "message": str(exc)[:240]}
            write_json(run_dir / "output" / "map.json", unavailable_map(run_id, exc))
            manifest["stages"]["map"] = {"status": "failed", "error": error}
            manifest["errors"].append(error)
    manifest.update(stats=stats, status="partial" if manifest["errors"] else "completed", stage="finished")
    write_json(run_dir / "run_manifest.json", manifest)
    return {"run_id": run_id, "parent_run_id": source_run, "stats": stats,
            "status": manifest["status"], "stages": manifest["stages"], "errors": manifest["errors"],
            "acquisition": manifest["acquisition"]}
