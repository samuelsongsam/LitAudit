# LitAudit 离线演示脚本（B 第一轮）

时长目标：不超过 5 分钟。本轮证明工程可回放，不证明文献结论。

1. 打开终端，进入仓库根目录，执行 `python -m src.cli doctor`，确认 A 的数据文件存在、校验为 0 error。
2. 执行 `python -m src.cli run --offline`，记下 `run_id`。
3. 执行 `python -m src.cli ui`，选择刚生成的 run。
4. **筛选漏斗**：指出 5 篇真实候选，3 pending / 2 exclude / 0 include；点开 `paper-001` 的 reason，以及 `paper-004` 的 `reason_code=general_web_qa`。强调 authors/abstract 显示为 null。
5. **研究地图**：点击 `paper-001` 打开卡片。说明主线和矛盾对尚未生成，因为 A 还没有 `paper_cards.jsonl`。
6. **证据卡**：展示空状态文案，说明系统拒绝在没有 Evidence 时写确定结论。
7. **证伪报告**：展示空状态，同时列出两条 exclude 论文仍被保留，供后续反证据召回。
8. 可选：再跑 `python -m src.cli run --fixture --run-id demo`，切到 demo run，指出 fixture 的 Claim/Evidence/Hit 只用于字段演示，不计入真实统计。
