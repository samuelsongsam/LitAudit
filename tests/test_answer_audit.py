from src.answer_audit import audit_answer_statements


def _payload(status="supported", verdict="supports", extraction_status="verified"):
    return {
        "claims": [{"claim_id": "claim-001", "status": status, "text": "方法在该评测上提升了可追溯性。"}],
        "evidence": [
            {
                "evidence_id": "evidence-001",
                "claim_id": "claim-001",
                "paper_id": "paper-001",
                "verdict": verdict,
                "extraction_status": extraction_status,
                "locator": {"page": 3},
            }
        ],
    }


def test_verified_statement_requires_valid_claim_evidence_binding():
    result = audit_answer_statements(
        _payload(),
        [
            {
                "text": "该方法在论文报告的评测上提升了可追溯性。",
                "claim_id": "claim-001",
                "evidence_ids": ["evidence-001"],
                "certainty": "verified",
            }
        ],
    )
    assert result["ok"] is True
    assert "提升了可追溯性" in result["answer"]
    assert result["citations"][0]["claim_id"] == "claim-001"


def test_pending_claim_cannot_be_rendered_as_verified_fact():
    result = audit_answer_statements(
        _payload(status="pending"),
        [
            {
                "text": "该方法已经被证明有效。",
                "claim_id": "claim-001",
                "evidence_ids": ["evidence-001"],
                "certainty": "verified",
            }
        ],
    )
    assert result["ok"] is False
    assert any("definite_claim_not_supported" in error for error in result["errors"])
    assert result["answer"] == ""


def test_uncertain_statement_may_explain_pending_claim_without_evidence():
    payload = _payload(status="pending")
    payload["evidence"] = []
    result = audit_answer_statements(
        payload,
        [
            {
                "text": "当前证据不足，仍需获取全文核验。",
                "claim_id": "claim-001",
                "evidence_ids": [],
                "certainty": "uncertain",
            }
        ],
    )
    assert result["ok"] is True


def test_evidence_from_another_claim_is_rejected():
    payload = _payload()
    payload["evidence"][0]["claim_id"] = "claim-002"
    result = audit_answer_statements(
        payload,
        [
            {
                "text": "错误绑定。",
                "claim_id": "claim-001",
                "evidence_ids": ["evidence-001"],
                "certainty": "verified",
            }
        ],
    )
    assert result["ok"] is False
    assert any("evidence_claim_mismatch" in error for error in result["errors"])


def test_abstract_only_evidence_cannot_be_called_verified():
    result = audit_answer_statements(
        _payload(extraction_status="abstract_only"),
        [
            {
                "text": "全文已经核验证明该方法有效。",
                "claim_id": "claim-001",
                "evidence_ids": ["evidence-001"],
                "certainty": "verified",
            }
        ],
    )
    assert result["ok"] is False
    assert any("definite_without_grounding" in error for error in result["errors"])
