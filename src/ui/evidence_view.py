from __future__ import annotations

import streamlit as st

from src.schema import ClaimStatus, Dataset


def render_evidence(dataset: Dataset) -> None:
    st.subheader("论断-证据卡")
    st.caption(
        "没有 Evidence 的 Claim 不能显示为 supported。"
        "当前证据均为 abstract_only：只核验摘要摘录与 locator，不是全文页码级证据。"
    )

    if not dataset.claims:
        st.warning("当前 run 没有 claims.jsonl。这里只显示空状态，不生成综述。")
        return

    decisions = {item.claim_id: item for item in dataset.claim_decisions}
    for claim in dataset.claims:
        badge = claim.status.value
        st.markdown(f"### `{claim.claim_id}` · {badge}")
        if claim.status == ClaimStatus.supported:
            st.success(claim.text)
        elif claim.status == ClaimStatus.pending:
            st.warning(claim.text)
        elif claim.status == ClaimStatus.unsupported:
            st.error(claim.text)
        else:
            st.info(claim.text)
        st.caption(claim.decision_reason)
        decision = decisions.get(claim.claim_id)
        if decision:
            st.caption(f"判决账本：{decision.status.value} · reviewer={decision.reviewer} · {decision.reason}")

        related = [item for item in dataset.evidence if item.claim_id == claim.claim_id]
        if not related:
            st.error("没有 Evidence。按契约不得进入确定结论区。")
            continue
        for item in related:
            locator = item.locator.model_dump(exclude_none=True)
            locator_kinds = ", ".join(locator.keys())
            st.markdown(
                f"- **{item.verdict.value}** / `{item.extraction_status.value}` / 置信度 `{item.confidence.value}`  \n"
                f"  paper `{item.paper_id}` · locator 类型：`{locator_kinds}`  \n"
                f"  snippet: {item.snippet}  \n"
                f"  locator: `{locator}`"
            )
            if item.extraction_status.value == "abstract_only":
                st.caption("摘要级证据，不能当作全文已验证。")
