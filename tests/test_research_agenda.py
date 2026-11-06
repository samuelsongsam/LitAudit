from types import SimpleNamespace

import pytest

from src.grounded_reading import grounded_answer
from src.tasks import TaskCancelled


QUESTION = '依据这些文献，有哪些问题值得分析？'
PAGE_TEXT = 'The simulation study compares learned control with a fixed baseline on a grasping task.'
ABSTRACT = 'The deployment study compares control policies on physical robots and measures grasp success rate.'
DESIGN = {'comparison': '学习控制与固定基线', 'control': '使用相同抓取任务和动作预算', 'metrics': '抓取成功率与任务耗时'}


@pytest.fixture
def agenda_payload():
    return {'run_id': 'synthetic', 'question': '仿真与真实机器人控制的评测方法', 'research_agenda': True,
            'reading_scope': {'paper_ids': ['sim', 'robot']},
            'papers': [
                {'paper_id': 'sim', 'title': 'Simulation control'},
                {'paper_id': 'robot', 'title': 'Physical robot control', 'abstract': ABSTRACT,
                 'url': 'https://example.invalid/robot'},
                {'paper_id': 'out', 'title': 'Unrelated study', 'abstract': 'An unrelated publication.'}],
            'fulltext_index': {'hits': [{'paper_id': 'sim', 'passage_id': 's1', 'page': 4,
                                        'text': PAGE_TEXT, 'pdf_url': '/api/fulltext/synthetic/sim#page=4'}]}}


def proposals(context):
    ids = {(p['paper_id'], p['source_kind']): p['id'] for p in context['materials']}
    sources = [{'id': ids['sim', 'fulltext'], 'attribution': '仿真研究在抓取任务中对比学习控制和固定基线。'},
               {'id': ids['robot', 'abstract'], 'attribution': '部署研究摘要描述了真实机器人上的控制策略对比和抓取成功率。'}]
    return [
        {'question': '两种环境下对照方法的效果是否一致？', 'design': DESIGN,
         'motivation': '仿真论文比较了学习控制和固定基线，部署论文的摘要提到真实机器人上的策略比较。',
         'analysis_plan': '对齐任务和成功率定义，再比较同一控制策略相对固定基线的变化。', 'sources': sources},
        {'question': '评测环境会改变控制策略的相对排序吗？',
         'design': {**DESIGN, 'comparison': '仿真环境与实体机器人', 'metrics': '按抓取成功率得到的策略排名'},
         'motivation': '两篇论文分别在仿真和真实机器人上比较控制。',
         'analysis_plan': '在同一任务与资源预算下记录排序，单独检查跨环境排名变化。', 'sources': sources},
    ]


def test_agenda_separates_two_testable_questions_from_scoped_observations(agenda_payload, monkeypatch):
    def model(settings, prompt, context):
        if 'materials' not in context:
            assert all(q['scope'] == 'cross_paper' for q in context['questions'])
            return {'accepted_ids': [0, 1]}
        assert context['study_question'] == agenda_payload['question']
        assert not any(row['paper_id'] == 'out' for row in context['materials'])
        first, second = proposals(context)
        return {'questions': [first, second, {**first, 'question': '捏造结果能否支持新方向？',
                                            'design': {**DESIGN, 'comparison': '按模型接口进行分组'},
                                            'motivation': '论文报告模型提高了30%。'}]}

    monkeypatch.setattr('src.grounded_reading._call', model)
    overview, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert '效果是否一致' in overview and '相对排序' in overview
    assert audit['kind'] == 'research_agenda' and audit['answer_status'] == 'answered'
    assert len(audit['questions']) == 2 and len(audit['citations']) == 2
    assert audit['generation']['rejections'] == {'unsupported_quantity': 1}
    assert audit['questions'][0]['design'] == DESIGN and audit['questions'][0]['provenance'] == 'model_reviewed'
    assert len(audit['questions'][1]['sources']) == 2
    assert audit['evidence_paper_ids'] == ['sim', 'robot']
    fulltext, abstract = audit['citations']
    assert fulltext['page'] == 4 and fulltext['quote'] == PAGE_TEXT
    assert abstract['source_kind'] == 'abstract' and 'page' not in abstract and 'pdf_url' not in abstract
    assert abstract['url'] == 'https://example.invalid/robot'


def test_invalid_first_draft_is_repaired_before_review(agenda_payload, monkeypatch):
    calls = []

    def model(settings, prompt, context):
        calls.append(context)
        if 'materials' not in context:
            return {'accepted_ids': [0, 1]}
        if 'repair' not in context:
            return {'sections': [{'text': '只总结第一篇论文'}]}
        assert context['repair']['validation_codes'] == {'missing_questions': 1}
        return {'questions': proposals(context)}

    monkeypatch.setattr('src.grounded_reading._call', model)
    overview, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert '只总结第一篇论文' not in overview
    assert audit['answer_status'] == 'answered' and len(calls) == 3
    assert audit['generation']['attempts'] == 2 and audit['generation']['review_calls'] == 1


def test_single_paper_reviewed_proposal_survives_repair_timeout(agenda_payload, monkeypatch):
    def model(settings, prompt, context):
        if 'materials' not in context:
            return {'accepted_ids': [0]}
        if 'repair' in context:
            raise TimeoutError
        return {'questions': [{'question': '仿真里换一种固定控制基线会改变结果吗？',
                               'motivation': '仿真论文比较了学习控制和固定基线。',
                               'design': DESIGN,
                               'analysis_plan': '固定仿真任务，再更换基线，记录相同指标。', 'sources': [
                                   {'id': 'passage-1', 'attribution': '学习控制和固定基线接受抓取测试。'}]}]}

    monkeypatch.setattr('src.grounded_reading._call', model)
    _, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    focused = audit['questions'][0]
    assert audit['answer_status'] == 'partial' and audit['model_status'] == 'timed_out'
    assert focused['scope'] == 'single_paper' and len(focused['sources']) == 1 and focused['provenance'] == 'model_reviewed'


def test_distinct_excerpts_on_the_same_page_are_not_deduplicated_together():
    from src.research_agenda import unique_citations

    method = {'paper_id': 'sim', 'page': 4, 'quote': PAGE_TEXT}
    metric = {**method, 'quote': 'A second excerpt describes the evaluation metric.'}
    assert unique_citations([method, method.copy(), metric]) == [method, metric]


def test_invalid_abstract_quote_never_appears_in_generated_questions(agenda_payload, monkeypatch):
    def model(settings, prompt, context):
        assert 'materials' in context
        return {'questions': [{**proposals(context)[0], 'motivation': '某模型能消除所有错误。', 'sources': [
            {'id': 'paper-robot', 'quote': 'An invented quote.', 'attribution': '某模型能消除所有错误。'}]}]}

    monkeypatch.setattr('src.grounded_reading._call', model)
    text, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert '消除所有错误' not in text and audit['model_status'] == 'draft_invalid'
    assert audit['generation']['rejections'] == {'invalid_source': 2}


def test_generic_draft_is_rejected_even_with_a_valid_schema(agenda_payload, monkeypatch):
    def model(settings, prompt, context):
        first = proposals(context)[0]
        return {'questions': [{**first, 'question': '哪些任务和评价条件可以直接比较？',
                               'design': {'comparison': '对比不同研究', 'control': '控制变量', 'metrics': '衡量效果'}}]}

    monkeypatch.setattr('src.grounded_reading._call', model)
    _, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert audit['generation']['rejections'] == {'generic_design': 2}
    assert audit['generation']['review_calls'] == 0
    assert all(row['question'] != '哪些任务和评价条件可以直接比较？' for row in audit['questions'])


def test_bound_model_identifier_does_not_excuse_unsupported_measurements(agenda_payload):
    from src.research_agenda import _evidence, _prompt_evidence, _validated_questions

    agenda_payload['papers'][0]['title'] = 'GPT-6-Astra simulation control'
    evidence = _prompt_evidence(_evidence(agenda_payload), agenda_payload['question'])
    first = proposals({'materials': [{'id': key, **row} for key, row in evidence.items()]})[0]
    first['sources'][0]['attribution'] = 'GPT-6-Astra 的论文对比学习控制与固定基线。'
    first['motivation'] = 'GPT-6-Astra 的仿真设置可以与实体机器人设置比较。'
    validated, rejected = _validated_questions([first], evidence)
    assert len(validated) == 1 and not rejected

    first['sources'][0]['attribution'] = 'GPT-6-Astra 将抓取成功率提高 6%。'
    validated, rejected = _validated_questions([first], evidence)
    assert not validated and rejected == {'unsupported_quantity': 1}


def test_exactly_repeated_designs_are_rejected_even_when_worded_differently(agenda_payload):
    from src.research_agenda import _evidence, _prompt_evidence, _validated_questions

    evidence = _prompt_evidence(_evidence(agenda_payload), agenda_payload['question'])
    first = proposals({'materials': [{'id': key, **row} for key, row in evidence.items()]})[0]
    second = {**first, 'question': '效果会受两个评测环境影响吗？'}
    validated, rejected = _validated_questions([first, second], evidence)
    assert len(validated) == 1 and rejected == {'duplicate_design': 1}


def test_cross_paper_repair_remains_visible_at_the_card_limit(agenda_payload, monkeypatch):
    factors = ['控制频率', '执行预算', '抓取目标尺寸', '训练数据范围']

    def model(settings, prompt, context):
        if 'materials' not in context:
            return {'accepted_ids': [row['id'] for row in context['questions']]}
        first, second = proposals(context)
        if 'repair' in context:
            return {'questions': [second]}
        return {'questions': [{**first, 'question': f'{factor}变化会改变仿真评测结果吗？',
                               'motivation': '仿真论文在抓取任务中使用学习控制与固定基线。',
                               'design': {**DESIGN, 'comparison': f'按{factor}的不同设置分组'},
                               'sources': first['sources'][:1]} for factor in factors]}

    monkeypatch.setattr('src.grounded_reading._call', model)
    _, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert audit['answer_status'] == 'answered' and len(audit['questions']) == 4
    assert any(row['scope'] == 'cross_paper' for row in audit['questions'])


def test_unrelated_title_only_papers_do_not_produce_a_cross_paper_scaffold(agenda_payload, monkeypatch):
    agenda_payload.pop('fulltext_index')
    agenda_payload['papers'][1].pop('abstract')
    monkeypatch.setattr('src.grounded_reading._call', lambda *_: {})
    _, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert not audit['questions'] and audit['answer_status'] == 'insufficient_evidence'
    assert not audit['citations']


def test_abstract_only_agenda_has_no_page_links_and_honors_explicit_scope(agenda_payload, monkeypatch):
    agenda_payload['reading_scope']['paper_ids'] = ['robot']
    agenda_payload.pop('fulltext_index')

    def offline(*args):
        raise TimeoutError

    monkeypatch.setattr('src.grounded_reading._call', offline)
    text, audit = grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
    assert text and audit['model_status'] == 'timed_out'
    assert set(audit['evidence_paper_ids']) <= {'robot'}
    assert all(source['source_kind'] == 'abstract' and 'page' not in source for source in audit['citations'])


def test_agenda_cancel_does_not_publish_fallback(agenda_payload, monkeypatch):
    def cancel(*args):
        raise TaskCancelled

    monkeypatch.setattr('src.grounded_reading._call', cancel)
    with pytest.raises(TaskCancelled):
        grounded_answer(agenda_payload, QUESTION, SimpleNamespace())
