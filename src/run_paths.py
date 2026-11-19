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


def as_run_relative(run_dir: Path, path: Path) -> str:
    """Persist artifacts independently of the machine or extraction directory."""
    root = run_dir.resolve()
    target = path.resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("运行文件必须位于当前 run 目录内") from exc


def resolve_run_file(run_dir: Path, stored_path: str | Path) -> Path:
    """Read only files inside a run, including relocated historical snapshots.

    Old releases stored absolute Windows paths. Their ``runs/<id>/cache``
    suffix can be mapped to this run without accessing the old machine path.
    Arbitrary outside paths and traversal are never read.
    """
    root = run_dir.resolve()
    value = str(stored_path or "").strip().replace("\\", "/")
    parts = value.split("/")
    if not value or any(part in {"..", "."} for part in parts):
        raise ValueError("运行文件路径无效")
    absolute = value.startswith("/") or bool(re.match(r"^[A-Za-z]:/", value))
    candidates: list[Path] = []
    if not absolute:
        candidates.append(root / value)
    else:
        # An absolute path is accepted directly only if it already is inside
        # this run. Do not probe arbitrary external paths for existence.
        native = Path(value).resolve()
        if native.is_relative_to(root):
            candidates.append(native)
        for i, part in enumerate(parts):
            historical_run = (
                part == "runs" and i + 3 < len(parts)
                and RUN_ID_PATTERN.fullmatch(parts[i + 1])
                and parts[i + 2] == "cache"
            )
            matching_run = part == root.name and i + 2 < len(parts) and parts[i + 1] == "cache"
            if historical_run:
                candidates.append(root.joinpath(*parts[i + 2:]))
            elif matching_run:
                candidates.append(root.joinpath(*parts[i + 1:]))
    for candidate in candidates:
        target = candidate.resolve()
        if not target.is_relative_to(root):
            raise ValueError("运行文件路径超出当前 run")
        if target.is_file():
            return target
    if candidates:
        raise FileNotFoundError("当前 run 中找不到对应文件")
    raise ValueError("运行文件路径不属于当前 run")
