from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.config import ROOT, load_settings
from src.io_utils import load_dataset
from src.pipeline import run_pipeline
from src.replay import list_runs, load_run
from src.schema import dataset_stats


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def cmd_doctor(_: argparse.Namespace) -> int:
    settings = load_settings()
    required = [
        settings.data_dir / "search_queries.json",
        settings.data_dir / "papers.jsonl",
        settings.data_dir / "screening_log.jsonl",
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
    settings = load_settings(offline=True)
    source = "fixture" if args.fixture else "data"
    result = run_pipeline(settings, source=source, run_id=args.run_id, allow_errors=args.allow_errors)
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


def cmd_ui(args: argparse.Namespace) -> int:
    settings = load_settings()
    app = ROOT / "src" / "ui" / "app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app), "--"]
    if args.run_id:
        command.extend(["--run-id", args.run_id])
    return subprocess.call(command, cwd=settings.root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="litaudit", description="LitAudit 离线校验、流水线与回放")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查必要文件与数据契约")
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser("validate", help="校验 JSON/JSONL")
    validate.add_argument("--data-dir")
    validate.add_argument("--fixture", action="store_true")
    validate.set_defaults(func=cmd_validate)

    run = sub.add_parser("run", help="离线读取数据并生成 run_id")
    run.add_argument("--offline", action="store_true", default=True, help="离线模式（当前唯一支持的模式）")
    run.add_argument("--fixture", action="store_true", help="使用 data/fixtures，不混入真实统计")
    run.add_argument("--run-id")
    run.add_argument("--allow-errors", action="store_true")
    run.set_defaults(func=cmd_run)

    replay = sub.add_parser("replay", help="回放已落盘的 run")
    replay.add_argument("run_id", nargs="?")
    replay.add_argument("--list", action="store_true")
    replay.set_defaults(func=cmd_replay)

    ui = sub.add_parser("ui", help="打开四屏演示界面")
    ui.add_argument("--run-id")
    ui.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
