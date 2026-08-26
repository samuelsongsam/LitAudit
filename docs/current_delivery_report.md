# LitAudit 当前交付报告

版本：current-2026-08-26  
交付方向：A（研究与可信度） -> B（产品与工程）  
研究范围版本：`v0.1`  
数据状态：以本报告和 `runs/phase2-real/` 为当前准；更早报告均为历史记录。

## 1. 当前结论

LitAudit 当前已具备可校验、可离线运行、可回放的摘要级研究闭环：研究范围 -> 检索记录 -> 候选去重/筛选 -> PaperCard -> Claim/Evidence -> 反证据 -> 小型评测。A 的规定交付文件已齐全，B 的数据契约、离线 pipeline、回放和四屏 UI 基础已接入。

当前交付不是全文级研究结论，也不是正式模型效果评测。证据升级仅覆盖本地 PaperQA PDF 的 3 条 Evidence；其余 7 条仍是摘要级。研究地图的真实关系边和矛盾对仍为空，不能推断引用关系。

## 2. 当前数据规模

| 对象 | 数量/状态 |
|---|---:|
| 检索式 | 4 |
| 候选论文 | 7 |
| 论文筛选 | include 2 / exclude 5 / pending 0 |
| PaperCard | 7 |
| ScreeningLog | 12 |
| Claim | 8 |
| Claim 状态 | supported 5 / partial 1 / pending 2 / unsupported 0 |
| Evidence | 10 |
| Evidence 提取状态 | verified 3 / abstract_only 7 |
| FalsificationHit | 2 |
| RetrievalRun | 14，其中失败/限流 5 |
| 评测题目 | 3 |

排除论文必须继续保留，其中 `paper-006`、`paper-007` 被反证据模块引用。`claim-008` 因正向与反向摘要证据冲突保持 `pending`。

## 3. A 已交付内容

- A-01：`docs/research_scope.md`，固定唯一主问题、纳排标准和词表。
- A-02：`data/search_queries.json`，主检索、扩展、任务限定和反向风险检索式。
- A-03：`data/papers.jsonl`、`data/screening_log.jsonl`，稳定 ID、去重键和可复核理由。
- A-04：`data/paper_cards.jsonl`，7 张结构化论文卡片。
- A-05：`data/claims.jsonl`、`data/evidence.jsonl`，8 条 Claim、10 条 Evidence。
- A-06：`data/claim_decisions.jsonl`，支持/部分支持/待定判决和理由。
- A-07：`data/falsification.jsonl`、`docs/falsification_rules.md`，2 条反证据命中和规则。
- A-08：`data/gold_standard/questions.jsonl`、`scripts/evaluate.py`、`docs/evaluation.md`，3 个评测题目和可重算指标。
- 研究约束与操作审计：`docs/data_contract.md`、`docs/agent_log.md`、`docs/current_blockers_report.md`。

## 4. B 当前可接续内容

B 当前可以直接读取 `data/` 并运行真实离线快照 `runs/phase2-real/`。pipeline 已读取并快照 `paper_cards`、`claim_decisions`、`retrieval_runs`；UI 已有筛选漏斗、研究地图、证据卡和证伪报告基础视图。

建议 B 立即检查：

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline --run-id phase2-real
python -m src.cli replay phase2-real
python -m pytest -q
python scripts/evaluate.py
```

当前已验证结果：`pytest 12 passed`、`doctor ok=true`、`validate error_count=0`、离线 run 成功、评测脚本成功。

## 5. 可信度和不可改写规则

- 研究结论必须沿 `Claim -> Evidence -> PaperCard` 回溯。
- Evidence 必须保留 `paper_id`、原文摘录和 locator。
- `abstract_only` 不得显示为全文核验；`verified` 仅表示对应摘录和定位已经核验，不代表整篇论文完成审阅。
- 没有有效 Evidence 或存在规则/模型冲突的 Claim 必须保持 `pending`。
- B 不得改写 `paper_id`、`claim_id`、`evidence_id`、`decision`、`status`、`snippet`、`locator` 的含义。
- 排除论文不得从数据和日志删除；fixture 不得计入真实统计。

## 6. 当前未完成事项

1. 其他论文的全文 PDF/HTML 获取、逐页人工审阅和页码级证据。
2. PaperQA PDF 其余页面的实验表格、设置、限制和结论逐项核验；当前只完成第 1-2 页三条 Evidence。
3. Semantic Scholar HTTP 429 限流后的多源交叉检索。
4. OpenAlex 部分 arXiv external ID 查询适配修正。
5. 无检索 baseline、完整全文 gold standard 和正式模型效果评测。
6. A 对 B 四屏 UI 的逐条可信度抽查，以及固定交付阶段 7 的端到端验收。
7. 阶段 8 的联合交付包、正式录屏和导师审阅材料。

这些事项的失败原因和后续建议见 `docs/a_remaining_work_report.md` 与 `docs/current_blockers_report.md`。在条件满足前，B 应使用现有缓存和离线 run 继续开发，不以空结果代替失败，也不把摘要级证据升级成全文结论。

## 7. 验收签字建议

A 可确认：研究范围、数据契约、候选筛选、摘要级 Claim/Evidence、反证据和评测入口已交付。B 应确认：当前数据可读、离线 run 可回放、四屏能显示状态和限制；双方共同确认后才能进入端到端产品验收与联合交付。

## 8. 报告版本说明

本文件是当前唯一有效的综合交付报告。以下文件保留为历史记录，不应作为当前统计依据：

- `docs/向B交接报告.md`：之前的 A -> B 交接报告；
- `docs/a_progress_report.md`：之前的 A 阶段进度审计；
- `docs/a_remaining_work_report.md`：之前的 A 剩余工作报告；
- `docs/a_acceptance_report.md`：之前的 B 工程骨架验收；
- `docs/agent_handoff_to_B.md`：之前的交接兼容索引；
- `docs/agent_handoff_to_A.md`：之前的 B -> A 交接记录。

操作流水线和版本变化仍以 `docs/agent_log.md` 为准。
