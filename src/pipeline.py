from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.cache import FileCache
from src.config import Settings
from src.io_utils import load_dataset, write_json, write_jsonl
from src.logging_setup import setup_logging
from src.map_builder import build_map
from src.schema import Dataset, dataset_stats


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{stamp}_{uuid4().hex[:6]}"


def snapshot_dataset(dataset: Dataset, output_dir: Path) -> None:
    write_json(output_dir / "search_queries.json", [item.model_dump(mode="json") for item in dataset.queries])
    write_jsonl(output_dir / "papers.jsonl", dataset.papers)
    write_jsonl(output_dir / "screening_log.jsonl", dataset.screening)
    write_jsonl(output_dir / "claims.jsonl", dataset.claims)
    write_jsonl(output_dir / "evidence.jsonl", dataset.evidence)
    write_jsonl(output_dir / "falsification.jsonl", dataset.falsification)


def run_pipeline(
    settings: Settings,
    *,
    source: str = "data",
    run_id: str | None = None,
    allow_errors: bool = False,
) -> dict:
    run_id = run_id or new_run_id()
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(settings.log_level, run_dir / "pipeline.log")

    if source == "fixture":
        data_dir = settings.fixtures_dir
        offline = True
    else:
        data_dir = settings.data_dir
        offline = settings.offline or source == "data"

    if not offline:
        raise RuntimeError("当前版本只允许离线运行。真实检索 API 尚未接入，请使用 --offline 或 --fixture。")

    logger.info("start run_id=%s source=%s data_dir=%s", run_id, source, data_dir)
    cache = FileCache(run_dir / "cache")
    dataset: Dataset = load_dataset(data_dir)
    stats = dataset_stats(dataset)
    error_count = stats["error_count"]
    logger.info("loaded papers=%s pending=%s exclude=%s include=%s errors=%s", stats["paper_count"], stats["decision_counts"]["pending"], stats["decision_counts"]["exclude"], stats["decision_counts"]["include"], error_count)

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
            "offline": True,
            "data_dir": str(data_dir),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cache_dir": str(cache.cache_dir),
            "limitations": [
                "本 run 未调用 arXiv / OpenAlex / Semantic Scholar。",
                "null 的 authors/abstract 被原样保留，未填充默认值。",
                "exclude 与 pending 均写入输出，供 UI 展示。",
                "fixture 记录不计入 stats.json 的真实论文统计。",
            ],
            "stats": stats,
        },
    )
    logger.info("finished run_id=%s output=%s", run_id, output_dir)
    return {"run_id": run_id, "run_dir": str(run_dir), "stats": stats, "issues": [issue.model_dump() for issue in dataset.issues]}
