"""Interactive full-text reading and explicitly human-reviewed method notes.

Review notes are a separate user-owned overlay. They never rewrite gold data or
automatically promote an extracted passage to a supported scientific claim.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import Any
import unicodedata
from urllib.parse import quote
from uuid import uuid4

from src.fulltext_search import Passage, build_fulltext_search, chunk_pages
from src.io_utils import read_json
from src.replay import load_run
from src.run_paths import resolve_run_dir, resolve_run_file
from src.run_scope import visible_paper_ids

FIELDS = [
    {"key": "task", "label": "研究任务"}, {"key": "method", "label": "研究方法"},
    {"key": "data", "label": "数据集"}, {"key": "sample_size", "label": "样本规模"},
    {"key": "experiment", "label": "实验设置"}, {"key": "baseline", "label": "对照基线"},
    {"key": "metrics", "label": "评价指标"}, {"key": "results", "label": "主要结果"},
    {"key": "resources", "label": "资源要求"}, {"key": "conditions", "label": "适用条件"},
]
PATTERNS = {
    "task": r"\b(task|objective|aim|goal|problem|research question|focus on|present|propose)\b|研究问题|研究任务|研究目标",
    "method": r"\b(method|methodology|approach|framework|algorithm|procedure|propose|introduces?|present)\b|方法|算法|框架",
    "data": r"\b(datasets?|data set|corpus|corpora|benchmark|documents)\b|数据集|语料库",
    "sample_size": r"\b\d[\d,]*(?:\.\d+)?[kKmM]?\s+(?:(?:partially annotated|annotated|training|test|contrast enhanced|abdominal|3D|CT)\s+){0,5}(?:samples?|participants?|subjects?|patients?|examples?|documents?|queries|questions|observations|images?|scans?)\b|(?:样本|受试者|患者|样例|问题|文档).{0,12}\d|\d[\d,]*\s*(?:名|例|个|条|份)",
    "experiment": r"\b(experimental setup|setup|experiments?|randomized|randomised|cross.validation|train(?:ing)? split|test set|fine.tun\w*|hyperparameters?|protocol|batch sizes?|learning rate|sequence length|epochs)\b|实验设置|随机试验|交叉验证|训练集|测试集|超参数",
    "baseline": r"\b(baseline|compared|comparison|ablation|control group)\b|基线|对照|消融",
    "metrics": r"\b(metrics?|accuracy|precision|recall|f1|evaluation|auc|bleu|rouge)\b|指标|准确率|召回率",
    "resources": r"\b(gpu|cpu|hardware|memory|runtime|training time|compute|cost|NVIDIA|Tesla|V100|A100|RTX\w*)\b|算力|显存|资源|耗时",
    "results": r"\b(achiev(?:e|es|ed)|outperform(?:s|ed)?|improv(?:e|es|ed|ement)|results? show|obtained|significant(?:ly)?|reduc(?:e|es|ed))\b|结果表明|结果显示|提高|提升|降低|显著",
    "conditions": r"\b(limitations?|assum(?:e|es|ed|ption)|applicab\w*|restricted|under the|only when|provided that|depends on|not expect|generaliz\w*|generalisation|generalization)\b|适用|局限|限制|假设|前提|仅当|依赖|泛化",
}
FIELD_SECTIONS = {
    "task": {"abstract", "introduction"}, "method": {"methods", "methodology"},
    "data": {"data", "methods", "experimental_setup"},
    "sample_size": {"data", "methods", "experimental_setup"},
    "experiment": {"experimental_setup", "methods"},
    "baseline": {"experimental_setup", "results", "methods"},
    "metrics": {"experimental_setup", "results", "methods"},
    "results": {"results", "conclusion", "conclusions"},
    "resources": {"experimental_setup", "methods"},
    "conditions": {"limitations", "discussion"},
}
_locks: dict[Path, threading.RLock] = {}
_guard = threading.Lock()


def _lock(path: Path) -> threading.RLock:
    with _guard:
        return _locks.setdefault(path.resolve(), threading.RLock())


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".workspace-", suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        from src.io_utils import replace_with_retry
        replace_with_retry(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def workspace_papers(runs_dir: Path, run_id: str, paper_ids: list[str] | None = None) -> dict:
    """Return only papers belonging to this research, without reading PDFs."""
    loaded = load_run(runs_dir, run_id)
    papers = {p.paper_id: p for p in loaded["dataset"].papers if not p.is_fixture}
    manifest = loaded.get("manifest") or {}
    if manifest.get("offline") is False:
        allowed = visible_paper_ids(manifest.get("live") or {})
        papers = {key: p for key, p in papers.items() if key in allowed}
    if paper_ids is not None:
        if not isinstance(paper_ids, list) or any(not isinstance(p, str) for p in paper_ids):
            raise ValueError("paper_ids 必须是论文编号数组")
        requested = set(paper_ids)
        if requested - papers.keys():
            raise ValueError("所选论文不属于当前研究范围")
        papers = {key: p for key, p in papers.items() if key in requested}
    return papers


def _corpus(runs_dir: Path, run_id: str, paper_ids: list[str] | None = None) -> tuple[dict, dict, list]:
    papers = workspace_papers(runs_dir, run_id, paper_ids)
    run_dir = resolve_run_dir(runs_dir, run_id)
    audit_path = run_dir / "output" / "fulltext_audit.json"
    audit = read_json(audit_path) if audit_path.exists() else {}
    pages, missing = {}, []
    documents = {d.get("paper_id"): d for d in audit.get("documents", [])}
    for paper_id in papers:
        document = documents.get(paper_id) or {}
        try:
            text_path = resolve_run_file(run_dir, document.get("text_path") or "")
            rows = read_json(text_path)
            if not isinstance(rows, list):
                raise ValueError("全文分页数据应为数组")
            if any(not isinstance(row, dict) or not isinstance(row.get("text"), str)
                   or not isinstance(row.get("page"), int) or row["page"] < 1 or row["page"] > 300 for row in rows):
                raise ValueError("全文分页数据格式不正确")
            mapping = {row["page"]: row["text"] for row in rows}
            if not any(text.strip() for text in mapping.values()):
                raise ValueError("全文尚无可检索文本，请先完成OCR或获取文本版")
            pages[paper_id] = [mapping.get(i, "") for i in range(1, max(mapping, default=0) + 1)]
        except (OSError, ValueError, TypeError):
            missing.append(paper_id)
    return papers, pages, missing


def _hit(passage: Passage, run_id: str) -> dict:
    return {
        "passage_id": passage.passage_id, "paper_id": passage.paper_id, "title": passage.title,
        "page": passage.page, "section": passage.section, "text": passage.abstract,
        "text_sha256": passage.text_sha256,
        "pdf_url": f"/api/fulltext/{quote(run_id, safe='')}/{quote(passage.paper_id, safe='')}#page={passage.page}",
    }


def _sentences(text: str) -> list[str]:
    """Extract contiguous original spans, retaining their spelling and newlines."""
    endings = [m.end() for m in re.finditer(r"[。！？]|[.!?](?=\s+(?:[A-Z\u4e00-\u9fff•]|$))", text)]
    endings.append(len(text))
    result, start = [], 0
    for end in endings:
        value = text[start:end].strip()
        if value:
            result.append(value)
        start = end
    return result or [text]


def _matching_text(text: str) -> str:
    # Native PDF extraction commonly breaks words at line endings. Match the
    # reconstructed word, but always retain the unmodified contiguous quote.
    value = unicodedata.normalize("NFKC", text)
    value = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", value)
    return re.sub(r"\s+", " ", value).strip()


def _field_strength(text: str, field: str) -> int:
    """Conservative field-specific evidence, rather than keyword frequency.

    A matching word alone cannot tell whether a sentence describes this paper's
    data, its batch size, an unrelated method, or a tutorial's intended reader.
    Returning zero leaves a field explicitly missing instead of mislabelling it.
    This ranking does not certify scientific support; users still review quotes.
    """
    s = _matching_text(text)
    if len(s) < 16 or len(s) > 800:
        return 0
    if text.count("\n") > 12 or (field != "metrics" and re.search(r"\b(?:Figure|FIG\.|Table)\s*\d", s, re.I)):
        return 0
    if re.match(r"^[a-z]", s) or not re.search(r"[.!?。！？)\]]$", s):
        return 0
    if s.count(")") > s.count("(") or s.count("]") > s.count("["):
        return 0
    own = bool(re.search(r"\b(?:we|our)\b|本文|我们|本研究", s, re.I))
    score = 1
    if field == "task":
        explicit = re.search(r"\b(?:research objective|goal|aim)\s+is\b|\bgoal of\b.{0,90}\bis\b|\btask\s+is\b|\bwe\s+(?:focus|study|investigate|aim)\b|研究目标|研究任务|研究问题", s, re.I)
        contribution = re.search(r"\bwe\s+(?:present|propose|introduce)\b", s, re.I)
        if not (explicit or contribution):
            return 0
        score = 8 if explicit else 7
        if explicit and re.search(r"\b(?:tutorial|reader|my goal|we will)\b", s, re.I):
            score = 4
        elif explicit and re.search(r"\bgoal of\b.{0,90}\bis\b", s, re.I):
            score = 9
    elif field == "method":
        contribution = re.search(r"\b(?:we|our\s+(?:method|approach|framework))\s+(?:propose|present|introduce|combine|uses?|consists?|incorporates?)\b", s, re.I)
        mechanism = re.search(r"\b(?:method|approach|algorithm|procedure|framework)\s+(?:combines?|uses?|consists?|computes?|learns?|is\s+based|for\s+extracting)\b|提出|方法.*(?:结合|采用|计算)", s, re.I)
        if not (contribution or mechanism):
            return 0
        score = 11 if re.search(r"\bwe\s+(?:propose|present|introduce)\b", s, re.I) else 8 if contribution else 6
        if re.search(r"\b(?:will|might|could|hope|later|future work)\b", s, re.I):
            return 0
    elif field == "data":
        if re.search(r"\blet\s+[A-Z]\b|original data set|given dataset|data set specific|guidelines|see (?:appendix|section)|数据集特定", s, re.I):
            return 0
        description = re.search(r"\b(?:datasets?|data set|corpus|corpora)\b.{0,90}\b(?:contains?|consists?|compris\w*|includes?|provided|collected|collection)\b", s, re.I)
        usage = re.search(r"\bwe\b.{0,35}\b(?:use|select|include|evaluate|test|train)\b.{0,130}\b(?:datasets?|benchmark|corpus|corpora)\b|\b(?:datasets?|benchmark)\b.{0,25}(?:are|is) used\b", s, re.I)
        if not (description or usage or re.search(r"数据集.*(?:包含|收集|来自)|(?:采用|使用).*数据集", s)):
            return 0
        score = 8 if description else 6
        if re.search(r"\([^)]*[A-Z][A-Z0-9-]{2,}[^)]*\)|[“\"][A-Z][^”\"]+[”\"]|\b[A-Z][A-Z-]{2,}\b", s):
            score += 2
        if re.search(r"\d", s):
            score += 1
    elif field == "sample_size":
        # Batch size and numbered figure examples are never study sample counts.
        if re.search(r"batch|mini.batch|per batch|批次|批量|batch sizes?", s, re.I):
            return 0
        match = re.search(PATTERNS[field], s, re.I)
        if not match:
            return 0
        if re.search(r"\b(?:sample|example)\b", match.group(0), re.I) and re.search(r"\b(?:fig|figure)\b", s, re.I):
            return 0
        if re.search(r"\b(?:prior|previous|existing|breakthrough|supervised training of a large)\b", s, re.I) and not own:
            return 0
        score = 8
        if re.search(r"\b(?:dataset|data set|contains?|consists?|collected|included|acquired)\b", s, re.I):
            score += 3
    elif field == "experiment":
        if re.search(r"\b(?:overview|describe.*setup|details in|discuss|section|future|we include comparisons|less feasible|becomes less|principles|motivating use case|this means|when applying|by setting|in principle|retune)\b", s, re.I):
            return 0
        if not re.search(r"\b(?:us(?:e|es|ed|ing)|randomi[sz]\w*|trained|train(?:ing)?|split|fold|protocol|hyperparameters?|temperature|sampling)\b|采用|训练|设置|交叉验证", s, re.I):
            return 0
        if len(re.findall(r"[∑ΦλΘ∆=]", s)) > 3:
            return 0
        if re.search(r"\b(?:we (?:also )?observe|speedup|results show|outperforms?)\b", s, re.I):
            return 0
        score = 7 + (2 if own else 0)
        if re.search(r"\b(?:sequence length|batch sizes?|learning rate|epochs)\b.{0,50}\d", s, re.I):
            score += 3
    elif field == "baseline":
        if re.search(r"\b(?:include comparisons|experiment section|prior work|generic|many have|see section)\b", s, re.I):
            return 0
        specific = re.search(r"\bbaseline\s+(?:is|was)|\b(?:compared|benchmarked)\s+(?:against|to|with)\b|\bwe\s+compare\b|基线为|对照组", s, re.I)
        if not specific:
            return 0
        score = 7 + (2 if own else 0)
    elif field == "metrics":
        if not re.search(r"\b(?:metrics?|measure|measured|measuring|report|reported|evaluation is|evaluated using|in terms of|rate the)\b|评价指标|指标为|采用.*指标", s, re.I):
            return 0
        if not re.search(r"\b(?:accuracy|precision|recall|f1|auc|bleu|rouge\w*|score|error|correlation|DSC|distance)\b|准确率|召回率|评价指标", s, re.I):
            return 0
        score = 8 + (2 if own else 0)
    elif field == "results":
        if re.search(r"\b(?:can be|if the|might|could|we hope|we aim|we propose|we present|not expect)\b|\bproblem reduces\b", s, re.I):
            return 0
        if not re.search(r"\b(?:we\s+(?:find|show|observe)|results?\s+(?:show|demonstrate)|achiev\w*|outperform\w*|improv\w*|reduc\w*|obtained)\b|结果表明|结果显示|提高|提升|降低", s, re.I):
            return 0
        if re.search(r"\b(?:helps to|to reduce|to improve|is achieved by|obtained at the output|reduced representation|reduced dimensions|problem|basis|variables|sensor recordings)\b", s, re.I):
            return 0
        without_refs = re.sub(r"\[[\d,\s]+\]", "", s)
        score = 6 + (3 if re.search(r"\d", without_refs) else 0) + (1 if own else 0)
    elif field == "resources":
        concrete = re.search(r"\d\s*(?:GB|MB|TB|hours?|minutes?|seconds?|days?|GPU)|\b(?:NVIDIA|Tesla|RTX\w*|V100|A100|H100)\b|\d\s*(?:小时|分钟|显存)", s, re.I)
        if not concrete:
            return 0
        if re.search(r"\b(?:regular|usual way|pre.training|common|commonly|existing techniques|prior work)\b", s, re.I) and not own:
            return 0
        score = 8 + (3 if own else 0)
        if re.search(r"\b(?:all experiments|we use|training time|training.*hours?|finetun.*hours?)\b", s, re.I):
            score += 3
        if re.search(r"\ball experiments\b", s, re.I):
            score += 2
    elif field == "conditions":
        if ((len(s.split()) < 8 and not re.search(r"[\u4e00-\u9fff]", s))
                or re.search(r"\b(?:reader|reading|knowledge of|tutorial|both strategies|previous methods|labeled with|this question|he|she)\b|读者|阅读本文", s, re.I)):
            return 0
        if not re.search(r"\b(?:model|method|algorithm|network|data|datasets?|linear|linearity|labels?|training|samples?|tasks?|parameters?|variance|noise|measurements?|participants?|patients?|protocol|trial|experiment|cohort|population|sites?)\b|方法|模型|数据|实验|患者|样本|前提", s, re.I):
            return 0
        explicit = re.search(r"\b(?:assum\w*|restricted to|only when|provided that|depends on|not expect|limited to|limitations?|must)\b|适用|局限|限制|假设|前提|仅当|依赖", s, re.I)
        applicability = re.search(r"\b(?:applicable|can be applied|can be used)\s+to\b", s, re.I)
        if not (explicit or applicability):
            return 0
        if re.search(r"\b(?:to demonstrate|for example|in this example)\b", s, re.I):
            return 0
        score = 7 if explicit else 4
    return score


def _field_candidate(passage: Passage, field: str, run_id: str, chosen_quote: str | None = None) -> dict | None:
    if (passage.section or "").lower() in {"references", "bibliography", "参考文献"}:
        return None
    sentences = [s for s in _sentences(passage.abstract)
                 if re.search(PATTERNS[field], _matching_text(s), re.I)
                 and _field_strength(s, field)]
    if chosen_quote is not None:
        if not chosen_quote.strip() or chosen_quote not in passage.abstract:
            return None
        sentences = [chosen_quote]
    if not sentences:
        return None
    ranked = sorted(sentences, key=lambda s: (-_field_strength(s, field), len(s) > 600, abs(len(s) - 180)))
    original = ranked[0]
    value_sentence = original
    if chosen_quote is None and re.match(r"^(?:It|This dataset)\b", original):
        all_sentences = _sentences(passage.abstract)
        position = all_sentences.index(original)
        if position:
            before = all_sentences[position - 1]
            start = passage.abstract.index(before)
            end = passage.abstract.index(original) + len(original)
            if end - start <= 900:
                original = passage.abstract[start:end]
    # Values are extractive, never an ungrounded generated paraphrase. Numeric
    # fields use their exact phrase while the complete sentence stays visible.
    value = re.sub(r"\s+", " ", original).strip()
    if field == "sample_size":
        match = re.search(PATTERNS[field], value_sentence, re.I)
        if match:
            value = re.sub(r"\s+", " ", match.group(0))
    start = passage.abstract.index(original)
    strength = _field_strength(original, field)
    if passage.section == "abstract" and field in {"task", "method", "results"}:
        strength += 3
    return {**_hit(passage, run_id), "quote": original, "quote_sha256": sha256(original.encode()).hexdigest(),
            "value": value, "summary": value, "extraction_source": "rule_sentence", "field_score": strength,
            "value_kind": "extractive", "quote_start": start, "quote_end": start + len(original),
            "notice": "原文要点，待人工核对；不是自动支持判决。"}


def search_fulltext(runs_dir: Path, run_id: str, query: str,
                    paper_ids: list[str] | None = None, section: str | None = None) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("请输入不超过2000字的全文检索问题")
    if section is not None and (not isinstance(section, str) or len(section) > 100):
        raise ValueError("章节筛选应为不超过100字的文本")
    papers, pages, missing = _corpus(runs_dir, run_id, paper_ids)
    # Filtering is performed after chapter inheritance, so a method's
    # continuation page remains searchable without repeating the heading.
    result = build_fulltext_search(query.strip(), papers, pages, section=section)
    for item in result["hits"]:
        item.update(title=papers[item["paper_id"]].title or item["paper_id"],
                    pdf_url=f"/api/fulltext/{quote(run_id, safe='')}/{quote(item['paper_id'], safe='')}#page={item['page']}")
    return {**result, "run_id": run_id, "query": query.strip(), "missing_paper_ids": missing,
            "notice": "正文命中用于阅读定位；论断支持关系可在人工复核后保存。"}


def research_agenda_fulltext(runs_dir: Path, run_id: str, question: str, paper_ids: list[str],
                             *, selection: dict | None = None) -> dict:
    """Allocate the evidence window across papers before ranking passages within each one."""
    from src.retrieval_rank import lexical_score
    from src.tasks import check_cancelled

    papers, pages, missing = _corpus(runs_dir, run_id, paper_ids)
    available = [pid for pid in paper_ids if pid in pages]
    ranked = sorted(available, key=lambda pid: -lexical_score(
        question, f"{papers[pid].title or ''} {papers[pid].abstract or ''}"))
    query = (question[:1600] + " 方法 数据 实验 基线 指标 结果 局限 "
             "method dataset benchmark evaluation experiment results limitations ablation robustness")
    groups = []
    for pid in ranked[:6]:
        check_cancelled()
        passages = chunk_pages({pid: papers[pid]}, {pid: pages[pid]})
        primary = [passage for passage in passages if passage.section != "appendix"]
        group, chosen = [], set()
        for facet in ("experiment", "baseline", "results", "conditions"):
            check_cancelled()
            candidates = _rank_field_candidates(primary, facet, run_id, set())
            if facet == "experiment":
                candidates.sort(key=lambda item: not re.search(
                    r"\bablat\w*|\bpaired\b|\bcontrol group\b|\brandomi[sz]\w*|消融|配对|对照组|随机",
                    item["quote"], re.I))
            candidate = next((item for item in candidates if item["passage_id"] not in chosen), None)
            if candidate:
                chosen.add(candidate["passage_id"])
                group.append({**candidate, "agenda_facet": facet, "quote_hint": candidate["quote"]})
        if len(group) < 4:
            selected_pages = {hit["page"] for hit in group}
            candidates = build_fulltext_search(query, {pid: papers[pid]}, {pid: pages[pid]}, top_k=12,
                                               semantic_rerank=False)["hits"]
            for hit in candidates:
                if hit["page"] in selected_pages or hit["section"] == "references":
                    continue
                selected_pages.add(hit["page"])
                group.append({**hit, "title": papers[pid].title or pid,
                              "pdf_url": f"/api/fulltext/{quote(run_id, safe='')}/{quote(pid, safe='')}#page={hit['page']}"})
                if len(group) == 4:
                    break
        groups.append(group)
    hits = [group[index] for index in range(4) for group in groups if index < len(group)]
    if selection and (own := pages.get(selection["paper_id"])) and selection["page"] <= len(own):
        from src.reading_selection import selected_page_passages
        pid = selection["paper_id"]
        chunks = chunk_pages({pid: papers[pid]}, {pid: own})
        anchors = selected_page_passages(chunks, selection, own[selection["page"] - 1])[:2]
        anchored_ids = {p.passage_id for p in anchors}
        hits = [_hit(p, run_id) for p in anchors] + [hit for hit in hits if hit["passage_id"] not in anchored_ids]
    return {"algorithm": "paper_balanced_experiment_evidence", "hits": hits[:12],
            "available_fulltext_paper_ids": available, "missing_paper_ids": missing}


def _workspace_saved(run_dir: Path) -> dict:
    path = run_dir / "output" / "research_workspace.json"
    if not path.exists():
        return {"reviews": []}
    data = read_json(path)
    if (not isinstance(data, dict) or not isinstance(data.get("reviews"), list)
            or any(not isinstance(row, dict) for row in data["reviews"])):
        raise ValueError("研究笔记文件格式不正确，原文件已保留")
    for row in data["reviews"]:
        for key in ("paper_id", "passage_id", "review_id", "status", "text", "text_sha256", "quote", "display_value"):
            if key in row and row[key] is not None and not isinstance(row[key], str):
                raise ValueError("研究笔记字段格式不正确，原文件已保留")
    return data


def workspace_payload(runs_dir: Path, run_id: str) -> dict:
    run_dir = resolve_run_dir(runs_dir, run_id)
    with _lock(run_dir):
        data = _workspace_saved(run_dir)
    # Old or imported runs may contain historic notes outside their current
    # visible set. Hide those in UI/export while preserving the stored history.
    if data["reviews"]:
        allowed = workspace_papers(runs_dir, run_id).keys()
        data = {**data, "reviews": [row for row in data["reviews"] if row.get("paper_id") in allowed]}
    return {**data, "run_id": run_id, "protected": run_id in {"phase2-real", "demo"}}


def _condition_mentions(text: str) -> dict:
    """Literal comparison hints, not inferred identities or experiment links.

    Recognised names are deliberately incomplete. An unknown dataset stays
    unknown rather than using the word 'dataset' as evidence of equivalence.
    The complete source sentence is always retained by the calling context.
    """
    s = _matching_text(text)
    dataset_pattern = (r"\b(?:MNLI|CoLA|GLUE|SST-?2|MRPC|RTE|QNLI|QQP|SQuAD(?:\s*2\.0)?|"
                       r"ImageNet|CIFAR-?(?:10|100)|ISBI(?:\s*20\d{2})?|CT-?(?:82|150)|"
                       r"OASST1?|Alpaca|FLAN(?:\s*v\d)?|MMLU|HH-RLHF|MIMIC(?:-?(?:III|IV))?)\b")
    datasets = set()
    for m in re.finditer(dataset_pattern, s, re.I):
        near = s[max(0, m.start()-50):m.end()+65]
        if re.search(r"\b(?:data\s*sets?|corpus|corpora|benchmarks?|training data)\b|数据集|语料", near, re.I) or re.search(
                r"\b(?:on|using)\s+(?:the\s+)?" + re.escape(m.group()) + r"\b", s, re.I) or re.search(
                r"\b(?:finetun\w*|trained|training|evaluat\w*|test\w*)\b.{0,40}\bon\b.{0,80}\b" + re.escape(m.group()) + r"\b", s, re.I):
            datasets.add(re.sub(r"\s+", " ", m.group()).upper())
    # Explicitly named datasets outside the small recognised vocabulary.
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9_-]{2,}(?:\s+[A-Z][A-Za-z0-9_-]{2,}){0,2})\s+(?:data\s*set|corpus|benchmark)\b", s):
        name = re.sub(r"^(?:The|This|Our)\s+", "", m[1])
        if name.lower() not in {"the", "this", "our", "given", "training", "test", "validation"}:
            datasets.add(name.upper())
    metric_pattern = r"\b(?:accuracy|precision|recall|F1(?:[- ]score)?|AUC|BLEU|ROUGE(?:-[12L])?|DSC|Dice|IoU|RMSE|MSE|MAE|Rand error|warping error|pixel error)\b|准确率|召回率"
    aliases = {"dsc": "dice", "准确率": "accuracy", "召回率": "recall", "f1-score": "f1", "f1 score": "f1"}
    metrics = set()
    for m in re.finditer(metric_pattern, s, re.I):
        if m.group().lower() == "precision" and re.search(
                r"\b(?:bit|float|bfloat|quantiz|fp16|fp32|bf16)\w*\b", s[max(0,m.start()-25):m.end()+25], re.I):
            continue
        metrics.add(aliases.get(m.group().lower(), m.group().lower()))
    settings = {}
    patterns = {
        "batch_size": r"\bbatch\s+size(?:\s+of|\s+is|\s*=)?\s*(\d+)\b",
        "sequence_length": r"\bsequence\s+length(?:\s+of|\s+is|\s*=)?\s*(\d+)\b",
        "epochs": r"\b(\d+)\s+epochs?\b",
        "cross_validation": r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten)[- ]fold\b",
        "precision": r"\b((?:4|8|16|32)[- ]bit)\b",
        "model_parameters": r"\b(\d+(?:\.\d+)?(?:\s*[BM])?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*[BM])[- ]?(?:parameter|model)s?\b",
    }
    numbers = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
    for key, pattern in patterns.items():
        values = {numbers.get(m[1].lower(), re.sub(r"\s+", "", m[1].lower()).replace("-", "") if key == "precision"
                              else re.sub(r"\s+", "", m[1].lower()))
                  for m in re.finditer(pattern, s, re.I)}
        if values:
            settings[key] = sorted(values)
    return {"datasets": sorted(datasets), "metrics": sorted(metrics), "settings": settings,
            "scope": "literal_mentions_only_not_verified_experiment_identity"}


def _experiment_contexts(passages: list[Passage], run_id: str) -> list[dict]:
    """Keep configuration clues local to one continuous original sentence.

    Adjacent sentences and matching names across pages are not enough to prove
    a shared experiment. This intentionally provides source contexts for human
    selection instead of joining the independently selected ten fields.
    """
    contexts, seen = [], set()
    keys = ["data", "sample_size", "experiment", "baseline", "metrics", "results", "resources"]
    for passage in passages:
        if passage.section in {"references", "bibliography"} or (passage.section == "abstract" and passage.page == 1):
            continue
        for sentence in _sentences(passage.abstract):
            normalized = _matching_text(sentence)
            if not 30 <= len(normalized) <= 900:
                continue
            mentions = _condition_mentions(sentence)
            fields = {key: _field_candidate(passage, key, run_id, sentence) for key in keys
                      if re.search(PATTERNS[key], normalized, re.I) and _field_strength(sentence, key)}
            hint_count = sum(bool(mentions[k]) for k in ["datasets", "metrics", "settings"])
            # A generic method sentence alone is not an experimental context.
            if not (len(fields) >= 2 or hint_count >= 2
                    or ("experiment" in fields and mentions["settings"])
                    or ("resources" in fields and _field_strength(sentence, "resources") >= 11)):
                continue
            if not ({"experiment", "results", "data", "sample_size", "resources"} & fields.keys()
                    or mentions["datasets"]):
                continue
            fingerprint = sha256(normalized.encode()).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            ambiguities = []
            if len(mentions["datasets"]) > 1:
                ambiguities.append("multiple_dataset_mentions")
            if any(len(values) > 1 for values in mentions["settings"].values()):
                ambiguities.append("multiple_setting_values")
            if any(re.search(r"\d[-–]\d", value) for values in mentions["settings"].values() for value in values):
                ambiguities.append("setting_range_needs_selection")
            if re.search(r"\brespectively\b|分别|不同配置", normalized, re.I):
                ambiguities.append("configuration_mapping_needs_review")
            source = {**_hit(passage, run_id), "quote": sentence,
                      "quote_sha256": sha256(sentence.encode()).hexdigest(),
                      "quote_start": passage.abstract.index(sentence),
                      "quote_end": passage.abstract.index(sentence) + len(sentence)}
            contexts.append({"context_id": "context-" + sha256((passage.paper_id + fingerprint).encode()).hexdigest()[:16],
                             "paper_id": passage.paper_id, "source": source, "fields": fields,
                             "condition_mentions": mentions, "ambiguity_reasons": ambiguities,
                             "association": "same_sentence_context_only", "human_confirmed": False,
                             "notice": "信息仅在同一连续原文句内共现，尚未确认属于同一个实验配置。"})
    contexts.sort(key=lambda c: (-sum(bool(c["condition_mentions"][k]) for k in ["datasets", "metrics", "settings"]),
                                 bool(c["ambiguity_reasons"]), -len(c["fields"]),
                                 c["source"]["page"], c["context_id"]))
    return contexts[:8]


def _comparison_eligibility(papers: list[dict]) -> dict:
    """Check observed conditions without ranking incompatible result numbers."""
    pairs = []
    for index, left in enumerate(papers):
        for right in papers[index + 1:]:
            a, b = left["experiment_contexts"], right["experiment_contexts"]
            checks = []
            for key, label in [("datasets", "数据集"), ("metrics", "评价指标")]:
                av = sorted({v for context in a for v in context["condition_mentions"][key]})
                bv = sorted({v for context in b for v in context["condition_mentions"][key]})
                status = ("missing" if not av or not bv else "matching_mentions" if av == bv else
                          "partial_overlap" if set(av) & set(bv) else "different")
                checks.append({"key": key, "label": label, "status": status, "left_values": av, "right_values": bv})
            def settings(contexts):
                collected = {}
                for context in contexts:
                    for key, values in context["condition_mentions"]["settings"].items():
                        collected.setdefault(key, set()).update(values)
                return collected
            av, bv = settings(a), settings(b)
            common = av.keys() & bv.keys()
            setting_status = ("missing" if not common else "different" if any(av[k] != bv[k] for k in common)
                              else "matching_mentions" if av.keys() == bv.keys() else "partial_overlap")
            checks.append({"key": "settings", "label": "实验设置", "status": setting_status,
                           "left_values": {k: sorted(v) for k, v in av.items()},
                           "right_values": {k: sorted(v) for k, v in bv.items()}})
            if any(c["status"] == "different" for c in checks):
                status, notice = "conditions_differ", "检测到不同的数据集、指标或设置，不能直接按结果数值排名。"
            elif any(c["status"] == "missing" for c in checks):
                status, notice = "insufficient_evidence", "缺少可核对的数据集、指标或共同实验设置，请先补充原文条件。"
            elif any(context["ambiguity_reasons"] for context in a + b) or any(c["status"] == "partial_overlap" for c in checks):
                status, notice = "multiple_configurations", "原文涉及多个或部分重合的条件，请先选择并人工核对具体实验。"
            else:
                status, notice = "needs_manual_confirmation", "部分条件名称一致，但尚未确认划分、模型与评测口径；请人工核对后比较。"
            pairs.append({"left_paper_id": left["paper_id"], "right_paper_id": right["paper_id"],
                          "status": status, "checks": checks, "notice": notice,
                          "left_context_ids": [c["context_id"] for c in a],
                          "right_context_ids": [c["context_id"] for c in b],
                          "automatic_ranking_allowed": False, "direct_result_comparison": False})
    return {"policy": "source_context_checks_require_human_experiment_alignment", "pairs": pairs,
            "automatic_ranking_allowed": False,
            "notice": "十字段为论文级阅读线索；配置线索仅保留同句证据，不自动拼接为同一实验或按结果排名。"}


def _rank_field_candidates(passages: list[Passage], field: str, run_id: str, used_quotes: set[str]) -> list[dict]:
    candidates = [candidate for passage in passages
                  if (candidate := _field_candidate(passage, field, run_id)) is not None]
    candidates.sort(key=lambda candidate: (
        -candidate.get("field_score", 0), candidate["section"] not in FIELD_SECTIONS[field],
        candidate["quote"] in used_quotes, len(candidate["quote"]) > 600,
        candidate["page"], candidate["passage_id"]))
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate["quote_sha256"], candidate)
    return list(unique.values())


def paper_method_evidence(runs_dir: Path, run_id: str, paper_id: str) -> dict:
    """Locate extractive method evidence in one paper's stored page text."""
    from src.tasks import check_cancelled

    papers, pages, _ = _corpus(runs_dir, run_id, [paper_id])
    passages = chunk_pages(papers, pages)
    fields, used_quotes = [], set()
    for field in FIELDS:
        check_cancelled()
        key = field["key"]
        if key not in {"task", "method", "data", "experiment", "baseline", "metrics", "results"}:
            continue
        ranked = _rank_field_candidates(passages, key, run_id, used_quotes)
        candidate = ranked[0] if ranked else None
        if candidate:
            used_quotes.add(candidate["quote"])
        fields.append({**field, "candidate": candidate, "status": "located" if candidate else "missing"})
    return {"paper_id": paper_id, "title": papers[paper_id].title or paper_id, "fields": fields,
            "mode": "extractive", "has_fulltext": paper_id in pages}


def method_comparison(runs_dir: Path, run_id: str, paper_ids: list[str] | None = None) -> dict:
    papers, pages, missing = _corpus(runs_dir, run_id, paper_ids)
    passages = chunk_pages(papers, pages)
    reviews = workspace_payload(runs_dir, run_id)["reviews"]
    results = []
    for paper_id, paper in papers.items():
        own = [p for p in passages if p.paper_id == paper_id]
        contexts = _experiment_contexts(own, run_id)
        fields, used_quotes = {}, set()
        for field in FIELDS:
            key = field["key"]
            candidates = _rank_field_candidates(own, key, run_id, used_quotes)
            candidate = candidates[0] if candidates else None
            if candidate:
                used_quotes.add(candidate["quote"])
            saved = [r for r in reviews if r.get("paper_id") == paper_id and r.get("field") == key]
            selected = next((r for r in reversed(saved) if r.get("status") == "accepted"), saved[-1] if saved else None)
            if selected:
                original = next((p for p in own if p.passage_id == selected.get("passage_id")
                                 and p.text_sha256 == selected.get("text_sha256")), None)
                if original:
                    candidate = _field_candidate(original, key, run_id, selected.get("quote")) or _hit(original, run_id)
                    if selected.get("display_value"):
                        candidate.update(value=selected["display_value"], summary=selected["display_value"],
                                         value_kind="human_note", extraction_source="human")
                else:
                    selected = {**selected, "status": "stale", "notice": "原文版本已变化，请重新核对"}
            linked_contexts = [c["context_id"] for c in contexts if candidate and
                               c["source"]["passage_id"] == candidate["passage_id"] and
                               (candidate.get("quote", "") == c["source"]["quote"])]
            fields[key] = {"candidate": candidate, "review": selected,
                           "status": selected["status"] if selected else "pending",
                           "missing": candidate is None, "candidate_count": len(candidates),
                           "candidates": candidates[:5], "experiment_context_ids": linked_contexts,
                           "experiment_association": "same_sentence_context_only" if linked_contexts else "unlinked"}
        results.append({"paper_id": paper_id, "title": paper.title or paper_id,
                        "has_fulltext": paper_id in pages, "fields": fields,
                        "experiment_contexts": contexts})
    return {"run_id": run_id, "fields": FIELDS, "papers": results, "missing_paper_ids": missing,
            "comparability": _comparison_eligibility(results),
            "extraction": "evidence_linked_extractive_sentences",
            "notice": "字段值摘自连续原文句，附完整段落与页码；人工修订、确认与备注单独保存。"}


def _portable(value: Any, source: Path, new_id: str | None = None) -> Any:
    if isinstance(value, list):
        return [_portable(item, source, new_id) for item in value]
    if not isinstance(value, dict):
        if isinstance(value, str) and new_id:
            return value.replace(f"/api/fulltext/{quote(source.name, safe='')}/",
                                 f"/api/fulltext/{quote(new_id, safe='')}/")
        return value
    result = {}
    for key, item in value.items():
        if key in {"response_path", "text_path"} and isinstance(item, str):
            try:
                item = resolve_run_file(source, item).relative_to(source.resolve()).as_posix()
            except (ValueError, OSError):
                pass
        result[key] = _portable(item, source, new_id)
    return result


def fork_workspace(runs_dir: Path, run_id: str) -> dict:
    source = resolve_run_dir(runs_dir, run_id)
    load_run(runs_dir, run_id)  # Require a real, replayable source.
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("研究记录包含符号链接，请先检查源文件")
    new_id = "workspace_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8]
    target = resolve_run_dir(runs_dir, new_id)
    shutil.copytree(source, target)
    for path in target.rglob("*"):
        if path.suffix not in {".json", ".jsonl"} or not path.is_file():
            continue
        if path.suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            path.write_text("".join(json.dumps(_portable(row, source, new_id), ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        else:
            data = _portable(read_json(path), source, new_id)
            if isinstance(data, dict) and "run_id" in data:
                data["run_id"] = new_id
            _atomic_json(path, data)
    manifest = read_json(target / "run_manifest.json")
    manifest.update(run_id=new_id, parent_run_id=run_id, workspace_copy=True,
                    created_at=datetime.now(timezone.utc).isoformat())
    _atomic_json(target / "run_manifest.json", manifest)
    return {"run_id": new_id, "parent_run_id": run_id}


def save_review(runs_dir: Path, run_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("复核内容应为JSON对象")
    passage_id = body.get("passage_id")
    field = body.get("field") or None
    status = body.get("status")
    note, claim, display_value = body.get("note", ""), body.get("claim", ""), body.get("display_value", "")
    if not isinstance(passage_id, str) or not isinstance(status, str) or status not in {"accepted", "rejected", "pending"}:
        raise ValueError("请选择真实正文片段及复核状态")
    if field is not None and (not isinstance(field, str) or field not in {f["key"] for f in FIELDS}):
        raise ValueError("未知的方法字段")
    if (not isinstance(note, str) or not isinstance(claim, str) or not isinstance(display_value, str)
            or len(note) > 4000 or len(claim) > 2000 or len(display_value) > 2000):
        raise ValueError("备注应不超过4000字，论断应不超过2000字")
    papers, pages, _ = _corpus(runs_dir, run_id)
    passage = next((p for p in chunk_pages(papers, pages) if p.passage_id == passage_id), None)
    if passage is None:
        raise ValueError("该片段不属于当前研究的可用全文")
    expected_hash = body.get("expected_text_sha256")
    if expected_hash is not None and (not isinstance(expected_hash, str) or expected_hash != passage.text_sha256):
        raise ValueError("原文片段版本已变化，请刷新全文结果并重新核对后保存")
    original_quote = body.get("quote")
    if original_quote is not None and (not isinstance(original_quote, str) or not original_quote.strip()
                                       or original_quote not in passage.abstract):
        raise ValueError("选定摘录必须是当前片段的连续原文")
    if original_quote is None:
        candidate = _field_candidate(passage, field, run_id) if field else None
        original_quote = candidate["quote"] if candidate else passage.abstract
    if run_id in {"phase2-real", "demo"}:
        run_id = fork_workspace(runs_dir, run_id)["run_id"]
    run_dir = resolve_run_dir(runs_dir, run_id)
    with _lock(run_dir):
        data = _workspace_saved(run_dir)
        review = {**_hit(passage, run_id), "review_id": "review-" + sha256((passage_id + "|" + (field or "")).encode()).hexdigest()[:20],
                  "field": field, "status": status, "note": note.strip(), "claim": claim.strip(),
                  "display_value": display_value.strip(), "quote": original_quote,
                  "quote_sha256": sha256(original_quote.encode()).hexdigest(),
                  "reviewer": "local_user", "review_source": "human", "updated_at": datetime.now(timezone.utc).isoformat()}
        previous = next((r for r in data["reviews"] if r.get("review_id") == review["review_id"]), None)
        if previous:
            review["history"] = (previous.get("history") or []) + [
                {key: previous.get(key) for key in ("status", "note", "claim", "display_value", "quote", "updated_at", "text_sha256")}]
        data["reviews"] = [r for r in data["reviews"] if r.get("review_id") != review["review_id"]] + [review]
        data.update(version="1", run_id=run_id, protected=False, updated_at=review["updated_at"])
        _atomic_json(run_dir / "output" / "research_workspace.json", data)
    return {"run_id": run_id, "review": review, "workspace": workspace_payload(runs_dir, run_id)}


def export_method_csv(runs_dir: Path, run_id: str, paper_ids: list[str] | None = None) -> str:
    matrix = method_comparison(runs_dir, run_id, paper_ids)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["论文", "字段", "状态", "字段要点", "原文摘录", "页码", "原文链接", "人工备注", "用户论断",
                     "实验配置关联", "配置线索编号", "跨论文比较说明"])
    for paper in matrix["papers"]:
        for field in FIELDS:
            value = paper["fields"][field["key"]]
            candidate, review = value["candidate"] or {}, value["review"] or {}
            notices = [pair["notice"] for pair in matrix["comparability"]["pairs"]
                       if paper["paper_id"] in {pair["left_paper_id"], pair["right_paper_id"]}]
            row = [paper["title"], field["label"], value["status"], candidate.get("value", ""),
                   candidate.get("quote", candidate.get("text", "")), candidate.get("page", ""),
                   candidate.get("pdf_url", ""), review.get("note", ""), review.get("claim", ""),
                   "同句线索，待人工确认" if value["experiment_context_ids"] else "尚未关联实验配置",
                   "; ".join(value["experiment_context_ids"]), "；".join(dict.fromkeys(notices)) or
                   "单篇导出；字段属于论文级阅读候选，具体实验配置仍需核对。"]
            # Prevent a note/title from becoming a spreadsheet formula on import.
            writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row])
    return "\ufeff" + stream.getvalue()
