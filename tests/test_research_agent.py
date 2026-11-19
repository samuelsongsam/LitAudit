import json
from types import SimpleNamespace

import pytest

from src.config import load_settings
from src.research_agent import run_agent
from src.tasks import TaskCancelled


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = load_settings(runs_dir=tmp_path)
    monkeypatch.setattr('src.research_workspace.workspace_papers', lambda *args: {
        'p1': SimpleNamespace(title='Study', abstract='Abstract')})
    return settings


def chooser(*actions):
    values = iter(actions)
    return lambda *args: next(values)


def test_tool_results_feedback_and_repeated_request_is_cached(setup):
    calls = []
    def planner(settings, context, deadline):
        if context['history']:
            assert context['history'][0]['result']['papers'][0]['title'] == 'Study'
            return {'tool': 'finish'}
        return {'tool': 'read_papers', 'paper_ids': ['p1']}
    def execute(*args):
        calls.append(args)
        return {'papers': [{'title': 'Study'}]}
    result = run_agent(setup, 'study', 'question', 'id', planner=planner, executor=execute)
    assert result['status'] == 'completed' and len(calls) == 1
    assert run_agent(setup, 'study', 'question', 'id', planner=planner, executor=execute) == result
    assert len(calls) == 1


@pytest.mark.parametrize('action', [
    {'tool': 'shell', 'query': 'delete'},
    {'tool': 'read_papers', 'paper_ids': ['foreign']},
    {'tool': 'acquire_fulltext', 'paper_ids': ['p1'], 'url': 'http://localhost'},
    {'tool': 'search_fulltext', 'paper_ids': ['p1']},
    {'tool': 'read_papers', 'paper_ids': ['p1', 'p1']},
])
def test_invalid_or_out_of_scope_actions_never_execute(setup, action):
    def fail(*args):
        pytest.fail('must not execute')
    result = run_agent(setup, 'study', 'question', 'id', planner=chooser(action), executor=fail)
    assert result['status'] == 'invalid_action'


def test_duplicate_action_stops(setup):
    action = {'tool': 'read_papers', 'paper_ids': ['p1']}
    result = run_agent(setup, 'study', 'question', 'id', planner=chooser(action, action), executor=lambda *args: {})
    assert result['status'] == 'no_progress' and len(result['steps']) == 1


def test_unused_query_does_not_abort_scoped_acquisition(setup):
    def execute(settings, run_id, action, deadline):
        assert action.query == '' and action.paper_ids == ['p1']
        return {'acquisition': {'status': 'completed'}}
    result = run_agent(setup, 'study', 'question', 'unused-query', planner=chooser(
        {'tool': 'acquire_fulltext', 'paper_ids': ['p1'], 'query': '获取实验全文'}, {'tool': 'finish'}), executor=execute)
    assert result['status'] == 'insufficient_evidence'


def test_planner_receives_conversation_references(setup):
    context = [{'role': 'assistant', 'content': '之前比较', 'paper_ids': ['p1']}]
    def planner(settings, value, deadline):
        assert value['conversation_context'] == context
        return {'tool': 'finish'}
    assert run_agent(setup, 'study', '后一篇', 'context', planner=planner,
                     conversation_context=context)['status'] == 'completed'


def test_bounded_search_does_not_cold_load_semantic_model(setup, monkeypatch):
    from src.research_agent_worker import execute
    def search(*args, **kwargs):
        assert kwargs['semantic_rerank'] is False
        return {'hits': [], 'algorithm': 'bm25_passage_ranking'}
    monkeypatch.setattr('src.research_workspace.search_fulltext', search)
    result = execute({'root': str(setup.root), 'runs_dir': str(setup.runs_dir), 'run_id': 'study',
                      'action': {'tool': 'search_fulltext', 'paper_ids': ['p1'], 'query': 'methods'}})
    assert result['algorithm'] == 'bm25_passage_ranking'


def test_step_budget(setup):
    result = run_agent(setup, 'study', 'question', 'id', planner=chooser(*[
        {'tool': 'search_fulltext', 'paper_ids': ['p1'], 'query': str(i)} for i in range(4)]),
        executor=lambda *args: {'hits': []})
    assert result['status'] == 'budget_exhausted' and result['model_calls'] == 4


@pytest.mark.parametrize('error,status', [(TimeoutError(), 'timeout'), (ConnectionError(), 'tool_failed')])
def test_tool_failure_preserves_trace(setup, error, status):
    def execute(*args):
        raise error
    result = run_agent(setup, 'study', 'question', 'id',
        planner=chooser({'tool': 'acquire_fulltext', 'paper_ids': ['p1']}), executor=execute)
    assert result['status'] == status
    assert result['steps'][0]['status'] == 'running'


def test_cancel_persists_and_does_not_retry(setup):
    def execute(*args):
        raise TaskCancelled()
    with pytest.raises(TaskCancelled):
        run_agent(setup, 'study', 'question', 'id',
            planner=chooser({'tool': 'read_papers', 'paper_ids': ['p1']}), executor=execute)
    assert run_agent(setup, 'study', 'question', 'id')['status'] == 'cancelled'


def test_interrupted_write_is_not_replayed(setup):
    result = run_agent(setup, 'study', 'question', 'id', planner=chooser({'tool': 'finish'}))
    path = setup.runs_dir / '.agent' / (result['execution_id'] + '.json')
    result['status'] = 'running'
    path.write_text(json.dumps(result), encoding='utf-8')
    assert run_agent(setup, 'study', 'question', 'id')['status'] == 'interrupted'


def test_wall_clock_budget_prevents_tool_after_slow_plan(setup):
    ticks = iter([0, 0, 91])
    result = run_agent(setup, 'study', 'question', 'id', clock=lambda: next(ticks),
        planner=chooser({'tool': 'read_papers', 'paper_ids': ['p1']}))
    assert result['status'] == 'budget_exhausted' and not result['steps']


def test_snapshot_keeps_conversation_identity(tmp_path):
    from src.conversation import save_turn, continue_conversation, list_conversations, load_conversation
    save_turn(tmp_path, 'one', 'question', 'answer')
    save_turn(tmp_path, 'two', 'question', 'answer')
    continue_conversation(tmp_path, 'one', 'two')
    assert load_conversation(tmp_path, 'two')['conversation_id'] == 'one'
    assert len(list_conversations(tmp_path)) == 1


def test_real_worker_reads_existing_baseline_without_mutation():
    from time import monotonic
    from src.research_agent import execute_tool, Action
    from src.research_workspace import workspace_papers
    settings = load_settings()
    papers = workspace_papers(settings.runs_dir, 'phase2-real')
    paper_id = next(iter(papers))
    result = execute_tool(settings, 'phase2-real', Action(tool='read_papers', paper_ids=[paper_id]), monotonic() + 15)
    assert result['papers'][0]['paper_id'] == paper_id
    assert result['papers'][0]['title'] == papers[paper_id].title


def test_agent_chat_runs_existing_audit_and_deduplicates_response(setup, monkeypatch):
    from src.ui.server import LitAuditHandler
    from src.conversation import load_conversation
    result = {'run_id': 'study', 'execution_id': 'test', 'status': 'completed', 'model_calls': 1,
              'limits': {}, 'steps': [], 'hits': []}
    monkeypatch.setattr('src.research_agent.run_agent', lambda *args, **kwargs: result)
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: {'run_id': 'study', 'papers': []})
    calls = []
    def answer(payload, message, intent, settings):
        calls.append(payload)
        assert payload['reading_mode'] == 'materials'
        return {'overview_mode': 'direct_answer', 'overview': '已复核', 'answer_audit': {'ok': True}}
    monkeypatch.setattr('src.ui.server.build_chat_response', answer)
    handler = object.__new__(LitAuditHandler)
    first = handler._agent_chat(setup, 'study', 'question', {'request_id': 'id'})
    assert handler._agent_chat(setup, 'study', 'question', {'request_id': 'id'}) == first
    assert len(calls) == 1
    assert len(load_conversation(setup.runs_dir, 'study')['messages']) == 2
