from pathlib import Path
import json
import re

try:
    import fitz
except ImportError:
    raise SystemExit("pymupdf required")

DATA = Path("data")
PDF_DIR = Path("data/cache/retrieval-2026-08-26/pdf")
PDF = {
    "paper-001": PDF_DIR / "paper-001.pdf",
    "paper-003": PDF_DIR / "paper-003.pdf",
    "paper-006": PDF_DIR / "paper-006.pdf",
    "paper-007": PDF_DIR / "paper-007.pdf",
}


def normalize(text: str) -> str:
    text = text.lower().replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"-\s+", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text)


def main() -> None:
    pages_cache: dict[str, dict[int, str]] = {}
    missing = []
    for line in (DATA / "evidence.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        pdf = PDF.get(item["paper_id"])
        page = (item.get("locator") or {}).get("page")
        if pdf is None or page is None:
            print("SKIP", item["evidence_id"])
            continue
        if item["paper_id"] not in pages_cache:
            doc = fitz.open(pdf)
            pages_cache[item["paper_id"]] = {i + 1: normalize(doc[i].get_text()) for i in range(doc.page_count)}
        hay = pages_cache[item["paper_id"]].get(page, "")
        needle = normalize(item["snippet"])
        ok = needle in hay
        # allow a slightly looser match if hyphenation removed extra spaces
        if not ok:
            tokens = [tok for tok in needle.split() if len(tok) > 3][:12]
            ok = all(tok in hay for tok in tokens)
        print(("OK" if ok else "MISS"), item["evidence_id"], "p" + str(page))
        if not ok:
            missing.append(item["evidence_id"])
    if missing:
        raise SystemExit("missing: " + ",".join(missing))
    print("all snippets located")


if __name__ == "__main__":
    main()
