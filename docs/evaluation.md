# LitAudit 可复核评测

## 范围

评测题目和金标准位于 `data/gold_standard/questions.jsonl`。它们是基于当前仓库已核验证据建立的小型 gold fixture，用来检查漏斗、论断和反证据是否可回溯，不代表跨论文总体效果，也不替代独立人工金标准。

## 三个题目

1. 科学文献全文 RAG 问答：金标准 `paper-001`，Claim 为 `claim-001/002`。
2. 科学论文灵感检索与新颖性生成：金标准 `paper-003`，Claim 为 `claim-003/004`。
3. RAG 可信度反证：金标准 `paper-006/007`，Claim 为 `claim-006/007/008`。

## 指标

`python scripts/evaluate.py` 或 `python -m src.cli evaluate` 从仓库 JSONL 读取并输出 JSON。当前结果必须从脚本重算，不能手填。

仓库覆盖：

- `gold_paper_recall`：候选中命中金标准论文的比例
- `gold_claim_coverage`：Claims 中覆盖金标准 Claim 的比例
- `claim_evidence_link_rate`：有至少一条 Evidence 的 Claim 比例
- `supported_claim_rate` / `partial_claim_rate` / `pending_claim_rate`

可追溯性：

- `evidence_locator_rate`：Evidence 有 page/section/paragraph/char_range/url_anchor 的比例
- `page_locator_rate`：有 PDF 页码的比例
- `verified_evidence_rate`：`extraction_status=verified` 的比例
- `falsification_target_coverage`：被至少一条 FalsificationHit 命中的目标 Claim 比例

## 无检索对照

`baseline.name = no_external_retrieval_proxy` 是可追溯性代理，不是一次真实闭卷 LLM 考试：

- 无外部检索就不能产生 `paper_id` / locator，因此 locator、verified、claim-evidence 链接和反证据覆盖率均为 0
- LitAudit 离线快照在同一套金标准上报告上述比率
- `delta_vs_no_retrieval` 是两者之差

这只说明「系统能否把论断钉回原文」，不能解释成 RAG agent 的准确率、F1 或因果效应。`claim-008` 因正反证据冲突保持 pending，评测不得把它改写成 supported。

## 当前限制

- gold 是仓库内可复核集合
- `verified` 只表示对应摘录已对照本地 PDF 页码，不是整篇论文审阅完毕
- Semantic Scholar HTTP 429 仍记为失败，不进入召回成功统计
- 未报告模型生成质量分数
