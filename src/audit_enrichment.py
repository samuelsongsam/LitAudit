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
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from xml.etree import ElementTree

from src.io_utils import write_json, load_dataset, read_json
from src.pdf_download import PdfDownloadError, fetch_pdf
from src.run_paths import as_run_relative, resolve_run_file
from src.schema import (
    ActionStatus, Dataset, DecisionTrace, EvidenceSpan, NextAction, QueryPlan, ResearchQuestion,
    RetrievalRun, SourceSnapshot, validate_dataset,
)


def normalized_text(text: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", text).casefold())


_ARXIV_REF = re.compile(r"(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|[a-z.-]+/\d{7})(v\d+)?", re.I)


def _arxiv_reference(value: str) -> re.Match[str] | None:
    value = value.strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        path = parsed.path.split("/", 2)
        if len(path) == 3 and path[1] in {"abs", "pdf"}:
            return _ARXIV_REF.fullmatch(path[2].rstrip("/").removesuffix(".pdf"))
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"doi.org", "dx.doi.org"}:
        value = parsed.path.lstrip("/")
        if not value.lower().startswith("10.48550/arxiv."):
            return None
    return _ARXIV_REF.fullmatch(re.sub(r"^(?:arxiv:|(?:doi:\s*)?10\.48550/arxiv\.)\s*", "", value, flags=re.I))


def arxiv_pdf_url(paper) -> str | None:
    identifier = _arxiv_reference(paper.doi_or_arxiv or "")
    landing = _arxiv_reference(paper.url or "")
    # The catalog's normalized identifier can omit the version that the
    # retrieved landing page names. Keep that version for citation accuracy.
    if identifier is None or (landing and identifier[1].lower() == landing[1].lower() and not identifier[2]):
        identifier = landing
    return f"https://arxiv.org/pdf/{identifier[0].lower()}" if identifier else None


def _withdrawn_arxiv_pdf_urls(content: bytes) -> set[str]:
    if b"withdrawn" not in content.lower():
        return set()
    try:
        entries = ElementTree.fromstring(content).findall("{*}entry")
    except ElementTree.ParseError:
        return set()
    withdrawn = set()
    for entry in entries:
        comment = (entry.findtext("{*}comment") or "").strip()
        if re.match(r"(?:withdrawn\b|(?:this|the) (?:paper|submission) (?:has been|was) withdrawn\b)", comment, re.I):
            reference = _arxiv_reference(entry.findtext("{*}id") or "")
            if reference and reference[2]:
                withdrawn.add(f"https://arxiv.org/pdf/{reference[0].lower()}")
    return withdrawn


def provider_pdf_url(paper) -> str | None:
    """Accept provider-supplied public HTTPS PDF URLs while rejecting local targets."""
    value = (getattr(paper, "open_access_pdf_url", None) or "").strip()
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or host == "localhost" or host.endswith(".local"):
        return None
    try:
        if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
            return None
    except ValueError:
        pass
    return value


def _pdf_download_candidates(paper) -> list[tuple[str, str]]:
    arxiv_url, provider_url = arxiv_pdf_url(paper), provider_pdf_url(paper)
    candidates = [(arxiv_url, "arxiv_download")] if arxiv_url else []
    # A provider's copy may be another revision. An explicitly selected
    # arXiv revision must remain bound to its own PDF even when it disappears.
    if provider_url and provider_url != arxiv_url and not (arxiv_url and re.search(r"v\d+$", arxiv_url, re.I)):
        candidates.append((provider_url, "provider_open_access_pdf"))
    return candidates


def fulltext_pdf_url(paper) -> str | None:
    candidates = _pdf_download_candidates(paper)
    return candidates[0][0] if candidates else None


def _download_pdf(candidates: list[tuple[str, str]], target: Path) -> tuple[str, str]:
    for index, (url, source) in enumerate(candidates):
        try:
            fetch_pdf(url, target)
        except (URLError, TimeoutError, ValueError):
            if index + 1 == len(candidates):
                raise
        else:
            return url, source
    raise ValueError("fulltext_not_available")


def _pdf_error_code(error: Exception) -> str:
    if isinstance(error, PdfDownloadError):
        return str(error)
    if isinstance(error, HTTPError):
        return f"http_{error.code}"
    if isinstance(error, TimeoutError) or (isinstance(error, URLError) and isinstance(error.reason, TimeoutError)):
        return "pdf_timeout"
    if isinstance(error, URLError):
        return "pdf_connection_failed"
    if str(error) in {"pdf_too_large", "response_not_pdf", "pdf_processing_timeout"}:
        return str(error)
    return "pdf_parse_failed"


def _response_file(root: Path, run_dir: Path, source_dir: Path | None, stored_path: str | None,
                   citation_cache: Path | None = None) -> Path | None:
    if not stored_path:
        return None
    for directory in (source_dir, run_dir, citation_cache):
        if directory is not None:
            try:
                return resolve_run_file(directory, stored_path)
            except (ValueError, OSError):
                pass
    # Repository-local baseline responses predate run-relative snapshots.
    value = stored_path.replace("\\", "/")
    if ".." in value.split("/"):
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate.is_relative_to(root.resolve()) and candidate.is_file():
        return candidate
    if "/data/cache/" in value:
        relocated = (root / "data" / "cache" / value.split("/data/cache/", 1)[1]).resolve()
        if relocated.is_relative_to((root / "data" / "cache").resolve()) and relocated.is_file():
            return relocated
    return None


def _saved_extraction(source_dir: Path, document: dict, digest: str, *, retry_ocr: bool) -> dict | None:
    """Reuse validated page text for this exact PDF while retaining stable citations."""
    if document.get("status") != "parsed" or document.get("document_sha256") != digest:
        return None
    coverage, capabilities = document.get("coverage"), document.get("processing_capabilities")
    if not isinstance(coverage, dict) or not isinstance(capabilities, dict):
        return None
    if retry_ocr and coverage.get("ocr_required_pages"):
        return None
    try:
        pages = read_json(resolve_run_file(source_dir, document.get("text_path") or ""))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(pages, list) or not 1 <= len(pages) <= 300 or len(pages) != document.get("page_count"):
        return None
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page") != index or not isinstance(page.get("text"), str):
            return None
        if page.get("text_sha256") != sha256(page["text"].encode()).hexdigest():
            return None
    if not any(page["text"].strip() for page in pages):
        return None
    return {"pages": pages, "coverage": coverage, "capabilities": capabilities,
            "backend": document.get("processing_backend") or "saved_page_text"}


def _carry_fulltext_audit(source_dir: Path, run_dir: Path, dataset: Dataset, visible_ids: set[str] | None) -> None:
    """Keep stored page evidence when only catalog records and citation edges change."""
    from src.research_workspace import _portable
    from src.tasks import check_cancelled

    source_output, output = source_dir / "output", run_dir / "output"
    audit_path = source_output / "fulltext_audit.json"
    audit = read_json(audit_path) if audit_path.exists() else {}
    prior = {row["paper_id"]: row for row in audit.get("documents", [])
             if isinstance(row, dict) and isinstance(row.get("paper_id"), str)}
    documents = []
    for paper in dataset.real_papers():
        check_cancelled()
        paper_id = paper.paper_id
        if visible_ids is not None and paper_id not in visible_ids:
            continue
        original = prior.get(paper_id)
        if original is None:
            documents.append({"paper_id": paper_id, "status": "missing", "error_code": "fulltext_not_available",
                              "page_count": 0})
            continue
        row = dict(original)
        for key in ("response_path", "text_path"):
            if not row.get(key):
                continue
            try:
                path = resolve_run_file(source_dir, row[key])
            except (OSError, ValueError):
                row.pop(key)
                continue
            relative = path.relative_to(source_dir)
            target = run_dir / relative
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            row[key] = relative.as_posix()
        if row.get("status") == "parsed" and not row.get("text_path"):
            row.update(status="missing", error_code="fulltext_not_available", page_count=0)
        documents.append(row)
    audit["documents"] = documents
    for filename in ("fulltext_index.json", "document_structure.json"):
        path = source_output / filename
        if path.is_file():
            write_json(output / filename, _portable(read_json(path), source_dir, run_dir.name))
    write_json(output / "fulltext_audit.json", _portable(audit, source_dir, run_dir.name))


def enrich_audit(dataset: Dataset, *, root: Path, run_dir: Path,
                 question: str, visible_ids: set[str] | None = None,
                 acquire: bool = False, source_dir: Path | None = None,
                 acquire_ids: set[str] | None = None,
                 imported_pdfs: dict[str, str] | None = None,
                 reuse_from_run: str | None = None, citation_cache: Path | None = None) -> Dataset:
    from src.tasks import TaskCancelled, check_cancelled, report_progress

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
    withdrawn_pdf_urls = set()
    for retrieval in dataset.retrieval_runs:
        check_cancelled()
        existing = snapshots.get(retrieval.retrieval_id)
        path = _response_file(root, run_dir, source_dir, retrieval.response_path, citation_cache)
        digest = None
        copied = None
        if path and path.is_file():
            content = path.read_bytes()
            if (acquire and retrieval.source == "arxiv" and retrieval.status == "success"
                    and retrieval.request.startswith("https://export.arxiv.org/api/query?")):
                withdrawn_pdf_urls.update(_withdrawn_arxiv_pdf_urls(content))
            digest = sha256(content).hexdigest()
            copied = cache / f"response-{sha256(retrieval.retrieval_id.encode()).hexdigest()[:16]}{path.suffix}"
            if citation_cache is not None and source_dir and path.is_relative_to(source_dir / "cache"):
                copied = run_dir / path.relative_to(source_dir)
                copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(content)
            retrieval.response_path = as_run_relative(run_dir, copied)
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
            response_path=as_run_relative(run_dir, copied) if copied else None, content_sha256=digest,
            error_code=error, error_message=retrieval.notes if error else None)

    if citation_cache is not None and source_dir:
        dataset.source_snapshots = list(snapshots.values())
        _carry_fulltext_audit(source_dir, run_dir, dataset, visible_ids)
        return validate_dataset(dataset)

    cards = dataset.card_by_id()
    documents = []
    doc_by_paper = {}
    pages_by_paper = {}
    structures = []
    download_count = 0
    previous_documents = {}
    if source_dir:
        try:
            previous_audit = read_json(source_dir / "output" / "fulltext_audit.json")
            previous_documents = {d["paper_id"]: d for d in previous_audit.get("documents", [])
                                  if isinstance(d, dict) and isinstance(d.get("paper_id"), str)}
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    baseline = {p.paper_id: p for p in load_dataset(root / "data").papers} if (root / "data" / "papers.jsonl").exists() else {}
    for paper in sorted(dataset.real_papers(), key=lambda p: {"include": 0, "pending": 1, "exclude": 2}[p.decision.value]):
        check_cancelled()
        if visible_ids is not None and paper.paper_id not in visible_ids:
            continue
        key = sha256(paper.paper_id.encode()).hexdigest()[:16]
        target = cache / f"document-{key}.pdf"
        # Only use baseline files for the same stable paper identity.
        original = baseline.get(paper.paper_id)
        same_identity = original is not None and original.dedup_key == paper.dedup_key
        if same_identity:
            requested_arxiv_url = arxiv_pdf_url(paper)
            if requested_arxiv_url and re.search(r"v\d+$", requested_arxiv_url, re.I):
                same_identity = arxiv_pdf_url(original) == requested_arxiv_url
        local_candidates = list((root / "data" / "cache").glob(f"*/pdf/{paper.paper_id}.pdf")) if same_identity and re.fullmatch(r"paper-\d+", paper.paper_id) else []
        imported_source = (imported_pdfs or {}).get(paper.paper_id)
        previous_document = previous_documents.get(paper.paper_id, {})
        if source_dir:
            local_candidates.insert(0, source_dir / "cache" / "audit" / target.name)
            stored = previous_document.get("response_path")
            if not imported_source and isinstance(stored, str):
                try:
                    # Imported/relocated workspaces may use another portable
                    # path. Reuse only a file contained in this source run.
                    local_candidates.insert(0, resolve_run_file(source_dir, stored))
                except (ValueError, OSError):
                    pass
        existing_doc = next((p for p in local_candidates if p.is_file()), None)
        requested = acquire and (acquire_ids is None or paper.paper_id in acquire_ids)
        candidates = _pdf_download_candidates(paper) if requested and not existing_doc else []
        row = {"paper_id": paper.paper_id, "status": "missing", "error_code": "fulltext_not_available", "page_count": 0}
        if candidates and candidates[0][0] in withdrawn_pdf_urls:
            row.update(status="failed", error_code="arxiv_withdrawn")
            candidates = []
        download_url = None
        extracted_dir = source_dir
        retrieved_at = now
        try:
            if candidates and candidates[0][1] == "arxiv_download" and reuse_from_run:
                from src.fulltext_reuse import find_versioned_arxiv_pdf
                saved = find_versioned_arxiv_pdf(run_dir.parent, reuse_from_run, paper.paper_id, candidates[0][0])
                if saved:
                    existing_doc, extracted_dir, previous_document = saved.path, saved.run_dir, saved.document
                    download_url, retrieved_at = candidates[0][0], saved.retrieved_at
            if existing_doc:
                if existing_doc.resolve() != target.resolve():
                    shutil.copyfile(existing_doc, target)
                row["acquisition"] = "arxiv_saved_copy" if download_url else "local_copy"
            elif candidates and download_count < 5:
                download_count += 1
                report_progress("fulltext_download", run_id=run_dir.name)
                download_url, row["acquisition"] = _download_pdf(candidates, target)
            else:
                if candidates and download_count >= 5:
                    row["error_code"] = "batch_limit_retry_remaining"
                documents.append(row)
                continue
            content = target.read_bytes()
            digest = sha256(content).hexdigest()
            retrieval_id = f"fulltext-{key}"
            snapshot_id = f"snapshot-fulltext-{key}"
            request = download_url or imported_source
            if not request and previous_document.get("document_sha256") == digest:
                previous_retrieval = next((r for r in dataset.retrieval_runs if r.retrieval_id == retrieval_id), None)
                if previous_retrieval:
                    request = previous_retrieval.request
                    previous_snapshot = snapshots.get(retrieval_id)
                    if (previous_retrieval.source == "arxiv_download" and previous_snapshot
                            and previous_snapshot.source == "arxiv_download" and previous_snapshot.status == "success"
                            and previous_snapshot.content_sha256 == digest and request == arxiv_pdf_url(paper)):
                        row["acquisition"] = "arxiv_saved_copy"
                        retrieved_at = previous_snapshot.retrieved_at
            retrieval_source = "arxiv_download" if row["acquisition"] == "arxiv_saved_copy" else row["acquisition"]
            dataset.retrieval_runs = [r for r in dataset.retrieval_runs if r.retrieval_id != retrieval_id]
            dataset.retrieval_runs.append(RetrievalRun(
                retrieval_id=retrieval_id, query_id="fulltext-acquisition", source=retrieval_source,
                request=request or paper.url or paper.paper_id,
                retrieved_at=retrieved_at.date(), status="success", result_count=1,
                response_path=as_run_relative(run_dir, target), notes="本次保存全文文件；不代表已审阅全文。"))
            snapshots[retrieval_id] = SourceSnapshot(
                snapshot_id=snapshot_id, retrieval_id=retrieval_id, source=retrieval_source,
                status="success", retrieved_at=retrieved_at, response_path=as_run_relative(run_dir, target), content_sha256=digest)
            row.update(snapshot_id=snapshot_id, document_sha256=digest, response_path=as_run_relative(run_dir, target))
            processed = (_saved_extraction(extracted_dir, previous_document, digest, retry_ocr=requested)
                         if acquire and acquire_ids is not None and extracted_dir else None)
            if processed is None:
                from src.document_processing import read_document
                if acquire:
                    report_progress("fulltext_extract", run_id=run_dir.name)
                processed = read_document(target, timeout_seconds=60 if acquire else None)
            page_rows = processed["pages"]
            pages = [page["text"] for page in page_rows]
            text_path = cache / f"document-{key}-pages.json"
            write_json(text_path, page_rows)
            has_text = any(text.strip() for text in pages)
            row.update(status="parsed" if has_text else "needs_ocr", error_code=None if has_text else "ocr_required",
                       page_count=len(pages), text_path=as_run_relative(run_dir, text_path),
                       coverage=processed["coverage"], processing_capabilities=processed["capabilities"],
                       processing_backend=processed["backend"],
                       structure_path="output/document_structure.json")
            if has_text:
                pages_by_paper[paper.paper_id] = pages
            structures.append({"paper_id": paper.paper_id, "backend": processed["backend"],
                               "coverage": processed["coverage"], "capabilities": processed["capabilities"],
                               "pages": [{k: v for k, v in page.items() if k != "text"} for page in page_rows]})
        except Exception as exc:
            if isinstance(exc, TaskCancelled):
                raise
            row.update(status="failed", error_code=_pdf_error_code(exc), error_message=str(exc)[:240])
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
        if row["status"] != "parsed" or row.get("coverage", {}).get("ocr_required_pages"):
            error_code = row.get("error_code")
            reason = {
                "fulltext_not_available": "尚未取得可解析的开放全文。",
                "batch_limit_retry_remaining": "本批次全文获取已达上限，可在下一批继续。",
                "ocr_required": "该文件需要 OCR 后才能建立页码文本索引。",
                "arxiv_withdrawn": "该 arXiv 版本已撤回。可在论文来源页查看撤回说明和版本记录。",
                "http_404": "来源未提供该版本的 PDF。可查看论文来源页或导入已有 PDF。",
                "http_410": "来源已移除该版本的 PDF。可查看论文来源页或导入已有 PDF。",
                "http_429": "论文来源暂时限制下载。可稍后重试或导入本地 PDF。",
            }.get(error_code, "全文获取或解析失败，需要复核来源文件。")
            if row.get("coverage", {}).get("ocr_required_pages"):
                reason = "以下PDF页需要OCR或人工阅读：" + "、".join(map(str, row["coverage"]["ocr_required_pages"]))
            action("acquire_fulltext", "paper", row["paper_id"], reason)
            if row.get("coverage", {}).get("ocr_required_pages"):
                actions[("acquire_fulltext", "paper", row["paper_id"])].status = ActionStatus.open
    for check in checks:
        if check["status"] != "matched":
            action("verify_evidence", "evidence", check["evidence_id"], "指定页未精确匹配摘录，需人工核对排版、OCR 或摘录差异。")
    from src.schema import ActionStatus
    for row in documents:
        existing = actions.get(("acquire_fulltext", "paper", row["paper_id"]))
        if existing and row["status"] == "parsed" and not row.get("coverage", {}).get("ocr_required_pages"):
            existing.status = ActionStatus.completed
    for check in checks:
        existing = actions.get(("verify_evidence", "evidence", check["evidence_id"]))
        if existing and check["status"] == "matched":
            existing.status = ActionStatus.completed
    from src.fulltext_search import build_fulltext_search
    if acquire:
        report_progress("fulltext_save", run_id=run_dir.name)
    fulltext_search = build_fulltext_search(
        question, cards, pages_by_paper, semantic_rerank=not (acquire and acquire_ids is not None))
    write_json(run_dir / "output" / "fulltext_index.json", fulltext_search)
    write_json(run_dir / "output" / "document_structure.json", {
        "version": "page-structure-v1", "created_at": now.isoformat(), "documents": structures,
        "scope": "页面文本提取、表格候选和图像区域定位；图表、公式与语义判决须分别核查。"})
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
        "limitations": ["精确文本匹配只检查摘录位置，不判断语义支持，也不代表人工通读。", "全文下载支持 arXiv 及检索提供商声明的开放 PDF，每次最多 5 篇。", "扫描页仅在本地OCR引擎可用时处理；未处理页与表格/图像/公式状态逐页记录。"]})
    return validate_dataset(dataset)
