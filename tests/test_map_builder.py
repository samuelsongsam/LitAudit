from src.config import ROOT
from src.io_utils import load_dataset
from src.map_builder import build_map


def test_phase2_real_keeps_evidence_edges_and_adds_heuristics():
    dataset = load_dataset(ROOT / "runs" / "phase2-real" / "output")
    map_payload = build_map(dataset, "phase2-real")
    kinds = {edge["kind"] for edge in map_payload["edges"]}
    assert "evidence_conflict" in kinds
    assert "falsification" in kinds
    assert "decision_boundary" in kinds
    assert "track_affinity" in kinds
    heuristic = next(edge for edge in map_payload["edges"] if edge["kind"] == "track_affinity")
    assert "不是引用" in heuristic["note"]
