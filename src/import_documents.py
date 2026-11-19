"""Create an independent research record from a user-selected PDF."""
from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import re

from src.config import Settings
from src.io_utils import write_json
from src.pipeline import new_run_id, snapshot_dataset, unavailable_map
from src.run_paths import resolve_run_dir
from src.schema import Dataset, PaperCard, ScreeningLog, dataset_stats


def import_pdf(settings: Settings, body: dict) -> dict:
    encoded = body.get('content_base64')
    filename = body.get('filename', 'paper.pdf')
    parent = body.get('run_id')
    selected = body.get('paper_id')
    if selected is not None and (not isinstance(selected, str) or not selected or not parent):
        raise ValueError('请选择当前研究中的论文')
    if not isinstance(filename, str) or not filename.lower().endswith('.pdf'):
        raise ValueError('请选择PDF文件')
    if not isinstance(encoded, str) or len(encoded) > 35 * 1024 * 1024:
        raise ValueError('PDF文件不得超过25MB')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('PDF文件编码无效') from exc
    if not content.startswith(b'%PDF-') or len(content) > 25 * 1024 * 1024:
        raise ValueError('文件不是有效PDF或超过25MB')
    question = body.get('question') or '导入论文阅读与方法比较'
    title = body.get('title') or re.split(r'[/\\]', filename)[-1][:-4]
    if not isinstance(question, str) or not isinstance(title, str) or len(question) > 2000 or len(title) > 1000:
        raise ValueError('论文题名或研究问题格式无效')
    authors = body.get('authors') or []
    if not isinstance(authors, list) or len(authors) > 100 or any(not isinstance(a, str) or len(a) > 300 for a in authors):
        raise ValueError('authors必须是作者名称列表')
    year = body.get('year')
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1500 <= year <= date.today().year + 1):
        raise ValueError('发表年份无效')
    source_url = body.get('source_url')
    if source_url is not None and (not isinstance(source_url, str) or len(source_url) > 2000 or not source_url.startswith('https://')):
        raise ValueError('来源链接应为HTTPS地址')
    identifier = body.get('identifier')
    if identifier is not None and (not isinstance(identifier, str) or len(identifier) > 300):
        raise ValueError('论文标识格式无效')
    from pypdf import PdfReader
    import io
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError('请先提供未加密的PDF')
        if len(reader.pages) > 300:
            raise ValueError('PDF页数超过300页')
    except Exception as exc:
        raise ValueError('PDF无法读取：' + str(exc)[:150]) from exc
    digest = sha256(content).hexdigest()
    historical_ids = set()
    attached_manifest = {}
    visible_ids = None
    if parent:
        from src.research_workspace import fork_workspace
        from src.replay import load_run
        loaded = load_run(settings.runs_dir, parent)
        parent_manifest = loaded['manifest']
        from src.research_workspace import workspace_papers
        papers = workspace_papers(settings.runs_dir, parent, [selected] if selected is not None else None)
        if selected is None:
            duplicate = next((p for p in papers.values() if p.dedup_key == 'pdf:' + digest), None)
            if duplicate is not None:
                return {'run_id': parent, 'paper_id': duplicate.paper_id, 'duplicate': True,
                        'status': parent_manifest.get('status', 'completed'),
                        'notice': '这份PDF已在当前研究中，已打开原有阅读记录。', 'stats': dataset_stats(loaded['dataset'])}
        run_id = fork_workspace(settings.runs_dir, parent)['run_id']
        forked = load_run(settings.runs_dir, run_id)
        dataset = forked['dataset']
        if selected is not None:
            attached_manifest = dict(forked['manifest'])
            attached_manifest.pop('acquisition', None)
            question = body.get('question') or attached_manifest.get('question') or question
        historical_ids = {p.paper_id for p in dataset.papers}
        if parent_manifest.get('offline') is False:
            from src.run_scope import visible_paper_ids
            visible_ids = visible_paper_ids(parent_manifest.get('live') or {})
        if visible_ids is not None and selected is None:
            allowed = visible_ids
            evidence = [e for e in dataset.evidence if e.paper_id in allowed]
            claim_ids = {e.claim_id for e in evidence} | {c.claim_id for c in dataset.claims if c.paper_id in allowed}
            dataset = dataset.model_copy(update={
                'papers': [p for p in dataset.papers if p.paper_id in allowed],
                'paper_cards': [p for p in dataset.paper_cards if p.paper_id in allowed],
                'claims': [c for c in dataset.claims if c.claim_id in claim_ids], 'evidence': evidence,
                'claim_decisions': [c for c in dataset.claim_decisions if c.claim_id in claim_ids],
                'screening': [s for s in dataset.screening if s.paper_id in allowed],
                'falsification': [f for f in dataset.falsification if f.paper_id in allowed and f.target_claim in claim_ids],
                'evidence_spans': [s for s in dataset.evidence_spans if s.paper_id in allowed],
                'decision_traces': [t for t in dataset.decision_traces if t.claim_id in claim_ids],
                'next_actions': [], 'issues': [],
            })
            visible_ids = None
    else:
        run_id = new_run_id('import')
        dataset = Dataset()
    run_dir = resolve_run_dir(settings.runs_dir, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {**(attached_manifest or {'offline': True, 'source': 'user_pdf'}),
                'run_id': run_id, 'parent_run_id': parent,
                'question': question, 'status': 'running', 'stage': 'import_pdf',
                'created_at': datetime.now(timezone.utc).isoformat(), 'errors': [], 'cache_dir': 'cache'}
    write_json(run_dir / 'run_manifest.json', manifest)
    paper_id = selected
    if paper_id is None:
        ids = historical_ids | {p.paper_id for p in dataset.papers}
        index = 1
        while f'paper-{index:03}' in ids:
            index += 1
        paper_id = f'paper-{index:03}'
        paper = PaperCard(paper_id=paper_id, title=title, authors=authors, year=year,
                          url=source_url or f'local:sha256:{digest}', source='user_pdf',
                          doi_or_arxiv=identifier or None, retrieved_at=date.today(),
                          dedup_key='pdf:' + digest, decision='include',
                          reason='用户导入并选择纳入阅读，研究结论需结合原文核对。', parse_status='pdf_imported')
        dataset.papers.append(paper)
        dataset.paper_cards.append(paper.model_copy(deep=True))
        dataset.screening.append(ScreeningLog(
            screening_id='import-' + sha256((run_id + paper_id).encode()).hexdigest()[:16],
            paper_id=paper_id, stage='full_text', decision='include',
            reason_code='user_pdf_import', reason=paper.reason,
            checked_fields=['user_selection', 'pdf_readability'], reviewer='user_import',
            reviewed_at=date.today(), scope_version='user-defined'))
    # Keep the same document naming convention used by audit enrichment.
    key = sha256(paper_id.encode()).hexdigest()[:16]
    cache = run_dir / 'cache/audit'
    cache.mkdir(parents=True, exist_ok=True)
    pdf_path = cache / f'document-{key}.pdf'
    pdf_path.write_bytes(content)
    snapshot_dataset(dataset, run_dir / 'output')
    try:
        from src.audit_enrichment import enrich_audit
        imported_pdfs = {paper_id: source_url or f'local:sha256:{digest}'} if selected is not None else None
        dataset = enrich_audit(dataset, root=settings.root, run_dir=run_dir, question=question,
                              source_dir=run_dir, visible_ids=visible_ids, imported_pdfs=imported_pdfs)
        # Enrichment already validates the complete dataset.
        snapshot_dataset(dataset, run_dir / 'output')
        stats = dataset_stats(dataset)
        manifest.update(status='partial' if stats['error_count'] else 'completed', stage='finished', stats=stats)
        if stats['error_count']:
            manifest['errors'].append({'stage': 'validation', 'message': '数据校验发现问题，请查看validation_report.json'})
    except Exception as exc:
        from src.tasks import TaskCancelled
        if isinstance(exc, TaskCancelled):
            manifest.update(status='cancelled', stage='fulltext')
            write_json(run_dir / 'run_manifest.json', manifest)
            raise
        manifest.update(status='partial', stage='fulltext', errors=[{'stage': 'fulltext', 'message': str(exc)[:240]}])
    from src.map_builder import build_map, write_pyvis_html
    try:
        graph = build_map(dataset, run_id)
        write_json(run_dir / 'output/map.json', graph)
        write_pyvis_html(graph, run_dir / 'output/map.html')
    except Exception as exc:
        write_json(run_dir / 'output/map.json', unavailable_map(run_id, exc))
        manifest['status'] = 'partial'
        manifest['errors'].append({'stage': 'map', 'message': str(exc)[:240]})
    stats = dataset_stats(dataset)
    write_json(run_dir / 'stats.json', stats)
    write_json(run_dir / 'validation_report.json', [i.model_dump() for i in dataset.issues])
    write_json(run_dir / 'run_manifest.json', manifest)
    return {'run_id': run_id, 'paper_id': paper_id, 'status': manifest['status'], 'stats': stats}
