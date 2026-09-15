from __future__ import annotations

from src.run_scope import visible_paper_ids

from typing import Any


DEFINITE = {"verified", "qualified"}
GROUNDING_VERDICTS = {"supports", "partially_supports"}
GROUNDING_EXTRACTION = {"verified", "abstract_only"}


def scoped_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Use the same run boundary for generation, auditing and presentation."""
    live = payload.get("live")
    if payload.get("offline", True) or not live:
        return payload
    ids = visible_paper_ids(live)
    evidence = [e for e in payload.get("evidence", []) if e.get("paper_id") in ids]
    claim_ids = {e.get("claim_id") for e in evidence}
    claims = [c for c in payload.get("claims", []) if c.get("paper_id") in ids or c.get("claim_id") in claim_ids or c.get("text") == payload.get("question")]
    return {**payload, "papers": [p for p in payload.get("papers", []) if p.get("paper_id") in ids],
            "claims": claims, "evidence": evidence,
            "falsification": [f for f in payload.get("falsification", []) if f.get("paper_id") in ids]}


def audit_answer_statements(payload: dict[str, Any], statements: object) -> dict[str, Any]:
    """Validate sentence-level Claim/Evidence bindings before prose is shown."""
    if not isinstance(statements, list) or not statements:
        return {"ok": False, "errors": ["answer_statements_missing"], "answer": "", "citations": []}

    payload = scoped_payload(payload)
    claims = {item.get("claim_id"): item for item in payload.get("claims", []) if item.get("claim_id")}
    evidence = {item.get("evidence_id"): item for item in payload.get("evidence", []) if item.get("evidence_id")}
    errors: list[str] = []
    accepted: list[str] = []
    citations: list[dict[str, Any]] = []

    for index, item in enumerate(statements):
        prefix = f"statement[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}:not_object")
            continue
        text = str(item.get("text") or "").strip()
        claim_id = str(item.get("claim_id") or "").strip()
        certainty = str(item.get("certainty") or "").strip()
        evidence_ids = item.get("evidence_ids") or []
        if not text:
            errors.append(f"{prefix}:empty_text")
        if certainty not in {"verified", "qualified", "uncertain"}:
            errors.append(f"{prefix}:invalid_certainty")
        claim = claims.get(claim_id)
        if claim is None:
            errors.append(f"{prefix}:unknown_claim")
            continue
        if not isinstance(evidence_ids, list) or any(not isinstance(value, str) for value in evidence_ids):
            errors.append(f"{prefix}:invalid_evidence_ids")
            continue

        cited = []
        for evidence_id in evidence_ids:
            row = evidence.get(evidence_id)
            if row is None:
                errors.append(f"{prefix}:unknown_evidence:{evidence_id}")
                continue
            if row.get("claim_id") != claim_id:
                errors.append(f"{prefix}:evidence_claim_mismatch:{evidence_id}")
                continue
            cited.append(row)

        if certainty in DEFINITE:
            allowed_claim_statuses = {"supported"} if certainty == "verified" else {"supported", "partial"}
            allowed_extraction = {"verified"} if certainty == "verified" else GROUNDING_EXTRACTION
            if claim.get("status") not in allowed_claim_statuses:
                errors.append(f"{prefix}:definite_claim_not_supported")
            grounding = [
                row
                for row in cited
                if row.get("verdict") in GROUNDING_VERDICTS
                and row.get("extraction_status") in allowed_extraction
                and row.get("locator")
            ]
            if not grounding:
                errors.append(f"{prefix}:definite_without_grounding")
            if any(row.get("verdict") == "contradicts" and row.get("claim_id") == claim_id for row in evidence.values()):
                errors.append(f"{prefix}:definite_with_conflict")
            if certainty == "verified" and payload.get("evidence_spans"):
                spans = {s.get("evidence_id"): s for s in payload["evidence_spans"]}
                if not any(spans.get(row.get("evidence_id"), {}).get("extraction_status") == "verified" for row in grounding):
                    errors.append(f"{prefix}:verified_without_verified_span")
        # IDs validate provenance, not the meaning of arbitrary generated prose.
        # Render the stored claim and a server-owned qualification instead.
        claim_text = str(claim.get("text") or "").strip()
        if not claim_text:
            errors.append(f"{prefix}:empty_claim_text")
        if certainty == "uncertain":
            rendered = f"待核验论断 [{claim_id}]：\n「{claim_text}」\n本条仅列出待核验内容，不作确定结论。"
        elif certainty == "qualified":
            rendered = f"有限支持 [{claim_id}]：\n「{claim_text}」\n仅在所引证据范围内成立，不应扩展为无条件结论。"
        else:
            rendered = f"已有证据支持的论断 [{claim_id}]：\n「{claim_text}」\n定位核验不代表整篇全文审阅。"
        accepted.append(rendered)
        citations.append({"statement": index, "claim_id": claim_id, "evidence_ids": evidence_ids, "certainty": certainty})

    return {
        "ok": not errors,
        "errors": errors,
        "answer": "\n\n".join(accepted) if not errors else "",
        "citations": citations,
    }


def audit_overview_statements(payload: dict[str, Any], statements: object) -> dict[str, Any]:
    """Audit scientific claims and explicitly separate verbatim abstract leads.

Abstract leads must be exact excerpts. A paper ID alone cannot validate an
arbitrary model-generated paraphrase. Operational counts are rendered by UI.
"""
    payload = scoped_payload(payload)
    if not isinstance(statements, list) or not statements:
        return {"ok": False, "errors": ["overview_statements_missing"], "answer": "", "citations": []}
    papers = {p["paper_id"]: p for p in payload.get("papers", [])}
    answers, citations, errors = [], [], []
    for i, item in enumerate(statements):
        if not isinstance(item, dict):
            errors.append(f"statement[{i}]:not_object")
            continue
        if item.get("certainty") == "abstract_only":
            paper = papers.get(item.get("paper_id"))
            quote = item.get("quote")
            if not paper or not isinstance(quote, str) or not quote.strip() or quote not in (paper.get("abstract") or ""):
                errors.append(f"statement[{i}]:invalid_abstract_excerpt")
                continue
            answers.append(f"摘要级线索 · {paper.get('title')} [{paper['paper_id']}]\n{quote}\n尚未核验全文，不能据此形成确定结论。")
            citations.append({"statement": i, "paper_id": paper["paper_id"], "certainty": "abstract_only"})
        else:
            result = audit_answer_statements(payload, [item])
            errors.extend(result["errors"])
            if result["ok"]:
                answers.append(result["answer"])
                citations.extend({**c, "statement": i} for c in result["citations"])
    return {"ok": not errors, "errors": errors, "answer": "\n\n".join(answers) if not errors else "", "citations": citations}
