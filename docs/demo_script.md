# LitAudit 离线演示脚本（B 第二轮）

时长目标：约 6 分钟。展示真实摘要级数据，不把结果说成全文结论。

1. `python -m src.cli doctor`，确认 `ok=true`，7 篇候选，2 include / 5 exclude / 0 pending。
2. `python -m src.cli run --offline --run-id phase2-real`
3. `python -m src.cli ui --run-id phase2-real`
4. **筛选漏斗**：指出 PaperQA、SciMON 为 include；WebGPT、Toolformer、STORM 以及两篇风险论文为 exclude。打开筛选日志，说明有历史 pending 记录。指出 Semantic Scholar 429 是 `rate_limited`，不是零结果。
5. **研究地图**：展示摘要级主线（科学文献问答 vs 相邻自动科研 vs 任务边界）。点开 `paper-001`，看到 `parse_status=abstract_verified` 和 parse_error。强调关系边为空。
6. **证据卡**：打开 `claim-001`（supported）和 `claim-008`（pending）。指出 10 条证据都是 `abstract_only`，locator 是 abstract + url_anchor。
7. **证伪报告**：展示 `hit-001`、`hit-002`，说明它们是通用 RAG/QA 风险，不是对科学文献主问题的致命反证。
