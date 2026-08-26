"""One-shot upgrade: attach PDF page locators to existing claims/evidence.

This script is the audit trail for the 2026-08-26 full-text partial verification.
It is idempotent: it overwrites the same IDs rather than duplicating them.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    evidence = [
        {
            "evidence_id": "evidence-001",
            "claim_id": "claim-001",
            "paper_id": "paper-001",
            "snippet": "We present PaperQA, a RAG agent for answering questions over the scientific literature. PaperQA is an agent that performs information retrieval across full-text scientific articles, assesses the relevance of sources and passages, and uses RAG to provide answers.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2312.07559v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-002",
            "claim_id": "claim-002",
            "paper_id": "paper-001",
            "snippet": "we also introduce LitQA, a more complex benchmark that requires retrieval and synthesis of information from full-text scientific papers across the literature.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2312.07559v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-003",
            "claim_id": "claim-003",
            "paper_id": "paper-003",
            "snippet": "We present SCIMON, a modeling framework that uses retrieval of inspirations from past scientific papers, and explicitly optimizes for novelty by iteratively comparing to prior papers and updating idea suggestions until sufficient novelty is achieved.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2305.14259v7",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-004",
            "claim_id": "claim-004",
            "paper_id": "paper-003",
            "snippet": "Comprehensive evaluations reveal that GPT-4 tends to generate ideas with overall low technical depth and novelty, while our methods partially mitigate this issue.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2305.14259v7",
            },
            "verdict": "supports",
            "confidence": "medium",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-005",
            "claim_id": "claim-005",
            "paper_id": "paper-001",
            "snippet": "We modified PubMedQA to remove the provided context (so it is closed-book) and found PaperQA beats GPT-4 by 30 points (57.9% to 86.3%).",
            "locator": {
                "page": 2,
                "section": "introduction",
                "url_anchor": "https://arxiv.org/abs/2312.07559v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-006",
            "claim_id": "claim-006",
            "paper_id": "paper-006",
            "snippet": "Retrieval-augmented generation (RAG) aims to reduce hallucinations by grounding responses in external context, yet large language models (LLMs) still frequently introduce unsupported information or contradictions even when provided with relevant context.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2505.04847v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-007",
            "claim_id": "claim-007",
            "paper_id": "paper-007",
            "snippet": "However, self-citing LLMs often struggle to match the required format, refer to non-existent sources, and fail to faithfully reflect LLMs' context usage throughout the generation.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2406.13663v4",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-008",
            "claim_id": "claim-008",
            "paper_id": "paper-001",
            "snippet": "Retrieval-Augmented Generation (RAG) models have been proposed to reduce hallucinations and provide provenance for how an answer was generated.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2312.07559v2",
            },
            "verdict": "context_only",
            "confidence": "medium",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-009",
            "claim_id": "claim-008",
            "paper_id": "paper-006",
            "snippet": "large language models (LLMs) still frequently introduce unsupported information or contradictions even when provided with relevant context.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2505.04847v2",
            },
            "verdict": "contradicts",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-010",
            "claim_id": "claim-008",
            "paper_id": "paper-007",
            "snippet": "self-citing LLMs often struggle to match the required format, refer to non-existent sources, and fail to faithfully reflect LLMs' context usage throughout the generation.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2406.13663v4",
            },
            "verdict": "contradicts",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-011",
            "claim_id": "claim-002",
            "paper_id": "paper-001",
            "snippet": "From Table 2 we see that PaperQA outperforms all competing models and products, and is on par with that of human experts with access to the internet.",
            "locator": {
                "page": 7,
                "section": "results",
                "url_anchor": "https://arxiv.org/pdf/2312.07559v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-012",
            "claim_id": "claim-005",
            "paper_id": "paper-001",
            "snippet": "We have an underlying assumption from this that the information in the underlying papers is correct, which may not hold.",
            "locator": {
                "page": 9,
                "section": "limitations",
                "url_anchor": "https://arxiv.org/pdf/2312.07559v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-013",
            "claim_id": "claim-008",
            "paper_id": "paper-001",
            "snippet": "We measured the hallucination rate of citations for recent LLMs to be between 40-60%, whereas we were not able to find a single hallucinated citation in PaperQA's responses.",
            "locator": {
                "page": 10,
                "section": "conclusion",
                "url_anchor": "https://arxiv.org/pdf/2312.07559v2",
            },
            "verdict": "context_only",
            "confidence": "medium",
            "extraction_status": "verified",
        },
        {
            "evidence_id": "evidence-014",
            "claim_id": "claim-006",
            "paper_id": "paper-006",
            "snippet": "they do not fully eliminate hallucinations, as LLMs often introduce details unsupported by retrieved contexts, misrepresent information, or generate outright contradictions",
            "locator": {
                "page": 1,
                "section": "introduction",
                "url_anchor": "https://arxiv.org/pdf/2505.04847v2",
            },
            "verdict": "supports",
            "confidence": "high",
            "extraction_status": "verified",
        },
    ]
    dump_jsonl(DATA / "evidence.jsonl", evidence)

    claims = load_jsonl(DATA / "claims.jsonl")
    claim_updates = {
        "claim-001": "本地 PDF 第 1 页摘要直接支持 PaperQA 作为科学文献全文 RAG agent 的描述。",
        "claim-002": "本地 PDF 第 1 页摘要与第 7 页 Table 2 结果段支持 LitQA 任务定义，并报告 PaperQA 与人类专家相当。",
        "claim-003": "本地 PDF 第 1 页摘要直接支持 SciMON 的论文灵感检索、迭代比较和新颖性优化描述。",
        "claim-004": "本地 PDF 第 1 页摘要报告低技术深度/新颖性及部分缓解，但没有在本轮抽取完整实验表数值，保持 partial。",
        "claim-005": "PDF 第 2 页报告单篇 PubMedQA closed-book 增益，第 9 页 Limitations 声明底层论文未必正确；任务异质，不能推出普遍优越性，保持 pending。",
        "claim-006": "反向检索论文 PDF 第 1 页摘要和引言直接报告相关上下文下仍有 unsupported information/contradictions。",
        "claim-007": "反向检索论文 PDF 第 1 页摘要直接报告不存在来源和上下文忠实性失败。",
        "claim-008": "PaperQA PDF 提供单系统正向报告，paper-006/007 PDF 报告相关上下文下仍有无支持信息、矛盾和归因失败；任务不统一，必须保持 pending。",
    }
    for row in claims:
        if row["claim_id"] in claim_updates:
            row["decision_reason"] = claim_updates[row["claim_id"]]
    dump_jsonl(DATA / "claims.jsonl", claims)

    decisions = [
        {
            "claim_id": "claim-001",
            "status": "supported",
            "evidence_ids": ["evidence-001"],
            "reason": "PDF 第 1 页摘要直接支持 PaperQA 的科学文献全文检索 RAG agent 描述；verified 只覆盖该摘录，不是整篇审阅完毕。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-002",
            "status": "supported",
            "evidence_ids": ["evidence-002", "evidence-011"],
            "reason": "PDF 第 1 页摘要与第 7 页结果段支持 LitQA 全文跨文献检索任务及与人类专家相当的报告。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-003",
            "status": "supported",
            "evidence_ids": ["evidence-003"],
            "reason": "PDF 第 1 页摘要直接支持 SciMON 的论文灵感检索、迭代比较和新颖性优化描述。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-004",
            "status": "partial",
            "evidence_ids": ["evidence-004"],
            "reason": "PDF 第 1 页摘要报告该观察和部分缓解，但本轮未抽取完整实验设置与数值，保持 partial。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-005",
            "status": "pending",
            "evidence_ids": ["evidence-005", "evidence-012"],
            "reason": "单篇 closed-book 增益与 Limitations 并存，不能支持跨任务普遍优越性。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-006",
            "status": "supported",
            "evidence_ids": ["evidence-006", "evidence-014"],
            "reason": "PDF 第 1 页摘要和引言直接报告相关上下文下仍有无支持信息或矛盾；仅作为通用 RAG 风险。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-007",
            "status": "supported",
            "evidence_ids": ["evidence-007"],
            "reason": "PDF 第 1 页摘要直接报告不存在来源和上下文忠实性失败；仅作为通用 RAG 归因风险。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "claim_id": "claim-008",
            "status": "pending",
            "evidence_ids": ["evidence-008", "evidence-009", "evidence-010", "evidence-013"],
            "reason": "正向 PDF 只说明 RAG 目标/单篇报告，反向 PDF 报告 unsupported information、contradictions 和 attribution failures；冲突未解决。",
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
    ]
    dump_jsonl(DATA / "claim_decisions.jsonl", decisions)

    hits = [
        {
            "hit_id": "hit-001",
            "target_claim": "claim-008",
            "paper_id": "paper-006",
            "threat": "overlap",
            "threat_level": "high",
            "snippet": "large language models (LLMs) still frequently introduce unsupported information or contradictions even when provided with relevant context.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2505.04847v2",
            },
            "reason": "PDF 第 1 页摘要直接削弱“外部检索普遍提高可信度”的强断言；任务是通用 RAG，不是科学文献，因此威胁属于 overlap 而非 fatal。",
            "status": "verified",
            "reverse_query": "q-004",
        },
        {
            "hit_id": "hit-002",
            "target_claim": "claim-008",
            "paper_id": "paper-007",
            "threat": "overlap",
            "threat_level": "high",
            "snippet": "self-citing LLMs often struggle to match the required format, refer to non-existent sources, and fail to faithfully reflect LLMs' context usage throughout the generation.",
            "locator": {
                "page": 1,
                "section": "abstract",
                "url_anchor": "https://arxiv.org/abs/2406.13663v4",
            },
            "reason": "PDF 第 1 页摘要报告来源不存在和上下文归因失败，直接削弱“带引用即具备可追溯性”的强断言；任务是通用 QA，威胁为 overlap。",
            "status": "verified",
            "reverse_query": "q-004",
        },
    ]
    dump_jsonl(DATA / "falsification.jsonl", hits)

    screening = load_jsonl(DATA / "screening_log.jsonl")
    extra = [
        {
            "screening_id": "screen-013",
            "paper_id": "paper-001",
            "stage": "full_text",
            "decision": "include",
            "reason_code": "in_scope_pdf_partial",
            "reason": "本地 arXiv PDF 20 页可提取。已核验第 1、2、7、9、10 页指定摘录；任务仍是科学文献全文 RAG 问答。未完成逐页审阅。",
            "checked_fields": ["title", "abstract", "pdf_pages"],
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "screening_id": "screen-014",
            "paper_id": "paper-003",
            "stage": "full_text",
            "decision": "include",
            "reason_code": "adjacent_auto_science_pdf_partial",
            "reason": "本地 arXiv PDF 21 页可提取。已核验第 1 页摘要摘录；任务仍是科学想法生成，与文献问答相邻但不等同。未完成逐页审阅。",
            "checked_fields": ["title", "abstract", "pdf_pages"],
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "screening_id": "screen-015",
            "paper_id": "paper-006",
            "stage": "full_text",
            "decision": "exclude",
            "reason_code": "risk_paper_general_rag_pdf_partial",
            "reason": "本地 arXiv PDF 13 页可提取。第 1 页和第 7 页 Limitations 确认任务是通用 summarization/QA/data-to-text faithfulness，不是科学文献任务；保持 exclude，保留反证据。",
            "checked_fields": ["title", "abstract", "pdf_pages"],
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
        {
            "screening_id": "screen-016",
            "paper_id": "paper-007",
            "stage": "full_text",
            "decision": "exclude",
            "reason_code": "risk_paper_general_qa_pdf_partial",
            "reason": "本地 arXiv PDF 17 页可提取。第 1 页确认任务是通用 QA 答案归因，不是科学文献任务；保持 exclude，保留反证据。",
            "checked_fields": ["title", "abstract", "pdf_pages"],
            "reviewer": "litaudit",
            "reviewed_at": "2026-08-26",
            "scope_version": "v0.1",
        },
    ]
    existing_ids = {row["screening_id"] for row in screening}
    for row in extra:
        if row["screening_id"] not in existing_ids:
            screening.append(row)
    dump_jsonl(DATA / "screening_log.jsonl", screening)

    cards = load_jsonl(DATA / "paper_cards.jsonl")
    card_updates = {
        "paper-001": {
            "parse_status": "pdf_partial_verified",
            "parse_error": "已核验 PDF 第 1、2、7、9、10 页指定摘录；未完成 20 页逐页审阅，不得视为全文已读完。",
            "fields": {
                "task": "科学文献全文上的问题回答与检索/综合。",
                "method": "RAG agent；对全文文章执行信息检索，评估来源和段落相关性后生成回答。",
                "data": "LitQA（50 题，生物医学，2021-09 之后文献）；PubMedQAblind、MedQA、BioASQ 子样本。",
                "metrics": "PDF 核验：LitQA 上 PaperQA accuracy 69.5%/precision 87.9%（4 次，第 7 页 Table 2），人类 66.8%/87.9%，GPT-4 33.4%/50.6%。PubMedQAblind 上 GPT-4 57.9%、PaperQA 86.3%（第 2 页与第 9 页 Table 5）。",
                "claims": None,
                "limitations": "第 9 页：假设被引论文内容正确，期刊名和引用数不是可靠质量信号；LitQA 题目可能过时，应限制文献截止 2023-09-15；多 agent prompt 未证明最优。",
            },
        },
        "paper-003": {
            "parse_status": "pdf_partial_verified",
            "parse_error": "已核验 PDF 第 1 页摘要摘录；未完成 21 页逐页审阅，未抽取完整实验表。",
            "fields": {
                "task": "从科学文献生成新科学想法，并评价想法的新颖性。",
                "method": "从过去科学论文检索 inspiration；迭代比较先前论文并更新 idea suggestions，显式优化 novelty。",
                "data": "过去科学论文；本轮未抽取完整数据集名称与样本量。",
                "metrics": "PDF 第 1 页摘要报告 GPT-4 生成想法的技术深度和新颖性整体较低，所提方法部分缓解；具体表内数值待后续核验。",
                "claims": None,
                "limitations": "与首期主问题的文献问答任务相邻但不等同；当前只核验摘要页，不是全文结论。",
            },
        },
        "paper-006": {
            "parse_status": "pdf_partial_verified",
            "parse_error": "已核验 PDF 第 1 页摘要/引言和第 7 页 Limitations；任务仍为通用 RAG，保持 exclude。",
            "fields": {
                "task": "通用 RAG 摘要、问答和 data-to-text 的 faithfulness 基准。",
                "method": "HHEM 幻觉检测模型和 FaithJudge LLM-as-a-judge 评测框架。",
                "data": "人工标注幻觉示例；FaithBench 与 RAGTruth 子集。",
                "metrics": "PDF 关注 hallucination rate 与和人工标注的一致性；本轮未抽取排行榜全表。",
                "claims": None,
                "limitations": "第 7 页：评价只关注 faithfulness，不评价摘要/答案整体质量或有用性。用于风险背景和反证据，不用于首期纳入结论。",
            },
        },
        "paper-007": {
            "parse_status": "pdf_partial_verified",
            "parse_error": "已核验 PDF 第 1 页摘要；未完成 17 页逐页审阅。任务仍为通用 QA，保持 exclude。",
            "fields": {
                "task": "通用 QA 中的答案来源归因和可验证性。",
                "method": "MIRAGE 使用模型内部信息，将上下文敏感答案 token 与影响其预测的检索文档配对。",
                "data": "多语言 extractive QA 和 open-ended QA。",
                "metrics": "PDF 摘要报告与人工答案归因的高一致性，以及开放问答中与 self-citation 相当的 citation quality/efficiency；本轮未抽取完整数值表。",
                "claims": None,
                "limitations": "不是科学文献任务；用于风险背景和反证据，不用于首期纳入结论。",
            },
        },
    }
    for card in cards:
        extra_fields = card_updates.get(card["paper_id"])
        if extra_fields:
            card.update(extra_fields)
    dump_jsonl(DATA / "paper_cards.jsonl", cards)

    question_notes = {
        "eval-001": "金标准来自已核验的 PaperQA PDF 摘录；全文逐页审阅尚未完成。",
        "eval-002": "任务属于首期范围允许的相邻自动科研信息整合；不得与科学问答结果混为一谈。",
        "eval-003": "风险金标准来自反向检索论文 PDF；两篇因任务非科研文献而排除，但保留为反证据来源。",
    }
    questions = load_jsonl(DATA / "gold_standard" / "questions.jsonl")
    for row in questions:
        if row["question_id"] in question_notes:
            row["notes"] = question_notes[row["question_id"]]
    dump_jsonl(DATA / "gold_standard" / "questions.jsonl", questions)
    print("upgraded evidence", len(evidence), "screening", len(screening), "cards", len(cards))


if __name__ == "__main__":
    main()
