from __future__ import annotations

import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _has_locator(item: dict) -> bool:
    locator = item.get("locator") or {}
    return any(locator.get(key) not in (None, "") for key in ("page", "section", "paragraph", "char_range", "url_anchor"))


def _no_retrieval_baseline() -> dict:
    return {
        "name": "no_external_retrieval_proxy",
        "description": (
            "无外部检索的代理对照：不允许 paper_id/locator，因此不能产生可核验证据。"
            "这不是一次真实闭卷 LLM 答题，也不报告准确率或因果效应。"
        ),
        "evidence_locator_rate": 0.0,
        "verified_evidence_rate": 0.0,
        "page_locator_rate": 0.0,
        "claim_evidence_link_rate": 0.0,
        "falsification_target_coverage": 0.0,
    }


def evaluate(root: Path) -> dict:
    data = root / "data"
    papers = {row["paper_id"]: row for row in read_jsonl(data / "papers.jsonl")}
    claims = {row["claim_id"]: row for row in read_jsonl(data / "claims.jsonl")}
    evidence = read_jsonl(data / "evidence.jsonl")
    hits = read_jsonl(data / "falsification.jsonl")
    questions = read_jsonl(data / "gold_standard" / "questions.jsonl")

    return _evaluate_rows(papers, claims, evidence, hits, questions)


def evaluate_payload(payload: dict) -> dict:
    """Evaluate only this run's visible, non-fixture data."""
    from src.answer_audit import scoped_payload
    visible = scoped_payload(payload)
    papers = {p["paper_id"]: p for p in visible.get("papers", []) if not p.get("is_fixture") and p.get("source") != "fixture" and not p["paper_id"].startswith("fixture-")}
    claims = {c["claim_id"]: c for c in visible.get("claims", []) if not c.get("is_fixture") and not c["claim_id"].startswith("fixture-")}
    evidence = [e for e in visible.get("evidence", []) if e.get("paper_id") in papers and e.get("claim_id") in claims and not e["evidence_id"].startswith("fixture-")]
    hits = [h for h in visible.get("falsification", []) if h.get("paper_id") in papers and h.get("target_claim") in claims and not h["hit_id"].startswith("fixture-")]
    result = _evaluate_rows(papers, claims, evidence, hits, [])
    result.update(run_id=payload["run_id"], scope="current_run", question_count=None,
                  gold_paper_count=None, gold_claim_count=None, gold_paper_recall=None,
                  gold_claim_coverage=None, baseline=None, delta_vs_no_retrieval={})
    result["litaudit"]["name"] = "current_run"
    result["limitations"] = ["指标仅来自当前运行中可见的论文与证据。", "当前运行未执行独立金标答题或无检索对照实验。", "证据状态为已存储的审计状态；定位匹配不代表语义判断或全文通读。"]
    return result


def _evaluate_rows(papers, claims, evidence, hits, questions) -> dict:

    gold_papers = {paper_id for row in questions for paper_id in row.get("gold_paper_ids", [])}
    gold_claims = {claim_id for row in questions for claim_id in row.get("gold_claim_ids", [])}
    located = [item for item in evidence if _has_locator(item)]
    page_located = [item for item in evidence if (item.get("locator") or {}).get("page") is not None]
    verified = [item for item in evidence if item.get("extraction_status") == "verified"]
    abstract_only = [item for item in evidence if item.get("extraction_status") == "abstract_only"]
    claims_with_evidence = {item["claim_id"] for item in evidence if item.get("claim_id") in claims}
    hit_targets = {item["target_claim"] for item in hits if item.get("target_claim") in claims}
    supported = sum(item.get("status") == "supported" for item in claims.values())
    pending = sum(item.get("status") == "pending" for item in claims.values())
    partial = sum(item.get("status") == "partial" for item in claims.values())

    litaudit = {
        "name": "litaudit_offline_snapshot",
        "evidence_locator_rate": len(located) / len(evidence) if evidence else 0.0,
        "verified_evidence_rate": len(verified) / len(evidence) if evidence else 0.0,
        "page_locator_rate": len(page_located) / len(evidence) if evidence else 0.0,
        "claim_evidence_link_rate": len(claims_with_evidence) / len(claims) if claims else 0.0,
        "falsification_target_coverage": len(hit_targets) / len(claims) if claims else 0.0,
    }
    baseline = _no_retrieval_baseline()
    delta = {
        key: round(litaudit[key] - baseline[key], 4)
        for key in (
            "evidence_locator_rate",
            "verified_evidence_rate",
            "page_locator_rate",
            "claim_evidence_link_rate",
            "falsification_target_coverage",
        )
    }

    return {
        "question_count": len(questions),
        "paper_count": len(papers),
        "claim_count": len(claims),
        "evidence_count": len(evidence),
        "verified_evidence_count": len(verified),
        "abstract_only_evidence_count": len(abstract_only),
        "page_locator_count": len(page_located),
        "falsification_count": len(hits),
        "gold_paper_count": len(gold_papers),
        "gold_claim_count": len(gold_claims),
        "gold_paper_recall": sum(paper_id in papers for paper_id in gold_papers) / len(gold_papers) if gold_papers else 0.0,
        "gold_claim_coverage": sum(claim_id in claims for claim_id in gold_claims) / len(gold_claims) if gold_claims else 0.0,
        "evidence_locator_rate": litaudit["evidence_locator_rate"],
        "verified_evidence_rate": litaudit["verified_evidence_rate"],
        "page_locator_rate": litaudit["page_locator_rate"],
        "claim_evidence_link_rate": litaudit["claim_evidence_link_rate"],
        "supported_claim_rate": supported / len(claims) if claims else 0.0,
        "partial_claim_rate": partial / len(claims) if claims else 0.0,
        "pending_claim_rate": pending / len(claims) if claims else 0.0,
        "falsification_target_coverage": litaudit["falsification_target_coverage"],
        "baseline": baseline,
        "litaudit": litaudit,
        "delta_vs_no_retrieval": delta,
        "limitations": [
            "gold standard is repository-local and not a cross-paper population effect",
            "baseline is a traceability proxy (no locator), not a live closed-book LLM accuracy run",
            "verified means the quoted span was checked against a local PDF page, not that the whole paper was read",
            "do not report causal superiority of RAG agents from these coverage rates",
        ],
    }
