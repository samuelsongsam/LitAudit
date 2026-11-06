from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from src.io_utils import write_json, write_jsonl
from src.paper_library import citation_metadata, export_library, library_payload, save_library_item
from src.research_assistant import _duration_hours, _duration_analysis, _memory_analysis, _memory_comparison, research_guidance
from src.research_workspace import FIELDS, method_comparison, save_review


@pytest.fixture
def structured_research(tmp_path):
    """Synthetic, clearly labelled unit-test paragraphs in three new domains."""
    runs = tmp_path / "runs"
    run = runs / "new-domains"
    out = run / "output"
    out.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": "new-domains", "offline": True})
    write_json(out / "search_queries.json", [])
    papers, documents = [], []
    for index, topic in enumerate(["crop irrigation", "solar forecasting", "edge sensor learning"], 1):
        pid = f"p{index}"
        papers.append({"paper_id": pid, "title": "Synthetic test " + topic,
                       "authors": ["Test Author"], "year": 2024, "venue": "Unit-test corpus",
                       "doi_or_arxiv": f"doi:10.1234/test_{index}", "url": f"https://example.org/p{index}",
                       "source": "unit-test", "retrieved_at": "2026-11-04", "dedup_key": pid,
                       "decision": "include", "reason": "synthetic workflow verification"})
        body = (f"Methods\nThe research objective is to evaluate {topic}. "
                "Our method combines a lightweight encoder with a calibration procedure. "
                "The dataset contains 240 participants collected at three sites. "
                "The experimental setup uses five-fold cross-validation and a held-out test set. "
                "The baseline is a linear model trained with the same inputs. "
                "The evaluation metrics are accuracy and recall. "
                "The method achieved accuracy of 0.83 in the held-out experiment. "
                "The experiment uses one GPU with 8 GB memory and takes two hours. "
                "The applicability is restricted to the tested sites and assumes consistent labels.")
        cache = run / "cache" / pid
        cache.mkdir(parents=True)
        write_json(cache / "pages.json", [{"page": 1, "text": "Introduction\nSynthetic test material."},
                                           {"page": 2, "text": body}])
        documents.append({"paper_id": pid, "status": "parsed", "text_path": f"cache/{pid}/pages.json"})
    write_jsonl(out / "papers.jsonl", papers)
    write_jsonl(out / "paper_cards.jsonl", papers)
    write_json(out / "fulltext_audit.json", {"documents": documents})
    return runs, run


def test_ten_method_fields_are_extractive_and_located(structured_research):
    runs, _ = structured_research
    result = method_comparison(runs, "new-domains")
    assert len(FIELDS) == 10
    assert len(result["papers"]) == 3
    for paper in result["papers"]:
        assert len(paper["fields"]) == 10
        assert paper["fields"]["sample_size"]["candidate"]["value"] == "240 participants"
        quotes = []
        for field in paper["fields"].values():
            candidate = field["candidate"]
            assert candidate["page"] == 2
            assert candidate["quote"] in candidate["text"]
            assert candidate["text"][candidate["quote_start"]:candidate["quote_end"]] == candidate["quote"]
            assert candidate["value_kind"] == "extractive"
            assert candidate["extraction_source"] == "rule_sentence"
            assert field["status"] == "pending"
            quotes.append(candidate["quote"])
        assert len(set(quotes)) >= 7  # fields are not all the same paragraph.


def test_paper_panel_method_preset_uses_local_excerpts_and_saves_the_turn(structured_research, monkeypatch):
    from types import SimpleNamespace
    from src.conversation import load_conversation
    from src.ui.server import LitAuditHandler

    runs, _ = structured_research
    monkeypatch.setattr("src.ui.server.load_settings", lambda **_: SimpleNamespace(runs_dir=runs))
    monkeypatch.setattr("src.ui.server.build_payload", lambda *args: pytest.fail("Preset must not build chat payload"))
    monkeypatch.setattr("src.ui.server.classify_intent", lambda *args: pytest.fail("Preset must not call model router"))
    request = {"message": "分析方法与实验", "run_id": "new-domains", "reading_paper_id": "p2",
               "reading_mode": True, "analysis_preset": "methods_experiments"}
    handler = LitAuditHandler.__new__(LitAuditHandler)
    result = {}
    handler._json = lambda body, status=200: result.update(body=body, status=status)
    handler._chat(request)

    assert result["status"] == 200 and result["body"]["status"] == "completed"
    response = result["body"]["response"]
    assert response["overview_mode"] == "method_evidence"
    assert response["reading_scope"]["paper_ids"] == ["p2"]
    analysis = response["method_analysis"]
    assert analysis["paper_id"] == "p2" and analysis["mode"] == "extractive"
    assert "solar forecasting" in response["overview"] and "crop irrigation" not in response["overview"]
    assert len(analysis["fields"]) == 7
    for field in analysis["fields"]:
        candidate = field["candidate"]
        assert candidate["page"] == 2 and candidate["quote"] in candidate["text"]
        assert candidate["paper_id"] == "p2" and candidate["pdf_url"] == "/api/fulltext/new-domains/p2#page=2"
    assert load_conversation(runs, "new-domains")["messages"][-1]["response"] == response
    assert LitAuditHandler._retry_descriptor("/api/chat", request)["body"]["analysis_preset"] == "methods_experiments"


def test_dataset_size_is_not_batch_size_and_generic_resource_prose_is_not_hardware(structured_research):
    runs, run = structured_research
    write_json(run / "cache/p1/pages.json", [{"page": 1, "text": (
        "Methods\nGradient updates use small batch sizes of 2 to 4 samples. "
        "The dataset consists of 150 abdominal 3D CT scans acquired from patients. "
        "Networks are commonly used because they make efficient use of GPU memory. "
        "We use NVIDIA Tesla V100 for all experiments. "
        "We use a sequence length of 128 to match the baseline. "
        "The reader is assumed to know linear algebra. "
        "He assumes that another person has not seen an object."
    )}])
    paper = method_comparison(runs, "new-domains", ["p1"])["papers"][0]
    assert paper["fields"]["sample_size"]["candidate"]["value"] == "150 abdominal 3D CT scans"
    assert "Tesla V100" in paper["fields"]["resources"]["candidate"]["value"]
    assert "sequence length of 128" in paper["fields"]["experiment"]["candidate"]["quote"]
    assert paper["fields"]["conditions"]["candidate"] is None


def test_pdf_figure_labels_and_hyphenated_adjectives_do_not_create_study_fields(structured_research):
    runs, run = structured_research
    write_json(run / "cache/p1/pages.json", [{"page": 1, "text": (
        "Discussion\nFIG. 6 Example of when a method fails. "
        "For a sym-\nmetric matrix, eigenvectors define an orthogonal basis. "
        "Let X be the original data set, where each column is a sample. "
        "Another method is difficult to compute. "
        "The goal of the tutorial is to educate."
    )}])
    fields = method_comparison(runs, "new-domains", ["p1"])["papers"][0]["fields"]
    for key in ["sample_size", "metrics", "data", "resources"]:
        assert fields[key]["candidate"] is None, key


def test_chinese_conditions_do_not_require_english_word_spacing(structured_research):
    runs, run = structured_research
    original = "该方法仅适用于标注体系一致的数据，并假设每个样本的特征顺序固定。"
    write_json(run / "cache/p1/pages.json", [{"page": 1, "text": "方法\n" + original}])
    candidate = method_comparison(runs, "new-domains", ["p1"])["papers"][0]["fields"]["conditions"]["candidate"]
    assert original in candidate["quote"]
    assert candidate["quote"] in candidate["text"]


def test_human_value_edit_is_distinct_from_exact_evidence(structured_research):
    runs, _ = structured_research
    candidate = method_comparison(runs, "new-domains", ["p1"])["papers"][0]["fields"]["method"]["candidate"]
    request = {"passage_id": candidate["passage_id"], "field": "method", "status": "accepted",
               "quote": candidate["quote"], "display_value": "我将其归纳为编码与校准两步", "note": "已阅读上下文"}
    saved = save_review(runs, "new-domains", request)["review"]
    assert saved["quote"] == candidate["quote"] and saved["text"] == candidate["text"]
    field = method_comparison(runs, "new-domains", ["p1"])["papers"][0]["fields"]["method"]
    assert field["candidate"]["value"] == request["display_value"]
    assert field["candidate"]["value_kind"] == "human_note"
    save_review(runs, "new-domains", {**request, "display_value": "重新核对后的个人归纳"})
    changed = method_comparison(runs, "new-domains", ["p1"])["papers"][0]["fields"]["method"]["review"]
    assert changed["history"][0]["display_value"] == request["display_value"]
    with pytest.raises(ValueError, match="连续原文"):
        save_review(runs, "new-domains", {**request, "quote": "A fabricated claim"})


def test_stale_fragment_confirmation_is_rejected_before_any_write(structured_research):
    runs, run = structured_research
    candidate = method_comparison(runs, "new-domains", ["p1"])["papers"][0]["fields"]["method"]["candidate"]
    body = {"passage_id": candidate["passage_id"], "field": "method", "status": "accepted",
            "expected_text_sha256": candidate["text_sha256"]}
    path = run / "cache/p1/pages.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[1]["text"] = rows[1]["text"].replace("lightweight encoder", "different classifier")
    write_json(path, rows)
    with pytest.raises(ValueError, match="版本已变化"):
        save_review(runs, "new-domains", body)
    assert not (run / "output/research_workspace.json").exists()


def test_library_partial_updates_and_concurrency(structured_research):
    runs, _ = structured_research
    bodies = [{"paper_id": "p1", "favorite": True}, {"paper_id": "p1", "reading_status": "reading"},
              {"paper_id": "p1", "tags": ["Methods", "Methods", "  Replicate "]},
              {"paper_id": "p1", "notes": "Need to check sample conditions."}]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda body: save_library_item(runs, "new-domains", body), bodies))
    item = library_payload(runs, "new-domains")["items"][0]
    assert item["favorite"] is True and item["reading_status"] == "reading"
    assert item["tags"] == ["Methods", "Replicate"]
    assert item["notes"] == "Need to check sample conditions."
    assert item["history_count"] == 3


@pytest.mark.parametrize("updates", [{"favorite": "yes"}, {"reading_status": "finished"},
                                      {"tags": "tag"}, {"notes": []}, {}])
def test_library_validation_preserves_original(structured_research, updates):
    runs, run = structured_research
    path = run / "output/paper_library.json"
    with pytest.raises(ValueError):
        save_library_item(runs, "new-domains", {"paper_id": "p1", **updates})
    assert not path.exists()


def test_library_scope_and_gold_protection(structured_research):
    runs, run = structured_research
    protected = runs / "phase2-real"
    run.rename(protected)
    before = {p.relative_to(protected): p.read_bytes() for p in protected.rglob("*") if p.is_file()}
    result = save_library_item(runs, "phase2-real", {"paper_id": "p1", "favorite": True})
    assert result["run_id"].startswith("workspace_")
    assert before == {p.relative_to(protected): p.read_bytes() for p in protected.rglob("*") if p.is_file()}
    copy = runs / result["run_id"]
    write_json(copy / "run_manifest.json", {"run_id": result["run_id"], "offline": False,
                                           "live": {"matched_paper_ids": ["p2"]}})
    assert {i["paper_id"] for i in library_payload(runs, result["run_id"])["items"]} == {"p2"}
    with pytest.raises(ValueError):
        save_library_item(runs, result["run_id"], {"paper_id": "p1", "favorite": True})
    with pytest.raises(ValueError):
        export_library(runs, result["run_id"], "bibtex", ["p1"])


def test_portable_exports_escape_structural_injection(structured_research):
    runs, run = structured_research
    path = run / "output/papers.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["title"] = "A {trial}\nER  -\nTI  - injected"
    write_jsonl(path, rows)
    save_library_item(runs, "new-domains", {"paper_id": "p1", "notes": "=HYPERLINK(test)", "tags": ["tag"]})
    bib = export_library(runs, "new-domains", "bibtex", ["p1"])
    assert "\\{trial\\}" in bib["content"] and bib["content"].count("@misc{") == 1
    assert "10.1234/test\\_1" in bib["content"]
    ris = export_library(runs, "new-domains", "ris", ["p1"])["content"]
    assert sum(line.startswith("TI  -") for line in ris.splitlines()) == 1
    assert sum(line == "ER  -" for line in ris.splitlines()) == 1
    csv = export_library(runs, "new-domains", "csv", ["p1"])["content"]
    assert csv.startswith("\ufeff") and "'=HYPERLINK(test)" in csv
    md = export_library(runs, "new-domains", "markdown", ["p1"])
    assert md["paper_count"] == 1 and "阅读清单" in md["content"]


def test_guidance_stays_conditional_and_binds_every_fact(structured_research):
    runs, run = structured_research
    result = research_guidance(runs, "new-domains", ["p1"],
                               {"data": "my own sensor observations", "compute": "one laptop", "time": "two weeks"})
    assert result["kind"] == "conditional_suggestions" and len(result["suggestions"]) == 1
    suggestion = result["suggestions"][0]
    assert suggestion["decision"] == "requires_user_judgment"
    assert all(f["quote"] and f["page"] == 2 and f["passage_id"] and f["pdf_url"] for f in suggestion["facts"])
    assert {c["dimension"] for c in suggestion["checks"]} == {"data", "compute", "time"}
    assert not (run / "output/claim_decisions.jsonl").exists()
    with pytest.raises(ValueError):
        research_guidance(runs, "new-domains", user_resources=[])


def test_no_fulltext_produces_no_invented_guidance(structured_research):
    runs, run = structured_research
    write_json(run / "output/fulltext_audit.json", {"documents": []})
    result = research_guidance(runs, "new-domains", ["p1"], {"compute": "laptop"})
    assert result["suggestions"] == [] and result["missing_fulltext"] == ["p1"]


def test_numeric_resource_comparison_keeps_exact_source_and_scope(structured_research):
    runs, _ = structured_research
    result = research_guidance(runs, "new-domains", ["p1"], {"compute": "一张GPU，4GB显存", "time": "1小时"})
    checks = {c["dimension"]: c for c in result["suggestions"][0]["checks"]}
    assert checks["compute"]["numeric_comparison"]["status"] == "reported_capacity_above_user"
    assert checks["compute"]["numeric_comparison"]["reported_gb"] == 8
    assert checks["time"]["numeric_comparison"]["reported_hours"] == 2
    assert checks["time"]["numeric_comparison"]["status"] == "reported_run_above_user_budget"
    assert checks["compute"]["numeric_comparison"]["source_passage_id"]


def test_stable_citation_keys_follow_scholarly_identity_and_preserve_notes(structured_research):
    runs, run = structured_research
    import shutil
    save_library_item(runs, "new-domains", {"paper_id": "p1", "favorite": True, "notes": "Keep this human note."})
    saved_path = run / "output/paper_library.json"
    original = saved_path.read_bytes()
    first = library_payload(runs, "new-domains")["items"][0]
    assert first["citation_key_source"] == "doi"
    assert first["citation_key"] != first["paper_id"]
    clone = runs / "another-research"
    shutil.copytree(run, clone)
    rows = [json.loads(line) for line in (clone / "output/papers.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[0]["doi_or_arxiv"] = "https://doi.org/10.1234/OTHER_PAPER"
    for name in ["papers.jsonl", "paper_cards.jsonl"]:
        write_jsonl(clone / "output" / name, rows)
    other = library_payload(runs, "another-research")["items"][0]
    assert first["paper_id"] == other["paper_id"] and first["citation_key"] != other["citation_key"]
    bib = export_library(runs, "new-domains", "bibtex", ["p1"])["content"]
    ris = export_library(runs, "new-domains", "ris", ["p1"])["content"]
    assert "@misc{" + first["citation_key"] + "," in bib
    assert "ID  - " + first["citation_key"] in ris
    assert saved_path.read_bytes() == original
    assert library_payload(runs, "new-domains")["items"][0]["notes"] == "Keep this human note."


def test_citation_key_normalizes_identifier_aliases_and_arxiv_versions():
    doi = citation_metadata({"doi_or_arxiv": "DOI:10.1234/AbC_1", "paper_id": "paper-001"})
    alias = citation_metadata({"url": "https://doi.org/10.1234/abc_1?source=test", "paper_id": "different"})
    assert doi["citation_key"] == alias["citation_key"]
    arxiv = citation_metadata({"doi_or_arxiv": "arXiv:2305.14314v3"})
    pdf = citation_metadata({"url": "https://arxiv.org/pdf/2305.14314v1.pdf"})
    assert arxiv["citation_key"] == pdf["citation_key"]
    assert arxiv["arxiv_id"] == "2305.14314" and arxiv["citation_key_source"] == "arxiv"
    assert citation_metadata({"doi_or_arxiv": "cs/9901001v2"})["arxiv_id"] == "cs/9901001"
    assert citation_metadata({"url": "https://example.org/2305.14314"})["arxiv_id"] is None
    encoded = citation_metadata({"url": "https://doi.org/10.1234/test%23part?tracking=1"})
    literal = citation_metadata({"doi_or_arxiv": "10.1234/test#part"})
    assert encoded["citation_key"] == literal["citation_key"]


def test_metadata_citation_key_is_stable_across_runs_notes_and_normalized_spelling():
    first = {"title": "Learning—Under Constraints.", "authors": ["Alice Smith"], "year": 2024,
             "paper_id": "paper-001", "notes": "first note"}
    alias = {**first, "paper_id": "paper-999", "title": " learning under constraints ",
             "authors": ["Smith, Alice"], "notes": "edited note"}
    assert citation_metadata(first)["citation_key"] == citation_metadata(alias)["citation_key"]
    assert citation_metadata(first)["citation_key_source"] == "metadata"
    assert citation_metadata({**first, "title": "A different paper"})["citation_key"] != citation_metadata(first)["citation_key"]
    assert citation_metadata({"title": "甲研究"})["citation_key"] != citation_metadata({"title": "乙研究"})["citation_key"]


def test_single_bibliography_deduplicates_same_identifier_without_deleting_local_records(structured_research):
    runs, run = structured_research
    rows = [json.loads(line) for line in (run / "output/papers.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[1]["doi_or_arxiv"] = rows[0]["doi_or_arxiv"]
    for name in ["papers.jsonl", "paper_cards.jsonl"]:
        write_jsonl(run / "output" / name, rows)
    result = export_library(runs, "new-domains", "bibtex", ["p1", "p2"])
    assert result["paper_count"] == 1 and result["selected_paper_count"] == 2
    assert result["content"].count("@misc{") == 1
    assert export_library(runs, "new-domains", "ris", ["p1", "p2"])["content"].count("TY  - GEN") == 1
    assert len(library_payload(runs, "new-domains")["items"]) == 3


def test_run_local_id_is_not_an_identity_for_an_unidentifiable_record(structured_research):
    runs, run = structured_research
    rows = [json.loads(line) for line in (run / "output/papers.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[0].update(title=None, authors=[], year=None, doi_or_arxiv=None, url="local:unknown", dedup_key="p1")
    for name in ["papers.jsonl", "paper_cards.jsonl"]:
        write_jsonl(run / "output" / name, rows)
    item = library_payload(runs, "new-domains")["items"][0]
    assert item["citation_key_warning"]
    with pytest.raises(ValueError, match="稳定标识"):
        export_library(runs, "new-domains", "bibtex", ["p1"])
    assert export_library(runs, "new-domains", "csv", ["p1"])["paper_count"] == 1


@pytest.mark.parametrize("text,hours", [("两周", 336), ("三天", 72), ("半小时", .5),
    ("一小时半", 1.5), ("一个半小时", 1.5), ("1小时30分钟", 1.5), ("两周三天", 408),
    ("二十四小时", 24), ("三点五小时", 3.5), ("two weeks", 336)])
def test_duration_understands_explicit_chinese_and_compound_quantities(text, hours):
    assert _duration_hours(text) == pytest.approx(hours)


@pytest.mark.parametrize("text", ["2到4小时", "两到三天", "训练2小时，评估1小时", "训练1小时，评估1小时", "2 hours or 3 hours"])
def test_alternative_or_multiple_duration_configurations_are_not_maximized(text):
    parsed = _duration_analysis(text)
    assert parsed["status"] == "ambiguous" and _duration_hours(text) is None


def test_duration_candidate_retains_original_quote_spelling():
    original = "The experiment took Two Hours."
    candidate = _duration_analysis(original)["candidates"][0]
    assert candidate["hours"] == 2
    assert candidate["quote"] == "Two Hours" and candidate["quote"] in original


def test_memory_configuration_keeps_model_scale_and_never_picks_largest():
    reported = "The 7B model uses 12 GB GPU memory; the 65B model uses 48 GB GPU memory."
    parsed = _memory_analysis(reported)
    assert parsed["status"] == "ambiguous"
    assert [c["capacity_gb"] for c in parsed["candidates"]] == [12, 48]
    comparison, analysis = _memory_comparison(reported, "一张16GB显存GPU", "passage-1")
    assert comparison is None and analysis["status"] == "ambiguous"
    comparison, analysis = _memory_comparison(reported, "复现7B模型，一张16GB显存GPU", "passage-1")
    assert analysis["status"] == "resolved" and comparison["reported_gb"] == 12
    assert comparison["user_gb"] == 16 and comparison["source_passage_id"] == "passage-1"


def test_multi_gpu_capacity_is_not_summed_or_equated_to_single_gpu():
    parsed = _memory_analysis("2张24GB显存GPU")
    assert parsed["candidates"][0]["device_count"] == 2
    assert parsed["candidates"][0]["capacity_gb"] == 24
    comparison, analysis = _memory_comparison("2张24GB显存GPU", "单卡48GB显存GPU", "p")
    # 单卡 is explicit even without an Arabic count.
    assert comparison is None and analysis["status"] == "ambiguous"


def test_resource_comparison_refuses_a_different_model_scale():
    comparison, analysis = _memory_comparison("The 65B model trains on one GPU with 48 GB memory.",
                                            "我准备训练7B模型，单卡16GB显存GPU", "p")
    assert comparison is None and analysis["status"] == "ambiguous"
    assert analysis["reason"] == "model_scale_mismatch"


def test_guidance_exposes_configuration_selection_instead_of_a_false_numeric_result(structured_research, monkeypatch):
    runs, _ = structured_research
    quote = "7B uses 12 GB GPU memory; 65B uses 48 GB GPU memory."
    candidate = {"quote": quote, "text": quote, "page": 2, "passage_id": "source-1",
                 "text_sha256": "test-hash", "pdf_url": "/test#page=2"}
    monkeypatch.setattr("src.research_assistant.method_comparison", lambda *a, **k: {
        "papers": [{"paper_id": "p1", "title": "Synthetic multi-configuration test", "fields": {
            "resources": {"candidate": candidate, "status": "pending"}}}], "missing_paper_ids": []})
    check = research_guidance(runs, "new-domains", ["p1"], {"compute": "一张16GB显存GPU"})["suggestions"][0]["checks"][0]
    assert check["status"] == "needs_configuration_selection"
    assert check["numeric_comparison"] is None
    assert check["resource_analysis"]["status"] == "ambiguous"
    assert "先选择" in check["suggestion"] and check["sources"][0]["quote"] == quote
