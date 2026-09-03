from __future__ import annotations

import re
from typing import Any

from src.schema import Dataset, EvidenceVerdict, PaperDecision

TITLE_STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "using",
    "based",
    "via",
}


def _text_blob(paper, card=None) -> str:
    parts = [paper.title or "", paper.abstract or "", paper.reason or ""]
    if card and card.fields:
        parts.extend(
            [
                card.fields.task or "",
                card.fields.method or "",
                card.fields.metrics or "",
                card.fields.limitations or "",
            ]
        )
    return " ".join(parts)


def _content_tokens(text: str) -> set[str]:
    lowered = text.lower()
    latin = {token for token in re.findall(r"[a-z0-9]{3,}", lowered) if token not in TITLE_STOP}
    cjk = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    return latin | cjk


def _title_tokens(title: str | None) -> set[str]:
    return _content_tokens(title or "")


def _overlap_score(left: str | None, right: str | None) -> float:
    left_tokens = _content_tokens(left or "")
    right_tokens = _content_tokens(right or "")
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _paper_overlap(left_paper, left_card, right_paper, right_card) -> float:
    return _overlap_score(_text_blob(left_paper, left_card), _text_blob(right_paper, right_card))


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


def _append_edge(edges: list[dict[str, Any]], seen: set[tuple[str, str, str]], edge: dict[str, Any]) -> None:
    key = (edge["source"], edge["target"], edge["kind"])
    if key in seen:
        return
    seen.add(key)
    edges.append(edge)


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


def _heuristic_edges(dataset: Dataset, tracks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cards = dataset.card_by_id()
    papers = {paper.paper_id: paper for paper in dataset.real_papers()}
    includes = [paper for paper in papers.values() if paper.decision == PaperDecision.include]
    excludes = [paper for paper in papers.values() if paper.decision == PaperDecision.exclude]
    pendings = [paper for paper in papers.values() if paper.decision == PaperDecision.pending]
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for include in includes:
        include_card = cards.get(include.paper_id)
        ranked_excludes = sorted(
            (
                (_paper_overlap(include, include_card, exclude, cards.get(exclude.paper_id)), exclude)
                for exclude in excludes
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        for score, exclude in ranked_excludes[:3]:
            if score < 0.06:
                continue
            _append_edge(
                edges,
                seen,
                {
                    "source": include.paper_id,
                    "target": exclude.paper_id,
                    "kind": "decision_boundary",
                    "note": "摘要级主题相近但筛选结论不同；这是启发边，不是页码证据或引用关系。",
                    "score": round(score, 3),
                },
            )

    for include in includes:
        include_card = cards.get(include.paper_id)
        ranked = sorted(
            (
                (_paper_overlap(include, include_card, pending, cards.get(pending.paper_id)), pending)
                for pending in pendings
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        for score, pending in ranked[:2]:
            if score < 0.06:
                continue
            _append_edge(
                edges,
                seen,
                {
                    "source": include.paper_id,
                    "target": pending.paper_id,
                    "kind": "pending_review",
                    "note": "纳入论文与待定论文在摘要上相近，提醒继续核验；不是已支持结论。",
                    "score": round(score, 3),
                },
            )

    affinity_candidates: list[tuple[float, str, str]] = []
    include_ids = [paper.paper_id for paper in includes]
    for track in tracks.values():
        track_ids = [
            paper_id
            for paper_id in track.get("paper_ids", [])
            if paper_id in papers and papers[paper_id].decision == PaperDecision.include
        ]
        pool = track_ids if len(track_ids) >= 2 else include_ids
        for index, left_id in enumerate(pool):
            for right_id in pool[index + 1 :]:
                if left_id == right_id:
                    continue
                score = _paper_overlap(
                    papers[left_id],
                    cards.get(left_id),
                    papers[right_id],
                    cards.get(right_id),
                )
                if score >= 0.08:
                    affinity_candidates.append((score, left_id, right_id))
    affinity_candidates.sort(key=lambda item: item[0], reverse=True)
    per_source: dict[str, int] = {}
    for score, left_id, right_id in affinity_candidates:
        if per_source.get(left_id, 0) >= 2 or per_source.get(right_id, 0) >= 2:
            continue
        _append_edge(
            edges,
            seen,
            {
                "source": left_id,
                "target": right_id,
                "kind": "track_affinity",
                "note": "同一主线内摘要主题相近的弱关联；不是引用或证据边。",
                "score": round(score, 3),
            },
        )
        per_source[left_id] = per_source.get(left_id, 0) + 1
        per_source[right_id] = per_source.get(right_id, 0) + 1
    return edges


def _fallback_chain_edges(
    includes: list,
    tracks: dict[str, dict[str, Any]],
    papers: dict[str, Any],
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    heuristic_kinds = {"decision_boundary", "track_affinity", "pending_review"}
    if any(edge["kind"] in heuristic_kinds for edge in edges):
        return
    include_ids = [paper.paper_id for paper in includes if paper.paper_id in papers]
    if len(include_ids) < 2:
        return
    chained: list[str] = []
    for track in tracks.values():
        track_ids = [
            paper_id
            for paper_id in track.get("paper_ids", [])
            if paper_id in papers and papers[paper_id].decision == PaperDecision.include
        ]
        if len(track_ids) >= 2:
            chained.extend(track_ids)
    if len(chained) < 2:
        chained = include_ids
    for index in range(len(chained) - 1):
        _append_edge(
            edges,
            seen,
            {
                "source": chained[index],
                "target": chained[index + 1],
                "kind": "track_affinity",
                "note": "同轮候选论文的弱关联链；不是引用或页码证据。",
            },
        )


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

    evidence_edges = _conflict_pairs(dataset) + _falsification_edges(dataset)
    heuristic_edges = _heuristic_edges(dataset, tracks)
    papers = {paper.paper_id: paper for paper in dataset.real_papers()}
    includes = [paper for paper in papers.values() if paper.decision == PaperDecision.include]
    heuristic_seen = {(edge["source"], edge["target"], edge["kind"]) for edge in heuristic_edges}
    _fallback_chain_edges(includes, tracks, papers, heuristic_edges, heuristic_seen)
    edges = evidence_edges + heuristic_edges
    contradictions = _contradictions(dataset)
    limitations = [
        "主线来自 paper_cards.fields.task/method 的归类，不是引用图谱。",
        "证据边只来自已落盘的 Evidence.verdict 冲突和 FalsificationHit。",
        "track_affinity / decision_boundary / pending_review 是摘要级启发边，不能当作页码证据或引用关系。",
        "parse_status=pdf_partial_verified 表示指定摘录已核验，不等于全文逐页审阅完毕。",
        "exclude 节点必须保留：它们是反证据来源，不是被扔掉的噪声。",
    ]
    if not dataset.paper_cards:
        limitations = [
            "当前 run 没有 paper_cards.jsonl，只展示候选节点。",
            "关系边来自证据冲突、反证据和摘要级启发规则，不推断引用关系。",
        ]
    if not evidence_edges and not heuristic_edges:
        limitations.append("当前没有可展示的关系边。")

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
            "track_affinity": "同主线摘要相近",
            "decision_boundary": "纳入与排除边界",
            "pending_review": "纳入指向待定",
        },
    }
