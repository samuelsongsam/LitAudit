from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    fixtures_dir: Path
    runs_dir: Path
    offline: bool
    log_level: str


def load_settings(
    *,
    data_dir: str | Path | None = None,
    fixtures_dir: str | Path | None = None,
    runs_dir: str | Path | None = None,
    offline: bool | None = None,
) -> Settings:
    load_dotenv(ROOT / ".env")
    resolved_data = Path(data_dir or os.getenv("LITAUDIT_DATA_DIR", "data"))
    resolved_fixtures = Path(fixtures_dir or os.getenv("LITAUDIT_FIXTURES_DIR", "data/fixtures"))
    resolved_runs = Path(runs_dir or os.getenv("LITAUDIT_RUNS_DIR", "runs"))
    if not resolved_data.is_absolute():
        resolved_data = ROOT / resolved_data
    if not resolved_fixtures.is_absolute():
        resolved_fixtures = ROOT / resolved_fixtures
    if not resolved_runs.is_absolute():
        resolved_runs = ROOT / resolved_runs
    env_offline = os.getenv("LITAUDIT_OFFLINE", "1").strip() not in {"0", "false", "False"}
    return Settings(
        root=ROOT,
        data_dir=resolved_data,
        fixtures_dir=resolved_fixtures,
        runs_dir=resolved_runs,
        offline=env_offline if offline is None else offline,
        log_level=os.getenv("LITAUDIT_LOG_LEVEL", "INFO"),
    )
