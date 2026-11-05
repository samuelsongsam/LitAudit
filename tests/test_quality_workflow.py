"""Reading exclusions, idempotent retry and supplementary-study persistence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from src.reading_scope import resolve_reading_scope
from src.tasks import TaskManager
from src.ui.server import LitAuditHandler


def terminal(manager, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.get(task_id)
        if job['status'] not in {'queued', 'running', 'cancel_requested'}:
            return job
        time.sleep(.005)
    raise AssertionError('Task did not finish')


@pytest.fixture
def reading_research():
    return {'offline': False, 'live': {'matched_paper_ids': ['paper-001', 'paper-002']},
            'papers': [{'paper_id': 'paper-001', 'title': 'QLoRA: Efficient Finetuning'},
                       {'paper_id': 'paper-002', 'title': 'LoRA: Low-Rank Adaptation'},
                       {'paper_id': 'paper-999', 'title': 'Hidden baseline'}]}


@pytest.mark.parametrize('question', [
    '不要再看QLoRA，请解释LoRA的方法',
    'Ignore QLoRA; read LoRA instead',
    'Exclude QLoRA and explain LoRA',
])
def test_explicit_reading_exclusions_do_not_keep_the_old_paper(reading_research, question):
    result = resolve_reading_scope(reading_research, question, selected='paper-001')
    assert result['paper_ids'] == ['paper-002']
    assert result['excluded_paper_ids'] == ['paper-001']


def test_scientific_negation_still_selects_both_named_methods(reading_research):
    question = 'LoRA不采用量化，而QLoRA采用量化，请比较两者'
    result = resolve_reading_scope(reading_research, question)
    assert set(result['paper_ids']) == {'paper-001', 'paper-002'}
    assert result['excluded_paper_ids'] == []


def test_exclusion_without_a_positive_name_uses_only_remaining_visible_papers(reading_research):
    result = resolve_reading_scope(reading_research, '这次不要看QLoRA', all_papers=True)
    assert result['paper_ids'] == ['paper-002']
    assert result['source'] == 'message_exclusion'
    with pytest.raises(ValueError):
        resolve_reading_scope(reading_research, '不要看QLoRA；不要看LoRA')


def test_parallel_retries_of_one_parent_execute_one_child_only(tmp_path):
    manager = TaskManager(tmp_path)
    entered, release = threading.Event(), threading.Event()
    executions = []
    descriptor = {'path': '/api/fulltext/search', 'body': {'run_id': 'study', 'query': 'methods'}}
    try:
        def fail():
            raise RuntimeError('controlled initial failure')
        parent = manager.submit('/api/fulltext/search', fail, retry_descriptor=descriptor)
        terminal(manager, parent['task_id'])
        def work():
            executions.append('execute')
            entered.set()
            assert release.wait(5)
            return {'run_id': 'study'}
        def submit(index):
            return manager.submit('/api/fulltext/search', work, input_digest='same-input',
                                  retry_descriptor=descriptor, retry_of=parent['task_id'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            submitted = list(pool.map(submit, range(12)))
        assert entered.wait(2)
        assert len({job['task_id'] for job in submitted}) == 1
        child_id = submitted[0]['task_id']
        assert manager.get(parent['task_id'])['can_retry'] is False
        assert manager.get(parent['task_id'])['retry_task_id'] == child_id
        release.set()
        assert terminal(manager, child_id)['status'] == 'completed'
        assert executions == ['execute']
        # Refreshing/reposting the old parent returns the existing result.
        assert submit(99)['task_id'] == child_id
        assert executions == ['execute']
    finally:
        release.set()
        manager.close()


def test_failed_retry_can_be_retried_as_its_own_child_not_by_duplicating_original(tmp_path):
    manager = TaskManager(tmp_path)
    descriptor = {'path': '/api/fulltext/search', 'body': {'query': 'method'}}
    try:
        def fail():
            raise RuntimeError('controlled failure')
        parent = manager.submit('/api/fulltext/search', fail, retry_descriptor=descriptor)
        terminal(manager, parent['task_id'])
        child = manager.submit('/api/fulltext/search', fail, retry_descriptor=descriptor, retry_of=parent['task_id'])
        terminal(manager, child['task_id'])
        assert not manager.get(parent['task_id'])['can_retry']
        assert manager.get(child['task_id'])['can_retry']
        grandchild = manager.submit('/api/fulltext/search', lambda: {'run_id': 'completed'},
                                    retry_descriptor=descriptor, retry_of=child['task_id'])
        assert terminal(manager, grandchild['task_id'])['status'] == 'completed'
        assert grandchild['retry_of'] == child['task_id']
        assert len({parent['task_id'], child['task_id'], grandchild['task_id']}) == 3
    finally:
        manager.close()


@pytest.fixture
def supplementary_handler(tmp_path, monkeypatch):
    settings = SimpleNamespace(runs_dir=tmp_path, openalex_mailto=None, openalex_api_key=None)
    manifest = {'question': 'time-series anomaly detection', 'constraints': {'year_from': 2020},
                'live': {'constraints': {'year_from': 2021}, 'matched_paper_ids': ['paper-001'],
                         'coverage': {'arxiv': {'status': 'success'}, 'openalex': {'status': 'partial'},
                                      'semantic_scholar': {'status': 'failed'}}}}
    monkeypatch.setattr('src.replay.load_run', lambda *args: {'manifest': deepcopy_json(manifest)})
    calls = []
    bundle = object()
    def search(question, **kwargs):
        calls.append(('search', question, kwargs))
        return bundle
    def pipeline(config, **kwargs):
        calls.append(('pipeline', config, kwargs))
        return {'run_id': 'study-copy', 'status': 'completed'}
    monkeypatch.setattr('src.retrieve.search_all', search)
    monkeypatch.setattr('src.ui.server.run_pipeline', pipeline)
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    return handler, manifest, calls, bundle


def deepcopy_json(value):
    return json.loads(json.dumps(value))


def test_search_more_retries_only_failed_providers_and_keeps_the_parent(supplementary_handler):
    handler, _, calls, bundle = supplementary_handler
    result = handler._execute_operation('/api/research/search-more', {'run_id': 'study', 'failed_only': True})
    search = calls[0]
    assert search[1] == 'time-series anomaly detection'
    assert search[2]['base_sources'] == ['openalex']
    assert search[2]['constraints'] == {'year_from': 2021}
    pipeline = calls[1]
    assert pipeline[2]['source_run'] == 'study' and pipeline[2]['search_bundle'] is bundle
    assert pipeline[2]['live'] is True
    assert result['run_id'] == 'study-copy'
    assert result['search_more']['parent_run_id'] == 'study'
    assert result['search_more']['failed_only'] is True


def test_search_more_does_not_start_network_when_no_source_failed(supplementary_handler):
    handler, manifest, calls, _ = supplementary_handler
    manifest['live']['coverage'] = {'arxiv': {'status': 'success'}, 'openalex': {'status': 'not_requested'},
                                   'semantic_scholar': {'status': 'failed'}}
    manifest['live']['retrieval'] = [{'source': 'semantic_scholar', 'status': 'failed'}]
    with pytest.raises(ValueError, match='没有需要重试'):
        handler._execute_operation('/api/research/search-more', {'run_id': 'study', 'failed_only': True})
    assert calls == []


def test_search_more_legacy_failures_are_source_filtered_and_budget_is_explicit(supplementary_handler):
    handler, manifest, calls, _ = supplementary_handler
    manifest['live'].pop('coverage')
    manifest['live']['retrieval'] = [
        {'source': 'arxiv', 'status': 'success'}, {'source': 'openalex', 'status': 'rate_limited'},
        {'source': 'unrecognised', 'status': 'failed'}]
    supplement = {'pages_per_query': 1, 'max_requests': 2, 'sources': ['openalex', 'semantic_scholar']}
    handler._execute_operation('/api/research/search-more', {'run_id': 'study', 'failed_only': True,
                                                           'search_supplement': supplement})
    assert calls[0][2]['base_sources'] == ['openalex']
    assert calls[0][2]['supplement'] == {**supplement, 'sources': ['openalex']}


@pytest.mark.parametrize('body', [{'failed_only': 'yes'}, {'search_supplement': {'max_requests': 999}}])
def test_search_more_invalid_options_are_rejected_before_a_network_call(supplementary_handler, body):
    handler, _, calls, _ = supplementary_handler
    with pytest.raises(ValueError):
        handler._execute_operation('/api/research/search-more', {'run_id': 'study', **body})
    assert calls == []


def test_supplementary_pipeline_preserves_user_sidecars_and_online_visibility(tmp_path, monkeypatch):
    from src.config import load_settings
    from src.io_utils import write_json, read_json
    from src.paper_library import library_payload
    from src.pipeline import run_pipeline, snapshot_dataset
    from src.replay import load_run
    from src.research_workspace import workspace_payload
    from src.schema import Dataset, PaperCard, ScreeningLog

    settings = load_settings(runs_dir=tmp_path / 'runs', offline=False)
    source = settings.runs_dir / 'original-study'
    source.mkdir(parents=True)
    today = date(2026, 11, 4)
    def paper(identifier, title):
        return PaperCard(paper_id=identifier, title=title, source='arxiv', authors=['Researcher'],
                         url='https://example.org/' + identifier, retrieved_at=today,
                         dedup_key='test:' + identifier, decision='include', reason='Test research selection')
    def screening(identifier):
        return ScreeningLog(screening_id='screen-' + identifier, paper_id=identifier,
                            stage='title_abstract', decision='include', reason_code='test',
                            reason='Selected for this research', checked_fields=['title'],
                            reviewer='test', reviewed_at=today, scope_version='test')
    visible, hidden, added = paper('paper-001', 'Current research'), paper('paper-002', 'Hidden baseline'), paper('paper-003', 'Newly found study')
    dataset = Dataset(papers=[visible, hidden], paper_cards=[visible, hidden],
                      screening=[screening(visible.paper_id), screening(hidden.paper_id)])
    snapshot_dataset(dataset, source / 'output')
    write_json(source / 'run_manifest.json', {'run_id': 'original-study', 'offline': False,
               'question': 'new-topic study', 'status': 'partial',
               'live': {'matched_paper_ids': ['paper-001'], 'added_paper_ids': [], 'retrieval': []}})
    write_json(source / 'output/paper_library.json', {'version': 1, 'run_id': 'original-study', 'items': {
        'paper-001': {'favorite': True, 'reading_status': 'reading', 'tags': ['focus'], 'notes': 'My research note'},
        'paper-002': {'notes': 'Hidden historical note'}}})
    write_json(source / 'output/research_workspace.json', {'run_id': 'original-study', 'reviews': [
        {'review_id': 'review-a', 'paper_id': 'paper-001', 'passage_id': 'paper-001:p1:c1',
         'status': 'pending', 'text': 'Original source quote', 'quote': 'Original source quote',
         'note': 'My evidence reasoning', 'pdf_url': '/api/fulltext/original-study/paper-001#page=1'},
        {'review_id': 'review-b', 'paper_id': 'paper-002', 'status': 'pending', 'text': 'Hidden old quote'}]})
    write_json(source / 'output/research_context.json', {'constraints': {'year_from': 2021}, 'user_resources': {'time': '两周'}})
    write_json(source / 'output/conversation.json', {'run_id': 'original-study', 'messages': [
        {'role': 'user', 'content': 'Read the current study'},
        {'role': 'assistant', 'content': 'Original answer', 'response': {'run_id': 'original-study',
         'answer_audit': {'citations': [{'paper_id': 'paper-001', 'pdf_url': '/api/fulltext/original-study/paper-001#page=1'}]}}}]})
    before = {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    sentinel_bundle = object()
    def ingest(original, config, **kwargs):
        assert kwargs['search_bundle'] is sentinel_bundle
        updated = original.model_copy(deep=True)
        updated.papers.append(added)
        updated.paper_cards.append(added)
        updated.screening.append(screening(added.paper_id))
        return updated, {'matched_paper_ids': ['paper-003'], 'added_paper_ids': ['paper-003'], 'retrieval': []}
    monkeypatch.setattr('src.live_ingest.ingest_live', ingest)
    monkeypatch.setattr('src.audit_enrichment.enrich_audit', lambda data, **kwargs: data)
    monkeypatch.setattr('src.pipeline.build_map', lambda data, run_id: {'run_id': run_id, 'nodes': [], 'edges': []})
    monkeypatch.setattr('src.pipeline.write_pyvis_html', lambda *args: None)
    result = run_pipeline(settings, run_id='supplementary-study', source_run='original-study',
                          live=True, question='new-topic study', search_bundle=sentinel_bundle)
    child = settings.runs_dir / result['run_id']
    loaded = load_run(settings.runs_dir, result['run_id'])
    assert loaded['manifest']['parent_run_id'] == 'original-study'
    assert set(loaded['manifest']['live']['matched_paper_ids']) == {'paper-001', 'paper-003'}
    assert loaded['manifest']['live']['parent_visible_paper_ids'] == ['paper-001']
    assert set(i['paper_id'] for i in library_payload(settings.runs_dir, result['run_id'])['items']) == {'paper-001', 'paper-003'}
    library = read_json(child / 'output/paper_library.json')
    assert library['run_id'] == result['run_id'] and library['items']['paper-001']['notes'] == 'My research note'
    assert library['items']['paper-001']['favorite'] is True
    reviews = workspace_payload(settings.runs_dir, result['run_id'])['reviews']
    assert len(reviews) == 1 and reviews[0]['note'] == 'My evidence reasoning'
    assert reviews[0]['pdf_url'] == '/api/fulltext/supplementary-study/paper-001#page=1'
    assert read_json(child / 'output/research_context.json')['user_resources']['time'] == '两周'
    conversation = read_json(child / 'output/conversation.json')
    assert len(conversation['messages']) == 2 and conversation['run_id'] == result['run_id']
    assert conversation['messages'][1]['response']['answer_audit']['citations'][0]['pdf_url'] == '/api/fulltext/supplementary-study/paper-001#page=1'
    after = {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    assert before == after
