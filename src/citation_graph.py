from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode

from src.http_fetch import FetchResult, http_get

FetchFn = Callable[..., FetchResult]


def _paper_payload(row: dict[str, Any], direction: str) -> dict[str, Any]:
    key = "citedPaper" if direction == "references" else "citingPaper"
    paper = row.get(key) or {}
    return {
        "paper_id": paper.get("paperId"),
        "title": paper.get("title"),
        "abstract": paper.get("abstract"),
        "year": paper.get("year"),
        "url": paper.get("url"),
        "open_access_pdf_url": (paper.get("openAccessPdf") or {}).get("url"),
    }


def expand_citation_graph(
    hits: list[Any], *, cache_dir: Path, api_key: str | None = None,
    fetch: FetchFn = http_get, max_seeds: int = 3, limit: int = 20,
) -> dict[str, Any]:
    seeds = [hit for hit in hits if getattr(hit, "semantic_scholar_id", None)][:max_seeds]
    graph: dict[str, Any] = {
        "algorithm": "semantic_scholar_one_hop",
        "limits": {"seed_papers": max_seeds, "relations_per_direction": limit},
        "seed_count": len(seeds), "nodes": [], "edges": [], "requests": [],
    }
    nodes: dict[str, dict[str, Any]] = {}
    headers = {"x-api-key": api_key} if api_key else None
    fields = "contexts,intents,isInfluential,title,abstract,year,url,openAccessPdf"
    citation_cache = cache_dir / "citations"
    citation_cache.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        seed_id = seed.semantic_scholar_id
        nodes[seed_id] = {"paper_id": seed_id, "title": seed.title, "seed": True}
        for direction in ("references", "citations"):
            url = (
                f"https://api.semanticscholar.org/graph/v1/paper/{quote(seed_id, safe='')}/{direction}?"
                + urlencode({"fields": fields, "limit": limit})
            )
            result = fetch(url, headers=headers, timeout=25, mailto=None)
            path = citation_cache / f"{seed_id}-{direction}.json"
            if result.body:
                path.write_bytes(result.body)
            request_row = {
                "seed_paper_id": seed_id, "direction": direction, "url": result.url or url,
                "http_status": result.status, "status": "success" if result.status == 200 else "rate_limited" if result.status == 429 else "failed",
                "response_path": str(path) if result.body else None, "error": result.error,
            }
            graph["requests"].append(request_row)
            if result.status != 200 or not result.body:
                continue
            try:
                rows = (json.loads(result.body.decode("utf-8")) or {}).get("data") or []
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                request_row["status"] = "parse_failed"
                continue
            for row in rows:
                related = _paper_payload(row, direction)
                related_id = related.get("paper_id")
                if not related_id:
                    continue
                nodes.setdefault(related_id, {**related, "seed": False})
                source, target = (seed_id, related_id) if direction == "references" else (related_id, seed_id)
                graph["edges"].append({
                    "source": source, "target": target, "relation": "cites",
                    "contexts": [str(value) for value in row.get("contexts") or []][:3],
                    "intents": [str(value) for value in row.get("intents") or []],
                    "is_influential": bool(row.get("isInfluential")),
                })
    graph["nodes"] = list(nodes.values())
    graph["edge_count"] = len(graph["edges"])
    graph["failure_count"] = sum(row["status"] != "success" for row in graph["requests"])
    return graph
