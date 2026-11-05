"""Reproducible real-paper tasks and a clearly scoped source-location study.

Network responses and PDFs are cached under output/validation/v2. Existing
validation runs are reused; old gold data and protected runs are never edited.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'output/validation/v2'
SOURCES = OUT / 'sources'
TASKS = [
    {'id': 'lora', 'question': '有限显存条件下比较LoRA和QLoRA的训练参数、量化方法与资源要求',
     'query': 'LoRA QLoRA low rank adaptation quantized finetuning', 'ids': ['2106.09685', '2305.14314'],
     'constraints': {'year_from': 2021, 'year_to': 2025, 'research_object': 'large language models', 'method': 'low rank adaptation quantization'}},
    {'id': 'segmentation', 'question': 'Compare U-Net and Attention U-Net for biomedical image segmentation: architecture, data, and evaluation.',
     'query': 'U-Net Attention U-Net biomedical image segmentation', 'ids': ['1505.04597', '1804.03999'],
     'constraints': {'year_from': 2015, 'year_to': 2025, 'research_object': 'biomedical image segmentation', 'method': 'U-Net attention gates'}},
    {'id': 'pca', 'question': '阅读本地导入的PCA教程，核查均值中心化、方差目标及SVD关系', 'ids': ['1404.1100']},
]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def cached_fetch(url, *, headers=None, timeout=25, mailto=None):
    from src.http_fetch import FetchResult, http_get
    cache = OUT / 'http'
    cache.mkdir(parents=True, exist_ok=True)
    key = sha256(url.encode()).hexdigest()
    meta, body = cache / (key+'.json'), cache / (key+'.body')
    if meta.exists():
        row = json.loads(meta.read_text(encoding='utf-8'))
        if (row.get('status') == 200 and not row.get('error')) or not ARGS.refresh_failed:
            return FetchResult(url=url, status=row.get('status'), body=body.read_bytes() if body.exists() else b'',
                               error=row.get('error'), notes=['cached_network_response'])
    start = time.perf_counter()
    response=http_get(url,headers=headers,timeout=min(timeout,18),mailto=mailto)
    content,status,error=response.body,response.status,response.error
    # The validation cache is included in the submission. Keep credentials
    # out even if a provider echoes an authentication header in an error.
    for name, value in (headers or {}).items():
        if name.lower() in {'authorization', 'x-api-key'}:
            secret = value.removeprefix('Bearer ')
            if secret:
                content = content.replace(secret.encode(), b'[redacted]')
                error = error.replace(secret, '[redacted]') if error else error
    row = {'url':url, 'status':status, 'error':error, 'seconds':round(time.perf_counter()-start, 3),
           'fetched_at':datetime.now(timezone.utc).isoformat(), 'bytes':len(content)}
    if content: body.write_bytes(content)
    dump(meta,row)
    return FetchResult(url=url,status=status,body=content,error=error)


def official_source(arxiv_id):
    SOURCES.mkdir(parents=True,exist_ok=True)
    for kind,suffix in [('abs','.html'),('pdf','.pdf')]:
        path=SOURCES/(arxiv_id+suffix)
        if not path.exists():
            response=cached_fetch(f'https://arxiv.org/{kind}/{arxiv_id}',timeout=60)
            if response.status != 200 or (kind=='pdf' and not response.body.startswith(b'%PDF-')):
                raise RuntimeError(f'Official {kind} unavailable for {arxiv_id}: HTTP {response.status}')
            path.write_bytes(response.body)
    source=(SOURCES/(arxiv_id+'.html')).read_text(encoding='utf-8')
    def metas(key):
        return [html.unescape(v) for v in re.findall(r'<meta\s+name="'+re.escape(key)+r'"\s+content="([^"]*)"',source,re.I)]
    titles=metas('citation_title');authors=metas('citation_author');published=metas('citation_date')
    match=re.search(r'<blockquote[^>]*class="abstract[^\"]*"[^>]*>(.*?)</blockquote>',source,re.S)
    abstract=html.unescape(re.sub('<[^>]+>',' ',match[1])) if match else ''
    abstract=re.sub(r'\s+',' ',abstract).replace('Abstract:','').strip()
    if not titles:raise ValueError('Official title metadata missing: '+arxiv_id)
    from src.retrieve import LiveHit
    return LiveHit(source='arxiv',title=titles[0],authors=authors,year=int(published[0][:4]) if published else int('20'+arxiv_id[:2]),
                   venue='arXiv preprint',doi_or_arxiv='arXiv:'+arxiv_id,url='https://arxiv.org/abs/'+arxiv_id,
                   abstract=abstract,dedup_key='arxiv:'+arxiv_id,open_access_pdf_url='https://arxiv.org/pdf/'+arxiv_id,
                   publication_types=['preprint'])


def prepare_task(task, settings, official):
    from src.retrieve import search_all, SearchBundle, merge_duplicate_hits, hit_keys, title_key, extract_arxiv_id
    from src.schema import Dataset, SearchQuery, RetrievalRun, dataset_stats
    from src.pipeline import run_pipeline, snapshot_dataset
    from src.replay import load_run
    from src.io_utils import write_json
    run_id='validation-v2-'+task['id']
    run_dir=settings.runs_dir/run_id
    cached=OUT/(task['id']+'-task.json')
    if cached.exists():
        saved=json.loads(cached.read_text(encoding='utf-8'))
        if (settings.runs_dir/saved.get('run_id',run_id)/'run_manifest.json').exists():return saved
    if task['id']=='pca':
        from src.import_documents import import_pdf
        paper=official[task['ids'][0]]
        result=import_pdf(settings, {'filename':'1404.1100.pdf','title':paper.title,'authors':paper.authors,'year':paper.year,
            'question':task['question'],'source_url':paper.url,'identifier':paper.doi_or_arxiv,
            'content_base64':base64.b64encode((SOURCES/'1404.1100.pdf').read_bytes()).decode()})
        result.update(task=task['id'], path='local_pdf_import',run_id=result['run_id'],discovery=None,
                      source_papers={'1404.1100':result['paper_id']})
        dump(cached,result);return result
    start=time.perf_counter()
    # Discovery is budgeted and its representation backend is explicitly recorded.
    previous=os.environ.get('LITAUDIT_RERANK_EMBEDDER')
    os.environ['LITAUDIT_RERANK_EMBEDDER']='hash'
    try:
        bundle=search_all(task['query'],cache_dir=OUT/'discovery'/task['id'],
                          openalex_api_key=settings.openalex_api_key,
                          mailto=settings.openalex_mailto,limit_per_source=6,fetch=cached_fetch,sleep_s=.15,
                          constraints=task.get('constraints'))
    finally:
        if previous is None:os.environ.pop('LITAUDIT_RERANK_EMBEDDER',None)
        else:os.environ['LITAUDIT_RERANK_EMBEDDER']=previous
    broad_ids={key for hit in bundle.hits for key in hit_keys(hit)}
    target_found={a:any(hit_keys(h) & hit_keys(official[a]) for h in bundle.hits) for a in task['ids']}
    discovery={'seconds':round(time.perf_counter()-start,3),'coverage':bundle.coverage,
               'filter_report':bundle.filter_report,'candidate_count':len(bundle.hits),'reranker':'hash_explicit_discovery_budget',
               'queries':[q.model_dump(mode='json') for q in bundle.queries],
               'requests':[r.model_dump(mode='json') for r in bundle.runs],
               'known_target_found_before_supplement':target_found}
    supplements=[]
    for arxiv_id in task['ids']:
        if not target_found[arxiv_id]:
            supplements.append(official[arxiv_id])
            qid='q-exact-arxiv-'+arxiv_id
            bundle.queries.append(SearchQuery(query_id=qid,source='arxiv',query='https://arxiv.org/abs/'+arxiv_id,
                                               purpose='开发者指定目标的官方题录精确补检索',date=date.today(),scope_version='validation-v2'))
            bundle.runs.append(RetrievalRun(retrieval_id='exact-'+arxiv_id,query_id=qid,source='arxiv',
                request='https://arxiv.org/abs/'+arxiv_id,retrieved_at=date.today(),http_status=200,status='success',
                result_count=1,response_path=str(SOURCES/(arxiv_id+'.html')),
                notes='精确查找的官方缓存题录，与宽泛检索效果分开报告'))
    bundle.hits=merge_duplicate_hits([*bundle.hits,*supplements])
    discovery['exact_supplement_ids']=[p.doi_or_arxiv for p in supplements]
    if not run_dir.exists():
        run_pipeline(settings,run_id=run_id,live=True,question=task['question'],constraints=task['constraints'],search_bundle=bundle)
    loaded=load_run(settings.runs_dir,run_id)
    papers={a:next(p for p in loaded['dataset'].papers if
                  p.dedup_key=='arxiv:'+a or extract_arxiv_id(p.doi_or_arxiv)==a or
                  title_key(p.title)==title_key(official[a].title)) for a in task['ids']}
    for a,paper in papers.items():
        target=run_dir/'cache/audit'/('document-'+sha256(paper.paper_id.encode()).hexdigest()[:16]+'.pdf')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((SOURCES/(a+'.pdf')).read_bytes())
    from src.audit_enrichment import enrich_audit
    from src.run_scope import visible_paper_ids
    dataset=enrich_audit(loaded['dataset'],root=settings.root,run_dir=run_dir,question=task['question'],
                         source_dir=run_dir,visible_ids=visible_paper_ids(loaded['manifest'].get('live') or {}))
    snapshot_dataset(dataset,run_dir/'output')
    stats=dataset_stats(dataset);write_json(run_dir/'stats.json',stats)
    manifest=loaded['manifest'];manifest.update(stats=stats,validation_preparation={
        'official_pdf_supplement':task['ids'],'notes':'官方PDF预先下载后复制到此新run，再经正式enrich_audit解析；未改金标。'})
    write_json(run_dir/'run_manifest.json',manifest)
    result={'task':task['id'],'run_id':run_id,'path':'online_discovery_with_explicit_exact_supplement',
            'source_papers':{a:p.paper_id for a,p in papers.items()},'discovery':discovery,'stats':stats}
    dump(cached,result);return result


def compare_discovery(settings, official, prepared):
    """Preserve the measured initial discovery and measure transparent decomposition.

    The same normalized English topic and per-request budget are retained; an
    explicit comparison intent activates independent named-title searches.
    This tests four known targets, not recall over all relevant literature.
    """
    from src.retrieve import search_all, hit_keys
    path=OUT/'discovery-comparison.json'
    if path.exists() and not ARGS.refresh_failed:
        return json.loads(path.read_text(encoding='utf-8'))
    previous=os.environ.get('LITAUDIT_RERANK_EMBEDDER')
    os.environ['LITAUDIT_RERANK_EMBEDDER']='hash'
    results=[]
    try:
        for task in TASKS[:2]:
            before=next(p for p in prepared if p['task']==task['id'])['discovery']
            start=time.perf_counter()
            query='Compare '+task['query']
            bundle=search_all(query,cache_dir=OUT/'discovery-after'/task['id'],
                             openalex_api_key=settings.openalex_api_key,
                             mailto=settings.openalex_mailto,limit_per_source=6,fetch=cached_fetch,
                             sleep_s=.15,constraints=task['constraints'])
            found={a:any(hit_keys(h) & hit_keys(official[a]) for h in bundle.hits) for a in task['ids']}
            results.append({'task':task['id'],'query_after':query,'known_target_ids':task['ids'],
                            'before':before,'after':{'seconds':round(time.perf_counter()-start,3),
                                'coverage':bundle.coverage,'candidate_count':len(bundle.hits),
                                'known_target_found_before_supplement':found,
                                'queries':[q.model_dump(mode='json') for q in bundle.queries],
                                'requests':[r.model_dump(mode='json') for r in bundle.runs]},
                            'caveat':'同一已知目标小样本；新策略有额外题名请求，耗时受HTTP缓存及网络波动影响；未作开放文献Recall推断。'})
            print('DISCOVERY_COMPARE',task['id'],before['known_target_found_before_supplement'],found,flush=True)
    finally:
        if previous is None:os.environ.pop('LITAUDIT_RERANK_EMBEDDER',None)
        else:os.environ['LITAUDIT_RERANK_EMBEDDER']=previous
    dump(path,results);return results


def verify_exact_lookup(settings):
    """Exercise the same public search path available to a researcher with IDs."""
    from src.retrieve import search_all, extract_arxiv_id
    path=OUT/'exact-id-lookup.json'
    if path.exists() and not ARGS.refresh_failed:
        return json.loads(path.read_text(encoding='utf-8'))
    ids=[a for task in TASKS[:2] for a in task['ids']]
    previous=os.environ.get('LITAUDIT_RERANK_EMBEDDER')
    os.environ['LITAUDIT_RERANK_EMBEDDER']='hash'
    start=time.perf_counter()
    try:
        bundle=search_all('arXiv:'+','.join(ids),cache_dir=OUT/'exact-id-discovery',
                          fetch=cached_fetch,sleep_s=.15,limit_per_source=6)
    finally:
        if previous is None:os.environ.pop('LITAUDIT_RERANK_EMBEDDER',None)
        else:os.environ['LITAUDIT_RERANK_EMBEDDER']=previous
    found={extract_arxiv_id(hit.doi_or_arxiv):hit.title for hit in bundle.hits}
    result={'mode':'explicit_user_supplied_arxiv_ids','seconds':round(time.perf_counter()-start,3),
            'expected_ids':ids,'found':found,'all_expected_found':all(a in found for a in ids),
            'coverage':bundle.coverage,'requests':[r.model_dump(mode='json') for r in bundle.runs],
            'caveat':'已知ID精确查找，不计入开放主题发现成功率。'}
    dump(path,result);return result


REFERENCE_SPECS=[
 ('lora-freeze','lora','zh','2106.09685','LoRA如何冻结预训练权重并注入可训练的低秩矩阵？','injects trainable rank decomposition matrices'),
 ('qlora-techniques','lora','zh','2305.14314','QLoRA有哪些量化和显存优化方法？','4-bit NormalFloat (NF4)'),
 ('qlora-memory','lora','en','2305.14314','What GPU memory is reported for finetuning a 65B model with QLoRA?','single 48GB GPU'),
 ('unet-paths','segmentation','en','1505.04597','How does U-Net combine a contracting path and an expanding path?','contracting path to capture context and a symmetric expanding path'),
 ('unet-augmentation','segmentation','zh','1505.04597','U-Net训练数据较少时使用了什么弹性形变数据增强方法？','elastic deformations'),
 ('attention-data','segmentation','en','1804.03999','Which NIH CT dataset is used to evaluate Attention U-Net pancreas segmentation?','NIH-TCIA'),
 ('pca-centering','pca','zh','1404.1100','PCA如何对每种测量进行均值中心化预处理？','Subtract off the mean for each measurement type.'),
 ('pca-objective','pca','en','1404.1100','What does PCA minimize and maximize in the covariance objective?','minimize redundancy'),
 ('pca-svd','pca','zh','1404.1100','PCA与奇异值分解SVD之间有什么关系？','PCA is closely related to singular value decomposition'),
]


def build_references():
    from src.research_eval import normalize
    from pypdf import PdfReader
    references=[]
    for rid,task,lang,arxiv_id,question,quote in REFERENCE_SPECS:
        source=SOURCES/(arxiv_id+'.pdf');reader=PdfReader(source)
        pages=[i+1 for i,page in enumerate(reader.pages) if normalize(quote) in normalize(page.extract_text() or '')]
        if not pages:raise ValueError('Reference quote not found in real PDF: '+rid)
        references.append({'id':rid,'task':task,'language':lang,'arxiv_id':arxiv_id,'question':question,
                           'quote':quote,'pages':pages,'pdf_sha256':sha256(source.read_bytes()).hexdigest(),
                           'reference_method':'developer-selected quote, verified against actual PDF text before scoring'})
    reference={'version':'developer_source_location_v2','created_at':datetime.now(timezone.utc).isoformat(),
               'description':'开发者根据五篇公开PDF整理的9题定位样本，不是独立人工盲评或开放文献Recall金标。',
               'references':references}
    path=ROOT/'data/research_eval_v2.json'
    if path.exists():
        frozen=json.loads(path.read_text(encoding='utf-8'))
        if frozen.get('references') != references:
            raise ValueError('固定参考集或源PDF发生变化，停止评分；请另建版本而不要覆盖此参考。')
    else:
        dump(path,reference)
    return references


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('MKL_NUM_THREADS','4')
    from src.config import load_settings
    from src.pipeline import snapshot_dataset
    from src.schema import Dataset
    settings=load_settings(offline=False)
    empty=OUT/'empty-data';snapshot_dataset(Dataset(),empty)
    settings=replace(settings,data_dir=empty,live_limit=30)
    ids=[a for task in TASKS for a in task['ids']]
    with ThreadPoolExecutor(max_workers=3) as pool:
        official=dict(zip(ids,pool.map(official_source,ids)))
    references=build_references()
    prepared=[]
    for task in TASKS:
        result=prepare_task(task,settings,official);prepared.append(result)
        print('TASK_READY',task['id'],result['run_id'],flush=True)
        dump(OUT/'tasks.json',prepared)
    source_manifest=[{'arxiv_id':a,'title':official[a].title,'url':'https://arxiv.org/pdf/'+a,
                      'pdf_path':str((SOURCES/(a+'.pdf')).relative_to(ROOT)),
                      'pdf_sha256':sha256((SOURCES/(a+'.pdf')).read_bytes()).hexdigest()} for a in ids]
    dump(OUT/'sources.json',source_manifest)
    if ARGS.prepare_only:return
    discovery_comparison=compare_discovery(settings,official,prepared)
    exact_lookup=verify_exact_lookup(settings)
    os.environ['LITAUDIT_RERANK_EMBEDDER']=ARGS.embedder
    from src.research_workspace import _corpus
    from src.research_eval import run_reference_evaluation
    corpora={}
    for task in prepared:
        papers,pages,_=_corpus(settings.runs_dir,task['run_id'])
        # Compare on the same known-paper corpus, not unrelated discovery hits.
        selected=set(task['source_papers'].values())
        corpora[task['task']]={'papers':{k:v for k,v in papers.items() if k in selected},
                               'pages':{k:v for k,v in pages.items() if k in selected},
                               'paper_ids':task['source_papers']}
    evaluation=run_reference_evaluation(references,corpora)
    report={'created_at':datetime.now(timezone.utc).isoformat(),'tasks':prepared,'sources':source_manifest,
            'evaluation':evaluation,'discovery_comparison':discovery_comparison,'exact_lookup':exact_lookup,
            'requested_embedder':ARGS.embedder}
    dump(OUT/'report.json',report)
    print('SUMMARY',json.dumps(evaluation['summary'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--refresh-failed',action='store_true')
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--embedder',choices=['specter2','hash'],default='specter2')
    ARGS=parser.parse_args();main()
