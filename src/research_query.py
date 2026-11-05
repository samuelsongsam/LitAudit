"""Validated, portable research constraints and transparent metadata checks."""
from __future__ import annotations

from datetime import date
import re
from typing import Any


ACTIVE_SEARCH_SOURCES = ("arxiv", "openalex")
_RETIRED_SEARCH_SOURCE = "semantic_scholar"

PUBLICATION_TYPES = {
    "": "any", "any": "any", "all": "any", "全部": "any", "不限": "any",
    "journal": "journal", "journalarticle": "journal", "期刊": "journal", "期刊论文": "journal",
    "conference": "conference", "会议": "conference", "会议论文": "conference",
    "preprint": "preprint", "预印本": "preprint",
    "review": "review", "综述": "review", "综述论文": "review",
}
TERM_EXPANSIONS = {
    "时间序列": "time series", "预测": "forecasting prediction", "异常检测": "anomaly detection",
    "图神经网络": "graph neural network", "图像分割": "image segmentation", "医学影像": "medical imaging",
    "遥感": "remote sensing", "小样本": "few-shot learning", "随机对照": "randomized controlled trial",
    "临床试验": "clinical trial", "糖尿病": "diabetes", "蛋白质": "protein", "药物发现": "drug discovery",
    "检索增强": "retrieval augmented generation", "多智能体": "multi-agent", "智能体": "agent",
    "文本分类": "text classification", "因果推断": "causal inference", "对比学习": "contrastive learning",
    "深度学习": "deep learning", "迁移学习": "transfer learning", "强化学习": "reinforcement learning",
    "联邦学习": "federated learning", "故障诊断": "fault diagnosis", "推荐系统": "recommendation system",
    "递归式自我改进": "recursive self-improvement", "递归自我改进": "recursive self-improvement",
}


def validate_search_supplement(value: Any = None) -> dict:
    """Validate an opt-in budget; an omitted/empty value keeps one-page search."""
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        raise ValueError("补充检索预算必须为JSON对象")
    if set(value) - {"pages_per_query", "max_requests", "sources"}:
        raise ValueError("存在未知补充检索预算字段")
    result = {}
    for key, default, upper in [("pages_per_query", 1, 3), ("max_requests", 6, 12)]:
        raw = value.get(key, default)
        if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= upper:
            raise ValueError(f"{key}必须为1到{upper}的整数")
        result[key] = raw
    sources = _active_sources(value.get("sources", list(ACTIVE_SEARCH_SOURCES)))
    if not sources:
        return {}
    result["sources"] = sources
    return result


def _active_sources(value: Any) -> list[str]:
    accepted = (*ACTIVE_SEARCH_SOURCES, _RETIRED_SEARCH_SOURCE)
    if (not isinstance(value, list) or not value or len(value) > len(accepted)
            or any(not isinstance(source, str) or source not in accepted for source in value)):
        raise ValueError("检索来源应为 arXiv、OpenAlex 的非空列表")
    return list(dict.fromkeys(source for source in value if source in ACTIVE_SEARCH_SOURCES))


def validate_search_sources(value: Any = None) -> list[str] | None:
    """An explicit non-empty source list can retry failed providers only."""
    if value is None:
        return None
    sources = _active_sources(value)
    if not sources:
        raise ValueError("所选检索来源已停用，请选择 arXiv 或 OpenAlex")
    return sources


def validate_constraints(value: Any = None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("研究条件必须为JSON对象")
    allowed = {"year_from", "year_to", "research_object", "method", "publication_type"}
    if set(value) - allowed:
        raise ValueError("存在未知研究条件：" + ", ".join(sorted(set(value) - allowed)))
    result = {}
    for key in ("year_from", "year_to"):
        raw = value.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, bool) or not isinstance(raw, (str, int)) or not re.fullmatch(r"\d{4}", str(raw)):
            raise ValueError("年份必须是四位整数")
        year = int(raw)
        if not 1800 <= year <= date.today().year + 1:
            raise ValueError("年份超出可接受范围")
        result[key] = year
    if result.get("year_from", 0) > result.get("year_to", 9999):
        raise ValueError("起始年份不能大于结束年份")
    for key in ("research_object", "method"):
        raw = value.get(key)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str) or len(raw) > 500:
            raise ValueError("研究对象和方法必须是不超过500字的文本")
        text = " ".join(raw.split()).strip()
        if text:
            result[key] = text
    raw_type = value.get("publication_type")
    if raw_type is None or raw_type == "":
        raw_type = "any"
    if not isinstance(raw_type, str) or raw_type.lower().strip() not in PUBLICATION_TYPES:
        raise ValueError("文献类型应为any、journal、conference、preprint或review")
    kind = PUBLICATION_TYPES[raw_type.lower().strip()]
    if kind != "any":
        result["publication_type"] = kind
    return result


def expand_terms(text: str) -> str:
    additions = [english for term, english in TERM_EXPANSIONS.items() if term in (text or "")]
    return " ".join(dict.fromkeys([text.strip(), *additions])).strip()


def research_text(question: str | None, constraints: dict | None = None) -> str:
    conditions = validate_constraints(constraints)
    return expand_terms(" ".join(v for v in [question or "", conditions.get("research_object"), conditions.get("method")] if v))


def metadata_check(hit: Any, constraints: dict | None) -> dict:
    conditions = validate_constraints(constraints)
    checks, explanations = {}, []
    year = getattr(hit, "year", None)
    if conditions.get("year_from") or conditions.get("year_to"):
        if not isinstance(year, int) or isinstance(year, bool):
            checks["year"] = "unknown"
            explanations.append("来源未给出可核验年份，待确认时间范围")
        elif year < conditions.get("year_from", 0) or year > conditions.get("year_to", 9999):
            checks["year"] = "mismatch"
            explanations.append("来源年份不符合指定范围")
        else:
            checks["year"] = "matched"
    kind = conditions.get("publication_type")
    if kind:
        types = {str(v).lower().replace("_", "").replace("-", "").replace(" ", "") for v in getattr(hit, "publication_types", [])}
        known = set()
        if types & {"journal", "journalarticle"}: known.add("journal")
        if types & {"conference", "conferencepaper", "proceedingsarticle"}: known.add("conference")
        if types & {"review", "systematicreview", "metaanalysis"}: known.add("review")
        if types & {"preprint", "postedcontent"}: known.add("preprint")
        if kind in known:
            checks["publication_type"] = "matched"
        elif not known or (kind == "review" and known & {"journal", "conference"}) or (kind in {"journal", "conference"} and known == {"review"}):
            # An article's venue type does not establish whether it is a review.
            checks["publication_type"] = "unknown"
            explanations.append("来源元数据不能确认指定文献类型，待人工复核")
        else:
            checks["publication_type"] = "mismatch"
            explanations.append("来源文献类型不符合指定条件")
    return {"status": "mismatch" if "mismatch" in checks.values() else "unknown" if "unknown" in checks.values() else "matched",
            "checks": checks, "checked": bool(checks), "scope": "year_and_publication_metadata",
            "query_only_fields": [key for key in ("research_object", "method") if conditions.get(key)],
            "notes": explanations}
