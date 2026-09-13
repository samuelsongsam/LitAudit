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


class QueryPlanStatus(str, Enum):
    draft = "draft"
    ready = "ready"
    executed = "executed"


class SnapshotStatus(str, Enum):
    success = "success"
    zero_results = "zero_results"
    partial_failed = "partial_failed"
    all_failed = "all_failed"
    rate_limited = "rate_limited"
    failed = "failed"


class NextActionKind(str, Enum):
    retrieve_more = "retrieve_more"
    acquire_fulltext = "acquire_fulltext"
    verify_evidence = "verify_evidence"
    resolve_conflict = "resolve_conflict"
    human_review = "human_review"
    accept_uncertainty = "accept_uncertainty"


class ActionStatus(str, Enum):
    open = "open"
    completed = "completed"
    dismissed = "dismissed"


class PaperFields(StrictModel):
    task: str | None = None
    method: str | None = None
    data: str | None = None
    metrics: str | None = None
    claims: str | None = None
    limitations: str | None = None


class Locator(StrictModel):
    page: int | None = Field(default=None, ge=1)
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


class ResearchQuestion(StrictModel):
    question_id: str
    text: str
    population_or_object: str | None = None
    method_or_phenomenon: str | None = None
    task_or_outcome: str | None = None
    comparison: str | None = None
    domain_boundary: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    scope_version: str

    @field_validator("question_id", "text", "scope_version")
    @classmethod
    def research_question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ResearchQuestion 必填字符串不能为空")
        return value

    @model_validator(mode="after")
    def valid_year_window(self) -> "ResearchQuestion":
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("ResearchQuestion.start_year 不能晚于 end_year")
        return self


class QueryPlan(StrictModel):
    query_plan_id: str
    question_id: str
    query_ids: list[str]
    subquestions: list[str] = Field(default_factory=list)
    boundary_terms: list[str] = Field(default_factory=list)
    reverse_terms: list[str] = Field(default_factory=list)
    status: QueryPlanStatus
    scope_version: str
    created_at: datetime

    @model_validator(mode="after")
    def ready_plan_requires_queries(self) -> "QueryPlan":
        if self.status in {QueryPlanStatus.ready, QueryPlanStatus.executed} and not self.query_ids:
            raise ValueError("ready/executed QueryPlan 必须包含 query_ids")
        if len(self.query_ids) != len(set(self.query_ids)):
            raise ValueError("QueryPlan.query_ids 不能重复")
        return self


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


class SourceSnapshot(StrictModel):
    snapshot_id: str
    retrieval_id: str
    source: str
    status: SnapshotStatus
    retrieved_at: datetime
    response_path: str | None = None
    content_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_snapshot_result(self) -> "SourceSnapshot":
        if self.status == SnapshotStatus.success and (not self.response_path or not self.content_sha256):
            raise ValueError("成功的 SourceSnapshot 必须包含 response_path 和 content_sha256")
        if self.status in {SnapshotStatus.failed, SnapshotStatus.all_failed, SnapshotStatus.rate_limited}:
            if not self.error_code:
                raise ValueError("失败的 SourceSnapshot 必须包含 error_code")
        return self


class EvidenceSpan(StrictModel):
    span_id: str
    evidence_id: str
    paper_id: str
    snapshot_id: str | None = None
    document_version: str
    snippet_sha256: str
    locator: Locator
    extraction_status: ExtractionStatus
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def verified_span_has_audit_fields(self) -> "EvidenceSpan":
        if self.extraction_status == ExtractionStatus.verified and self.verified_at is None:
            raise ValueError("verified EvidenceSpan 必须包含 verified_at")
        if len(self.snippet_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.snippet_sha256.lower()):
            raise ValueError("EvidenceSpan.snippet_sha256 必须是 64 位 SHA-256 十六进制值")
        return self


class DecisionTrace(StrictModel):
    trace_id: str
    claim_id: str
    evidence_ids: list[str]
    rule_status: ClaimStatus
    model_status: ClaimStatus | None = None
    final_status: ClaimStatus
    conflict_detected: bool = False
    rationale: str
    rule_version: str
    prompt_version: str | None = None
    model_name: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_resolution(self) -> "DecisionTrace":
        if not self.rationale.strip() or not self.rule_version.strip():
            raise ValueError("DecisionTrace 必须包含 rationale 和 rule_version")
        if self.conflict_detected and self.final_status == ClaimStatus.supported:
            raise ValueError("存在冲突的 DecisionTrace 不能输出 supported")
        if self.model_status is not None and self.model_status != self.rule_status:
            if self.final_status not in {ClaimStatus.pending, ClaimStatus.partial}:
                raise ValueError("规则与模型不一致时 final_status 必须为 pending 或 partial")
        return self


class NextAction(StrictModel):
    action_id: str
    kind: NextActionKind
    target_type: str
    target_id: str
    reason: str
    priority: int = Field(ge=0, le=3)
    status: ActionStatus = ActionStatus.open
    created_at: datetime

    @field_validator("target_type")
    @classmethod
    def valid_target_type(cls, value: str) -> str:
        if value not in {"question", "query_plan", "paper", "claim", "evidence", "run"}:
            raise ValueError("NextAction.target_type 不受支持")
        return value


class ValidationIssue(StrictModel):
    level: str
    code: str
    message: str
    object_id: str | None = None


class Dataset(StrictModel):
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    query_plans: list[QueryPlan] = Field(default_factory=list)
    queries: list[SearchQuery] = Field(default_factory=list)
    papers: list[PaperCard] = Field(default_factory=list)
    paper_cards: list[PaperCard] = Field(default_factory=list)
    screening: list[ScreeningLog] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claim_decisions: list[ClaimDecision] = Field(default_factory=list)
    falsification: list[FalsificationHit] = Field(default_factory=list)
    retrieval_runs: list[RetrievalRun] = Field(default_factory=list)
    source_snapshots: list[SourceSnapshot] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    decision_traces: list[DecisionTrace] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
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
    issues.extend(_unique([item.question_id for item in dataset.research_questions], "question_id"))
    issues.extend(_unique([item.query_plan_id for item in dataset.query_plans], "query_plan_id"))
    issues.extend(_unique([q.query_id for q in dataset.queries], "query_id"))
    issues.extend(_unique([p.paper_id for p in dataset.papers], "paper_id"))
    issues.extend(_unique([s.screening_id for s in dataset.screening], "screening_id"))
    issues.extend(_unique([c.claim_id for c in dataset.claims], "claim_id"))
    issues.extend(_unique([e.evidence_id for e in dataset.evidence], "evidence_id"))
    issues.extend(_unique([h.hit_id for h in dataset.falsification], "hit_id"))
    issues.extend(_unique([card.paper_id for card in dataset.paper_cards], "paper_cards.paper_id"))
    issues.extend(_unique([item.claim_id for item in dataset.claim_decisions], "claim_decisions.claim_id"))
    issues.extend(_unique([item.retrieval_id for item in dataset.retrieval_runs], "retrieval_id"))
    issues.extend(_unique([item.snapshot_id for item in dataset.source_snapshots], "snapshot_id"))
    issues.extend(_unique([item.span_id for item in dataset.evidence_spans], "span_id"))
    issues.extend(_unique([item.trace_id for item in dataset.decision_traces], "trace_id"))
    issues.extend(_unique([item.action_id for item in dataset.next_actions], "action_id"))

    questions = {item.question_id: item for item in dataset.research_questions}
    query_ids = {item.query_id for item in dataset.queries}
    papers = {paper.paper_id: paper for paper in dataset.papers}
    claims = {claim.claim_id: claim for claim in dataset.claims}
    evidence_by_id = {item.evidence_id: item for item in dataset.evidence}
    evidence_ids = set(evidence_by_id)
    retrieval_ids = {item.retrieval_id for item in dataset.retrieval_runs}
    snapshots = {item.snapshot_id: item for item in dataset.source_snapshots}

    for plan in dataset.query_plans:
        if plan.question_id not in questions:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_question_fk",
                    message=f"QueryPlan {plan.query_plan_id} 引用了不存在的 question_id {plan.question_id}",
                    object_id=plan.query_plan_id,
                )
            )
        for query_id in plan.query_ids:
            if query_id not in query_ids:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="missing_query_fk",
                        message=f"QueryPlan {plan.query_plan_id} 引用了不存在的 query_id {query_id}",
                        object_id=plan.query_plan_id,
                    )
                )

    for snapshot in dataset.source_snapshots:
        if snapshot.retrieval_id not in retrieval_ids:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_retrieval_fk",
                    message=f"SourceSnapshot {snapshot.snapshot_id} 引用了不存在的 retrieval_id {snapshot.retrieval_id}",
                    object_id=snapshot.snapshot_id,
                )
            )
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

    latest_screening = latest_screening_by_paper(dataset.screening)
    for paper_id, log in latest_screening.items():
        paper = papers.get(paper_id)
        if paper is not None and paper.decision != log.decision:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="paper_screening_mismatch",
                    message=f"论文 {paper_id} 的 decision={paper.decision.value} 与最新筛选记录 decision={log.decision.value} 不一致",
                    object_id=paper_id,
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

    for span in dataset.evidence_spans:
        evidence = evidence_by_id.get(span.evidence_id)
        if evidence is not None:
            from hashlib import sha256
            if span.snippet_sha256 != sha256(evidence.snippet.encode("utf-8")).hexdigest():
                issues.append(ValidationIssue(level="error", code="span_hash_mismatch", message="证据摘录与片段哈希不一致", object_id=span.span_id))
            if span.locator != evidence.locator:
                issues.append(ValidationIssue(level="error", code="span_locator_mismatch", message="证据与片段定位不一致", object_id=span.span_id))
            if span.extraction_status == ExtractionStatus.verified and evidence.extraction_status != ExtractionStatus.verified:
                issues.append(ValidationIssue(level="error", code="span_status_upgrade", message="未核验证据不能升级为已核验片段", object_id=span.span_id))
        if evidence is None:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_evidence_fk",
                    message=f"EvidenceSpan {span.span_id} 引用了不存在的 evidence_id {span.evidence_id}",
                    object_id=span.span_id,
                )
            )
        elif evidence.paper_id != span.paper_id:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="span_evidence_paper_mismatch",
                    message=f"EvidenceSpan {span.span_id} 的 paper_id 与 Evidence {span.evidence_id} 不一致",
                    object_id=span.span_id,
                )
            )
        if span.paper_id not in papers:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_paper_fk",
                    message=f"EvidenceSpan {span.span_id} 引用了不存在的 paper_id {span.paper_id}",
                    object_id=span.span_id,
                )
            )
        if span.snapshot_id is not None and span.snapshot_id not in snapshots:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_snapshot_fk",
                    message=f"EvidenceSpan {span.span_id} 引用了不存在的 snapshot_id {span.snapshot_id}",
                    object_id=span.span_id,
                )
            )

        if span.extraction_status == ExtractionStatus.verified:
            snapshot = snapshots.get(span.snapshot_id)
            if snapshot is None or snapshot.status != SnapshotStatus.success or span.document_version != snapshot.content_sha256:
                issues.append(ValidationIssue(level="error", code="verified_span_without_document", message="已核验片段必须绑定与文档版本哈希一致的成功全文快照", object_id=span.span_id))

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
            elif evidence_by_id[evidence_id].claim_id != decision.claim_id:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="decision_evidence_claim_mismatch",
                        message=f"ClaimDecision {decision.claim_id} 引用的 Evidence {evidence_id} 属于 claim_id {evidence_by_id[evidence_id].claim_id}",
                        object_id=decision.claim_id,
                    )
                )

        # A decision is an auditable projection of the Claim/Evidence graph.
        # Do not allow a supported decision to omit its grounding evidence or
        # to cite only contradictory/context-free evidence.
        if decision.status == ClaimStatus.supported:
            cited = [evidence_by_id[eid] for eid in decision.evidence_ids if eid in evidence_by_id]
            grounding = [
                item
                for item in cited
                if item.can_ground_claim
                and item.verdict in {EvidenceVerdict.supports, EvidenceVerdict.partially_supports}
            ]
            contradictions = [
                item for item in cited if item.can_ground_claim and item.verdict == EvidenceVerdict.contradicts
            ]
            if not grounding:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="supported_decision_without_grounding",
                        message=f"ClaimDecision {decision.claim_id} 标记为 supported，但 evidence_ids 中没有支持性 Evidence",
                        object_id=decision.claim_id,
                    )
                )
            if contradictions:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="supported_decision_with_conflict",
                        message=f"ClaimDecision {decision.claim_id} 引用了 contradict Evidence，不能标记为 supported",
                        object_id=decision.claim_id,
                    )
                )

    for trace in dataset.decision_traces:
        claim = claims.get(trace.claim_id)
        if claim is None:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_claim_fk",
                    message=f"DecisionTrace {trace.trace_id} 引用了不存在的 claim_id {trace.claim_id}",
                    object_id=trace.trace_id,
                )
            )
        elif trace.final_status != claim.status:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="trace_claim_status_mismatch",
                    message=f"DecisionTrace {trace.trace_id} 的 final_status 与 Claim.status 不一致",
                    object_id=trace.trace_id,
                )
            )
        cited = [evidence_by_id[eid] for eid in trace.evidence_ids if eid in evidence_by_id]
        for evidence_id in trace.evidence_ids:
            if evidence_id not in evidence_by_id:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="missing_evidence_fk",
                        message=f"DecisionTrace {trace.trace_id} 引用了不存在的 evidence_id {evidence_id}",
                        object_id=trace.trace_id,
                    )
                )
            elif evidence_by_id[evidence_id].claim_id != trace.claim_id:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="trace_evidence_claim_mismatch",
                        message=f"DecisionTrace {trace.trace_id} 引用了其他 Claim 的 Evidence {evidence_id}",
                        object_id=trace.trace_id,
                    )
                )
        if trace.final_status == ClaimStatus.supported and not any(
            item.can_ground_claim
            and item.verdict in {EvidenceVerdict.supports, EvidenceVerdict.partially_supports}
            for item in cited
        ):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="supported_trace_without_grounding",
                    message=f"DecisionTrace {trace.trace_id} 输出 supported，但没有支持性 Evidence",
                    object_id=trace.trace_id,
                )
            )

    action_targets = {
        "question": set(questions),
        "query_plan": {item.query_plan_id for item in dataset.query_plans},
        "paper": set(papers),
        "claim": set(claims),
        "evidence": evidence_ids,
    }
    for action in dataset.next_actions:
        if action.target_type == "run":
            continue
        if action.target_id not in action_targets.get(action.target_type, set()):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_action_target",
                    message=f"NextAction {action.action_id} 的目标 {action.target_type}:{action.target_id} 不存在",
                    object_id=action.action_id,
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
        "research_question_count": len(dataset.research_questions),
        "query_plan_count": len(dataset.query_plans),
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
        "source_snapshot_count": len(dataset.source_snapshots),
        "evidence_span_count": len(dataset.evidence_spans),
        "decision_trace_count": len(dataset.decision_traces),
        "open_next_action_count": sum(1 for item in dataset.next_actions if item.status == ActionStatus.open),
        "decision_counts": counts,
        "claim_status_counts": claim_status_counts,
        "evidence_status_counts": evidence_status_counts,
        "error_count": sum(1 for issue in dataset.issues if issue.level == "error"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
