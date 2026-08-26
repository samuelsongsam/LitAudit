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
    st.caption("主线来自 PaperCard 的 task/method。没有核验过的引用关系时，边保持空，不推断。")
    for note in map_payload.get("limitations", []):
        st.warning(note)

    tracks = map_payload.get("tracks") or []
    if tracks:
        st.markdown("**摘要级主线候选**")
        for track in tracks:
            st.markdown(f"- **{track['label']}**：{', '.join(f'`{pid}`' for pid in track.get('paper_ids', []))}")
    else:
        st.info("还没有可展示的主线。")

    st.markdown("**关系边**")
    edges = map_payload.get("edges") or []
    if edges:
        st.write(edges)
    else:
        st.info("关系边为空。等待全文/引用数据后再接入，当前不生成推断边。")

    papers = dataset.papers
    if not papers:
        return
    selected = st.selectbox(
        "选择论文节点",
        options=[paper.paper_id for paper in papers],
        format_func=lambda paper_id: next(
            (f"{paper.paper_id} · {paper.decision.value} · {paper.title}" for paper in papers if paper.paper_id == paper_id),
            paper_id,
        ),
    )
    paper = next(item for item in papers if item.paper_id == selected)
    card = dataset.card_by_id().get(selected)
    color = DECISION_COLOR[paper.decision.value]
    parse_status = card.parse_status if card else None
    parse_error = card.parse_error if card else None
    fields = card.fields if card else None
    st.markdown(
        f"<div style='border:1px solid {color}; padding:1rem;'>"
        f"<strong>{paper.paper_id}</strong> · {paper.decision.value}<br>"
        f"{paper.title or '（标题为空）'}<br>"
        f"parse_status={parse_status}"
        f"</div>",
        unsafe_allow_html=True,
    )
    if parse_error:
        st.caption(parse_error)
    if fields:
        st.markdown("**结构化字段（摘要级，未补造数值）**")
        st.write(
            {
                "task": fields.task,
                "method": fields.method,
                "data": fields.data,
                "metrics": fields.metrics,
                "limitations": fields.limitations,
            }
        )
    st.markdown("**筛选理由**")
    st.write(paper.reason)
    if paper.url:
        st.markdown(f"[打开来源]({paper.url})")
