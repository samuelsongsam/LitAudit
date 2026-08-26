from __future__ import annotations

import re

from src.schema import Dataset

TOKEN = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]{3,}")
STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "was",
    "not",
    "use",
    "using",
    "into",
    "than",
    "can",
}


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN.finditer(text or "")} - STOP


def _score(query: set[str], text: str) -> float:
    if not query:
        return 0.0
    overlap = query & _tokens(text)
    if len(overlap) < 2 and len(query) > 1:
        return 0.0
    return len(overlap) / len(query)


def ask(dataset: Dataset, question: str, *, limit: int = 5) -> dict:
    query = _tokens(question)
    papers = []
    for paper in dataset.real_papers():
        card = dataset.card_by_id().get(paper.paper_id)
        blob = " ".join(
            part
            for part in (
                paper.title or "",
                paper.abstract or "",
                paper.reason,
                "" if card is None or card.fields is None else " ".join(
                    value for value in (card.fields.task, card.fields.method, card.fields.data) if value
                ),
            )
            if part
        )
        score = _score(query, blob)
        if score <= 0:
            continue
        papers.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "decision": paper.decision.value,
                "score": round(score, 4),
                "reason": paper.reason,
            }
        )
    papers.sort(key=lambda row: (-row["score"], row["paper_id"]))

    claims = []
    for claim in dataset.real_claims():
        score = _score(query, f"{claim.text} {claim.decision_reason}")
        if score <= 0:
            continue
        related = [item for item in dataset.evidence if item.claim_id == claim.claim_id]
        claims.append(
            {
                "claim_id": claim.claim_id,
                "text": claim.text,
                "status": claim.status.value,
                "score": round(score, 4),
                "evidence_ids": [item.evidence_id for item in related],
                "extraction_status": sorted({item.extraction_status.value for item in related}),
            }
        )
    claims.sort(key=lambda row: (-row["score"], row["claim_id"]))

    paper_ids = {row["paper_id"] for row in papers[:limit]}
    claim_ids = {row["claim_id"] for row in claims[:limit]}
    hits = [
        {
            "hit_id": hit.hit_id,
            "target_claim": hit.target_claim,
            "paper_id": hit.paper_id,
            "threat": hit.threat.value,
            "status": hit.status.value,
        }
        for hit in dataset.falsification
        if hit.target_claim in claim_ids or hit.paper_id in paper_ids
    ]
    return {
        "question": question,
        "mode": "local_keyword_overlap",
        "papers": papers[:limit],
        "claims": claims[:limit],
        "falsification": hits,
        "limitations": [
            "只在当前离线候选集上做关键词重叠检索，不调用外部 API，也不生成长综述。",
            "分数不是相关性模型，不能当成排序质量评测。",
            "命中论文仍必须经过筛选漏斗和证据卡查看，不能凭分数纳入结论。",
        ],
    }
