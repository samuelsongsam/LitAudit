from __future__ import annotations

import re
from dataclasses import dataclass

from src.schema import PaperDecision

LLM = (
    "language model",
    "language models",
    " llm",
    "llms",
    "gpt-3",
    "gpt-4",
    "generative agent",
)
SCIENCE = (
    "scientific literature",
    "scientific papers",
    "scientific research",
    "scientific knowledge",
    "scientific question",
    "scientific idea",
    "scientific inspiration",
    "scientific articles",
    "literature review",
    "science qa",
    "litqa",
    "scholarly",
    "past scientific",
    "research on scientific",
    "full-text scientific",
    "full text scientific",
)
SCIENCE_NEGATION = (
    "rather than scientific",
    "rather than science",
    "not scientific literature",
    "not science question",
    "general downstream tasks rather than",
)
YEAR_MIN = 2019
YEAR_MAX = 2026
TOPIC_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "into", "using", "use",
    "modern", "specific", "technical", "details", "detail", "analysis", "including",
    "include", "comparison", "performance", "architecture", "research", "paper",
}


@dataclass(frozen=True)
class ScreenResult:
    decision: PaperDecision
    reason_code: str
    reason: str


def _blob(title: str | None, abstract: str | None) -> str:
    return f"{title or ''} {abstract or ''}".lower()


def _has_any(text: str, needles: tuple[str, ...] | list[str]) -> bool:
    return any(needle in text for needle in needles)


def _has_rag(text: str) -> bool:
    return bool(
        re.search(r"\brag\b", text)
        or "retrieval-augmented" in text
        or "retrieval augmented" in text
        or "retrieval of" in text
        or "information retrieval" in text
    )


def _has_agent(text: str) -> bool:
    return bool(re.search(r"\bagent\b", text) or "tool-using" in text or "toolformer" in text)


def _has_llm(text: str) -> bool:
    padded = f" {text} "
    return _has_any(padded, LLM) or "large language" in text


def _has_science(text: str) -> bool:
    if _has_any(text, SCIENCE_NEGATION):
        return False
    return _has_any(text, SCIENCE)


def _topic_terms(query: str | None) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{2,}", query or "")
        if token.lower() not in TOPIC_STOP
    }


def screen_title_abstract(
    title: str | None,
    abstract: str | None,
    year: int | None = None,
    *,
    research_query: str | None = None,
) -> ScreenResult:
    """规则筛选标题+摘要。明显符合 include，明显排除 exclude，否则 pending。"""
    text = _blob(title, abstract)
    if research_query:
        terms = _topic_terms(research_query)
        matched = {term for term in terms if term in text}
        gpu_topic = "gpu" in terms and bool(terms & {"hopper", "ada", "rdna", "cdna", "microarchitecture"})
        if gpu_topic:
            model_signal = any(term in text for term in ("hopper", "h100", "ada", "lovelace", "rdna", "cdna", "mi200", "mi300"))
            title_text = (title or "").lower()
            title_architecture_signal = any(
                term in title_text
                for term in (
                    "gpu architecture", "hopper architecture", "microarchitect", "instruction set",
                    "global load", "memory architecture", "matrix accelerator", "automotive gpu",
                    "cuda tile", "kernel fusion",
                )
            )
            architecture_signal_count = sum(
                term in text
                for term in (
                    "microarchitect", "instruction set", " isa ", "cache", "memory hierarchy",
                    "tensor core", "compute unit", "shared memory", "distributed shared memory",
                    "tensor memory accelerator", " wgmma", " dpx",
                )
            )
            architecture_signal = title_architecture_signal or architecture_signal_count >= 2
            if model_signal and architecture_signal:
                return ScreenResult(
                    PaperDecision.include,
                    "custom_gpu_architecture_match",
                    "标题/摘要同时命中现代 GPU 型号与微架构、指令或存储层级信号。仅完成摘要级相关性筛选，尚未全文核验。",
                )
            if model_signal:
                return ScreenResult(
                    PaperDecision.pending,
                    "custom_gpu_model_only",
                    "标题/摘要命中目标 GPU 型号，但微架构技术信号不足，暂列待定。",
                )
            return ScreenResult(
                PaperDecision.exclude,
                "custom_gpu_application_only",
                "论文涉及 GPU 应用，但未命中本轮指定的现代 GPU 微架构型号。",
            )
        if len(matched) >= 2:
            return ScreenResult(
                PaperDecision.include,
                "custom_topic_match",
                "标题/摘要与本轮自定义研究主题有明确词项重叠。仅完成摘要级相关性筛选，尚未做全文与页码核验。",
            )
        if matched:
            return ScreenResult(
                PaperDecision.pending,
                "custom_topic_uncertain",
                "标题/摘要与本轮主题只有弱匹配，暂列待定，需进一步阅读摘要或全文。",
            )
        return ScreenResult(
            PaperDecision.exclude,
            "custom_topic_mismatch",
            "标题/摘要未显示与本轮自定义研究主题的直接相关性。",
        )
    if year is not None and (year < YEAR_MIN or year > YEAR_MAX):
        return ScreenResult(
            PaperDecision.exclude,
            "out_of_window",
            f"出版年 {year} 不在 {YEAR_MIN}–{YEAR_MAX} 首期时间窗。",
        )
    if _has_any(text, ("wikipedia-like", "wikipedia pages", "freshwiki", "write wikipedia")):
        return ScreenResult(
            PaperDecision.exclude,
            "general_web_writing",
            "任务是 Wikipedia/互联网长文写作，不是科学文献综述或科学问答。",
        )
    if _has_any(text, ("eli5", "reddit users", " reddit")):
        return ScreenResult(
            PaperDecision.exclude,
            "general_web_qa",
            "任务是通用网页/社区问答，不是科学文献任务。",
        )
    llm = _has_llm(text)
    retrieval = _has_rag(text) or _has_agent(text)
    science = _has_science(text)

    if _has_any(text, ("calculator", "translation system", "calendar")) and not science:
        return ScreenResult(
            PaperDecision.exclude,
            "general_tools",
            "通用工具调用，没有科学文献综述或科学问答任务。",
        )

    if not science and (
        "faithfulness" in text
        or "attribution" in text
        or "unsupported information" in text
        or "self-citing" in text
    ):
        return ScreenResult(
            PaperDecision.exclude,
            "general_rag_risk",
            "通用 RAG 可信度/归因评测，不是科学文献任务；保留为反证据边界，不纳入主问题。",
        )
    if llm and retrieval and science:
        return ScreenResult(
            PaperDecision.include,
            "in_scope_live_abstract",
            "标题/摘要显示 LLM 与检索或 agent 用于科学文献或科研信息任务。仅摘要规则筛选，尚未全文核验，不能把论断标为 supported。",
        )
    if not llm and not retrieval:
        return ScreenResult(
            PaperDecision.exclude,
            "not_llm_retrieval",
            "不是 LLM 驱动，或没有外部检索/agent 任务。",
        )
    if llm and retrieval and not science:
        return ScreenResult(
            PaperDecision.exclude,
            "general_qa_not_scientific",
            "虽有 LLM/RAG，但任务不是科学文献综述或科学问答。",
        )
    return ScreenResult(
        PaperDecision.pending,
        "scope_uncertain",
        "标题/摘要不足以判断是否落入首期范围，标为 pending。不编造纳入结论，也不生成页码级证据。",
    )
