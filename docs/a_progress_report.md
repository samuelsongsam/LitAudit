# [历史版本] A 阶段工作进度报告

> 本文件是之前的阶段审计。当前交付请以 `docs/current_delivery_report.md` 为准。

审计日期：2026-08-26  
依据：《两人分工与交付计划.md》v0.1  
审计角色：A（研究与可信度负责人）

## 总结

A-01 至 A-08 的规定产出均已建立并通过当前数据契约校验。A-03、A-04、A-05、A-06、A-07 的研究证据目前是摘要级，不应表述为全文核验。当前真实数据为 7 篇候选论文（include 2、exclude 5、pending 0）、7 张 PaperCard、8 条 Claim、10 条 Evidence、2 条 FalsificationHit 和 3 个评测问题。

## 逐项状态

### A-01 研究问题与范围：已完成

文件：`docs/research_scope.md`。已固定垂直领域“LLM agents / RAG / 自动科研文献综述与科学研究问答”，唯一主问题为比较检索增强智能体与无外部检索 LLM 在证据可追溯性和事实/任务质量上的差异。纳入、排除、时间范围、论文来源、词表、歧义词和不覆盖项均已写入，范围版本为 `v0.1`。

### A-02 检索式：已完成

文件：`data/search_queries.json`。共有 4 条查询，分别覆盖主检索、同义词/缩写扩展、任务限定和反向风险检索，并记录 source、date、scope_version 和 notes。arXiv、OpenAlex 的成功响应已缓存；Semantic Scholar 的 HTTP 429 已记录，不能当作零结果。

### A-03 候选、去重与筛选：已完成（摘要级）

文件：`data/papers.jsonl`、`data/screening_log.jsonl`。7 篇论文均有稳定唯一 `paper_id`、`dedup_key`、来源、decision 和人工可复核 reason；筛选日志 12 条，覆盖所有论文并保留后续核验记录。状态为 include 2、exclude 5、pending 0。排除论文没有删除，风险论文仍可供反证据模块召回。

### A-04 论文卡片：已完成（摘要级）

文件：`data/paper_cards.jsonl`。7 张卡片包含 task、method 等结构化字段以及 `parse_status`/`parse_error`。当前所有卡片为 `abstract_verified`；全文 PDF/HTML、实验表格和页码定位尚未完成，因此该项不能升级为全文完成。

### A-05 原子 Claim 与 Evidence：已完成（摘要级）

文件：`data/claims.jsonl`、`data/evidence.jsonl`。8 条 Claim 均有证据关联，10 条 Evidence 均保留 `paper_id`、原文摘录和 locator。当前 locator 为摘要 section 和 URL anchor；没有伪造页码，全文级要求仍未满足。

### A-06 Claim 可信度判决：已完成（受证据层级限制）

文件：`data/claim_decisions.jsonl`。状态统计为 supported 5、partial 1、pending 2、unsupported 0。没有 Evidence 的 Claim 未被判为 supported；主问题级强断言因正反证据和任务差异冲突保持 pending。

### A-07 反证据规则与命中：已完成（摘要级）

文件：`data/falsification.jsonl`、`docs/falsification_rules.md`。已建立 2 条风险命中，分别保留通用 RAG faithfulness 和 attribution 风险。命中论文为 exclude，但不可删除；其作用是削弱或限定主问题结论，而不是作为首期科研任务纳入样本。

### A-08 评测集与指标：已完成入口，正式效果评测未完成

文件：`data/gold_standard/questions.jsonl`、`scripts/evaluate.py`、`docs/evaluation.md`。已有 3 个评测问题，脚本可重算 gold paper recall、claim coverage、locator/link rate 和状态比例。当前结果为 gold paper recall 1.0、gold claim coverage 1.0、evidence locator rate 1.0、claim-evidence link rate 1.0；这些是仓库覆盖率，不是模型准确率。尚无无检索 baseline、完整全文 gold standard 或独立模型输出对照。

## 本次验收结果

已使用仓库配套 Python 3.12.13 执行：

```text
pytest: 12 passed
doctor: ok=true
validate: error_count=0, issues=[]
evaluate.py: 执行成功，question_count=3
```

## 尚未完成事项

1. 全文 PDF/HTML 解析、页码/段落级 Evidence 和实验指标核验。
2. Semantic Scholar 在限流窗口恢复后进行多源交叉核验。
3. OpenAlex 部分 arXiv external ID 查询适配修正。
4. 无检索 baseline、完整全文 gold standard 和正式模型效果评估。
5. A 对 B 四屏 UI 的逐条可信度抽查，以及第 7 阶段端到端验收。

以上事项不是已完成工作的隐瞒项。全文下载失败、HTTP 429 和 OpenAlex 404 的原因已记录在 `docs/current_blockers_report.md` 与 `data/retrieval_runs.jsonl`；在限制解除前，B 应继续使用缓存和离线 run，不得把摘要级证据显示为全文结论。

## 交给 B 的下一步

B 应先运行 `python -m src.cli doctor`、`python -m src.cli validate` 和 `python -m pytest -q`，再对 `runs/phase2-real/` 的漏斗、地图、证据卡和证伪报告进行真实数据检查。重点确认 `abstract_only`、`pending`、`exclude`、失败记录和 `Claim -> Evidence -> PaperCard` 回溯链均可见且不可被 UI 改写。
