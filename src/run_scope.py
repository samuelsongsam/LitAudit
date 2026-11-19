from __future__ import annotations


def visible_paper_ids(live: dict) -> set[str]:
    """New runs record all hits; legacy runs recorded only newly added papers."""
    return set(live.get("matched_paper_ids", live.get("added_paper_ids", [])) or [])
