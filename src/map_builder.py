from __future__ import annotations

from typing import Any

from src.schema import Dataset, EvidenceVerdict, PaperDecision


def _track_key(card) -> tuple[str, str]:
    if card.decision == PaperDecision.pending:
        return "pending", "待核验（仅摘要，不得当作结论）"
    task = (card.fields.task if card.fields else "") or ""
    if card.decision == PaperDecision.include:
        lowered = task.lower()
        if any(token in task for token in ("问答", "问题回答", "回答")) or "qa" in lowered or "rag" in lowered:
            return "sciqa", "科学文献问答 / RAG agent"
        return "autosci", "相邻自动科研信息整合"
    return "boundary", "任务边界（exclude，保留给反证据）"


def _conflict_pairs(dataset: Dataset) -> list[dict[str, Any]]:
    grouped: dict[str, list] = {}
    for item in dataset.evidence:
        if item.is_fixture:
            continue
        grouped.setdefault(item.claim_id, []).append(item)

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    positive = {EvidenceVerdict.supports, EvidenceVerdict.partially_supports, EvidenceVerdict.context_only}
    for claim_id, items in grouped.items():
        left = [item for item in items if item.verdict in positive]
        right = [item for item in items if item.verdict == EvidenceVerdict.contradicts]
        for source in left:
            for target in right:
                if source.paper_id == target.paper_id:
                    continue
                key = (claim_id, source.paper_id, target.paper_id, "evidence_conflict")
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(
                    {
                        "source": source.paper_id,
                        "target": target.paper_id,
                        "kind": "evidence_conflict",
                        "claim_id": claim_id,
                        "evidence_ids": [source.evidence_id, target.evidence_id],
                        "note": f"{source.verdict.value} vs {target.verdict.value}",
                    }
                )
    return pairs


def _falsification_edges(dataset: Dataset) -> list[dict[str, Any]]:
    grouped: dict[str, list] = {}
    for item in dataset.evidence:
        if item.is_fixture:
            continue
        grouped.setdefault(item.claim_id, []).append(item)

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for hit in dataset.falsification:
        if hit.is_fixture:
            continue
        related = grouped.get(hit.target_claim, [])
        sources = {
            item.paper_id
            for item in related
            if item.verdict != EvidenceVerdict.contradicts and item.paper_id != hit.paper_id
        }
        for source in sorted(sources):
            key = (source, hit.paper_id, hit.hit_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": source,
                    "target": hit.paper_id,
                    "kind": "falsification",
                    "claim_id": hit.target_claim,
                    "hit_id": hit.hit_id,
                    "threat": hit.threat.value,
                    "note": "反证据命中，不是引用边",
                }
            )
    return edges


def _contradictions(dataset: Dataset) -> list[dict[str, Any]]:
    claims = {claim.claim_id: claim for claim in dataset.real_claims()}
    grouped: dict[str, list] = {}
    for item in dataset.evidence:
        if item.is_fixture:
            continue
        grouped.setdefault(item.claim_id, []).append(item)

    rows: list[dict[str, Any]] = []
    for claim_id, items in grouped.items():
        supports = [item.paper_id for item in items if item.verdict in {EvidenceVerdict.supports, EvidenceVerdict.partially_supports, EvidenceVerdict.context_only}]
        contradicts = [item.paper_id for item in items if item.verdict == EvidenceVerdict.contradicts]
        if not (supports and contradicts):
            continue
        claim = claims.get(claim_id)
        hits = [hit.hit_id for hit in dataset.falsification if hit.target_claim == claim_id]
        rows.append(
            {
                "claim_id": claim_id,
                "claim_status": None if claim is None else claim.status.value,
                "claim_text": None if claim is None else claim.text,
                "support_or_context_papers": sorted(set(supports)),
                "contradict_papers": sorted(set(contradicts)),
                "hit_ids": hits,
                "note": "同一论断上的正反证据冲突；冲突未解决时 Claim 必须 pending。",
            }
        )
    return rows


def build_map(dataset: Dataset, run_id: str) -> dict[str, Any]:
    cards = dataset.card_by_id()
    nodes = []
    tracks: dict[str, dict[str, Any]] = {}
    evidence_by_paper: dict[str, list[str]] = {}
    for item in dataset.evidence:
        evidence_by_paper.setdefault(item.paper_id, []).append(item.extraction_status.value)

    for paper in dataset.papers:
        card = cards.get(paper.paper_id)
        fields = card.fields if card and card.fields else None
        statuses = evidence_by_paper.get(paper.paper_id, [])
        nodes.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "year": paper.year,
                "decision": paper.decision.value,
                "reason": paper.reason,
                "doi_or_arxiv": paper.doi_or_arxiv,
                "url": paper.url,
                "is_fixture": paper.is_fixture,
                "parse_status": card.parse_status if card else None,
                "parse_error": card.parse_error if card else None,
                "task": fields.task if fields else None,
                "method": fields.method if fields else None,
                "evidence_status": statuses,
            }
        )
        if paper.is_fixture:
            continue
        source_card = card or paper
        key, label = _track_key(source_card)
        bucket = tracks.setdefault(key, {"track_id": key, "label": label, "paper_ids": []})
        bucket["paper_ids"].append(paper.paper_id)

    edges = _conflict_pairs(dataset) + _falsification_edges(dataset)
    contradictions = _contradictions(dataset)
    limitations = [
        "主线来自 paper_cards.fields.task/method 的归类，不是引用图谱。",
        "关系边只来自已落盘的 Evidence.verdict 冲突和 FalsificationHit，不推断引用或共被引。",
        "parse_status=pdf_partial_verified 表示指定摘录已核验，不等于全文逐页审阅完毕。",
        "exclude 节点必须保留：它们是反证据来源，不是被扔掉的噪声。",
    ]
    if not dataset.paper_cards:
        limitations = [
            "当前 run 没有 paper_cards.jsonl，只展示候选节点。",
            "关系边只在有 Evidence/FalsificationHit 时生成，不推断引用关系。",
        ]
    if not edges:
        limitations.append("当前没有可回溯的冲突边；保持空列表，不补造。")

    return {
        "run_id": run_id,
        "nodes": nodes,
        "edges": edges,
        "tracks": list(tracks.values()),
        "contradictions": contradictions,
        "limitations": limitations,
        "legend": {
            PaperDecision.include.value: "纳入",
            PaperDecision.exclude.value: "排除（保留给反证据召回）",
            PaperDecision.pending.value: "待核验，不得当作结论",
            "evidence_conflict": "同一论断上的正反证据",
            "falsification": "反证据命中",
        },
    }
