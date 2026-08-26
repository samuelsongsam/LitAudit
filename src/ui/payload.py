from __future__ import annotations

from src.ask import ask
from src.config import ROOT
from src.eval_metrics import evaluate
from src.replay import list_runs, load_run
from src.schema import dataset_stats, latest_screening_by_paper

SCOPE_QUESTION = (
    "在自动科研文献综述或研究问答中，相比无外部检索的 LLM，"
    "检索增强大模型智能体是否提高证据可追溯性与事实/任务质量？"
)


def _dump(model) -> dict:
    return model.model_dump(mode="json")


def build_payload(runs_dir, run_id: str) -> dict:
    loaded = load_run(runs_dir, run_id)
    dataset = loaded["dataset"]
    cards = dataset.card_by_id()
    latest = latest_screening_by_paper(dataset.screening)
    papers = []
    for paper in dataset.papers:
        card = cards.get(paper.paper_id)
        log = latest.get(paper.paper_id)
        papers.append(
            {
                **_dump(paper),
                "is_fixture": paper.is_fixture,
                "parse_status": None if card is None else card.parse_status,
                "parse_error": None if card is None else card.parse_error,
                "fields": None if card is None or card.fields is None else _dump(card.fields),
                "latest_screening": None if log is None else _dump(log),
            }
        )
    return {
        "run_id": run_id,
        "scope_version": "v0.1",
        "question": SCOPE_QUESTION,
        "offline": True,
        "manifest": loaded.get("manifest") or {},
        "stats": loaded.get("stats") or dataset_stats(dataset),
        "map": loaded.get("map") or {},
        "eval": evaluate(ROOT),
        "papers": papers,
        "claims": [_dump(item) for item in dataset.claims],
        "evidence": [_dump(item) for item in dataset.evidence],
        "claim_decisions": [_dump(item) for item in dataset.claim_decisions],
        "falsification": [_dump(item) for item in dataset.falsification],
        "screening": [_dump(item) for item in dataset.screening],
        "retrieval_runs": [_dump(item) for item in dataset.retrieval_runs],
        "queries": [_dump(item) for item in dataset.queries],
    }


def list_available_runs(runs_dir) -> list[str]:
    return list_runs(runs_dir)


def ask_payload(runs_dir, run_id: str, question: str) -> dict:
    dataset = load_run(runs_dir, run_id)["dataset"]
    return ask(dataset, question)
