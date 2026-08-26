# 反证据规则（v0.1）

## 目标
反证据模块针对 Claim 的强断言寻找削弱、冲突或适用范围边界。它不能把通用 RAG 风险自动升级为科学文献任务的致命反证。

## 命中分类
- fatal：同一研究对象、同一任务和相近评价设置下，可靠原文直接反驳目标 Claim。
- overlap：任务或对象高度重叠，原文显示失败、矛盾或不稳定，但仍存在设置差异。
- distinguishable：论文只在相邻任务/对象中提供风险，能够提醒边界但不能直接推翻目标 Claim。

## 判决规则
1. 每条 FalsificationHit 必须关联存在的 target_claim 和 paper_id。
2. 必须保存原文摘录、section/page/paragraph/url_anchor 等定位、反向查询 ID 和威胁理由。
3. 通用 QA/RAG 风险只能先标 overlap 或 distinguishable，除非全文证明任务和设置与目标 Claim 相同。
4. 若正向证据与反向证据冲突，目标 Claim 状态必须为 pending，不能强行判 supported。
5. exclude 论文仍可作为反证据来源，不得从候选和日志删除。

## 当前命中
- hit-001：paper-006 报告相关上下文下仍有 unsupported information/contradictions，打击 claim-008，威胁 overlap/high。
- hit-002：paper-007 报告不存在来源和上下文归因失败，打击 claim-008，威胁 overlap/high。

两条命中均为摘要级证据，尚未完成全文页码核验；目标 Claim 因正反方向冲突保持 pending。
