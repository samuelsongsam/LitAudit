from src.dialogue_context import recent_context, referenced_papers
from src.material_answer import material_answer


def test_long_answer_keeps_structured_references():
    history = recent_context([{'role': 'assistant', 'content': '长回答' * 3000,
        'response': {'answer_audit': {'citations': [{'paper_id': 'a'}, {'paper_id': 'b'}, {'paper_id': 'a'}]}}}])
    assert history[0]['paper_ids'] == ['a', 'b']
    assert len(history[0]['content']) == 6000
    assert referenced_papers('只解释后一篇', history, {'a', 'b', 'c'}) == ['b']


def test_referential_comparison_cannot_expand_to_all_papers(monkeypatch):
    payload = {'papers': [{'paper_id': pid, 'abstract': 'Public abstract.'} for pid in ['a', 'b', 'c']],
        'conversation_context': [{'role': 'assistant', 'content': '比较A与B', 'paper_ids': ['a', 'b']}]}
    def call(settings, prompt, context):
        assert set(context['sources']) == {'abstract:a', 'abstract:b'}
        return {'sections': []}
    monkeypatch.setattr('src.material_answer._call', call)
    material_answer(payload, '这些方案能公平比较吗？', None)


def test_foreign_history_ids_are_excluded():
    assert referenced_papers('这些方案', [{'role': 'assistant', 'paper_ids': ['foreign']}], {'a'}) == []


def test_discussion_scope_survives_a_partially_cited_answer():
    context = recent_context([{'role': 'assistant', 'content': '有限答案',
        'response': {'answer_audit': {'scope_paper_ids': ['a', 'b'], 'citations': [{'paper_id': 'a'}]}}}])
    assert referenced_papers('后一篇', context, {'a', 'b'}) == ['b']


def test_second_paper_followup_does_not_need_model_routing():
    from src.conversation import classify_intent
    payload = {'papers': [{'paper_id': 'a'}, {'paper_id': 'b'}],
               'conversation_context': [{'role': 'assistant', 'paper_ids': ['a', 'b']}]}
    intent = classify_intent('只解释后一篇，不要重新检索。', payload, None)
    assert intent.target_paper_id == 'b' and intent.direct_answer and not intent.needs_retrieval
