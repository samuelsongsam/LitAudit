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


def screen_title_abstract(title: str | None, abstract: str | None, year: int | None = None) -> ScreenResult:
    """规则筛选标题+摘要。明显符合 include，明显排除 exclude，否则 pending。"""
    text = _blob(title, abstract)
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
