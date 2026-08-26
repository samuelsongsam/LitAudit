# LitAudit 当前交付报告

版本：current-2026-08-26-full  
数据状态：以本报告和 `runs/phase2-real/` 为当前准；更早报告均为历史记录。

## 1. 当前结论

LitAudit 已形成可离线运行、可回放、可抽查的研究闭环：固定主问题 -> 检索记录 -> 筛选漏斗 -> PaperCard -> Claim/Evidence -> 研究地图冲突边 -> 反证据 -> 可追溯性评测 -> 五屏 UI。

当前交付**不是**跨任务因果结论，也**不是**全文逐页审阅完毕。`verified` 只表示对应摘录已对照本地 PDF 页码。主问题级主张 `claim-008` 因正反证据冲突保持 `pending`。

## 2. 当前数据规模

| 对象 | 数量/状态 |
|---|---:|
| 检索式 | 4 |
| 候选论文 | 7 |
| 论文筛选 | include 2 / exclude 5 / pending 0 |
| PaperCard | 7；其中 4 张 `pdf_partial_verified` |
| ScreeningLog | 16 |
| Claim | 8 |
| Claim 状态 | supported 5 / partial 1 / pending 2 / unsupported 0 |
| Evidence | 14，全部 verified 且有页码 |
| FalsificationHit | 2，页码级 overlap |
| RetrievalRun | 14，其中失败/限流 5 |
| 评测题目 | 3 |

排除论文必须继续保留。`paper-006`、`paper-007` 被反证据引用。

## 3. 已完成

- 研究范围、数据契约、检索缓存、筛选日志
- PaperQA / SciMON / RAG faithfulness / MIRAGE 本地 PDF 与指定页摘录核验
- 研究地图：主线 + 证据冲突边 + 矛盾对（不推断引用图）
- 评测：仓库覆盖率 + 无检索可追溯性代理对照
- UI：漏斗、地图、证据卡、证伪、评测；顶栏本地问题检索
- 比赛材料底稿：`docs/contest_technical_report.md`、`docs/demo_script.md`、`docs/submission_checklist.md`

## 4. 验收命令

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline --run-id phase2-real
python -m src.cli evaluate
python -m pytest -q
python -m src.cli ui --run-id phase2-real
```

## 5. 仍未完成（诚实限制，不是失败隐藏）

1. STORM / WebGPT / Toolformer 无本地 PDF，保持摘要级边界卡片。
2. 已有 PDF 未做逐页审阅；SciMON 未抽取完整实验表。
3. Semantic Scholar 429 与 OpenAlex 部分 external ID 适配未修复；pipeline 仍只离线读取。
4. 评测不是闭卷 LLM 准确率，也不是正式模型效果实验。
5. 比赛提交包（PDF、视频、ZIP）需按 `docs/submission_checklist.md` 人工导出和录屏。

## 6. 可信度规则

- 结论必须沿 `Claim -> Evidence -> PaperCard` 回溯
- `pdf_partial_verified` / `verified` 不等于全文已读完
- 冲突必须 pending
- 429 不能记成零结果成功
- fixture 不计入真实统计
