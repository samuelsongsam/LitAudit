"""Evidence-linked, conditional reading guidance from a user's constraints.

This module performs no model/network calls and never writes a claim verdict.
Facts are extractive spans; advice stays explicitly conditional.
"""
from __future__ import annotations

from pathlib import Path
import math
import re

from src.research_workspace import FIELDS, method_comparison


_ENGLISH_NUMBERS = {word: float(i) for i, word in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"])}
_NUMBER = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+|半|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|half)\b)"
_DIGITS = {c: i for i, c in enumerate("零一二三四五六七八九")}
_DIGITS.update({"〇": 0, "两": 2})


def _number(value: str) -> float | None:
    """Parse explicit Chinese/Arabic quantities; never guess 几/数/若干."""
    if value.casefold() in _ENGLISH_NUMBERS:
        return _ENGLISH_NUMBERS[value.casefold()]
    if value.casefold() in {"半", "half"}:
        return .5
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        pass
    if "点" in value:
        whole, decimal = value.split("点", 1)
        base = _number(whole or "零")
        if base is None or not decimal or any(c not in _DIGITS for c in decimal):
            return None
        return base + float("0." + "".join(str(_DIGITS[c]) for c in decimal))
    if all(c in _DIGITS for c in value):
        return float("".join(str(_DIGITS[c]) for c in value))
    total, section, digit = 0, 0, 0
    for char in value:
        if char in _DIGITS:
            digit = _DIGITS[char]
        elif char in {"十", "百", "千"}:
            section += (digit or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            digit = 0
        elif char == "万":
            total += (section + digit or 1) * 10000
            section, digit = 0, 0
        else:
            return None
    return float(total + section + digit)


def _clause(text: str, start: int, end: int) -> str:
    separators = r"[;；。\n,，]"
    before = list(re.finditer(separators, text[:start]))
    after = re.search(separators, text[end:])
    return text[before[-1].end() if before else 0:end + after.start() if after else len(text)].strip()


def _model_scales(text: str) -> list[str]:
    return sorted(set(m.group(1) + m.group(2).upper() for m in re.finditer(
        r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*([bBmM])(?![A-Za-z0-9])", text)))


def _memory_analysis(text: str) -> dict:
    candidates = []
    factors = {"gb": 1, "gib": 1024 ** 3 / 1e9, "mb": 1 / 1000,
               "mib": 1024 ** 2 / 1e9, "tb": 1000, "tib": 1024 ** 4 / 1e9}
    for match in re.finditer(r"(" + _NUMBER + r")\s*(Gi?B|Mi?B|Ti?B)(?![A-Za-z])", text, re.I):
        context = _clause(text, match.start(), match.end())
        lower = context.lower()
        if re.search(r"gpu|vram|显存|显卡", lower):
            kind = "gpu_memory"
        elif re.search(r"memory|\bram\b|内存", lower):
            kind = "memory"
        elif (re.search(r"gpu|vram|显存|显卡", text, re.I)
              and not re.search(r"\bram\b|host memory|cpu memory|system memory|主机内存|系统内存", text, re.I)):
            kind = "gpu_memory"
        else:
            continue
        amount = _number(match.group(1))
        if amount is None or amount <= 0:
            continue
        normalized = re.sub(r"\b(one|two|three|four|five|six|seven|eight)\b",
                            lambda m: str(["one", "two", "three", "four", "five", "six", "seven", "eight"].index(m[0]) + 1), lower)
        count_match = re.search(r"(" + _NUMBER + r")\s*(?:张|块|台|个|卡)\s*(?:gpu|显卡|卡)?", normalized)
        if not count_match:
            count_match = re.search(r"(" + _NUMBER + r")\s*(?:gpus?|显卡|张卡)\b", normalized)
        if not count_match:
            prefix = text[max(0, match.start() - 12):match.start()]
            count_match = re.search(r"(" + _NUMBER + r")\s*[x×*]\s*$", prefix)
        if not count_match:
            global_counts = list(re.finditer(r"(" + _NUMBER + r")\s*(?:张|块|台|个)?\s*(?:gpus?|显卡)(?![A-Za-z])", text, re.I))
            if len(global_counts) == 1:
                count_match = global_counts[0]
        count = _number(count_match.group(1)) if count_match else None
        if count is None and re.search(r"单卡|单张|single[- ](?:gpu|card)|一张|一块", lower):
            count = 1.0
        if count is not None and (not count.is_integer() or count < 1):
            count = None
        total_scope = bool(re.search(r"\btotal\b|总计|合计|总显存|总内存", lower))
        explicit_each = bool(re.search(r"\beach\b|per[- ](?:gpu|device|card)|每(?:张|块|卡|台)|单卡", lower))
        # “2张24GB显卡” and “2 x 24 GB GPUs” explicitly express capacity per card.
        prefix_each = bool(re.search(r"(?:张|块|卡|[x×*])\s*$", text[max(0, match.start() - 8):match.start()]))
        scope = "total" if total_scope else "per_device" if explicit_each or prefix_each or count == 1 else "unspecified"
        phase = "inference" if re.search(r"inferenc|推理", lower) else "training" if re.search(r"train|finetun|训练|微调", lower) else None
        candidate = {"kind": kind, "capacity_gb": round(amount * factors[match.group(2).lower()], 9),
                     "device_count": int(count) if count else None, "capacity_scope": scope,
                     "model_scales": _model_scales(context), "phase": phase,
                     "quote": context, "start": match.start(), "end": match.end()}
        signature = tuple(str(candidate[k]) for k in ("kind", "capacity_gb", "device_count", "capacity_scope", "model_scales", "phase"))
        if not any(c["signature"] == signature for c in candidates):
            candidates.append({**candidate, "signature": signature})
    for candidate in candidates:
        candidate.pop("signature")
    return {"status": "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "not_found",
            "candidates": candidates,
            "reason": "multiple_memory_configurations" if len(candidates) > 1 else None}


def _memory(text: str) -> tuple[str, float] | None:
    parsed = _memory_analysis(text)
    if parsed["status"] != "resolved":
        return None
    candidate = parsed["candidates"][0]
    return candidate["kind"], candidate["capacity_gb"]


def _duration_analysis(text: str) -> dict:
    # Match on the original text so candidate quotes remain verbatim rather
    # than silently changing “Two Hours” into the derived phrase “2 hours”.
    normalized = text
    units = {"second": 1 / 3600, "seconds": 1 / 3600, "秒": 1 / 3600,
             "minute": 1 / 60, "minutes": 1 / 60, "分钟": 1 / 60,
             "hour": 1, "hours": 1, "小时": 1,
             "day": 24, "days": 24, "天": 24, "week": 168, "weeks": 168, "周": 168, "星期": 168}
    pattern = r"(" + _NUMBER + r")\s*(?:个\s*)?(半\s*)?(" + "|".join(sorted(units, key=len, reverse=True)) + r")(半)?"
    candidates, previous_end, previous_scale = [], None, None
    for match in re.finditer(pattern, normalized, re.I):
        amount = _number(match[1])
        if amount is None:
            continue
        amount += .5 if match[2] or match[4] else 0
        scale = units[match[3].casefold()]
        value = amount * scale
        before = normalized[max(0, match.start() - 25):match.start()]
        ranged = re.search(r"(" + _NUMBER + r")\s*(?:to|至|到|[-–—~～])\s*$", before, re.I)
        if ranged:
            lower = _number(ranged[1])
            if lower is not None:
                candidates.append({"hours": lower * scale, "quote": ranged[0] + match[0], "range": True,
                                   "context": _clause(normalized, match.start(), match.end())})
        gap = normalized[previous_end:match.start()] if previous_end is not None else None
        compound = previous_scale is not None and scale < previous_scale and gap is not None and bool(re.fullmatch(r"\s*(?:又|和|and|\+)?\s*", gap, re.I))
        if compound and not ranged:
            candidates[-1]["hours"] += value
            candidates[-1]["quote"] += (gap or "") + match[0]
        else:
            candidates.append({"hours": value, "quote": match[0], "range": bool(ranged),
                               "context": _clause(normalized, match.start(), match.end())})
        previous_end, previous_scale = match.end(), scale
    unique = list({(round(c["hours"], 12), c["range"], c["context"]): c for c in candidates}.values())
    status = "resolved" if len(unique) == 1 and not unique[0]["range"] else "ambiguous" if unique else "not_found"
    return {"status": status, "hours": unique[0]["hours"] if status == "resolved" else None,
            "candidates": unique, "reason": "multiple_duration_configurations" if status == "ambiguous" else None}


def _duration_hours(text: str) -> float | None:
    return _duration_analysis(text)["hours"]


def _memory_comparison(reported_text: str, user_text: str, passage_id: str) -> tuple[dict | None, dict]:
    reported, supplied = _memory_analysis(reported_text), _memory_analysis(user_text)
    user_scales = _model_scales(user_text)
    if reported["status"] == "ambiguous" and len(user_scales) == 1:
        selected = [c for c in reported["candidates"] if c["model_scales"] == user_scales]
        if len(selected) == 1:
            reported = {**reported, "status": "resolved", "candidates": selected,
                        "selected_by": "explicit_user_model_scale", "reason": None}
    analysis = {"reported": reported, "user": supplied, "status": "not_found"}
    if "ambiguous" in {reported["status"], supplied["status"]}:
        return None, {**analysis, "status": "ambiguous", "reason": "multiple_memory_configurations"}
    if reported["status"] != "resolved" or supplied["status"] != "resolved":
        return None, analysis
    left, right = reported["candidates"][0], supplied["candidates"][0]
    reason = None
    if left["kind"] != right["kind"]:
        reason = "memory_category_mismatch"
    elif left["device_count"] and right["device_count"] and left["device_count"] != right["device_count"]:
        reason = "device_count_mismatch"
    elif (max(left["device_count"] or 0, right["device_count"] or 0) > 1
          and (left["device_count"] is None or right["device_count"] is None)):
        reason = "device_count_not_explicit"
    elif any(c["device_count"] and c["device_count"] > 1 and c["capacity_scope"] == "unspecified" for c in (left, right)):
        reason = "per_device_capacity_not_explicit"
    elif left["capacity_scope"] != right["capacity_scope"] and "total" in {left["capacity_scope"], right["capacity_scope"]}:
        reason = "total_and_per_device_capacity_mismatch"
    elif left["phase"] and right["phase"] and left["phase"] != right["phase"]:
        reason = "training_inference_phase_mismatch"
    elif left["model_scales"] and user_scales and not set(left["model_scales"]) & set(user_scales):
        reason = "model_scale_mismatch"
    if reason:
        return None, {**analysis, "status": "ambiguous", "reason": reason}
    return {"kind": left["kind"], "reported_gb": left["capacity_gb"], "user_gb": right["capacity_gb"],
            "reported_device_count": left["device_count"], "user_device_count": right["device_count"],
            "source_passage_id": passage_id,
            "status": "reported_capacity_above_user" if left["capacity_gb"] > right["capacity_gb"] else "capacity_value_not_above_user",
            "scope": "仅比较同类明确容量；多卡显存不相加，设备数量、模型规模、精度和批大小仍需核对。"}, {**analysis, "status": "resolved"}


def research_guidance(runs_dir: Path, run_id: str, paper_ids: list[str] | None = None,
                      user_resources: dict | None = None) -> dict:
    resources = {} if user_resources is None else user_resources
    if not isinstance(resources, dict) or set(resources) - {"data", "compute", "time"}:
        raise ValueError("研究条件应包含 data、compute、time 文本")
    if any(not isinstance(v, str) or len(v) > 2000 for v in resources.values()):
        raise ValueError("每项研究条件应为2000字以内的文本")
    resources = {key: value.strip() for key, value in resources.items() if value.strip()}
    matrix = method_comparison(runs_dir, run_id, paper_ids)
    labels = {field["key"]: field["label"] for field in FIELDS}
    suggestions = []
    for paper in matrix["papers"]:
        facts = []
        for key, field in paper["fields"].items():
            candidate = field.get("candidate")
            if not candidate:
                continue
            facts.append({"field": key, "label": labels[key], "value": candidate.get("value", ""),
                          "value_source": candidate.get("extraction_source", "rule_sentence"),
                          "quote": candidate.get("quote", candidate["text"]), "page": candidate["page"],
                          "passage_id": candidate["passage_id"], "text_sha256": candidate["text_sha256"],
                          "pdf_url": candidate["pdf_url"], "review_status": field["status"]})
        if not facts:
            continue
        by_field = {fact["field"]: fact for fact in facts}
        checks = []
        for key, label, field_keys in [
            ("data", "数据条件", ["data", "sample_size", "conditions"]),
            ("compute", "算力条件", ["resources", "method"]),
            ("time", "时间安排", ["resources", "experiment"]),
        ]:
            if key not in resources:
                continue
            references = [by_field[f] for f in field_keys if f in by_field]
            primary_available = field_keys[0] in by_field
            comparison = None
            analysis = None
            resource_fact = by_field.get("resources")
            if key == "compute" and resource_fact:
                comparison, analysis = _memory_comparison(resource_fact["quote"], resources[key], resource_fact["passage_id"])
            elif key == "time" and resource_fact:
                reported, supplied = _duration_analysis(resource_fact["quote"]), _duration_analysis(resources[key])
                analysis = {"reported": reported, "user": supplied,
                            "status": "ambiguous" if "ambiguous" in {reported["status"], supplied["status"]} else
                                      "resolved" if reported["status"] == supplied["status"] == "resolved" else "not_found"}
                if analysis["status"] == "resolved":
                    comparison = {"kind": "reported_run_time", "reported_hours": reported["hours"], "user_hours": supplied["hours"],
                                  "source_passage_id": resource_fact["passage_id"],
                                  "status": "reported_run_above_user_budget" if reported["hours"] > supplied["hours"] else "reported_run_within_time_value",
                                  "scope": "原文运行时间依赖其配置；总研究时间还需包含数据准备与重复实验。"}
            ambiguous = analysis is not None and analysis["status"] == "ambiguous"
            checks.append({"dimension": key, "label": label, "user_constraint": resources[key],
                           "status": "needs_configuration_selection" if ambiguous else "needs_comparison" if primary_available else "needs_more_evidence",
                           "suggestion": (f"{label}包含多种或不一致配置，暂不比较数值。请先选择模型规模、训练或推理阶段、设备数量和单卡容量，再核对原文。"
                                          if ambiguous else f"请将你的{label}与所引原文逐项比较；条件相符时可将该方案列入候选。"
                                          if primary_available else f"当前尚未提取到明确的{label}依据，先补充正文或人工记录再决定是否采用。"),
                           "sources": references, "numeric_comparison": comparison, "resource_analysis": analysis})
        missing = [labels[key] for key in ["method", "data", "experiment", "resources", "conditions"] if key not in by_field]
        suggestions.append({"paper_id": paper["paper_id"], "title": paper["title"],
                            "kind": "conditional_reading_guidance", "facts": facts, "checks": checks,
                            "missing_fields": missing,
                            "recommendation": "先核对方法、实验和适用条件，再结合你的数据与资源决定是否开展复现。",
                            "decision": "requires_user_judgment"})
    return {"run_id": run_id, "kind": "conditional_suggestions", "user_resources": resources,
            "suggestions": suggestions, "missing_fulltext": matrix["missing_paper_ids"],
            "requested_conditions": [key for key in ("data", "compute", "time") if key not in resources],
            "notice": "事实字段对应原文摘录；建议用于条件核查，不代表已验证复现可行性或方法优劣。"}
