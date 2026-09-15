"""Build reproducible audit artifacts without changing source gold data.

Text matching checks location, never the semantic truth of a claim. Historical
human verdicts are preserved and their provenance is explicitly labelled.
"""
from __future__ import annotations

import re
import shutil
import unicodedata
import ipaddress
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from src.io_utils import write_json, load_dataset
from src.schema import (
    Dataset, DecisionTrace, EvidenceSpan, NextAction, QueryPlan, ResearchQuestion,
    RetrievalRun, SourceSnapshot, validate_dataset,
)


def normalized_text(text: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", text).casefold())


def arxiv_pdf_url(paper) -> str | None:
    for value in (paper.doi_or_arxiv or "", paper.url or ""):
        match = re.search(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/|^)(\d{4}\.\d{4,5}(?:v\d+)?)", value, re.I)
        if match:
            return f"https://arxiv.org/pdf/{match.group(1)}"
    return None


def provider_pdf_url(paper) -> str | None:
    """Accept provider-supplied public HTTPS PDF URLs while rejecting local targets."""
    value = (getattr(paper, "open_access_pdf_url", None) or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or host == "localhost" or host.endswith(".local"):
        return None
    try:
        if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
            return None
    except ValueError:
        pass
    return value


def fulltext_pdf_url(paper) -> str | None:
    return arxiv_pdf_url(paper) or provider_pdf_url(paper)


def fetch_pdf(url: str, target: Path) -> None:
    # URLs come from arXiv identifiers or provider-declared open-access PDF
    # locations, never from a browser parameter. Keep response size and wait bounded.
    with urlopen(Request(url, headers={"User-Agent": "LitAudit/0.2"}), timeout=25) as response:
        content = response.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("pdf_too_large")
    if not content.startswith(b"%PDF-"):
        raise ValueError("response_not_pdf")
    target.write_bytes(content)


def enrich_audit(dataset: Dataset, *, root: Path, run_dir: Path,
                 question: str, visible_ids: set[str] | None = None,
                 acquire: bool = False, source_dir: Path | None = None) -> Dataset:
    dataset = dataset.model_copy(deep=True)
    now = datetime.now(timezone.utc)
    cache = run_dir / "cache" / "audit"
    cache.mkdir(parents=True, exist_ok=True)
    if not dataset.research_questions:
        dataset.research_questions.append(ResearchQuestion(
            question_id="rq-audit", text=question, scope_version="v0.2"))
    if not dataset.query_plans and dataset.queries:
        dataset.query_plans.append(QueryPlan(
            query_plan_id="qp-audit", question_id=dataset.research_questions[-1].question_id,
            query_ids=[q.query_id for q in dataset.queries], status="executed",
            scope_version="v0.2", created_at=now))

    # Freeze every available response into this run; missing files are explicit.
    snapshots = {s.retrieval_id: s for s in dataset.source_snapshots}
    for retrieval in dataset.retrieval_runs:
        existing = snapshots.get(retrieval.retrieval_id)
        path = Path(retrieval.response_path) if retrieval.response_path else None
        if path and not path.is_absolute():
            path = root / path
        digest = None
        copied = None
        if path and path.is_file():
            content = path.read_bytes()
            digest = sha256(content).hexdigest()
            copied = cache / f"response-{sha256(retrieval.retrieval_id.encode()).hexdigest()[:16]}{path.suffix}"
            copied.write_bytes(content)
            retrieval.response_path = str(copied)
        if retrieval.http_status == 429 or retrieval.status == "rate_limited":
            status, error = "rate_limited", "http_429"
        elif retrieval.status != "success":
            status, error = "failed", retrieval.status
        elif not copied:
            status, error = "failed", "snapshot_file_missing"
        else:
            status, error = ("zero_results" if retrieval.result_count == 0 else "success"), None
        snapshots[retrieval.retrieval_id] = SourceSnapshot(
            snapshot_id=existing.snapshot_id if existing else f"snapshot-{retrieval.retrieval_id}",
            retrieval_id=retrieval.retrieval_id, source=retrieval.source, status=status,
            retrieved_at=existing.retrieved_at if existing else datetime.combine(retrieval.retrieved_at, datetime.min.time(), tzinfo=timezone.utc),
            response_path=str(copied) if copied else None, content_sha256=digest,
            error_code=error, error_message=retrieval.notes if error else None)

    cards = dataset.card_by_id()
    documents = []
    doc_by_paper = {}
    pages_by_paper = {}
    download_count = 0
    baseline = {p.paper_id: p for p in load_dataset(root / "data").papers} if (root / "data" / "papers.jsonl").exists() else {}
    for paper in sorted(dataset.real_papers(), key=lambda p: {"include": 0, "pending": 1, "exclude": 2}[p.decision.value]):
        if visible_ids is not None and paper.paper_id not in visible_ids:
            continue
        key = sha256(paper.paper_id.encode()).hexdigest()[:16]
        target = cache / f"document-{key}.pdf"
        # Only use baseline files for the same stable paper identity.
        original = baseline.get(paper.paper_id)
        same_identity = original is not None and original.dedup_key == paper.dedup_key
        local_candidates = list((root / "data" / "cache").glob(f"*/pdf/{paper.paper_id}.pdf")) if same_identity and re.fullmatch(r"paper-\d+", paper.paper_id) else []
        if source_dir:
            local_candidates.insert(0, source_dir / "cache" / "audit" / target.name)
        existing_doc = next((p for p in local_candidates if p.is_file()), None)
        row = {"paper_id": paper.paper_id, "status": "missing", "error_code": "fulltext_not_available", "page_count": 0}
        try:
            if existing_doc:
                shutil.copyfile(existing_doc, target)
                row["acquisition"] = "local_copy"
            elif acquire and fulltext_pdf_url(paper) and download_count < 5:
                download_count += 1
                fetch_pdf(fulltext_pdf_url(paper), target)
                row["acquisition"] = "arxiv_download" if arxiv_pdf_url(paper) else "provider_open_access_pdf"
            else:
                if acquire and download_count >= 5:
                    row["error_code"] = "batch_limit_retry_remaining"
                documents.append(row)
                continue
            content = target.read_bytes()
            digest = sha256(content).hexdigest()
            retrieval_id = f"fulltext-{key}"
            snapshot_id = f"snapshot-fulltext-{key}"
            dataset.retrieval_runs = [r for r in dataset.retrieval_runs if r.retrieval_id != retrieval_id]
            dataset.retrieval_runs.append(RetrievalRun(
                retrieval_id=retrieval_id, query_id="fulltext-acquisition", source=row["acquisition"],
                request=fulltext_pdf_url(paper) or paper.url or paper.paper_id,
                retrieved_at=now.date(), status="success", result_count=1,
                response_path=str(target), notes="本次保存全文文件；不代表已审阅全文。"))
            snapshots[retrieval_id] = SourceSnapshot(
                snapshot_id=snapshot_id, retrieval_id=retrieval_id, source=row["acquisition"],
                status="success", retrieved_at=now, response_path=str(target), content_sha256=digest)
            row.update(snapshot_id=snapshot_id, document_sha256=digest, response_path=str(target))
            from pypdf import PdfReader
            reader = PdfReader(target)
            if len(reader.pages) > 300:
                raise ValueError("page_limit_exceeded")
            pages = [page.extract_text() or "" for page in reader.pages]
            if not any(text.strip() for text in pages):
                raise ValueError("ocr_required")
            text_path = cache / f"document-{key}-pages.json"
            write_json(text_path, [{"page": i + 1, "text": text} for i, text in enumerate(pages)])
            row.update(status="parsed", error_code=None, page_count=len(pages), text_path=str(text_path))
            pages_by_paper[paper.paper_id] = pages
        except (OSError, ValueError, ImportError, HTTPError) as exc:
            row.update(status="failed", error_code="http_429" if isinstance(exc, HTTPError) and exc.code == 429 else type(exc).__name__, error_message=str(exc)[:240])
        except Exception as exc:
            row.update(status="failed", error_code="pdf_parse_failed", error_message=str(exc)[:240])
        documents.append(row)
        doc_by_paper[paper.paper_id] = row

    spans = {span.evidence_id: span for span in dataset.evidence_spans}
    checks = []
    for evidence in dataset.evidence:
        if visible_ids is not None and evidence.paper_id not in visible_ids:
            continue
        row = doc_by_paper.get(evidence.paper_id, {})
        pages = pages_by_paper.get(evidence.paper_id, [])
        page = evidence.locator.page
        needle = normalized_text(evidence.snippet)
        matched = bool(needle and page and 0 < page <= len(pages) and needle in normalized_text(pages[page - 1]))
        # Preserve historical evidence verdicts, but require a fresh location
        # match for a new verified span. Never invent a historical review date.
        status = "verified" if matched and evidence.extraction_status.value == "verified" else "abstract_only" if evidence.extraction_status.value == "abstract_only" else "unverified"
        spans[evidence.evidence_id] = EvidenceSpan(
            span_id=f"span-{evidence.evidence_id}", evidence_id=evidence.evidence_id,
            paper_id=evidence.paper_id, snapshot_id=row.get("snapshot_id"),
            document_version=row.get("document_sha256", "fulltext-missing"),
            snippet_sha256=sha256(evidence.snippet.encode()).hexdigest(),
            locator=evidence.locator, extraction_status=status,
            verified_at=now if status == "verified" else None)
        checks.append({"evidence_id": evidence.evidence_id, "paper_id": evidence.paper_id,
                       "page": page, "status": "matched" if matched else "needs_review",
                       "method": "normalized_exact_page_match", "historical_verdict_preserved": True})

    traces = {t.claim_id: t for t in dataset.decision_traces}
    actions = {(a.kind.value, a.target_type, a.target_id): a for a in dataset.next_actions}
    def action(kind, target_type, target_id, reason, priority=1):
        key = (kind, target_type, target_id)
        if key not in actions:
            actions[key] = NextAction(action_id="action-" + sha256("|".join(key).encode()).hexdigest()[:16], kind=kind, target_type=target_type, target_id=target_id, reason=reason, priority=priority, created_at=now)
    for claim in dataset.claims:
        related = [e for e in dataset.evidence if e.claim_id == claim.claim_id]
        conflict = any(e.verdict.value == "contradicts" for e in related)
        traces[claim.claim_id] = DecisionTrace(
            trace_id=f"trace-{claim.claim_id}", claim_id=claim.claim_id,
            evidence_ids=[e.evidence_id for e in related], rule_status=claim.status,
            final_status=claim.status, conflict_detected=conflict,
            rationale="保留原 Claim 判决，执行关联与状态校验；未新增模型或人工判决。" + claim.decision_reason,
            rule_version="legacy-projection-v0.2", created_at=now)
        if claim.status.value in {"pending", "partial"}:
            action("resolve_conflict" if conflict else "verify_evidence", "claim", claim.claim_id,
                   "存在反证，需要人工复核冲突。" if conflict else "证据不足，需要补充或核验支持证据。", 0 if conflict else 1)
    for row in documents:
        if row["status"] != "parsed":
            error_code = row.get("error_code")
            reason = {
                "fulltext_not_available": "尚未取得可解析的开放全文。",
                "batch_limit_retry_remaining": "本批次全文获取已达上限，可在下一批继续。",
                "ocr_required": "该文件需要 OCR 后才能建立页码文本索引。",
            }.get(error_code, "全文获取或解析失败，需要复核来源文件。")
            action("acquire_fulltext", "paper", row["paper_id"], reason)
    for check in checks:
        if check["status"] != "matched":
            action("verify_evidence", "evidence", check["evidence_id"], "指定页未精确匹配摘录，需人工核对排版、OCR 或摘录差异。")
    from src.schema import ActionStatus
    for row in documents:
        existing = actions.get(("acquire_fulltext", "paper", row["paper_id"]))
        if existing and row["status"] == "parsed":
            existing.status = ActionStatus.completed
    for check in checks:
        existing = actions.get(("verify_evidence", "evidence", check["evidence_id"]))
        if existing and check["status"] == "matched":
            existing.status = ActionStatus.completed
    from src.fulltext_search import build_fulltext_search
    fulltext_search = build_fulltext_search(question, cards, pages_by_paper)
    write_json(run_dir / "output" / "fulltext_index.json", fulltext_search)
    dataset.source_snapshots = list(snapshots.values())
    dataset.evidence_spans = list(spans.values())
    dataset.decision_traces = list(traces.values())
    dataset.next_actions = list(actions.values())
    write_json(run_dir / "output" / "fulltext_audit.json", {
        "created_at": now.isoformat(), "documents": documents, "checks": checks,
        "search_index": {
            "algorithm": fulltext_search["algorithm"],
            "passage_count": fulltext_search["passage_count"],
            "hit_count": len(fulltext_search["hits"]),
        },
        "limitations": ["精确文本匹配只检查摘录位置，不判断语义支持，也不代表人工通读。", "全文下载支持 arXiv 及检索提供商声明的开放 PDF，每次最多 5 篇；扫描 PDF 需要另行 OCR。"]})
    return validate_dataset(dataset)
