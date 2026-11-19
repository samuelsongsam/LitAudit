"""Experimental comparison never joins independently selected study fields."""
import csv
from hashlib import sha256
import io

import pytest

from src.io_utils import write_json, write_jsonl
from src.research_workspace import _condition_mentions, export_method_csv, method_comparison, save_review


def make_run(tmp_path, bodies):
    runs = tmp_path / 'runs'
    run = runs / 'config-study'
    out = run / 'output'
    out.mkdir(parents=True)
    write_json(run/'run_manifest.json', {'run_id': 'config-study', 'offline': True})
    write_json(out/'search_queries.json', [])
    papers, docs = [], []
    for index, body in enumerate(bodies, 1):
        pid = 'p'+str(index)
        papers.append({'paper_id': pid, 'title': 'Synthetic configuration '+str(index),
                       'source': 'unit-test', 'url': 'https://example.org/'+pid,
                       'retrieved_at': '2026-11-04', 'dedup_key': pid,
                       'decision': 'include', 'reason': 'Synthetic comparison boundary test'})
        path = run/'cache'/f'{pid}.json'
        write_json(path, [{'page': 1, 'text': 'Methods\n'+body}])
        docs.append({'paper_id': pid, 'status': 'parsed', 'text_path': f'cache/{pid}.json'})
    write_jsonl(out/'papers.jsonl', papers)
    write_jsonl(out/'paper_cards.jsonl', papers)
    write_json(out/'fulltext_audit.json', {'documents': docs})
    return runs, run


def test_configuration_context_preserves_one_original_sentence_and_hash(tmp_path):
    text = 'We evaluate accuracy on the MNLI dataset using batch size 16 and sequence length 128.'
    runs, _ = make_run(tmp_path, [text])
    paper = method_comparison(runs, 'config-study')['papers'][0]
    assert paper['experiment_contexts']
    context = paper['experiment_contexts'][0]
    source = context['source']
    assert source['quote'] in source['text'] and source['page'] == 1
    assert source['text_sha256'] == sha256(source['text'].encode()).hexdigest()
    assert source['quote_sha256'] == sha256(source['quote'].encode()).hexdigest()
    assert source['text'][source['quote_start']:source['quote_end']] == source['quote']
    assert context['condition_mentions']['datasets'] == ['MNLI']
    assert context['condition_mentions']['settings']['batch_size'] == ['16']
    assert context['association'] == 'same_sentence_context_only'
    assert context['human_confirmed'] is False


def test_independent_sentences_are_not_joined_into_a_complete_experiment(tmp_path):
    runs, _ = make_run(tmp_path, [
        'The dataset contains 240 participants. '
        'The evaluation metrics are accuracy and recall. '
        'The experimental setup uses five-fold cross-validation.'
    ])
    paper = method_comparison(runs, 'config-study')['papers'][0]
    assert paper['fields']['data']['candidate']
    assert paper['fields']['metrics']['candidate']
    assert paper['fields']['experiment']['candidate']
    assert not any({'data', 'metrics', 'experiment'} <= context['fields'].keys()
                   for context in paper['experiment_contexts'])
    shared = set(paper['fields']['data']['experiment_context_ids'])
    shared &= set(paper['fields']['metrics']['experiment_context_ids'])
    shared &= set(paper['fields']['experiment']['experiment_context_ids'])
    assert not shared


@pytest.mark.parametrize(('first', 'second', 'expected'), [
    ('MNLI', 'SST-2', 'conditions_differ'),
    ('MNLI', 'MNLI', 'needs_manual_confirmation'),
])
def test_matching_names_do_not_authorize_automatic_result_ranking(tmp_path, first, second, expected):
    runs, _ = make_run(tmp_path, [
        f'We evaluate accuracy on the {first} dataset using batch size 16.',
        f'We evaluate accuracy on the {second} dataset using batch size 16.'
    ])
    result = method_comparison(runs, 'config-study')
    pair = result['comparability']['pairs'][0]
    assert pair['status'] == expected
    assert pair['automatic_ranking_allowed'] is False
    assert pair['direct_result_comparison'] is False


def test_missing_and_inconsistent_settings_are_explicit(tmp_path):
    runs, run = make_run(tmp_path, [
        'We evaluate accuracy on the MNLI dataset using batch size 16.',
        'We evaluate accuracy on the MNLI dataset using sequence length 128.'
    ])
    pair = method_comparison(runs, 'config-study')['comparability']['pairs'][0]
    assert pair['status'] == 'insufficient_evidence'
    write_json(run/'cache/p2.json', [{'page': 1, 'text': 'Methods\nWe evaluate accuracy on the MNLI dataset using batch size 32.'}])
    pair = method_comparison(runs, 'config-study')['comparability']['pairs'][0]
    assert pair['status'] == 'conditions_differ'
    assert next(c for c in pair['checks'] if c['key']=='settings')['status'] == 'different'


def test_multi_dataset_sentence_stays_ambiguous(tmp_path):
    sentence = 'We evaluate accuracy on the MNLI and SST-2 datasets using batch size 16.'
    runs, _ = make_run(tmp_path, [sentence, sentence])
    result = method_comparison(runs, 'config-study')
    assert 'multiple_dataset_mentions' in result['papers'][0]['experiment_contexts'][0]['ambiguity_reasons']
    assert result['comparability']['pairs'][0]['status'] == 'multiple_configurations'


def test_candidates_remain_selectable_and_review_never_confirms_experiment_identity(tmp_path):
    runs, _ = make_run(tmp_path, [
        'We evaluate accuracy on the MNLI dataset using batch size 16. '
        'The experimental setup uses five-fold cross-validation. '
        'We use a sequence length of 128 to match the baseline.'
    ])
    paper = method_comparison(runs, 'config-study')['papers'][0]
    field = paper['fields']['experiment']
    assert 1 <= len(field['candidates']) <= 5
    candidate = field['candidates'][-1]
    save_review(runs, 'config-study', {'passage_id': candidate['passage_id'], 'field':'experiment',
                                    'status':'accepted', 'quote':candidate['quote'],
                                    'expected_text_sha256':candidate['text_sha256'], 'display_value':'人工选择的实验设置'})
    paper = method_comparison(runs, 'config-study')['papers'][0]
    assert paper['fields']['experiment']['candidate']['quote'] == candidate['quote']
    assert paper['fields']['experiment']['candidate']['value'] == '人工选择的实验设置'
    assert all(c['human_confirmed'] is False for c in paper['experiment_contexts'])


def test_csv_keeps_condition_warnings_with_existing_human_fields(tmp_path):
    runs, _ = make_run(tmp_path, [
        'We evaluate accuracy on the MNLI dataset using batch size 16.',
        'We evaluate accuracy on the CIFAR-10 dataset using batch size 32.'
    ])
    rows = list(csv.reader(io.StringIO(export_method_csv(runs, 'config-study').lstrip('\ufeff'))))
    assert rows[0][-3:] == ['实验配置关联', '配置线索编号', '跨论文比较说明']
    assert all('不能直接按结果数值排名' in row[-1] for row in rows[1:])


def test_online_scope_excludes_hidden_experiment_contexts(tmp_path):
    runs, run = make_run(tmp_path, [
        'We evaluate accuracy on the MNLI dataset using batch size 16.',
        'We evaluate accuracy on the CIFAR-10 dataset using batch size 32.'
    ])
    write_json(run/'run_manifest.json', {'run_id':'config-study','offline':False,'live':{'matched_paper_ids':['p2']}})
    result = method_comparison(runs, 'config-study')
    assert {p['paper_id'] for p in result['papers']} == {'p2'}
    assert result['comparability']['pairs'] == []
    assert all(c['paper_id']=='p2' for p in result['papers'] for c in p['experiment_contexts'])


def test_precision_datatype_and_model_names_do_not_become_evaluation_conditions():
    mentions = _condition_mentions('Guanaco uses 4-bit precision and improves on the Stanford Alpaca finetuned model.')
    assert mentions['metrics'] == []
    assert mentions['datasets'] == []
    assert mentions['settings']['precision'] == ['4bit']
    mentions = _condition_mentions('We report accuracy for 7-65B models finetuned on the Alpaca dataset.')
    assert mentions['settings']['model_parameters'] == ['7-65b']
    assert mentions['datasets'] == ['ALPACA']
