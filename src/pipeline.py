from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.cache import FileCache
from src.config import Settings
from src.io_utils import load_dataset, write_json, write_jsonl
from src.logging_setup import setup_logging
from src.map_builder import build_map
from src.run_paths import resolve_run_dir
from src.schema import Dataset, ExtractionStatus, dataset_stats

PROTECTED_RUNS = {"phase2-real", "demo"}


def _manifest_limitations(dataset: Dataset, *, offline: bool) -> list[str]:
    real_evidence = [item for item in dataset.evidence if not item.is_fixture]
    verified = sum(item.extraction_status == ExtractionStatus.verified for item in real_evidence)
    abstract_only = sum(item.extraction_status == ExtractionStatus.abstract_only for item in real_evidence)
    mode = (
        "本 run 离线读取已落盘的检索缓存与结构化数据，不现场调用 API。"
        if offline
        else "本 run 在金标候选上合并了 arXiv / OpenAlex / Semantic Scholar 在线检索；结果写入新 run，不回写 data/。"
    )
    return [
        mode,
        "papers.jsonl 是候选主索引；paper_cards.jsonl 是结构化扩展卡片。",
        f"Evidence: verified={verified}, abstract_only={abstract_only}。verified 只表示该摘录与页码已核验，不是整篇全文审阅完毕。",
        "在线新论文只做标题+摘要规则筛选；拿不准标 pending。不会自动生成页码级 Evidence，也不会把 claim-008 改为 supported。",
        "研究地图的边来自论断证据冲突和反证据命中，不是引用网络。",
        "exclude 与 pending 均写入输出；fixture 不计入真实统计。",
        "HTTP 429 / 连接失败保留在 retrieval_runs.jsonl，不改成零结果成功。",
    ]


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid4().hex[:6]}"


def snapshot_dataset(dataset: Dataset, output_dir: Path) -> None:
    write_json(output_dir / "search_queries.json", [item.model_dump(mode="json") for item in dataset.queries])
    write_jsonl(output_dir / "papers.jsonl", dataset.papers)
    write_jsonl(output_dir / "paper_cards.jsonl", dataset.paper_cards)
    write_jsonl(output_dir / "screening_log.jsonl", dataset.screening)
    write_jsonl(output_dir / "claims.jsonl", dataset.claims)
    write_jsonl(output_dir / "evidence.jsonl", dataset.evidence)
    write_jsonl(output_dir / "claim_decisions.jsonl", dataset.claim_decisions)
    write_jsonl(output_dir / "falsification.jsonl", dataset.falsification)
    write_jsonl(output_dir / "retrieval_runs.jsonl", dataset.retrieval_runs)


def run_pipeline(
    settings: Settings,
    *,
    source: str = "data",
    run_id: str | None = None,
    allow_errors: bool = False,
    question: str | None = None,
    live: bool | None = None,
) -> dict:
    if source == "fixture":
        data_dir = settings.fixtures_dir
        offline = True
    else:
        data_dir = settings.data_dir
        offline = settings.offline if live is None else not live

    if not offline:
        if run_id in PROTECTED_RUNS:
            run_id = None
        run_id = run_id or new_run_id("live")
    else:
        run_id = run_id or new_run_id("run")

    run_dir = resolve_run_dir(settings.runs_dir, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(settings.log_level, run_dir / "pipeline.log")
    logger.info(
        "start run_id=%s source=%s offline=%s data_dir=%s question=%s",
        run_id,
        source,
        offline,
        data_dir,
        (question or "")[:80],
    )
    cache = FileCache(run_dir / "cache")
    dataset: Dataset = load_dataset(data_dir)
    live_report = None
    if not offline:
        from src.live_ingest import ingest_live

        dataset, live_report = ingest_live(
            dataset,
            settings,
            question=question,
            cache=cache,
            run_dir=run_dir,
        )
        logger.info(
            "live ingest added=%s skipped_dup=%s failures=%s",
            live_report.get("added_paper_ids"),
            live_report.get("skipped_duplicates"),
            [item for item in live_report.get("retrieval", []) if item.get("status") != "success"],
        )

    stats = dataset_stats(dataset)
    error_count = stats["error_count"]
    logger.info(
        "loaded papers=%s pending=%s exclude=%s include=%s errors=%s",
        stats["paper_count"],
        stats["decision_counts"]["pending"],
        stats["decision_counts"]["exclude"],
        stats["decision_counts"]["include"],
        error_count,
    )

    if error_count and not allow_errors:
        write_json(run_dir / "validation_report.json", [issue.model_dump() for issue in dataset.issues])
        raise ValueError(f"数据契约校验失败，共 {error_count} 个错误。详见 {run_dir / 'validation_report.json'}")

    output_dir = run_dir / "output"
    snapshot_dataset(dataset, output_dir)
    map_payload = build_map(dataset, run_id)
    write_json(output_dir / "map.json", map_payload)
    write_json(run_dir / "validation_report.json", [issue.model_dump() for issue in dataset.issues])
    write_json(run_dir / "stats.json", stats)
    write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": run_id,
            "source": source,
            "offline": offline,
            "question": question,
            "data_dir": str(data_dir),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cache_dir": str(cache.cache_dir),
            "limitations": _manifest_limitations(dataset, offline=offline),
            "stats": stats,
            "live": live_report,
        },
    )
    logger.info("finished run_id=%s output=%s", run_id, output_dir)
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "stats": stats,
        "issues": [issue.model_dump() for issue in dataset.issues],
        "offline": offline,
        "live": live_report,
    }
