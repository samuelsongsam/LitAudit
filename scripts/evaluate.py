from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(root: Path) -> dict:
    data = root / "data"
    papers = {row["paper_id"]: row for row in read_jsonl(data / "papers.jsonl")}
    claims = {row["claim_id"]: row for row in read_jsonl(data / "claims.jsonl")}
    evidence = read_jsonl(data / "evidence.jsonl")
    hits = read_jsonl(data / "falsification.jsonl")
    questions = read_jsonl(data / "gold_standard" / "questions.jsonl")

    gold_papers = {paper_id for row in questions for paper_id in row.get("gold_paper_ids", [])}
    gold_claims = {claim_id for row in questions for claim_id in row.get("gold_claim_ids", [])}
    located = [
        item
        for item in evidence
        if any(item.get("locator", {}).get(key) not in (None, "") for key in ("page", "section", "paragraph", "char_range", "url_anchor"))
    ]
    claims_with_evidence = {item["claim_id"] for item in evidence if item.get("claim_id") in claims}
    hit_targets = {item["target_claim"] for item in hits if item.get("target_claim") in claims}
    supported = sum(item.get("status") == "supported" for item in claims.values())
    pending = sum(item.get("status") == "pending" for item in claims.values())
    return {
        "question_count": len(questions),
        "paper_count": len(papers),
        "claim_count": len(claims),
        "evidence_count": len(evidence),
        "falsification_count": len(hits),
        "gold_paper_count": len(gold_papers),
        "gold_claim_count": len(gold_claims),
        "gold_paper_recall": sum(paper_id in papers for paper_id in gold_papers) / len(gold_papers) if gold_papers else 0.0,
        "gold_claim_coverage": sum(claim_id in claims for claim_id in gold_claims) / len(gold_claims) if gold_claims else 0.0,
        "evidence_locator_rate": len(located) / len(evidence) if evidence else 0.0,
        "claim_evidence_link_rate": len(claims_with_evidence) / len(claims) if claims else 0.0,
        "supported_claim_rate": supported / len(claims) if claims else 0.0,
        "pending_claim_rate": pending / len(claims) if claims else 0.0,
        "falsification_target_coverage": len(hit_targets) / len(claims) if claims else 0.0,
        "limitations": [
            "gold standard is abstract-level and repository-local",
            "no baseline run or full-text page-level gold evidence",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(evaluate(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
