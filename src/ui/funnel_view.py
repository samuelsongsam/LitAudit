"""筛选漏斗视图：必须同时展示 include / exclude / pending 及理由。"""

from __future__ import annotations

import streamlit as st

from src.schema import Dataset, dataset_stats, latest_screening_by_paper


def render_funnel(dataset: Dataset) -> None:
    stats = dataset_stats(dataset)
    counts = stats["decision_counts"]
    st.subheader("筛选漏斗")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("真实候选", stats["paper_count"])
    c2.metric("include", counts["include"])
    c3.metric("exclude", counts["exclude"])
    c4.metric("pending", counts["pending"])
    st.caption("papers.jsonl 是候选主索引。exclude 必须保留，不能从界面消失。fixture 不计入以上数字。")

    if stats.get("fixture_paper_count"):
        st.info(f"当前还载入了 {stats['fixture_paper_count']} 条 fixture，仅用于 schema 演示，不进入真实统计。")

    cards = dataset.card_by_id()
    latest = latest_screening_by_paper(dataset.screening)
    rows = []
    for paper in dataset.papers:
        log = latest.get(paper.paper_id)
        card = cards.get(paper.paper_id)
        rows.append(
            {
                "paper_id": paper.paper_id,
                "decision": paper.decision.value,
                "title": paper.title,
                "year": paper.year,
                "parse_status": None if card is None else card.parse_status,
                "reason_code": None if log is None else log.reason_code,
                "reason": paper.reason,
                "doi_or_arxiv": paper.doi_or_arxiv,
                "fixture": paper.is_fixture,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("全部筛选日志（含历史阶段，不只最新一条）"):
        log_rows = [
            {
                "screening_id": log.screening_id,
                "paper_id": log.paper_id,
                "stage": log.stage.value,
                "decision": log.decision.value,
                "reason_code": log.reason_code,
                "reviewed_at": str(log.reviewed_at),
                "reason": log.reason,
            }
            for log in dataset.screening
        ]
        st.dataframe(log_rows, use_container_width=True, hide_index=True)

    st.markdown("**检索运行**")
    if not dataset.retrieval_runs:
        st.caption("当前 run 没有 retrieval_runs.jsonl。")
    else:
        st.caption("HTTP 429 和连接失败必须显示为失败/限流，不能当成零结果成功。")
        run_rows = [
            {
                "retrieval_id": run.retrieval_id,
                "source": run.source,
                "query_id": run.query_id,
                "http_status": run.http_status,
                "status": run.status,
                "result_count": run.result_count,
                "notes": run.notes,
            }
            for run in dataset.retrieval_runs
        ]
        st.dataframe(run_rows, use_container_width=True, hide_index=True)

    st.markdown("**检索式**")
    for query in dataset.queries:
        st.markdown(f"- `{query.query_id}` / {query.source}: {query.query}")
        if query.notes:
            st.caption(query.notes)
