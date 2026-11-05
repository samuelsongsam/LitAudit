"""User-owned reading lists and portable scholarly exports for each research."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from urllib.parse import unquote, urlparse

from src.io_utils import read_json
from src.research_workspace import _atomic_json, _lock, fork_workspace, workspace_papers
from src.run_paths import resolve_run_dir

READING_STATES = {"unread", "reading", "done"}
FORMATS = {"bibtex", "ris", "markdown", "csv"}


def _saved(run_dir: Path) -> dict:
    path = run_dir / "output" / "paper_library.json"
    if not path.exists():
        return {"version": 1, "items": {}}
    data = read_json(path)
    if (not isinstance(data, dict) or not isinstance(data.get("items"), dict)
            or any(not isinstance(row, dict) for row in data["items"].values())):
        raise ValueError("阅读清单格式不正确，原记录已保留")
    for row in data["items"].values():
        if (("notes" in row and not isinstance(row["notes"], str))
                or ("tags" in row and (not isinstance(row["tags"], list) or any(not isinstance(t, str) for t in row["tags"])))
                or ("history" in row and not isinstance(row["history"], list))):
            raise ValueError("阅读清单字段格式不正确，原记录已保留")
    return data


def library_payload(runs_dir: Path, run_id: str) -> dict:
    papers = workspace_papers(runs_dir, run_id)
    run_dir = resolve_run_dir(runs_dir, run_id)
    # Readers share the writer lock: Windows cannot atomically replace a JSON
    # file while another request has that file open without delete sharing.
    with _lock(run_dir):
        saved = _saved(run_dir)
    items = []
    for paper_id, paper in papers.items():
        entry = saved["items"].get(paper_id) or {}
        citation = citation_metadata({"title": paper.title, "authors": paper.authors,
                                      "year": paper.year, "doi_or_arxiv": paper.doi_or_arxiv,
                                      "url": paper.url, "dedup_key": paper.dedup_key})
        items.append({"paper_id": paper_id, "title": paper.title or paper_id,
                      "authors": paper.authors or [], "year": paper.year,
                      "venue": paper.venue, "doi_or_arxiv": paper.doi_or_arxiv, "url": paper.url,
                      "favorite": bool(entry.get("favorite", False)),
                      "reading_status": entry.get("reading_status", "unread"),
                      "tags": entry.get("tags", []), "notes": entry.get("notes", ""),
                      "updated_at": entry.get("updated_at"),
                      "history_count": len(entry.get("history") or []), **citation})
    return {"run_id": run_id, "items": items, "formats": sorted(FORMATS),
            "protected": run_id in {"phase2-real", "demo"}}


def save_library_item(runs_dir: Path, run_id: str, body: dict) -> dict:
    if not isinstance(body, dict) or not isinstance(body.get("paper_id"), str):
        raise ValueError("请指定论文编号")
    paper_id = body["paper_id"]
    papers = workspace_papers(runs_dir, run_id)
    if paper_id not in papers:
        raise ValueError("该论文不属于当前研究范围")
    updates = {}
    if "favorite" in body:
        if not isinstance(body["favorite"], bool):
            raise ValueError("favorite 应为布尔值")
        updates["favorite"] = body["favorite"]
    if "reading_status" in body:
        status = body["reading_status"]
        if not isinstance(status, str) or status not in READING_STATES:
            raise ValueError("阅读状态应为 unread、reading 或 done")
        updates["reading_status"] = status
    if "tags" in body:
        tags = body["tags"]
        if (not isinstance(tags, list) or len(tags) > 20
                or any(not isinstance(t, str) or len(t) > 50 for t in tags)):
            raise ValueError("标签应为最多20个、每个50字以内的文本")
        updates["tags"] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    if "notes" in body:
        if not isinstance(body["notes"], str) or len(body["notes"]) > 20000:
            raise ValueError("阅读笔记应不超过20000字")
        updates["notes"] = body["notes"].strip()
    if not updates:
        raise ValueError("请提供收藏、阅读状态、标签或笔记")
    if run_id in {"phase2-real", "demo"}:
        run_id = fork_workspace(runs_dir, run_id)["run_id"]
    run_dir = resolve_run_dir(runs_dir, run_id)
    with _lock(run_dir):
        data = _saved(run_dir)
        previous = data["items"].get(paper_id) or {}
        entry = {"favorite": False, "reading_status": "unread", "tags": [], "notes": "",
                 **previous, **updates, "updated_at": datetime.now(timezone.utc).isoformat(),
                 "source": "human"}
        if previous:
            entry["history"] = (previous.get("history") or []) + [
                {key: previous.get(key) for key in ("favorite", "reading_status", "tags", "notes", "updated_at")}]
        data["items"][paper_id] = entry
        data.update(run_id=run_id, updated_at=entry["updated_at"])
        _atomic_json(run_dir / "output" / "paper_library.json", data)
    return {"run_id": run_id, "item": next(i for i in library_payload(runs_dir, run_id)["items"] if i["paper_id"] == paper_id)}


def _line(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())


def _bib(value: Any) -> str:
    """Protect structural delimiters and TeX control characters in metadata."""
    replacements = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}",
                    "%": r"\%", "&": r"\&", "#": r"\#", "_": r"\_", "$": r"\$"}
    return "".join(replacements.get(c, c) for c in _line(value))


def _url(value: Any) -> str:
    value = _line(value)
    return value if urlparse(value).scheme in {"http", "https"} else ""


def _doi(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    # Remove a URL's query before decoding its path: an encoded # or ? can
    # belong to the DOI itself and must not collapse two scholarly identities.
    candidate = unquote(parsed.path) if parsed.scheme in {"http", "https"} else raw
    match = re.search(r"10\.\d{4,9}/\S+", candidate, re.I)
    return match.group(0).rstrip(".,;").casefold() if match else ""


def _arxiv(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        if (parsed.hostname or "").lower() not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org", "doi.org", "dx.doi.org"}:
            return ""
        raw = unquote(parsed.path)
    raw = re.sub(r"^(?:/?(?:abs|pdf)/|arxiv\s*:\s*|/?10\.48550/arxiv\.)", "", raw, flags=re.I)
    match = re.fullmatch(r"(\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})(?:v\d+)?(?:\.pdf)?", raw, re.I)
    return match.group(1).casefold() if match else ""


def _normalized_metadata(value: Any) -> str:
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", _line(value)).casefold()))


def citation_metadata(item: dict) -> dict:
    """Derive export identity from bibliographic facts, never a run-local ID.

    Notes and reading state are intentionally excluded. Derivation does not
    mutate saved records, so existing human history remains byte-for-byte intact.
    """
    values = [item.get("doi_or_arxiv"), item.get("url")]
    doi = next((identifier for value in values if (identifier := _doi(value))), "")
    arxiv = next((identifier for value in values if (identifier := _arxiv(value))), "")
    warning = None
    if doi:
        source, identity, slug = "doi", "doi:" + doi, doi
    elif arxiv:
        source, identity, slug = "arxiv", "arxiv:" + arxiv, arxiv
    else:
        title = _normalized_metadata(item.get("title"))
        authors = sorted(" ".join(sorted(_normalized_metadata(a).split())) for a in item.get("authors") or [])
        metadata = {"title": title, "authors": authors, "year": _line(item.get("year"))}
        # A record with no useful title may still have a stable source/PDF key.
        # Do not manufacture uniqueness from paper-001 or a run name.
        if not title:
            pdf_key = _line(item.get("dedup_key"))
            source_url = _line(item.get("url"))
            stable_source = pdf_key if re.fullmatch(r"pdf:[0-9a-f]{64}", pdf_key, re.I) else source_url if (
                urlparse(source_url).scheme in {"http", "https"} or re.fullmatch(r"local:sha256:[0-9a-f]{64}", source_url, re.I)) else ""
            metadata["source"] = stable_source
            if not stable_source:
                warning = "题录缺少题名、稳定标识或原文件指纹，请补充后导出参考文献。"
        identity = "metadata:" + json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source, slug = "metadata", title[:32] or "untitled"
    readable = re.sub(r"[^a-z0-9]+", "_", slug.casefold()).strip("_")[:48] or "paper"
    key = f"{source}_{readable}_{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    return {"citation_key": key, "citation_key_source": source,
            "citation_identity": identity, "citation_key_warning": warning, "arxiv_id": arxiv or None}


def _md(value: Any) -> str:
    return _line(value).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_library(runs_dir: Path, run_id: str, format: str = "bibtex", paper_ids: list[str] | None = None) -> dict:
    if not isinstance(format, str) or format not in FORMATS:
        raise ValueError("导出格式应为 bibtex、ris、markdown 或 csv")
    payload = library_payload(runs_dir, run_id)
    items = payload["items"]
    if paper_ids is not None:
        if not isinstance(paper_ids, list) or any(not isinstance(i, str) for i in paper_ids):
            raise ValueError("paper_ids 应为论文编号列表")
        allowed = {i["paper_id"] for i in items}
        if set(paper_ids) - allowed:
            raise ValueError("导出论文不属于当前研究范围")
        items = [i for i in items if i["paper_id"] in set(paper_ids)]
    selected_count = len(items)
    if format in {"bibtex", "ris"}:
        if any(item.get("citation_key_warning") for item in items):
            raise ValueError("部分论文缺少题名或稳定标识，请先补充题录；现有阅读记录仍可导出CSV/Markdown。")
        # Identical scholarly identifiers must not create duplicate keys inside
        # one bibliography. CSV/Markdown retain every local reading record.
        unique = {}
        for item in items:
            unique.setdefault(item["citation_key"], item)
        items = list(unique.values())
    if format == "bibtex":
        records = []
        for item in items:
            key = item["citation_key"]
            fields = {"title": item["title"], "author": " and ".join(item["authors"]),
                      "year": item["year"], "journal": item["venue"],
                      "doi": _doi(item["doi_or_arxiv"]) or _doi(item["url"]), "url": _url(item["url"]),
                      "eprint": item.get("arxiv_id"), "archivePrefix": "arXiv" if item.get("arxiv_id") else None}
            values = [f"  {k} = {{{_bib(v)}}}" for k, v in fields.items() if v]
            records.append("@misc{" + key + ",\n" + ",\n".join(values) + "\n}")
        content, extension = "\n\n".join(records) + ("\n" if records else ""), "bib"
    elif format == "ris":
        records = []
        for item in items:
            rows = ["TY  - GEN", "ID  - " + item["citation_key"], "TI  - " + _line(item["title"])]
            rows.extend("AU  - " + _line(author) for author in item["authors"])
            for tag, value in [("PY", item["year"]), ("JO", item["venue"]), ("DO", _doi(item["doi_or_arxiv"]) or _doi(item["url"])), ("UR", _url(item["url"]))]:
                if value:
                    rows.append(tag + "  - " + _line(value))
            rows.extend("KW  - " + _line(tag) for tag in item["tags"])
            rows.append("ER  -")
            records.append("\n".join(rows))
        content, extension = "\n\n".join(records) + ("\n" if records else ""), "ris"
    elif format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["论文编号", "标题", "作者", "年份", "来源", "DOI或arXiv", "链接", "收藏", "阅读状态", "标签", "阅读笔记", "稳定引用键"])
        for item in items:
            row = [item["paper_id"], item["title"], "; ".join(item["authors"]), item["year"], item["venue"],
                   item["doi_or_arxiv"], _url(item["url"]), item["favorite"], item["reading_status"], "; ".join(item["tags"]), item["notes"], item["citation_key"]]
            writer.writerow([_csv_cell(v) for v in row])
        content, extension = "\ufeff" + stream.getvalue(), "csv"
    else:
        rows = ["# 文献阅读清单", "", "| 论文 | 年份 | 阅读状态 | 收藏 | 标签 |", "| --- | --- | --- | --- | --- |"]
        for item in items:
            rows.append("| " + " | ".join(_md(v) for v in [item["title"], item["year"], item["reading_status"], "是" if item["favorite"] else "否", ", ".join(item["tags"])]) + " |")
        for item in items:
            if item["notes"]:
                rows += ["", "## " + _md(item["title"]), "", item["notes"].replace("<", "&lt;").replace(">", "&gt;")]
        content, extension = "\n".join(rows) + "\n", "md"
    return {"run_id": run_id, "format": format, "filename": f"litaudit-{run_id}-library.{extension}",
            "content": content, "paper_count": len(items), "selected_paper_count": selected_count,
            "source": "stored_metadata_and_human_notes"}
