# [历史版本] A -> B 交接（兼容索引）

> 本文件仅保留兼容旧引用；当前交付请以 `docs/current_delivery_report.md` 为准。

本项目的最新交接内容已迁移到 [向B交接报告.md](./向B交接报告.md)。请以该文件及 `docs/data_contract.md` 为准；本文件保留用于兼容既有引用。

- 研究范围：`v0.1`，主问题见 `docs/research_scope.md`。
- 当前真实数据：7 篇候选（include 2、exclude 5、pending 0），8 条 Claim，10 条摘要级 Evidence，2 条 FalsificationHit。
- 工程验收：pytest 10 passed；doctor `ok=true`；validate `error_count=0`；离线 run 位于 `runs/phase2-real/`。
- 主要限制：全文页码级证据、Semantic Scholar 429、OpenAlex 部分 external ID 404，以及 B 尚未接入 `paper_cards.jsonl`、`claim_decisions.jsonl`、`retrieval_runs.jsonl`。

B 的接入顺序、字段不可改写规则和验收命令详见新报告。
