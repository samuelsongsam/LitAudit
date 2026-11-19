# 当前未完成事项与处理建议

更新时间：2026-08-26 20:30 (+08:00)
综合状态以 `docs/current_delivery_report.md` 为准。本文件只保留仍未完成的限制，避免把已完成项继续当成阻塞。

## 已完成（不再作为阻塞）

- 指定页 PDF 核验：paper-001/003/006/007 本地 PDF 可提取；14 条 Evidence 均为页码级 `verified`。
- 研究地图：已由 Evidence 冲突和 FalsificationHit 生成边与矛盾对，不推断引用图。
- 评测：`python -m src.cli evaluate` 输出仓库覆盖率与无检索可追溯性代理对照。
- UI：漏斗 / 地图 / 证据卡 / 证伪 / 评测五屏；顶栏本地问题检索。
- 比赛底稿：技术文档、演示脚本、提交清单已写入 docs/。

## 仍未完成

1. STORM / WebGPT / Toolformer 无本地 PDF，保持摘要级边界卡片。
2. 已有 PDF 未做逐页审阅；SciMON 未抽取完整实验表。
3. Semantic Scholar HTTP 429 与 OpenAlex 部分 external ID 适配未修复；pipeline 仍只离线读取。
4. 评测不是闭卷 LLM 准确率，也不是正式模型效果实验。
5. 比赛提交包（PDF、视频、ZIP）需按 `docs/submission_checklist.md` 人工导出和录屏。
