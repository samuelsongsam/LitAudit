from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from src.http_fetch import FetchResult, http_get
from src.schema import RetrievalRun, SearchQuery

FetchFn = Callable[..., FetchResult]

DEFAULT_ARXIV = 'all:"retrieval-augmented" AND all:agent AND (all:scientific OR all:literature)'
DEFAULT_OPENALEX = "large language model retrieval augmented scientific literature"
DEFAULT_S2 = "scientific question answering RAG retrieval augmented agent"
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
ZH_MAP = (
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
    ("经典", "classical"),
    ("当代", "contemporary"),
    ("检索增强", "retrieval-augmented"),
    ("可追溯", "traceability provenance"),
    ("文献综述", "literature review"),
    ("科学问答", "scientific question answering"),
    ("智能体", "agent"),
    ("幻觉", "hallucination"),
    ("证据", "evidence"),
    ("科研", "scientific research"),
    ("大模型", "large language model"),
    ("综述", "literature review"),
    ("问答", "question answering"),
)
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


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


@dataclass
class QuerySpec:
    query_id: str
    source: str
    query: str
    purpose: str


@dataclass
class SearchBundle:
    queries: list[SearchQuery]
    runs: list[RetrievalRun]
    hits: list[LiveHit]
    notes: list[str] = field(default_factory=list)


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
    extras = [english for chinese, english in ZH_MAP if chinese in text]
    if extras:
        text = f"{text} {' '.join(extras)}"
    return text


def to_arxiv_query(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    if "all:" in raw or "ti:" in raw:
        return raw
    low = raw.lower()
    if "gpu" in low and any(term in low for term in ("microarchitecture", "hopper", "ada", "rdna", "cdna")):
        return '(all:gpu OR all:nvidia OR all:amd) AND (all:hopper OR all:h100 OR all:ada OR all:rdna OR all:cdna)'
    parts: list[str] = []
    for phrase in (
        "retrieval-augmented",
        "retrieval augmented",
        "large language model",
        "literature review",
        "question answering",
        "scientific literature",
    ):
        if phrase in low:
            normalized = "retrieval-augmented" if phrase == "retrieval augmented" else phrase
            token = f'all:"{normalized}"'
            if token not in parts:
                parts.append(token)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", raw):
        lowered = token.lower()
        if lowered in STOP or any(lowered in part.lower() for part in parts):
            continue
        parts.append(f"all:{lowered}")
        if len(parts) >= 6:
            break
    return " AND ".join(parts)


def to_provider_query(text: str) -> str:
    """Keep a concise English query for providers whose search endpoints handle natural text."""
    stop = STOP | {
        "modern", "specific", "technical", "details", "detail", "including", "include",
        "analysis", "deep", "comparison", "such", "like", "architecture",
    }
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{1,}", text or ""):
        lowered = token.lower()
        if lowered in stop or lowered in tokens:
            continue
        tokens.append(lowered)
        if len(tokens) >= 14:
            break
    return " ".join(tokens)


def build_query_plan(question: str | None) -> list[QuerySpec]:
    english = expand_question(question or "")
    user_arxiv = to_arxiv_query(english)
    provider_query = to_provider_query(english)
    specs = [QuerySpec("q-live-arxiv-user", "arxiv", user_arxiv or DEFAULT_ARXIV, "用户问题检索")] if question else [QuerySpec("q-live-arxiv", "arxiv", DEFAULT_ARXIV, "范围主检索")]
    specs.append(QuerySpec("q-live-openalex", "openalex", provider_query or english or DEFAULT_OPENALEX, "OpenAlex 扩展"))
    specs.append(
        QuerySpec(
            "q-live-s2",
            "semantic_scholar",
            provider_query or english or DEFAULT_S2,
            "Semantic Scholar",
        )
    )
    if not question and len(specs) < 4:
        specs.append(QuerySpec("q-live-risk", "arxiv", RISK_ARXIV, "反向风险检索"))
    return specs[:4]


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"^https?://(dx\.)?doi\.org/", "", value.strip(), flags=re.I)
    cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.I)
    return cleaned.lower() or None


def extract_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = ARXIV_ID.search(value.replace("arXiv:", "").replace("arxiv:", ""))
    return match.group(1) if match else None


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


def parse_openalex(body: bytes) -> tuple[list[LiveHit], int | None]:
    if not body:
        return [], None
    payload = json.loads(body.decode("utf-8"))
    meta = payload.get("meta") or {}
    total = meta.get("count")
    hits: list[LiveHit] = []
    for work in payload.get("results") or []:
        title = (work.get("display_name") or work.get("title") or "").strip()
        if not title:
            continue
        doi = normalize_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
        location = work.get("primary_location") or {}
        source = (location.get("source") or {}).get("display_name")
        landing = location.get("landing_page_url") or work.get("id")
        arxiv_id = extract_arxiv_id(landing) or extract_arxiv_id(str(work.get("ids") or {}))
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
            )
        )
    return hits, int(total) if total is not None else None


def parse_semantic_scholar(body: bytes) -> tuple[list[LiveHit], int | None]:
    if not body:
        return [], None
    payload = json.loads(body.decode("utf-8"))
    total = payload.get("total")
    hits: list[LiveHit] = []
    for paper in payload.get("data") or []:
        title = (paper.get("title") or "").strip()
        if not title:
            continue
        external = paper.get("externalIds") or {}
        arxiv_id = extract_arxiv_id(external.get("ArXiv") or external.get("arXiv"))
        doi = normalize_doi(external.get("DOI") or external.get("Doi"))
        url = paper.get("url") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None)
        if doi and not url:
            url = f"https://doi.org/{doi}"
        if not url:
            continue
        if arxiv_id:
            dedup = f"arxiv:{arxiv_id}"
            identifier = f"arXiv:{arxiv_id}"
        elif doi:
            dedup = f"doi:{doi}"
            identifier = doi
        else:
            dedup = f"title:{title_key(title)}"
            identifier = url
        authors = [item.get("name") for item in paper.get("authors") or [] if item.get("name")]
        hits.append(
            LiveHit(
                source="semantic_scholar",
                title=title,
                authors=authors,
                year=paper.get("year"),
                venue=paper.get("venue"),
                doi_or_arxiv=identifier,
                url=url,
                abstract=paper.get("abstract"),
                dedup_key=dedup,
            )
        )
    return hits, int(total) if total is not None else None


def _source_urls(spec: QuerySpec, *, limit: int, mailto: str | None) -> list[str]:
    if spec.source == "arxiv":
        params = urlencode({"search_query": spec.query, "start": 0, "max_results": limit})
        return [
            f"https://export.arxiv.org/api/query?{params}",
            f"https://arxiv.org/api/query?{params}",
        ]
    if spec.source == "openalex":
        params = {"search": spec.query, "per_page": limit}
        if mailto:
            params["mailto"] = mailto
        return ["https://api.openalex.org/works?" + urlencode(params)]
    params = {
        "query": spec.query,
        "limit": limit,
        "fields": "title,abstract,year,authors,externalIds,url,venue",
    }
    return ["https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params)]


def _parse(source: str, body: bytes) -> tuple[list[LiveHit], int | None]:
    if source == "arxiv":
        return parse_arxiv(body)
    if source == "openalex":
        return parse_openalex(body)
    return parse_semantic_scholar(body)


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
        result = fetch(url, headers=headers, timeout=timeout, mailto=mailto)
        if result.status == 200:
            return result
        if result.status == 429:
            time.sleep(1.2)
            retry = fetch(url, headers=headers, timeout=timeout, mailto=mailto)
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


def search_all(
    question: str | None,
    *,
    cache_dir: Path,
    mailto: str | None = None,
    semantic_scholar_api_key: str | None = None,
    limit_per_source: int = 15,
    fetch: FetchFn = http_get,
    sleep_s: float = 0.35,
) -> SearchBundle:
    cache_dir.mkdir(parents=True, exist_ok=True)
    specs = build_query_plan(question)
    queries: list[SearchQuery] = []
    runs: list[RetrievalRun] = []
    hits: list[LiveHit] = []
    notes: list[str] = []
    today = date.today()
    for index, spec in enumerate(specs):
        if index:
            time.sleep(sleep_s)
        urls = _source_urls(spec, limit=limit_per_source, mailto=mailto)
        headers = {}
        if spec.source == "semantic_scholar" and semantic_scholar_api_key:
            headers["x-api-key"] = semantic_scholar_api_key
        timeout = 35 if spec.source == "arxiv" else 25
        result = _fetch_with_fallback(
            urls,
            fetch=fetch,
            headers=headers or None,
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
        if status == "rate_limited":
            run_notes.append("HTTP 429 记为限流失败，不能当成零结果成功。")
        queries.append(
            SearchQuery(
                query_id=spec.query_id,
                source=spec.source,
                query=spec.query,
                purpose=spec.purpose,
                date=today,
                scope_version="v0.1",
                notes="在线检索式",
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
        if status == "success":
            hits.extend(parsed)
    return SearchBundle(queries=queries, runs=runs, hits=hits, notes=notes)
