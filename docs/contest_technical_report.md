# 勘文 / LitAudit 技术文档

**大赛：** 全球人工智能创新·治理·安全大赛  
**赛道：** 01 智能体应用  
**赛题：** 面向真实学术场景的深度研究智能体  
**系统：** 勘文（LitAudit）  
**范围版本：** v0.1  
**日期：** 2026-08-29

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
  -> 在线/离线候选检索
  -> 筛选漏斗（include / exclude / pending + 理由）
  -> PaperCard（task / method / data / metrics / limitations）
  -> Claim / Evidence / ClaimDecision
  -> 研究地图（主线 + 证据冲突边 + 矛盾对）
  -> 反证据命中（可召回 exclude 论文）
  -> 评测对照（可追溯性，不是准确率）
  -> 研究工作区上下文与结构化审计报告
```

实现为可校验的 Python 包：`src/schema.py` 用 pydantic 卡住字段；`src/pipeline.py` 生成带 `run_id` 的离线快照；`src/replay.py` 回放；`src/ui/` 提供离线勘验工作台（漏斗、地图、证据、证伪、评测）。

工作台顶部显示当前研究问题、scope 版本、run 状态规模、页码证据数和待处理项。左侧 01–05 按“检索与筛选 -> 研究地图 -> 证据核验 -> 反证检查 -> 可追溯性评测”组织。研究地图使用 SVG Graph：论文以方框节点展示，现有 `evidence_conflict` 和 `falsification` 关系以带方向的箭头展示；支持力导向动态布局、拖动节点、平移/缩放画布、重置/适配布局以及点击节点和箭头查看详情。布局引擎按论文框实际矩形执行多轮碰撞校正；曲线起止点取源框和目标框边界交点。同一论文对存在多类关系时使用不同曲率分轨，箭头帽与实线冲突边或虚线反证边保持同色。`GET /api/run/<run_id>/report` 和 UI 的“下载审计报告”会生成结构化 Markdown，包含 Claim/Evidence 索引、反证据、检索失败、人工待处理项和限制；它不生成未经核验的长综述。

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

打开工作台后，选择“更多 -> 下载审计报告”可导出当前 run。进入研究地图可以拖动论文节点，点击箭头查看关系详情；拖动后箭头会重新计算方框边界锚点，`重新布局` 会再次执行矩形避碰。在线检索产生新的 `live_...` run，不覆盖 `phase2-real`；报告、工作区上下文和图谱都保留 `claim-008=pending`、反证据及 HTTP 429 失败记录。当前没有已核验引用关系，因此图谱不把关键词相似度或引用关系臆测成箭头。

## 6. 限制与后续

### 对话式研究入口（当前实现）

默认入口现为对话首页。每轮消息先按 `skills/conversational-research-routing/SKILL.md` 规定的契约交给 DeepSeek 等 OpenAI 兼容 LLM 判断，区分新主题、当前 run 追问、指定论文探索、分支深入、重新检索和范围澄清；需要新文献时创建新的 `live_*` run，当前结果追问复用已有数据。路由、澄清题、直接回答和总论均由 LLM 组织，输入受限于当前 run 的问题、论文、Claim、Evidence、反证和统计；无配置或失败时只返回 AI 服务状态，不显示固定问题或模板答案。对话记录保存到 `output/conversation.json`。回复按总论、论文列表、研究地图和三个原有核验模块入口组织，后三个模块本轮仍沿用原实现，未接入新的自动核验逻辑。

在线自定义主题使用本轮问题生成的来源适配查询，不再强制套用首期 RAG 查询与筛选条件。中英混合问题会生成精简英文检索式；自定义标题摘要筛选依据本轮主题词项，GPU 微架构等明确领域可增加型号与技术信号约束。live 回复只向 LLM 和地图暴露本轮新增论文，继承的基准数据继续留在审计 run 中但不会冒充当前主题结果。
对话页的输入栏固定在对话内容底部，长对话滚动时仍可继续追问；切换到原有审计视图时，顶部检索栏保持原布局。
对话首页移除了与输入栏重复的顶部研究问题框，并提供“新建对话”和“历史对话”管理。历史列表通过 `/api/conversations` 获取，删除通过 `DELETE /api/chat/<run_id>` 仅移除 `output/conversation.json`，不删除该 run 的候选论文、Evidence 或地图快照。
对话中的“本轮相关论文”使用当前消息的 `ask` 关键词重叠结果过滤；当前 run 中保留的基准论文不会自动全部展示。指定论文探索只返回目标论文；没有匹配时明确显示零结果，并保留 run 数据供审计查看。
对话回复同时读取当前 live run 的检索状态。若来源失败或限流，会显示失败来源并明确提示不能据此判断没有相关论文；因此“零匹配”和“检索不可用”在 UI 上不会混淆。
当前对话总论使用 DeepSeek 的 OpenAI 兼容 Chat Completions 接口；密钥只通过本地 `.env` 注入。LLM 负责组织和解释结构化结果，不负责绕过本地 Skill 路由、筛选规则或 Claim -> Evidence 证据闸门。
真实调用验收已通过；无 Key/请求失败路径只验证 `llm_error` 状态，不调用固定模板。

连续追问采用双层路由契约：LLM 先给出 `direct_answer / clarify / retrieve`，同时标记 `follow_up / paper_explore / branch_deepen / requery / new_topic`。服务端据此选择当前 run 数据或在线检索工具，并校验检索完成后必须存在可回放 run；客户端不会把无 run 的直接回答或澄清误当作检索结果。

- 在线多源检索未接入 pipeline；Semantic Scholar 曾 429  
- 研究地图不是引用图谱  
- 未完成全部论文的逐页审阅  
- 主问题的普遍优越性主张保持 pending  

这些限制是产品的一部分：系统宁可停在 pending，也不生成无法点回原文的流畅综述。
