"""Run three new-topic map-context workflows entirely on this computer.

The six public arXiv records below were supplied after an official-page check.
Their abstract_excerpts are short excerpts, not complete abstracts or full text.
No paper retrieval, model download, hosted-model request or PDF reading occurs.
Run: python scripts/validate_new_map_topics.py
Outputs: tmp/new-map-validation/{sources,result}.json and isolated runs-*.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import socket
import sys
import time
from urllib.error import URLError
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECORDS = [
    {
        'domain': 'traffic', 'arxiv_id': '1709.04875', 'year': 2017,
        'title': 'Spatio-Temporal Graph Convolutional Networks: A Deep Learning Framework for Traffic Forecasting',
        'abstract_excerpt': 'Timely accurate traffic forecast is crucial for urban traffic control and guidance. In this paper, we propose a novel deep learning framework, Spatio-Temporal Graph Convolutional Networks (STGCN), to tackle the time series prediction problem in traffic domain.',
    },
    {
        'domain': 'traffic', 'arxiv_id': '1906.00121', 'year': 2019,
        'title': 'Graph WaveNet for Deep Spatial-Temporal Graph Modeling',
        'abstract_excerpt': 'To overcome these limitations, we propose in this paper a novel graph neural network architecture, Graph WaveNet, for spatial-temporal graph modeling. By developing a novel adaptive dependency matrix and learn it through node embedding, our model can precisely capture the hidden spatial dependency in the data.',
    },
    {
        'domain': 'robotics', 'arxiv_id': '2303.04137', 'year': 2023,
        'title': 'Diffusion Policy: Visuomotor Policy Learning via Action Diffusion',
        'abstract_excerpt': "This paper introduces Diffusion Policy, a new way of generating robot behavior by representing a robot's visuomotor policy as a conditional denoising diffusion process.",
    },
    {
        'domain': 'robotics', 'arxiv_id': '2304.13705', 'year': 2023,
        'title': 'Learning Fine-Grained Bimanual Manipulation with Low-Cost Hardware',
        'abstract_excerpt': 'Fine manipulation tasks, such as threading cable ties or slotting a battery, are notoriously difficult for robots because they require precision, careful coordination of contact forces, and closed-loop visual feedback.',
    },
    {
        'domain': 'operators', 'arxiv_id': '2010.08895', 'year': 2020,
        'title': 'Fourier Neural Operator for Parametric Partial Differential Equations',
        'abstract_excerpt': 'For partial differential equations (PDEs), neural operators directly learn the mapping from any functional parametric dependence to the solution.',
    },
    {
        'domain': 'operators', 'arxiv_id': '1910.03193', 'year': 2019,
        'title': 'DeepONet: Learning nonlinear operators for identifying differential equations based on the universal approximation theorem of operators',
        'abstract_excerpt': 'This universal approximation theorem is suggestive of the potential application of neural networks in learning nonlinear operators from data.',
    },
]
TASKS = [
    {'domain': 'traffic', 'language': 'zh',
     'question': '城市交通预测中，时空图方法有哪些研究方向？这些论文的主题簇分别对应哪些主题？'},
    {'domain': 'robotics', 'language': 'en',
     'question': 'What research topics do the clusters represent for robot manipulation and visuomotor policy learning?'},
    {'domain': 'operators', 'language': 'zh',
     'question': '神经算子如何用于偏微分方程？这些论文的主题簇分别是什么？'},
]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class RuntimeMessages(logging.Handler):
    def __init__(self, rows: list):
        super().__init__(level=logging.WARNING)
        self.rows = rows

    def emit(self, record) -> None:
        if len(self.rows) < 20 and record.name.startswith(('adapters', 'transformers', 'huggingface')):
            self.rows.append({'logger': record.name, 'level': record.levelname,
                              'message': record.getMessage()[:1000]})


@contextmanager
def offline_only(network_attempts: list):
    """Prevent accidental downloads or model calls even after a code regression."""
    names = ['HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE', 'LITAUDIT_MAP_EMBEDDER']
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                      LITAUDIT_MAP_EMBEDDER='specter2')
    original_connect = socket.socket.connect
    original_connection = socket.create_connection
    original_urlopen = urllib.request.urlopen
    def blocked_connect(sock, address, *args, **kwargs):
        network_attempts.append({'mechanism': 'socket.connect', 'destination_type': type(address).__name__})
        raise OSError('Network access is disabled for new-topic local validation')
    def blocked_connection(*args, **kwargs):
        network_attempts.append({'mechanism': 'socket.create_connection'})
        raise OSError('Network access is disabled for new-topic local validation')
    def blocked_urlopen(*args, **kwargs):
        network_attempts.append({'mechanism': 'urlopen'})
        raise URLError('External requests are disabled for new-topic local validation')
    socket.socket.connect = blocked_connect
    socket.create_connection = blocked_connection
    urllib.request.urlopen = blocked_urlopen
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_connection
        urllib.request.urlopen = original_urlopen
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def supplied_membership(dataset, run_id: str) -> dict:
    """Fallback for context checks only, explicitly excluded from clustering results."""
    ids = [p.paper_id for p in dataset.papers]
    return {'run_id': run_id, 'algorithm': 'supplied_membership_workflow_only',
            'embedding': {'backend': 'unavailable'},
            'nodes': [{'paper_id': p.paper_id, 'title': p.title} for p in dataset.papers],
            'edges': [], 'tracks': [{'track_id': 'semantic-1', 'paper_ids': ids}],
            'origin': 'preselected_task_members_for_context_checks_only'}


def main() -> None:
    out = ROOT / 'tmp/new-map-validation'
    out.mkdir(parents=True, exist_ok=True)
    runs = out / ('runs-' + str(time.time_ns()))
    runs.mkdir()
    sources = {
        'provenance': 'Six public records supplied by the parent after checking official arXiv pages; this script performs no online verification.',
        'text_scope': 'Short abstract excerpts only; not complete abstracts, full papers or method evidence.',
        'records': [{**row, 'url': 'https://arxiv.org/abs/' + row['arxiv_id'],
                     'abstract_is_excerpt': True} for row in RECORDS],
    }
    write_json(out / 'sources.json', sources)
    report = {
        'started_at': datetime.now(timezone.utc).isoformat(), 'isolated_runs': str(runs),
        'purpose': 'New-topic map-context and routing workflow checks; not a research-effect or clustering-quality benchmark.',
        'input_scope': 'Official-page-checked titles and short abstract excerpts supplied in sources.json.',
        'hosted_model_calls': 0, 'successful_network_requests': 0, 'network_attempts_blocked': [],
        'model_downloads': 0, 'llm_naming_scope': 'disabled; deterministic member-term names only',
        'runtime_warnings': [],
        'tasks': [], 'checks': [], 'ok': False,
    }
    started = time.monotonic()
    runtime_messages = RuntimeMessages(report['runtime_warnings'])
    logging.getLogger().addHandler(runtime_messages)
    with offline_only(report['network_attempts_blocked']):
        # Import after the guard so all imported HTTP clients also inherit it.
        from src.config import Settings
        from src.map_builder import build_map
        from src.map_topics import base_map_topics, is_map_question, map_chat_response, resolve_cluster_reading_scope
        from src.pipeline import snapshot_dataset
        from src.schema import Dataset, PaperCard, PaperDecision, dataset_stats
        settings = Settings(root=ROOT, data_dir=ROOT/'data', fixtures_dir=ROOT/'data/fixtures',
                            runs_dir=runs, offline=True, log_level='WARNING', llm_api_key=None)
        previous_context = None
        semantic_unavailable = None
        all_papers = []
        semantic_groups = []
        for task in TASKS:
            task_start = time.monotonic()
            records = [r for r in sources['records'] if r['domain'] == task['domain']]
            papers = [PaperCard(paper_id=f'paper-{i:03d}', title=row['title'], year=row['year'],
                                authors=[], doi_or_arxiv=row['arxiv_id'], url=row['url'], source='arxiv',
                                abstract=row['abstract_excerpt'], retrieved_at=date.today(),
                                dedup_key='arxiv:' + row['arxiv_id'], decision=PaperDecision.pending,
                                reason='New-topic workflow input; the abstract field contains a supplied short excerpt, not a full abstract.')
                      for i, row in enumerate(records, 1)]
            dataset = Dataset(papers=papers)
            run_id = 'new-map-' + task['domain']
            run_dir = runs/run_id
            snapshot_dataset(dataset, run_dir/'output')
            write_json(run_dir/'stats.json', dataset_stats(dataset))
            write_json(run_dir/'run_manifest.json', {
                'run_id': run_id, 'offline': True, 'question': task['question'], 'source': 'new_topic_local_validation',
                'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'completed',
                'input_text_scope': 'abstract_excerpt', 'complete_abstracts': False, 'fulltext_processed': False,
            })
            graph_started = time.monotonic()
            try:
                if semantic_unavailable:
                    raise RuntimeError(semantic_unavailable)
                graph = build_map(dataset, run_id)
                if graph.get('embedding', {}).get('backend') != 'specter2':
                    raise RuntimeError('Cached SPECTER2 was not used')
                graph_origin = 'computed_specter2_semantic_communities'
            except Exception as exc:
                semantic_unavailable = f'{type(exc).__name__}: {exc}'[:500]
                graph = supplied_membership(dataset, run_id)
                graph_origin = 'supplied_membership_for_workflow_only'
            graph_seconds = time.monotonic()-graph_started
            write_json(run_dir/'output/map.json', graph)
            payload = {'run_id': run_id, 'offline': True, 'question': task['question'],
                       'papers': [p.model_dump(mode='json') for p in papers], 'claims': [], 'evidence': [], 'map': graph}
            assert is_map_question(task['question'], payload=payload)
            first = map_chat_response(payload, task['question'], settings)
            topics = first['map_answer']['topics']
            assert {pid for topic in topics for pid in topic['paper_ids']} == {p.paper_id for p in papers}
            expected_titles = {p.title for p in papers}
            assert {p['title'] for topic in topics for p in topic['papers']} == expected_titles
            for topic in topics:
                for source in topic['sources']:
                    original = next(p for p in papers if p.paper_id == source['paper_id'])
                    assert source['paper_id'] in topic['paper_ids']
                    assert source['quote'] in (' '.join(original.title.split()) if source['field'] == 'title'
                                               else ' '.join((original.abstract or '').split()))
            history = [{'role': 'assistant', 'content': first['overview'], 'response': first}]
            follow_question = '第二个呢？' if len(topics) >= 2 else '这一组有哪些论文？'
            follow = map_chat_response(payload, follow_question, settings, history=history)
            assert len(follow['map_answer']['selected_cluster_ids']) == 1
            if len(topics) >= 2:
                assert follow['map_answer']['selected_cluster_ids'] == [topics[1]['cluster_id']]
            context = {'map_version': first['map_answer']['map_version'],
                       'cluster_ids': follow['map_answer']['selected_cluster_ids']}
            explicit_question = f'请比较 {papers[0].paper_id} 与 {papers[1].paper_id} 的方法和实验设置'
            assert not is_map_question(explicit_question, history, context, payload)
            reading_scope = resolve_cluster_reading_scope(payload, explicit_question, runs, history=history, context=context)
            assert set(reading_scope['paper_ids']) == {p.paper_id for p in papers}
            # This only resolves membership; no abstract excerpt is promoted to full text.
            cluster_scope = resolve_cluster_reading_scope(payload, '只比较这一簇的方法', runs,
                                                          history=history, context=context)
            selected_topic = next(t for t in topics if t['cluster_id'] in context['cluster_ids'])
            assert set(cluster_scope['paper_ids']) <= set(selected_topic['paper_ids'])
            assert cluster_scope['available_fulltext_count'] == 0
            old_context_rejected = None
            if previous_context:
                try:
                    map_chat_response(payload, '解释这个主题簇', settings, context=previous_context)
                except ValueError:
                    old_context_rejected = True
                else:
                    raise AssertionError('A previous research map context was accepted in a new topic')
            previous_context = context
            item = {
                'run_id': run_id, 'language': task['language'], 'question': task['question'],
                'records': [r['arxiv_id'] for r in records], 'paper_count': len(papers),
                'map_origin': graph_origin, 'embedding': graph.get('embedding'),
                'similarity_threshold': graph.get('similarity_threshold'), 'graph_seconds': round(graph_seconds, 3),
                'actual_groups': [{'cluster_id': t['cluster_id'], 'label': t['label'], 'paper_ids': t['paper_ids'],
                                   'member_arxiv_ids': [p.doi_or_arxiv for p in papers if p.paper_id in t['paper_ids']]}
                                  for t in topics] if graph_origin.startswith('computed_') else None,
                'workflow_groups': len(topics), 'follow_question': follow_question,
                'follow_selected_cluster_ids': follow['map_answer']['selected_cluster_ids'],
                'explicit_paper_route': reading_scope['source'], 'cluster_reading_membership_checked': True,
                'fulltext_processing_exercised': False, 'previous_topic_context_rejected': old_context_rejected,
                'overview': first['overview'], 'follow_overview': follow['overview'],
                'elapsed_seconds': round(time.monotonic()-task_start, 3),
            }
            report['tasks'].append(item)
            for p in papers:
                all_papers.append(p.model_copy(update={'paper_id': f'paper-{len(all_papers)+1:03d}'}))
            print(f"{task['domain']}: {len(papers)} papers; {len(topics)} groups; {graph_origin}", flush=True)
            write_json(out/'result.json', report)
        # The mixed graph is computed independently; no expected cluster count is forced.
        mixed_start = time.monotonic()
        if not semantic_unavailable:
            mixed = Dataset(papers=all_papers)
            graph = build_map(mixed, 'new-map-mixed')
            mixed_payload = {'run_id': 'new-map-mixed', 'offline': True,
                             'papers': [p.model_dump(mode='json') for p in all_papers],
                             'claims': [], 'evidence': [], 'map': graph}
            actual = base_map_topics(mixed_payload)
            by_arxiv_domain = {r['arxiv_id']: r['domain'] for r in RECORDS}
            for topic in actual['topics']:
                member_papers = [p for p in all_papers if p.paper_id in topic['paper_ids']]
                semantic_groups.append({'cluster_id': topic['cluster_id'], 'paper_ids': topic['paper_ids'],
                                        'arxiv_ids': [p.doi_or_arxiv for p in member_papers],
                                        'source_domains': sorted({by_arxiv_domain[p.doi_or_arxiv] for p in member_papers}),
                                        'label': topic['label']})
            snapshot_dataset(mixed, runs/'new-map-mixed/output')
            write_json(runs/'new-map-mixed/output/map.json', graph)
            write_json(runs/'new-map-mixed/run_manifest.json', {
                'run_id': 'new-map-mixed', 'offline': True, 'source': 'new_topic_local_validation',
                'question': 'Mixed six-paper map; actual communities only, no forced domain clusters.',
                'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'completed',
                'input_text_scope': 'abstract_excerpt', 'fulltext_processed': False,
            })
            mixed_answer = map_chat_response(mixed_payload, '混合地图的主题簇分别对应什么？', settings)
            mixed_history = [{'role': 'assistant', 'content': mixed_answer['overview'], 'response': mixed_answer}]
            mixed_follow_question = '第二个呢？' if len(actual['topics']) >= 2 else '这一组有哪些论文？'
            mixed_follow = map_chat_response(mixed_payload, mixed_follow_question, settings, history=mixed_history)
            expected_topic = actual['topics'][1 if len(actual['topics']) >= 2 else 0]
            assert mixed_follow['map_answer']['selected_cluster_ids'] == [expected_topic['cluster_id']]
            assert set(expected_topic['paper_ids']) <= {p.paper_id for p in all_papers}
            mixed_comparison_checked = False
            if len(actual['topics']) >= 2:
                compared = map_chat_response(mixed_payload, '比较第一簇和第二簇的主题差异', settings,
                                             history=mixed_history)
                assert compared['map_answer']['selected_cluster_ids'] == [t['cluster_id'] for t in actual['topics'][:2]]
                mixed_comparison_checked = True
            report['mixed_graph'] = {'status': 'computed', 'embedding': graph['embedding'],
                                     'actual_group_count': len(semantic_groups), 'actual_groups': semantic_groups,
                                     'edge_count': len(graph.get('edges', [])),
                                     'similarity_threshold': graph['similarity_threshold'],
                                     'follow_question': mixed_follow_question,
                                     'follow_selected_cluster_ids': mixed_follow['map_answer']['selected_cluster_ids'],
                                     'follow_member_paper_ids': expected_topic['paper_ids'],
                                     'follow_overview': mixed_follow['overview'],
                                     'two_cluster_comparison_checked': mixed_comparison_checked,
                                     'elapsed_seconds': round(time.monotonic()-mixed_start, 3),
                                     'interpretation': 'Observed communities of six short-excerpt inputs; no domain-quality claim or target of three communities.'}
        else:
            report['mixed_graph'] = {'status': 'semantic_model_unavailable', 'actual_groups': None,
                                     'reason': semantic_unavailable,
                                     'interpretation': 'Only supplied-member context workflows were exercised; clustering effects were not evaluated.'}
    logging.getLogger().removeHandler(runtime_messages)
    report['checks'] = ['three_new_topics_use_isolated_datasets', 'chinese_and_english_questions_route_to_current_map',
                        'theme_sources_and_members_match_each_current_dataset', 'ordinal_followup_selects_one_exact_cluster',
                        'explicit_paper_question_overrides_map_context', 'cluster_method_request_resolves_member_scope',
                        'topic_switch_rejects_previous_map_version', 'no_fulltext_claim_from_abstract_excerpts',
                        'no_hosted_model_call_or_successful_network_request']
    report.update(ok=True, semantic_model_available=not bool(semantic_unavailable),
                  elapsed_seconds=round(time.monotonic()-started, 3),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write_json(out/'result.json', report)
    print(json.dumps({'ok': True, 'tasks': len(report['tasks']), 'semantic_model_available': not bool(semantic_unavailable),
                      'mixed_group_count': report['mixed_graph'].get('actual_group_count'),
                      'network_attempts_blocked': len(report['network_attempts_blocked']),
                      'elapsed_seconds': report['elapsed_seconds']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
