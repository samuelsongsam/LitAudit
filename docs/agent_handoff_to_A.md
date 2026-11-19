# [历史版本] B -> A 交接：第二轮真实数据接入

> 本文件是之前的 B -> A 交接记录；当前综合交付请以 `docs/current_delivery_report.md` 为准。

- 交接方向：B -> A
- 日期：2026-08-26
- 分支：`feat/b-phase2-ingest`

## 1. 本轮完成

1. 读取并快照 `paper_cards.jsonl`、`claim_decisions.jsonl`、`retrieval_runs.jsonl`。
2. `papers.jsonl` 仍是候选主索引；`paper_cards.jsonl` 是摘要级扩展卡片。
3. 漏斗展示 2 include / 5 exclude / 0 pending，以及全部 12 条筛选日志和 14 条检索运行。
4. 地图用 PaperCard 的 task/method 生成主线候选；关系边和矛盾对保持空，不推断引用。
5. 证据卡展示 8 条 Claim、10 条 `abstract_only` Evidence、locator 类型和置信度。
6. 证伪报告展示 `hit-001` / `hit-002`，并标明通用 RAG/QA 与自动科研主问题的任务差异。
7. HTTP 429 保持 `rate_limited`，不能写成零结果成功。

## 2. 对 A 四个问题的确认

1. 同意：`papers.jsonl` 是主索引，`paper_cards.jsonl` 是扩展输入。
2. 能：证据卡同时显示 `extraction_status=abstract_only`、locator 类型和置信度。
3. 是：无真实关系边时显示空状态，不生成推断边。
4. 可以：在不改变字段语义的前提下，后续再提 schema v0.2 建议。本轮没有改枚举含义。

## 3. 验收命令

```powershell
python -m pytest -q
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline --run-id phase2-real
python scripts/evaluate.py
python -m src.cli ui --run-id phase2-real
```

预期 stats：paper_count=7，include=2，exclude=5，pending=0，paper_card_count=7，claim_count=8，evidence_count=10，falsification_count=2，retrieval_run_count=14。

## 4. B 没有改动的内容

- 研究范围、纳排标准、论文判决、Claim 状态、Evidence 摘录。
- 未把 `abstract_only` 升级为全文 verified，未补造页码。

## 5. 仍交给 A / 后续的事项

- 全文 PDF 解析与页码级证据。
- Semantic Scholar 429 重跑。
- OpenAlex external ID 适配。
- 无检索 baseline 与正式效果评测。
