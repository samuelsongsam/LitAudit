from pathlib import Path

needles = {
    "paper-001-pages.txt": [
        "We present PaperQA",
        "we also introduce LitQA",
        "57.9%",
        "86.3%",
        "LIMITATIONS",
        "were not able to find a single hallucinated citation",
        "Table 2",
        "expert humans",
    ],
    "paper-003-pages.txt": [
        "We present SciMON",
        "GPT-4 tends to generate",
        "partially mitigate",
        "ABSTRACT",
        "Limitation",
        "novelty",
    ],
    "paper-006-pages.txt": [
        "unsupported information or contradictions",
        "Retrieval-augmented generation",
        "faithfulness",
        "ABSTRACT",
        "Limitation",
    ],
    "paper-007-pages.txt": [
        "non-existent sources",
        "fail to faithfully reflect",
        "MIRAGE",
        "ABSTRACT",
        "Limitation",
    ],
}

base = Path("data/cache/retrieval-2026-08-26/pdf")
for fname, keys in needles.items():
    text = (base / fname).read_text(encoding="utf-8")
    pages = text.split("===== PAGE ")
    print("\n########", fname)
    for page in pages[1:]:
        num, _, body = page.partition(" =====")
        for key in keys:
            if key.lower() in body.lower():
                snippet = body.strip().replace("\n", " ")[:220]
                print(f"  p{num.strip()} HIT {key!r}")
