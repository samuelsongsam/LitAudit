"""筛选漏斗视图：必须同时展示 include / exclude / pending 及理由。"""

from __future__ import annotations

import streamlit as st

from src.schema import Dataset, dataset_stats


def render_funnel(dataset: Dataset) -> None:
    stats = dataset_stats(dataset)
    counts = stats["decision_counts"]
    st.subheader("筛选漏斗")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("真实候选", stats["paper_count"])
    c2.metric("include", counts["include"])
    c3.metric("exclude", counts["exclude"])
    c4.metric("pending", counts["pending"])
    st.caption("fixture 不计入以上数字。exclude 与 pending 必须可见，不能从界面消失。")

    if stats["fixture_paper_count"]:
        st.info(f"当前还载入了 {stats['fixture_paper_count']} 条 fixture，仅用于 schema 演示，不进入真实统计。")

    rows = []
    screening = {log.paper_id: log for log in dataset.screening}
    for paper in dataset.papers:
        log = screening.get(paper.paper_id)
        rows.append(
            {
                "paper_id": paper.paper_id,
                "decision": paper.decision.value,
                "title": paper.title,
                "year": paper.year,
                "authors": None if paper.authors is None else ", ".join(paper.authors),
                "abstract": paper.abstract,
                "reason_code": None if log is None else log.reason_code,
                "reason": paper.reason,
                "doi_or_arxiv": paper.doi_or_arxiv,
                "fixture": paper.is_fixture,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("**检索式**")
    for query in dataset.queries:
        st.markdown(f"- `{query.query_id}` / {query.source}: {query.query}")
        if query.notes:
            st.caption(query.notes)
