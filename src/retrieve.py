from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urlparse
from xml.etree import ElementTree as ET

from src.http_fetch import PROVIDER_TIMEOUT, FetchResult, http_get
from src.provider_runtime import connection_diagnostic, provider_auth_headers
from src.schema import RetrievalRun, SearchQuery
from src.research_query import (ACTIVE_SEARCH_SOURCES, validate_constraints, validate_search_supplement, validate_search_sources,
                                research_text, expand_terms, metadata_check)

FetchFn = Callable[..., FetchResult]

DEFAULT_ARXIV = 'all:"retrieval-augmented" AND all:agent AND (all:scientific OR all:literature)'
DEFAULT_OPENALEX = "large language model retrieval augmented scientific literature"
RISK_ARXIV = 'all:RAG AND (all:faithfulness OR all:"citation hallucination" OR all:attribution) AND all:LLM'
STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "was",
    "not",
    "use",
    "using",
    "into",
    "than",
    "can",
    "whether",
}
# Chinese terms translated into provider queries (exclude intent-only words like 综述/经典).
ZH_SEARCH_MAP = (
    ("现代GPU微架构", "modern GPU microarchitecture"),
    ("GPU微架构", "GPU microarchitecture"),
    ("微架构", "microarchitecture"),
    ("性能对比", "performance comparison"),
    ("架构图", "architecture"),
    ("指令集", "instruction set"),
    ("技术细节", "architecture details"),
    ("理性", "reason rationality"),
    ("自由", "freedom liberty"),
    ("绝对精神", "absolute spirit"),
    ("哲学", "philosophy"),
    ("核心概念", "core concepts"),
    ("当代", "contemporary"),
    ("检索增强", "retrieval-augmented"),
    ("可追溯", "traceability provenance"),
    ("科学问答", "scientific question answering"),
    ("智能体", "agent"),
    ("多智能体", "multi-agent"),
    ("多代理", "multi-agent"),
    ("辩论", "debate"),
    ("框架设计", "framework design"),
    ("逻辑推理", "logical reasoning"),
    ("幻觉", "hallucination"),
    ("证据", "evidence"),
    ("科研", "scientific research"),
    ("大模型", "large language model"),
    ("问答", "question answering"),
)
GENERIC_QUERY_STOP = STOP | {
    "compare", "compared", "comparing", "comparison", "versus", "vs",
    "literature",
    "review",
    "classical",
    "survey",
    "method",
    "methods",
    "design",
    "theory",
    "paper",
    "papers",
    "principles",
    "reasoning",
    "framework",
    "logic",
    "mathematical",
    "classic",
    "overview",
    "surveying",
}
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
_ARXIV_REFERENCE = re.compile(r"(\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", re.I)
_RECURSIVE_SELF_IMPROVEMENT = re.compile(r"\brecursive[\s-]+self[\s-]+improvement\b", re.I)


@dataclass
class LiveHit:
    source: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi_or_arxiv: str | None
    url: str
    abstract: str | None
    dedup_key: str
    source_id: str | None = None
    open_access_pdf_url: str | None = None
    citation_count: int | None = None
    reference_count: int | None = None
    fields_of_study: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)
    tldr: str | None = None
    semantic_score: float | None = None
    lexical_score: float | None = None
    ranking_score: float | None = None
    semantic_scholar_id: str | None = None
    matched_sources: list[str] = field(default_factory=list)
    source_records: list[dict] = field(default_factory=list)
    constraint_check: dict = field(default_factory=dict)


@dataclass
class QuerySpec:
    query_id: str
    source: str
    query: str
    purpose: str
    constraints: dict = field(default_factory=dict)


@dataclass
class SearchBundle:
    queries: list[SearchQuery]
    runs: list[RetrievalRun]
    hits: list[LiveHit]
    notes: list[str] = field(default_factory=list)
    citation_graph: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    filter_report: dict = field(default_factory=dict)
    search_budget: dict = field(default_factory=dict)


def retrieval_status(http_status: int | None, error: str | None = None) -> str:
    if http_status == 429:
        return "rate_limited"
    if http_status == 200 and not error:
        return "success"
    return "failed"


def expand_question(question: str) -> str:
    text = (question or "").strip()
    # Remove conversational instructions before sending the research topic to providers.
    text = re.sub(
        r"(?:请)?(?:检索|搜索|查找|找些?|寻找|帮我看看|开始检索)\s*",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(?:输出|返回|给出)(?:论文列表|研究分支|争议点|结果|综述).*?$|(?:比较|对比|限定|优先)(?:人工审查|有无检索增强|近五年|CCFA类会议论文|论文|来源).*?(?=，|。|$)",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"[，。；;、]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    extras = [english for chinese, english in ZH_SEARCH_MAP if chinese in text]
    if extras:
        text = f"{text} {' '.join(extras)}"
    return expand_terms(text)


def _distinctive_tokens(text: str) -> list[str]:
    recursive_improvement = _RECURSIVE_SELF_IMPROVEMENT.search(text or "")
    tokens: list[str] = []
    if recursive_improvement:
        tokens.append("recursive self-improvement")
        text = _RECURSIVE_SELF_IMPROVEMENT.sub(" ", text)
    raw = (text or "").strip().lower()
    if "multi-agent" in raw or "multi agent" in raw:
        tokens.append("multi-agent")
    if "retrieval-augmented" in raw or "retrieval augmented" in raw:
        tokens.append("retrieval-augmented")
    for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text or ""):
        lowered = token.lower()
        if lowered in GENERIC_QUERY_STOP or lowered in tokens:
            continue
        if recursive_improvement and lowered == "rsi":
            continue
        if lowered == "multi" and "multi-agent" in tokens:
            continue
        if lowered == "agent" and "multi-agent" in tokens:
            continue
        tokens.append(lowered)
        if len(tokens) >= 6:
            break
    return tokens


def to_arxiv_query(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    if "all:" in raw or "ti:" in raw:
        return raw
    if _RECURSIVE_SELF_IMPROVEMENT.search(raw):
        return 'all:"recursive self-improvement"'
    low = raw.lower()
    if "gpu" in low and any(term in low for term in ("microarchitecture", "hopper", "ada", "rdna", "cdna")):
        return '(all:gpu OR all:nvidia OR all:amd) AND (all:hopper OR all:h100 OR all:ada OR all:rdna OR all:cdna)'
    if ("multi-agent" in low or "multi agent" in low or "multiagent" in low) and "debate" in low:
        return '(all:"multi-agent" OR all:multiagent OR all:"multi agent") AND (all:debate OR all:"llm debate")'
    tokens = _distinctive_tokens(raw)
    if "retrieval-augmented" in low and ("agent" in tokens or "rag" in tokens):
        return 'all:"retrieval-augmented" AND (all:agent OR all:rag OR all:"question answering")'
    if len(tokens) >= 2:
        return f"all:{tokens[0]} AND all:{tokens[1]}"
    if tokens:
        return f"all:{tokens[0]}"
    return ""


def to_arxiv_fallback_query(text: str) -> str:
    raw = expand_question(text or "")
    if _RECURSIVE_SELF_IMPROVEMENT.search(raw):
        return 'all:"recursive self-improvement"'
    low = raw.lower()
    if ("multi-agent" in low or "multi agent" in low or "multiagent" in low) and "debate" in low:
        return '(all:"multi-agent" OR all:multiagent) AND all:debate'
    tokens = _distinctive_tokens(raw)
    if len(tokens) >= 2:
        return f"all:{tokens[0]} AND all:{tokens[1]}"
    if tokens:
        return f"all:{tokens[0]}"
    return ""


def to_provider_query(text: str) -> str:
    """Keep a concise English query for providers whose search endpoints handle natural text."""
    stop = GENERIC_QUERY_STOP | {
        "modern", "specific", "technical", "details", "detail", "including", "include",
        "analysis", "deep", "comparison", "such", "like", "architecture",
    }
    tokens: list[str] = []
    for token in _distinctive_tokens(text or ""):
        if token in stop or token in tokens:
            continue
        tokens.append(token)
        if len(tokens) >= 8:
            break
    return " ".join(tokens)


def comparison_name_candidates(question: str | None) -> list[str]:
    """Recognize explicit named comparison targets as query hints, not entities.

    This conservative heuristic handles user-written mixed-case abbreviations
    and hyphenated model names. It deliberately does not invent target names
    for a generic comparison of methods and exposes every generated query.
    """
    text = question or ""
    if not re.search(r"比较|对比|\b(?:compare|comparing|comparison|versus|vs)\b", text, re.I):
        return []
    tokens = list(re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", text))
    names = []
    for index, token in enumerate(tokens):
        name = token.group()
        if sum(c.isupper() for c in name) < 2 or name.lower() in {"gpu", "cpu", "pdf", "ram", "vram", "llm", "llms"}:
            continue
        if index:
            previous = tokens[index-1]
            prefix = previous.group()
            if (text[previous.end():token.start()].isspace() and prefix[0].isupper()
                    and prefix[1:].islower() and prefix.lower() not in GENERIC_QUERY_STOP):
                name = prefix + " " + name
        if name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    return names[:2] if len(names) >= 2 else []


def build_query_plan(question: str | None, constraints: dict | None = None) -> list[QuerySpec]:
    conditions = validate_constraints(constraints)
    identifiers = list(dict.fromkeys(ARXIV_ID.findall(question or "")))[:10]
    if identifiers:
        # Identifiers supplied by the researcher are exact lookup instructions,
        # not scientific keywords. Metadata conditions are checked after fetch.
        return [QuerySpec("q-live-arxiv-identifiers", "arxiv", "id_list:"+",".join(identifiers),
                          "用户提供arXiv标识符的精确查找；其他条件按返回元数据复核", conditions)]
    english = expand_question(research_text(question, conditions))
    recursive_improvement = _RECURSIVE_SELF_IMPROVEMENT.search(english)
    user_arxiv = to_arxiv_query(english)
    provider_query = to_provider_query(english)
    specs = [QuerySpec("q-live-arxiv-user", "arxiv", user_arxiv or DEFAULT_ARXIV, "用户问题检索")] if question else [QuerySpec("q-live-arxiv", "arxiv", DEFAULT_ARXIV, "范围主检索")]
    specs.append(QuerySpec("q-live-openalex", "openalex", provider_query or english or DEFAULT_OPENALEX, "OpenAlex 扩展"))
    if question:
        # A complementary query preserves the complete object/method phrases;
        # the concise query above is useful for provider relevance search.
        phrases = research_text("", conditions) or " ".join(_distinctive_tokens(english)[2:6])
        english_phrases = re.findall(r"[A-Za-z][A-Za-z0-9+.-]*", phrases)
        if english_phrases:
            phrases = " ".join(dict.fromkeys(english_phrases))
        if recursive_improvement and phrases:
            phrases = to_provider_query(f"recursive self-improvement {phrases}")
        if phrases and phrases != provider_query:
            specs.append(QuerySpec("q-live-openalex-complement", "openalex", phrases,
                                   "互补检索：研究对象与方法／次级主题词"))
    if not question:
        specs.append(QuerySpec("q-live-risk", "arxiv", RISK_ARXIV, "反向风险检索"))
    # An AND query for two named methods finds comparison studies but can miss
    # the original method papers. Keep the joint query and add independent
    # title queries; these are transparent candidates, not paper identity claims.
    for index, name in enumerate(comparison_name_candidates(question), 1):
        if recursive_improvement and name.casefold() == "rsi":
            continue
        specs.append(QuerySpec(f"q-live-arxiv-comparison-{index}", "arxiv", f'ti:"{name}"',
                               "比较对象的独立题名补充检索（名称启发式，需核对结果）"))
    for spec in specs:
        spec.constraints = conditions
        if spec.source == "arxiv" and (conditions.get("year_from") or conditions.get("year_to")):
            start = conditions.get("year_from", 1800)
            end = conditions.get("year_to", date.today().year + 1)
            spec.query = f"({spec.query}) AND submittedDate:[{start}01010000 TO {end}12312359]"
    return specs


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"^https?://(dx\.)?doi\.org/", "", value.strip(), flags=re.I)
    cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.I)
    return cleaned.lower() or None


def extract_arxiv_id(value: str | None, *, allow_bare: bool = True) -> str | None:
    """Recognize arXiv metadata without matching numbers inside unrelated identifiers."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().lower()
    doi = normalize_doi(value) or ""
    if value.startswith("arxiv:"):
        identifier = value.removeprefix("arxiv:").strip()
    elif doi.startswith("10.48550/arxiv."):
        identifier = doi.removeprefix("10.48550/arxiv.")
    else:
        try:
            parsed = urlparse(value)
            trusted_url = (parsed.scheme in {"http", "https"}
                           and parsed.hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"})
        except ValueError:
            return None
        if trusted_url:
            path = parsed.path.split("/", 2)
            if len(path) != 3 or path[1] not in {"abs", "pdf", "html"}:
                return None
            identifier = path[2].rstrip("/")
        elif allow_bare:
            identifier = value
        else:
            return None
    match = _ARXIV_REFERENCE.fullmatch(identifier.removesuffix(".pdf"))
    return match[1] if match else None


def title_key(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def hit_keys(hit: LiveHit) -> set[str]:
    keys = {hit.dedup_key.lower()}
    arxiv_id = extract_arxiv_id(hit.doi_or_arxiv) or extract_arxiv_id(hit.url)
    if arxiv_id:
        keys.add(f"arxiv:{arxiv_id}")
    doi = normalize_doi(hit.doi_or_arxiv)
    if doi and not doi.startswith("arxiv"):
        keys.add(f"doi:{doi}")
    if hit.title:
        keys.add(f"title:{title_key(hit.title)}")
    return keys


def merge_duplicate_hits(hits: list[LiveHit]) -> list[LiveHit]:
    """Merge provider metadata for the same paper while preserving result order."""
    merged: list[LiveHit] = []
    for candidate in hits:
        index = next(
            (i for i, current in enumerate(merged) if hit_keys(current) & hit_keys(candidate)),
            None,
        )
        if index is None:
            candidate = replace(candidate,
                matched_sources=list(dict.fromkeys([candidate.source, *candidate.matched_sources])),
                source_records=candidate.source_records or [{"source": candidate.source, "source_id": candidate.source_id,
                    "url": candidate.url, "doi_or_arxiv": candidate.doi_or_arxiv, "year": candidate.year,
                    "publication_types": candidate.publication_types}])
            merged.append(candidate)
            continue
        current = merged[index]

        def richer_text(first: str | None, second: str | None) -> str | None:
            return max((value for value in (first, second) if value), key=len, default=None)

        def union(first: list[str], second: list[str]) -> list[str]:
            return list(dict.fromkeys([*first, *second]))

        merged[index] = replace(
            current,
            authors=current.authors or candidate.authors,
            year=current.year or candidate.year,
            venue=current.venue or candidate.venue,
            doi_or_arxiv=current.doi_or_arxiv or candidate.doi_or_arxiv,
            url=current.url or candidate.url,
            abstract=richer_text(current.abstract, candidate.abstract),
            source_id=current.source_id or candidate.source_id,
            open_access_pdf_url=current.open_access_pdf_url or candidate.open_access_pdf_url,
            citation_count=max(
                (value for value in (current.citation_count, candidate.citation_count) if value is not None),
                default=None,
            ),
            reference_count=max(
                (value for value in (current.reference_count, candidate.reference_count) if value is not None),
                default=None,
            ),
            fields_of_study=union(current.fields_of_study, candidate.fields_of_study),
            publication_types=union(current.publication_types, candidate.publication_types),
            tldr=richer_text(current.tldr, candidate.tldr),
            semantic_scholar_id=current.semantic_scholar_id or candidate.semantic_scholar_id,
            matched_sources=union(current.matched_sources or [current.source], candidate.matched_sources or [candidate.source]),
            source_records=[*current.source_records, *(candidate.source_records or [{"source": candidate.source,
                            "source_id": candidate.source_id, "url": candidate.url, "doi_or_arxiv": candidate.doi_or_arxiv,
                            "year": candidate.year, "publication_types": candidate.publication_types}])],
        )
    return merged


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def parse_arxiv(body: bytes) -> tuple[list[LiveHit], int | None]:
    if not body:
        return [], None
    root = ET.fromstring(body)
    total = None
    hits: list[LiveHit] = []
    for child in list(root):
        name = _local(child.tag)
        if name == "totalResults":
            try:
                total = int((child.text or "").strip())
            except ValueError:
                total = None
        if name != "entry":
            continue
        fields: dict[str, str] = {}
        authors: list[str] = []
        html_url = None
        for node in list(child):
            local = _local(node.tag)
            if local == "title":
                fields["title"] = re.sub(r"\s+", " ", (node.text or "").strip())
            elif local == "summary":
                fields["abstract"] = re.sub(r"\s+", " ", (node.text or "").strip())
            elif local == "id":
                fields["id"] = (node.text or "").strip()
            elif local == "published":
                fields["published"] = (node.text or "").strip()
            elif local == "author":
                name_node = next((item for item in list(node) if _local(item.tag) == "name"), None)
                if name_node is not None and name_node.text:
                    authors.append(name_node.text.strip())
            elif local == "link" and node.attrib.get("rel") == "alternate":
                html_url = node.attrib.get("href")
            elif local == "doi":
                fields["doi"] = (node.text or "").strip()
        arxiv_id = extract_arxiv_id(fields.get("id"))
        if not arxiv_id or not fields.get("title"):
            continue
        year = None
        if fields.get("published"):
            try:
                year = int(fields["published"][:4])
            except ValueError:
                year = None
        url = html_url or f"https://arxiv.org/abs/{arxiv_id}"
        doi = normalize_doi(fields.get("doi"))
        hits.append(
            LiveHit(
                source="arxiv",
                title=fields["title"],
                authors=authors,
                year=year,
                venue="arXiv preprint",
                doi_or_arxiv=f"arXiv:{arxiv_id}",
                url=url,
                abstract=fields.get("abstract"),
                dedup_key=f"arxiv:{arxiv_id}",
                publication_types=["preprint"],
            )
        )
        if doi:
            hits[-1].doi_or_arxiv = f"arXiv:{arxiv_id}"
    return hits, total


def reconstruct_abstract(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    placed: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for index in positions or []:
            placed.append((int(index), str(word)))
    if not placed:
        return None
    placed.sort()
    return " ".join(word for _, word in placed)


def _openalex_pdf_url(work: dict, primary_location: dict) -> str | None:
    best_location = work.get("best_oa_location") or {}
    if best_location.get("pdf_url") and best_location.get("is_oa") is not False:
        return best_location["pdf_url"]
    for location in [primary_location, *(work.get("locations") or [])]:
        if isinstance(location, dict) and location.get("is_oa") is True and location.get("pdf_url"):
            return location["pdf_url"]
    if not best_location and primary_location.get("is_oa") is not False:
        return primary_location.get("pdf_url")
    return None


def parse_openalex(body: bytes) -> tuple[list[LiveHit], int | None]:
    if not body:
        return [], None
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("OpenAlex 响应缺少检索结果列表")
    meta = payload.get("meta") or {}
    total = meta.get("count")
    hits: list[LiveHit] = []
    for work in payload["results"]:
        title = (work.get("display_name") or work.get("title") or "").strip()
        if not title:
            continue
        ids = work.get("ids") or {}
        doi = normalize_doi(work.get("doi") or ids.get("doi"))
        location = work.get("primary_location") or {}
        source = (location.get("source") or {}).get("display_name")
        landing = location.get("landing_page_url") or work.get("id")
        arxiv_id = (extract_arxiv_id(landing, allow_bare=False) or extract_arxiv_id(ids.get("arxiv"))
                    or extract_arxiv_id(doi, allow_bare=False) or extract_arxiv_id(ids.get("doi"), allow_bare=False))
        authors = [
            item.get("author", {}).get("display_name")
            for item in work.get("authorships") or []
            if item.get("author", {}).get("display_name")
        ]
        if arxiv_id:
            dedup = f"arxiv:{arxiv_id}"
            identifier = f"arXiv:{arxiv_id}"
            url = f"https://arxiv.org/abs/{arxiv_id}"
        elif doi:
            dedup = f"doi:{doi}"
            identifier = doi
            url = landing or f"https://doi.org/{doi}"
        elif landing:
            dedup = f"url:{landing}"
            identifier = landing
            url = landing
        else:
            continue
        hits.append(
            LiveHit(
                source="openalex",
                title=title,
                authors=[name for name in authors if name],
                year=work.get("publication_year"),
                venue=source,
                doi_or_arxiv=identifier,
                url=url,
                abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
                dedup_key=dedup,
                source_id=work.get("id"),
                open_access_pdf_url=_openalex_pdf_url(work, location),
                citation_count=work.get("cited_by_count"),
                reference_count=len(work.get("referenced_works") or []),
                fields_of_study=[
                    topic.get("display_name") for topic in work.get("topics") or []
                    if topic.get("display_name")
                ][:8],
                publication_types=[str(value) for value in
                    [work.get("type"), (location.get("source") or {}).get("type")] if value],
            )
        )
    return hits, int(total) if total is not None else None


def _source_urls(spec: QuerySpec, *, limit: int, mailto: str | None, offset: int = 0) -> list[str]:
    conditions = spec.constraints
    if spec.source == "arxiv":
        if spec.query.startswith("id_list:"):
            identifiers = spec.query.removeprefix("id_list:")
            if not all(re.fullmatch(r"\d{4}\.\d{4,5}", value) for value in identifiers.split(",")):
                raise ValueError("Invalid explicit arXiv identifiers")
            params = urlencode({"id_list": identifiers, "max_results": limit})
        else:
            params = urlencode({"search_query": spec.query, "start": offset, "max_results": limit})
        return [
            f"https://export.arxiv.org/api/query?{params}",
            f"https://arxiv.org/api/query?{params}",
        ]
    if spec.source == "openalex":
        params = {"search": spec.query, "per_page": limit}
        if offset:
            params["page"] = offset // limit + 1
        filters = []
        if conditions.get("year_from"):
            filters.append(f"from_publication_date:{conditions['year_from']}-01-01")
        if conditions.get("year_to"):
            filters.append(f"to_publication_date:{conditions['year_to']}-12-31")
        kind = conditions.get("publication_type")
        if kind in {"journal", "conference"}:
            filters.append(f"primary_location.source.type:{kind}")
        elif kind == "review":
            filters.append("type:review")
        if filters:
            params["filter"] = ",".join(filters)
        if mailto:
            params["mailto"] = mailto
        return ["https://api.openalex.org/works?" + urlencode(params)]
    raise ValueError("检索来源应为 arXiv 或 OpenAlex")


def _parse(source: str, body: bytes) -> tuple[list[LiveHit], int | None]:
    if source == "arxiv":
        return parse_arxiv(body)
    if source == "openalex":
        return parse_openalex(body)
    raise ValueError("检索来源应为 arXiv 或 OpenAlex")


def _fetch_with_fallback(
    urls: list[str],
    *,
    fetch: FetchFn,
    headers: dict[str, str] | None,
    mailto: str | None,
    timeout: float,
) -> FetchResult:
    last = FetchResult(url=urls[0], status=None, error="no request")
    for url in urls:
        _retrieval_checkpoint("retrieval_request")
        result = fetch(url, headers=headers, timeout=timeout, mailto=mailto)
        _retrieval_checkpoint("retrieval_response")
        if result.status == 200:
            return result
        if result.status == 429:
            from src.provider_runtime import retry_after_seconds, wait_cancelable
            retry_deadline = time.monotonic() + 12.0
            hint = retry_after_seconds(next((v for k, v in result.headers.items() if k.lower() == "retry-after"), None))
            delay = hint if hint is not None else 3.0
            # One base-query retry, at most twelve seconds of waiting. Extra
            # pagination bypasses this helper to preserve its exact call cap.
            if delay > 12.0:
                result.notes.append("retry_deferred_provider_cooldown")
                return result
            if fetch is http_get:
                wait_cancelable(delay)
            else:
                # Injected transports remain deterministic in parser/budget
                # tests; callers can supply their own scheduler.
                _retrieval_checkpoint("provider_wait")
            _retrieval_checkpoint("retrieval_request")
            retry_options = {"headers": headers, "timeout": timeout, "mailto": mailto}
            if fetch is http_get:
                retry_options["provider_wait_budget"] = max(0., retry_deadline - time.monotonic())
            retry = fetch(url, **retry_options)
            _retrieval_checkpoint("retrieval_response")
            if retry.status == 200:
                retry.notes = [*result.notes, *retry.notes, "retried_once"]
                return retry
            result.notes.append("retried_once")
            if retry.error:
                result.notes.append(retry.error)
            elif retry.status not in {None, 429}:
                result.notes.append(f"retry_http={retry.status}")
            return result
        last = result
    return last


def _retrieval_checkpoint(stage: str) -> None:
    # Local import avoids a retrieve -> tasks -> conversation import cycle.
    from src.tasks import report_progress
    report_progress(stage)


def _next_offset(*, offset: int, limit: int, parsed_count: int, total: int | None) -> int | None:
    if not parsed_count or (total is not None and offset + limit >= total):
        return None
    return offset + limit if total is not None or parsed_count >= limit else None


def _batch_record(spec: QuerySpec, parsed: list[LiveHit], *, status: str, total: int | None,
                  offset: int, limit: int, before: list[LiveHit], next_offset: int | None,
                  supplement: bool = False, page_number: int | None = None) -> dict:
    before_count = len(merge_duplicate_hits(before))
    new_count = len(merge_duplicate_hits([*before, *parsed])) - before_count if status == "success" else 0
    return {"query_id": spec.query_id, "base_query_id": spec.query_id.split("-page-")[0],
            "source": spec.source, "page": page_number or offset // limit + 1, "offset": offset,
            "status": status, "raw_result_count": len(parsed) if status == "success" else None,
            "new_unique_count": max(0, new_count), "reported_total": total,
            "supplement": supplement, "has_more": next_offset is not None,
            "more_results_basis": "provider_total_or_next" if total is not None else "full_batch_heuristic",
            "stop_reason": None if next_offset is not None else "end_or_empty_page" if status == "success" else status}


def search_all(
    question: str | None,
    *,
    cache_dir: Path,
    mailto: str | None = None,
    openalex_api_key: str | None = None,
    limit_per_source: int = 15,
    fetch: FetchFn = http_get,
    sleep_s: float = 0.35,
    constraints: dict | None = None,
    supplement: dict | None = None,
    base_sources: list[str] | None = None,
) -> SearchBundle:
    conditions = validate_constraints(constraints)
    budget = validate_search_supplement(supplement)
    sources = validate_search_sources(base_sources)
    if budget and (isinstance(limit_per_source, bool) or not isinstance(limit_per_source, int)
                   or not 1 <= limit_per_source <= 100):
        raise ValueError("补充检索每页条数必须在1到100之间")
    cache_dir.mkdir(parents=True, exist_ok=True)
    active_sources = ACTIVE_SEARCH_SOURCES if sources is None else sources
    specs = [spec for spec in build_query_plan(question, conditions) if spec.source in active_sources]
    queries: list[SearchQuery] = []
    runs: list[RetrievalRun] = []
    hits: list[LiveHit] = []
    notes: list[str] = []
    batches: list[dict] = []
    continuations: list[dict] = []
    extra_requests = 0
    today = date.today()
    def track(spec, result, parsed, total, status, *, headers, timeout):
        nxt = None if status != "success" or spec.query.startswith("id_list:") else _next_offset(
            offset=0, limit=limit_per_source, parsed_count=len(parsed), total=total)
        batch = _batch_record(spec, parsed, status=status, total=total, offset=0,
                              limit=limit_per_source, before=hits, next_offset=nxt)
        batches.append(batch)
        if nxt is not None and spec.source in budget.get("sources", []):
            continuations.append({"spec": spec, "headers": headers, "timeout": timeout,
                                  "next_offset": nxt, "pages_used": 0, "last_batch": batch,
                                  "last_url": result.url, "seen_keys": {h.dedup_key for h in parsed}})

    for index, spec in enumerate(specs):
        if index:
            time.sleep(sleep_s)
        urls = _source_urls(spec, limit=limit_per_source, mailto=mailto)
        headers = provider_auth_headers(spec.source, openalex_api_key)
        timeout = 35 if spec.source == "arxiv" else 25
        result = _fetch_with_fallback(
            urls,
            fetch=fetch,
            headers=headers,
            mailto=mailto,
            timeout=timeout,
        )
        status = retrieval_status(result.status, result.error)
        parsed: list[LiveHit] = []
        total = None
        suffix = "xml" if spec.source == "arxiv" else "json"
        response_path = cache_dir / f"{spec.query_id}.{suffix}"
        if result.body:
            response_path.write_bytes(result.body)
        if status == "success":
            try:
                parsed, total = _parse(spec.source, result.body)
            except (ET.ParseError, json.JSONDecodeError, ValueError, TypeError) as exc:
                status = "failed"
                notes.append(f"{spec.query_id} 解析失败: {exc}")
                parsed, total = [], None
        result_count = len(parsed) if status == "success" else None
        run_notes = list(result.notes)
        if result.error:
            run_notes.append(result.error)
        if result.status != 200 or result.error:
            _, message = connection_diagnostic(spec.source, result, authenticated=bool(headers))
            if message:
                run_notes.append(message)
        queries.append(
            SearchQuery(
                query_id=spec.query_id,
                source=spec.source,
                query=spec.query,
                purpose=spec.purpose,
                date=today,
                scope_version="v0.1",
                notes="在线检索式；结构化条件：" + json.dumps(conditions, ensure_ascii=False),
            )
        )
        runs.append(
            RetrievalRun(
                retrieval_id=f"live-{spec.query_id}",
                query_id=spec.query_id,
                source=spec.source,
                request=result.url or urls[0],
                retrieved_at=today,
                http_status=result.status,
                status=status,
                result_count=result_count,
                response_path=str(response_path),
                notes="; ".join(run_notes) if run_notes else None,
                total_count=total if status == "success" else None,
            )
        )
        track(spec, result, parsed, total, status, headers=headers, timeout=timeout)
        if status == "success":
            hits.extend(parsed)
        if (
            spec.source == "arxiv"
            and not spec.query.startswith("id_list:")
            and status == "success"
            and len(parsed) == 0
            and question
        ):
            fallback_query = to_arxiv_fallback_query(question)
            if fallback_query and fallback_query != spec.query:
                time.sleep(sleep_s)
                if conditions.get("year_from") or conditions.get("year_to"):
                    start = conditions.get("year_from", 1800)
                    end = conditions.get("year_to", date.today().year + 1)
                    fallback_query = f"({fallback_query}) AND submittedDate:[{start}01010000 TO {end}12312359]"
                fallback_spec = QuerySpec("q-live-arxiv-fallback", "arxiv", fallback_query, "arXiv 零结果回退检索", conditions)
                fallback_urls = _source_urls(fallback_spec, limit=limit_per_source, mailto=mailto)
                fallback_result = _fetch_with_fallback(
                    fallback_urls,
                    fetch=fetch,
                    headers=None,
                    mailto=mailto,
                    timeout=timeout,
                )
                fallback_status = retrieval_status(fallback_result.status, fallback_result.error)
                fallback_parsed: list[LiveHit] = []
                fallback_total = None
                fallback_path = cache_dir / f"{fallback_spec.query_id}.xml"
                if fallback_result.body:
                    fallback_path.write_bytes(fallback_result.body)
                if fallback_status == "success":
                    try:
                        fallback_parsed, fallback_total = _parse("arxiv", fallback_result.body)
                    except (ET.ParseError, ValueError, TypeError) as exc:
                        fallback_status = "failed"
                        notes.append(f"{fallback_spec.query_id} 解析失败: {exc}")
                fallback_notes = list(fallback_result.notes)
                if fallback_result.error:
                    fallback_notes.append(fallback_result.error)
                queries.append(
                    SearchQuery(
                        query_id=fallback_spec.query_id,
                        source=fallback_spec.source,
                        query=fallback_spec.query,
                        purpose=fallback_spec.purpose,
                        date=today,
                        scope_version="v0.1",
                        notes="arXiv 零结果后回退检索式",
                    )
                )
                runs.append(
                    RetrievalRun(
                        retrieval_id=f"live-{fallback_spec.query_id}",
                        query_id=fallback_spec.query_id,
                        source=fallback_spec.source,
                        request=fallback_result.url or fallback_urls[0],
                        retrieved_at=today,
                        http_status=fallback_result.status,
                        status=fallback_status,
                        result_count=len(fallback_parsed) if fallback_status == "success" else None,
                        response_path=str(fallback_path),
                        notes="; ".join(fallback_notes) if fallback_notes else "arxiv_zero_result_fallback",
                        total_count=fallback_total if fallback_status == "success" else None,
                    )
                )
                track(fallback_spec, fallback_result, fallback_parsed, fallback_total, fallback_status,
                      headers=None, timeout=timeout)
                if fallback_status == "success" and fallback_parsed:
                    hits.extend(fallback_parsed)
                    notes.append(f"arXiv 首次零结果，回退检索返回 {len(fallback_parsed)} 条。")
    # Opt-in supplements use one HTTP attempt per batch, so max_requests is a
    # real cap on additional provider requests, including failed/429 responses.
    # The previous successful arXiv host is reused; no hidden fallback/retry can
    # exceed the caller's additional-request budget.
    while continuations and extra_requests < budget.get("max_requests", 0):
        continuation = continuations.pop(0)
        spec = continuation["spec"]
        offset = continuation["next_offset"]
        page = continuation["pages_used"] + 2
        page_spec = replace(spec, query_id=f"{spec.query_id}-page-{page}",
                            purpose=f"{spec.purpose}（补充第{page}页）")
        _retrieval_checkpoint("retrieval_supplement")
        time.sleep(max(sleep_s, 3.0) if spec.source == "arxiv" else sleep_s)
        _retrieval_checkpoint("retrieval_request")
        urls = _source_urls(spec, limit=limit_per_source, mailto=mailto, offset=offset)
        previous_host = urlparse(continuation["last_url"] or "").netloc
        url = next((u for u in urls if urlparse(u).netloc == previous_host), urls[0])
        extra_requests += 1
        result = fetch(url, headers=continuation["headers"], timeout=continuation["timeout"], mailto=mailto)
        _retrieval_checkpoint("retrieval_response")
        status = retrieval_status(result.status, result.error)
        parsed, total = [], None
        suffix = "xml" if spec.source == "arxiv" else "json"
        response_path = cache_dir / f"{page_spec.query_id}.{suffix}"
        if result.body:
            response_path.write_bytes(result.body)
        run_notes = [*result.notes, "bounded_supplement_single_http_attempt"]
        if result.error:
            run_notes.append(result.error)
        if status == "success":
            try:
                parsed, total = _parse(spec.source, result.body)
            except (ET.ParseError, json.JSONDecodeError, ValueError, TypeError) as exc:
                status = "failed"
                run_notes.append("parse_error:" + type(exc).__name__)
        if status == "rate_limited":
            run_notes.append("HTTP 429 记为限流失败；补页不自动重试以遵守额外请求预算。")
        nxt = _next_offset(offset=offset, limit=limit_per_source,
                           parsed_count=len(parsed), total=total) if status == "success" else None
        row = _batch_record(page_spec, parsed, status=status, total=total, offset=offset,
                            limit=limit_per_source, before=hits, next_offset=nxt, supplement=True, page_number=page)
        batches.append(row)
        queries.append(SearchQuery(query_id=page_spec.query_id, source=spec.source, query=spec.query,
                                   purpose=page_spec.purpose, date=today, scope_version="v0.3",
                                   notes=f"显式预算补页；offset={offset}；每页最多{limit_per_source}条；结构化条件：" + json.dumps(conditions, ensure_ascii=False)))
        runs.append(RetrievalRun(retrieval_id=f"live-{page_spec.query_id}", query_id=page_spec.query_id,
                                 source=spec.source, request=result.url or url, retrieved_at=today,
                                 http_status=result.status, status=status,
                                 result_count=len(parsed) if status == "success" else None,
                                 response_path=str(response_path), notes="; ".join(run_notes),
                                 total_count=total if status == "success" else None))
        if status != "success":
            row["has_more"] = continuation["last_batch"]["has_more"]
            row["reported_total"] = continuation["last_batch"]["reported_total"]
            row["more_results_basis"] = continuation["last_batch"]["more_results_basis"]
            row["stop_reason"] = status
            continue
        if not parsed and total is not None and offset < total:
            row["has_more"] = True
            row["stop_reason"] = "empty_page_before_reported_total"
        query_new_keys = {h.dedup_key for h in parsed} - continuation["seen_keys"]
        hits.extend(parsed)
        continuation["pages_used"] += 1
        continuation["seen_keys"].update(h.dedup_key for h in parsed)
        continuation["last_batch"] = row
        if not query_new_keys and parsed:
            row["stop_reason"] = "repeated_page_no_new_query_records"
        elif nxt is not None and continuation["pages_used"] < budget["pages_per_query"]:
            continuation["next_offset"] = nxt
            continuations.append(continuation)
        elif nxt is not None:
            row["stop_reason"] = "pages_per_query_limit"
    for continuation in continuations:
        continuation["last_batch"]["stop_reason"] = "additional_request_budget_exhausted"
    if extra_requests:
        notes.append(f"显式补充检索使用 {extra_requests}/{budget['max_requests']} 次额外请求；每批来源、页码与新增数已保存。")
    merged_hits = merge_duplicate_hits(hits)
    duplicate_count = len(hits) - len(merged_hits)
    if duplicate_count:
        notes.append(f"跨来源合并 {duplicate_count} 条重复论文，并保留开放全文与引用元数据。")
    before_filter = len(merged_hits)
    excluded, unknown, kept = [], [], []
    for hit in merged_hits:
        hit.constraint_check = metadata_check(hit, conditions)
        if hit.constraint_check["status"] == "mismatch":
            excluded.append({"title": hit.title, "dedup_key": hit.dedup_key, **hit.constraint_check})
            continue
        if hit.constraint_check["status"] == "unknown":
            unknown.append({"title": hit.title, "dedup_key": hit.dedup_key, **hit.constraint_check})
        kept.append(hit)
    merged_hits = kept
    filter_report = {"before_filter": before_filter, "kept": len(kept), "excluded": excluded, "needs_confirmation": unknown}
    coverage = {}
    for source in ACTIVE_SEARCH_SOURCES:
        own = [r for r in runs if r.source == source]
        own_batches = [b for b in batches if b["source"] == source]
        latest = {b["base_query_id"]: b for b in own_batches}
        coverage[source] = {"query_count": len(own), "successful_queries": sum(r.status == "success" for r in own),
                            "raw_result_count": sum(r.result_count or 0 for r in own if r.status == "success"),
                            "visible_unique_count": sum(source in h.matched_sources for h in kept),
                            "reported_total_max": max((r.total_count for r in own if r.total_count is not None), default=None),
                            "truncated": any(b["has_more"] for b in latest.values()),
                            "batches": own_batches,
                            "coverage_basis": "executed_query_batches_only",
                            "status": "not_requested" if not own else "success" if all(r.status == "success" for r in own)
                            else "partial" if any(r.status == "success" for r in own) else "failed"}
    if question and merged_hits:
        _retrieval_checkpoint("retrieval_ranking")
        from src.retrieval_rank import rank_hits
        merged_hits, ranking = rank_hits(research_text(question, conditions), merged_hits)
        notes.append(
            "候选统一重排：" + ranking["backend"]
            + (f"（{ranking['reason']}）" if ranking.get("reason") else "")
        )
    return SearchBundle(queries=queries, runs=runs, hits=merged_hits, notes=notes,
                        constraints=conditions, coverage=coverage, filter_report=filter_report,
                        search_budget={**budget, "enabled": bool(budget), "additional_requests_used": extra_requests,
                                       "requested_base_sources": sources,
                                       "additional_unique_count": sum(b["new_unique_count"] for b in batches if b["supplement"]),
                                       "scope": "additional_pagination_http_requests_only_base_search_and_citation_requests_excluded"})


def _openalex_work_id(value: str | None) -> str | None:
    match = re.fullmatch(r"(?:https?://(?:openalex\.org/|api\.openalex\.org/works/))?(W[0-9]+)/?",
                         value.strip() if isinstance(value, str) else "", flags=re.I)
    return match.group(1).upper() if match else None


def _openalex_lookup_id(value: str | None) -> str | None:
    if not isinstance(value, str) or len(value) > 250:
        return None
    work_id = _openalex_work_id(value)
    if work_id:
        return work_id
    arxiv = re.fullmatch(r"(?:(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)|arxiv:\s*)?"
                         r"(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?", value.strip(), flags=re.I)
    if arxiv:
        return f"https://doi.org/10.48550/arxiv.{arxiv.group(1)}"
    doi = normalize_doi(value)
    if doi and re.fullmatch(r"10\.\d+/[^\s?#]+", doi):
        return f"https://doi.org/{doi}"
    return None


def related_paper_identifier(paper) -> str | None:
    return (_openalex_work_id(paper.source_id) or _openalex_lookup_id(paper.doi_or_arxiv)
            or _openalex_lookup_id(paper.url))


def fetch_related_hits(
    paper_id: str, direction: str, *, cache_dir: Path, api_key: str | None = None,
    mailto: str | None = None, fetch: FetchFn = http_get, limit: int = 20, constraints: dict | None = None,
) -> SearchBundle:
    """Fetch and record OpenAlex references or citing works for one paper."""
    from src.tasks import report_progress

    lookup_id = _openalex_lookup_id(paper_id)
    if not lookup_id:
        raise ValueError("引用探索需要 OpenAlex ID、DOI 或 arXiv 编号")
    if direction not in {"references", "citations"}:
        raise ValueError("direction 应为references或citations")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("引用探索数量应为1至100")
    conditions = validate_constraints(constraints)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = sha256((lookup_id + "|" + direction).encode()).hexdigest()[:16]
    query_id = f"q-related-{direction}-{key}"
    headers = provider_auth_headers("openalex", api_key)
    today = date.today()
    requests, runs = [], []
    deadline = time.monotonic() + 24.0

    def request(url, stage):
        report_progress(stage)
        options = {"deadline": deadline, "provider_wait_budget": 3.0} if fetch is http_get else {}
        return fetch(url, headers=headers, timeout=12, mailto=mailto, **options)

    def record(response, url, step, status, count, *, total=None, error=None):
        path = cache_dir / f"{query_id}-{step}.json"
        if response.body:
            path.write_bytes(response.body)
        notes = [*response.notes]
        if error or response.error:
            notes.append(error or response.error)
        runs.append(RetrievalRun(retrieval_id=f"related-{key}-{step}", query_id=query_id, source="openalex",
                                 request=response.url or url, retrieved_at=today, http_status=response.status,
                                 status=status, result_count=count, total_count=total,
                                 response_path=str(path) if response.body else None, notes="; ".join(notes) or None))
        entry = {"step": step, "status": status, "http_status": response.status}
        if response.error == PROVIDER_TIMEOUT:
            entry["error_code"] = PROVIDER_TIMEOUT
        requests.append(entry)

    seed_id = _openalex_work_id(lookup_id)
    hits, status = [], "failed"
    params = {"mailto": mailto} if mailto else {}
    if seed_id is None:
        url = f"https://api.openalex.org/works/{quote(lookup_id, safe=':/')}?" + urlencode({**params, "select": "id"})
        response = request(url, "citation_lookup")
        status = retrieval_status(response.status, response.error)
        error = None
        if status == "success":
            try:
                seed_id = _openalex_work_id(json.loads(response.body).get("id"))
            except (ValueError, TypeError, AttributeError):
                seed_id = None
            if seed_id is None:
                status, error = "failed", "OpenAlex 未返回可用的论文标识。"
        elif response.status == 404:
            error = "OpenAlex 未找到该论文。"
        record(response, url, "lookup", status, 1 if seed_id else None, error=error)

    if seed_id:
        filter_name = "cited_by" if direction == "references" else "cites"
        url = "https://api.openalex.org/works?" + urlencode({**params, "filter": f"{filter_name}:{seed_id}", "per_page": limit})
        response = request(url, "citation_fetch")
        status = retrieval_status(response.status, response.error)
        total, error = None, None
        if status == "success":
            try:
                if not response.body:
                    raise ValueError("OpenAlex 引用响应为空")
                hits, total = parse_openalex(response.body)
            except (ValueError, TypeError, AttributeError) as exc:
                status, error = "failed", f"citation_parse_failed:{type(exc).__name__}"
        record(response, url, direction, status, len(hits) if status == "success" else None, total=total, error=error)
    merged = merge_duplicate_hits(hits)
    raw_count = len(merged)
    excluded, unknown, kept = [], [], []
    for hit in merged:
        hit.constraint_check = metadata_check(hit, conditions)
        row = {"title": hit.title, "dedup_key": hit.dedup_key, **hit.constraint_check}
        if hit.constraint_check["status"] == "mismatch": excluded.append(row)
        else:
            kept.append(hit)
            if hit.constraint_check["status"] == "unknown": unknown.append(row)
    query = SearchQuery(query_id=query_id, source="openalex", query=lookup_id,
                        purpose="参考文献探索" if direction == "references" else "后续引用探索",
                        date=today, scope_version="v0.3", notes=f"direction={direction}; limit={limit}")
    nodes = [{"paper_id": seed_id, "seed": True}] if seed_id else []
    edges = []
    for hit in merged:
        related_id = _openalex_work_id(hit.source_id)
        if not related_id or related_id == seed_id:
            continue
        source, target = (seed_id, related_id) if direction == "references" else (related_id, seed_id)
        nodes.append({"paper_id": related_id, "title": hit.title, "abstract": hit.abstract, "year": hit.year,
                      "url": hit.url, "open_access_pdf_url": hit.open_access_pdf_url, "seed": False})
        edges.append({"seed": seed_id, "related": related_id, "direction": direction,
                      "source": source, "target": target, "relation": "cites"})
    graph = {"algorithm": "openalex_one_hop", "seed_count": int(seed_id is not None), "nodes": nodes,
             "edges": edges, "requests": requests, "edge_count": len(edges),
             "failure_count": sum(item["status"] != "success" for item in requests),
             "discovery": {"paper_id": seed_id or lookup_id, "direction": direction}}
    return SearchBundle(queries=[query], runs=runs, hits=kept,
                        notes=["OpenAlex 引用探索结果会按当前研究问题筛选。"], citation_graph=graph,
                        constraints=conditions,
                        coverage={"openalex": {"query_count": 1, "successful_queries": int(status == "success"),
                            "raw_result_count": len(hits), "visible_unique_count": len(kept), "status": status}},
                        filter_report={"before_filter": raw_count, "kept": len(kept), "excluded": excluded,
                                       "needs_confirmation": unknown})
