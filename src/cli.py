from __future__ import annotations

import argparse
import json
import sys

from src.ask import ask
from src.config import ROOT, load_settings
from src.eval_metrics import evaluate
from src.io_utils import load_dataset
from src.pipeline import run_pipeline
from src.replay import list_runs, load_run
from src.schema import dataset_stats


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _offline_from_args(args: argparse.Namespace) -> bool | None:
    if getattr(args, "offline", False) and getattr(args, "online", False):
        raise SystemExit("不能同时使用 --offline 和 --online")
    if getattr(args, "offline", False):
        return True
    if getattr(args, "online", False):
        return False
    return None


def cmd_doctor(_: argparse.Namespace) -> int:
    settings = load_settings()
    required = [
        settings.data_dir / "search_queries.json",
        settings.data_dir / "papers.jsonl",
        settings.data_dir / "screening_log.jsonl",
        settings.data_dir / "paper_cards.jsonl",
        settings.data_dir / "claims.jsonl",
        settings.data_dir / "evidence.jsonl",
        settings.data_dir / "claim_decisions.jsonl",
        settings.data_dir / "retrieval_runs.jsonl",
        settings.root / "docs" / "data_contract.md",
        settings.root / "docs" / "research_scope.md",
    ]
    missing = [str(path) for path in required if not path.exists()]
    dataset = load_dataset(settings.data_dir) if not missing else None
    _print(
        {
            "ok": not missing and dataset is not None and dataset_stats(dataset)["error_count"] == 0,
            "python": sys.version.split()[0],
            "root": str(settings.root),
            "missing_files": missing,
            "stats": dataset_stats(dataset) if dataset is not None else None,
        }
    )
    ok = not missing and dataset is not None and dataset_stats(dataset)["error_count"] == 0
    return 0 if ok else 1


def cmd_validate(args: argparse.Namespace) -> int:
    settings = load_settings(data_dir=args.data_dir)
    data_dir = settings.fixtures_dir if args.fixture else settings.data_dir
    dataset = load_dataset(data_dir)
    stats = dataset_stats(dataset)
    _print(
        {
            "data_dir": str(data_dir),
            "stats": stats,
            "issues": [issue.model_dump() for issue in dataset.issues],
        }
    )
    return 1 if stats["error_count"] else 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(offline=_offline_from_args(args))
    source = "fixture" if args.fixture else "data"
    result = run_pipeline(
        settings,
        source=source,
        run_id=args.run_id,
        allow_errors=args.allow_errors,
        question=args.question,
    )
    _print(result)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.list:
        _print({"runs": list_runs(settings.runs_dir)})
        return 0
    if not args.run_id:
        raise SystemExit("请提供 run_id，或使用 --list")
    payload = load_run(settings.runs_dir, args.run_id)
    payload["dataset"] = dataset_stats(payload["dataset"])
    _print(payload)
    return 0


def cmd_evaluate(_: argparse.Namespace) -> int:
    _print(evaluate(ROOT))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    settings = load_settings(offline=_offline_from_args(args))
    if settings.offline:
        dataset = load_dataset(settings.data_dir)
        _print(ask(dataset, args.question, limit=args.limit))
        return 0
    result = run_pipeline(settings, source="data", question=args.question)
    dataset = load_run(settings.runs_dir, result["run_id"])["dataset"]
    payload = ask(dataset, args.question, limit=args.limit)
    payload["run_id"] = result["run_id"]
    payload["live"] = result.get("live")
    payload["mode"] = "live_retrieve_then_local_overlap"
    _print(payload)
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from src.ui.server import serve_ui

    return serve_ui(run_id=args.run_id, port=args.port, open_browser=not args.no_browser)


def _add_online_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--offline", action="store_true", help="只读本地金标/快照，不调用检索 API")
    parser.add_argument("--online", action="store_true", help="调用 arXiv / OpenAlex / Semantic Scholar")


def cmd_audit(args: argparse.Namespace) -> int:
    from src.pipeline import upgrade_audit
    _print(upgrade_audit(load_settings(), args.run_id, acquire=args.acquire))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="litaudit", description="LitAudit 在线检索、离线回放与勘验工作台")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查必要文件与数据契约")
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser("validate", help="校验 JSON/JSONL")
    validate.add_argument("--data-dir")
    validate.add_argument("--fixture", action="store_true")
    validate.set_defaults(func=cmd_validate)

    audit = sub.add_parser("audit", help="创建增强审计快照，不修改原 run")
    audit.add_argument("run_id")
    audit.add_argument("--acquire", action="store_true", help="尝试下载最多 5 篇 arXiv 全文")
    audit.set_defaults(func=cmd_audit)

    run = sub.add_parser("run", help="运行流水线；默认在线检索，--offline 只快照金标")
    _add_online_flags(run)
    run.add_argument("--fixture", action="store_true", help="使用 data/fixtures，不混入真实统计")
    run.add_argument("--run-id")
    run.add_argument("--question", help="科研问题或 idea，在线检索时写入检索式")
    run.add_argument("--allow-errors", action="store_true")
    run.set_defaults(func=cmd_run)

    replay = sub.add_parser("replay", help="回放已落盘的 run")
    replay.add_argument("run_id", nargs="?")
    replay.add_argument("--list", action="store_true")
    replay.set_defaults(func=cmd_replay)

    eval_cmd = sub.add_parser("evaluate", help="计算仓库覆盖率与无检索可追溯性对照")
    eval_cmd.set_defaults(func=cmd_evaluate)

    ask_cmd = sub.add_parser("ask", help="检索问题：默认仅本地；--online 先在线扩候选再匹配")
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--limit", type=int, default=5)
    _add_online_flags(ask_cmd)
    ask_cmd.set_defaults(func=cmd_ask)

    ui = sub.add_parser("ui", help="打开勘验工作台")
    ui.add_argument("--run-id")
    ui.add_argument("--port", type=int, default=8787)
    ui.add_argument("--no-browser", action="store_true")
    ui.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
