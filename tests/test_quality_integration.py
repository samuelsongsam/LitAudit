"""Integration boundaries for reading scope, evidence allocation and retries."""
from copy import deepcopy
import json
import time
from types import SimpleNamespace

import pytest

from src.conversation import Intent
from src.reading_scope import resolve_reading_scope
from src.tasks import TaskManager
from src.ui.server import LitAuditHandler


@pytest.fixture
def research():
    return {'run_id': 'study', 'offline': False,
            'live': {'matched_paper_ids': ['paper-001', 'paper-002']},
            'papers': [{'paper_id': 'paper-001', 'title': 'QLoRA: Efficient Finetuning'},
                       {'paper_id': 'paper-002', 'title': 'LoRA: Low-Rank Adaptation'},
                       {'paper_id': 'paper-999', 'title': 'Hidden baseline'}],
            'fulltext_audit': {'documents': [{'paper_id': 'paper-001', 'status': 'parsed'},
                                              {'paper_id': 'paper-002', 'status': 'parsed'}]},
            'fulltext_index': {'hits': [{'passage_id': 'stale', 'paper_id': 'paper-001',
                                        'page': 1, 'text': 'Old cached content'}]}}


def terminal(manager, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.get(task_id)
        if job['status'] not in {'queued', 'running', 'cancel_requested'}:
            return job
        time.sleep(.005)
    raise AssertionError('Task did not finish')


@pytest.mark.parametrize('question, expected', [
    ('LoRA论文的实验设置是什么？', ['paper-002']),
    ('比较LoRA与QLoRA的方法和数据集', ['paper-002', 'paper-001']),
])
def test_reading_handler_uses_current_question_before_stale_selection_or_history(research, question, expected,
                                                                                tmp_path, monkeypatch):
    settings = SimpleNamespace(runs_dir=tmp_path)
    payload = deepcopy(research)
    history = [{'role': 'assistant', 'content': 'Previous answer', 'response': {
        'reading_scope': {'paper_ids': ['paper-001']},
        'answer_audit': {'citations': [{'paper_id': 'paper-001'}]}}}]
    monkeypatch.setattr('src.ui.server.load_settings', lambda **kwargs: settings)
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: payload)
    monkeypatch.setattr('src.ui.server.load_conversation', lambda *args: {'messages': history})
    observed = []
    def forbidden(*args, **kwargs):
        raise AssertionError('Explicit source reading must not launch topic discovery')
    monkeypatch.setattr('src.ui.server.classify_intent', forbidden)
    monkeypatch.setattr('src.ui.server.run_pipeline', forbidden)
    monkeypatch.setattr('src.ui.server.save_turn', lambda *args: None)
    def answer(current, message, intent, config):
        assert current['reading_scope']['paper_ids'] == expected
        assert intent.target_paper_id == (expected[0] if len(expected) == 1 else None)
        return {'overview': 'A source-bound answer', 'overview_mode': 'direct_answer', 'run_id': 'study'}
    monkeypatch.setattr('src.ui.server.build_chat_response', answer)
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler._attach_fulltext = lambda *args: None
    handler._save_research_context = lambda *args: None
    handler._json = lambda body, status=200: observed.append((status, body))
    handler._chat({'run_id': 'study', 'message': question, 'reading_mode': True,
                   'reading_paper_id': 'paper-001'})
    assert observed[-1][0] == 200
    assert observed[-1][1]['response']['reading_scope']['paper_ids'] == expected
    assert observed[-1][1]['run_id'] == 'study'


def test_compound_question_searches_each_facet_with_same_multi_paper_scope(research, tmp_path, monkeypatch):
    payload = deepcopy(research)
    payload['reading_scope'] = {'paper_ids': ['paper-001', 'paper-002'], 'source': 'message'}
    calls = []
    def search(runs_dir, run_id, query, paper_ids=None):
        calls.append((query, paper_ids))
        return {'hits': [{'passage_id': f'new-{len(calls)}', 'paper_id': 'paper-002',
                          'text': query, 'page': 2}], 'passage_count': 20}
    monkeypatch.setattr('src.research_workspace.search_fulltext', search)
    monkeypatch.setattr('src.research_workspace._corpus', lambda *args: ({}, {}, []))
    handler = object.__new__(LitAuditHandler)
    handler.settings = SimpleNamespace(runs_dir=tmp_path)
    handler._attach_fulltext(payload, '比较LoRA与QLoRA的核心方法、数据集、基线和适用条件',
                             Intent('follow_up', 1, 'test', False))
    assert len(calls) == 5  # Original question plus four explicit research facets.
    assert all(ids == ['paper-001', 'paper-002'] for _, ids in calls)
    assert len(payload['fulltext_index']['question_searches']) == 5
    assert {p['passage_id'] for p in payload['fulltext_index']['hits']} == {f'new-{i}' for i in range(1, 6)}
    assert 'stale' not in {p['passage_id'] for p in payload['fulltext_index']['hits']}


def test_search_failure_discards_stale_index_instead_of_answering_from_old_hits(research, tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('Saved fulltext temporarily unavailable')
    monkeypatch.setattr('src.research_workspace.search_fulltext', unavailable)
    handler = object.__new__(LitAuditHandler)
    handler.settings = SimpleNamespace(runs_dir=tmp_path)
    handler._attach_fulltext(research, '方法是什么', Intent('follow_up', 1, 'test', False))
    assert research['fulltext_index']['hits'] == []
    assert research['fulltext_search_status']['status'] == 'unavailable'


def test_missing_documents_do_not_allow_an_orphaned_old_index(research, tmp_path):
    research['fulltext_audit'] = {'documents': []}
    handler = object.__new__(LitAuditHandler)
    handler.settings = SimpleNamespace(runs_dir=tmp_path)
    handler._attach_fulltext(research, '方法是什么', Intent('follow_up', 1, 'test', False))
    assert research['fulltext_index']['hits'] == []


def test_research_agenda_balances_readable_papers_within_a_larger_catalog(tmp_path, monkeypatch):
    from src.research_workspace import research_agenda_fulltext

    ids = [f'paper-{i:03d}' for i in range(1, 25)]
    readable = [ids[0], ids[1], ids[3]]
    papers = {pid: SimpleNamespace(title=f'Synthetic study {pid}', abstract=None) for pid in ids}
    pages = {readable[0]: [f'Experiment and benchmark results for the model, trial {i}.' for i in range(15)],
             readable[1]: ['Methods\nWe used a paired evaluation across environments.'],
             readable[2]: ['Limitations\nSensor noise altered the experimental conditions.']}
    monkeypatch.setattr('src.research_workspace._corpus', lambda *_: (papers, pages, [pid for pid in ids if pid not in pages]))
    result = research_agenda_fulltext(tmp_path, 'study', '依据这些文献，有哪些问题值得分析？', ids)
    assert result['available_fulltext_paper_ids'] == readable
    assert [hit['paper_id'] for hit in result['hits'][:3]] == readable
    assert all(hit['pdf_url'].endswith(f"/{hit['paper_id']}#page={hit['page']}") for hit in result['hits'])

    selected = research_agenda_fulltext(tmp_path, 'study', '基于这段，有哪些问题值得分析？', [ids[0]],
                                       selection={'paper_id': ids[0], 'page': 14, 'quote': pages[ids[0]][13]})
    assert selected['hits'][0]['paper_id'] == ids[0] and selected['hits'][0]['page'] == 14


def test_research_agenda_uses_current_scope_without_retrieval_when_only_abstracts_exist(research, tmp_path, monkeypatch):
    settings = SimpleNamespace(runs_dir=tmp_path)
    research['fulltext_audit'] = {'documents': []}
    research['papers'][0]['abstract'] = 'Quantized adapters reduce memory use.'
    monkeypatch.setattr('src.ui.server.load_settings', lambda **kwargs: settings)
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: research)
    monkeypatch.setattr('src.ui.server.load_conversation', lambda *args: {'messages': []})
    monkeypatch.setattr('src.ui.server.classify_intent', lambda *args: pytest.fail('Agenda should use the saved study'))
    monkeypatch.setattr('src.ui.server.save_turn', lambda *args: None)

    def answer(current, message, intent, config):
        assert current['research_agenda'] is True
        assert current['reading_scope']['paper_ids'] == ['paper-001', 'paper-002']
        assert current['reading_scope']['available_fulltext_paper_ids'] == []
        assert current['fulltext_index']['hits'] == []
        return {'overview': '研究问题', 'overview_mode': 'direct_answer', 'run_id': 'study'}

    monkeypatch.setattr('src.ui.server.build_chat_response', answer)
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler._save_research_context = lambda *args: None
    results = []
    handler._json = lambda body, status=200: results.append((status, body))
    handler._chat({'run_id': 'study', 'message': '依据这些文献，有哪些问题值得分析？'})
    assert results[0][0] == 200 and results[0][1]['status'] == 'completed'


def test_research_agenda_passes_an_exact_experimental_contrast_before_generic_appendix_hits(tmp_path, monkeypatch):
    from src.research_workspace import research_agenda_fulltext

    pid = 'paper-001'
    contrast = 'The experimental setup uses paired trials to compare tactile feedback against a vision-only baseline.'
    papers = {pid: SimpleNamespace(title='Robot feedback study', abstract=None)}
    pages = {pid: ['Methods\n' + contrast,
                   'Appendix\nBenchmark evaluation experiment results and limitations. ' * 12]}
    monkeypatch.setattr('src.research_workspace._corpus', lambda *_: (papers, pages, []))
    result = research_agenda_fulltext(tmp_path, 'study', '依据这些文献，有哪些问题值得分析？', [pid])
    first = result['hits'][0]
    assert first['agenda_facet'] == 'experiment' and first['page'] == 1
    assert contrast in first['quote_hint'] and first['quote_hint'] in first['text']


@pytest.mark.parametrize('question', ['paper-002的方法是什么', '请解释paper-002的方法'])
def test_ascii_paper_identifier_is_separate_from_adjacent_chinese(research, question):
    assert resolve_reading_scope(research, question)['paper_ids'] == ['paper-002']


def test_unknown_identifier_adjacent_to_chinese_is_not_silently_treated_as_all_papers(research):
    with pytest.raises(ValueError):
        resolve_reading_scope(research, '请解释paper-999的方法')


def test_ordinary_paper_based_phrase_is_not_a_reserved_paper_identifier(research):
    result = resolve_reading_scope(research, 'Explain a paper-based method')
    assert set(result['paper_ids']) == {'paper-001', 'paper-002'}


def test_retry_after_restart_keeps_private_input_and_creates_separate_child(tmp_path):
    root = tmp_path / '.tasks'
    root.mkdir()
    descriptor = {'path': '/api/fulltext/search', 'body': {'run_id': 'study', 'query': 'private source question'}}
    (root / 'interrupted-original.json').write_text(json.dumps({
        'task_id': 'interrupted-original', 'operation': '/api/fulltext/search', 'status': 'running',
        'created_at': '2026-11-04T00:00:00Z', 'retry_descriptor': descriptor,
        'run_id': 'study', 'stage': 'fulltext'}), encoding='utf-8')
    manager = TaskManager(tmp_path)
    try:
        calls, responses = [], []
        handler = object.__new__(LitAuditHandler)
        handler.path = '/api/tasks/interrupted-original/retry'
        handler.headers = {}
        handler.server = SimpleNamespace(tasks=manager)
        handler._read_body = lambda **kwargs: {}
        def execute(path, body):
            calls.append((path, body))
            return {'run_id': body['run_id'], 'hits': []}
        handler._execute_operation = execute
        handler._json = lambda body, status=200: responses.append((status, body))
        handler.do_POST()
        assert responses[0][0] == 202
        child = terminal(manager, responses[0][1]['task_id'])
        assert child['status'] == 'completed' and child['retry_of'] == 'interrupted-original'
        assert calls == [(descriptor['path'], descriptor['body'])]
        assert manager.get('interrupted-original')['status'] == 'interrupted'
        public = json.dumps([manager.get('interrupted-original'), child, manager.list()])
        assert 'retry_descriptor' not in public and 'private source question' not in public
    finally:
        manager.close()


def test_retry_descriptor_omits_history_credentials_and_idempotency_id():
    body = {'run_id': 'study', 'message': 'Explain the source', 'reading_mode': True,
            'conversation_context': [{'content': 'Large saved history'}], 'request_id': 'previous-task',
            'llm_api_key': 'must not persist', 'constraints': {'year_from': 2020}}
    descriptor = LitAuditHandler._retry_descriptor('/api/chat', body)
    assert descriptor['body'] == {'run_id': 'study', 'message': 'Explain the source', 'reading_mode': True,
                                  'constraints': {'year_from': 2020}}


def test_grounded_mode_with_no_current_hits_never_falls_back_to_abstract_model(monkeypatch):
    from src.conversation import Intent, build_chat_response
    def forbidden(*args, **kwargs):
        raise AssertionError('No abstract-only fallback or model call is allowed for empty current正文')
    monkeypatch.setattr('src.conversation.urlopen', forbidden)
    payload = {'run_id':'study','reading_mode':'grounded','papers':[{'paper_id':'paper-001','title':'Only abstract','abstract':'Old metadata'}],
               'claims':[],'evidence':[],'fulltext_index':{'hits':[]}}
    settings = SimpleNamespace(llm_api_key='test-only')
    result = build_chat_response(payload,'正文方法是什么',Intent('follow_up',1.0,'reading',False,direct_answer=True),settings)
    assert result['error']=='no_fulltext' and result['answer_audit']['question_coverage'][0]['status']=='insufficient_evidence'


def test_legitimate_large_question_executes_without_truncation_when_not_auto_retriable(tmp_path):
    manager = TaskManager(tmp_path)
    try:
        message = '中文研究问题' * 1800
        body = {'message': message, 'reading_mode': False}
        calls, responses = [], []
        handler = object.__new__(LitAuditHandler)
        handler.path = '/api/chat'
        handler.headers = {'Prefer': 'respond-async'}
        handler.server = SimpleNamespace(tasks=manager)
        handler._read_body = lambda **kwargs: body
        def execute(path, original):
            calls.append(original['message'])
            return {'status': 'completed'}
        handler._execute_operation = execute
        handler._json = lambda data, status=200: responses.append((status, data))
        handler.do_POST()
        assert responses[0][0] == 202
        done = terminal(manager, responses[0][1]['task_id'])
        assert done['status'] == 'completed' and calls == [message]
        assert not done['can_retry']
        saved = json.loads((tmp_path / '.tasks' / f'{done["task_id"]}.json').read_text(encoding='utf-8'))
        assert 'retry_descriptor' not in saved
    finally:
        manager.close()
