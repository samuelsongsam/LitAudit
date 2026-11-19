"""Versioned map topics and map-aware conversation, grounded in cluster members.

Map membership is computed by the map builder.  Names are annotations over that
membership, never a replacement for it.  Optional model annotations live in an
independent cache, so reading and naming maps never changes a research snapshot.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
import threading
from time import monotonic

from src.answer_audit import scoped_payload
from src.grounded_transport import post_model_json
from src.io_utils import replace_with_retry
from src.run_paths import resolve_run_dir

SCHEMA_VERSION = 2
MAX_TOPIC_PAPERS = 8
MAX_PAPERS_PER_REQUEST = 24
_TOPIC_REFRESH_SECONDS = 35
GROUPING_DESCRIPTION = '按题名与摘要的语义相近程度分组，可逐篇查看研究任务。'
_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()
_STOP = set('the and for with from that this using based via into over under study paper '
            'propose proposed approach method methods model models learning data results '
            'show shows which their these our can are was were has have its new also an '
            'of to in on at as by is be we it a or not more than across towards through '
            'efficient performance large deep neural network networks research analysis'.split())
_TERMS = [
    (r'\bqlora\b|quantiz.{0,80}low.rank|low.rank.{0,80}quantiz', '量化低秩适配'),
    (r'\blora\b|low.rank adapt', '低秩适配'),
    (r'quantiz', '模型量化'), (r'fine.?tun', '模型微调'),
    (r'segmentation|图像分割', '图像分割'), (r'medical|biomedical|clinical|医学|医疗|临床', '医学研究'),
    (r'\bu.net\b', 'U-Net'), (r'\battention\b|注意力', '注意力机制'),
    (r'transformer', 'Transformer'), (r'contrastive|对比学习', '对比学习'),
    (r'anomaly|异常检测', '异常检测'), (r'time.series|时间序列', '时间序列'),
    (r'forecast|预测', '预测'), (r'principal component|\bpca\b|主成分', '主成分分析'),
    (r'causal|因果', '因果推断'), (r'retrieval.augmented|\brag\b|检索增强', '检索增强生成'),
    (r'graph neural|\bgnn\b|图神经', '图神经网络'), (r'federated|联邦', '联邦学习'),
    (r'diffusion|扩散', '扩散模型'), (r'robot|机器人', '机器人'),
    (r'protein|蛋白', '蛋白质'), (r'finance|financial|金融', '金融'),
]
# These scope qualifiers can turn a shared research object into a paper-specific
# application or method. Match explicit equivalents in each supplied record.
_SHARED_SCOPE = [
    *[pattern for pattern, term in _TERMS if term in {
        '医学研究', '图像分割', '异常检测', '因果推断', '检索增强生成', '联邦学习',
        '扩散模型', '蛋白质', '金融',
    }],
    r'\btraffic\b|交通', r'\b(?:forecast\w*|predict\w*)\b|预测',
    r'\bbimanual\b|双臂', r'\blow.cost hardware\b|低成本硬件',
    r'\bPDEs?\b|partial differential equations?|偏微分方程',
    r'\bODEs?\b|ordinary differential equations?|常微分方程',
]


def _digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _space(value) -> str:
    return ' '.join(str(value or '').split())


def _cache_path(runs_dir: Path, run_id: str, version: str) -> Path:
    # Reuse run-id validation without placing annotations in protected snapshots.
    resolve_run_dir(Path(runs_dir), run_id)
    if not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{64}', version):
        raise ValueError('地图版本无效')
    return Path(runs_dir).resolve() / '.map-topics' / run_id / (version + '.json')


def _lock(path: Path):
    with _LOCK_GUARD:
        return _LOCKS.setdefault(str(path), threading.RLock())


def _write_cache(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.topics-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
        replace_with_retry(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _terms(papers: list[dict]) -> list[str]:
    scores = []
    texts = [(_space(p.get('title')), _space(p.get('abstract'))) for p in papers]
    for pattern, label in _TERMS:
        count = sum(2 * bool(re.search(pattern, title, re.I)) + bool(re.search(pattern, abstract, re.I))
                    for title, abstract in texts)
        if count:
            scores.append((count, label))
    scores.sort(key=lambda x: -x[0])
    known = [label for _, label in scores]
    known = [label for label in known if not any(label != other and label in other for other in known)]
    if len(known) >= 2:
        return known[:5]
    tokens = Counter()
    for title, _ in texts:
        tokens.update(t for t in re.findall(r'[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,8}', title)
                      if t.lower() not in _STOP)
    return list(dict.fromkeys(known + [t for t, _ in tokens.most_common(6)]))[:5]


def base_map_topics(payload: dict) -> dict:
    """Derive exact members and useful term labels without model or disk writes."""
    visible = scoped_payload(payload)
    papers = {p['paper_id']: p for p in visible.get('papers', []) if p.get('paper_id')}
    graph = payload.get('map') or {}
    nodes = {n['paper_id']: n for n in graph.get('nodes', []) if n.get('paper_id') in papers}
    groups = []
    assigned = set()
    for track in graph.get('tracks', []):
        ids = sorted(set(p for p in track.get('paper_ids', []) if p in nodes and p not in assigned))
        if ids:
            groups.append((track.get('track_id'), ids))
            assigned.update(ids)
    for pid in sorted(set(nodes) - assigned):
        groups.append((None, [pid]))
    fingerprint = {'schema': SCHEMA_VERSION, 'algorithm': graph.get('algorithm'),
                   'embedding': {k: (graph.get('embedding') or {}).get(k) for k in ['backend', 'model']},
                   'groups': [{'track_id': track_id, 'paper_ids': ids} for track_id, ids in groups],
                   'texts': [{k: papers[pid].get(k) for k in ['paper_id', 'title', 'abstract']}
                             for pid in sorted(nodes)]}
    version = _digest(fingerprint)
    topics = []
    for index, (track_id, ids) in enumerate(groups, 1):
        members = [papers[pid] for pid in ids]
        keywords = _terms(members)
        label = ' · '.join(keywords[:2]) or _space(members[0].get('title'))[:48] or '论文集合'
        ranked = sorted(ids, key=lambda pid: (-float(nodes[pid].get('semantic_degree') or 0), pid))
        representatives = [{'paper_id': pid, 'title': papers[pid].get('title') or pid,
                            'year': papers[pid].get('year')} for pid in ranked[:3]]
        sources = [{'paper_id': p['paper_id'], 'field': 'title', 'quote': _space(p.get('title'))}
                   for p in members if p.get('title')][:6]
        topics.append({'cluster_id': 'topic-' + _digest(ids)[:20], 'track_id': track_id,
                       'display_index': index, 'label': label, 'summary': GROUPING_DESCRIPTION,
                       'common_direction': '', 'common_sources': [], 'paper_tasks': [],
                       'keywords': keywords, 'paper_ids': ids, 'member_count': len(ids),
                       'representative_papers': representatives,
                       'papers': [{'paper_id': pid, 'title': papers[pid].get('title') or pid,
                                   'year': papers[pid].get('year')} for pid in ids],
                       'sources': sources, 'label_source': 'terms', 'map_version': version})
    return {'run_id': payload.get('run_id'), 'schema_version': SCHEMA_VERSION,
            'map_version': version, 'topics': topics, 'naming_status': 'terms',
            'grouping': {'input': 'title + abstract', 'embedding': (graph.get('embedding') or {}).get('backend'),
                         'method': 'semantic_similarity_communities'},
            'paper_count': len(nodes), 'cluster_count': len(topics)}


def save_topic_snapshot(topics: dict, runs_dir: Path) -> None:
    """Keep topic versions for graph-message replay, outside research snapshots."""
    path = _cache_path(runs_dir, topics['run_id'], topics['map_version'])
    with _lock(path):
        _write_cache(path, topics)


def _checked_source(source, paper_ids: set[str], papers: dict) -> dict:
    if not isinstance(source, dict) or source.get('paper_id') not in paper_ids:
        raise ValueError('归纳引用应来自对应论文')
    pid, field, quote = source['paper_id'], source.get('field'), source.get('quote')
    if field not in {'title', 'abstract'} or not isinstance(quote, str) or len(quote.strip()) < 8:
        raise ValueError('主题引用位置无效')
    original = _space(papers[pid].get(field))
    if field == 'abstract':
        original = original[:900]
    if _space(quote) not in original:
        raise ValueError('主题引用与输入摘录不一致')
    return {'paper_id': pid, 'field': field, 'quote': _space(quote)}


def _annotation_text(value, *, min_length: int, max_length: int) -> str:
    if not isinstance(value, str) or not min_length <= len(_space(value)) <= max_length:
        raise ValueError('主题名称或解释长度无效')
    if any(s in value for s in ['不代表', '不作', '待补充', '还需要补充']):
        raise ValueError('主题解释应直接描述研究内容')
    return _space(value)


def _scope_conflict(text: str, members: list[str]) -> bool:
    return any(re.search(pattern, text, re.I) and not all(re.search(pattern, p, re.I) for p in members)
               for pattern in _SHARED_SCOPE)


def _validate_annotations(base: dict, rows, papers: dict) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError('主题标注应为数组')
    by_id = {t['cluster_id']: t for t in base['topics']}
    accepted, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('cluster_id') not in by_id or row['cluster_id'] in seen:
            raise ValueError('主题编号无效或重复')
        topic = by_id[row['cluster_id']]
        label = _annotation_text(row.get('label'), min_length=2, max_length=80)
        direction = _annotation_text(row.get('common_direction'), min_length=0, max_length=240)
        if (re.search(r'placeholder|sample topic|示例主题|短中文主题名|^主题名称$|^主题名$|^主题[ A-Za-z一二三四五六七八九十\d]+$', label, re.I)
                or re.fullmatch(r'[XxＸｘ]{2,}', label.strip())):
            raise ValueError('主题名应概括成员论文内容')
        member_texts = [_space(papers[pid].get('title')) + ' ' + _space(papers[pid].get('abstract'))[:900]
                        for pid in topic['paper_ids']]
        source_text = ' '.join(member_texts)
        for pattern, term in _TERMS:
            label_mentions = term in label or re.search(pattern, label, re.I)
            if label_mentions and not re.search(pattern, source_text, re.I) and term not in source_text:
                raise ValueError('主题名中的研究方向与成员题名摘要不一致')
        provided = set(topic['paper_ids'][:MAX_TOPIC_PAPERS])
        common_sources = row.get('common_sources')
        if not isinstance(common_sources, list) or len(common_sources) != (len(provided) if direction else 0):
            raise ValueError('共同方向应为每篇成员论文提供一条独立来源')
        common_sources = [_checked_source(s, provided, papers) for s in common_sources]
        if direction and (len(provided) != topic['member_count'] or {s['paper_id'] for s in common_sources} != provided):
            raise ValueError('共同方向应覆盖全部成员论文')
        if direction and _scope_conflict(label, member_texts):
            direction, common_sources = '', []
        elif direction and _scope_conflict(direction, member_texts):
            # The separately generated topic name may express the broader
            # direction without the added application in the longer prose.
            direction = label

        tasks = row.get('paper_tasks')
        if not isinstance(tasks, list) or len(tasks) != len(provided):
            raise ValueError('每篇输入论文应有一条独立的任务说明')
        by_paper = {}
        for task in tasks:
            pid = task.get('paper_id') if isinstance(task, dict) else None
            if pid not in provided or pid in by_paper:
                raise ValueError('论文任务编号无效或重复')
            by_paper[pid] = {'paper_id': pid,
                             'task': _annotation_text(task.get('task'), min_length=4, max_length=240),
                             'source': _checked_source(task.get('source'), {pid}, papers)}
        paper_tasks = [by_paper[pid] for pid in topic['paper_ids'] if pid in by_paper]
        sources = [*common_sources, *(task['source'] for task in paper_tasks)]
        sources = list({(s['paper_id'], s['field'], s['quote']): s for s in sources}.values())
        keywords = row.get('keywords') or topic['keywords']
        if not isinstance(keywords, list) or len(keywords) > 8 or any(not isinstance(t, str) or len(t) > 80 for t in keywords):
            raise ValueError('主题关键词无效')
        accepted.append({**topic, 'label': label if direction else f'相近论文 {topic["display_index"]}',
                         'summary': direction or GROUPING_DESCRIPTION, 'common_direction': direction,
                         'common_sources': common_sources, 'paper_tasks': paper_tasks,
                         'keywords': keywords, 'sources': sources, 'label_source': 'model'})
        seen.add(row['cluster_id'])
    return accepted


def _history_topics(history: list | None) -> list[dict]:
    return [m['response']['map_answer'] for m in reversed(history or [])
            if isinstance(m, dict) and isinstance(m.get('response'), dict)
            and isinstance(m['response'].get('map_answer'), dict)
            and isinstance(m['response']['map_answer'].get('topics'), list)]


def _model_annotations(topics: list) -> list[dict]:
    rows = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        if topic.get('label_source') == 'model':
            rows.append(topic)
        elif topic.get('label_source') == 'human' and topic.get('generated_label_source') == 'model':
            rows.append({**topic, 'label': topic.get('generated_label'), 'label_source': 'model'})
    return rows


def _reuse_history_annotations(base: dict, history: list | None, papers: dict) -> dict | None:
    """Reuse copied model names only after checking the current exact map inputs."""
    for saved in _history_topics(history):
        if saved.get('map_version') != base['map_version']:
            continue
        rows = _model_annotations(saved['topics'])
        if not rows:
            continue
        try:
            accepted = _validate_annotations(base, rows, papers)
        except (ValueError, TypeError, KeyError):
            continue
        annotations = {t['cluster_id']: t for t in accepted}
        return {**base, 'topics': [annotations.get(t['cluster_id'], t) for t in base['topics']],
                'naming_status': 'model' if len(annotations) == len(base['topics']) else 'mixed',
                'generation': saved.get('generation', {}), 'created_at': saved.get('created_at'),
                'annotation_source': 'conversation_history'}
    return None


def _cached_map_topics(payload: dict, runs_dir: Path | None = None) -> dict:
    base = base_map_topics(payload)
    if runs_dir is None or not payload.get('run_id'):
        return base
    path = _cache_path(runs_dir, payload['run_id'], base['map_version'])
    cached = None
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(saved, dict) and saved.get('map_version') == base['map_version']:
            rows = _model_annotations(saved.get('topics', []))
            papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
            accepted = _validate_annotations(base, rows, papers)
            annotations = {t['cluster_id']: t for t in accepted}
            status = ('model' if len(accepted) == len(base['topics']) else 'mixed') if accepted else (
                'terms_after_error' if saved.get('naming_status') == 'terms_after_error' else 'terms')
            cached = {**base, 'topics': [annotations.get(t['cluster_id'], t) for t in base['topics']],
                      'naming_status': status,
                      'generation': saved.get('generation', {}), 'created_at': saved.get('created_at')}
            if accepted:
                return cached
    except (OSError, ValueError, TypeError, KeyError):
        pass
    # A research fork copies its conversation, but deliberately does not copy
    # the workspace-level sidecar cache. Reuse its validated annotations without
    # another model call or writing anything during a GET/payload read.
    try:
        from src.conversation import load_conversation
        history = load_conversation(runs_dir, payload['run_id']).get('messages', [])
    except (OSError, ValueError, TypeError, KeyError):
        history = []
    papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
    return _reuse_history_annotations(base, history, papers) or cached or base


def _manual_path(runs_dir: Path, run_id: str, version: str) -> Path:
    return _cache_path(runs_dir, run_id, version).with_suffix('.manual.json')


def _human_label(value) -> str:
    if not isinstance(value, str):
        raise ValueError('主题名称应为文本')
    label = _space(value)
    if not 1 <= len(label) <= 80:
        raise ValueError('主题名称应为1至80个字')
    return label


def _apply_manual_labels(topics: dict, runs_dir: Path | None) -> dict:
    if runs_dir is None or not topics.get('run_id'):
        return topics
    labels = {}
    # A copied research conversation can carry a historical human name, but it
    # applies only to exactly the same map version and member set.
    try:
        from src.conversation import load_conversation
        history = load_conversation(runs_dir, topics['run_id']).get('messages', [])
        for saved in _history_topics(history):
            if saved.get('map_version') != topics['map_version']:
                continue
            for row in saved['topics']:
                if isinstance(row, dict) and row.get('label_source') == 'human' and row.get('cluster_id') not in labels:
                    labels[row['cluster_id']] = {'label': row.get('label'), 'member_hash': _digest(row.get('paper_ids', [])),
                                                 'updated_at': row.get('label_updated_at', row.get('updated_at'))}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    path = _manual_path(runs_dir, topics['run_id'], topics['map_version'])
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            if (isinstance(saved, dict) and saved.get('run_id') == topics['run_id']
                    and saved.get('map_version') == topics['map_version'] and isinstance(saved.get('labels'), dict)):
                labels.update(saved['labels'])
        except (OSError, ValueError):
            pass
    rows, count = [], 0
    for topic in topics['topics']:
        row = labels.get(topic['cluster_id'])
        if isinstance(row, dict) and row.get('member_hash') == _digest(topic['paper_ids']):
            try:
                label = _human_label(row.get('label'))
            except ValueError:
                row = None
            if row and isinstance(row.get('updated_at'), str):
                generated_label = topic.get('generated_label', topic['label']) if topic.get('label_source') == 'human' else topic['label']
                generated_source = topic.get('generated_label_source', 'terms') if topic.get('label_source') == 'human' else topic['label_source']
                topic = {**topic, 'generated_label': generated_label, 'generated_label_source': generated_source,
                         'label': label, 'label_source': 'human',
                         'label_updated_at': row['updated_at'], 'updated_at': row['updated_at']}
                count += 1
        rows.append(topic)
    return {**topics, 'topics': rows, 'manual_label_count': count}


def map_topics(payload: dict, runs_dir: Path | None = None) -> dict:
    return _apply_manual_labels(_cached_map_topics(payload, runs_dir), runs_dir)


def save_topic_label(payload: dict, runs_dir: Path, *, cluster_id: str, map_version: str, label: str) -> dict:
    """Save a user topic name independently of generated names and run files."""
    current = map_topics(payload, runs_dir)
    if map_version != current['map_version']:
        raise ValueError('地图版本已更新，请在当前地图中修改主题名称')
    topic = next((t for t in current['topics'] if t['cluster_id'] == cluster_id), None)
    if topic is None:
        raise ValueError('所选主题簇不属于当前地图')
    name = _human_label(label)
    path = _manual_path(runs_dir, payload['run_id'], map_version)
    with _lock(path):
        saved = {'schema_version': SCHEMA_VERSION, 'run_id': payload['run_id'],
                 'map_version': map_version, 'labels': {}}
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(previous, dict) or previous.get('run_id') != payload['run_id']
                        or previous.get('map_version') != map_version or not isinstance(previous.get('labels'), dict)):
                    raise ValueError('invalid_manual_topic_labels')
                saved = previous
            except (ValueError, OSError) as exc:
                raise ValueError('人工主题标注文件损坏，请先恢复备份') from exc
        saved['labels'][cluster_id] = {'label': name, 'label_source': 'human',
                                      'updated_at': datetime.now(timezone.utc).isoformat(),
                                      'member_hash': _digest(topic['paper_ids'])}
        _write_cache(path, saved)
    updated = next(t for t in map_topics(payload, runs_dir)['topics'] if t['cluster_id'] == cluster_id)
    return {'run_id': payload['run_id'], 'map_version': map_version, 'topic': updated}


def merge_map_topics(payload: dict, runs_dir: Path | None = None) -> dict:
    topics = map_topics(payload, runs_dir)
    by_track = {t['track_id']: t for t in topics['topics'] if t.get('track_id')}
    graph = payload.get('map') or {}
    return {**graph, 'map_version': topics['map_version'], 'topic_naming_status': topics['naming_status'],
            'topics': topics['topics'], 'tracks': [{**track, **by_track.get(track.get('track_id'), {})}
                                                 for track in graph.get('tracks', [])]}


def _generate(settings, context: dict, feedback: str = '', *, deadline: float) -> dict:
    instructions = ('根据各簇的题名与摘要摘录，分别写中文共同方向和逐篇任务。'
                    'label 和 common_direction 只描述每篇成员的摘录或题名都能独立支持的最具体共同方向。'
                    '逐篇核对同一个共同方向是否成立，某项任务、应用、方法或结论只出现于部分论文时，将它移到对应论文的 paper_tasks。'
                    '优先概括共享的研究对象、问题类型或建模方向。只有每篇引文都明确提到同一个应用时，才把该应用写进共同方向和主题名。'
                    '只使用输入文字，不能凭你对论文的既有知识补全应用。例如一篇研究遥感图像中的建筑检测，另一篇研究通用图像目标检测，'
                    '共同方向是图像目标检测，遥感和建筑只归到第一篇。每条引用都须独立支持共同方向中的所有限定词。'
                    '共同方向只写一句，避免在共同方向中复述各篇的区别或推断任何结论。'
                    'common_sources 每篇成员给一条直接支持该共同方向的连续逐字短原文。'
                    '共同依据不足，或提供的 papers 少于 member_count 时，common_direction 填空字符串，common_sources 填空数组，label 填“相近论文”。'
                    'paper_tasks 为每篇给出的论文写一句具体研究任务，各自引用本篇能直接支持该任务的一条连续逐字短原文。'
                    '同一论文的任务和共同方向可以复用引文。引文尽量短，须足以支持对应描述。'
                    '只返回JSON {"topics":[{"cluster_id":"原编号","label":"短中文主题名",'
                    '"common_direction":"一句共同方向","keywords":["词语"],'
                    '"common_sources":[{"paper_id":"原编号","field":"title或abstract","quote":"逐字原文"}],'
                    '"paper_tasks":[{"paper_id":"原编号","task":"本篇研究任务",'
                    '"source":{"paper_id":"同一编号","field":"title或abstract","quote":"逐字原文"}}]}]}。'
                    '成员关系、论文数量与编号由系统固定。'
                    '不得增造论文、数字、实验结果，不使用不代表、不作、待补充等模板。')
    if feedback:
        instructions += '上一次结构检查反馈：' + feedback + '。请修正并重新给出全部主题。'
    body = {'model': settings.llm_model, 'temperature': 0.1, 'max_tokens': 5000,
            'response_format': {'type': 'json_object'}, 'messages': [
                {'role': 'system', 'content': instructions},
                {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}]}
    result = post_model_json(settings.llm_base_url.rstrip('/') + '/chat/completions',
                             settings.llm_api_key, body, deadline=deadline)
    content = result['choices'][0]['message']['content'].strip()
    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError('主题命名响应格式无效')
    return result


def refresh_map_topics(payload: dict, settings, *, force: bool = False) -> dict:
    from src.tasks import TaskCancelled, check_cancelled, report_progress

    if not isinstance(force, bool):
        raise ValueError('force应为布尔值')
    check_cancelled()
    base = map_topics(payload, settings.runs_dir)
    if not base['topics']:
        return {**base, 'refresh_status': 'empty', 'refresh_reason': 'no_topics'}
    if not force and base['naming_status'] == 'model':
        return {**base, 'refresh_status': 'cached'}
    if not getattr(settings, 'llm_api_key', None):
        return {**base, 'refresh_status': 'local', 'refresh_reason': 'unconfigured'}
    path = _cache_path(settings.runs_dir, payload['run_id'], base['map_version'])
    deadline = monotonic() + _TOPIC_REFRESH_SECONDS
    lock = _lock(path)
    while not lock.acquire(timeout=min(0.2, max(0.0, deadline - monotonic()))):
        check_cancelled()
        if monotonic() >= deadline:
            return {**map_topics(payload, settings.runs_dir), 'refresh_status': 'fallback', 'refresh_reason': 'timeout'}
    try:
        check_cancelled()
        base = map_topics(payload, settings.runs_dir)
        if not force and base['naming_status'] == 'model':
            return {**base, 'refresh_status': 'cached'}
        by_id = {topic['cluster_id']: topic for topic in _model_annotations(base['topics'])}
        papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
        selected = []
        remaining = MAX_PAPERS_PER_REQUEST
        for topic in base['topics']:
            if len(selected) == 12:
                break
            if not force and topic['cluster_id'] in by_id:
                continue
            count = min(topic['member_count'], MAX_TOPIC_PAPERS)
            if count > remaining:
                continue
            selected.append(topic)
            remaining -= count
        context = {'map_version': base['map_version'], 'topics': [
            {'cluster_id': t['cluster_id'], 'member_count': t['member_count'],
             'papers': [{'paper_id': pid, 'title': _space(papers[pid].get('title')),
                         'abstract': _space(papers[pid].get('abstract'))[:900]}
                        for pid in t['paper_ids'][:MAX_TOPIC_PAPERS]]} for t in selected]}
        accepted, feedback, calls, reason = [], '', 0, 'validation'
        for attempt in range(2):
            check_cancelled()
            if monotonic() >= deadline:
                reason = 'timeout'
                break
            report_progress('map_topics_retry' if attempt else 'map_topics_generate', run_id=payload['run_id'])
            calls += 1
            try:
                generated = _generate(settings, context, feedback=feedback, deadline=deadline)
                accepted = _validate_annotations(base, generated.get('topics'), papers)
                updated = {t['cluster_id']: t for t in accepted}
                if updated.keys() != {t['cluster_id'] for t in selected}:
                    raise ValueError('命名结果应覆盖本次提供的全部主题')
                annotations = by_id | updated
                if len({t['label'] for t in annotations.values()}) < len(annotations):
                    raise ValueError('不同主题应根据成员差异给出不同名称')
                break
            except TaskCancelled:
                raise
            except TimeoutError:
                reason = 'timeout'
                break
            except ValueError as exc:
                accepted = []
                feedback = str(exc)
            except Exception:
                reason = 'model_unavailable'
                break
        check_cancelled()
        if not accepted and by_id:
            return {**_apply_manual_labels(base, settings.runs_dir), 'refresh_status': 'fallback', 'refresh_reason': reason}
        by_id.update((topic['cluster_id'], topic) for topic in accepted)
        result = {**base, 'topics': [by_id.get(t['cluster_id'], t) for t in base['topics']],
                  'naming_status': 'model' if len(by_id) == len(base['topics']) else
                                   'mixed' if by_id else 'terms_after_error',
                  'generation': {'calls': calls, 'max_calls': 2, 'model': settings.llm_model,
                                 'status': 'completed' if accepted else 'terms',
                                 'diagnostic': reason if not accepted else ''},
                  'created_at': datetime.now(timezone.utc).isoformat()}
        _write_cache(path, result)
        visible = _apply_manual_labels(result, settings.runs_dir)
        if not accepted:
            return {**visible, 'refresh_status': 'fallback', 'refresh_reason': reason}
        return {**visible, 'refresh_status': 'generated' if result['naming_status'] == 'model' else 'partial'}
    finally:
        lock.release()


def _number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9}
    if value == '十':
        return 10
    if '十' in value:
        left, right = value.split('十', 1)
        if (left and left not in digits) or (right and right not in digits):
            return None
        return (digits.get(left, 1) * 10) + digits.get(right, 0)
    return digits.get(value)


def validate_map_context(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'map_version', 'cluster_ids', 'graph_id'}:
        raise ValueError('地图上下文格式无效')
    version, ids = value.get('map_version'), value.get('cluster_ids', [])
    if version is not None and (not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{64}', version)):
        raise ValueError('地图版本无效')
    if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(i, str) or not re.fullmatch(r'(?:topic-[a-f0-9]{20}|semantic-\d+)', i) for i in ids):
        raise ValueError('主题簇编号无效')
    graph = value.get('graph_id')
    if graph is not None and (not isinstance(graph, str) or len(graph) > 200):
        raise ValueError('地图标识无效')
    return {'map_version': version, 'cluster_ids': list(dict.fromkeys(ids)), 'graph_id': graph}


def _reading_focus(question: str) -> bool:
    return bool(re.search(r'方法|实验|数据集|样本|基线|指标|资源|算力|显存|训练|结果|适用|正文|全文|阅读|读|'
                          r'\b(?:method|experiment|dataset|baseline|metric|resource|read|full.?text)\w*\b', question, re.I))


def _explicit_papers(payload: dict | None, question: str) -> list[str]:
    if not payload:
        return []
    from src.reading_scope import _message_papers
    papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
    return _message_papers(question, papers)[0]


def is_map_question(question: str, history: list | None = None, context: dict | None = None,
                    payload: dict | None = None) -> bool:
    if re.search(r'重新检索|检索新|搜索新|找.*论文|查找.*论文|补充.*文献|search.*papers|find.*papers', question, re.I):
        return False
    explicit_papers = _explicit_papers(payload, question)
    if explicit_papers and (_reading_focus(question) or (
            re.search(r'比较|对比|区别|不同|为什么|原理|机制|解释', question)
            and not re.search(r'主题簇|图里|图中|图上|这些组|分组|聚类', question))):
        return False
    explicit = bool(re.search(r'主题簇|簇\s*\d|第\s*[一二两三四五六七八九十\d]+\s*(?:个)?\s*簇|'
                              r'研究地图|关系图|图谱|语义簇|\bclusters?\b|\bmap\b', question, re.I))
    explicit = explicit or bool(re.search(r'(?:图中|图里|图上).*(?:主题|颜色|分组|分别|论文)', question))
    explicit = explicit or bool(re.search(r'(?:当前|这|各个|所有).{0,4}聚类', question))
    if explicit:
        return True
    previous = next((m.get('response', {}).get('map_answer') for m in reversed(history or [])
                     if isinstance(m, dict) and isinstance(m.get('response'), dict) and m['response'].get('map_answer')), None)
    if not previous and not context:
        return False
    refers = bool(re.search(r'第二个|第[一二两三四五六七八九十\d]+个|这[一两]?(?:组|类|簇)|'
                           r'那[一两]?(?:组|类|簇)|它们|前一组|后一组|这些主题|这个主题|'
                           r'分别.*(?:主题|对应)|为什么.*一起|展开说|具体一点|详细解释', question))
    return refers or bool(context and re.search(r'主题|分组|成员|代表论文|共同|差异|区别|为什么', question))


def _topic_source(payload: dict, runs_dir: Path, history: list | None, context: dict | None):
    context = validate_map_context(context)
    current = map_topics(payload, runs_dir)
    snapshots = _history_topics(history)
    previous = snapshots[0] if snapshots else None
    requested_version = (context or {}).get('map_version')
    source = current
    if requested_version and requested_version != current['map_version']:
        historical = next((t for t in snapshots if t.get('map_version') == requested_version), None)
        if historical is not None:
            source = {**historical, 'run_id': payload['run_id']}
            previous = historical
        else:
            path = _cache_path(runs_dir, payload['run_id'], requested_version)
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(saved, dict) or saved.get('map_version') != requested_version
                        or saved.get('run_id') != payload['run_id'] or not isinstance(saved.get('topics'), list)):
                    raise ValueError('地图版本无效')
                source = saved
                previous = saved
            except (OSError, ValueError, TypeError):
                raise ValueError('这张地图已更新，请重新选择当前主题簇')
    elif current.get('naming_status') != 'model':
        papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
        reused = _reuse_history_annotations(current, history, papers)
        if reused:
            current = source = reused
    return current, source, previous, context


def _select_map_topics(source: dict, question: str, previous: dict | None, context: dict | None):
    topics = source.get('topics') or []
    by_id = {t['cluster_id']: t for t in topics}
    aliases = {t.get('track_id'): t['cluster_id'] for t in topics if t.get('track_id')}
    chosen = []
    number_pattern = r'(?:第\s*([一二两三四五六七八九十\d]+)\s*(?:个)?\s*(?:主题)?(?:簇|组|类)|(?:主题簇|簇|cluster)\s*([一二两三四五六七八九十\d]+))'
    explicit_numbers = []
    for match in re.finditer(number_pattern, question, re.I):
        number = _number(match.group(1) or match.group(2))
        explicit_numbers.append(number)
        chosen.extend(t['cluster_id'] for t in topics if t['display_index'] == number)
    if not chosen and previous:
        for match in re.finditer(r'第\s*([一二两三四五六七八九十\d]+)\s*个', question):
            number = _number(match.group(1))
            explicit_numbers.append(number)
            chosen.extend(t['cluster_id'] for t in topics if t['display_index'] == number)
    if any(number is None or not 1 <= number <= len(topics) for number in explicit_numbers):
        raise ValueError(f'当前地图共有 {len(topics)} 个主题簇，请选择对应编号')
    for topic in topics:
        if topic['cluster_id'] in question or (len(topic['label']) >= 4 and topic['label'] in question):
            chosen.append(topic['cluster_id'])
    all_groups = bool(re.search(r'分别|所有|各个|每个|有哪些主题|多少|全部', question))
    if not chosen and context and not all_groups:
        chosen = [aliases.get(cid, cid) for cid in context['cluster_ids']]
        if any(cid not in by_id for cid in chosen):
            raise ValueError('所选主题簇不属于这张地图')
    if not chosen and previous and not all_groups and re.search(r'这|那|它|刚才|上述|前面', question):
        chosen = [cid for cid in previous.get('selected_cluster_ids', []) if cid in by_id]
    chosen = list(dict.fromkeys(chosen))
    linked_reference = re.search(r'(?:它|这个|这组|这一组|这一簇|刚才).{0,12}(?:和|与|跟)|'
                                 r'(?:和|与|跟).{0,12}(?:它|这个|这组|这一组|这一簇|刚才)', question)
    if chosen and previous and linked_reference and re.search(r'比较|对比|差异|区别|不同', question):
        referenced = ([aliases.get(cid, cid) for cid in context.get('cluster_ids', [])] if context else [])
        referenced = referenced or previous.get('selected_cluster_ids', [])
        chosen = list(dict.fromkeys([cid for cid in referenced if cid in by_id] + chosen))
    selected = [by_id[cid] for cid in chosen] if chosen else topics
    return topics, selected, chosen


def resolve_cluster_reading_scope(payload: dict, question: str, runs_dir: Path, *,
                                  history: list | None = None, context: dict | None = None) -> dict | None:
    """Turn a paper/cluster reading request into a bounded existing-paper scope.

    Topic explanation and paper reading use different tools.  This adapter only
    selects existing papers; generation stays with the established grounded
    reading pipeline and its original-page/source checks.
    """
    if re.search(r'重新检索|检索新|搜索新|找.*论文|查找.*论文|补充.*文献', question):
        return None
    papers = {p['paper_id']: p for p in scoped_payload(payload).get('papers', [])}
    explicit = _explicit_papers(payload, question)
    focus = _reading_focus(question)
    if explicit and (focus or re.search(r'比较|对比|区别|不同|为什么|原理|机制|解释', question)):
        # A named paper always beats an old selected map cluster, but a question
        # explicitly about grouping keeps the map operation unless it asks for
        # methods, experiments or other paper content.
        if not focus and re.search(r'主题簇|图里|图中|图上|这些组|分组|聚类', question):
            return None
        ids = explicit[:4]
        return {'paper_ids': ids, 'titles': [papers[pid].get('title') or pid for pid in ids],
                'source': 'message', 'selection_limit': 4, 'ambiguous_name': False,
                'notice': '本轮按问题中提到的论文查找正文。'}
    if not focus:
        return None
    if re.search(r'主题名|名称|命名|叫什么|对应.*主题|哪些主题|如何划分|分组依据|为什么.*(?:一起|分组)', question):
        return None
    previous_map = next((m['response']['map_answer'] for m in reversed(history or [])
                         if isinstance(m, dict) and isinstance(m.get('response'), dict)
                         and m['response'].get('map_answer')), None)
    cluster_ref = bool(re.search(r'簇|这(?:一|两)?组|这些组|那(?:一|两)?组|这个主题|这些主题|第[一二两三四五六七八九十\d]+个', question))
    if not cluster_ref and not (context and context.get('cluster_ids')):
        return None
    if not previous_map and not context and not re.search(r'簇|这些组|这个主题|这些主题', question):
        return None
    _, source, previous, context = _topic_source(payload, runs_dir, history, context)
    _, selected, _ = _select_map_topics(source, question, previous, context)
    candidates = list(dict.fromkeys(
        [p['paper_id'] for topic in selected for p in topic.get('representative_papers', [])]
        + [pid for topic in selected for pid in topic['paper_ids']]))
    candidates = [pid for pid in candidates if pid in papers]
    if not candidates:
        raise ValueError('请在当前地图中选择要阅读的主题簇')
    parsed = {d.get('paper_id') for d in (payload.get('fulltext_audit') or {}).get('documents', [])
              if d.get('status') == 'parsed'}
    readable = [pid for pid in candidates if pid in parsed]
    amount = re.search(r'([一二两三四1234])\s*篇', question)
    limit = _number(amount.group(1)) if amount else (4 if re.search(r'比较|对比', question) else 2)
    ids = (readable or candidates)[:min(4, limit or 4)]
    return {'paper_ids': ids, 'titles': [papers[pid].get('title') or pid for pid in ids],
            'source': 'cluster_selection', 'cluster_ids': [t['cluster_id'] for t in selected],
            'map_version': source['map_version'], 'member_count': len(candidates),
            'available_fulltext_count': len(readable), 'selection_limit': min(4, limit or 4),
            'ambiguous_name': False,
            'notice': '本轮从所选主题簇中优先阅读已有全文的代表论文。'}


def map_chat_response(payload: dict, question: str, settings, *, history: list | None = None,
                      context: dict | None = None) -> dict:
    current, source, previous, context = _topic_source(payload, settings.runs_dir, history, context)
    if (source['map_version'] == current['map_version'] and current['topics']
            and current['naming_status'] == 'terms' and getattr(settings, 'llm_api_key', None)):
        source = refresh_map_topics(payload, settings)
    topics, selected, chosen = _select_map_topics(source, question, previous, context)
    kind = 'compare' if re.search(r'对比|比较|差异|区别|不同', question) else 'members' if re.search(r'哪些论文|成员|列出|论文列表', question) else 'cluster' if chosen else 'overview'
    rows = []
    if topics:
        if kind == 'overview':
            rows.append(f'当前 {source.get("paper_count", sum(t["member_count"] for t in topics))} 篇论文分成 {len(topics)} 个主题簇：')
        for t in selected:
            rows.append(f'**主题簇 {t["display_index"]}：{t["label"]}**')
            direction = t.get('common_direction')
            rows.append('**共同方向**\n\n' + direction if direction else '**分组依据**\n\n' + GROUPING_DESCRIPTION)
            tasks = {item['paper_id']: item['task'] for item in t.get('paper_tasks', [])}
            if kind in {'members', 'cluster'}:
                examples = t['papers']
            else:
                examples = [p for p in t['papers'] if p['paper_id'] in tasks] or t['representative_papers'][:2]
            if examples:
                rows.append('**各篇论文**\n\n' + '\n'.join(
                    f'- 《{p["title"]}》' + (f'（{p["year"]}）' if p.get('year') else '') +
                    (f'。{tasks[p["paper_id"]]}' if p['paper_id'] in tasks else '') for p in examples))
        if re.search(r'为什么|为何|依据|怎么分|如何分', question):
            rows.append('地图依据论文题名与摘要的语义近邻关系组织分组。共同方向综合各篇来源，具体任务列在对应论文下。')
    else:
        rows.append('当前地图包含 ' + str(len((payload.get('map') or {}).get('nodes', []))) + ' 篇论文。可以从论文题名与摘要开始查看研究方向。')
    answer = {**source, 'kind': kind, 'selected_cluster_ids': [t['cluster_id'] for t in selected],
              'context_source': 'historical_map' if source.get('map_version') != current['map_version'] else 'current_map'}
    save_topic_snapshot(answer, settings.runs_dir)
    # Persist the full topic table in each response to resolve ordinals and replay
    # old maps without relying on a client-supplied graph or on a mutable label.
    return {'overview': '\n\n'.join(rows), 'overview_mode': 'map_answer', 'map_answer': answer,
            'run_id': payload.get('run_id'), 'papers': [], 'map': {}, 'actions': [],
            'intent': {'kind': 'map_explain', 'route_source': 'map_context', 'needs_retrieval': False},
            'answer_audit': {'ok': True, 'kind': 'map_membership', 'citations': [], 'errors': [],
                             'map_version': answer['map_version']},
            'paper_selection': {'mode': 'map_context', 'retrieval_status': 'not_started',
                                'matched_count': 0, 'added_count': 0,
                                'total_run_count': len(scoped_payload(payload).get('papers', []))}}
