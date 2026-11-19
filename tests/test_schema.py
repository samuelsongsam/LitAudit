from src.schema import (
    Claim,
    ClaimDecision,
    ClaimSource,
    ClaimStatus,
    Dataset,
    DecisionTrace,
    Evidence,
    EvidenceSpan,
    EvidenceVerdict,
    ExtractionStatus,
    Locator,
    QueryPlan,
    ResearchQuestion,
    PaperCard,
    PaperDecision,
    RetrievalRun,
    SourceSnapshot,
    ScreeningLog,
    ScreeningStage,
    validate_dataset,
)
from src.io_utils import load_dataset


def _paper(**kwargs):
    payload = {
        "paper_id": "paper-001",
        "title": "Example",
        "authors": None,
        "year": 2023,
        "venue": "arXiv preprint",
        "doi_or_arxiv": "arXiv:2312.07559",
        "url": "https://arxiv.org/abs/2312.07559",
        "source": "arxiv",
        "abstract": None,
        "retrieved_at": "2026-08-22",
        "dedup_key": "arxiv:2312.07559",
        "decision": "pending",
        "reason": "摘要未核验，保持 pending。",
    }
    payload.update(kwargs)
    return PaperCard.model_validate(payload)


def test_null_authors_and_abstract_are_preserved():
    paper = _paper()
    assert paper.authors is None
    assert paper.abstract is None
    dumped = paper.model_dump()
    assert dumped["authors"] is None
    assert dumped["abstract"] is None


def test_locator_accepts_section_only():
    locator = Locator.model_validate({"section": "abstract", "page": None})
    assert locator.section == "abstract"


def test_locator_requires_one_field():
    try:
        Locator.model_validate({})
    except Exception as exc:
        assert "locator" in str(exc)
    else:
        raise AssertionError("empty locator should fail")


def test_supported_claim_without_evidence_is_error():
    dataset = Dataset(
        papers=[_paper()],
        screening=[
            ScreeningLog.model_validate(
                {
                    "screening_id": "screen-001",
                    "paper_id": "paper-001",
                    "stage": ScreeningStage.title_abstract,
                    "decision": PaperDecision.pending,
                    "reason_code": "metadata_unverified",
                    "reason": "无摘要",
                    "checked_fields": ["title"],
                    "reviewer": "test",
                    "reviewed_at": "2026-08-22",
                    "scope_version": "v0.1",
                }
            )
        ],
        claims=[
            Claim.model_validate(
                {
                    "claim_id": "claim-001",
                    "text": "检索一定提高可追溯性。",
                    "source": ClaimSource.derived,
                    "status": ClaimStatus.supported,
                    "decision_reason": "错误地没有证据却标成 supported",
                }
            )
        ],
    )
    dataset = validate_dataset(dataset)
    assert any(issue.code == "supported_without_evidence" for issue in dataset.issues)


def test_duplicate_paper_id_is_error():
    dataset = Dataset(papers=[_paper(), _paper()])
    dataset = validate_dataset(dataset)
    assert any(issue.code == "duplicate_id" for issue in dataset.issues)


def test_evidence_can_use_url_anchor():
    evidence = Evidence.model_validate(
        {
            "evidence_id": "ev-001",
            "claim_id": "claim-001",
            "paper_id": "paper-001",
            "snippet": "quoted sentence",
            "locator": {"url_anchor": "https://arxiv.org/abs/2312.07559#abstract"},
            "verdict": EvidenceVerdict.context_only,
            "confidence": "unverified",
            "extraction_status": ExtractionStatus.abstract_only,
        }
    )
    assert evidence.locator.url_anchor.endswith("#abstract")


def test_load_dataset_preserves_parse_errors(tmp_path):
    (tmp_path / "search_queries.json").write_text("[]", encoding="utf-8")
    (tmp_path / "papers.jsonl").write_text(
        '{"paper_id":"bad","title":"Missing source"}\n', encoding="utf-8"
    )
    dataset = load_dataset(tmp_path)
    assert dataset.issues
    assert any(issue.code == "schema_error" for issue in dataset.issues)


def test_claim_decision_must_match_claim_status():
    dataset = Dataset(
        papers=[_paper()],
        screening=[
            ScreeningLog.model_validate(
                {
                    "screening_id": "screen-001",
                    "paper_id": "paper-001",
                    "stage": ScreeningStage.title_abstract,
                    "decision": PaperDecision.pending,
                    "reason_code": "metadata_unverified",
                    "reason": "无摘要",
                    "checked_fields": ["title"],
                    "reviewer": "test",
                    "reviewed_at": "2026-08-22",
                    "scope_version": "v0.1",
                }
            )
        ],
        claims=[
            Claim.model_validate(
                {
                    "claim_id": "claim-001",
                    "text": "待证论断",
                    "source": ClaimSource.derived,
                    "status": ClaimStatus.pending,
                    "decision_reason": "还没有证据",
                }
            )
        ],
        claim_decisions=[
            ClaimDecision.model_validate(
                {
                    "claim_id": "claim-001",
                    "status": "supported",
                    "evidence_ids": [],
                    "reason": "错误地把 pending 写成 supported",
                    "reviewer": "test",
                    "reviewed_at": "2026-08-26",
                    "scope_version": "v0.1",
                }
            )
        ],
    )
    dataset = validate_dataset(dataset)
    assert any(issue.code == "claim_status_mismatch" for issue in dataset.issues)


def test_supported_decision_requires_supporting_evidence():
    dataset = Dataset(
        papers=[_paper()],
        claims=[
            Claim.model_validate(
                {
                    "claim_id": "claim-001",
                    "text": "该方法有效。",
                    "source": ClaimSource.derived,
                    "status": ClaimStatus.supported,
                    "decision_reason": "有证据。",
                }
            )
        ],
        claim_decisions=[
            ClaimDecision.model_validate(
                {
                    "claim_id": "claim-001",
                    "status": ClaimStatus.supported,
                    "evidence_ids": [],
                    "reason": "错误地省略证据。",
                    "reviewer": "test",
                    "reviewed_at": "2026-08-26",
                    "scope_version": "v0.1",
                }
            )
        ],
    )
    dataset = validate_dataset(dataset)
    assert any(issue.code == "supported_decision_without_grounding" for issue in dataset.issues)


def test_supported_decision_cannot_cite_contradicting_evidence():
    dataset = Dataset(
        papers=[_paper()],
        claims=[
            Claim.model_validate(
                {
                    "claim_id": "claim-001",
                    "text": "该方法有效。",
                    "source": ClaimSource.derived,
                    "status": ClaimStatus.supported,
                    "decision_reason": "错误地忽略反证。",
                }
            )
        ],
        evidence=[
            Evidence.model_validate(
                {
                    "evidence_id": "ev-001",
                    "claim_id": "claim-001",
                    "paper_id": "paper-001",
                    "snippet": "结果相反。",
                    "locator": {"page": 2},
                    "verdict": EvidenceVerdict.contradicts,
                    "confidence": "high",
                    "extraction_status": ExtractionStatus.verified,
                }
            )
        ],
        claim_decisions=[
            ClaimDecision.model_validate(
                {
                    "claim_id": "claim-001",
                    "status": ClaimStatus.supported,
                    "evidence_ids": ["ev-001"],
                    "reason": "错误地把反证当支持。",
                    "reviewer": "test",
                    "reviewed_at": "2026-08-26",
                    "scope_version": "v0.1",
                }
            )
        ],
    )
    dataset = validate_dataset(dataset)
    assert any(issue.code == "supported_decision_without_grounding" for issue in dataset.issues)
    assert any(issue.code == "supported_decision_with_conflict" for issue in dataset.issues)


def test_rate_limit_cannot_be_marked_success():
    run = RetrievalRun.model_validate(
        {
            "retrieval_id": "retrieval-x",
            "query_id": "q-003",
            "source": "semantic_scholar",
            "request": "https://example.invalid",
            "retrieved_at": "2026-08-26",
            "http_status": 429,
            "status": "rate_limited",
            "result_count": None,
            "response_path": None,
            "notes": "限流",
        }
    )
    assert run.is_failure is True


def test_query_plan_references_existing_question_and_queries():
    question = ResearchQuestion.model_validate(
        {
            "question_id": "rq-001",
            "text": "RAG 是否改善科学问答可追溯性？",
            "scope_version": "v0.2",
            "start_year": 2019,
            "end_year": 2026,
        }
    )
    plan = QueryPlan.model_validate(
        {
            "query_plan_id": "qp-001",
            "question_id": "rq-001",
            "query_ids": ["q-missing"],
            "status": "ready",
            "scope_version": "v0.2",
            "created_at": "2026-09-10T10:00:00+08:00",
        }
    )
    dataset = validate_dataset(Dataset(research_questions=[question], query_plans=[plan]))
    assert any(issue.code == "missing_query_fk" for issue in dataset.issues)


def test_success_snapshot_requires_hash_and_path():
    try:
        SourceSnapshot.model_validate(
            {
                "snapshot_id": "snapshot-001",
                "retrieval_id": "retrieval-001",
                "source": "arxiv",
                "status": "success",
                "retrieved_at": "2026-09-10T10:00:00+08:00",
            }
        )
    except Exception as exc:
        assert "response_path" in str(exc)
    else:
        raise AssertionError("successful snapshot without audit fields should fail")


def test_verified_evidence_span_requires_verification_time():
    try:
        EvidenceSpan.model_validate(
            {
                "span_id": "span-001",
                "evidence_id": "ev-001",
                "paper_id": "paper-001",
                "document_version": "sha256:document",
                "snippet_sha256": "0" * 64,
                "locator": {"page": 1},
                "extraction_status": "verified",
            }
        )
    except Exception as exc:
        assert "verified_at" in str(exc)
    else:
        raise AssertionError("verified span without verified_at should fail")


def test_decision_trace_disagreement_must_remain_uncertain():
    try:
        DecisionTrace.model_validate(
            {
                "trace_id": "trace-001",
                "claim_id": "claim-001",
                "evidence_ids": ["ev-001"],
                "rule_status": "unsupported",
                "model_status": "supported",
                "final_status": "supported",
                "rationale": "模型与规则冲突。",
                "rule_version": "rules-v0.2",
                "created_at": "2026-09-10T10:00:00+08:00",
            }
        )
    except Exception as exc:
        assert "pending" in str(exc) or "partial" in str(exc)
    else:
        raise AssertionError("rule/model disagreement must not resolve to supported")
