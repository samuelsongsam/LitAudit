"""Live-model chat acceptance test on a disposable copy of a saved research."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check_records(records):
    checks = []
    by_turn = {int(r['input']['request_id'].split('-')[-1]) + 1: r for r in records}
    def ids(turn):
        audit = by_turn[turn]['output']['response'].get('answer_audit') or {}
        return audit.get('scope_paper_ids') or list(dict.fromkeys(c.get('paper_id') for c in audit.get('citations', [])))
    for turn, record in by_turn.items():
        checks.append({'check': f'turn_{turn}_answer', 'passed': record['output'].get('status') == 'completed'
            and bool(record['output']['response'].get('answer_audit', {}).get('ok'))})
    if 2 in by_turn:
        checks.append({'check': 'two_paper_scope', 'passed': len(ids(2)) == 2})
    if {2, 3} <= by_turn.keys():
        checks.append({'check': 'these_schemes_keep_scope', 'passed': ids(3) == ids(2)})
    if {2, 4} <= by_turn.keys():
        checks.append({'check': 'second_paper_reference', 'passed': ids(4) == ids(2)[1:2]})
    if 6 in by_turn:
        checks.append({'check': 'two_research_questions', 'passed': len(by_turn[6]['output']['response']['answer_audit'].get('questions', [])) == 2})
    if 5 in by_turn:
        response = by_turn[5]['output']['response']
        checks.append({'check': 'agent_obtained_cited_fulltext', 'passed':
            response.get('agent_execution', {}).get('status') == 'completed' and
            any(c.get('certainty') == 'fulltext_only' and c.get('page')
                for c in response.get('answer_audit', {}).get('citations', []))})
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_run')
    parser.add_argument('output')
    parser.add_argument('--turns', nargs='+', type=int)
    args = parser.parse_args()
    from src.config import load_settings
    import src.ui.server as server_module
    root_settings = load_settings()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Capture only public-test model outputs, never credentials or request headers.
    from src import grounded_transport
    original_post = grounded_transport.post_model_json
    def capture_post(*args, **kwargs):
        value = original_post(*args, **kwargs)
        with (output / 'model_outputs.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value.get('choices', []), ensure_ascii=False) + '\n')
        return value
    grounded_transport.post_model_json = capture_post
    runs = output / 'runs'
    # Build a fresh public-only dataset. Never copy private notes, conversation,
    # manual claims, uploaded documents, or arbitrary cached files.
    from src.replay import load_run
    from src.run_scope import visible_paper_ids
    from src.schema import Dataset, PaperCard, ScreeningLog, validate_dataset
    from src.pipeline import snapshot_dataset
    from src.io_utils import write_json
    from urllib.parse import urlparse
    loaded = load_run(root_settings.runs_dir, args.source_run)
    visible = visible_paper_ids(loaded['manifest'].get('live') or {})
    papers = []
    for paper in loaded['dataset'].papers:
        host = urlparse(paper.url or '').hostname or ''
        if paper.paper_id not in visible or paper.source not in {'arxiv', 'openalex'}:
            continue
        if host not in {'arxiv.org', 'www.arxiv.org', 'doi.org', 'openalex.org'}:
            continue
        papers.append(PaperCard(paper_id=paper.paper_id, title=paper.title, authors=paper.authors,
            year=paper.year, abstract=paper.abstract, doi_or_arxiv=paper.doi_or_arxiv,
            url=paper.url, source=paper.source, retrieved_at=paper.retrieved_at,
            dedup_key=paper.dedup_key, decision='include', reason='Public metadata acceptance test'))
    if not papers:
        raise ValueError('No eligible public-source papers')
    args.source_run = 'public-dialogue'
    run_dir = runs / args.source_run
    screening = [ScreeningLog(screening_id=f'acceptance-{i}', paper_id=p.paper_id,
        stage='title_abstract', decision='include', reason_code='acceptance_public_metadata',
        reason='Public metadata acceptance test; not an independent scientific inclusion judgment',
        checked_fields=['title', 'abstract'], reviewer='acceptance_test',
        reviewed_at=p.retrieved_at, scope_version='acceptance') for i, p in enumerate(papers)]
    dataset = validate_dataset(Dataset(papers=papers, screening=screening))
    if any(issue.level == 'error' for issue in dataset.issues):
        raise ValueError('Public test dataset failed validation')
    snapshot_dataset(dataset, run_dir / 'output')
    write_json(run_dir / 'output/map.json', {'status': 'unavailable', 'nodes': [], 'edges': [],
        'tracks': [], 'embedding': {'backend': 'unavailable'}, 'limitations': ['Map generation is outside this chat acceptance test.']})
    write_json(run_dir / 'run_manifest.json', {'run_id': args.source_run, 'offline': False,
        'question': 'Prefill-Decode 分离、多机多卡、资源调度和通信开销', 'status': 'completed',
        'live': {'matched_paper_ids': [p.paper_id for p in papers]}})
    settings = load_settings(runs_dir=runs)
    server_module.load_settings = lambda **kwargs: settings
    server, url = server_module.make_server(port=0, run_id=args.source_run)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    questions = [
        '根据以上检索结果，用中文总结这个方向主要解决什么问题、有哪些技术路线。只使用当前材料，每个主要观点附论文引用。',
        '从当前结果中选择两篇最相关的论文，比较它们怎样划分 prefill 和 decode 资源、怎样处理负载变化，以及适用条件。材料没说明的请标为当前材料未说明。',
        '这些方案在完全相同的硬件和负载下，分别能提高多少吞吐量？如果当前材料不能证明条件一致，请直接说明不能公平比较。',
        '只解释你刚才比较的后一篇，它怎样处理负载变化？不要重新检索，也不要换成其他论文。',
        '请从当前论文中选择一篇最相关的，检查它的实验配置和性能结果。如果摘要不足，请尝试获取开放全文并检索实验段落，再给出有出处的回答。',
        '基于当前研究材料，提出两个值得进一步验证的问题。每个问题说明已有依据、尚未解决的缺口，以及可执行的对照实验。不要把实验设想写成已有结论。',
    ]
    run_id = args.source_run
    records = []
    try:
        for index, question in enumerate(questions):
            if args.turns and index + 1 not in args.turns:
                continue
            started = time.monotonic()
            body = {'run_id': run_id, 'message': question, 'reading_mode': False,
                    'agent_mode': index == 4, 'request_id': f'acceptance-{index}'}
            print(f'TURN {index + 1} starting', flush=True)
            request = Request(url.split('?')[0] + 'api/chat', data=json.dumps(body).encode(),
                              headers={'Content-Type': 'application/json'})
            # The local acceptance server must not go through a system proxy.
            with build_opener(ProxyHandler({})).open(request, timeout=360) as response:
                result = json.load(response)
            run_id = result.get('run_id') or run_id
            records.append({'input': body, 'output': result, 'seconds': round(time.monotonic() - started, 2)})
            (output / 'transcript.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            audit = result.get('response', {}).get('answer_audit') or {}
            print(json.dumps({'turn': index+1, 'status': result.get('status'),
                'mode': result.get('response', {}).get('overview_mode'), 'kind': audit.get('kind'),
                'papers': list(dict.fromkeys(c.get('paper_id') for c in audit.get('citations', []))),
                'questions': len(audit.get('questions', [])),
                'agent': result.get('response', {}).get('agent_execution'), 'seconds': records[-1]['seconds']}, ensure_ascii=True), flush=True)
        checks = check_records(records)
        (output / 'checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
        print(json.dumps(checks), flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
