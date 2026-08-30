# LitAudit 当前交付报告

版本：current-2026-08-29-workspace
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
- UI 优化：顶部研究工作区上下文、连续审计导航、当前 run Markdown 审计报告导出
- 研究地图优化：SVG 论文关系图、方向箭头、动态力导向、节点拖动、画布缩放/平移、节点与关系详情联动
- 研究地图几何修正：论文框矩形避碰、箭头按方框边界计算起止点、同一论文对的多关系分轨、箭头帽颜色与关系类型一致
- 对话式研究入口：默认首页支持连续提问；意图路由区分新主题、当前 run 追问、指定论文探索、分支深入、重新检索和范围澄清；路由、澄清题、直接回答和总论均由配置的 OpenAI 兼容 LLM + Skill 生成，未配置或失败时不生成固定 fallback 内容
- 对话输入栏位于对话内容底部并在长对话中保持可用；原有审计页面继续保留顶部检索栏
- 对话首页移除重复的研究问题/范围大框，提供新建对话、历史对话加载和删除会话记录；删除不影响对应 run 的论文与证据
- 对话论文列表已改为按本轮问题匹配结果展示，不再把当前 run 的全部基准论文误当成本轮检索结果；同时显示本轮匹配数、在线新增数和 run 总数
- 在线检索状态在对话回复中显式区分：成功零匹配、部分检索源失败、全部检索源失败；失败/限流不能解释成没有相关论文
- 对话总论已配置 DeepSeek OpenAI 兼容接口；Key 仅存本地 `.env`，不进入源码和版本控制，LLM 仍受本地意图路由和 Claim -> Evidence 约束
- 检索前澄清已加入对话路由：短句、宽泛主题或研究边界不足时先追问，不创建 live run、不调用在线来源；收到对象、方法/现象、任务/比较和边界等必要信息后才扩展为检索请求
- 在线地图已与内部基准上下文分离：`live` run 只展示 `added_paper_ids` 对应的新论文和双方均为新增论文的关系；本地基准论文不删除，继续供筛选、反证和 LLM 上下文使用
- 对话路由已改为严格 LLM-first：Skill 规定路由契约和约束，DeepSeek 根据当前消息与上下文判断直接回答、需要澄清或可以检索；需要澄清时由 LLM 返回恰好 3 道单选题且每题 3 个选项，前端不显示总论/论文/地图格式；用户选择后以 `expanded_query` 检索，明确要求直接回答则不检索；LLM 不可用时仅返回服务状态，不使用固定问题或模板答案
- 自定义主题检索不会再强制加入默认 RAG 主线或风险检索式；原始主题和用户选择由 DeepSeek 合并为 `expanded_query` 后调用三类论文来源
- 已修复澄清选择提交后的结构化查询兼容问题：DeepSeek 返回对象形态的 `expanded_query` 会先按其原主题、选择和范围字段安全归一化为检索字符串，不再触发 `slice(None, 80, None)` 500；无法归一化时返回 AI 服务错误，不进入流水线
- DeepSeek 路由和总论调用对瞬时网络错误、超时、无效 JSON 及不满足 Skill 契约的返回自动重试一次；两次均失败才显示 AI 服务状态，仍不使用固定回答或固定选择题
- 自定义主题不再套用首期 RAG 专用筛选器：标题摘要按本轮扩展查询做主题相关性筛选；GPU 微架构主题进一步要求现代型号与微架构、ISA、缓存/内存层级等技术信号，只有型号但技术信号不足的论文保持 pending
- GPU 等中英混合问题会为 OpenAlex/Semantic Scholar生成精简英文查询，并为 arXiv 使用主题组合查询；不会再把 Hopper、Ada、RDNA、CDNA、NVIDIA、AMD 全部用 AND 强制同时出现
- live 总论、论文列表、地图和检索失败统计只读取本轮 `added_paper_ids` 与本轮检索记录；新增 0 篇时不再使用基准 7 篇 RAG 论文生成其他主题的总论
- 已完成真实 DeepSeek 调用验收：对 `phase2-real` 的 pending 追问返回 `LLM 总论`，保留证据冲突和 `claim-008=pending`；回归测试显式禁用外部 LLM，避免测试依赖密钥
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

## 5. 本轮优化已落地

- `src/ui/payload.py` 新增 workspace context：实际问题、scope 版本、run 时间、冲突、待定论文、摘要级论文和检索失败。
- `src/ui/static/app.js` 将 01–05 呈现为连续研究审计流程，并提供“下载审计报告”入口。
- `src/ui/server.py` 新增 `GET /api/run/<run_id>/report`。
- 报告只从快照生成结构化 Markdown，不越过 Claim -> Evidence -> PaperCard 证据闸门。
- `mapView` 已替换为 SVG Graph：论文是方框节点，`evidence_conflict` 是实线箭头，`falsification` 是虚线箭头；关系方向沿现有 `source -> target` 记录展示。
- 图谱支持节点拖动、空白区域平移、滚轮缩放、重新布局、适配视图、重置位置和布局按 run 保存；点击节点或边可查看对应详情。
- 图谱按 `208 x 88` 论文框执行矩形碰撞校正；箭头不再以节点左上角或框内固定偏移为锚点，而是沿曲线路径计算源框和目标框的边界交点。
- 同一 `source -> target` 同时存在 `evidence_conflict` 与 `falsification` 时，两条边使用不同曲率；实线冲突边、虚线反证边及其箭头帽保持同色。
- 当前图谱仍不推断引用网络；没有已核验引用边时只展示证据冲突和反证关系。
- 对话首页按“总论概览 -> 检索论文 -> 研究地图 -> 后续核验模块”组织回复；消息绑定 run 并保存到 `output/conversation.json`。当前 run 的事实追问不重复调用外部检索，明确扩展或重新检索才创建新的 `live_*` run。
- 证据核验、反证检查、可追溯性评测本轮仅保留原有视图和代码；对话底部显示保留入口，不在对话链路中重新实现。
- UI/报告回归测试已补充；当前环境使用捆绑 Python 验证为 51 passed。历史版本写入的固定澄清用户/助手消息只在显示层成对隐藏，原始审计文件不删除。
- 检索后追问协议已收紧：`follow_up` 和 `paper_explore` 可复用当前 run；`branch_deepen`、`requery` 和已明确的新主题调用在线检索并生成新 run；澄清不创建 run。前端只在 `run_id` 非空时加载结果，防止 `/api/run/null`。
- 对话回答新增安全 Markdown 渲染和阅读排版：先转义 LLM 内容，再识别有限的标题、段落、列表和行内强调；直接回答限制为 900px 阅读宽度。DeepSeek 提示词要求先给直接结论、按层级分段，并限制默认篇幅。
- UI 外观与会话隔离：左侧旧的五模块导航替换为历史对话工作区；每条会话支持切换、重命名、删除和新建。核验模块通过当前 run 的独立地址打开，删除只删除对话记录，不删除该 run 的论文、证据、反证和评测数据。
- 澄清题扩展：每个 DeepSeek 动态问题在三个 AI 选项之外增加“其他”，用户选择后填写自定义范围；前端逐题校验并将三项最终答案传回既有 `clarification_context`，不改变路由和查询归一化契约。
- 对话连续性修复：澄清后创建新 live run 时，客户端保留前序内存消息，服务端同时把前序消息写入新 run 的 `conversation.json`；新旧消息按角色和内容去重，确保当前显示、刷新和历史回放一致。
- 模块绑定修复：证据核验、反证检查和可追溯评测入口按当前对话 `run_id` 打开；在线结果在模块渲染前过滤继承的基准论文、论断、证据和反证，并提供返回对话按钮，防止不同对话内容互相干扰。

## 6. 仍未完成（诚实限制，不是失败隐藏）

1. STORM / WebGPT / Toolformer 无本地 PDF，保持摘要级边界卡片。
2. 已有 PDF 未做逐页审阅；SciMON 未抽取完整实验表。
3. Semantic Scholar 429 与 OpenAlex 部分 external ID 适配未修复；pipeline 仍只离线读取。
4. 评测不是闭卷 LLM 准确率，也不是正式模型效果实验。
5. 比赛提交包（PDF、视频、ZIP）需按 `docs/submission_checklist.md` 人工导出和录屏。
6. LLM 总论、路由和澄清题需要在 `.env` 配置 `LITAUDIT_LLM_API_KEY`，可选配置兼容 `BASE_URL` 和模型名；未配置或调用失败时只返回 AI 服务状态，不使用固定问题或模板答案。

## 7. 可信度规则

- 结论必须沿 `Claim -> Evidence -> PaperCard` 回溯
- `pdf_partial_verified` / `verified` 不等于全文已读完
- 冲突必须 pending
- 429 不能记成零结果成功
- fixture 不计入真实统计
