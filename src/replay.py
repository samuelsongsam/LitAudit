from __future__ import annotations

from pathlib import Path

from src.io_utils import load_dataset, read_json
from src.schema import Dataset


def list_runs(runs_dir: Path) -> list[str]:
    if not runs_dir.exists():
        return []
    dirs = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "run_manifest.json").exists()]
    dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.name for path in dirs]


def load_run(runs_dir: Path, run_id: str) -> dict:
    run_dir = runs_dir / run_id
    if not (run_dir / "run_manifest.json").exists():
        raise FileNotFoundError(f"找不到可回放的 run: {run_id}")
    output_dir = run_dir / "output"
    dataset: Dataset = load_dataset(output_dir)
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "manifest": read_json(run_dir / "run_manifest.json"),
        "stats": read_json(run_dir / "stats.json") if (run_dir / "stats.json").exists() else {},
        "map": read_json(output_dir / "map.json") if (output_dir / "map.json").exists() else {},
        "dataset": dataset,
    }
