# 勘文 / LitAudit 技术文档

**大赛：** 全球人工智能创新·治理·安全大赛  
**赛道：** 01 智能体应用  
**赛题：** 面向真实学术场景的深度研究智能体  
**系统：** 勘文（LitAudit）  
**范围版本：** v0.1  
**日期：** 2026-08-26

## 1. 问题与定位

现有文献智能体（Deep Research、STORM、普通 RAG 综述器）优化的是流畅度和引用数量。真实科研决策需要的是可核验性：论断能否点回原文、候选为何纳入或排除、领域里哪两条路线冲突、有没有能否定当前想法的反证据。

LitAudit 因此不写长综述。输入一个科研问题或待检验想法，输出四份可回放产物：

1. 系统评价式筛选漏斗  
2. 研究地图（主线、矛盾对、可回溯边）  
3. 论断–原文证据卡  
4. 反证据 / 证伪报告  

首期垂直领域固定为：大模型智能体 / 检索增强 / 自动科研文献问答。主研究问题是：

> 在自动科研文献综述或研究问答中，相比无外部检索的 LLM，检索增强大模型智能体是否提高证据可追溯性与事实/任务质量？

当前诚实结论：单篇 PaperQA 报告了 LitQA / PubMedQAblind 上的正向数字，但通用 RAG 文献同时报告相关上下文下仍有无支持信息、矛盾和归因失败。任务不统一，主问题级主张保持 `pending`。

## 2. 系统结构

```
用户问题
  -> 离线候选检索（当前版本不现场调用 API）
  -> 筛选漏斗（include / exclude / pending + 理由）
  -> PaperCard（task / method / data / metrics / limitations）
  -> Claim / Evidence / ClaimDecision
  -> 研究地图（主线 + 证据冲突边 + 矛盾对）
  -> 反证据命中（可召回 exclude 论文）
  -> 评测对照（可追溯性，不是准确率）
```

实现为可校验的 Python 包：`src/schema.py` 用 pydantic 卡住字段；`src/pipeline.py` 生成带 `run_id` 的离线快照；`src/replay.py` 回放；`src/ui/` 提供离线勘验工作台（漏斗、地图、证据、证伪、评测）。

硬规则：

- 研究结论必须沿 `Claim -> Evidence -> PaperCard` 回溯  
- 无 Evidence 不能 `supported`  
- 正反证据冲突必须 `pending`  
- `abstract_only` 不得显示成全文已验证；`verified` 只覆盖该摘录  
- exclude 论文不得删除（`paper-006/007` 被反证据引用）  
- HTTP 429 必须记为 `rate_limited`，不能当成零结果成功  
- fixture 不计入真实统计  

## 3. 当前数据与核验层级

| 对象 | 数量 / 状态 |
|---|---:|
| 候选论文 | 7 |
| 筛选 | include 2 / exclude 5 / pending 0 |
| ScreeningLog | 16（含全文部分核验记录） |
| PaperCard | 7 |
| Claim | 8（supported 5 / partial 1 / pending 2） |
| Evidence | 14，全部 `verified` 且有页码 |
| FalsificationHit | 2（overlap / high，打击 claim-008） |
| RetrievalRun | 14，失败/限流 5 |
| 评测题 | 3 |

本地 PDF：PaperQA、SciMON、RAG faithfulness、MIRAGE。`parse_status=pdf_partial_verified` 表示指定页摘录已核验，不是整篇逐页审阅完毕。STORM / WebGPT / Toolformer 仍是摘要级边界卡片，未升格为纳入证据。

## 4. 评测

评测比较的是证据可追溯性，不是模型分数。无检索代理不允许 locator，因此 locator / verified / 反证据覆盖率为 0；LitAudit 离线快照在同一金标准上给出可重算差值。脚本：`python -m src.cli evaluate`。

不报告：跨任务 Recall@50、因果元分析、闭卷 LLM 准确率。

## 5. 复现

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline --run-id phase2-real
python -m src.cli evaluate
python -m pytest -q
python -m src.cli ui --run-id phase2-real
```

## 6. 限制与后续

- 在线多源检索未接入 pipeline；Semantic Scholar 曾 429  
- 研究地图不是引用图谱  
- 未完成全部论文的逐页审阅  
- 主问题的普遍优越性主张保持 pending  

这些限制是产品的一部分：系统宁可停在 pending，也不生成无法点回原文的流畅综述。
