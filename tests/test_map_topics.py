from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import map_topics as mt


@pytest.fixture
def payload():
    papers = [
        {'paper_id': 'p1', 'title': 'QLoRA: Efficient Finetuning of Quantized LLMs', 'year': 2023,
         'abstract': 'Quantized low-rank adapters reduce the memory requirements of finetuning.'},
        {'paper_id': 'p2', 'title': 'LoRA: Low-Rank Adaptation of Large Language Models', 'year': 2021,
         'abstract': 'Low-rank adaptation freezes pretrained weights and trains rank decomposition matrices.'},
        {'paper_id': 'p3', 'title': 'U-Net: Convolutional Networks for Biomedical Image Segmentation', 'year': 2015,
         'abstract': 'A contracting and expanding path enables biomedical image segmentation.'},
        {'paper_id': 'p4', 'title': 'Attention U-Net: Learning Where to Look for the Pancreas', 'year': 2018,
         'abstract': 'Attention gates improve medical image segmentation of the pancreas.'},
        {'paper_id': 'p5', 'title': 'Contrastive Learning for Time Series Anomaly Detection', 'year': 2024,
         'abstract': 'Contrastive representations detect anomalies in multivariate time series.'},
        {'paper_id': 'p6', 'title': 'Time Series Forecasting and Anomaly Detection', 'year': 2024,
         'abstract': 'Time series forecasting identifies anomalous observations.'},
    ]
    return {'run_id': 'study', 'offline': True, 'papers': papers, 'claims': [], 'evidence': [],
            'map': {'algorithm': 'specter2_cosine_network', 'embedding': {'backend': 'specter2'},
                    'nodes': [{'paper_id': p['paper_id'], 'title': p['title'], 'semantic_degree': 2} for p in papers],
                    'tracks': [{'track_id': f'semantic-{i + 1}', 'label': f'主题簇 {i + 1}',
                                'paper_ids': [papers[i * 2]['paper_id'], papers[i * 2 + 1]['paper_id']]}
                               for i in range(3)]}}


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(runs_dir=tmp_path, llm_api_key=None,
                           llm_model='test-model', llm_base_url='https://example.invalid/v1')


def generated(context):
    names = ['低显存模型微调', '医学图像分割', '时间序列异常检测']
    return {'topics': [
        {'cluster_id': t['cluster_id'], 'label': names[i],
         'common_direction': f'本组论文研究{names[i]}。',
         'keywords': [names[i]], 'common_sources': [
             {'paper_id': p['paper_id'], 'field': 'title', 'quote': p['title']} for p in t['papers']],
         'paper_tasks': [{'paper_id': p['paper_id'], 'task': f'研究任务 {p["paper_id"]}。',
                          'source': {'paper_id': p['paper_id'], 'field': 'abstract', 'quote': p['abstract']}}
                         for p in t['papers']]}
        for i, t in enumerate(context['topics'])]}


def test_term_names_member_counts_and_no_network_or_writes(payload, settings, monkeypatch):
    monkeypatch.setattr(mt, '_generate', lambda *args: pytest.fail('GET topic labels must not use a model'))
    result = mt.map_topics(payload, settings.runs_dir)
    assert result['cluster_count'] == 3 and result['paper_count'] == 6
    assert result['topics'][0]['paper_ids'] == ['p1', 'p2']
    assert '低秩适配' in result['topics'][0]['label']
    assert '图像分割' in result['topics'][1]['label']
    assert '时间序列' in result['topics'][2]['label']
    assert all(t['label_source'] == 'terms' and t['sources'] for t in result['topics'])
    assert list(settings.runs_dir.iterdir()) == []


def test_online_topics_hide_inherited_out_of_scope_papers(payload):
    payload.update(offline=False, live={'matched_paper_ids': ['p1', 'p2']})
    result = mt.base_map_topics(payload)
    assert result['paper_count'] == 2 and result['cluster_count'] == 1
    assert {p for t in result['topics'] for p in t['paper_ids']} == {'p1', 'p2'}


def test_membership_ids_stable_but_ordinal_versions_change(payload):
    original = mt.base_map_topics(payload)
    changed = deepcopy(payload)
    changed['map']['tracks'].reverse()
    reordered = mt.base_map_topics(changed)
    assert {t['cluster_id'] for t in original['topics']} == {t['cluster_id'] for t in reordered['topics']}
    assert original['map_version'] != reordered['map_version']
    changed = deepcopy(payload)
    changed['papers'][0]['abstract'] += ' Additional abstract detail.'
    assert mt.base_map_topics(changed)['map_version'] != original['map_version']


def test_model_names_validated_cached_and_merged_without_changing_map(payload, settings, monkeypatch):
    settings.llm_api_key = 'test-only'
    original = deepcopy(payload['map'])
    calls = []
    monkeypatch.setattr(mt, '_generate', lambda s, context, **kwargs: calls.append(context) or generated(context))
    named = mt.refresh_map_topics(payload, settings)
    assert len(calls) == 1 and named['naming_status'] == 'model'
    assert named['refresh_status'] == 'generated'
    assert [t['label'] for t in named['topics']] == ['低显存模型微调', '医学图像分割', '时间序列异常检测']
    cached = mt.refresh_map_topics(payload, settings)
    assert cached['naming_status'] == 'model' and cached['refresh_status'] == 'cached'
    assert len(calls) == 1
    graph = mt.merge_map_topics(payload, settings.runs_dir)
    assert graph['tracks'][1]['label'] == '医学图像分割'
    assert graph['tracks'][1]['cluster_id'] == named['topics'][1]['cluster_id']
    assert graph['tracks'][1]['sources']
    assert graph['tracks'][1]['common_sources'] == named['topics'][1]['common_sources']
    assert graph['tracks'][1]['paper_tasks'] == named['topics'][1]['paper_tasks']
    assert payload['map'] == original
    assert not (settings.runs_dir / 'study').exists()


@pytest.mark.parametrize('bad_source', ['foreign_member', 'rewritten_quote', 'missing_other_member',
                                        'repeated_common_source', 'cross_paper_task', 'missing_paper_task'])
def test_invalid_model_sources_never_relabel_clusters(payload, settings, monkeypatch, bad_source):
    settings.llm_api_key = 'test-only'
    calls = []
    def invalid(s, context, feedback='', **kwargs):
        calls.append(feedback)
        result = generated(context)
        row = result['topics'][0]
        if bad_source == 'foreign_member':
            row['common_sources'][0]['paper_id'] = 'p3'
        elif bad_source == 'rewritten_quote':
            row['common_sources'][0]['quote'] = 'This invented sentence does not occur in any paper.'
        elif bad_source == 'missing_other_member':
            row['common_sources'].pop()
        elif bad_source == 'repeated_common_source':
            row['common_sources'][1] = row['common_sources'][0]
        elif bad_source == 'cross_paper_task':
            row['paper_tasks'][1]['source'] = row['paper_tasks'][0]['source']
        elif bad_source == 'missing_paper_task':
            row['paper_tasks'].pop()
        return result
    monkeypatch.setattr(mt, '_generate', invalid)
    result = mt.refresh_map_topics(payload, settings)
    assert len(calls) == 2 and calls[1]
    assert result['naming_status'] == 'terms_after_error'
    assert result['refresh_status'] == 'fallback' and result['refresh_reason'] == 'validation'
    assert all(t['label_source'] == 'terms' for t in result['topics'])
    assert mt.map_topics(payload, settings.runs_dir)['naming_status'] == 'terms_after_error'


@pytest.mark.parametrize('label, expected', [
    ('低秩适配', '低秩适配'), ('交通预测模型', ''),
])
def test_single_member_application_is_removed_without_losing_paper_tasks(payload, settings, monkeypatch, label, expected):
    settings.llm_api_key = 'test-only'
    payload['papers'][0]['abstract'] += ' The example application is traffic forecasting.'

    def annotate(s, context, **kwargs):
        result = generated(context)
        result['topics'][0].update(label=label, common_direction='研究低秩适配的交通预测方法。')
        return result

    monkeypatch.setattr(mt, '_generate', annotate)
    result = mt.refresh_map_topics(payload, settings)
    topic = result['topics'][0]
    assert topic['common_direction'] == expected
    assert bool(topic['common_sources']) == bool(expected)
    assert [t['paper_id'] for t in topic['paper_tasks']] == ['p1', 'p2']
    chat = mt.map_chat_response(payload, '第一簇有哪些论文？', settings)['overview']
    assert '交通预测' not in chat
    assert '**各篇论文**' in chat
    assert '研究任务 p1。' in chat and '研究任务 p2。' in chat


def test_invalid_first_response_is_repaired_once(payload, settings, monkeypatch):
    settings.llm_api_key = 'test-only'
    calls, deadlines = [], []
    def repair(s, context, feedback='', *, deadline):
        calls.append(feedback)
        deadlines.append(deadline)
        return {'topics': []} if len(calls) == 1 else generated(context)
    monkeypatch.setattr(mt, '_generate', repair)
    result = mt.refresh_map_topics(payload, settings)
    assert len(calls) == 2 and result['generation']['calls'] == 2
    assert deadlines[0] == deadlines[1]
    assert result['naming_status'] == 'model'


def test_timeout_keeps_saved_topics_and_manual_label(payload, settings, monkeypatch):
    settings.llm_api_key = 'test-only'
    monkeypatch.setattr(mt, '_generate', lambda s, context, **kwargs: generated(context))
    saved = mt.refresh_map_topics(payload, settings)
    topic = saved['topics'][0]
    mt.save_topic_label(payload, settings.runs_dir, cluster_id=topic['cluster_id'],
                        map_version=saved['map_version'], label='人工低秩研究路线')
    path = mt._cache_path(settings.runs_dir, payload['run_id'], saved['map_version'])
    cache = path.read_bytes()
    deadlines = []
    def timeout(s, context, feedback='', *, deadline):
        deadlines.append(deadline)
        raise TimeoutError()
    monkeypatch.setattr(mt, '_generate', timeout)
    result = mt.refresh_map_topics(payload, settings, force=True)
    assert len(deadlines) == 1
    assert result['refresh_status'] == 'fallback' and result['refresh_reason'] == 'timeout'
    assert result['topics'][0]['label'] == '人工低秩研究路线'
    assert result['topics'][0]['generated_label'] == topic['label']
    assert path.read_bytes() == cache


def test_refresh_reports_local_labels_without_calling_model(payload, settings, monkeypatch):
    monkeypatch.setattr(mt, '_generate', lambda *args, **kwargs: pytest.fail('No model should be requested'))
    result = mt.refresh_map_topics(payload, settings)
    assert result['refresh_status'] == 'local' and result['refresh_reason'] == 'unconfigured'
    assert result['topics'] == mt.map_topics(payload, settings.runs_dir)['topics']


def test_next_refresh_continues_with_unprocessed_clusters(payload, settings, monkeypatch):
    settings.llm_api_key = 'test-only'
    monkeypatch.setattr(mt, 'MAX_PAPERS_PER_REQUEST', 4)
    ids = [topic['cluster_id'] for topic in mt.base_map_topics(payload)['topics']]
    names = dict(zip(ids, ['低显存模型微调', '医学图像分割', '时间序列异常检测']))
    calls = []
    def annotate(s, context, **kwargs):
        result = generated(context)
        calls.append([row['cluster_id'] for row in result['topics']])
        for row in result['topics']:
            name = names[row['cluster_id']]
            row.update(label=name, common_direction=f'本组论文研究{name}。')
        return result
    monkeypatch.setattr(mt, '_generate', annotate)
    first = mt.refresh_map_topics(payload, settings)
    second = mt.refresh_map_topics(payload, settings)
    assert first['refresh_status'] == 'partial'
    assert second['refresh_status'] == 'generated'
    assert calls == [ids[:2], ids[2:]]
    assert [topic['label'] for topic in second['topics']] == list(names.values())


def test_concurrent_naming_is_single_flight(payload, settings, monkeypatch):
    settings.llm_api_key = 'test-only'
    calls = []
    monkeypatch.setattr(mt, '_generate', lambda s, context, **kwargs: calls.append(context) or generated(context))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: mt.refresh_map_topics(payload, settings), range(8)))
    assert len(calls) == 1
    assert all(r['naming_status'] == 'model' for r in results)


def test_annotations_never_write_inside_gold_run(payload, settings, monkeypatch):
    payload['run_id'] = 'phase2-real'
    golden = settings.runs_dir / 'phase2-real'
    golden.mkdir()
    sentinel = golden / 'sentinel.txt'
    sentinel.write_text('protected gold bytes', encoding='utf-8')
    settings.llm_api_key = 'test-only'
    monkeypatch.setattr(mt, '_generate', lambda s, context, **kwargs: generated(context))
    mt.refresh_map_topics(payload, settings)
    assert [p.name for p in golden.iterdir()] == ['sentinel.txt']
    assert sentinel.read_text() == 'protected gold bytes'
    assert (settings.runs_dir / '.map-topics/phase2-real').is_dir()


@pytest.mark.parametrize('broken', ['{broken', '[]', '{"topics":[null]}'])
def test_broken_annotation_cache_does_not_break_research(payload, settings, broken):
    base = mt.base_map_topics(payload)
    path = mt._cache_path(settings.runs_dir, payload['run_id'], base['map_version'])
    path.parent.mkdir(parents=True)
    path.write_text(broken, encoding='utf-8')
    assert mt.map_topics(payload, settings.runs_dir)['naming_status'] == 'terms'


def test_ordinal_followup_comparison_and_replay(payload, settings):
    first = mt.map_chat_response(payload, '主题簇分别对应哪些主题？', settings)
    assert first['overview_mode'] == 'map_answer' and len(first['map_answer']['selected_cluster_ids']) == 3
    history = [{'role': 'assistant', 'response': first}]
    assert mt.is_map_question('第二个呢？', history)
    second = mt.map_chat_response(payload, '第二个呢？', settings, history=history)
    assert second['map_answer']['selected_cluster_ids'] == [first['map_answer']['topics'][1]['cluster_id']]
    history.append({'role': 'assistant', 'response': second})
    compared = mt.map_chat_response(payload, '它和第三簇有什么区别？', settings, history=history)
    assert compared['map_answer']['kind'] == 'compare'
    assert compared['map_answer']['selected_cluster_ids'] == [t['cluster_id'] for t in first['map_answer']['topics'][1:]]
    changed = deepcopy(payload)
    changed['map']['tracks'].reverse()
    replay = mt.map_chat_response(changed, '第二簇有哪些论文？', settings,
                                 context={'map_version': first['map_answer']['map_version'], 'cluster_ids': []})
    assert replay['map_answer']['context_source'] == 'historical_map'
    assert replay['map_answer']['selected_cluster_ids'] == [first['map_answer']['topics'][1]['cluster_id']]
    assert '不代表' not in replay['overview'] and '待补充' not in replay['overview']


def test_map_context_validation_rejects_foreign_members_and_versions(payload, settings):
    base = mt.base_map_topics(payload)
    with pytest.raises(ValueError, match='不属于'):
        mt.map_chat_response(payload, '解释这个主题', settings,
                             context={'map_version': base['map_version'], 'cluster_ids': ['topic-' + 'a' * 20]})
    with pytest.raises(ValueError, match='已更新'):
        mt.map_chat_response(payload, '解释这个主题', settings,
                             context={'map_version': 'a' * 64, 'cluster_ids': []})
    with pytest.raises(ValueError, match='编号'):
        mt.map_chat_response(payload, '第十簇是什么？', settings)
    with pytest.raises(ValueError):
        mt.validate_map_context({'cluster_ids': ['../../secrets']})
    with pytest.raises(ValueError):
        mt.validate_map_context({'cluster_ids': [], 'api_key': 'forbidden'})
    assert not mt.is_map_question('K-means聚类算法是什么？')
    assert not mt.is_map_question('查找主题簇聚类方法的论文')
    assert not mt.is_map_question('第二个呢？', [])
    all_topics = mt.map_chat_response(payload, '所有主题簇分别是什么？', settings,
                                     context={'map_version': base['map_version'],
                                              'cluster_ids': [base['topics'][0]['cluster_id']]})
    assert len(all_topics['map_answer']['selected_cluster_ids']) == 3


def test_server_routes_map_before_reading_mode_or_llm_routing(payload, settings, monkeypatch):
    from src.ui.server import LitAuditHandler
    monkeypatch.setattr('src.ui.server.load_settings', lambda **kwargs: settings)
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: deepcopy(payload))
    monkeypatch.setattr('src.ui.server.classify_intent', lambda *args: pytest.fail('Map question must use map routing'))
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler._attach_fulltext = lambda *args: pytest.fail('Map question must not search paper bodies')
    captured = []
    handler._json = lambda data, **kwargs: captured.append(data)
    handler._chat({'run_id': 'study', 'message': '主题簇分别对应哪些主题？', 'reading_mode': True})
    assert captured[-1]['response']['overview_mode'] == 'map_answer'
    handler._chat({'run_id': 'study', 'message': '第二个呢？', 'reading_mode': True})
    assert captured[-1]['response']['map_answer']['selected_cluster_ids'] == [mt.base_map_topics(payload)['topics'][1]['cluster_id']]
    from src.conversation import load_conversation
    saved = load_conversation(settings.runs_dir, 'study')['messages']
    assert len(saved) == 4 and saved[-1]['response']['map_answer']['map_version']
    context = {'map_version': mt.base_map_topics(payload)['map_version'], 'cluster_ids': []}
    descriptor = handler._retry_descriptor('/api/chat', {'run_id': 'study', 'map_context': context})
    assert descriptor['body']['map_context'] == context


def test_topic_get_is_read_only_and_refresh_uses_the_application_workspace(payload, settings, monkeypatch):
    from src.ui.server import LitAuditHandler
    workspace_reads, topic_reads = [], []
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: workspace_reads.append(args) or deepcopy(payload))
    monkeypatch.setattr('src.ui.payload.build_map_topic_payload', lambda *args: topic_reads.append(args) or deepcopy(payload))
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler.path = '/api/map-topics/study'
    result = []
    handler._json = lambda data, **kwargs: result.append((data, kwargs))
    handler.do_GET()
    assert result[-1][0]['cluster_count'] == 3
    assert list(settings.runs_dir.iterdir()) == []
    refreshed = handler._execute_operation('/api/map-topics/refresh', {'run_id': 'study'})
    assert refreshed['map_version'] == result[-1][0]['map_version']
    assert workspace_reads == [(settings.runs_dir, 'study')]
    assert topic_reads == [(settings.runs_dir, 'study')]
    assert handler._retry_descriptor('/api/map-topics/refresh', {'run_id': 'study', 'force': True}) == {
        'path': '/api/map-topics/refresh', 'body': {'run_id': 'study', 'force': True}}


@pytest.mark.parametrize('question', ['比较LoRA与QLoRA的方法、实验与资源要求', 'LoRA和QLoRA为什么有这些区别？'])
def test_explicit_papers_override_a_previously_selected_map_cluster(payload, settings, question):
    first = mt.map_chat_response(payload, '主题簇分别对应哪些主题？', settings)
    context = {'map_version': first['map_answer']['map_version'],
               'cluster_ids': [first['map_answer']['topics'][1]['cluster_id']]}
    history = [{'role': 'assistant', 'response': first}]
    assert not mt.is_map_question(question, history, context, payload)
    scope = mt.resolve_cluster_reading_scope(payload, question, settings.runs_dir, history=history, context=context)
    assert set(scope['paper_ids']) == {'p1', 'p2'}
    assert scope['source'] == 'message'


@pytest.mark.parametrize('question,expected', [
    ('只比较这一簇的方法', ['p3', 'p4']), ('读这个簇已有全文两篇', ['p3', 'p4']),
    ('比较这个簇的方法和实验设置', ['p3', 'p4'])])
def test_cluster_reading_resolves_exact_members_and_ignores_an_old_paper_selector(payload, settings, question, expected):
    payload['fulltext_audit'] = {'documents': [{'paper_id': p['paper_id'], 'status': 'parsed'} for p in payload['papers']]}
    first = mt.map_chat_response(payload, '主题簇分别对应哪些主题？', settings)
    context = {'map_version': first['map_answer']['map_version'],
               'cluster_ids': [first['map_answer']['topics'][1]['cluster_id']]}
    scope = mt.resolve_cluster_reading_scope(payload, question, settings.runs_dir,
                                             history=[{'role': 'assistant', 'response': first}], context=context)
    assert scope['paper_ids'] == expected
    assert scope['source'] == 'cluster_selection'
    assert scope['cluster_ids'] == context['cluster_ids']
    assert scope['available_fulltext_count'] == 2
    assert mt.resolve_cluster_reading_scope(payload, '这个簇的主题名称为什么这样命名？', settings.runs_dir,
                                           context=context) is None


def test_cluster_reading_prefers_available_originals_and_limits_four(payload, settings):
    payload['map']['tracks'] = [{'track_id': 'semantic-1', 'paper_ids': [p['paper_id'] for p in payload['papers']]}]
    payload['fulltext_audit'] = {'documents': [{'paper_id': pid, 'status': 'parsed'} for pid in ['p2', 'p3', 'p4', 'p5', 'p6']]}
    base = mt.base_map_topics(payload)
    context = {'map_version': base['map_version'], 'cluster_ids': [base['topics'][0]['cluster_id']]}
    scope = mt.resolve_cluster_reading_scope(payload, '只比较这一簇的方法', settings.runs_dir, context=context)
    assert len(scope['paper_ids']) == 4 and 'p1' not in scope['paper_ids']
    two = mt.resolve_cluster_reading_scope(payload, '读这个簇已有全文两篇', settings.runs_dir, context=context)
    assert len(two['paper_ids']) == 2


@pytest.mark.parametrize('label', ['短中文主题名', '示例主题', '医学图像分割'])
def test_novel_domain_rejects_placeholder_or_foreign_topic_names(settings, monkeypatch, label):
    settings.llm_api_key = 'test-only'
    pca = {'run_id': 'pca', 'offline': True, 'papers': [
        {'paper_id': 'pca-1', 'title': 'A Tutorial on Principal Component Analysis',
         'abstract': 'Principal component analysis is a linear method for dimensionality reduction.'}],
        'map': {'nodes': [{'paper_id': 'pca-1'}], 'tracks': [{'track_id': 'semantic-1', 'paper_ids': ['pca-1']}]}}
    def wrong(s, context, **kwargs):
        p = context['topics'][0]['papers'][0]
        source = {'paper_id': p['paper_id'], 'field': 'title', 'quote': p['title']}
        return {'topics': [{'cluster_id': context['topics'][0]['cluster_id'], 'label': label,
                            'common_direction': '本组论文说明了相应方向中的理论与方法。',
                            'common_sources': [source], 'paper_tasks': [
                                {'paper_id': p['paper_id'], 'task': '介绍主成分分析。', 'source': source}]}]}
    monkeypatch.setattr(mt, '_generate', wrong)
    result = mt.refresh_map_topics(pca, settings)
    assert result['naming_status'] == 'terms_after_error'
    assert '主成分分析' in result['topics'][0]['label']


def test_server_cluster_method_question_uses_grounded_pipeline_without_map_overview(payload, settings, monkeypatch):
    from src.ui.server import LitAuditHandler
    from src.conversation import load_conversation
    payload['fulltext_audit'] = {'documents': [{'paper_id': p['paper_id'], 'status': 'parsed'} for p in payload['papers']]}
    first = mt.map_chat_response(payload, '主题簇分别对应哪些主题？', settings)
    from src.conversation import save_turn
    save_turn(settings.runs_dir, 'study', '主题簇分别对应哪些主题？', first['overview'], first)
    monkeypatch.setattr('src.ui.server.load_settings', lambda **kwargs: settings)
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: deepcopy(payload))
    monkeypatch.setattr('src.ui.server.classify_intent', lambda *args: pytest.fail('Cluster reading already has a resolved tool'))
    calls = []
    def answer(data, message, intent, config):
        calls.append(deepcopy(data['reading_scope']))
        assert data['reading_mode'] == 'grounded'
        return {'overview': '当前所选论文的方法解读。', 'overview_mode': 'direct_answer',
                'run_id': 'study', 'answer_audit': {'ok': True}}
    monkeypatch.setattr('src.ui.server.build_chat_response', answer)
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler._attach_fulltext = lambda *args: None
    captured = []
    handler._json = lambda data, **kwargs: captured.append(data)
    context = {'map_version': first['map_answer']['map_version'],
               'cluster_ids': [first['map_answer']['topics'][1]['cluster_id']]}
    handler._chat({'run_id': 'study', 'message': '只比较这一簇的方法', 'reading_mode': False,
                   'reading_paper_id': 'p1', 'map_context': context})
    assert calls[0]['paper_ids'] == ['p3', 'p4']
    assert captured[-1]['response']['overview_mode'] == 'direct_answer'
    assert captured[-1]['response']['reading_scope']['cluster_ids'] == context['cluster_ids']
    assert load_conversation(settings.runs_dir, 'study')['messages'][-1]['response']['reading_scope']['paper_ids'] == ['p3', 'p4']


def test_human_topic_name_saves_and_replays_in_get_payload_and_chat(payload, settings, monkeypatch):
    from src.ui.server import LitAuditHandler
    base = mt.base_map_topics(payload)
    original = deepcopy(payload['map'])
    request = {'run_id': 'study', 'cluster_id': base['topics'][0]['cluster_id'],
               'map_version': base['map_version'], 'label': '  我的模型路线  '}
    monkeypatch.setattr('src.ui.server.build_payload', lambda *args: deepcopy(payload))
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler.path = '/api/map-topics/label'
    handler.headers = {}
    handler._read_body = lambda **kwargs: request
    responses = []
    handler._json = lambda value, **kwargs: responses.append(value)
    handler.do_POST()
    result = responses[-1]
    assert set(result) == {'run_id', 'map_version', 'topic'}
    assert result['topic']['label'] == '我的模型路线'
    assert result['topic']['label_source'] == 'human' and result['topic']['updated_at']
    assert result['topic']['paper_ids'] == base['topics'][0]['paper_ids']
    handler.path = '/api/map-topics/study'
    handler.do_GET()
    assert responses[-1]['topics'][0]['label'] == '我的模型路线'
    graph = mt.merge_map_topics(payload, settings.runs_dir)
    assert graph['tracks'][0]['label'] == '我的模型路线'
    reply = mt.map_chat_response(payload, '第一簇对应什么主题？', settings)
    assert '我的模型路线' in reply['overview']
    assert reply['map_answer']['topics'][0]['label_source'] == 'human'
    assert payload['map'] == original


def test_forced_model_refresh_preserves_human_name_and_old_conversation_snapshot(payload, settings, monkeypatch):
    settings.llm_api_key = 'test-only'
    calls = []
    def name(s, context, **kwargs):
        calls.append(context)
        result = generated(context)
        if len(calls) > 1:
            result['topics'][0]['label'] = '低显存模型微调（新版）'
            result['topics'][0]['common_direction'] = '本组论文研究低秩适配的模型微调路径。'
        return result
    monkeypatch.setattr(mt, '_generate', name)
    before = mt.map_chat_response(payload, '主题簇分别对应哪些主题？', settings)
    original_snapshot = deepcopy(before)
    first = before['map_answer']['topics'][0]
    mt.save_topic_label(payload, settings.runs_dir, cluster_id=first['cluster_id'],
                        map_version=before['map_answer']['map_version'], label='作者自己的模型路线')
    refreshed = mt.refresh_map_topics(payload, settings, force=True)
    assert len(calls) == 2
    assert refreshed['topics'][0]['label'] == '作者自己的模型路线'
    assert refreshed['topics'][0]['label_source'] == 'human'
    assert refreshed['topics'][0]['generated_label'] == '低显存模型微调（新版）'
    assert refreshed['topics'][0]['common_direction'] == '本组论文研究低秩适配的模型微调路径。'
    # Snapshot persistence must retain the model direction behind the human label.
    mt.map_chat_response(payload, '第一簇的主题是什么？', settings)
    after = mt.map_topics(payload, settings.runs_dir)
    assert after['topics'][0]['common_direction'] == refreshed['topics'][0]['common_direction']
    assert after['topics'][0]['label'] == '作者自己的模型路线'
    assert before == original_snapshot


def test_human_labels_reject_unknown_cluster_old_version_and_invalid_length(payload, settings):
    base = mt.base_map_topics(payload)
    valid = {'cluster_id': base['topics'][0]['cluster_id'], 'map_version': base['map_version'], 'label': '我的主题'}
    for update in [{'cluster_id': 'topic-' + 'f' * 20}, {'map_version': 'f' * 64},
                   {'label': ''}, {'label': ' '}, {'label': '名' * 81}, {'label': 123}]:
        with pytest.raises(ValueError):
            mt.save_topic_label(payload, settings.runs_dir, **{**valid, **update})
    assert list(settings.runs_dir.iterdir()) == []


def test_human_label_sidecar_does_not_write_gold_run(payload, settings):
    payload['run_id'] = 'phase2-real'
    run = settings.runs_dir/'phase2-real'
    (run/'output').mkdir(parents=True)
    golden = run/'output/map.json'
    golden.write_text(json.dumps(payload['map']), encoding='utf-8')
    before = {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    base = mt.base_map_topics(payload)
    mt.save_topic_label(payload, settings.runs_dir, cluster_id=base['topics'][0]['cluster_id'],
                        map_version=base['map_version'], label='人工研究方向')
    after = {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    assert before == after
    assert mt.map_topics(payload, settings.runs_dir)['topics'][0]['label'] == '人工研究方向'
    assert len(list((settings.runs_dir/'.map-topics/phase2-real').glob('*.manual.json'))) == 1


def test_requested_old_map_is_resolved_from_the_whole_copied_history(payload, settings, monkeypatch):
    first = mt.base_map_topics(payload)
    reordered = deepcopy(payload)
    reordered['map']['tracks'].reverse()
    newer = mt.base_map_topics(reordered)
    changed = deepcopy(payload)
    changed['run_id'] = 'forked-study'
    changed['papers'][0]['abstract'] += ' More published details.'
    history = [{'role': 'assistant', 'response': {'map_answer': first}},
               {'role': 'assistant', 'response': {'map_answer': newer}}]
    original_files = list(settings.runs_dir.rglob('*'))
    monkeypatch.setattr(mt, '_generate', lambda *args: pytest.fail('Replay must not request model naming'))
    current, source, previous, _ = mt._topic_source(changed, settings.runs_dir, history,
        {'map_version': first['map_version'], 'cluster_ids': [first['topics'][1]['cluster_id']]})
    assert source['map_version'] == previous['map_version'] == first['map_version']
    assert current['map_version'] != source['map_version']
    assert source['run_id'] == 'forked-study'
    assert source['topics'][1]['paper_ids'] == ['p3', 'p4']
    assert list(settings.runs_dir.rglob('*')) == original_files


def test_fork_reuses_current_model_annotations_from_conversation_without_external_call(payload, settings, monkeypatch):
    from src.conversation import save_turn
    settings.llm_api_key = 'test-only'
    calls = []
    monkeypatch.setattr(mt, '_generate', lambda s, context, **kwargs: calls.append(context) or generated(context))
    original = mt.refresh_map_topics(payload, settings)
    forked = deepcopy(payload)
    forked['run_id'] = 'forked-study'
    save_turn(settings.runs_dir, 'forked-study', '各个主题是什么？', '已有主题解释',
              {'overview_mode': 'map_answer', 'map_answer': original})
    assert not mt._cache_path(settings.runs_dir, 'forked-study', original['map_version']).exists()
    files_before_get = {p.relative_to(settings.runs_dir): p.read_bytes()
                        for p in settings.runs_dir.rglob('*') if p.is_file()}
    restored = mt.map_topics(forked, settings.runs_dir)
    assert restored['run_id'] == 'forked-study' and restored['naming_status'] == 'model'
    assert [t['label'] for t in restored['topics']] == [t['label'] for t in original['topics']]
    assert restored['annotation_source'] == 'conversation_history'
    assert {p.relative_to(settings.runs_dir): p.read_bytes()
            for p in settings.runs_dir.rglob('*') if p.is_file()} == files_before_get
    result = mt.map_chat_response(forked, '第二簇是什么主题？', settings)
    assert len(calls) == 1  # Only the initial parent naming call.
    assert result['map_answer']['selected_cluster_ids'] == [original['topics'][1]['cluster_id']]


def test_old_map_replay_cannot_expand_current_paper_reading_scope(payload, settings):
    previous = mt.base_map_topics(payload)
    history = [{'role': 'assistant', 'response': {'map_answer': previous}}]
    narrowed = deepcopy(payload)
    narrowed.update(run_id='forked-study', offline=False, live={'matched_paper_ids': ['p1', 'p2']})
    context = {'map_version': previous['map_version'], 'cluster_ids': [previous['topics'][1]['cluster_id']]}
    replay = mt.map_chat_response(narrowed, '第二簇有哪些论文？', settings, history=history, context=context)
    assert replay['map_answer']['context_source'] == 'historical_map'
    assert 'Biomedical' in replay['overview'] and 'Pancreas' in replay['overview']
    assert mt.map_topics(narrowed, settings.runs_dir)['paper_count'] == 2
    with pytest.raises(ValueError, match='当前地图'):
        mt.resolve_cluster_reading_scope(narrowed, '读这个簇已有全文两篇', settings.runs_dir,
                                        history=history, context=context)


def test_copied_history_annotations_are_rechecked_against_current_originals(payload, settings, monkeypatch):
    from src.conversation import save_turn
    base = mt.base_map_topics(payload)
    forged = deepcopy(base)
    for topic in forged['topics']:
        topic.update(label_source='model', label='已有命名主题', summary='已有命名主题的研究内容。',
                     sources=[{'paper_id': 'foreign-paper', 'field': 'title', 'quote': 'Unrelated title'}])
    save_turn(settings.runs_dir, 'study', '主题解释', '旧回答',
              {'overview_mode': 'map_answer', 'map_answer': forged})
    monkeypatch.setattr(mt, '_generate', lambda *args: pytest.fail('A GET never calls a model'))
    result = mt.map_topics(payload, settings.runs_dir)
    assert result['naming_status'] == 'terms'
    assert all(t['label_source'] == 'terms' for t in result['topics'])
