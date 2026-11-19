from datetime import date

from src.map_builder import build_map, similarity_edges
from src.schema import Dataset, PaperCard, PaperDecision


def _paper(paper_id: str, title: str, abstract: str) -> PaperCard:
    return PaperCard(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        source="test",
        retrieved_at=date(2026, 1, 1),
        dedup_key=paper_id,
        decision=PaperDecision.include,
        reason="test",
        doi_or_arxiv=f"https://example.test/{paper_id}",
    )


def test_semantic_map_uses_title_abstract_embeddings_and_cosine_edges():
    dataset = Dataset(
        papers=[
            _paper("paper-a", "Retrieval augmented literature review", "Scientific papers are retrieved for grounded answers."),
            _paper("paper-b", "Retrieval augmented literature review", "Scientific papers are retrieved for grounded answers."),
            _paper("paper-c", "Air pollution sensor network", "Urban air quality sensors measure particulate pollution."),
        ]
    )
    map_payload = build_map(dataset, "semantic-test")
    kinds = {edge["kind"] for edge in map_payload["edges"]}
    assert map_payload["algorithm"] == "specter2_cosine_network"
    assert map_payload["embedding"]["dimension"] == 768
    assert map_payload["similarity_matrix"]["paper_ids"] == ["paper-a", "paper-b", "paper-c"]
    assert map_payload["layout"] == "specter2_cosine_mds"
    assert all(0 <= node["semantic_x"] <= 1 and 0 <= node["semantic_y"] <= 1 for node in map_payload["nodes"])
    assert "semantic_similarity" in kinds
    edge = next(edge for edge in map_payload["edges"] if edge["source"] == "paper-a" and edge["target"] == "paper-b")
    assert edge["weight"] == 1.0
    assert "不是引用" in edge["note"]


def test_similarity_graph_sparsifies_dense_threshold_candidates():
    papers = [_paper(f"paper-{index}", f"Paper {index}", "abstract") for index in range(6)]
    embeddings = {
        paper.paper_id: [1.0, index * 0.01]
        for index, paper in enumerate(papers)
    }
    embeddings = {
        paper_id: [value / (sum(item * item for item in vector) ** 0.5) for value in vector]
        for paper_id, vector in embeddings.items()
    }
    edges, _, candidate_count = similarity_edges(papers, embeddings, threshold=0.8, neighbors_per_paper=2)
    degrees = {paper.paper_id: 0 for paper in papers}
    for edge in edges:
        degrees[edge["source"]] += 1
        degrees[edge["target"]] += 1
    assert candidate_count == 15
    assert len(edges) < candidate_count
    assert all(degree >= 2 for degree in degrees.values())
