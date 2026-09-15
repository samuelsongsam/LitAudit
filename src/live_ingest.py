from __future__ import annotations

import re
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path

from src.cache import FileCache
from src.config import Settings
from src.retrieve import LiveHit, expand_question, hit_keys, search_all, title_key
from src.schema import (
    Claim,
    ClaimDecision,
    ClaimSource,
    ClaimStatus,
    Dataset,
    PaperCard,
    PaperDecision,
    PaperFields,
    QueryPlan,
    QueryPlanStatus,
    ResearchQuestion,
    ScreeningLog,
    ScreeningStage,
    SnapshotStatus,
    SourceSnapshot,
    validate_dataset,
)
from src.screen_rules import screen_title_abstract

SCOPE_QUESTION = (
    "在自动科研文献综述或研究问答中，相比无外部检索的 LLM，"
    "检索增强大模型智能体是否提高证据可追溯性与事实/任务质量？"
)
RANK = {PaperDecision.include: 0, PaperDecision.pending: 1, PaperDecision.exclude: 2}


def next_numeric_id(prefix: str, existing: list[str], width: int = 3) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    numbers = [int(match.group(1)) for item in existing if (match := pattern.match(item))]
    return f"{prefix}-{max(numbers, default=0) + 1:0{width}d}"


def paper_keys(paper: PaperCard) -> set[str]:
    keys = {paper.dedup_key.lower()}
    from src.retrieve import extract_arxiv_id, normalize_doi

    arxiv_id = extract_arxiv_id(paper.doi_or_arxiv) or extract_arxiv_id(paper.url)
    if arxiv_id:
        keys.add(f"arxiv:{arxiv_id}")
    doi = normalize_doi(paper.doi_or_arxiv)
    if doi and not doi.startswith("10.48550"):
        keys.add(f"doi:{doi}")
    if paper.title:
        keys.add(f"title:{title_key(paper.title)}")
    return keys


def _unique_hits(hits: list[LiveHit], dataset: Dataset) -> tuple[list[LiveHit], int]:
    occupied: set[str] = set()
    for paper in dataset.papers:
        occupied.update(paper_keys(paper))
    unique: list[LiveHit] = []
    skipped = 0
    seen: set[str] = set()
    for hit in hits:
        keys = hit_keys(hit)
        if keys & occupied or keys & seen:
            skipped += 1
            continue
        unique.append(hit)
        seen.update(keys)
        occupied.update(keys)
    return unique, skipped


def _to_card(paper_id: str, hit: LiveHit, decision: PaperDecision, reason: str) -> PaperCard:
    today = date.today()
    year = None
    if hit.year is not None:
        try:
            year = int(hit.year)
        except (TypeError, ValueError):
            year = None
    return PaperCard(
        paper_id=paper_id,
        title=hit.title,
        authors=hit.authors or None,
        year=year,
        venue=hit.venue,
        doi_or_arxiv=hit.doi_or_arxiv,
        url=hit.url,
        source=hit.source,
        abstract=hit.abstract,
        source_id=hit.source_id,
        open_access_pdf_url=hit.open_access_pdf_url,
        citation_count=hit.citation_count,
        reference_count=hit.reference_count,
        fields_of_study=hit.fields_of_study,
        publication_types=hit.publication_types,
        tldr=hit.tldr,
        semantic_score=hit.semantic_score,
        lexical_score=hit.lexical_score,
        ranking_score=hit.ranking_score,
        semantic_scholar_id=hit.semantic_scholar_id,
        retrieved_at=today,
        dedup_key=hit.dedup_key,
        decision=decision,
        reason=reason,
        fields=PaperFields(
            task="在线标题/摘要筛选，尚未抽取任务字段。",
            method=None,
            data=None,
            metrics=None,
            claims=None,
            limitations="没有页码级 Evidence，不能把相关论断标为 supported。",
        ),
        parse_status="live_abstract",
        parse_error="在线摘要筛选，尚未全文核验。不能据此把论断标为 supported。",
    )


def _maybe_user_claim(dataset: Dataset, question: str | None) -> tuple[list[Claim], list[ClaimDecision]]:
    text = (question or "").strip()
    if not text or text == SCOPE_QUESTION:
        return [], []
    if any(claim.text.strip() == text for claim in dataset.claims):
        return [], []
    claim_id = next_numeric_id("claim", [item.claim_id for item in dataset.claims])
    claim = Claim(
        claim_id=claim_id,
        text=text,
        source=ClaimSource.user_idea,
        paper_id=None,
        status=ClaimStatus.pending,
        decision_reason="在线检索只完成标题摘要筛选，尚未建立页码级 Evidence，不能进入 supported。",
    )
    decision = ClaimDecision(
        claim_id=claim_id,
        status=ClaimStatus.pending,
        evidence_ids=[],
        reason="无 Evidence 的用户问题保持 pending。",
        reviewer="litaudit-live",
        reviewed_at=date.today(),
        scope_version="v0.1",
    )
    return [claim], [decision]


def _audit_objects(dataset: Dataset, question: str, queries, retrieval_runs) -> tuple[list, list, list]:
    now = datetime.now(timezone.utc)
    question_id = next_numeric_id("rq", [item.question_id for item in dataset.research_questions])
    research_question = ResearchQuestion(
        question_id=question_id,
        text=question,
        domain_boundary="由本轮对话范围确认结果限定；未提供的结构化边界保持空值。",
        scope_version="v0.2",
    )
    query_plan_id = next_numeric_id("qp", [item.query_plan_id for item in dataset.query_plans])
    query_plan = QueryPlan(
        query_plan_id=query_plan_id,
        question_id=question_id,
        query_ids=[item.query_id for item in queries],
        reverse_terms=[item.query for item in queries if "风险" in (item.purpose or "") or "反" in (item.purpose or "")],
        status=QueryPlanStatus.executed,
        scope_version="v0.2",
        created_at=now,
    )
    snapshot_ids = [item.snapshot_id for item in dataset.source_snapshots]
    snapshots: list[SourceSnapshot] = []
    for run in retrieval_runs:
        response_path = Path(run.response_path) if run.response_path else None
        response_exists = bool(response_path and response_path.is_file())
        if run.http_status == 429 or run.status == "rate_limited":
            status = SnapshotStatus.rate_limited
            error_code = "http_429"
        elif run.status != "success":
            status = SnapshotStatus.failed
            error_code = f"retrieval_{run.status}"
        elif run.result_count == 0:
            status = SnapshotStatus.zero_results
            error_code = None
        elif not response_exists:
            status = SnapshotStatus.failed
            error_code = "snapshot_file_missing"
        else:
            status = SnapshotStatus.success
            error_code = None
        snapshot_id = next_numeric_id("snapshot", snapshot_ids)
        snapshot_ids.append(snapshot_id)
        snapshots.append(
            SourceSnapshot(
                snapshot_id=snapshot_id,
                retrieval_id=run.retrieval_id,
                source=run.source,
                status=status,
                retrieved_at=now,
                response_path=str(response_path) if response_exists else None,
                content_sha256=sha256(response_path.read_bytes()).hexdigest() if response_exists else None,
                error_code=error_code,
                error_message=run.notes if status in {SnapshotStatus.failed, SnapshotStatus.rate_limited} else None,
            )
        )
    return [research_question], [query_plan], snapshots


def ingest_live(
    dataset: Dataset,
    settings: Settings,
    *,
    question: str | None,
    cache: FileCache,
    run_dir: Path,
    fetch=None,
) -> tuple[Dataset, dict]:
    kwargs = {
        "cache_dir": cache.cache_dir,
        "mailto": settings.openalex_mailto,
        "semantic_scholar_api_key": settings.semantic_scholar_api_key,
        "limit_per_source": 15,
        "sleep_s": 0.35,
    }
    if fetch is not None:
        kwargs["fetch"] = fetch
        kwargs["sleep_s"] = 0.0
    bundle = search_all(question, **kwargs)
    unique_hits, skipped = _unique_hits(bundle.hits, dataset)
    hit_key_set = set().union(*(hit_keys(hit) for hit in bundle.hits)) if bundle.hits else set()
    matched_existing = [p for p in dataset.papers if paper_keys(p) & hit_key_set and not p.is_fixture]
    matched_hits = {
        paper.paper_id: next((hit for hit in bundle.hits if paper_keys(paper) & hit_keys(hit)), None)
        for paper in matched_existing
    }
    research_query = expand_question(question or "") if question else None
    screened: list[tuple[LiveHit, object]] = []
    for hit in unique_hits:
        result = screen_title_abstract(hit.title, hit.abstract, hit.year, research_query=research_query)
        screened.append((hit, result))
    screened.sort(key=lambda item: (RANK[item[1].decision], item[0].title.lower()))
    screened = screened[: settings.live_limit]

    paper_ids = [paper.paper_id for paper in dataset.papers]
    screen_ids = [log.screening_id for log in dataset.screening]
    retrieval_ids = [run.retrieval_id for run in dataset.retrieval_runs]
    new_papers: list[PaperCard] = []
    new_logs: list[ScreeningLog] = []
    today = date.today()
    # Re-screen matched existing papers for this question without modifying data/.
    existing_updates = {}
    for paper in matched_existing:
        result = screen_title_abstract(paper.title, paper.abstract, paper.year, research_query=research_query)
        hit = matched_hits[paper.paper_id]
        existing_updates[paper.paper_id] = {
            "decision": result.decision,
            "reason": result.reason,
            "abstract": max(
                (value for value in (paper.abstract, hit.abstract if hit else None) if value),
                key=len,
                default=None,
            ),
            "source_id": paper.source_id or (hit.source_id if hit else None),
            "open_access_pdf_url": paper.open_access_pdf_url or (hit.open_access_pdf_url if hit else None),
            "citation_count": max(
                (value for value in (paper.citation_count, hit.citation_count if hit else None) if value is not None),
                default=None,
            ),
            "reference_count": max(
                (value for value in (paper.reference_count, hit.reference_count if hit else None) if value is not None),
                default=None,
            ),
            "fields_of_study": list(dict.fromkeys([*paper.fields_of_study, *(hit.fields_of_study if hit else [])])),
            "publication_types": list(dict.fromkeys([*paper.publication_types, *(hit.publication_types if hit else [])])),
            "tldr": paper.tldr or (hit.tldr if hit else None),
            "semantic_score": hit.semantic_score if hit else paper.semantic_score,
            "lexical_score": hit.lexical_score if hit else paper.lexical_score,
            "ranking_score": hit.ranking_score if hit else paper.ranking_score,
            "semantic_scholar_id": paper.semantic_scholar_id or (hit.semantic_scholar_id if hit else None),
        }
        screen_id = next_numeric_id("screen", screen_ids)
        screen_ids.append(screen_id)
        new_logs.append(ScreeningLog(
            screening_id=screen_id, paper_id=paper.paper_id, stage=ScreeningStage.title_abstract,
            decision=result.decision, reason_code=result.reason_code, reason=result.reason,
            checked_fields=["title", "abstract", "year"], reviewer="litaudit-live",
            reviewed_at=today, scope_version="v0.1"))
    for hit, result in screened:
        paper_id = next_numeric_id("paper", paper_ids)
        paper_ids.append(paper_id)
        card = _to_card(paper_id, hit, result.decision, result.reason)
        new_papers.append(card)
        screen_id = next_numeric_id("screen", screen_ids)
        screen_ids.append(screen_id)
        new_logs.append(
            ScreeningLog(
                screening_id=screen_id,
                paper_id=paper_id,
                stage=ScreeningStage.title_abstract,
                decision=result.decision,
                reason_code=result.reason_code,
                reason=result.reason,
                checked_fields=["title", "abstract", "doi_or_arxiv", "url", "year"],
                reviewer="litaudit-live",
                reviewed_at=today,
                scope_version="v0.1",
            )
        )

    retrieval_runs = list(dataset.retrieval_runs)
    new_retrieval_runs = []
    for run in bundle.runs:
        retrieval_id = next_numeric_id("retrieval", retrieval_ids)
        retrieval_ids.append(retrieval_id)
        remapped = run.model_copy(update={"retrieval_id": retrieval_id})
        retrieval_runs.append(remapped)
        new_retrieval_runs.append(remapped)

    new_claims, new_decisions = _maybe_user_claim(dataset, question)
    audit_questions, audit_plans, source_snapshots = _audit_objects(
        dataset, question or SCOPE_QUESTION, bundle.queries, new_retrieval_runs
    )
    merged = dataset.model_copy(
        update={
            "research_questions": [*dataset.research_questions, *audit_questions],
            "query_plans": [*dataset.query_plans, *audit_plans],
            "queries": [*dataset.queries, *bundle.queries],
            "papers": [*[p.model_copy(update=existing_updates.get(p.paper_id, {})) for p in dataset.papers], *new_papers],
            "paper_cards": [*[p.model_copy(update=existing_updates.get(p.paper_id, {})) for p in dataset.paper_cards], *new_papers],
            "screening": [*dataset.screening, *new_logs],
            "claims": [*dataset.claims, *new_claims],
            "claim_decisions": [*dataset.claim_decisions, *new_decisions],
            "retrieval_runs": retrieval_runs,
            "source_snapshots": [*dataset.source_snapshots, *source_snapshots],
        }
    )
    merged = validate_dataset(merged)
    from src.io_utils import write_json
    write_json(run_dir / "output" / "citation_graph.json", bundle.citation_graph)
    report = {
        "question": question,
        "added_paper_ids": [paper.paper_id for paper in new_papers],
        "matched_paper_ids": [paper.paper_id for paper in matched_existing] + [paper.paper_id for paper in new_papers],
        "reused_paper_ids": [paper.paper_id for paper in matched_existing],
        "added_decisions": {paper.paper_id: paper.decision.value for paper in new_papers},
        "skipped_duplicates": skipped,
        "hit_count": len(bundle.hits),
        "retrieval": [
            {
                "retrieval_id": run.retrieval_id,
                "source": run.source,
                "status": run.status,
                "http_status": run.http_status,
                "result_count": run.result_count,
            }
            for run in retrieval_runs[len(dataset.retrieval_runs) :]
        ],
        "notes": bundle.notes,
        "citation_graph": {
            "seed_count": bundle.citation_graph.get("seed_count", 0),
            "edge_count": bundle.citation_graph.get("edge_count", 0),
            "failure_count": bundle.citation_graph.get("failure_count", 0),
        },
        "claim_008": next(
            (claim.status.value for claim in merged.claims if claim.claim_id == "claim-008"),
            None,
        ),
    }
    return merged, report
