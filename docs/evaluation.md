# LitAudit 第一批可复核评测

## 范围

评测题目和金标准位于 data/gold_standard/questions.jsonl。它们是基于当前已核验摘要建立的小型 gold fixture，不代表跨论文总体效果，也不替代全文人工金标准。

## 三个题目

1. 科学文献全文 RAG 问答：金标准 paper-001，Claim 为 claim-001/002。
2. 科学论文灵感检索与新颖性生成：金标准 paper-003，Claim 为 claim-003/004。
3. RAG 可信度反证：金标准 paper-006/007，Claim 为 claim-006/007/008。

## 可重新计算指标

scripts/evaluate.py 从仓库 JSONL 读取并输出 JSON：

- gold_paper_recall：候选 PaperCard 中命中金标准论文的比例；
- gold_claim_coverage：Claims 中覆盖金标准 Claim 的比例；
- evidence_locator_rate：Evidence 中有 section/page/paragraph/char_range/url_anchor 定位的比例；
- claim_evidence_link_rate：有至少一条 Evidence 的 Claim 比例；
- supported_claim_rate：Claim.status=supported 的比例；
- pending_claim_rate：Claim.status=pending 的比例；
- falsification_target_coverage：被至少一条 FalsificationHit 命中的目标 Claim 比例。

当前结果必须从脚本重新计算，不能手填。由于没有 baseline run、完整全文金标准或统一任务集，本阶段不报告模型准确率、因果效果或跨任务 Recall@50。
