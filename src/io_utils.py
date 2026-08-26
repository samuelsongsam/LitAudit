from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.schema import (
    Claim,
    ClaimDecision,
    Dataset,
    Evidence,
    FalsificationHit,
    PaperCard,
    RetrievalRun,
    ScreeningLog,
    SearchQuery,
    ValidationIssue,
    validate_dataset,
)

T = TypeVar("T", bound=BaseModel)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} 第 {line_no} 行不是合法 JSON: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[BaseModel] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized: list[str] = []
    for row in rows:
        if isinstance(row, BaseModel):
            serialized.append(row.model_dump_json())
        else:
            serialized.append(json.dumps(row, ensure_ascii=False, default=str))
    path.write_text("\n".join(serialized) + ("\n" if serialized else ""), encoding="utf-8")


def _parse_rows(model: type[T], rows: list[dict[str, Any]], issues: list[ValidationIssue], label: str) -> list[T]:
    parsed: list[T] = []
    for index, row in enumerate(rows):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            object_id = str(
                row.get("paper_id")
                or row.get("claim_id")
                or row.get("evidence_id")
                or row.get("hit_id")
                or row.get("retrieval_id")
                or row.get("screening_id")
                or index
            )
            issues.append(
                ValidationIssue(
                    level="error",
                    code="schema_error",
                    message=f"{label}[{index}] 校验失败: {exc.errors()[0]['msg']}",
                    object_id=object_id,
                )
            )
    return parsed


def load_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def load_dataset(data_dir: Path) -> Dataset:
    issues: list[ValidationIssue] = []
    queries_path = data_dir / "search_queries.json"
    queries: list[SearchQuery] = []
    if queries_path.exists():
        raw_queries = read_json(queries_path)
        if not isinstance(raw_queries, list):
            issues.append(ValidationIssue(level="error", code="schema_error", message="search_queries.json 必须是数组"))
        else:
            queries = _parse_rows(SearchQuery, raw_queries, issues, "search_queries")
    else:
        issues.append(
            ValidationIssue(level="error", code="missing_file", message=f"缺少 {queries_path.name}", object_id="search_queries.json")
        )

    papers = _parse_rows(PaperCard, load_optional_jsonl(data_dir / "papers.jsonl"), issues, "papers")
    paper_cards = _parse_rows(PaperCard, load_optional_jsonl(data_dir / "paper_cards.jsonl"), issues, "paper_cards")
    screening = _parse_rows(ScreeningLog, load_optional_jsonl(data_dir / "screening_log.jsonl"), issues, "screening_log")
    claims = _parse_rows(Claim, load_optional_jsonl(data_dir / "claims.jsonl"), issues, "claims")
    evidence = _parse_rows(Evidence, load_optional_jsonl(data_dir / "evidence.jsonl"), issues, "evidence")
    claim_decisions = _parse_rows(
        ClaimDecision, load_optional_jsonl(data_dir / "claim_decisions.jsonl"), issues, "claim_decisions"
    )
    falsification = _parse_rows(
        FalsificationHit, load_optional_jsonl(data_dir / "falsification.jsonl"), issues, "falsification"
    )
    retrieval_runs = _parse_rows(
        RetrievalRun, load_optional_jsonl(data_dir / "retrieval_runs.jsonl"), issues, "retrieval_runs"
    )

    dataset = Dataset(
        queries=queries,
        papers=papers,
        paper_cards=paper_cards,
        screening=screening,
        claims=claims,
        evidence=evidence,
        claim_decisions=claim_decisions,
        falsification=falsification,
        retrieval_runs=retrieval_runs,
        issues=issues,
    )
    return validate_dataset(dataset)
