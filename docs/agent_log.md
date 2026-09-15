# Agent A 操作日志

## 2026-09-11 v0.2 审计闭环

- 新增 `audit_enrichment.py`：冻结来源文件，提取 PDF 逐页文本，为旧 Evidence 生成带文件指纹的片段和定位检查，为 Claim 生成保留原判决的轨迹，为缺全文、冲突和匹配失败生成下一步建议。
- 新增 CLI `audit <run_id> [--acquire]` 和 `/api/audit/upgrade`，始终创建新 run；新增原文 PDF 受限访问接口。
- 前端增加全文/定位/判决/待处理计数、原文入口、引用链、查询快照和报告下载；修复在线报告及生成上下文的基准隔离。
- 总论与直接回答执行引用审计；非法引用向模型反馈并重试一次，拒绝路由旧文本绕过校验。摘要线索严格使用原文摘录。
- 真实 PDF：4 篇解析、14 条定位检查，12 条匹配、2 条人工复核；原金标不变。真实模型总论返回 5 条绑定并通过检查。
- 回归覆盖全文缺失降级、原 run 不变、隐藏反证、虚构摘要和跨 run 引用。
- 最终验收：84 tests passed，doctor/validate/JS 语法/diff 检查通过。浏览器真实点击全文获取按钮，新增下载 3 篇 PDF，总计 7 篇解析、12/14 摘录匹配、5 项待处理；最终快照 `audit_20260911T141848Z_430f08`，真实模型 5 条总论陈述通过引用审计。原文 GET 接口与路径隔离已增加测试并实测。服务端口 8787。

## 2026-08-22 14:00
- 操作：读取 两人分工与交付计划.md、README.md，检查 docs/ 与 data/。
- 目的：确认角色 A 的职责、接口边界和现有资产。
- 输入：E:/LitAudit/两人分工与交付计划.md、E:/LitAudit/README.md。
- 输出：确认首期领域已指定为“大模型智能体 / 检索增强 / 自动科研”；现有 docs/data 不存在。
- 结果：成功。

## 2026-08-26 10:45
- 操作：再次尝试 arXiv、OpenAlex、Semantic Scholar 三源 API。
- 目的：完成 pending 论文元数据核验。
- 输出：三源均因套接字访问权限错误失败；未取得响应内容。
- 结果：失败，已记录并降级。

## 2026-08-26 10:50
- 操作：创建 data/paper_cards.jsonl、空的 claims/evidence/falsification JSONL、docs/a_acceptance_report.md 和 docs/current_blockers_report.md。
- 目的：完成当前可诚实完成的 A 工作，并向 B 暴露解析失败和后续阻塞。
- 结果：成功；真实证据字段保持 null/空，不伪造研究结论。

## 2026-08-26 10:57
- 操作：最终自检 data/validate 与 pytest，并更新 B 交接限制说明。
- 目的：确认新增 PaperCard/空证据入口不破坏现有契约，并汇总当前不可完成事项。
- 输出：validate error_count=0；pytest 10 passed；current_blockers_report.md 已创建。
- 结果：成功；本轮 A 可完成工作结束。
- 风险或备注：没有可复用数据；必须从零建立范围和契约。

## 2026-08-26 11:43
- 操作：在授权出站网络模式下重新检查 arXiv、OpenAlex 和 Semantic Scholar。
- 目的：确认先前 socket 权限阻塞是否仍然存在。
- 输出：arXiv 返回 HTTP 200/XML；Semantic Scholar 返回 HTTP 200/JSON；OpenAlex 主机可达但测试资源路径返回 HTTP 404；普通沙箱模式仍返回 WinError 10013。
- 结果：网络状态部分恢复；可以在授权模式继续真实检索，OpenAlex 查询路径仍需修正。
- 风险或备注：本次只做连通性和单篇元数据验证，没有改写候选论文、筛选状态或生成研究结论。

## 2026-08-26 12:14
- 操作：在授权网络模式下执行 arXiv 主/风险检索、候选元数据核验和 OpenAlex 扩展/标题交叉检索；Semantic Scholar 批量请求记录 HTTP 429。
- 目的：完成 A-02/A-03 的真实召回、去重和 pending 核验。
- 输出：保存 data/cache/retrieval-2026-08-26/ 原始响应和 data/retrieval_runs.jsonl；更新 7 篇候选与 12 条 screening log；paper-001、paper-003 include，paper-002/004/005/006/007 exclude。
- 结果：成功（摘要级）；Semantic Scholar 多源补核验受限流影响。

## 2026-08-26 12:15
- 操作：创建摘要级 PaperCard、Claim、Evidence、ClaimDecision、FalsificationHit、反证据规则和评测 fixture。
- 目的：完成当前可由摘要原文支持的 A-04 至 A-08 工作，不把全文或数值核验伪装成完成。
- 输出：7 PaperCard、8 Claim、10 Evidence、2 FalsificationHit、3 评测题目；claim-008 因正反证据冲突保持 pending。
- 结果：成功；全部 Evidence 标记 abstract_only。

## 2026-08-26 12:16
- 操作：运行 validate、pytest、phase2-real 离线 run 和 scripts/evaluate.py，并更新 current_blockers_report.md 与 agent_handoff_to_B.md。
- 目的：完成本轮 A 自检和 B 交接。
- 输出：validate error_count=0；pytest 10 passed；run stats 为 7 papers/2 include/5 exclude/0 pending/8 claims/10 evidence/2 falsification。
- 结果：成功；全文页码核验、S2 限流补核验和 B 新文件接入仍列为后续事项。

## 2026-08-26 12:20
- 操作：尝试下载 paper-001 和 paper-003 的公开 arXiv PDF。
- 目的：升级摘要级 Evidence 为页码级全文 Evidence。
- 输出：export.arxiv.org PDF 连接超时；arxiv.org PDF 下载因 Schannel CRYPT_E_REVOCATION_OFFLINE 失败，未取得 PDF。
- 结果：失败，Evidence 保持 abstract_only；失败原因已写入 current_blockers_report.md。

## 2026-08-26 12:26
- 操作：完成跨文件 JSONL/外键审计，重新生成 phase2-real，并确认测试与 CLI 状态。
- 目的：验证 A 新增数据可以被 B 当前离线读取器消费，且没有孤立引用。
- 输出：7 papers、7 paper_cards、12 screening logs、8 claims、10 evidence、8 claim decisions、2 falsification hits、14 retrieval runs、3 gold questions；所有外键和最新筛选状态匹配。
- 结果：成功；pytest 10 passed，doctor ok=true，validate error_count=0，phase2-real 生成成功。

## 2026-08-26 12:40
- 操作：创建 `docs/向B交接报告.md`，并恢复 `docs/agent_handoff_to_B.md` 兼容索引。
- 目的：向 B 汇总 A-01 至 A-08、B 当前工程状态、真实数据规模、字段语义、立即可执行接入步骤和未解决限制。
- 输入：`docs/research_scope.md`、`docs/data_contract.md`、`docs/a_acceptance_report.md`、`docs/current_blockers_report.md`、`docs/agent_handoff_to_A.md`、`data/` 和 `runs/phase2-real/`。
- 输出：中文交接报告及旧路径兼容文件；报告明确摘要级证据、网络失败、B 尚未接入的数据文件和验收命令。
- 结果：成功。
- 风险或备注：未改变研究字段语义或判决；全文证据、Semantic Scholar 和 OpenAlex external ID 适配仍待后续处理。

## 2026-08-26 17:10
- 操作：按《两人分工与交付计划》逐项审计 A-01 至 A-08、B-01 至 B-08 及固定交付阶段；使用配套 Python 重跑测试、doctor、validate 和评测脚本。
- 目的：确认项目当前阶段、真实数据规模和未完成项，向项目负责人报告进度。
- 输入：分工计划、README、docs、data、src、tests、runs/phase2-real/。
- 输出：12 tests passed；doctor `ok=true`；validate `issues=[]`；评测题目 3，论文 7，Claim 8，Evidence 10。
- 结果：A-01 至 A-08 产出齐全但全文证据仍为摘要级；B-01 至 B-04、B-07、B-08 基础能力完成，B-05/B-06 部分完成；固定阶段 1-3 已完成，阶段 4-6 已部分完成，阶段 7-8 未完成。
- 风险或备注：系统 Python 不在 PATH，已改用 bundled Python 3.12.13；该环境问题不影响项目验收结果。

## 2026-08-26 17:26
- 操作：完成 A-01 至 A-08 逐项进度审计，并创建 `docs/a_progress_report.md`。
- 目的：按照分工文档逐条报告 A 的已完成工作、证据层级、验收结果和未完成事项。
- 输入：`两人分工与交付计划.md`、A 阶段交付文件、真实 data、`runs/phase2-real/`。
- 输出：A-01 至 A-08 状态表；真实规模、校验结果和未完成清单。
- 结果：成功；所有 A 阶段规定文件存在，12 tests passed，doctor/validate 通过。
- 风险或备注：全文证据、跨源核验、正式 baseline 评测和端到端 UI 可信度抽查仍未完成。

## 2026-08-26 17:45
- 操作：逐项执行 A 当前可完成工作；检查本地 PaperQA PDF，并升级三条 Evidence 的定位状态。
- 目的：在不虚构全文证据的前提下，完成当前环境可做的证据升级，并汇总剩余阻塞事项。
- 输入：`data/cache/retrieval-2026-08-26/pdf/paper-001.pdf`、`data/evidence.jsonl`、`data/claim_decisions.jsonl`、项目分工文档。
- 输出：`evidence-001/002/005` 改为 PDF 页码级 `verified`；Claim-001/002 理由同步更新；新增 `docs/a_remaining_work_report.md`。
- 结果：成功；PDF 共 20 页且 20 页可提取文本；其他无全文论文未升级。
- 风险或备注：PaperQA PDF 仅完成第 1-2 页三条证据核验；全文逐页审阅、其他论文全文、跨源限流和正式效果评测仍未完成。

## 2026-08-26 17:35
- 操作：用升级后的 Evidence 重新生成 `runs/phase2-real/` 离线快照。
- 目的：让 B 的可回放 run 与当前数据状态一致。
- 输出：7 papers、10 evidence、3 verified、7 abstract_only，error_count=0。
- 结果：成功。

## 2026-08-26 18:00
- 操作：创建当前唯一综合交付报告 `docs/current_delivery_report.md`，并在之前的交接/进度/验收报告顶部标记“历史版本”。
- 目的：避免 B 使用过期统计，统一当前数据规模、验收结果、可信度规则和未完成事项的入口。
- 输入：最新 `data/`、`runs/phase2-real/`、`docs/a_remaining_work_report.md`、`docs/current_blockers_report.md` 和分工计划。
- 输出：当前交付报告；旧报告保留原文但明确不作为当前统计依据。
- 结果：成功。
- 风险或备注：未删除任何历史记录；当前综合报告仍明确摘要级证据和全文/基线评测限制。

## 2026-08-22 14:02
- 操作：首次并行只读命令的底层 PowerShell 进程启动失败，随后分开重试。
- 目的：完成项目文件盘点。
- 输出：重试成功，确认 README 存在且 docs/data 初始不存在。
- 结果：工具失败后恢复；不影响研究数据。

## 2026-08-22 14:10
- 操作：创建 docs/、data/、docs/prompts/。
- 目的：准备阶段交付目录。
- 输出：目录创建成功。
- 结果：成功。

## 2026-08-22 14:15
- 操作：尝试请求 https://export.arxiv.org/api/query，查询 RAG + agent。
- 目的：验证可用检索来源并获取候选元数据。
- 输出：PowerShell 返回套接字权限错误（access denied）；未取得 API 内容。
- 结果：失败，已降级。
- 风险或备注：未声称 API 成功；候选摘要/作者字段缺失时使用 null，相关论文标为 pending。

## 2026-08-22 14:25
- 操作：固定研究范围 v0.1，选择单一主问题并写入 docs/research_scope.md。
- 目的：锁定可检索、可证据核验的问题边界。
- 输出：纳入/排除标准、词表、歧义处理和不覆盖项。
- 结果：成功。

## 2026-08-22 14:35
- 操作：创建 data/search_queries.json、data/papers.jsonl、data/screening_log.jsonl。
- 目的：提供可复用检索式和第一批候选/筛选状态。
- 输出：4 条检索式、5 条候选、5 条筛选日志；去重键按 DOI/arXiv/标题作者年份优先级记录。
- 结果：成功。
- 风险或备注：3 条 pending 需在线摘要/全文核验；2 条 exclude 是边界/反证据候选，不删除。

## 2026-08-22 14:45
- 操作：创建 docs/data_contract.md，定义 PaperCard、Claim、Evidence、ScreeningLog、FalsificationHit 及 fixture。
- 目的：让 B 能直接实现读取、校验、降级和回溯。
- 结果：成功。

## 2026-08-22 14:50
- 操作：保存 docs/prompts/role_a_phase1.md；准备交接文档。
- 目的：保留可重复职责边界并交接给 B。
- 结果：成功；交接文档已创建，待最终自检结果追加。

## 2026-08-22 15:00
- 操作：运行 JSON/JSONL 结构、ID 唯一性、论文与筛选日志覆盖自检。
- 目的：确认阶段停止条件和 B 接口要求满足。
- 输出：search_queries=4；papers=5；screening_logs=5；paper_id 唯一；每篇论文有日志和非空 reason；decision 统计 include=0、exclude=2、pending=3。
- 结果：成功；未发现结构性错误。

## 2026-08-22 15:05
- 操作：检查核心文件存在性，并确认 JSON 与 JSONL 可由 PowerShell ConvertFrom-Json 读取。
- 目的：完成阶段停止条件的最终自检。
- 输入：docs/research_scope.md、data/search_queries.json、data/papers.jsonl、data/screening_log.jsonl、docs/data_contract.md、docs/agent_handoff_to_B.md。
- 输出：全部文件存在；JSON/JSONL 解析成功；fixture 明确标记为虚构；交接文档记录网络限制和 pending 论文。
- 结果：成功，Phase 1 可交接给 B。
- 风险或备注：尚无真实摘要/全文 Evidence；B 必须保留 pending，不能将候选当作已纳入结论。

## 2026-08-26 10:35
- 操作：完成 B 第一轮基础验收修复；保留 load_dataset 的 schema 解析错误，并让 doctor 在数据错误时返回非零码。
- 目的：避免坏数据被静默接受，确保命令行验收可被 CI 正确判断。
- 修改：src/schema.py、src/cli.py；新增 tests/test_schema.py 的解析错误回归测试。
- 结果：成功；pytest 10 passed，doctor/validate 均 error_count=0。

## 2026-08-26 10:36
- 操作：执行真实数据离线 run acceptance-data，并重新生成 fixture run demo 后回放。
- 目的：验证流水线快照、manifest 路径和 replay 可用性。
- 输出：acceptance-data 生成成功（5 篇真实候选，pending=3、exclude=2、include=0）；demo fixture 回放成功，路径已更新为当前仓库。
- 结果：成功。

## 2026-08-26 20:30
- 操作：不再按 A/B 分工，一次性补全可诚实完成的剩余工作。
- 目的：升级指定页 PDF 证据、生成可回溯地图边、加入无检索可追溯性对照、完善五屏 UI 和比赛交付底稿。
- 输入：本地 PDF paper-001/003/006/007，现有 data/、src/、docs/。
- 输出：14 条页码级 verified Evidence；地图 contradictions/edges；evaluate 基线对照；ask 本地检索；contest_technical_report / demo_script / submission_checklist。
- 结果：成功（部分全文）。claim-008 仍 pending；429 仍为失败；未完成逐页审阅和正式模型准确率评测。
- 风险或备注：STORM/WebGPT/Toolformer 无本地 PDF，保持摘要级边界卡片。

## 2026-08-29 12:45
- 操作：根据科研全家桶 Agent 的产品启发，升级 LitAudit 研究工作区。
- 目的：把已有检索、筛选、证据、反证和评测组织成连续的可审计研究流程，并提供可交付的结构化报告。
- 修改：`src/ui/payload.py` 增加 workspace context 和 Markdown 审计报告生成；`src/ui/server.py` 增加 `/api/run/<run_id>/report`；`src/ui/static/app.js` 与 `styles.css` 增加流程导航、工作区摘要和报告下载；`tests/test_ui.py` 增加上下文、报告和接口回归测试。
- 验证：捆绑 Python 执行 `pytest -q` 为 29 passed；`doctor` 返回 `ok=true`；`validate` 返回 `error_count=0`；本地 UI 页面实际显示新导航和“下载审计报告”。
- 结果：成功；没有改变研究范围、Claim 状态、Evidence、反证据或真实数据统计。
- 风险或备注：仓库 `.venv` 与全局 Python 不可用，本轮使用 `C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` 完成验证；STORM/WebGPT/Toolformer 摘要级限制、全文未逐页审阅、非准确率评测等限制仍然有效。

## 2026-08-29 13:20
- 操作：根据研究地图优化方案，将地图从分类卡片改为可交互 SVG 论文关系图。
- 目的：让论文以方框节点展示，让现有证据冲突和反证关系以有向箭头展示，并支持研究者整理布局和检查关系详情。
- 修改：`src/ui/static/app.js` 增加 SVG 节点/边、方向箭头、力导向布局、节点拖动、画布平移/缩放、布局控制、节点/边详情联动；`src/ui/static/styles.css` 增加图谱画布、状态节点、关系边和图例样式；`src/ui/static/index.html` 更新静态资源版本号；`tests/test_ui.py` 增加图谱结构回归断言。
- 语义边界：只使用 `map.json` 已有的 `evidence_conflict` 和 `falsification` 边，不根据关键词相似度推断引用关系；`claim-008` 仍 pending。
- 验证：`pytest -q` 为 29 passed；doctor `ok=true`；validate `error_count=0`；新版 UI 实测 7 个 SVG 论文节点、4 条可见有向边、4 个箭头命中区域；节点点击能更新详情，箭头点击能显示关系详情，拖动和滚轮缩放均无浏览器错误。
- 结果：成功；未改变研究数据和数据契约。

## 2026-08-29 13:45
- 操作：修正可交互研究地图的箭头几何、并行关系和重新布局避碰。
- 目的：解决论文框重叠、箭头从框内错误位置穿出、同一论文对多条关系重合以及箭头帽颜色不一致的问题。
- 修改：`src/ui/static/app.js` 使用论文框中心和矩形边界交点生成二次曲线路径，为同一 `source -> target` 的多关系分配独立曲率，并在每帧运动后执行多轮矩形碰撞校正、结束前强制收敛；`src/ui/static/styles.css` 为冲突、反证和默认箭头帽设置对应颜色。
- 语义边界：继续只读取结构化的 `evidence_conflict` 与 `falsification`；没有新增引用边或关键词相似边，没有修改 `claim-008=pending`。
- 浏览器验收：当前在线 run `live_20260829T051649Z_043724` 渲染 19 个论文节点、4 条有向关系；重新布局动画中段和结束均为 0 对矩形重叠，4 条关系路径互不相同，拖动 `paper-001` 后相关路径实时变化，箭头帽颜色与关系类型一致。
- 回归验证：捆绑 Python 执行 `pytest -q` 为 29 passed；`doctor` 返回 `ok=true`；`validate` 返回 `error_count=0`；`git diff --check` 无内容错误。`runs/phase2-real/output/claim_decisions.jsonl` 中 `claim-008` 仍为 `pending`。
- 结果：成功；同步更新当前交付报告、技术文档、演示脚本和提交清单。

## 2026-08-29 14:20
- 操作：将 UI 主入口改为对话式研究首页，并接入连续追问、多次检索意图路由和 LLM 总论。
- 修改：新增 `skills/conversational-research-routing/SKILL.md`、`src/conversation.py`、`POST /api/chat` 与 `GET /api/chat/<run_id>`；对话记录保存到 run 的 `output/conversation.json`。新增 `LITAUDIT_LLM_API_KEY`、`LITAUDIT_LLM_BASE_URL`、`LITAUDIT_LLM_MODEL` 配置。
- 路由：新主题、明确扩大/重新检索和深入分支会创建新的 `live_*` run；当前 run 追问和指定论文探索复用当前 run，并返回意图类型和目标论文。
- UI：对话回复按总论、论文、研究地图和后续核验模块排列；证据核验、反证检查、可追溯性评测仍保留旧视图，本轮不重新实现其内容。
- 结果：本轮未改变数据契约、Evidence、Falsification 或 `claim-008=pending`。
- 补充修正：发现仅输入论文简称时可能误判为新主题，已将论文 ID、标题冒号前简称和核心标题词纳入论文探索匹配，避免简单论文追问误触发新检索；新增回归断言。

## 2026-08-29 16:10
- 操作：将对话输入栏从顶部工作区移动到对话内容底部。
- 修改：对话页在 `chatView` 内渲染底部 `chat-compose`，使用 sticky 底部布局；非对话审计页面继续使用顶部检索栏。
- 浏览器验收：对话页输入框位于内容底部，顶部无重复输入框；切换检索与筛选页后顶部输入栏仍存在；控制台无错误。
- 回归：31 tests passed；未改变研究数据和核验结论。
## 2026-08-29 16:25
- 操作：清理对话首页顶部重复研究问题框，并增加会话管理。
- 修改：对话首页不再渲染顶部 workspace context 和范围行；新增“新建对话”“历史对话”控件，后端增加 `GET /api/conversations` 与 `DELETE /api/chat/<run_id>`。删除仅移除对应 `output/conversation.json`，保留 run 数据。
- 浏览器验收：顶部重复框不存在，底部输入栏存在；历史列表加载 7 条会话；新建对话后用户/AI 消息均清空。
- 回归：32 tests passed；`doctor ok=true`；`validate issues=[]`；未改变论文、Evidence、Falsification 或 `claim-008=pending`。

## 2026-08-29 16:45
- 操作：修正对话论文列表始终显示 7 篇基准论文的问题。
- 原因：在线 run 从 `data/` 的 7 篇基准论文开始合并；`build_chat_response` 又直接返回 `payload["papers"]`，没有使用同轮 `ask` 的匹配结果。
- 修改：对话回复按 `ask` 的 `paper_id` 过滤本轮相关论文；指定论文探索保留目标论文；新增 `paper_selection` 统计，区分匹配数、在线新增数和 run 总数；零匹配时不再展示全部基准论文。
- 验收：对已有 7 篇论文的 `phase2-real` 输入 `PaperQA`，最新一轮显示 1 篇目标论文；历史消息仍按历史记录保留。浏览器无错误。
- 回归：33 tests passed；`doctor ok=true`；`validate issues=[]`；未改变研究数据和 `claim-008=pending`。
## 2026-08-29 16:52
- 操作：排查“无论检索什么词都出现 7 篇论文、感觉没有搜索”的反馈。
- 结论：当前在线请求确实进入 `run_pipeline -> ingest_live -> search_all`；但本机到 arXiv、OpenAlex、Semantic Scholar 的 Python 外部连接均失败或超时。本轮 `live` run 因从 7 篇基准数据开始合并，在无新增结果时仍有 7 篇候选。
- 修正：对话回复继续按当前问题的 `ask` 匹配结果过滤论文，不再展示整个 run；新增 `paper_selection.retrieval_status` 和失败来源提示，区分成功零匹配与检索源不可用。
- 浏览器验收：当前在线 run 显示 0 篇本轮匹配、0 篇新增、7 篇 run 总数，并提示失败/限流不能据此判断没有相关论文；无浏览器错误。
- 回归：33 tests passed；`doctor ok=true`；`validate issues=[]`；未改变 Evidence、Falsification 或 `claim-008=pending`。

## 2026-08-29 17:05
- 操作：在网络权限下重启 UI 并进行在线检索端到端验收。
- 结果：问题 `quantum computing error correction` 成功创建 `live_20260829T085615Z_eb1d09`；在线召回新增 12 篇、跳过重复 3 篇，最终候选 19 篇；Semantic Scholar 返回 429，已作为部分检索源失败显示。
- UI 验收：最新回复显示本轮匹配 1 篇、在线新增 12 篇、当前 run 共 19 篇，并显示“部分检索源失败”；筛选、研究地图、证据、反证和评测页面均可打开，浏览器无错误。
- 结论：此前固定显示 7 篇的直接原因是服务在受限网络环境中运行，四个在线请求均失败；切换到可用网络权限后，检索和新 run 切换链路正常。

## 2026-08-29 17:20
- 操作：接入 DeepSeek OpenAI 兼容 LLM 到对话 Agent。
- 配置：项目根目录 `.env` 设置 `LITAUDIT_LLM_BASE_URL=https://api.deepseek.com/v1`、`LITAUDIT_LLM_MODEL=deepseek-chat`；密钥不写入源码，`.env` 已被忽略。
- 行为：LLM 总论提示词明确接收本地 Skill 意图路由结果，按当前 run 追问、指定论文、分支深入和重新检索解释交互；不能新增论文、证据或确定性结论。
- 验收：待重启服务后进行真实 DeepSeek 调用；保留无 Key/调用失败时的结构化模板降级。

## 2026-08-29 17:35
- 操作：重启服务加载 DeepSeek 配置并进行真实对话调用验收。
- 结果：`phase2-real` 的“为什么 claim-008 仍然是 pending？”返回 `勘文 AI · LLM 总论`，生成内容基于 7 篇论文、14 条页码证据和 2 条反证命中，并明确保留 pending；浏览器无错误。
- 修正：真实 Key 存在时，模板降级单测改为显式注入空 Key，避免测试请求外部模型。
- 安全：Key 只保存在被 `.gitignore` 忽略的本地 `.env`；由于曾在聊天中暴露，建议正式使用前在 DeepSeek 控制台轮换。
- 回归：33 tests passed；`doctor ok=true`；`validate issues=[]`。

## 2026-08-29 22:20
- 操作：强化对话 Agent 的“先澄清、后检索”规则。
- 修改：`conversational-research-routing` 增加 `needs_clarification`；短句、宽泛主题或缺少研究对象、方法/现象、任务/比较和边界的请求先返回澄清问题，不创建 run、不调用在线来源。信息充分或用户明确提出具体检索请求后，才允许创建新的在线 run。
- UI/API：支持无 `run_id` 的澄清响应，前端不会把尚未检索的请求当作已完成检索结果。
- 文档：README、当前交付报告同步说明检索前澄清行为。

## 2026-08-29 22:35
- 操作：修正在线检索地图混入本地基准论文的问题。
- 原因：在线 pipeline 从本地数据集继承 7 篇基准论文，原地图 payload 直接暴露整个合并后的 `map.json`。
- 修改：在线 run 的 UI 地图仅保留 `live.added_paper_ids` 节点，并裁剪只连接本轮新增论文的边、主线和矛盾对；本地论文不删除，仍保留在 run、审计数据和 LLM 内部上下文中。
- 运行态修正：发现 8787 端口仍由旧 UI 进程提供服务，重启后重新加载 payload 过滤代码。
- 原因修正：前端只发送“我选择了……”而未发送原始主题；`build_query_plan` 对所有新主题都追加默认 RAG 范围检索，导致哲学主题被 RAG 论文污染。
- 修改：澄清选择请求新增 `clarification_topic`；DeepSeek 使用原始主题、选择结果和上下文生成 `expanded_query`。用户主题 run 只执行用户主题 arXiv、OpenAlex 和 Semantic Scholar 查询，不再强制加入默认 RAG 查询。
- 进一步修正：用户自定义主题不再为了凑查询数量追加 RAG 反证风险式；仅默认主线检索保留风险检索。DeepSeek 实测将“哲学中的核心概念”与三项选择扩展为 `philosophy core concepts reason freedom absolute spirit comprehensive review overview classical contemporary`。

## 2026-08-30 18:05
- 操作：按要求移除所有面向用户的固定回答和固定选择题回退。
- 修改：DeepSeek 路由、澄清题、直接回答和总论均为 AI + Skill 生成；API Key 缺失、请求失败、JSON 无效或总论失败时只返回 `llm_unavailable/llm_error`，不再显示固定问题、模板总论或固定直接回答。
- 历史兼容：隐藏旧版本写入的固定澄清消息，避免打开 `phase2-real` 时再次看到过期固定题；不删除原始审计数据。
- 实际接口验收：`live_20260829T085615Z_eb1d09` 返回 12 个地图节点（`paper-008` 至 `paper-019`），0 个本地基准节点，0 条跨本地关系边。
- 回归：35 tests passed；`doctor ok=true`；`validate issues=[]`；`git diff --check` 无问题。

## 2026-08-29 22:50
- 操作：整改在线检索无论文返回的问题。
- 发现：截图对应的 `live_20260829T143335Z_52adfa` 中三个在线来源均为网络失败，且 OpenAlex/Semantic Scholar 请求把“请检索、比较、限定、输出论文列表”等对话指令一并发送，查询噪声过大。
- 修改：在线查询发送前清除对话操作词和输出要求，保留研究主题、方法和对象；新增回归测试。网络失败仍显示失败状态，不用本地基准论文冒充在线结果。
- 真实重跑：在网络权限下执行同一问题，arXiv 两路返回 15/6 条，OpenAlex 成功但为 0 条，Semantic Scholar 返回 429；去重后新增 12 篇候选（`paper-008` 至 `paper-019`）。
- UI 验收：重启 8787 服务切换到 `live_20260829T143740Z_a02524`；接口返回 12 个新检索地图节点，论文列表不再为空，本地基准论文未出现在地图中。

## 2026-08-29 23:10
- 操作：按用户要求重构检索前对话交互。
- 修改：路由 Skill 增加 LLM-first 判断，支持 `direct_answer`、`clarify`、`retrieve` 三种动作；澄清时生成恰好 3 道单选题、每题 3 个选项，用户提交选择后再使用 `expanded_query` 检索。
- UI：澄清阶段独立渲染问题和选项，不显示总论概览、本轮相关论文、研究地图或核验模块；直接回答时也不创建 run。
- 兼容：LLM 不可用时使用保守本地路由和固定三题降级，不因路由失败自动检索。

## 2026-08-29 23:35
- 操作：核查动态选择题是否实际调用 DeepSeek。
- 结果：当前 `.env` 配置有效；直接调用 DeepSeek 路由“城市”返回了针对城市研究的动态三题三选项，确认不是固定题生成。
- 修正：LLM 返回 `clarify` 时不再在正常路径混入固定问题；固定三题仅作为无密钥/接口不可用时的降级结果。重启 UI 时使用网络权限，确保 8787 服务可以调用 DeepSeek。

## 2026-08-29 22:10
- 操作：同步项目入口文档与环境文件忽略规则。
- 修改：README 补充对话首页、连续追问意图路由、会话持久化、DeepSeek OpenAI 兼容配置、LLM 降级行为和当前能力边界；`.gitignore` 增加 `.env.*` 规则并保留 `.env.example`。
- 安全核验：`.env`、`.env.local` 和 `.env.production` 均被忽略，真实密钥未进入跟踪文件；README 提醒已暴露密钥正式使用前应轮换。
- 回归：33 tests passed；`doctor ok=true`；`validate issues=[]`；`git diff --check` 无问题。

## 2026-08-30 18:20
- 操作：完成对话/检索流水线回归验收，并修正历史固定澄清消息的显示兼容问题。
- 发现：旧版本 `phase2-real/output/conversation.json` 中仍有固定澄清助手消息；之前仅隐藏助手消息，导致对应的用户主题孤立显示。
- 修改：显示层现在按成对记录隐藏旧固定澄清的用户/助手消息；原始审计 JSON 保留，不删除论文、证据或 run 数据。当前新消息仍要求 `route_source=llm` 才展示澄清结果。
- 验收：`42 passed`；`doctor ok=true`；`validate issues=[]`；`git diff --check` 通过。在线 HTTP 与网页实测输入“房地产”返回 DeepSeek 动态三题、无 run、无论文，未出现旧固定选项；LLM 失败时仍只返回 `llm_unavailable`。

## 2026-08-30 18:35
- 操作：修复提交澄清选择后出现 `对话失败：slice(None, 80, None)` 的问题。
- 原因：DeepSeek 对 `retrieve` 动作返回了包含 `original_topic`、`choices`、`scope` 的结构化 `expanded_query` 对象；旧代码将其直接传给流水线的字符串截取和检索逻辑。
- 修改：新增结构化查询归一化；优先读取 AI 返回的 `query/search_query/expanded_query` 字段，否则组合 AI 返回的原主题、选择和范围；同时收紧路由 JSON 的对象、问题、选项、回答类型校验。
- 真实验收：使用截图中的“房地产 + 市场趋势与价格分析 + 海外市场 + 实用指南与建议”提交成功，创建在线 run，完成三类来源检索并生成 LLM 总论；Semantic Scholar 的 429 仍按限流保留，未伪装成零结果。
- 回归：`43 passed`；无再现 500；新增 run 的 `overview_mode=llm` 且无 `error`。

## 2026-08-30 18:48
- 操作：处理输入“房地产”后偶发只显示“AI 未生成本轮内容，请重试”的问题。
- 判断：同一服务和配置随后的接口请求可正常返回动态澄清题，说明这是一次 DeepSeek 路由调用的瞬时失败或返回格式不合规，不是检索零结果，也不是固定模板回退。
- 修改：路由与总论请求增加一次有限重试；网络错误、超时、无效 JSON 和不满足三题三选项等 Skill 契约的返回都会重试。两次均失败才返回 `llm_unavailable`，不生成固定内容。
- 验收：最终服务连续三次请求“房地产”，均返回 `needs_clarification`、3 道动态题、无错误、无 run；网络失败和无效格式重试均有独立单测。回归 `45 passed`。

## 2026-08-30 19:15
- 操作：修复现代 GPU 微架构主题检索 0 篇、却使用基准 7 篇 RAG 论文生成总论的问题。
- 原因：arXiv 查询把 `gpu/nvidia/hopper/ada/amd/rdna` 全部以 AND 连接；OpenAlex/Semantic Scholar 收到中文长句；在线筛选仍只接受 LLM/RAG 科学问答；LLM 总论输入未隔离继承的基准论文。
- 修改：增加 GPU 中文概念扩展和来源适配英文查询；arXiv 改为 GPU/厂商与 Hopper/H100/Ada/RDNA/CDNA 的组合检索；自定义主题改用本轮相关性筛选，GPU 进一步检查型号与微架构/ISA/存储层级信号；总论、论文列表、地图和失败统计只使用本轮新增数据。
- 真实验收：最终对话 run `live_20260830T111130Z_a90fa7` 展示 12 篇在线新增论文，其中 9 篇纳入、3 篇待定；地图 12 个节点、0 个基准节点；总论命中 GPU/Hopper/RDNA/CDNA，未出现 PaperQA/SciMON。arXiv 返回 15，OpenAlex 返回 0，Semantic Scholar 429 保持限流状态。
- 回归：`48 passed`；`doctor ok=true`；`validate issues=[]`。在线论文仍只有摘要级筛选，因此地图没有证据关系边，不伪造引用或证据箭头。

## 2026-08-30 21:05
- 操作：修复检索完成后继续追问出现“找不到可回放的 run: null”。
- 原因：`/api/chat` 的直接回答可以不创建新 run，但前端对所有 completed 响应无条件执行 `loadRun(result.run_id)`；服务端也没有把当前 run 回传给当前研究上的直接追问。
- 修改：当前 run 追问返回并保存到原 run；澄清仍不创建或污染 run；新检索必须返回非空 run。DeepSeek 路由新增操作种类、目标论文和研究分支契约，前端增加空 run 防护。
- 回归：新增当前 run 复用、操作字段保留和禁止 `loadRun(null)` 测试。
- 二次修正：将意图判断与回答生成拆为两个 DeepSeek 调用。路由器只需返回动作、操作类型、目标论文或分支；直接回答随后读取当前 run 的论文、Claim、Evidence 和反证数据生成，不再因路由结果缺少 `answer` 字段整轮失败。
- 真实验收：在 `live_20260830T111130Z_a90fa7` 追问“基于当前结果说明论文，不要重新检索”，接口返回 `status=completed`、`action=reuse_run`、`intent=follow_up`、原 run ID 和 DeepSeek 回答正文。最终 `51 passed`；`doctor ok=true`；`validate issues=[]`。

## 2026-08-30 21:25
- 操作：优化直接回答的文字呈现，处理 Markdown 原样显示和超宽文字墙。
- 修改：新增先转义后解析的 Markdown 子集渲染，支持标题、段落、有序/无序列表、粗体、斜体和行内代码；回答正文限制为 900px，使用 15px 字号、27px 行高和清晰的段落/列表间距。
- LLM 输出：直接回答提示词要求先给一句结论，再按信息层级分段；论文较多时用有序列表，每项只保留标题、年份、核验层级和一个关键点，默认限制 800 至 1400 中文字符。
- 浏览器验收：历史 GPU 直接回答解析为 5 个段落、1 个有序列表和 13 个列表项，页面残留 `**` 数为 0；`51 passed`，`git diff --check` 通过。

## 2026-08-30 22:00
- 操作：重构外观和历史对话入口。
- 修改：左侧旧模块导航替换为历史对话侧栏；新增当前会话高亮、新建、切换、重命名和删除；新增 `PATCH /api/chat/<run_id>` 重命名接口。模块页顶部显示所属对话，核验入口使用 `run_id + view` 独立打开，避免跨会话混读。
- 数据边界：重命名只写目标 run 的 `output/conversation.json`；删除仍只删除目标对话记录，论文、Evidence、Falsification 和评测快照保留。
- 回归：`52 passed`，`git diff --check` 通过；8787 已重启并监听新 UI。
- 追加修复：侧栏上线后页面曾停在“正在打开勘文”。实际原因是 `mapView()` 中残留多余的 `` `}` ``，使 `app.js` 在浏览器解析阶段失败；删除该字符后使用 QuickJS 解析通过，浏览器实测左侧显示 12 条历史对话且控制台无错误。

## 2026-08-30
- 操作：为 DeepSeek 动态澄清题增加“其他”选项。
- 修改：每题显示三个 AI 选项和一个“其他”；选中后展开独立文本框，提交时要求三题均有最终答案，自定义答案按原题顺序进入 `clarification_context`，随后由 Agent 继续判断并检索。
- 验证：JavaScript 语法解析通过，`52 passed`，`git diff --check` 通过。

## 2026-08-30
- 操作：修复提交澄清选择后前面的对话消失。
- 原因：澄清阶段不创建 run，提交后会创建新的 live run；前端 `loadRun()` 只加载新 run 已持久化的消息，导致原始问题和澄清过程被覆盖。
- 修改：发送检索请求时携带前序消息上下文；服务端在新 run 中先持久化前序消息，再保存当前选择与检索回答；前端加载新 run 后按角色和内容去重合并，刷新和历史回放均保留完整链路。
- 验证：JavaScript 语法解析通过，`52 passed`；服务已重启。

## 2026-08-30
- 操作：修复后续核验模块仍显示固定 PaperQA 等基准内容、缺少返回对话的问题。
- 原因：模块页直接读取完整 payload；在线 run 的 payload 包含继承的基准结构化数据，模块渲染没有复用对话首页的本轮新增过滤。
- 修改：新增 `scopedAuditData()`，证据、反证和论断视图按当前在线 run 的 `added_paper_ids` 过滤；对话入口按当前 `run_id` 打开模块页，模块顶部显示所属对话并提供返回对话按钮。
- 验证：JavaScript 语法解析通过，`52 passed`。
- 追加：发现旧证据标签页仍使用 `app.js?v=20260830-sidebar2`，因此没有返回栏并展示旧页面内容；静态资源版本升级为 `sidebar3`，新标签页强制加载当前模块隔离逻辑。API 检查确认 PD 分离 run 的 19 个 payload 论文中仅 12 个属于本轮新增，基准数据由模块过滤器排除。

## 2026-09-09
- 操作：启动 v0.2 优化方案的 P0 落地。
- 文档：新增 `docs/optimized_product_plan.md`，明确产品定位、可信度优先架构、数据契约升级、阶段交付和终验标准。
- 规则：强化 `ClaimDecision` 校验；`supported` 必须引用至少一条可 grounding 的支持性 Evidence，且不能引用 contradict Evidence。
- 回归：新增两条 schema 测试；`66 passed`，`python -m src.cli validate` 无错误，`git diff --check` 通过。

## 2026-09-10
- 操作：完成 Phase 0 数据契约扩展，并接入在线检索与回答链路。
- 数据契约：新增 `ResearchQuestion`、`QueryPlan`、`SourceSnapshot`、`EvidenceSpan`、`DecisionTrace`、`NextAction` 及对应枚举、外键和状态约束；旧 run 缺少新文件时仍可读取。
- 流水线：新 run 固定输出六类 v0.2 审计文件；在线检索自动生成研究问题、已执行查询计划以及带响应 SHA-256 的来源快照，零结果、限流与失败分开记录。
- 回答审计：新增逐条陈述的 Claim/Evidence 绑定检查；确定性陈述必须绑定 supported/partial Claim 及可定位支持证据，pending 只能以 uncertain 表述。
- 回归：增加 schema、在线检索、run 快照和回答审计测试；摘要级 Evidence 不能冒充 verified；`75 passed`。
# 2026-09-14：代码审查五项整改

- 统一运行保护，拒绝覆盖已存在目录；保护测试在临时目录执行，真实金标不写入。
- 回答展示改为存储 Claim 原文与程序生成状态，防止 certainty 标签掩盖自由生成断言；补充针对三种 certainty 的回归用例。
- 当前运行独立计算 UI 评测，保留仓库级 CLI 金标评测。
- 区分本轮命中、复用和新增论文，重新筛选复用候选，同步所有展示和审计升级范围，兼容旧 manifest。
- 会话按运行加线程锁、原子替换，写入失败保留旧数据，损坏会话明确报错。
- 验收：98 项 Python 测试、2 项前端行为测试；外部检索与模型使用模拟响应。详见 current_delivery_report.md 最新章节。

# 2026-09-14：SPECTER2 研究地图替换

- 操作：将研究地图从证据冲突边/词重叠启发边替换为 Title + Abstract -> SPECTER2 embedding -> cosine matrix -> threshold graph。
- 模型适配：目标 Hugging Face 模型为 `allenai/specter2`；代码按 adapter 方式使用 `allenai/specter2_base` + `allenai/specter2`，取 CLS 768 维向量。默认无网络、无缓存时退回确定性 768 维文本哈希向量，并在 `map.json` 记录 backend 和原因；可用 `LITAUDIT_MAP_EMBEDDER=specter2` 强制要求真实模型。
- 图谱输出：`map.json` 新增 `algorithm=specter2_cosine_network`、embedding 元数据、全局相似度矩阵、相似度阈值；边统一为 `semantic_similarity`，边权为余弦相似度。NetworkX 用于语义簇；pipeline 额外输出 `output/map.html`，PyVis 可用时生成交互式 HTML，否则生成静态说明页。
- UI：工作台地图改为展示 SPECTER2 语义相似边，线宽按相似度变化；保留力学碰撞动画、悬停、拖拽、缩放和平移。证据冲突不再作为地图边，但 contradictions 仍保留在审计提示中。
- 文档：README、演示脚本、提交清单和当前交付报告已改为 SPECTER2 语义图口径。
- 模型缓存：安装 `.[map]` 后从 Hugging Face 下载 `allenai/specter2_base` snapshot `3447645e1def9117997203454fa4495937bfbd83` 与 `allenai/specter2` snapshot `2081559630a80fc5851d8f798a05ba81e9468089`。强制 `LITAUDIT_MAP_EMBEDDER=specter2` 构建 `phase2-real` 地图，确认 `embedding.backend=specter2`、`active_adapter=[PRX]`、7 个节点、21 条语义边。
- 验收：真实 SPECTER2 缓存存在状态下相关测试 48 passed；全量 98 passed；前端语法检查通过；`node --test tests/ui_scope.test.cjs` 2 passed；doctor ok；validate issues=[]；`git diff --check` 通过；`data/` 与 `runs/phase2-real/` 无差异。

# 2026-09-15：SPECTER2 可运行性交付修正

- 默认安装命令统一为 `pip install -e ".[dev,map]"`，`requirements.txt` 补齐地图依赖。
- 新增 `python -m src.cli download-model`，明确下载并报告 `allenai/specter2_base` 与 `allenai/specter2` 的缓存路径。
- 地图默认严格要求真实 SPECTER2；缺依赖或缓存时返回可执行修复提示。哈希兜底只在显式 `hash` 或 `auto` 模式启用。
- 基础模型与 adapter 在进程内只加载一次，相同 Title + Abstract 输入的向量结果缓存复用，并使用 inference mode；空论文集不再触发模型编码异常。
- 地图可读性修正：完整余弦矩阵继续保留，但画布采用阈值候选中的每篇 Top-2 近邻并集，避免高基线相似度形成毛线团；NetworkX 加权社区发现生成主题簇，布局按簇分区并执行矩形避碰。历史对话中的旧地图派生数据会用当前 run 的新版地图替换，旧浏览器布局缓存通过版本键自动失效。
- 对截图对应的德国古典哲学 run 实测：12 个可见节点由 64 条阈值候选压缩为 21 条关键近邻边，形成 2 个可分辨社区；Playwright 浏览器截图确认不再竖线塌缩或卡片重叠。
- 二次可视化重构：SPECTER2 余弦距离通过经典 MDS 投影为二维坐标；默认以无连线星图展示，社区映射颜色、关键近邻度数映射节点大小。节点悬停时仅显示局部近邻线和相关节点，其余节点淡化；不再使用线宽承载相似度差异。
