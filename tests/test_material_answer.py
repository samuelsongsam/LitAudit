from types import SimpleNamespace

from src.material_answer import material_answer
from src.conversation import Intent, _llm_direct_answer, classify_intent
from src.config import load_settings
from src.ui.server import LitAuditHandler


def payload():
    return {'run_id': 'study', 'papers': [
        {'paper_id': 'p1', 'title': 'PD', 'abstract': 'Prefill and decode run on different GPUs.'},
        {'paper_id': 'p2', 'title': 'Other', 'abstract': 'Unrelated material.'}],
        'offline': False, 'live': {'matched_paper_ids': ['p1']}}


def section(source='abstract:p1', quote='Prefill and decode run on different GPUs.'):
    return {'text': '论文将预填充与解码部署到不同 GPU。',
            'sources': [{'source_id': source, 'quote': quote}]}


def test_abstract_summary_is_translated_reviewed_and_scoped(monkeypatch):
    calls = []
    def model(settings, prompt, content):
        calls.append(content)
        assert 'abstract:p2' not in content['sources']
        return {'sections': [section()]} if len(calls) == 1 else {'accepted_ids': [0]}
    monkeypatch.setattr('src.material_answer._call', model)
    answer, audit = material_answer(payload(), '总结', None)
    assert '不同 GPU' in answer and '未经全文核验' in answer
    assert audit['ok'] and len(calls) == 2
    assert audit['citations'][0]['certainty'] == 'abstract_only'


def test_unknown_source_and_fabricated_quote_are_not_displayed(monkeypatch):
    monkeypatch.setattr('src.material_answer._call', lambda *args: {'sections': [
        section('abstract:p2', 'Unrelated material.'), section(quote='100 times faster')]})
    answer, audit = material_answer(payload(), '具体速度', None)
    assert not answer and not audit['ok'] and 'invalid_source_quote' in audit['errors']


def test_semantic_review_rejects_unsupported_paraphrase(monkeypatch):
    results = iter([{'sections': [{**section(), 'text': '这是所有场景的最优部署方案。'}]}, {'accepted_ids': []}])
    monkeypatch.setattr('src.material_answer._call', lambda *args: next(results))
    answer, audit = material_answer(payload(), '具体速度', None)
    assert not answer and not audit['ok']


def test_fabricated_number_is_rejected_before_model_review(monkeypatch):
    monkeypatch.setattr('src.material_answer._call', lambda *args: {
        'sections': [{**section(), 'text': '速度提升100倍。'}]})
    answer, audit = material_answer(payload(), '速度提升多少', None)
    assert not answer and not audit['ok'] and 'unsupported_number' in audit['errors']


def test_pdf_whitespace_and_generated_citation_ids_do_not_reject_valid_text(monkeypatch):
    current = payload()
    current['papers'][0]['abstract'] = 'Prefill and decode\nrun on different GPUs.'
    results = iter([{'sections': [{**section(), 'text': '预填充和解码分别部署。[paper-012]'}]}, {'accepted_ids': [0]}])
    monkeypatch.setattr('src.material_answer._call', lambda *args: next(results))
    answer, audit = material_answer(current, '比较', None)
    assert audit['ok'] and 'paper-012' not in answer
    assert '\n' in audit['citations'][0]['quote']


def test_existing_material_comparison_never_routes_to_new_search():
    for question in ['从当前结果中选择两篇最相关的论文，比较资源划分。',
                     '这些方案在完全相同的硬件和负载下，分别能提高多少吞吐量？不能证明条件一致请说明不能公平比较。']:
        intent = classify_intent(question, payload(), None)
        assert intent.direct_answer and not intent.needs_retrieval


def test_rejected_draft_gets_one_bounded_revision(monkeypatch):
    calls = []
    def model(settings, prompt, content):
        calls.append(content)
        if len(calls) == 1:
            return {'sections': [section(quote='invented quote')]}
        if len(calls) == 2:
            assert content['validation_feedback'] == ['invalid_source_quote']
            return {'sections': [section()]}
        return {'accepted_ids': [0]}
    monkeypatch.setattr('src.material_answer._call', model)
    answer, audit = material_answer(payload(), '比较', None)
    assert audit['ok'] and answer and len(calls) == 3


def test_neighbor_context_is_not_exposed_as_current_passage(monkeypatch):
    current = payload()
    current['fulltext_index'] = {'hits': [{'paper_id': 'p1', 'passage_id': 's', 'page': 1,
        'text': 'Actual passage.', 'context': [{'page': 2, 'text': 'Neighbor evidence.'}]}]}
    def model(settings, prompt, content):
        assert 'context' not in content['sources']['passage:s']
        assert 'Neighbor evidence.' not in str(content['sources'])
        return {'sections': []}
    monkeypatch.setattr('src.material_answer._call', model)
    answer, audit = material_answer(current, '比较', None)
    assert audit['kind'] == 'material_insufficient'


def test_two_paper_comparison_cannot_mix_in_a_third(monkeypatch):
    current = payload()
    current['offline'] = True
    current['papers'] = [{'paper_id': pid, 'abstract': 'Exact source.'} for pid in ['p1', 'p2', 'p3']]
    def row(ids):
        return {'text': '研究采用不同部署方式。', 'sources': [
            {'source_id': 'abstract:' + pid, 'quote': 'Exact source.'} for pid in ids]}
    def model(settings, prompt, content):
        if 'sections' in content:
            assert len(content['sections']) == 1
            return {'accepted_ids': [content['sections'][0]['id']]}
        return {'sections': [row(['p1', 'p2', 'p3']), row(['p1', 'p2'])]}
    monkeypatch.setattr('src.material_answer._call', model)
    answer, audit = material_answer(current, '选择两篇论文比较', None)
    assert audit['ok'] and {c['paper_id'] for c in audit['citations']} == {'p1', 'p2'}
    assert 'comparison_scope_exceeded' in audit['rejected']


def test_comparison_order_follows_display_not_citation_frequency(monkeypatch):
    current = payload()
    current['offline'] = True
    current['papers'] = [{'paper_id': pid, 'abstract': 'Exact source.'} for pid in ['a', 'b']]
    rows = [{'text': '比较两种方法。', 'sources': [{'source_id': 'abstract:'+pid, 'quote': 'Exact source.'} for pid in ids]}
            for ids in [['a', 'b'], ['b'], ['b']]]
    results = iter([{'sections': rows}, {'accepted_ids': [0, 1, 2]}])
    monkeypatch.setattr('src.material_answer._call', lambda *args: next(results))
    _, audit = material_answer(current, '选择两篇论文比较', None)
    assert audit['scope_paper_ids'] == ['a', 'b']


def test_mixed_sources_keep_page_and_abstract_labels(monkeypatch):
    current = payload()
    current['fulltext_index'] = {'hits': [{'paper_id': 'p1', 'passage_id': 's1', 'page': 3,
                                        'text': 'Two GPU pools are used.'}]}
    results = iter([{'sections': [section(), section('passage:s1', 'Two GPU pools are used.')]},
                    {'accepted_ids': [0, 1]}])
    monkeypatch.setattr('src.material_answer._call', lambda *args: next(results))
    answer, audit = material_answer(current, '总结', None)
    assert '正文第 3 页' in answer and '摘要' in answer
    assert {c['certainty'] for c in audit['citations']} == {'abstract_only', 'fulltext_only'}


def test_explicit_fulltext_does_not_fall_back_to_abstracts():
    current = {**payload(), 'reading_mode': 'grounded'}
    answer, audit = _llm_direct_answer(current, '实验细节', Intent('follow_up', 1, '', False),
                                     SimpleNamespace(llm_api_key=None))
    assert not answer and audit['errors'] == ['no_fulltext']


def test_summary_route_and_handler_reuse_run_without_fulltext(tmp_path, monkeypatch):
    question = '根据以上检索结果向我以文字的形式汇报这个方向当前的状况'
    current = payload()
    intent = classify_intent(question, current, None)
    assert intent.direct_answer and not intent.needs_retrieval
    settings = load_settings(runs_dir=tmp_path)
    monkeypatch.setattr('src.ui.server.load_settings', lambda **kwargs: settings)
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: current)
    monkeypatch.setattr('src.ui.server.run_pipeline', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('unexpected retrieval')))
    def respond(value, *args):
        assert value['reading_mode'] == 'materials'
        return {'overview': '摘要总结', 'overview_mode': 'direct_answer'}
    monkeypatch.setattr('src.ui.server.build_chat_response', respond)
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    replies = []
    handler._json = lambda body, status=200: replies.append((body, status))
    handler._chat({'run_id': 'study', 'message': question})
    assert replies[0][1] == 200
    assert replies[0][0]['action'] == 'reuse_run'
