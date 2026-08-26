from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperDecision(str, Enum):
    include = "include"
    exclude = "exclude"
    pending = "pending"


class ScreeningStage(str, Enum):
    title_abstract = "title_abstract"
    full_text = "full_text"
    deduplication = "deduplication"


class ClaimSource(str, Enum):
    user_idea = "user_idea"
    paper = "paper"
    derived = "derived"


class ClaimStatus(str, Enum):
    supported = "supported"
    partial = "partial"
    unsupported = "unsupported"
    pending = "pending"


class EvidenceVerdict(str, Enum):
    supports = "supports"
    partially_supports = "partially_supports"
    contradicts = "contradicts"
    context_only = "context_only"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unverified = "unverified"


class ExtractionStatus(str, Enum):
    verified = "verified"
    abstract_only = "abstract_only"
    unverified = "unverified"
    failed = "failed"


class ThreatKind(str, Enum):
    fatal = "fatal"
    overlap = "overlap"
    distinguishable = "distinguishable"


class ThreatLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class HitStatus(str, Enum):
    verified = "verified"
    pending = "pending"
    rejected = "rejected"


class PaperFields(StrictModel):
    task: str | None = None
    method: str | None = None
    data: str | None = None
    metrics: str | None = None
    claims: str | None = None
    limitations: str | None = None


class Locator(StrictModel):
    page: int | None = None
    section: str | None = None
    paragraph: str | None = None
    char_range: str | None = None
    url_anchor: str | None = None

    @model_validator(mode="after")
    def require_one_locator(self) -> "Locator":
        if not any(
            [
                self.page is not None,
                bool(self.section),
                bool(self.paragraph),
                bool(self.char_range),
                bool(self.url_anchor),
            ]
        ):
            raise ValueError("locator 必须至少包含 page/section/paragraph/char_range/url_anchor 之一")
        return self


class SearchQuery(StrictModel):
    query_id: str
    source: str
    query: str
    purpose: str | None = None
    keywords: list[str] | None = None
    date: Date | None = None
    scope_version: str | None = None
    notes: str | None = None


class PaperCard(StrictModel):
    paper_id: str
    title: str | None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi_or_arxiv: str | None = None
    url: str | None = None
    source: str
    abstract: str | None = None
    retrieved_at: Date
    dedup_key: str
    decision: PaperDecision
    reason: str
    fields: PaperFields | None = None
    parse_status: str | None = None
    parse_error: str | None = None

    @field_validator("paper_id", "source", "dedup_key", "reason")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value or not str(value).strip():
            raise ValueError("必填字符串不能为空")
        return value

    @model_validator(mode="after")
    def require_identifier(self) -> "PaperCard":
        if not self.doi_or_arxiv and not self.url:
            raise ValueError("paper 必须至少有 doi_or_arxiv 或 url 之一")
        if not self.reason.strip():
            raise ValueError("reason 不能为空")
        return self

    @property
    def is_fixture(self) -> bool:
        return self.source == "fixture" or self.paper_id.startswith("fixture-")


class ScreeningLog(StrictModel):
    screening_id: str
    paper_id: str
    stage: ScreeningStage
    decision: PaperDecision
    reason_code: str
    reason: str
    checked_fields: list[str]
    reviewer: str
    reviewed_at: Date
    scope_version: str


class Claim(StrictModel):
    claim_id: str
    text: str
    source: ClaimSource
    paper_id: str | None = None
    status: ClaimStatus
    decision_reason: str

    @model_validator(mode="after")
    def paper_source_requires_id(self) -> "Claim":
        if self.source == ClaimSource.paper and not self.paper_id:
            raise ValueError("source=paper 的 Claim 必须有 paper_id")
        if not self.text.strip() or not self.decision_reason.strip():
            raise ValueError("Claim.text 与 decision_reason 不能为空")
        return self

    @property
    def is_fixture(self) -> bool:
        return self.claim_id.startswith("fixture-")


class Evidence(StrictModel):
    evidence_id: str
    claim_id: str
    paper_id: str
    snippet: str
    locator: Locator
    verdict: EvidenceVerdict
    confidence: Confidence
    extraction_status: ExtractionStatus

    @field_validator("snippet")
    @classmethod
    def snippet_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evidence.snippet 不能为空")
        return value

    @property
    def is_fixture(self) -> bool:
        return self.evidence_id.startswith("fixture-")

    @property
    def can_ground_claim(self) -> bool:
        return self.extraction_status in {ExtractionStatus.verified, ExtractionStatus.abstract_only}


class FalsificationHit(StrictModel):
    hit_id: str
    target_claim: str
    paper_id: str
    threat: ThreatKind
    threat_level: ThreatLevel
    snippet: str
    locator: Locator
    reason: str
    status: HitStatus
    reverse_query: str | None = None

    @property
    def is_fixture(self) -> bool:
        return self.hit_id.startswith("fixture-")


class ClaimDecision(StrictModel):
    claim_id: str
    status: ClaimStatus
    evidence_ids: list[str]
    reason: str
    reviewer: str
    reviewed_at: Date
    scope_version: str


class RetrievalRun(StrictModel):
    retrieval_id: str
    query_id: str
    source: str
    request: str
    retrieved_at: Date
    http_status: int | None = None
    status: str
    result_count: int | None = None
    response_path: str | None = None
    notes: str | None = None
    total_count: int | None = None

    @property
    def is_failure(self) -> bool:
        if self.http_status == 429:
            return True
        return self.status not in {"success"}


class ValidationIssue(StrictModel):
    level: str
    code: str
    message: str
    object_id: str | None = None


class Dataset(StrictModel):
    queries: list[SearchQuery] = Field(default_factory=list)
    papers: list[PaperCard] = Field(default_factory=list)
    paper_cards: list[PaperCard] = Field(default_factory=list)
    screening: list[ScreeningLog] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claim_decisions: list[ClaimDecision] = Field(default_factory=list)
    falsification: list[FalsificationHit] = Field(default_factory=list)
    retrieval_runs: list[RetrievalRun] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)

    def real_papers(self) -> list[PaperCard]:
        return [paper for paper in self.papers if not paper.is_fixture]

    def real_claims(self) -> list[Claim]:
        return [claim for claim in self.claims if not claim.is_fixture]

    def card_by_id(self) -> dict[str, PaperCard]:
        return {card.paper_id: card for card in self.paper_cards}


def latest_screening_by_paper(logs: list[ScreeningLog]) -> dict[str, ScreeningLog]:
    latest: dict[str, ScreeningLog] = {}
    for log in logs:
        previous = latest.get(log.paper_id)
        if previous is None or (log.reviewed_at, log.screening_id) > (previous.reviewed_at, previous.screening_id):
            latest[log.paper_id] = log
    return latest


def _unique(items: list[str], label: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            issues.append(
                ValidationIssue(level="error", code="duplicate_id", message=f"重复的 {label}: {item}", object_id=item)
            )
        seen.add(item)
    return issues


def validate_dataset(dataset: Dataset) -> Dataset:
    # Preserve parse-time issues from load_dataset; semantic validation adds to them.
    issues: list[ValidationIssue] = list(dataset.issues)
    issues.extend(_unique([q.query_id for q in dataset.queries], "query_id"))
    issues.extend(_unique([p.paper_id for p in dataset.papers], "paper_id"))
    issues.extend(_unique([s.screening_id for s in dataset.screening], "screening_id"))
    issues.extend(_unique([c.claim_id for c in dataset.claims], "claim_id"))
    issues.extend(_unique([e.evidence_id for e in dataset.evidence], "evidence_id"))
    issues.extend(_unique([h.hit_id for h in dataset.falsification], "hit_id"))
    issues.extend(_unique([card.paper_id for card in dataset.paper_cards], "paper_cards.paper_id"))
    issues.extend(_unique([item.claim_id for item in dataset.claim_decisions], "claim_decisions.claim_id"))
    issues.extend(_unique([item.retrieval_id for item in dataset.retrieval_runs], "retrieval_id"))

    papers = {paper.paper_id: paper for paper in dataset.papers}
    claims = {claim.claim_id: claim for claim in dataset.claims}
    evidence_ids = {item.evidence_id for item in dataset.evidence}
    screening_by_paper: dict[str, list[ScreeningLog]] = {}
    for log in dataset.screening:
        screening_by_paper.setdefault(log.paper_id, []).append(log)
        if log.paper_id not in papers:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_paper_fk",
                    message=f"ScreeningLog {log.screening_id} 引用了不存在的 paper_id {log.paper_id}",
                    object_id=log.screening_id,
                )
            )

    for paper in dataset.papers:
        if paper.paper_id not in screening_by_paper:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_screening",
                    message=f"论文 {paper.paper_id} 没有筛选日志",
                    object_id=paper.paper_id,
                )
            )

    evidence_by_claim: dict[str, list[Evidence]] = {}
    for item in dataset.evidence:
        evidence_by_claim.setdefault(item.claim_id, []).append(item)
        if item.paper_id not in papers:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_paper_fk",
                    message=f"Evidence {item.evidence_id} 引用了不存在的 paper_id {item.paper_id}",
                    object_id=item.evidence_id,
                )
            )
        if item.claim_id not in claims:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_claim_fk",
                    message=f"Evidence {item.evidence_id} 引用了不存在的 claim_id {item.claim_id}",
                    object_id=item.evidence_id,
                )
            )
        if item.extraction_status in {ExtractionStatus.unverified, ExtractionStatus.failed} and item.verdict in {
            EvidenceVerdict.supports,
            EvidenceVerdict.partially_supports,
        }:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="ungrounded_support",
                    message=f"Evidence {item.evidence_id} 在 extraction_status={item.extraction_status.value} 时不能支撑确定结论",
                    object_id=item.evidence_id,
                )
            )

    for claim in dataset.claims:
        if claim.paper_id and claim.paper_id not in papers:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_paper_fk",
                    message=f"Claim {claim.claim_id} 引用了不存在的 paper_id {claim.paper_id}",
                    object_id=claim.claim_id,
                )
            )
        related = evidence_by_claim.get(claim.claim_id, [])
        grounding = [item for item in related if item.can_ground_claim]
        contradictions = [item for item in grounding if item.verdict == EvidenceVerdict.contradicts]
        supports = [
            item
            for item in grounding
            if item.verdict in {EvidenceVerdict.supports, EvidenceVerdict.partially_supports}
        ]
        if claim.status == ClaimStatus.supported:
            if not supports:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="supported_without_evidence",
                        message=f"Claim {claim.claim_id} 状态为 supported，但没有可定位的支持性 Evidence",
                        object_id=claim.claim_id,
                    )
                )
            if contradictions:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="supported_with_conflict",
                        message=f"Claim {claim.claim_id} 存在 contradict 证据，不能保持 supported，应降为 pending",
                        object_id=claim.claim_id,
                    )
                )

    for hit in dataset.falsification:
        if hit.paper_id not in papers:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_paper_fk",
                    message=f"FalsificationHit {hit.hit_id} 引用了不存在的 paper_id {hit.paper_id}",
                    object_id=hit.hit_id,
                )
            )
        if hit.target_claim not in claims:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_claim_fk",
                    message=f"FalsificationHit {hit.hit_id} 引用了不存在的 claim_id {hit.target_claim}",
                    object_id=hit.hit_id,
                )
            )

    for card in dataset.paper_cards:
        if card.paper_id not in papers:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_paper_fk",
                    message=f"PaperCard {card.paper_id} 不在 papers.jsonl 主索引中",
                    object_id=card.paper_id,
                )
            )

    for decision in dataset.claim_decisions:
        claim = claims.get(decision.claim_id)
        if claim is None:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_claim_fk",
                    message=f"ClaimDecision 引用了不存在的 claim_id {decision.claim_id}",
                    object_id=decision.claim_id,
                )
            )
        elif decision.status != claim.status:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="claim_status_mismatch",
                    message=f"ClaimDecision {decision.claim_id} 的 status={decision.status.value} 与 Claim.status={claim.status.value} 不一致",
                    object_id=decision.claim_id,
                )
            )
        for evidence_id in decision.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="missing_evidence_fk",
                        message=f"ClaimDecision {decision.claim_id} 引用了不存在的 evidence_id {evidence_id}",
                        object_id=decision.claim_id,
                    )
                )

    for run in dataset.retrieval_runs:
        if run.http_status == 429 and run.status == "success":
            issues.append(
                ValidationIssue(
                    level="error",
                    code="rate_limit_marked_success",
                    message=f"RetrievalRun {run.retrieval_id} 的 HTTP 429 不能记成 success",
                    object_id=run.retrieval_id,
                )
            )
        if run.is_failure and run.result_count == 0 and run.status == "success":
            issues.append(
                ValidationIssue(
                    level="error",
                    code="failure_marked_zero_result",
                    message=f"RetrievalRun {run.retrieval_id} 把失败写成了零结果成功",
                    object_id=run.retrieval_id,
                )
            )

    dataset.issues = issues
    return dataset


def dataset_stats(dataset: Dataset) -> dict[str, Any]:
    papers = dataset.real_papers()
    counts = {"include": 0, "exclude": 0, "pending": 0}
    for paper in papers:
        counts[paper.decision.value] += 1
    claim_status_counts = {"supported": 0, "partial": 0, "unsupported": 0, "pending": 0}
    for claim in dataset.real_claims():
        claim_status_counts[claim.status.value] += 1
    evidence_status_counts = {"verified": 0, "abstract_only": 0, "unverified": 0, "failed": 0}
    page_locator_count = 0
    for item in dataset.evidence:
        if item.is_fixture:
            continue
        evidence_status_counts[item.extraction_status.value] += 1
        if item.locator.page is not None:
            page_locator_count += 1
    return {
        "query_count": len(dataset.queries),
        "paper_count": len(papers),
        "fixture_paper_count": sum(1 for paper in dataset.papers if paper.is_fixture),
        "paper_card_count": sum(1 for card in dataset.paper_cards if not card.is_fixture),
        "screening_count": len(dataset.screening),
        "claim_count": len(dataset.real_claims()),
        "claim_decision_count": len(dataset.claim_decisions),
        "evidence_count": sum(1 for item in dataset.evidence if not item.is_fixture),
        "verified_evidence_count": evidence_status_counts["verified"],
        "abstract_only_evidence_count": evidence_status_counts["abstract_only"],
        "page_locator_count": page_locator_count,
        "falsification_count": sum(1 for item in dataset.falsification if not item.is_fixture),
        "retrieval_run_count": len(dataset.retrieval_runs),
        "retrieval_failure_count": sum(1 for run in dataset.retrieval_runs if run.is_failure),
        "decision_counts": counts,
        "claim_status_counts": claim_status_counts,
        "evidence_status_counts": evidence_status_counts,
        "error_count": sum(1 for issue in dataset.issues if issue.level == "error"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
