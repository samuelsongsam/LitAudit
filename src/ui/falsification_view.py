from __future__ import annotations

import streamlit as st

from src.schema import Dataset


def render_falsification(dataset: Dataset) -> None:
    st.subheader("证伪报告")
    st.caption("反证据可以召回 exclude 论文。hit-001 / hit-002 来自通用 RAG/QA 风险论文，任务不同于自动科研主问题。")

    if not dataset.falsification:
        st.warning("当前 run 没有 falsification.jsonl。")
        excluded = [paper for paper in dataset.real_papers() if paper.decision.value == "exclude"]
        if excluded:
            st.markdown("**已保留的排除论文（可供后续反证据召回）**")
            for paper in excluded:
                st.markdown(f"- `{paper.paper_id}` {paper.title}  \n  {paper.reason}")
        return

    for hit in dataset.falsification:
        st.markdown(f"### `{hit.hit_id}` · {hit.threat.value} / {hit.threat_level.value} / {hit.status.value}")
        st.write(hit.reason)
        st.caption(
            f"target_claim={hit.target_claim} · paper_id={hit.paper_id} · reverse_query={hit.reverse_query}"
        )
        st.info("任务差异：该命中来自通用 RAG/QA 风险文献，不是科学文献综述/问答的致命反证，威胁等级为 overlap。")
        st.markdown(f"snippet: {hit.snippet}")
        st.markdown(f"locator: `{hit.locator.model_dump(exclude_none=True)}`")
