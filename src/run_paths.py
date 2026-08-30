from __future__ import annotations

import re
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def resolve_run_dir(runs_dir: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id 只能包含字母、数字、点、下划线和连字符，且不能包含路径分隔符")
    root = runs_dir.resolve()
    target = (root / run_id).resolve()
    if target.parent != root:
        raise ValueError("run_id 必须指向 runs 目录下的直接子目录")
    return target
