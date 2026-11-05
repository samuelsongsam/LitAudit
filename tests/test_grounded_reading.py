from types import SimpleNamespace

import pytest

from src.grounded_reading import grounded_answer, validate_sections, question_requirements
from src.tasks import TaskCancelled


@pytest.fixture
def reading_payload():
    return {"run_id": "r", "offline": False, "live": {"matched_paper_ids": ["p1"]},
            "papers": [{"paper_id": "p1", "title": "Controlled experiment"},
                       {"paper_id": "hidden", "title": "Other research"}],
            "fulltext_index": {"hits": [
                {"passage_id": "s1", "paper_id": "p1", "title": "Controlled experiment", "page": 3,
                 "text": "The experiment used 24 samples and compared a baseline model.",
                 "text_sha256": "current", "pdf_url": "/api/fulltext/r/p1#page=3"},
                {"passage_id": "secret", "paper_id": "hidden", "page": 1,
                 "text": "This text belongs to another research scope."}]}}


def section(text="论文报告实验使用24个样本。", quote="The experiment used 24 samples", kind="paper_report"):
    return {"kind": kind, "text": text, "sources": [{"passage_id": "s1", "quote": quote}]}


def test_grounded_chinese_reading_is_model_reviewed_not_human_verified(reading_payload, monkeypatch):
    calls = []
    def model(settings, system, content):
        calls.append(content)
        if len(calls) == 1:
            return {"sections": [section()]}
        return {"verdicts": [{"id": 0, "verdict": "supported", "reason": "样本量与原文一致"}]}
    monkeypatch.setattr("src.grounded_reading._call", model)
    text, audit = grounded_answer(reading_payload, "样本量是多少", SimpleNamespace())
    assert "24个样本" in text and "PDF第3页" in text
    assert audit["human_verified"] is False and audit["semantic_review"] == "model_supported"
    assert audit["citations"][0]["certainty"] == "model_reviewed_reading"
    assert len(calls[0]["passages"]) == 1 and calls[0]["passages"][0]["paper_id"] == "p1"


def test_unsupported_arabic_numbers_are_removed_before_model_review(reading_payload, monkeypatch):
    calls = []
    def model(*args):
        calls.append(1)
        return {"sections": [section("论文报告实验使用2400个样本。")]}
    monkeypatch.setattr("src.grounded_reading._call", model)
    text, audit = grounded_answer(reading_payload, "样本量是多少", SimpleNamespace())
    assert "2400" not in text and audit["kind"] == "evidence_only"
    assert any("unsupported_number" in e for e in audit["review_errors"])
    # One bounded repair is allowed, but unsupported draft numbers are never
    # sent to the semantic reviewer or silently displayed as supported.
    assert calls == [1, 1]
    assert audit['revision']['attempted'] is True


@pytest.mark.parametrize("text", ["该方法准确率提升九成。", "实验使用一百个样本。", "该方法比基线快十倍。"])
def test_unsourced_chinese_numeric_claims_are_rejected(reading_payload, text):
    accepted, errors = validate_sections(reading_payload, [section(text)])
    assert accepted == []
    assert any("unsupported_number" in e for e in errors)


def test_reported_percentage_cannot_be_rewritten_as_a_multiplier(reading_payload):
    reading_payload["fulltext_index"]["hits"][0]["text"] = "The method achieved 95% accuracy on the held-out dataset."
    item = section("该方法在留出数据上比基线提升95倍。", quote="The method achieved 95% accuracy")
    accepted, errors = validate_sections(reading_payload, [item])
    assert accepted == []
    assert errors == ["0:unsupported_number"]


@pytest.mark.parametrize(("original", "translation"), [
    ("24 samples were included in the experiment.", "论文报告纳入24个样本。"),
    ("Training required 2 hours on the reported hardware.", "论文报告训练耗时2小时。"),
    ("The process used 8 GB of memory in the experiment.", "论文报告实验占用8GB内存。"),
    ("24 samples were included in the experiment.", "论文报告纳入二十四个样本。"),
    ("Training required 2 hours on the reported hardware.", "论文报告训练耗时两小时。"),
    ("The accuracy reached 90% in the reported experiment.", "论文报告准确率达到九成。"),
    ("The accuracy reached 95% in the reported experiment.", "论文报告准确率达到百分之九十五。"),
    ("Training required 20.5 hours on the reported hardware.", "论文报告训练耗时二十点五小时。"),
])
def test_source_quantities_allow_equivalent_chinese_units(reading_payload, original, translation):
    reading_payload["fulltext_index"]["hits"][0]["text"] = original
    accepted, errors = validate_sections(reading_payload, [section(translation, quote=original)])
    assert len(accepted) == 1
    assert errors == []


def test_invalid_quote_or_hidden_scope_cannot_back_an_explanation(reading_payload):
    bad = section(quote="The experiment definitely proves the method is optimal")
    assert validate_sections(reading_payload, [bad])[0] == []
    hidden = section()
    hidden["sources"] = [{"passage_id": "secret", "quote": "This text belongs to another research scope."}]
    assert validate_sections(reading_payload, [hidden])[0] == []


def test_semantic_review_rejection_keeps_only_original_text(reading_payload, monkeypatch):
    answers = iter([{"sections": [section("这个方法可以用于所有研究任务。", kind="explanation")]},
                    {"verdicts": [{"id": 0, "verdict": "unsupported", "reason": "原文没有普遍适用性结论"}]}])
    monkeypatch.setattr("src.grounded_reading._call", lambda *args: next(answers))
    text, audit = grounded_answer(reading_payload, "能否使用", SimpleNamespace())
    assert "用于所有研究任务" not in text and "24 samples" in text
    assert audit["kind"] == "evidence_only" and audit["human_verified"] is False


def test_user_resource_numbers_only_allowed_in_suggestions(reading_payload):
    item = section("如果你只有8GB显存，请先核对实现配置。", kind="suggestion")
    assert validate_sections(reading_payload, [item], {"compute": "8GB显存"})[0]
    assert not validate_sections(reading_payload, [{**item, "kind": "paper_report"}], {"compute": "8GB显存"})[0]


def test_empty_evidence_never_calls_model(reading_payload, monkeypatch):
    reading_payload["fulltext_index"]["hits"] = []
    def fail(*args): raise AssertionError("No model call expected")
    monkeypatch.setattr("src.grounded_reading._call", fail)
    text, audit = grounded_answer(reading_payload, "question", SimpleNamespace())
    assert text == "" and audit["errors"] == ["no_fulltext"]


def test_cancellation_is_not_converted_into_a_successful_reading(reading_payload, monkeypatch):
    def cancel(*args): raise TaskCancelled("user requested cancellation")
    monkeypatch.setattr("src.grounded_reading._call", cancel)
    with pytest.raises(TaskCancelled):
        grounded_answer(reading_payload, "question", SimpleNamespace())


def test_model_timeout_keeps_only_original_passages(reading_payload, monkeypatch):
    def timeout(*args):
        raise TimeoutError("grounded_model_deadline")
    monkeypatch.setattr("src.grounded_reading._call", timeout)
    text, audit = grounded_answer(reading_payload, "样本规模是多少", SimpleNamespace())
    assert audit["kind"] == "evidence_only" and audit["model_status"] == "timed_out"
    assert "24 samples" in text and all(c["certainty"] == "fulltext_only" for c in audit["citations"])


def test_compound_research_question_has_explicit_subquestions():
    requirements = question_requirements("请解释论文的核心方法、数据集、比较基线和适用条件。")
    assert [q['facet'] for q in requirements] == ['method', 'data', 'baseline', 'conditions']
    assert len({q['id'] for q in requirements}) == 4
    assert question_requirements("这个方法的样本量是多少？")[0]['facet'] == 'sample_size'
    parts = question_requirements('为什么需要先中心化？SVD如何得到主成分？')
    assert len(parts) == 2 and all(p['facet'] == 'general' for p in parts)
    assert [p['id'] for p in parts] == ['q_part_1', 'q_part_2']


def test_centering_data_question_is_not_misclassified_as_dataset_request():
    requirements = question_requirements('PCA为什么先中心化数据？')
    assert len(requirements) == 1 and requirements[0]['facet'] == 'general'
    assert '中心化' in requirements[0]['query']


def test_time_series_method_is_not_misclassified_as_compute_budget():
    requirements = question_requirements('时间序列预测方法有哪些？')
    assert [q['facet'] for q in requirements] == ['method']
    assert [q['facet'] for q in question_requirements('这种方法需要多少训练时间？')] == ['method', 'resources']


def test_known_facet_does_not_drop_a_second_general_research_question():
    requirements = question_requirements('QLoRA用了哪些数据集？为什么NF4适合这些权重？')
    assert requirements[0]['facet'] == 'data' and len(requirements) == 2
    assert requirements[1]['facet'] == 'general' and '为什么NF4' in requirements[1]['query']
    compound = question_requirements('QLoRA的核心方法、数据集、比较基线和适用条件分别是什么？请给出原文依据。')
    assert [q['facet'] for q in compound] == ['method', 'data', 'baseline', 'conditions']


def test_compound_answer_discloses_missing_questions_even_when_one_section_passes(reading_payload, monkeypatch):
    answers = iter([
        {'sections': [{**section('论文的方法使用基线模型进行比较。'), 'question_ids': ['q_method']}]},
        {'verdicts': [{'id': 0, 'verdict': 'supported', 'reason': '这项方法说明有据'}],
         'coverage': [{'question_id': 'q_method', 'status': 'answered', 'section_ids': [0], 'reason': '方法要点已说明'}]},
    ])
    monkeypatch.setattr('src.grounded_reading._call', lambda *args: next(answers))
    text, audit = grounded_answer(reading_payload, '解释核心方法、数据集和适用条件', SimpleNamespace())
    statuses = {q['facet']: q['status'] for q in audit['question_coverage']}
    assert statuses == {'method': 'answered', 'data': 'insufficient_evidence', 'conditions': 'insufficient_evidence'}
    assert audit['kind'] == 'grounded_reading' and audit['answer_status'] == 'partial'
    assert audit['coverage_complete'] is False and len(audit['missing_questions']) == 2
    assert '论文的方法使用基线模型进行比较。' in text
    assert all(phrase not in text for phrase in
               ['数据集：当前依据不足', '适用条件：当前依据不足', '还需要补充', '答题覆盖', '尚未完成'])
    assert {q['facet'] for q in audit['missing_questions']} == {'data', 'conditions'}
    assert audit['human_verified'] is False
    assert audit['review_configuration'] == 'same_model_separate_call'


def test_rejected_section_cannot_make_a_subquestion_look_answered(reading_payload, monkeypatch):
    answers = iter([
        {'sections': [{**section('论文的方法使用一个基线模型。'), 'question_ids': ['q_method']},
                      {**section('论文数据来自所有国家。'), 'question_ids': ['q_data']}]},
        {'verdicts': [{'id': 0, 'verdict': 'supported'}, {'id': 1, 'verdict': 'unsupported'}],
         'coverage': [{'question_id': 'q_method', 'status': 'answered', 'section_ids': [0]},
                      {'question_id': 'q_data', 'status': 'answered', 'section_ids': [1]}]},
    ])
    monkeypatch.setattr('src.grounded_reading._call', lambda *args: next(answers))
    text, audit = grounded_answer(reading_payload, '核心方法和数据集是什么', SimpleNamespace())
    assert audit['question_coverage'][1]['status'] == 'insufficient_evidence'
    assert audit['rejected_section_count'] == 1 and audit['rejected_sections']
    assert '所有国家' not in text and '部分候选解读未通过检查' not in text
    assert any(d['stage'] == 'semantic_review' and d['code'] == 'semantic_review_unsupported'
               for d in audit['rejection_details'])
    assert audit['answer_status'] == 'partial' and audit['coverage_complete'] is False


def test_legacy_model_response_does_not_claim_complete_coverage(reading_payload, monkeypatch):
    answers = iter([{'sections': [section()]}, {'verdicts': [{'id': 0, 'verdict': 'supported'}]}])
    monkeypatch.setattr('src.grounded_reading._call', lambda *args: next(answers))
    text, audit = grounded_answer(reading_payload, '样本量是多少', SimpleNamespace())
    assert audit['coverage_complete'] is False and audit['question_coverage'][0]['status'] == 'partial'
    assert '24个样本' in text and 'PDF第3页' in text
    assert all(phrase not in text for phrase in ['尚未完成', '还需要补充', '当前依据不足'])
    assert audit['answer_status'] == 'partial' and audit['citations'][0]['passage_id'] == 's1'


@pytest.mark.parametrize('text', [
    '方法A准确率为95%，方法B准确率为85%。',
    'A方法达到95%，B方法达到85%。',
    'Method A achieved 95% accuracy while Method B achieved 85% accuracy.',
])
def test_named_subject_number_swap_rejected_before_semantic_review(reading_payload, text):
    original = 'Method A achieved 85% accuracy while Method B achieved 95% accuracy.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    accepted, errors = validate_sections(reading_payload, [section(text, quote=original)])
    assert accepted == [] and errors == ['0:numeric_subject_mismatch']


def test_correct_named_subject_numbers_accept_chinese_paraphrase(reading_payload):
    original = 'Method A achieved 85% accuracy while Method B achieved 95% accuracy.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    accepted, errors = validate_sections(reading_payload, [section('方法A准确率为85%，方法B准确率为95%。', quote=original)])
    assert errors == [] and len(accepted) == 1
    binding = accepted[0]['numeric_attribution']
    assert binding['status'] == 'checked_named_bindings' and len(binding['checked_bindings']) == 2


def test_unresolvable_numeric_subject_is_marked_for_review_not_called_verified(reading_payload):
    original = 'Method A achieved 85% accuracy while Method B achieved 95% accuracy.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    accepted, errors = validate_sections(reading_payload, [section('甲方法的准确率为85%。', quote=original)])
    assert not errors and accepted
    assert accepted[0]['numeric_attribution']['status'] == 'requires_model_review'


def test_multiple_experiments_with_same_name_do_not_claim_numeric_binding_is_complete(reading_payload):
    original = 'Method A achieved 85% accuracy on one dataset; Method A achieved 95% accuracy on another dataset.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    accepted, errors = validate_sections(reading_payload, [section('方法A准确率为85%。', quote=original)])
    assert not errors and accepted[0]['numeric_attribution']['status'] == 'requires_model_review'


def test_model_type_suffix_is_not_mistaken_for_an_unsourced_number(reading_payload):
    original = 'The computation data type is BFloat16 for this experiment.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    accepted, errors = validate_sections(reading_payload, [section('论文计算使用BFloat16类型。', quote=original)])
    assert not errors and accepted


def test_missing_evidence_has_explicit_unanswered_coverage(reading_payload):
    reading_payload['fulltext_index']['hits'] = []
    text, audit = grounded_answer(reading_payload, '数据集和比较基线是什么', SimpleNamespace())
    assert not text and audit['answer_status'] == 'insufficient_evidence'
    assert all(q['status'] == 'insufficient_evidence' for q in audit['question_coverage'])


def test_pdf_decimal_space_is_equivalent_without_joining_separate_sentence_numbers(reading_payload):
    original = 'The annotators reported Fleiss kappa = 0 .42 for the study.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    assert validate_sections(reading_payload, [section('论文报告标注一致性系数为0.42。', quote=original)])[0]
    separate = 'The first score was 0. 42 samples were used in the other experiment.'
    reading_payload['fulltext_index']['hits'][0]['text'] = separate
    assert not validate_sections(reading_payload, [section('论文报告分数为0.42。', quote=separate)])[0]


def test_single_repair_preserves_supported_section_and_rechecks_failed_claim(reading_payload, monkeypatch):
    original_good = {**section(), 'question_ids': ['q_sample_size']}
    original_bad = {**section('这个方法适用于所有任务。'), 'question_ids': ['q_conditions']}
    calls = []
    outputs = iter([
        {'sections': [original_good, original_bad]},
        {'verdicts': [{'id': 0, 'verdict': 'supported'}, {'id': 1, 'verdict': 'partial', 'reason': '原文没有普遍适用结论'}],
         'coverage': [{'question_id': 'q_sample_size', 'status': 'answered', 'section_ids': [0]},
                      {'question_id': 'q_conditions', 'status': 'answered', 'section_ids': [1]}]},
        {'sections': [{**section('原文报告与一个基线模型进行比较。', quote='and compared a baseline model.'),
                       'id': 1, 'question_ids': ['q_conditions']}]},
        {'verdicts': [{'id': 1, 'verdict': 'supported', 'reason': '修订只保留实际比较事实'}],
         'coverage': [{'question_id': 'q_conditions', 'status': 'partial', 'section_ids': [1],
                       'reason': '比较事实不足以给出完整适用范围'}]},
    ])
    def model(settings, system, content):
        calls.append(content)
        return next(outputs)
    monkeypatch.setattr('src.grounded_reading._call', model)
    text, audit = grounded_answer(reading_payload, '样本规模与适用条件是什么', SimpleNamespace())
    assert len(calls) == 4 and audit['kind'] == 'grounded_reading'
    assert audit['sections'][0]['text'] == original_good['text']
    assert calls[2]['already_supported_sections'][0]['text'] == original_good['text']
    assert '原文没有普遍适用结论' in calls[2]['failed_sections'][0]['feedback'][0]['reason']
    assert '适用于所有任务' not in text
    assert audit['revision']['accepted_sections'] == 1 and audit['revision']['max_attempts'] == 1
    assert audit['question_coverage'][1]['status'] == 'partial'
    assert audit['coverage_complete'] is False
    assert audit['rejection_details'][0]['resolved_by_revision'] is True
    assert len(audit['review_attempts']) == 2


def test_repair_does_not_relax_original_continuous_quote_requirement(reading_payload, monkeypatch):
    original = 'The experiment used 16- bit computation on the reported hardware.'
    reading_payload['fulltext_index']['hits'][0]['text'] = original
    outputs = iter([
        {'sections': [section('论文使用16-bit计算。', quote=original.replace('16- bit', '16-bit'))]},
        {'sections': [{**section('论文使用16-bit计算。', quote=original), 'id': 0}]},
        {'verdicts': [{'id': 0, 'verdict': 'supported'}],
         'coverage': [{'question_id': 'q_main', 'status': 'answered', 'section_ids': [0]}]},
    ])
    monkeypatch.setattr('src.grounded_reading._call', lambda *args: next(outputs))
    text, audit = grounded_answer(reading_payload, '这里采用多少位计算？', SimpleNamespace())
    assert audit['kind'] == 'grounded_reading' and audit['revision']['accepted_sections'] == 1
    assert audit['citations'][0]['quote'] == original
    assert audit['rejection_details'][0]['code'] == 'invalid_source_quote'


def test_repeated_partial_verdict_is_not_upgraded_after_one_repair(reading_payload, monkeypatch):
    calls = []
    outputs = iter([
        {'sections': [section('这个方法适用于所有任务。')]},
        {'verdicts': [{'id': 0, 'verdict': 'partial', 'reason': '缺少普遍适用依据'}]},
        {'sections': [{**section('这个方法仍然适用于所有任务。'), 'id': 0}]},
        {'verdicts': [{'id': 0, 'verdict': 'partial', 'reason': '修订仍超出原文'}]},
    ])
    def model(*args):
        calls.append(1)
        return next(outputs)
    monkeypatch.setattr('src.grounded_reading._call', model)
    text, audit = grounded_answer(reading_payload, '适用条件是什么', SimpleNamespace())
    assert len(calls) == 4 and audit['kind'] == 'evidence_only'
    assert '适用于所有任务' not in text and audit['revision']['accepted_sections'] == 0
    assert [d['reason'] for d in audit['rejection_details']] == ['缺少普遍适用依据', '修订仍超出原文']
    assert len(audit['review_attempts']) == 2 and not audit['coverage_complete']


def test_revision_error_never_discards_already_supported_content(reading_payload, monkeypatch):
    outputs = iter([
        {'sections': [section(), section('这个方法适用于所有任务。')]},
        {'verdicts': [{'id': 0, 'verdict': 'supported'}, {'id': 1, 'verdict': 'unsupported', 'reason': '无据'}]},
    ])
    def model(*args):
        try:
            return next(outputs)
        except StopIteration:
            raise TimeoutError('simulated service timeout')
    monkeypatch.setattr('src.grounded_reading._call', model)
    text, audit = grounded_answer(reading_payload, '样本规模和适用条件', SimpleNamespace())
    assert audit['kind'] == 'grounded_reading' and '24个样本' in text
    assert audit['revision']['status'] == 'failed'
    assert audit['revision']['error'] == 'TimeoutError'
    assert any(d['stage'] == 'revision' for d in audit['rejection_details'])


def test_revision_cannot_overwrite_an_already_approved_section(reading_payload, monkeypatch):
    outputs = iter([
        {'sections': [section(), section('这个方法适用于所有任务。')]},
        {'verdicts': [{'id': 0, 'verdict': 'supported'}, {'id': 1, 'verdict': 'unsupported', 'reason': '无据'}]},
        {'sections': [{**section('覆盖原先正确内容。'), 'id': 0}]},
    ])
    monkeypatch.setattr('src.grounded_reading._call', lambda *args: next(outputs))
    text, audit = grounded_answer(reading_payload, '样本规模和适用条件', SimpleNamespace())
    assert audit['kind'] == 'grounded_reading' and len(audit['sections']) == 1
    assert audit['sections'][0]['text'] == section()['text']
    assert '覆盖原先正确内容' not in text
    assert audit['revision']['status'] == 'no_valid_revision_returned'


def test_cancellation_during_revision_is_not_converted_into_a_partial_success(reading_payload, monkeypatch):
    outputs = iter([
        {'sections': [section(), section('这个方法适用于所有任务。')]},
        {'verdicts': [{'id': 0, 'verdict': 'supported'}, {'id': 1, 'verdict': 'unsupported', 'reason': '无据'}]},
    ])
    def model(*args):
        try:
            return next(outputs)
        except StopIteration:
            raise TaskCancelled('stop before revision')
    monkeypatch.setattr('src.grounded_reading._call', model)
    with pytest.raises(TaskCancelled):
        grounded_answer(reading_payload, '样本规模和适用条件', SimpleNamespace())


def test_explicit_reading_mode_reuses_current_paper_without_intent_router_or_retrieval(reading_payload, monkeypatch, tmp_path):
    """Exercise the HTTP handler directly, with model/source services isolated."""
    from copy import deepcopy
    from src.ui.server import LitAuditHandler

    settings = SimpleNamespace(runs_dir=tmp_path, llm_api_key="test-only")
    payload = deepcopy(reading_payload)
    payload["fulltext_audit"] = {"documents": [{"paper_id": "p1", "status": "parsed"}]}
    history = [{"role": "assistant", "content": "上一轮解读", "response": {
        "answer_audit": {"citations": [{"paper_id": "p1", "passage_id": "s1"}]}}}]
    monkeypatch.setattr("src.ui.server.load_settings", lambda **kwargs: settings)
    monkeypatch.setattr("src.ui.server.build_payload", lambda *args: payload)
    monkeypatch.setattr("src.ui.server.load_conversation", lambda *args: {"messages": history})
    def forbidden(*args, **kwargs):
        raise AssertionError("Explicit source reading must not route or retrieve a new topic")
    monkeypatch.setattr("src.ui.server.classify_intent", forbidden)
    monkeypatch.setattr("src.ui.server.run_pipeline", forbidden)
    recorded = []
    def answer(current, question, intent, current_settings):
        assert current["run_id"] == "r" and current["reading_mode"] == "grounded"
        assert intent.direct_answer and not intent.needs_retrieval
        assert intent.target_paper_id == "p1"
        return {"overview": "有依据的继续解读", "overview_mode": "llm_direct", "run_id": "r"}
    monkeypatch.setattr("src.ui.server.build_chat_response", answer)
    monkeypatch.setattr("src.ui.server.save_turn", lambda *args: recorded.append(args))
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler._attach_fulltext = lambda *args: None
    handler._save_research_context = lambda *args: None
    handler._json = lambda body, status=200: recorded.append((status, body))
    handler._chat({"run_id": "r", "message": "这会影响它的适用范围吗？", "reading_mode": True})
    assert recorded[-1][0] == 200
    assert recorded[-1][1]["action"] == "reuse_run"
    assert recorded[-1][1]["run_id"] == "r"


def test_explicit_reading_mode_cannot_borrow_another_runs_text(monkeypatch, tmp_path):
    from src.ui.server import LitAuditHandler
    settings = SimpleNamespace(runs_dir=tmp_path, llm_api_key="test-only")
    monkeypatch.setattr("src.ui.server.load_settings", lambda **kwargs: settings)
    monkeypatch.setattr("src.ui.server.build_payload", lambda *args: {
        "run_id": "empty-current", "papers": [], "fulltext_audit": {"documents": []}})
    monkeypatch.setattr("src.ui.server.load_conversation", lambda *args: {"messages": []})
    def forbidden(*args, **kwargs):
        raise AssertionError("No model, retrieval or previous-run fallback may run")
    for name in ["classify_intent", "run_pipeline", "build_chat_response"]:
        monkeypatch.setattr("src.ui.server." + name, forbidden)
    recorded = []
    handler = object.__new__(LitAuditHandler)
    handler.settings = settings
    handler._json = lambda body, status=200: recorded.append((status, body))
    handler._chat({"run_id": "empty-current", "message": "继续解释", "reading_mode": True,
                   "reading_paper_id": "paper-from-other-run"})
    assert recorded[0][0] == 400
    assert "当前研究的全文" in recorded[0][1]["error"]
