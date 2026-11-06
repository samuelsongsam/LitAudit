import json
from urllib.parse import parse_qs, urlparse

import pytest

from src.http_fetch import FetchResult
from src.research_query import validate_search_supplement
from src.retrieve import QuerySpec, _source_urls, search_all


@pytest.fixture(autouse=True)
def deterministic_dependencies(monkeypatch):
    monkeypatch.setattr('src.retrieve.time.sleep', lambda seconds: None)
    monkeypatch.setattr('src.retrieval_rank.rank_hits', lambda question, hits: (hits, {'backend': 'test'}))


def plan(monkeypatch, source, *, query='test topic'):
    monkeypatch.setattr('src.retrieve.build_query_plan', lambda *args: [QuerySpec('q-topic', source, query, 'topic')])


def oa_body(ids, total=100):
    return json.dumps({'meta': {'count': total}, 'results': [
        {'id': f'https://openalex.org/W{i}', 'title': f'Unique topic study {i}',
         'publication_year': 2024, 'doi': f'https://doi.org/10.9999/paper{i}'} for i in ids]}).encode()


def arxiv_body(ids, total=100):
    entries=''.join(f'<entry><id>https://arxiv.org/abs/2401.{i:05}</id><title>Unique study {i}</title>'
                    '<summary>A method for the topic.</summary><published>2024-01-01T00:00:00Z</published>'
                    '<author><name>Researcher</name></author></entry>' for i in ids)
    return ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
            f'<opensearch:totalResults>{total}</opensearch:totalResults>{entries}</feed>').encode()


@pytest.mark.parametrize('value', [True, [], {'pages_per_query': 0}, {'pages_per_query': 4},
    {'max_requests': True}, {'max_requests': 13}, {'sources': []}, {'sources': ['invalid']},
    {'sources': [[]]}, {'unknown': 1}])
def test_invalid_supplement_budget_is_rejected_before_requests(value):
    with pytest.raises(ValueError):
        validate_search_supplement(value)


def test_budget_is_opt_in_and_empty_keeps_original_request_count(tmp_path, monkeypatch):
    plan(monkeypatch, 'openalex')
    seen=[]
    def fetch(url, **kwargs):
        seen.append(url)
        return FetchResult(url, 200, oa_body([1,2]))
    for setting in [None, {}]:
        seen.clear()
        bundle=search_all('topic', cache_dir=tmp_path, limit_per_source=2, fetch=fetch, sleep_s=0,
                          supplement=setting)
        assert len(seen)==1 and not bundle.search_budget['enabled']
        assert bundle.coverage['openalex']['truncated']


def test_openalex_pages_are_distinct_traceable_and_count_unique_additions(tmp_path, monkeypatch):
    plan(monkeypatch, 'openalex')
    seen=[]
    def fetch(url, **kwargs):
        params=parse_qs(urlparse(url).query);page=int(params.get('page',['1'])[0]);seen.append(page)
        return FetchResult(url,200,oa_body({1:[1,2],2:[2,3],3:[4,5]}[page],total=5))
    result=search_all('topic', cache_dir=tmp_path, limit_per_source=2, fetch=fetch, sleep_s=0,
                      supplement={'pages_per_query':2,'max_requests':2,'sources':['openalex']})
    assert seen==[1,2,3]
    assert len(result.hits)==5 and len(result.runs)==3
    assert result.search_budget['additional_requests_used']==2
    assert result.search_budget['additional_unique_count']==3
    batches=result.coverage['openalex']['batches']
    assert [b['new_unique_count'] for b in batches]==[2,1,2]
    assert not result.coverage['openalex']['truncated']
    assert len({r.query_id for r in result.runs})==3
    assert all((tmp_path/f'{q.query_id}.json').is_file() for q in result.queries)
    assert '补充第2页' in result.queries[1].purpose


def test_arxiv_uses_start_and_reuses_successful_host_with_bounded_calls(tmp_path, monkeypatch):
    plan(monkeypatch,'arxiv')
    seen=[]
    def fetch(url, **kwargs):
        params=parse_qs(urlparse(url).query);offset=int(params['start'][0]);seen.append((urlparse(url).netloc,offset))
        if 'export.arxiv' in url:
            return FetchResult(url,503,b'')
        return FetchResult(url,200,arxiv_body([offset+1,offset+2],total=6))
    result=search_all('topic', cache_dir=tmp_path, limit_per_source=2, fetch=fetch, sleep_s=0,
                      supplement={'pages_per_query':2,'max_requests':1,'sources':['arxiv']})
    assert seen==[('export.arxiv.org',0),('arxiv.org',0),('arxiv.org',2)]
    assert len(result.hits)==4 and result.search_budget['additional_requests_used']==1
    assert result.coverage['arxiv']['batches'][-1]['stop_reason']=='additional_request_budget_exhausted'
    assert result.coverage['arxiv']['truncated']


def test_archived_source_selection_keeps_active_pages_without_retired_requests(tmp_path, monkeypatch):
    monkeypatch.setattr('src.retrieve.build_query_plan', lambda *args: [
        QuerySpec('q-oa', 'openalex', 'topic', 'topic'),
        QuerySpec('q-s2', 'semantic_scholar', 'topic', 'topic')])
    seen = []

    def fetch(url, **kwargs):
        assert urlparse(url).hostname == 'api.openalex.org'
        page = int(parse_qs(urlparse(url).query).get('page', ['1'])[0])
        seen.append(page)
        return FetchResult(url, 200, oa_body([page], total=2))

    result = search_all('topic', cache_dir=tmp_path, limit_per_source=1, fetch=fetch,
                        base_sources=['openalex', 'semantic_scholar'],
                        supplement={'sources': ['semantic_scholar', 'openalex']})
    assert seen == [1, 2]
    assert set(result.coverage) == {'arxiv', 'openalex'}
    assert result.search_budget['sources'] == ['openalex']


def test_repeated_page_stops_without_burning_remaining_budget(tmp_path, monkeypatch):
    plan(monkeypatch,'openalex');seen=[]
    def fetch(url, **kwargs):
        seen.append(url);return FetchResult(url,200,oa_body([1,2],100))
    result=search_all('topic', cache_dir=tmp_path, limit_per_source=2, fetch=fetch, sleep_s=0,
                      supplement={'pages_per_query':3,'max_requests':3})
    assert len(seen)==2 and len(result.hits)==2
    assert result.coverage['openalex']['batches'][-1]['stop_reason']=='repeated_page_no_new_query_records'
    assert result.search_budget['additional_unique_count']==0


def test_supplement_429_is_not_zero_success_and_does_not_auto_retry(tmp_path, monkeypatch):
    plan(monkeypatch,'openalex');seen=[]
    def fetch(url, **kwargs):
        seen.append(url)
        return FetchResult(url,200,oa_body([1,2])) if len(seen)==1 else FetchResult(url,429,b'{"error":"limited"}')
    result=search_all('topic', cache_dir=tmp_path, limit_per_source=2, fetch=fetch, sleep_s=0,
                      supplement={'pages_per_query':3,'max_requests':1})
    assert len(seen)==2 and result.runs[-1].status=='rate_limited'
    assert result.runs[-1].result_count is None
    assert result.coverage['openalex']['status']=='partial' and result.coverage['openalex']['truncated']


def test_id_lookup_is_never_paginated(tmp_path, monkeypatch):
    plan(monkeypatch,'arxiv',query='id_list:2401.00001');seen=[]
    def fetch(url, **kwargs):
        seen.append(url);return FetchResult(url,200,arxiv_body([1],100))
    result=search_all('arxiv:2401.00001', cache_dir=tmp_path,limit_per_source=1,fetch=fetch,sleep_s=0,
                      supplement={'pages_per_query':3,'max_requests':3})
    assert len(seen)==1 and result.search_budget['additional_requests_used']==0


def test_cancel_checkpoint_stops_before_next_provider_request(tmp_path, monkeypatch):
    from src.tasks import TaskCancelled
    plan(monkeypatch,'openalex');requests=[];stages=[]
    def checkpoint(stage):
        stages.append(stage)
        if stage=='retrieval_supplement':
            raise TaskCancelled('stop')
    monkeypatch.setattr('src.retrieve._retrieval_checkpoint',checkpoint)
    def fetch(url, **kwargs):
        requests.append(url);return FetchResult(url,200,oa_body([1,2]))
    with pytest.raises(TaskCancelled):
        search_all('topic',cache_dir=tmp_path,limit_per_source=2,fetch=fetch,sleep_s=0,
                   supplement={'pages_per_query':1,'max_requests':1})
    assert len(requests)==1 and stages==['retrieval_request','retrieval_response','retrieval_supplement']


def test_pagination_urls_retain_provider_filters():
    constraints={'year_from':2020,'year_to':2024,'publication_type':'review'}
    spec=QuerySpec('q','openalex','topic','search',constraints)
    params=parse_qs(urlparse(_source_urls(spec,limit=15,mailto=None,offset=30)[0]).query)
    assert params['page']==['3'] and 'type:review' in params['filter'][0]


def test_only_requested_base_source_is_retried_and_others_are_not_requested(tmp_path, monkeypatch):
    monkeypatch.setattr('src.retrieve.build_query_plan', lambda *args: [
        QuerySpec('q-arxiv','arxiv','topic','topic'),
        QuerySpec('q-oa','openalex','topic','topic'),
        QuerySpec('q-s2','semantic_scholar','topic','topic')])
    seen=[]
    def fetch(url, **kwargs):
        seen.append(url);assert 'openalex.org' in url
        return FetchResult(url,200,oa_body([1,2],2))
    result=search_all('topic',cache_dir=tmp_path,fetch=fetch,sleep_s=0,base_sources=['openalex'])
    assert len(seen)==1 and result.coverage['openalex']['status']=='success'
    assert result.coverage['arxiv']['status']=='not_requested'
    assert 'semantic_scholar' not in result.coverage
    assert result.search_budget['requested_base_sources']==['openalex']


@pytest.mark.parametrize('sources',[[], 'openalex', ['unknown'], [True], ['semantic_scholar']])
def test_invalid_base_sources_rejected_before_any_network(tmp_path,sources):
    def forbidden(*args,**kwargs):
        raise AssertionError('No request should run')
    with pytest.raises(ValueError):
        search_all('topic',cache_dir=tmp_path,fetch=forbidden,base_sources=sources)
