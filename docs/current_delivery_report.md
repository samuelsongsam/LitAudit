# LitAudit 当前交付报告

## 交付前复验：2026-09-15

当前交付在原 SPECTER2 语义地图基础上补齐三层检索能力：多来源候选统一重排、开放全文分段混合检索、Semantic Scholar 一跳引文扩展。候选重排使用 `allenai/specter2_adhoc_query` 编码短查询、`allenai/specter2` proximity adapter 编码 Title + Abstract；综合分由语义 0.75、词项 0.20、被引量 0.05 组成。三个 Hugging Face 仓库均已缓存，真实加载状态为查询 `[QRY]`、论文 `[PRX]`。

已解析全文按页切片，BM25 召回后再由 SPECTER2 重排，命中记录包含论文 ID、页码、章节提示和文本 SHA-256，产物为 `output/fulltext_index.json`。全文来源包括本地文件、arXiv 及检索提供商声明的开放 PDF；扫描件仍标记为 OCR 待办。引文扩展限制为最多 3 篇种子，每篇每个方向最多 20 条，独立保存引用方向、上下文、意图、influential 标志和原始响应，产物为 `output/citation_graph.json`。SPECTER2 语义地图与引文数据是两个独立层，界面地图仍展示 Title + Abstract 语义近邻。

本次交付前结果：`doctor` 正常；`validate` 无错误；`pip check` 无依赖冲突；Python **110 项测试通过**；前端 JavaScript 语法检查通过；前端范围行为 **2 项测试通过**；真实模型适配器加载通过。真实 Semantic Scholar 小流量验收取得 4 条引用关系、2 个请求均为 HTTP 200。真实离线端到端 run `delivery-smoke-20260915` 使用 SPECTER2 生成 7 个地图节点、10 条关键近邻边，并从 4 篇 PDF 建立 294 个全文片段、返回 12 个页码级候选，`claim-008` 保持 pending。

浏览器验收发现 UI 曾在打开 run 时重复执行 SPECTER2 构图，首次并发加载可能触发模型导入竞争并返回 500。现已改为优先读取 run 内算法版本匹配的 `map.json`，旧格式或缺失时才重建；修复后 `/api/run/delivery-smoke-20260915` 在约 0.14 秒内返回 200。筛选漏斗、地图、证据页、审计报告和 PDF 接口均已验证；界面不再显示“暂无全文”，内部 `fulltext_not_available` 也改为用户可读待办文字。完整计划与逐项验收见 `docs/retrieval_optimization_plan.md`。

当前限制：完整检索效果仍缺少人工标注问题集上的 Recall@10 / nDCG@10 对照；扫描 PDF 未自动 OCR；付费全文不绕过许可；引文网络目前作为独立数据产物提供，尚未加入界面交互层切换；外部 API 仍可能限流。以上限制不影响离线回放和证据状态边界。

## 最新工作区交付：2026-09-15 可运行性修正

默认安装路径现已包含测试与地图依赖，并新增 `python -m src.cli download-model` 负责从 Hugging Face 获取 `allenai/specter2_base`、`allenai/specter2` 和 `allenai/specter2_adhoc_query`。地图默认严格使用真实 SPECTER2；缺少依赖或缓存时会明确提示安装和下载命令，非语义哈希兜底只允许显式启用。

模型和 adapter 改为每进程加载一次，相同论文文本的 embedding 会复用缓存，推理使用 inference mode。空论文集不再调用模型，修复了 fixture 和空在线结果构图时的 `IndexError`。

针对稠密语义图无法阅读的问题，完整相似度矩阵仍保存在 payload 中，画布边改为阈值候选内的每篇 Top-2 近邻并集，并使用 NetworkX 加权社区发现划分主题簇。前端按簇分区、执行矩形避碰、根据相似度调整弹簧距离，并自动失效旧布局缓存。历史对话不再显示生成当时固化的旧地图，而是渲染当前 run 的最新版派生地图。截图对应 run 从 64 条候选边收敛到 21 条关键边，12 篇论文形成 2 个可辨识社区。

进一步按 SPECTER2 数据特性改为语义星图：对余弦距离矩阵执行确定性二维 MDS，空间距离成为相关性差异的主要编码；节点颜色表示 NetworkX 社区，节点大小表示关键近邻度数。默认隐藏所有关系线，悬停或选中节点时只显示该论文的 Top-2 近邻，同时淡化无关节点。常驻标签缩短，完整题名保留在悬停提示中。该设计不再要求用户比较接近的线宽。

## 最新工作区交付：2026-09-14 SPECTER2 研究地图替换

本节优先于下方历史记录。本轮完整替换论文检索地图的关系生成方式：论文节点仍来自当前 run 可见论文，但关系边不再由证据冲突或词重叠启发规则生成，而是按 Title + Abstract 生成 768 维语义向量，计算全局余弦相似度矩阵，并以默认阈值 0.82 过滤出语义相似边。

实现要点：

1. **SPECTER2 适配**：目标模型改为 Hugging Face `allenai/specter2`，代码按 SPECTER2 adapter 结构加载 `allenai/specter2_base` 与 `allenai/specter2`。输入文本使用标题和摘要拼接，取 CLS 向量并归一化。
2. **无 GPU / 无模型缓存兜底**：默认优先使用本地 SPECTER2；若 `adapters` / `transformers` / `torch` 或本地模型缓存不可用，退回确定性的 768 维文本哈希向量，保证离线测试和工作台不崩。payload 会记录 `embedding.backend` 与失败原因；强制要求 SPECTER2 时可设置 `LITAUDIT_MAP_EMBEDDER=specter2`。
3. **相似度矩阵与网络拓扑**：`map.json` 新增 `algorithm=specter2_cosine_network`、`embedding` 元数据、`similarity_threshold` 和 `similarity_matrix`。边统一为 `semantic_similarity`，`weight/score` 保存余弦相似度。
4. **NetworkX / HTML 输出**：语义簇优先用 NetworkX connected components 生成；每个 pipeline run 额外输出 `output/map.html`。若安装 PyVis，则生成 PyVis 交互式 HTML；未安装时生成可说明状态的静态 HTML fallback。应用内 SVG 图继续提供力学碰撞动画、悬停、拖拽、平移和缩放。
5. **审计边界保留**：证据冲突不再作为地图边，但 `contradictions` 仍保留给审计提示。语义相似不代表引用、页码证据或事实支持，Claim/Evidence 判断仍以证据模块为准。

模型落地：已安装 `.[map]` 依赖，并从 Hugging Face 下载缓存 `allenai/specter2_base` 与 `allenai/specter2`。本机缓存 snapshot 分别为 `3447645e1def9117997203454fa4495937bfbd83` 和 `2081559630a80fc5851d8f798a05ba81e9468089`。强制 `LITAUDIT_MAP_EMBEDDER=specter2` 构建 `phase2-real` 地图已验证 `embedding.backend=specter2`、`model=allenai/specter2`、`base_model=allenai/specter2_base`、`active_adapter=[PRX]`，7 个节点、21 条语义边。

验收：地图、pipeline、UI 相关测试 48 项在真实 SPECTER2 缓存存在的状态下通过；全量 Python 测试 98 项通过；前端语法检查通过；前端范围行为测试 2 项通过；doctor 正常、validate 无错误；diff 格式检查通过，`data/` 与 `runs/phase2-real/` 无差异。若未来机器没有模型缓存，默认 `auto` 模式仍会记录原因并退回确定性向量；交付环境已具备真实 SPECTER2 缓存。

## 最新工作区交付：2026-09-14 代码审查整改

本节优先于下方历史记录。本轮按五项问题逐条修改、验收：

1. **运行保护**：在线、离线、fixture 均将 `phase2-real` / `demo` 请求转为新运行；已有普通运行拒绝覆盖。目录在日志和快照写入前独占创建，审计升级同样先预留新目录。
2. **回答正文约束**：模型选择 Claim/Evidence，程序展示存储的 Claim 原文及固定证据状态。`uncertain` 不显示模型生成的断言；`qualified` 和 `verified` 也不能以合法编号夹带新结论。摘要逐字引用和引用错误修正重试保留。
3. **评测隔离**：UI 按当前运行可见的真实论文、论断和证据计算指标，不调用全局金标评测。未执行的金标答题与无检索对照不显示成绩。CLI `evaluate` 保留仓库金标评测用途。
4. **检索命中保留**：新增 `matched_paper_ids` / `reused_paper_ids`，与 `added_paper_ids` 区分；本轮命中的已有论文在独立 run 内按当前主题重新筛选。回答、路由、关键词问答、地图、筛选漏斗、审计报告、审计升级和评测使用同一可见范围；旧运行兼容仅新增编号。
5. **会话持久化**：按规范化运行路径串行处理读取、追加、重命名和删除；临时文件写完、刷新后原子替换。写入失败保留旧文件；损坏文件报错而非静默重置。

验收：Python 全量测试 98 项通过；前端范围与指标展示测试 2 项通过。覆盖受保护文件字节不变、普通运行拒绝覆盖、无证据 99% 断言不展示、空/fixture/live 评测隔离、新增 0 但命中 1 的端到端快照、16 条并发消息加重命名、原子替换失败以及损坏会话保护。

最终复验：98 项 Python 测试在 38.88 秒内通过；doctor 正常、validate 无错误；前端语法检查及 2 项行为测试通过；diff 格式检查通过，`data/` 与 `runs/phase2-real/` 无差异。

边界：本轮使用离线数据及模拟检索/模型响应，未再次调用真实外部服务；并发锁针对当前单进程多线程 HTTP 服务，不覆盖多个独立进程同时写同一会话。正文约束保证不添加超出已存储 Claim 的模型断言，不等同于自动验证 Claim 的科学真实性。旧历史回答不会被追溯改写。原 `.venv` 启动器不可用，本次使用可用 Python 运行时与本地测试依赖完成验证。

## 最新工作区交付：2026-09-11

本节优先于下方历史记录。已实现独立审计快照、PDF 全文获取/解析状态、来源文件冻结、摘录精确定位检查、EvidenceSpan / DecisionTrace / NextAction 生成、前端证据工作区与报告导出。总论和直接回答均检查 Claim/Evidence 引用，摘要线索要求逐字摘录；失败后给模型一次带错误反馈的修正机会。

最终验收 run：`audit_20260911T141848Z_430f08`。浏览器点击全文按钮后真实下载 STORM、WebGPT、Toolformer，加上 4 篇本地 PDF，共 7 篇解析成功。14 条证据生成片段记录，其中 12 条指定页匹配、2 条需人工复核；8 条判决轨迹，21 个来源快照，5 个待处理事项。原金标和 `claim-008=pending` 保持不变。新片段的 verified 表示已有已核验证据再次完成机器定位匹配，不是新的人工作证或语义判断。

真实配置模型总论调用通过引用审计，返回 5 条带绑定的陈述。下载目前支持 arXiv，每次最多 5 篇，单文件 25MB、300 页上限。未完成的长期项目：OCR、其他全文来源、自动语义判决、人工双人盲评与效果对照实验。不能把现有回放指标宣传为模型效果提升。

验收检查：`84 passed`；doctor 正常；最终快照 validate 无错误；JavaScript 语法检查与 `git diff --check` 通过。浏览器显示证据工作区、全文下载完成后自动切换新 run、报告接口返回成功，无页面脚本错误。原文 PDF GET 接口已实测，并新增拒绝越出 run 目录的回归测试。最终 run 的真实模型总论返回 5 条陈述并通过引用检查。

启动：`python -m src.cli ui --run-id audit_20260911T141848Z_430f08 --port 8787 --no-browser`。

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
- 当前界面地图展示 SPECTER2 语义近邻；引文关系保存在独立 `citation_graph.json`，不与语义边或证据关系混用。
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
3. Semantic Scholar 仍可能出现 429；系统会保留限流状态并继续使用成功来源，不能将失败解释为零结果。
4. 评测不是闭卷 LLM 准确率，也不是正式模型效果实验。
5. 比赛提交包（PDF、视频、ZIP）需按 `docs/submission_checklist.md` 人工导出和录屏。
6. LLM 总论、路由和澄清题需要在 `.env` 配置 `LITAUDIT_LLM_API_KEY`，可选配置兼容 `BASE_URL` 和模型名；未配置或调用失败时只返回 AI 服务状态，不使用固定问题或模板答案。

## 8. v0.2 优化进展（2026-09-10）

- 已冻结第一版增强审计契约：ResearchQuestion、QueryPlan、SourceSnapshot、EvidenceSpan、DecisionTrace、NextAction。
- 新旧 run 向后兼容；新 run 会输出对应 JSONL 文件。
- 在线检索已记录结构化问题、已执行查询计划、响应路径和内容 SHA-256；成功零结果、限流和失败不再共用一个快照状态。
- 直接回答新增句子级 Claim/Evidence 审计：确定性陈述缺少可定位支持证据时整次回答拒绝进入确定结果。
- 当前已有 v0.1 金标尚未批量迁移生成 EvidenceSpan 与 DecisionTrace；这是下一阶段的数据迁移任务，不能把空扩展对象口播成已完成增强审计。

## 7. 可信度规则

- 结论必须沿 `Claim -> Evidence -> PaperCard` 回溯
- `pdf_partial_verified` / `verified` 不等于全文已读完
- 冲突必须 pending
- 429 不能记成零结果成功
- fixture 不计入真实统计
