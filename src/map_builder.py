from __future__ import annotations

from typing import Any

from src.schema import Dataset, PaperDecision


def _track_key(card) -> tuple[str, str]:
    task = (card.fields.task if card.fields else "") or ""
    if card.decision == PaperDecision.include:
        lowered = task.lower()
        if any(token in task for token in ("问答", "问题回答", "回答")) or "qa" in lowered or "rag" in lowered:
            return "sciqa", "科学文献问答 / RAG agent"
        return "autosci", "相邻自动科研信息整合"
    return "boundary", "任务边界（exclude，保留给反证据）"


def build_map(dataset: Dataset, run_id: str) -> dict[str, Any]:
    cards = dataset.card_by_id()
    nodes = []
    tracks: dict[str, dict[str, Any]] = {}
    for paper in dataset.papers:
        card = cards.get(paper.paper_id)
        fields = card.fields if card and card.fields else None
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
            }
        )
        if paper.is_fixture:
            continue
        source_card = card or paper
        key, label = _track_key(source_card)
        bucket = tracks.setdefault(key, {"track_id": key, "label": label, "paper_ids": []})
        bucket["paper_ids"].append(paper.paper_id)

    limitations = [
        "主线来自 paper_cards.fields.task/method 的摘要级归类，不是引用图谱。",
        "关系边和矛盾对为空：当前没有经核验的引用数据，不推断边。",
        "parse_status=abstract_verified 不等于全文已核验，不能补造页码。",
    ]
    if not dataset.paper_cards:
        limitations = [
            "当前 run 没有 paper_cards.jsonl，只展示候选节点。",
            "关系边和矛盾对为空，不推断引用关系。",
        ]

    return {
        "run_id": run_id,
        "nodes": nodes,
        "edges": [],
        "tracks": list(tracks.values()),
        "contradictions": [],
        "limitations": limitations,
        "legend": {
            PaperDecision.include.value: "纳入",
            PaperDecision.exclude.value: "排除（保留给反证据召回）",
            PaperDecision.pending.value: "待核验，不得当作结论",
        },
    }
