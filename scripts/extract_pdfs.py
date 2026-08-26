from pathlib import Path

import fitz

base = Path("data/cache/retrieval-2026-08-26/pdf")
for name in ["paper-003.pdf", "paper-006.pdf", "paper-007.pdf"]:
    doc = fitz.open(base / name)
    out = base / (name.replace(".pdf", "-pages.txt"))
    parts = []
    for i in range(doc.page_count):
        parts.append(f"===== PAGE {i + 1} =====\n{doc[i].get_text()}\n")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(name, "pages", doc.page_count, "chars", sum(len(p) for p in parts))
