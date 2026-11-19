from src.agenda_fallback import local_research_questions


def _entry(pid, text, *, page=None, title='Robot manipulation', hint=None):
    entry = {'paper_id': pid, 'title': title, 'text': text, 'source_kind': 'abstract' if page is None else 'fulltext'}
    if page is not None:
        entry.update(page=page, passage_id=f'{pid}-passage', pdf_url=f'/api/fulltext/test/{pid}#page={page}')
    if hint:
        entry['quote_hint'] = hint
    return entry


def test_local_questions_use_real_source_factors_and_explicit_controls():
    entries = {
        'visual': _entry('a', 'The robot uses a visual-feedback program during the elevator-button task. The study records mean completion time.', page=2),
        'touch': _entry('b', 'The Insert Hole comparison studies tactile feedback after obstruction.', page=9),
        'budget': _entry('c', 'A larger execution budget permits additional recovery actions for robot manipulation.', page=3),
        'simulation': _entry('a', 'The simulation and hardware studies therefore examine both what transfers: body descriptions and approach references.', page=5),
        'paired': _entry('d', 'We introduce a paired Sim-Real benchmark with common tasks and success criteria.'),
    }
    result = local_research_questions(entries, '机器人操作、感知反馈与仿真迁移')
    assert len(result) == 3
    feedback, transfer, budget = result
    assert '触觉反馈' in feedback['question'] and '恢复率' in feedback['design']['metrics']
    assert '初始偏差' in feedback['design']['control']
    assert '仿真经验' in transfer['question'] and '实体' in transfer['design']['comparison']
    assert '执行预算' in budget['question'] and '耗时' in budget['question']
    assert {source['paper_id'] for source in feedback['sources']} == {'a', 'b'}
    assert any('插孔任务' in source['attribution'] for source in feedback['sources'])
    for question in result:
        assert question['scope'] == 'cross_paper' and question['origin'] == 'local'
        for source in question['sources']:
            assert any(source['paper_id'] == e['paper_id'] and source['quote'] in e['text'] for e in entries.values())
            assert 'text' not in source
    abstract = transfer['sources'][1]
    assert abstract['source_kind'] == 'abstract' and 'page' not in abstract and 'pdf_url' not in abstract


def test_title_only_or_unrelated_visual_feedback_does_not_create_robot_comparison():
    entries = {
        'a': _entry('a', 'The classroom assessment provides visual feedback to learners.', title='Education assessment'),
        'b': _entry('b', 'A robot receives tactile feedback.', title='Robot sensing'),
        'title': {'paper_id':'c', 'title':'Robot manipulation', 'source_kind':'title', 'text':'Visual feedback after obstruction'},
    }
    assert local_research_questions(entries, '') == []


def test_normalizes_quote_hint_only_to_match_stored_evidence():
    first = 'A larger execution budget enables more trials.'
    second = 'The key controlled factor is the execution budget.'
    entries = {
        'a': _entry('a', first + ' ' + second, page=3, hint='The key controlled factor is\nthe execution budget.'),
        'b': _entry('b', 'The protocol records task completion time.', page=5),
    }
    [question] = local_research_questions(entries, '')
    assert question['sources'][0]['quote'] == second
