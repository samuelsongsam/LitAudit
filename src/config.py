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
    semantic_scholar_api_key: str | None = None
    openalex_mailto: str | None = None
    live_limit: int = 12
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"


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
    env_offline = os.getenv("LITAUDIT_OFFLINE", "0").strip().lower() in {"1", "true", "yes"}
    try:
        live_limit = int(os.getenv("LITAUDIT_LIVE_LIMIT", "12"))
    except ValueError:
        live_limit = 12
    return Settings(
        root=ROOT,
        data_dir=resolved_data,
        fixtures_dir=resolved_fixtures,
        runs_dir=resolved_runs,
        offline=env_offline if offline is None else offline,
        log_level=os.getenv("LITAUDIT_LOG_LEVEL", "INFO"),
        semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY") or None,
        openalex_mailto=os.getenv("OPENALEX_MAILTO") or None,
        live_limit=max(1, live_limit),
        llm_api_key=os.getenv("LITAUDIT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
        llm_base_url=os.getenv("LITAUDIT_LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_model=os.getenv("LITAUDIT_LLM_MODEL", "gpt-4o-mini"),
    )
