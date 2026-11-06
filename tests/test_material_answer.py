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
    assert '材料不足' in answer and not audit['citations']


def test_semantic_review_rejects_unsupported_paraphrase(monkeypatch):
    results = iter([{'sections': [{**section(), 'text': '这是所有场景的最优部署方案。'}]}, {'accepted_ids': []}])
    monkeypatch.setattr('src.material_answer._call', lambda *args: next(results))
    answer, audit = material_answer(payload(), '具体速度', None)
    assert not answer and not audit['ok']


def test_fabricated_number_is_rejected_before_model_review(monkeypatch):
    monkeypatch.setattr('src.material_answer._call', lambda *args: {
        'sections': [{**section(), 'text': '速度提升100倍。'}]})
    answer, audit = material_answer(payload(), '速度提升多少', None)
    assert '材料不足' in answer and not audit['citations']


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
