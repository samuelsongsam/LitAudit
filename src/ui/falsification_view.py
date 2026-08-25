from __future__ import annotations

import streamlit as st

from src.schema import Dataset


def render_falsification(dataset: Dataset) -> None:
    st.subheader("证伪报告")
    st.caption("反证据模块会保留 exclude 论文，允许重新召回。威胁等级：fatal / overlap / distinguishable。")

    if not dataset.falsification:
        st.warning("当前 run 没有 falsification.jsonl。真实杀手论文检出要等 A 完成反向检索后再接入。")
        excluded = [paper for paper in dataset.real_papers() if paper.decision.value == "exclude"]
        if excluded:
            st.markdown("**已保留的排除论文（可供后续反证据召回）**")
            for paper in excluded:
                st.markdown(f"- `{paper.paper_id}` {paper.title}  \n  {paper.reason}")
        return

    for hit in dataset.falsification:
        st.markdown(f"### `{hit.hit_id}` · {hit.threat.value} / {hit.threat_level.value} / {hit.status.value}")
        st.write(hit.reason)
        st.caption(f"target_claim={hit.target_claim} · paper_id={hit.paper_id}")
        st.markdown(f"snippet: {hit.snippet}")
        st.markdown(f"locator: `{hit.locator.model_dump(exclude_none=True)}`")
