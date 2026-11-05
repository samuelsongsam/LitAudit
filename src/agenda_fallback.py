"""Construct bounded experimental questions from observable literature cues."""
from __future__ import annotations

import re
from itertools import product
from typing import NamedTuple


class _Axis(NamedTuple):
    family: str
    cues: tuple[tuple[str, str], tuple[str, str]]
    question: str
    comparison: str
    control: str
    metrics: str
    rationale: str


_AXES = (
    _Axis('feedback', (
        ('视觉反馈', r'\bvisual[-\s]+feedback\b|\bvision[-\s]+only\b|视觉反馈|仅视觉'),
        ('触觉反馈', r'\btactile[-\s]+feedback\b|\bcontact[-\s]+feedback\b|触觉反馈|接触反馈'),
    ), '同一接触操作任务中，增加触觉反馈能否加快受阻后的恢复？',
          '设置视觉反馈组与视觉加触觉反馈组，逐次记录受阻后的动作与恢复结果。',
          '使用同一机器人、接触任务、初始偏差、控制接口和动作预算。',
          '受阻识别时间、受阻后的恢复率和最终任务成功率。',
          '把新增的触觉通道单独作为变量，可以区分更早察觉受阻与受阻后更容易纠正这两种收益。'),
    _Axis('feedback', (
        ('触觉反馈', r'\btactile[-\s]+feedback\b|\bcontact[-\s]+feedback\b|触觉反馈|接触反馈'),
        ('受阻与恢复', r'\bobstruction\b|\bfailure[-\s]+recovery\b|\bafter[-\s]+obstruction\b|受阻|失败恢复'),
    ), '触觉反馈的收益主要来自更早识别受阻，还是受阻后更容易恢复？',
          '对照有触觉与关闭触觉的执行记录，把每次受阻分为识别、调整和恢复三个阶段。',
          '固定机器人、物体、初始偏差、其他传感输入与动作预算。',
          '受阻识别时间、已识别受阻事件的恢复率和最终任务成功率。',
          '按阶段标记受阻过程，可以检验触觉信息在识别、调整或恢复的哪一步最有作用。'),
    _Axis('transfer', (
        ('仿真到实体的复用材料', r'\bsim(?:ulation|ulated)[-\s]+(?:XML[-\s]+)?(?:experience|assets|records)\b|\bsim2real[-\s]+reuse\b|\bsimulation and hardware studies[^.]{0,110}\btransfers\b|仿真经验|仿真资产'),
        ('配对的仿真与实体评测', r'\bpaired[-\s]+sim[-–—\s]+real\b|\bmatched[-\s]+simulated and real\b|\bshared task definitions and success criteria\b|仿真与真实.*配对|配对.*仿真'),
    ), '同一任务迁移到实体机器人后，复用仿真经验是否仍有效？',
          '在成对的仿真与实体任务中，分别对照提供仿真经验和从零执行，估计两种环境中的复用收益。',
          '对齐机器人接口、任务定义、起始姿态、成功标准与执行预算；分开报告各环境。',
          '各环境的成功率差、完成时间差，以及由仿真到实体时复用收益的变化。',
          '先算各环境中复用组相对从零执行组的差值，可以把环境本身的难度与经验的迁移收益分开。'),
    _Axis('transfer', (
        ('仿真评测', r'\bsimulat(?:ion|ed|or)\b|\bsim[-–—]real\b|仿真'),
        ('实体环境评测', r'\b(?:physical|real[-\s]+world|real)[-\s]+robots?\b|\bphysical[-\s]+(?:deployment|environment|task)\b|实体机器人|真实机器人'),
    ), '同一控制策略相对固定基线的表现，在仿真与实体机器人上有多大差距？',
          '对同一任务进行仿真和实体配对试验，在两种环境中分别运行同一策略和固定基线。',
          '统一机器人控制接口、起始条件、动作预算与成功判定。',
          '两种环境各自的成功率差、完成时间差，以及相对基线的跨环境变化。',
          '用同一基线作参照，能区分机器人转到实体环境后的普遍难度变化和特定策略的性能变化。'),
    _Axis('budget', (
        ('执行或推理预算', r'\bcontrol[-\s]+step[-\s]+limit\b|\b(?:action|execution)[-\s]+budget\b|\btoken[-\s]+(?:usage|costs?|budget)\b|\bmodel[-\s]+calls?\b|控制步数|动作预算|令牌(?:成本|预算|消耗)|模型调用'),
        ('完成耗时', r'\b(?:completion|execution|inference)[-\s]+time\b|\bwall[-\s]+clock\b|\blatency\b|完成时间|执行耗时|推理耗时|延迟'),
    ), '增加执行预算后，任务成功率和耗时各怎样变化？',
          '给同一策略设置两档以上的执行预算，逐档记录实际动作步数、模型消耗和任务结果。',
          '固定模型、动作接口、任务难度和成功标准；用同一计时口径，单列环境执行耗时。',
          '成功率、端到端完成时间、实际动作步数和模型消耗。',
          '把成功率与实际耗时放到同一预算曲线上，可以找到继续增加预算是否划算的区间。'),
    _Axis('starting_state', (
        ('演示或经验复用', r'\bexperience[-\s]+reuse\b|\bsynchronized[-\s]+(?:action|demonstration)\b|\bexperience[-\s]+recorded\b|\btraining[-\s]+set[-\s]+demonstrations\b|经验复用|同步演示|训练集演示'),
        ('起点变化或分布外验证', r'\bdisplaced[-\s]+start\b|\bnew[-\s]+starting[-\s]+positions?\b|\bunseen[-\s]+initial\b|\bbeyond[-\s]+(?:the[-\s]+)?demonstrat\w*|起点偏移|初始位置变化|演示任务之外'),
    ), '起始条件离演示越远，复用经验的收益是否越小？',
          '按起点偏移分档，分别运行复用原始演示与无经验基线，记录每一档内的差值。',
          '保持同一机器人、任务、演示来源、成功判定和动作预算。',
          '各偏移档的成功率、完成时间与复用收益。',
          '各偏移档都设置无经验对照，能检验起点变化影响的是任务本身的难度，还是经验复用的效果。'),
    _Axis('validation', (
        ('内部验证', r'\bcross[-\s]+validation\b|\binternal[-\s]+validation\b|交叉验证|内部验证'),
        ('独立外部数据', r'\bexternal[-\s]+validation\b|\bexternal[-\s]+cohort\b|\bheld[-\s]+out[-\s]+(?:test set|site|cohort)\b|外部验证|外部队列|留出(?:测试集|机构|队列)'),
    ), '同一方法在内部验证和独立外部数据上的表现差距有多大？',
          '固定开发集和训练流程，在内部划分与外部数据分别评估同一模型和同一基线。',
          '统一纳入条件、标签定义、预处理及评价指标；外部数据保持隔离。',
          '主评价指标与置信区间，以及相对同一基线的外部性能变化。',
          '比较同一模型和基线在内外部的差值，可以检查原先的相对优势是否依赖数据来源。'),
)
_ROBOTICS = re.compile(r'\brobots?\b|\brobotic\b|\bembodied\b|\bgripper\b|\bmanipulation\b|\blearned control\b|机器人|具身|夹爪|操作任务', re.I)
_TASK_CONTEXTS = (
    ('插孔任务', r'\binsert[-\s]+hole\b|插孔'),
    ('电梯按钮任务', r'\belevator[-\s]+button\b|电梯按钮'),
    ('固定起点试验', r'\bfixed[-\s]+start\b|固定起点'),
)


def _cue_quote(text: str, match: re.Match) -> str:
    """Find a continuous original excerpt containing the matched cue."""
    boundaries = [0, *(m.end() for m in re.finditer(r'(?<=[。！？])|(?<=[.!?])\s+(?=[A-Z])', text)), len(text)]
    start = max(offset for offset in boundaries if offset <= match.start())
    end = min(offset for offset in boundaries if offset >= match.end())
    if end - start > 340:
        start, end = max(start, match.start() - 90), min(end, match.end() + 180)
    return text[start:end].strip()


def _find_cue(evidence: list[dict], pattern: str) -> list[tuple[dict, str]]:
    candidates = []
    for entry in evidence:
        text = entry.get('text') or ''
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        hint = ' '.join((entry.get('quote_hint') or '').split())
        quote = hint if 8 <= len(hint) <= 340 and hint in text and re.search(pattern, hint, re.I) else _cue_quote(text, match)
        if len(quote) >= 8:
            candidates.append((entry, quote))
    return candidates


def _bound(cue: tuple[dict, str], label: str) -> dict:
    entry, quote = cue
    source = {key: value for key, value in entry.items() if key not in {'text', 'quote_hint'}}
    kind = entry['source_kind']
    position = f'正文第 {entry["page"]} 页' if kind == 'fulltext' else '摘要'
    task = next((name for name, pattern in _TASK_CONTEXTS if re.search(pattern, quote, re.I)), '')
    observation = f'{task}中的{label}' if task else label
    return {**source, 'quote': quote, 'certainty': 'fulltext_only' if kind == 'fulltext' else 'abstract_only',
            'attribution': f'{position}涉及{observation}。'}


def local_research_questions(evidence: dict, study_question: str, *, limit: int = 4) -> list[dict]:
    """Use original mentions to choose concrete hypotheses and controls for new tests."""
    from src.retrieval_rank import lexical_score

    entries = [entry for entry in evidence.values() if entry.get('source_kind') in {'fulltext', 'abstract'}]
    entries.sort(key=lambda entry: (entry['source_kind'] != 'fulltext',
                                   -lexical_score(study_question, entry.get('title') or '')))
    robotics = [entry for entry in entries if _ROBOTICS.search(f"{entry.get('title') or ''} {entry.get('text') or ''}")]
    questions, used_families = [], set()
    for axis in _AXES:
        if len(questions) >= limit:
            break
        if axis.family in used_families:
            continue
        (left_label, left_pattern), (right_label, right_pattern) = axis.cues
        relevant = entries if axis.family == 'validation' else robotics
        pairs = product(_find_cue(relevant, left_pattern), _find_cue(relevant, right_pattern))
        pair = min(pairs, key=lambda pair: (pair[0][0]['paper_id'] == pair[1][0]['paper_id'],
                                           sum(cue[0]['source_kind'] != 'fulltext' for cue in pair)), default=None)
        if pair is None:
            continue
        sources = [_bound(cue, label) for cue, label in zip(pair, (left_label, right_label))]
        cross_paper = sources[0]['paper_id'] != sources[1]['paper_id']
        if all(sources[0].get(k) == sources[1].get(k) for k in ('paper_id', 'page', 'source_kind', 'quote')):
            sources = [{**sources[0], 'attribution': f'同一摘录涉及{left_label}与{right_label}。'}]
        observed = f'两篇论文分别涉及{left_label}和{right_label}。' if cross_paper else f'这篇论文的材料涉及{left_label}和{right_label}。'
        questions.append({'question': axis.question, 'motivation': observed + axis.rationale,
                          'analysis_plan': ' '.join((axis.comparison, axis.control, axis.metrics)),
                          'design': {'comparison': axis.comparison, 'control': axis.control, 'metrics': axis.metrics},
                          'scope': 'cross_paper' if cross_paper else 'single_paper', 'origin': 'local', 'sources': sources})
        used_families.add(axis.family)
    return questions
