from __future__ import annotations

import streamlit as st

from src.schema import Dataset, PaperDecision


DECISION_COLOR = {
    PaperDecision.include.value: "#1f7a4c",
    PaperDecision.exclude.value: "#8a1f1f",
    PaperDecision.pending.value: "#8a6d1f",
}


def render_map(dataset: Dataset, map_payload: dict) -> None:
    st.subheader("研究地图")
    st.caption("第一轮只展示候选节点。主线和矛盾对将在 A 提供 paper_cards.jsonl 后接入，当前不编造结构。")
    for note in map_payload.get("limitations", []):
        st.warning(note)

    selected = st.selectbox(
        "选择论文节点",
        options=[paper.paper_id for paper in dataset.papers],
        format_func=lambda paper_id: next(
            (f"{paper.paper_id} · {paper.decision.value} · {paper.title}" for paper in dataset.papers if paper.paper_id == paper_id),
            paper_id,
        ),
    )
    paper = next(item for item in dataset.papers if item.paper_id == selected)
    color = DECISION_COLOR[paper.decision.value]
    st.markdown(
        f"<div style='border:1px solid {color}; padding:1rem;'>"
        f"<strong>{paper.paper_id}</strong> · {paper.decision.value}<br>"
        f"{paper.title or '（标题为空）'}<br>"
        f"year={paper.year} · authors={paper.authors} · abstract={paper.abstract}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("**筛选理由**")
    st.write(paper.reason)
    if paper.url:
        st.markdown(f"[打开来源]({paper.url})")

    st.markdown("**全部节点**")
    for item in dataset.real_papers():
        st.markdown(f"- `{item.decision.value}` `{item.paper_id}` {item.title}")
