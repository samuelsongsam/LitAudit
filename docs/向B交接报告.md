# [历史版本] 向 B 交接报告

> 本文件是 2026-08-26 较早的交接记录。当前统计和验收结果以 `docs/current_delivery_report.md` 为准。

交接方向：A（研究与可信度） -> B（产品与工程）  
交接日期：2026-08-26  
研究范围版本：`v0.1`  
项目目录：`E:\LitAudit`

## 1. 项目当前状态

LitAudit 已完成研究范围冻结、检索式设计、候选论文去重与摘要级筛选，并完成第一批摘要级 PaperCard、Claim、Evidence、反证据和评测 fixture。B 已完成离线读取、schema 校验、pipeline、replay、研究地图基础输出和 UI 骨架。当前可以进行真实数据的离线接入验收，但尚不能把结果描述为全文核验或模型效果结论。

首期唯一主问题是：**在自动科研文献综述或科学研究问答中，相比无外部检索的 LLM，检索增强大模型智能体是否提高证据可追溯性与事实/任务质量？** 垂直领域限定为 LLM agents、RAG 与自动科研文献综述/科学研究问答，不扩展到通用搜索、多学科产品比较或临床决策。

## 2. A 已完成事项（A-01 至 A-08）

| 阶段 | 状态 | 产出 |
|---|---|---|
| A-01 研究范围 | 完成 | `docs/research_scope.md`，含主问题、纳排标准、词表、歧义处理和不覆盖项 |
| A-02 检索式 | 完成 | `data/search_queries.json`，4 条可复用查询；arXiv/OpenAlex 有成功缓存，Semantic Scholar 受限 |
| A-03 候选与筛选 | 完成（摘要级） | 7 篇候选、稳定 ID、去重键和 12 条筛选记录 |
| A-04 PaperCard | 完成（摘要级） | `data/paper_cards.jsonl`，7 张卡片，含解析状态 |
| A-05 Claim/Evidence | 完成（摘要级） | `data/claims.jsonl` 8 条 Claim，`data/evidence.jsonl` 10 条 Evidence |
| A-06 Claim 判决 | 完成 | `data/claim_decisions.jsonl`，冲突的主问题强断言保持 `pending` |
| A-07 反证据 | 完成（摘要级） | `data/falsification.jsonl` 2 条 FalsificationHit，风险论文保留 |
| A-08 评测 fixture | 完成 | `data/gold_standard/questions.jsonl` 3 题、`scripts/evaluate.py`、`docs/evaluation.md` |

## 3. B 已完成事项（当前可复用工程）

B 已建立 `src/schema.py`、`src/io_utils.py`、`src/pipeline.py`、`src/replay.py`、`src/map_builder.py`、`src/cli.py`、`src/ui/` 及对应测试和 fixture。读取器会保留 `null` 元数据、`exclude/pending` 及理由；无效 JSONL、重复 ID、孤立外键、无 Evidence 的确定支持会被拒绝。

已执行验收：`pytest -q` 为 **10 passed**；`python -m src.cli doctor` 为 `ok=true`；`python -m src.cli validate` 为 `error_count=0`；真实离线 run `runs/phase2-real/` 成功生成。

## 4. 当前真实数据规模

| 对象 | 数量 | 说明 |
|---|---:|---|
| 候选论文 | 7 | fixture 不计入此数字 |
| `include` | 2 | `paper-001` PaperQA；`paper-003` SciMON |
| `exclude` | 5 | 含 2 篇用于反证据的风险论文，不能删除 |
| `pending` | 0 | 当前候选筛选无 pending；Claim 仍有 pending |
| ScreeningLog | 12 | 包含后续核验记录，不能只取第一条 |
| PaperCard | 7 | 全部 `abstract_verified`，不等于全文核验 |
| Claim | 8 | `supported=5`、`partial=1`、`pending=2`、`unsupported=0` |
| Evidence | 10 | 全部 `extraction_status=abstract_only` |
| FalsificationHit | 2 | 来自 `paper-006`、`paper-007` 的风险线索 |
| retrieval runs | 14 | 含成功请求和失败/限流记录 |

当前离线评测脚本输出的是仓库覆盖率，不是模型准确率或因果效果：`gold_paper_recall=1.0`、`gold_claim_coverage=1.0`、`evidence_locator_rate=1.0`、`claim_evidence_link_rate=1.0`、`supported_claim_rate=0.625`、`pending_claim_rate=0.25`、`falsification_target_coverage=0.125`。

## 5. 交付文件与用途

- `docs/research_scope.md`：唯一研究问题、纳入/排除标准和范围版本。
- `data/search_queries.json`：主检索、同义词扩展、任务限定、反向风险检索式。
- `data/papers.jsonl`：候选论文主记录；包含排除项和可复核理由。
- `data/screening_log.jsonl`：逐论文、逐阶段筛选审计记录。
- `data/paper_cards.jsonl`：摘要级结构化卡片和 `parse_status`。
- `data/claims.jsonl`、`data/evidence.jsonl`、`data/claim_decisions.jsonl`：论断、证据及判决链。
- `data/falsification.jsonl`、`docs/falsification_rules.md`：反证据命中和规则。
- `data/retrieval_runs.jsonl`、`data/cache/retrieval-2026-08-26/`：检索来源、HTTP 状态和原始响应缓存。
- `docs/data_contract.md`：字段类型、枚举、外键、降级和不可改写语义，B 实现以此为准。
- `docs/current_blockers_report.md`：未完成事项、失败原因和处理建议。
- `docs/agent_log.md`：A 的可审计操作记录。
- `runs/phase2-real/`：真实数据离线流水线快照；`runs/demo/`：fixture 演示快照。

## 6. B 应立即执行的接入工作

1. 扩展读取和快照：加载 `paper_cards.jsonl`、`claim_decisions.jsonl`、`retrieval_runs.jsonl`，并在 schema、pipeline、replay 中保留原字段。
2. 更新地图：使用 PaperCard 的 `task/method/data/metrics` 生成主线候选；没有真实关系边时显示空状态，不推断引用关系。
3. 更新证据卡：展示 10 条 `abstract_only` Evidence、定位类型和置信度，并明确摘要级限制。
4. 更新证伪报告：展示 `hit-001/hit-002`，标记其与自动科研主问题的任务差异。
5. 在 UI 中显示最新筛选状态：2 include、5 exclude、0 pending；保留每条 reason/reason_code。
6. 运行以下命令确认接入无回归：

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline --run-id phase2-real
python -m src.cli replay --list
python -m pytest -q
python scripts/evaluate.py
```

## 7. B 不得擅自改变的研究语义

- 不得修改 `research_scope.md` 的主问题、纳入/排除标准或 `scope_version`。
- 不得重命名、复用或重新解释 `paper_id`、`claim_id`、`evidence_id`、`snippet`、`locator`、`decision`、`status`。
- `abstract_only` 不得显示为全文已验证；不得补造页码、章节、指标或实验结果。
- 没有有效 Evidence 的 Claim 不得变成 `supported`；规则与模型冲突必须为 `pending`。
- `exclude` 论文不可删除，因为 `paper-006`、`paper-007` 被反证据模块引用。
- 所有结论必须沿 `Claim -> Evidence -> PaperCard` 回溯；fixture 必须与真实统计分离。

## 8. 已知限制与未解决问题

这些问题不是研究范围遗漏，而是当前网络、来源或工程接入尚未完成：

- 全文 PDF/HTML 解析、页码/段落定位和全文实验表格核验尚未完成。arXiv PDF 下载分别因连接超时和 `CRYPT_E_REVOCATION_OFFLINE` 失败，因此 10 条 Evidence 仅能支持摘要级判断。
- Semantic Scholar 请求返回 HTTP 429；不能把限流当成零结果。待限流窗口恢复或取得合规 API 访问后重跑并追加日志。
- OpenAlex free-text 检索成功，但部分按 arXiv external ID 的路径返回 404；需修正适配，不覆盖 arXiv 主记录。
- B 当前 pipeline 尚未接入新增的 PaperCard、Claim 判决和 retrieval run 文件；研究地图尚无经核验的主线、关系边和矛盾对。
- 尚无无检索 baseline、完整全文 gold standard 或正式模型效果评测；现有指标不能外推系统准确率、因果效果或跨任务 Recall。

在这些限制解除前，B 可以继续做离线读取、校验、展示和回放，但不得把摘要级结果升级成确定的全文研究结论。若网络仍不可用，使用 `data/cache/` 和现有离线数据继续开发；失败原因必须写入 `docs/agent_log.md` 或 `data/retrieval_runs.jsonl`。

## 9. 验收建议

B 完成接入后应确认：所有 JSON/JSONL 可解析；各类 ID 唯一；外键完整；每篇论文在筛选日志有记录；Evidence 均有摘录和 locator；状态枚举合法；fixture 不进入真实统计；`pending` 和冲突不会被 UI 或流水线强行改写。建议重新生成 `runs/phase2-real/`，检查 `stats.json` 与上述规模一致，并运行 10 个测试及评测脚本。

## 10. 需要 B 确认的问题

1. 是否同意将 `paper_cards.jsonl` 作为 PaperCard 的扩展输入，而以 `papers.jsonl` 继续作为候选主索引？
2. UI 是否能同时显示 `extraction_status=abstract_only`、locator 类型及证据置信度？
3. 地图在无真实关系边时是否按空状态呈现，并等待后续全文/引用数据，而不生成推断边？
4. B 接入后，是否可以在不改变字段语义的前提下提出 schema 版本 `v0.2` 修改建议？

## 11. 下一步顺序

先完成三类新增 JSONL 的读取和校验，再接入证据卡与反证据报告，随后更新研究地图和评测回放；最后再处理全文下载/解析、Semantic Scholar 限流和 OpenAlex external ID 适配。A 将继续负责研究语义、证据升级和筛选判决，B 负责工程实现与 UI 呈现。
