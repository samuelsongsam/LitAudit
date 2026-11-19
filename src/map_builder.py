from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache
from html import escape
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from src.schema import Dataset, EvidenceVerdict, PaperDecision

SPECTER_BASE_MODEL = "allenai/specter2_base"
SPECTER_ADAPTER = "allenai/specter2"
SPECTER_QUERY_ADAPTER = "allenai/specter2_adhoc_query"
EMBEDDING_DIMENSION = 768
DEFAULT_SIMILARITY_THRESHOLD = 0.82
DEFAULT_NEIGHBORS_PER_PAPER = 2
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
    "into",
    "over",
    "under",
    "study",
    "paper",
}


def paper_embedding_text(paper: Any, *, separator: str = " ") -> str:
    """Match SPECTER2's title + abstract input shape."""
    return separator.join(part for part in [paper.title, paper.abstract] if part and part.strip()).strip()


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    latin = [token for token in re.findall(r"[a-z0-9]{3,}", lowered) if token not in TITLE_STOP]
    cjk = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return latin + cjk


def _normalize(vector: Iterable[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return values
    return [value / norm for value in values]


def _hash_embedding(text: str) -> list[float]:
    """Deterministic 768d text vector used when SPECTER2 is unavailable locally."""
    vector = [0.0] * EMBEDDING_DIMENSION
    for token in _tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSION
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize(vector)


@lru_cache(maxsize=1)
def _load_specter2() -> tuple[Any, Any, str]:
    """Load the local SPECTER2 base model and proximity adapter once per process."""
    from adapters import AutoAdapterModel
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(SPECTER_BASE_MODEL, local_files_only=True)
    model = AutoAdapterModel.from_pretrained(SPECTER_BASE_MODEL, local_files_only=True)
    adapter_name = model.load_adapter(SPECTER_ADAPTER, source="hf", local_files_only=True, set_active=True)
    model.set_active_adapters(adapter_name)
    model.eval()
    return tokenizer, model, str(adapter_name)


def download_specter2() -> dict[str, str]:
    """Download the exact Hugging Face repositories required by this implementation."""
    from huggingface_hub import snapshot_download

    return {
        "base_model": snapshot_download(repo_id=SPECTER_BASE_MODEL),
        "adapter": snapshot_download(repo_id=SPECTER_ADAPTER),
        "query_adapter": snapshot_download(repo_id=SPECTER_QUERY_ADAPTER),
    }


@lru_cache(maxsize=16)
def _encode_specter2_texts(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
    import torch

    tokenizer, model, _ = _load_specter2()
    inputs = tokenizer(
        list(texts),
        padding=True,
        truncation=True,
        return_tensors="pt",
        return_token_type_ids=False,
        max_length=512,
    )
    with torch.inference_mode():
        output = model(**inputs)
    return tuple(tuple(_normalize(vector)) for vector in output.last_hidden_state[:, 0, :].detach().cpu().tolist())


def _specter2_embeddings(papers: list[Any]) -> tuple[list[list[float]], dict[str, Any]]:
    if not papers:
        return [], {
            "backend": "specter2",
            "model": SPECTER_ADAPTER,
            "base_model": SPECTER_BASE_MODEL,
            "active_adapter": None,
            "reason": "no eligible papers",
        }
    try:
        from adapters import AutoAdapterModel  # noqa: F401
        from transformers import AutoTokenizer  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on optional package
        return [], {"backend": "hash", "model": None, "reason": f"SPECTER2 dependencies unavailable: {exc.__class__.__name__}"}

    try:
        tokenizer, _, adapter_name = _load_specter2()
    except Exception as exc:  # pragma: no cover - depends on local model cache
        return [], {"backend": "hash", "model": None, "reason": f"SPECTER2 load failed: {exc.__class__.__name__}"}

    texts = [paper_embedding_text(paper, separator=tokenizer.sep_token or " ") for paper in papers]
    try:
        vectors = [list(vector) for vector in _encode_specter2_texts(tuple(texts))]
    except Exception as exc:  # pragma: no cover - depends on torch/model runtime
        return [], {"backend": "hash", "model": None, "reason": f"SPECTER2 encode failed: {exc.__class__.__name__}"}
    return [
        _normalize(vector) for vector in vectors
    ], {
        "backend": "specter2",
        "model": SPECTER_ADAPTER,
        "base_model": SPECTER_BASE_MODEL,
        "active_adapter": adapter_name,
        "reason": None,
    }


def embed_papers(papers: list[Any]) -> tuple[dict[str, list[float]], dict[str, Any]]:
    texts = [paper_embedding_text(paper) for paper in papers]
    mode = os.getenv("LITAUDIT_MAP_EMBEDDER", "specter2").strip().lower()
    if mode not in {"auto", "hash", "specter", "specter2"}:
        raise ValueError("LITAUDIT_MAP_EMBEDDER must be specter2, auto, or hash")
    if not papers:
        return {}, {
            "backend": "specter2" if mode != "hash" else "hash",
            "model": SPECTER_ADAPTER if mode != "hash" else None,
            "base_model": SPECTER_BASE_MODEL if mode != "hash" else None,
            "active_adapter": None,
            "reason": "no eligible papers",
        }
    vectors: list[list[float]] = []
    metadata: dict[str, Any] = {"backend": "hash", "model": None, "reason": None}
    if mode in {"auto", "specter", "specter2"}:
        vectors, metadata = _specter2_embeddings(papers)
        if mode in {"specter", "specter2"} and not vectors:
            raise RuntimeError(
                f"{metadata.get('reason') or 'SPECTER2 embedding failed'}. "
                "Run `python -m src.cli download-model` after installing `.[map]`, "
                "or explicitly set LITAUDIT_MAP_EMBEDDER=hash for the non-semantic test fallback."
            )
    if not vectors:
        vectors = [_hash_embedding(text) for text in texts]
        metadata.setdefault("backend", "hash")
        metadata.setdefault("reason", "SPECTER2 unavailable")
    return {paper.paper_id: vector for paper, vector in zip(papers, vectors)}, metadata


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def semantic_projection(matrix: list[list[float]]) -> list[tuple[float, float]]:
    """Project cosine distances to a deterministic 2D map with classical MDS."""
    size = len(matrix)
    if size == 0:
        return []
    if size == 1:
        return [(0.5, 0.5)]
    import numpy as np

    similarity = np.asarray(matrix, dtype=float)
    distances = np.clip(1.0 - similarity, 0.0, 2.0)
    centering = np.eye(size) - np.ones((size, size)) / size
    gram = -0.5 * centering @ (distances ** 2) @ centering
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    order = np.argsort(eigenvalues)[::-1][:2]
    values = np.maximum(eigenvalues[order], 0.0)
    coordinates = eigenvectors[:, order] * np.sqrt(values)
    if coordinates.shape[1] < 2:
        coordinates = np.column_stack([coordinates[:, 0], np.zeros(size)])
    for axis in range(2):
        # Eigenvector signs are arbitrary. Fix them so serialized maps are stable.
        pivot = int(np.argmax(np.abs(coordinates[:, axis])))
        if coordinates[pivot, axis] < 0:
            coordinates[:, axis] *= -1
        low = float(coordinates[:, axis].min())
        high = float(coordinates[:, axis].max())
        coordinates[:, axis] = 0.5 if high - low < 1e-12 else (coordinates[:, axis] - low) / (high - low)
    return [(round(float(x), 6), round(float(y), 6)) for x, y in coordinates]


def similarity_edges(
    papers: list[Any],
    embeddings: dict[str, list[float]],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    neighbors_per_paper: int = DEFAULT_NEIGHBORS_PER_PAPER,
) -> tuple[list[dict[str, Any]], list[list[float]], int]:
    size = len(papers)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    candidates: list[dict[str, Any]] = []
    for index in range(size):
        matrix[index][index] = 1.0
    for left_index, right_index in combinations(range(size), 2):
        left = papers[left_index]
        right = papers[right_index]
        score = cosine_similarity(embeddings.get(left.paper_id, []), embeddings.get(right.paper_id, []))
        matrix[left_index][right_index] = score
        matrix[right_index][left_index] = score
        if score >= threshold:
            candidates.append(
                {
                    "source": left.paper_id,
                    "target": right.paper_id,
                    "kind": "semantic_similarity",
                    "weight": round(score, 4),
                    "score": round(score, 4),
                    "note": "SPECTER2 语义向量余弦相似度边；不是引用关系或证据支持关系。",
                }
            )
    candidates.sort(key=lambda edge: (-edge["weight"], edge["source"], edge["target"]))
    selected: set[tuple[str, str]] = set()
    for paper in papers:
        incident = [edge for edge in candidates if paper.paper_id in {edge["source"], edge["target"]}]
        for edge in incident[: max(1, neighbors_per_paper)]:
            selected.add((edge["source"], edge["target"]))
    edges = [edge for edge in candidates if (edge["source"], edge["target"]) in selected]
    return edges, matrix, len(candidates)


def _connected_components(paper_ids: list[str], edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency = {paper_id: set() for paper_id in paper_ids}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        adjacency.setdefault(edge["target"], set()).add(edge["source"])
    components: list[list[str]] = []
    seen: set[str] = set()
    for paper_id in paper_ids:
        if paper_id in seen:
            continue
        stack = [paper_id]
        seen.add(paper_id)
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    components.sort(key=lambda item: (-len(item), item[0] if item else ""))
    return components


def _semantic_tracks(paper_ids: list[str], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        import networkx as nx

        graph = nx.Graph()
        graph.add_nodes_from(paper_ids)
        graph.add_weighted_edges_from((edge["source"], edge["target"], edge["weight"]) for edge in edges)
        isolates = sorted(nx.isolates(graph))
        connected = graph.subgraph([node for node in graph if node not in isolates]).copy()
        components = [sorted(component) for component in nx.community.greedy_modularity_communities(connected, weight="weight")]
        components.extend([[paper_id] for paper_id in isolates])
        components.sort(key=lambda item: (-len(item), item[0] if item else ""))
    except Exception:  # pragma: no cover - networkx is optional
        components = _connected_components(paper_ids, edges)
    return [
        {
            "track_id": f"semantic-{index + 1}",
            "label": f"主题簇 {index + 1}" if len(component) > 1 else "语义孤岛",
            "paper_ids": component,
        }
        for index, component in enumerate(components)
    ]


def _contradictions(dataset: Dataset) -> list[dict[str, Any]]:
    claims = {claim.claim_id: claim for claim in dataset.real_claims()}
    grouped: dict[str, list] = {}
    for item in dataset.evidence:
        if item.is_fixture:
            continue
        grouped.setdefault(item.claim_id, []).append(item)

    rows: list[dict[str, Any]] = []
    positive = {EvidenceVerdict.supports, EvidenceVerdict.partially_supports, EvidenceVerdict.context_only}
    for claim_id, items in grouped.items():
        supports = [item.paper_id for item in items if item.verdict in positive]
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


def _node_rows(dataset: Dataset, papers: list[Any]) -> list[dict[str, Any]]:
    cards = dataset.card_by_id()
    evidence_by_paper: dict[str, list[str]] = {}
    for item in dataset.evidence:
        evidence_by_paper.setdefault(item.paper_id, []).append(item.extraction_status.value)

    nodes = []
    for paper in papers:
        card = cards.get(paper.paper_id)
        fields = card.fields if card and card.fields else None
        text = paper_embedding_text(paper)
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
                "evidence_status": evidence_by_paper.get(paper.paper_id, []),
                "embedding_text_chars": len(text),
            }
        )
    return nodes


def build_map(
    dataset: Dataset,
    run_id: str,
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    neighbors_per_paper: int = DEFAULT_NEIGHBORS_PER_PAPER,
) -> dict[str, Any]:
    papers = [paper for paper in dataset.papers if not paper.is_fixture and paper_embedding_text(paper)]
    nodes = _node_rows(dataset, papers)
    embeddings, embedding_meta = embed_papers(papers)
    edges, matrix, candidate_edge_count = similarity_edges(
        papers, embeddings, threshold=threshold, neighbors_per_paper=neighbors_per_paper
    )
    paper_ids = [paper.paper_id for paper in papers]
    tracks = _semantic_tracks(paper_ids, edges)
    coordinates = semantic_projection(matrix)
    track_by_paper = {
        paper_id: track["track_id"] for track in tracks for paper_id in track["paper_ids"]
    }
    coordinate_by_paper = dict(zip(paper_ids, coordinates))
    degrees = {paper_id: 0 for paper_id in paper_ids}
    for edge in edges:
        degrees[edge["source"]] += 1
        degrees[edge["target"]] += 1
    for node in nodes:
        node["track_id"] = track_by_paper.get(node["paper_id"])
        x, y = coordinate_by_paper.get(node["paper_id"], (0.5, 0.5))
        node["semantic_x"] = x
        node["semantic_y"] = y
        node["semantic_degree"] = degrees.get(node["paper_id"], 0)
    limitations = [
        "节点文本由 Title + Abstract 拼接生成；缺少标题或摘要的论文不会参与语义图。",
        f"边为余弦相似度 >= {threshold:.2f} 的无向语义相似关系，边权越大表示文本语义越接近。",
        "语义相似不等于引用、证据支持或事实一致；Claim/Evidence 审计仍以证据模块为准。",
        "exclude 与 pending 节点仍会参与语义图，用于观察主题边界和待核验候选。",
    ]
    if embedding_meta.get("backend") != "specter2":
        limitations.append(
            "当前环境未使用本地 SPECTER2 模型，已退回确定性 768 维文本哈希向量；安装 adapters/transformers/torch 并缓存 allenai/specter2_base 与 allenai/specter2 后可得到 SPECTER2 语义坐标。"
        )
    if not edges:
        limitations.append("当前阈值下没有论文对达到语义连边条件，图中会出现孤岛。")

    return {
        "run_id": run_id,
        "algorithm": "specter2_cosine_network",
        "layout_version": 3,
        "layout": "specter2_cosine_mds",
        "embedding": {
            "backend": embedding_meta.get("backend"),
            "model": embedding_meta.get("model"),
            "base_model": embedding_meta.get("base_model"),
            "active_adapter": embedding_meta.get("active_adapter"),
            "dimension": EMBEDDING_DIMENSION,
            "input": "title + abstract",
            "fallback_reason": embedding_meta.get("reason"),
        },
        "similarity_threshold": threshold,
        "edge_policy": {
            "type": "threshold_top_k_union",
            "neighbors_per_paper": neighbors_per_paper,
            "candidate_edge_count": candidate_edge_count,
            "displayed_edge_count": len(edges),
        },
        "similarity_matrix": {
            "paper_ids": paper_ids,
            "values": [[round(value, 4) for value in row] for row in matrix],
        },
        "nodes": nodes,
        "edges": edges,
        "tracks": tracks,
        "contradictions": _contradictions(dataset),
        "limitations": limitations,
        "legend": {
            PaperDecision.include.value: "纳入",
            PaperDecision.exclude.value: "排除（保留给反证据召回）",
            PaperDecision.pending.value: "待核验，不得当作结论",
            "semantic_similarity": "SPECTER2 语义相似边",
        },
    }


def build_pyvis_html(map_payload: dict[str, Any]) -> str:
    try:
        from pyvis.network import Network
    except Exception:
        return _fallback_html(map_payload)

    network = Network(height="760px", width="100%", bgcolor="#fffdf7", font_color="#2b261f")
    network.barnes_hut(gravity=-2800, central_gravity=0.18, spring_length=180, spring_strength=0.045, damping=0.18)
    track_ids = {track["track_id"]: index for index, track in enumerate(map_payload.get("tracks", []))}
    colors = ["#3b82a0", "#c96b3b", "#688b4e", "#8a65a8", "#c29a2e", "#4776b5"]
    for node in map_payload.get("nodes", []):
        cluster_index = track_ids.get(node.get("track_id"), 0) % len(colors)
        network.add_node(
            node["paper_id"],
            label=node.get("title") or node["paper_id"],
            title=_paper_tooltip(node),
            color=colors[cluster_index],
            value=max(8, 8 + int(node.get("semantic_degree") or 0) * 2),
            x=(float(node.get("semantic_x") or 0.5) - 0.5) * 900,
            y=(float(node.get("semantic_y") or 0.5) - 0.5) * 600,
        )
    for edge in map_payload.get("edges", []):
        weight = float(edge.get("weight") or edge.get("score") or 0.0)
        network.add_edge(
            edge["source"],
            edge["target"],
            width=1,
            color={"color": "rgba(55, 86, 120, 0.12)", "highlight": "#375678"},
            title=f"cosine={weight:.4f}",
            physics=True,
        )
    return network.generate_html(notebook=False)


def write_pyvis_html(map_payload: dict[str, Any], path: Path) -> None:
    path.write_text(build_pyvis_html(map_payload), encoding="utf-8")


def _decision_color(decision: str | None) -> str:
    return {"include": "#4f8a63", "exclude": "#b35b4b", "pending": "#b18a2f"}.get(decision or "", "#7b8794")


def _paper_tooltip(node: dict[str, Any]) -> str:
    title = node.get("title") or node.get("paper_id") or ""
    year = node.get("year") or "unknown year"
    decision = node.get("decision") or "unknown"
    reason = node.get("reason") or ""
    return f"{escape(title)}<br>{escape(str(year))} · {escape(decision)}<br>{escape(reason)}"


def _fallback_html(map_payload: dict[str, Any]) -> str:
    payload = {
        "nodes": map_payload.get("nodes", []),
        "edges": map_payload.get("edges", []),
        "threshold": map_payload.get("similarity_threshold"),
        "embedding": map_payload.get("embedding", {}),
    }
    rows = "\n".join(
        f"<li>{escape(edge['source'])} - {escape(edge['target'])}: {edge.get('weight', edge.get('score'))}</li>"
        for edge in payload["edges"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8" />
<title>LitAudit semantic paper map</title>
<body>
<h1>LitAudit semantic paper map</h1>
<p>PyVis 未安装，因此输出静态边列表。应用内 UI 仍提供力学动画、悬停与拖拽。</p>
<p>Embedding: {escape(str(payload["embedding"]))}; threshold={escape(str(payload["threshold"]))}</p>
<ul>{rows}</ul>
</body>
</html>
"""
