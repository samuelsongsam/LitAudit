# [历史版本] A 工作完成与未完成报告

> 本文件是之前的剩余工作记录。当前交付请以 `docs/current_delivery_report.md` 为准。

日期：2026-08-26  
依据：《两人分工与交付计划.md》v0.1

## 已逐条完成

1. **A-01 研究范围**：已固定唯一主问题和 `scope_version=v0.1`，纳排标准、关键词、同义词、缩写、任务词和反向词已在 `docs/research_scope.md`。
2. **A-02 检索式**：已保存主检索、扩展检索、任务限定检索和风险检索；成功响应和失败/限流记录在 `data/cache/`、`data/retrieval_runs.jsonl`。
3. **A-03 候选与筛选**：已完成 7 篇候选的稳定 ID、去重键和筛选日志；2 include、5 exclude、0 pending。排除论文保留。
4. **A-04 PaperCard**：已完成 7 张卡片。新补充检查了本地 `paper-001.pdf`，20 页均可提取文本；没有全文缓存的论文仍保持摘要级状态。
5. **A-05 Claim/Evidence**：已将 PaperQA 的 `evidence-001`、`evidence-002` 升级为第 1 页 PDF 定位的 `verified` Evidence；`evidence-005` 升级为第 2 页 Introduction 定位的 `verified` Evidence。其余 Evidence 仍为 `abstract_only`，未补造页码。
6. **A-06 Claim 判决**：已同步更新 Claim-001、Claim-002 判决理由；Claim-005 虽有单篇 PDF 数值证据，仍因不能支持跨任务普遍结论而保持 `pending`。
7. **A-07 反证据**：2 条反证据命中和规则已保留；风险论文不删除、不改成纳入。
8. **A-08 评测**：3 个问题、gold standard、指标脚本和说明已可重算；明确标注仓库覆盖率不等于模型效果。

## 本轮验收

使用仓库配套 Python 3.12.13：

```text
pytest: 12 passed
doctor: ok=true
validate: error_count=0, issues=[]
evaluate.py: 成功
```

当前规模：7 papers、7 paper_cards、8 claims、10 evidence、2 falsification hits。Evidence 中 3 条为 `verified`（PaperQA PDF 页码级），7 条仍为 `abstract_only`。

## 当前不能完成或需要后续人工/外部条件的事项

1. **其他论文的全文页码级证据**：当前没有可核验本地 PDF/HTML，不能凭摘要或网络失败补造页码。需要重新获得公开全文并逐页提取、人工核对。
2. **PaperQA 全文逐页人工审阅**：PDF 已可提取 20 页，但本轮只核验了第 1-2 页的三条 Evidence；表格、实验设置、限制和全部结论仍需人工逐页审阅。
3. **Semantic Scholar 交叉检索**：HTTP 429 限流；需等待窗口、遵守速率限制或使用合规访问后重跑。
4. **OpenAlex external ID 适配**：部分按 arXiv 标识的路径返回 404；需修正查询适配并保留现有 arXiv 主记录。
5. **正式效果评测**：缺少无检索 baseline、独立系统输出和完整全文 gold standard，当前脚本不能报告模型准确率、因果效果或正式 Recall@50。
6. **B 端端到端可信度复核**：A 尚未逐屏抽查 UI 是否同时显示 `abstract_only`、`verified`、`pending`、`exclude`、失败记录及回溯链；需 B 提供可运行界面或截图/回放后复核。

上述事项属于资料、网络或后续工程验收限制，不是用空结果替代成功。B 可继续使用当前缓存、fixture 和 `runs/phase2-real/` 开发；任何新增证据必须沿 `Claim -> Evidence -> PaperCard` 回溯并保留原文定位。
