from __future__ import annotations

from typing import Any

from src.schema import Dataset, PaperDecision


def build_map(dataset: Dataset, run_id: str) -> dict[str, Any]:
    """第一轮只根据已校验论文生成节点。主线/矛盾对等待 A 的 paper_cards。"""
    nodes = []
    for paper in dataset.papers:
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
            }
        )
    return {
        "run_id": run_id,
        "nodes": nodes,
        "edges": [],
        "tracks": [],
        "contradictions": [],
        "limitations": [
            "paper_cards.jsonl 尚未由 A 提供，因此不生成方法主线或矛盾对。",
            "当前地图只展示筛选后的候选节点，颜色对应 include / exclude / pending。",
        ],
        "legend": {
            PaperDecision.include.value: "纳入",
            PaperDecision.exclude.value: "排除（保留给反证据召回）",
            PaperDecision.pending.value: "待核验，不得当作结论",
        },
    }
