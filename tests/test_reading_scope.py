import pytest

from src.reading_scope import is_research_agenda_question, resolve_reading_scope


def test_agenda_outside_reading_mode_requires_a_reference_to_the_saved_literature():
    assert is_research_agenda_question('依据这些文献，有哪些问题值得分析？', scoped_reading=False)
    assert is_research_agenda_question('Based on these papers, what questions are worth investigating?', scoped_reading=False)
    assert not is_research_agenda_question('为城市洪水预警提出三个研究问题', scoped_reading=False)


@pytest.fixture
def payload():
    return {'offline': False, 'live': {'matched_paper_ids': ['paper-001', 'paper-002', 'paper-003', 'paper-004']},
            'papers': [
                {'paper_id': 'paper-001', 'title': 'QLoRA: Efficient Finetuning of Quantized LLMs'},
                {'paper_id': 'paper-002', 'title': 'LoRA: Low-Rank Adaptation of Large Language Models'},
                {'paper_id': 'paper-003', 'title': 'U-Net: Convolutional Networks for Biomedical Image Segmentation'},
                {'paper_id': 'paper-004', 'title': 'Attention U-Net: Learning Where to Look'},
                {'paper_id': 'paper-999', 'title': 'Unrelated old baseline'}]}


def history():
    return [{'role': 'assistant', 'response': {'answer_audit': {'citations': [{'paper_id': 'paper-001'}]}}}]


def test_new_explicit_paper_overrides_previous_and_stale_selector(payload):
    result = resolve_reading_scope(payload, 'LoRA论文的实验是什么？', selected='paper-001', history=history())
    assert result['paper_ids'] == ['paper-002'] and result['source'] == 'message'


def test_compare_two_names_is_not_locked_to_previous_paper(payload):
    assert resolve_reading_scope(payload, '比较LoRA与QLoRA的数据', history=history())['paper_ids'] == ['paper-002', 'paper-001']


def test_longer_method_name_does_not_accidentally_select_shorter_name(payload):
    assert resolve_reading_scope(payload, 'Attention U-Net的方法', history=history())['paper_ids'] == ['paper-004']
    assert set(resolve_reading_scope(payload, '比较Attention U-Net与U-Net')['paper_ids']) == {'paper-003', 'paper-004'}


def test_history_only_used_for_explicit_reference_and_never_hidden_scope(payload):
    assert resolve_reading_scope(payload, '刚才这篇的基线呢？', history=history())['paper_ids'] == ['paper-001']
    assert len(resolve_reading_scope(payload, '实验设置是什么？', history=history())['paper_ids']) == 4
    assert len(resolve_reading_scope(payload, '刚才这篇', all_papers=True, history=history())['paper_ids']) == 4
    with pytest.raises(ValueError):
        resolve_reading_scope(payload, 'paper-999 的方法')
    with pytest.raises(ValueError):
        resolve_reading_scope(payload, '方法', selected='paper-999')


def test_regular_selector_and_multi_paper_selection(payload):
    assert resolve_reading_scope(payload, '方法', selected=['paper-002', 'paper-003'])['paper_ids'] == ['paper-002', 'paper-003']


@pytest.mark.parametrize('question', [
    '依据这些文献，有哪些问题值得分析？',
    '这组论文有哪些值得进一步研究的方向？',
    '可以从哪些角度分析这些文献？',
    '基于这些论文，提出三个可检验的研究问题。',
    '接下来应优先验证哪些假设？',
    'Based on these papers, what questions are worth analysing?',
    'What should we investigate next?',
    'Suggest three testable hypotheses based on these studies.',
])
def test_research_agenda_questions_ask_for_directions_to_investigate(question):
    assert is_research_agenda_question(question)


@pytest.mark.parametrize('question', [
    '这篇有哪些问题和局限？',
    '这些论文的研究问题与方法分别是什么？',
    '这篇论文的研究问题是什么？',
    '作者提出了哪些研究问题？',
    '请给出这篇论文的研究问题。',
    '作者报告了哪些实验结果？',
    '比较这些论文的实验和基线。',
    'What are the limitations of this paper?',
    'What research questions do these papers address?',
    'Did the authors propose research questions?',
    'List the research questions addressed by these papers.',
])
def test_paper_facts_and_limitations_are_not_research_agendas(question):
    assert not is_research_agenda_question(question)


def test_research_agenda_detection_does_not_expand_selected_scope(payload):
    question = '有哪些问题值得分析？'
    assert is_research_agenda_question(question)
    assert resolve_reading_scope(payload, question, selected='paper-003')['paper_ids'] == ['paper-003']
