# 当前未完成事项与处理建议

更新时间：2026-08-26 12:14 (+08:00)

## 本轮已完成

- A-02：arXiv 主检索和风险检索实际返回 HTTP 200；OpenAlex 扩展检索实际返回 HTTP 200；Semantic Scholar 访问被 429 限流并已记录。
- A-03：7 篇候选、稳定 ID、去重键和 12 条筛选日志；2 include、5 exclude、0 pending。
- A-04：7 张摘要级 PaperCard；标题、作者、摘要、来源和解析状态已填充。
- A-05/A-06：8 条 Claim、10 条 Evidence 和 claim_decisions；证据均保留 arXiv abstract URL anchor，主问题级强断言保持 pending。
- A-07：2 条摘要级 FalsificationHit 和反证据规则；风险论文保留为 exclude，不从候选中删除。
- A-08：3 个评测题目、gold fixture、指标说明和 scripts/evaluate.py；脚本可重新计算当前仓库指标。

## 当前不能完成或需要后续核验的事项

### 1. 全文页码级证据

- 状态：部分阻塞，不是研究范围排除。
- 当前证据：10 条均为 arXiv 摘要级 Evidence，locator 为 section=abstract + URL anchor。
- 尚未完成：PDF/HTML 全文解析、页码/章节/段落定位、全文实验表格核验。
- 追加尝试：授权下载 arXiv PDF 时，export.arxiv.org 连接超时；arxiv.org 主域名因 Schannel 证书吊销检查离线失败（CRYPT_E_REVOCATION_OFFLINE）。
- 处理：Claim 的 supported/partial 仅表示摘要直接支持；涉及数值、跨任务推广和因果效果的强结论保持 pending 或降级。

### 2. Semantic Scholar 多源交叉核验

- 状态：服务返回 HTTP 429 rate limited。
- 已尝试：候选单篇元数据、任务限定检索、风险检索。
- 处理：不把 429 当作零结果；当前以 arXiv 成功 XML 和 OpenAlex 成功缓存为主要来源。
- 后续：等待限流窗口或使用 API 要求的速率/凭证后重跑，并追加 retrieval_runs 记录。

### 3. OpenAlex 查询适配

- 状态：主机可达，free-text 扩展检索 HTTP 200；部分按 arXiv 标识的 works 路径返回 404。
- 处理：已保存成功的扩展和标题搜索响应；paper-001、paper-003、paper-004、paper-005 有对齐结果，paper-002 的标题搜索首条未对齐，仍以 arXiv XML 为准。
- 后续：修正 OpenAlex external ID/filter 适配，不覆盖 arXiv 主记录。

### 4. B 的完整 PaperCard 接入

- 状态：未完成。
- 原因：B 当前 pipeline 读取 papers.jsonl、claims/evidence/falsification，但尚未加载独立的 paper_cards.jsonl、claim_decisions.jsonl 和 retrieval_runs.jsonl。
- 处理：B 应扩展读取、快照、map/UI 和 schema；A 不直接改 B 的接口实现。

### 5. 评测基线和完整金标准

- 状态：入口已完成，正式效果评测未完成。
- 原因：当前只有摘要级 gold fixture，没有无检索 baseline、完整全文金标准或独立系统输出。
- 处理：当前脚本只报告仓库覆盖率、Evidence 定位率和状态比例，不报告模型准确率、因果效果或跨任务 Recall@50。

## B 当前可以继续做

- 接入 data/paper_cards.jsonl，并显示 parse_status/parse_error。
- 接入 data/claim_decisions.jsonl 和 data/retrieval_runs.jsonl。
- 将 2 篇 include、5 篇 exclude、0 篇 pending 和理由展示到漏斗。
- 在地图中使用 paper_cards 的 task/method/data/metrics 生成主线候选，但保留摘要级限制。
- 在证据卡展示 10 条 abstract-only Evidence 和 8 条 Claim 状态。
- 在证伪报告展示 hit-001/hit-002，并标注通用 RAG 任务差异。
