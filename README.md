# 勘文 LitAudit

勘文是一套可回放、可核验的文献调研工作台。它接收科研问题，使用 DeepSeek 对话 Agent 判断用户意图，再调用在线文献检索、候选筛选和本地审计数据，返回结构化研究结果。

勘文的目标不是自动写一篇看似完整的长综述，而是让用户知道检索到了什么、为什么保留、哪些内容只是摘要级判断、哪些论断有页码证据，以及哪里存在反证和不确定性。

## 当前流程

```text
用户问题
  -> DeepSeek + conversational-research-routing Skill 判断意图
  -> 必要时生成动态范围确认题
  -> arXiv / OpenAlex / Semantic Scholar 检索
  -> DOI、arXiv ID、标题去重
  -> SPECTER2 查询与论文统一重排
  -> 标题与摘要规则筛选
  -> 核心候选一跳引文扩展
  -> 写入独立 live_<时间>_<随机标识> run
  -> 按需获取开放全文并建立页码级混合检索索引
  -> DeepSeek 根据当前 run 生成总论
  -> 对话、论文、研究地图和审计模块按 run 展示
```

每次在线检索都会产生新的 `live_*` run，不覆盖本地基准数据。每个历史对话绑定一个 run；论文、检索记录、Claim、Evidence、反证、地图和评测都必须从当前 run 读取。

在线、离线与 fixture 模式均保护 `phase2-real` / `demo`：请求这些名称时创建新运行；其他已存在的运行名称拒绝覆盖。本轮检索区分“命中”“复用”“新增”，命中的已有论文会在新运行内重新筛选，并保留在结果中。UI 评测只统计当前可见结果；仓库金标评测通过 CLI `evaluate` 单独执行。

## 对话 Agent

对话首页是主要入口。每条消息先交给 DeepSeek 路由，再决定下一步操作：

- `follow_up`：基于当前 run 回答，不重新检索。
- `paper_explore`：聚焦用户提到的论文。
- `branch_deepen`：沿当前研究分支继续检索，创建新 run。
- `requery`：重新、扩大、缩小或刷新检索，创建新 run。
- `new_topic`：脱离当前主题，必要时重新澄清范围。

信息不足时，DeepSeek 生成三道针对当前主题的选择题。每道题包含三个 AI 生成选项和一个“其他”选项；选择“其他”后用户可以填写自定义范围。只有完成范围确认后，系统才进入检索。

对话支持连续追问、新建、切换、重命名和删除。删除对话只删除会话记录，不删除该 run 的论文和审计数据。

## 检索与筛选

在线检索支持 arXiv、OpenAlex 和 Semantic Scholar。HTTP 429 记录为 `rate_limited`，不能解释成零结果。网络失败、部分来源失败和确实没有匹配结果在界面中分开显示。

在线检索默认完成标题和摘要级筛选。在证据核验页面点击“获取全文并核验”，会创建独立审计快照，优先解析已有本地 PDF，并尝试下载 arXiv 或检索提供商声明的开放 PDF（每次最多 5 篇）。获取、解析失败和需要 OCR 的情况会保存为明确状态。全文解析不会自动把 Claim 标记为 `supported`。

筛选规则必须区分研究主题和输出形式。“综述”“深入分析”“性能对比”是输出要求，不能直接当作论文主题词。自定义主题筛选不能只因为论文包含 `literature review` 或 `systematic review` 就纳入；应同时检查领域锚点、对象、方法和任务等实质性词项。当前规则属于工程筛选，不等同于语义模型判断或人工全文审阅。

## 审计模块

对话回复包含论文筛选、研究地图、证据核验、反证检查和可追溯性评测入口。进入模块时地址携带当前对话的 `run_id`；模块只读取当前 run，显示所属对话和返回对话按钮。在线 run 会过滤继承的本地基准论文，避免 PaperQA、SciMON 等基准数据混入其他主题。

研究地图中的论文是节点。系统将每篇论文的 Title + Abstract 输入 SPECTER2（`allenai/specter2_base` + `allenai/specter2` adapter）得到 768 维向量，计算全局余弦相似度矩阵，并在相似度达到阈值时连边。边权越大，界面连线越粗。语义相似边不是引用、页码级证据或事实支持关系；Claim/Evidence 审计仍以证据模块为准。每个 run 会输出 `output/map.json` 和可独立打开的 `output/map.html`，工作台内置图支持力学碰撞动画、悬停、拖拽、画布平移和缩放。UI 优先读取 run 内已生成且算法版本匹配的地图，避免打开页面时重复加载模型；旧格式或缺失地图才会重建。

### v0.2 证据审计工作区

- 保存研究问题、查询计划、来源快照及 SHA-256、EvidenceSpan、DecisionTrace 和 NextAction。
- 逐页提取本地或新获取的 PDF；对已有摘录执行归一化精确匹配。匹配只检查位置，保留原人工判决；未匹配的摘录进入人工复核。
- 页面可查看原文 PDF、证据到文件指纹的链路、全文失败状态、后续建议，并下载当前 run 的 Markdown 审计报告。
- 总论与直接回答均执行引用完整性检查；证据必须属于对应 Claim，冲突不能通过省略反证来隐藏。摘要线索只允许逐字摘录并明确标记。
- Claim 回答由程序展示已存储原文及证据状态，模型自由生成的正文不直接作为审计结论；待核验内容明确标记，不因 certainty 标签而自动可信。
- 模型返回非法引用时，将校验错误反馈给模型修正一次；仍不通过则显示回答状态，并保留论文与审计入口。
- 审计升级创建 `audit_*` 新运行，原 run 和金标保持不变。运行 `python -m src.cli audit phase2-real` 可只核验本地文件；加 `--acquire` 可尝试获取 arXiv 或提供商声明的开放全文。

证据规则：没有 Evidence 的 Claim 不能标记为 `supported`；正反证据冲突时必须保持 `pending`；`pdf_partial_verified` 只表示摘录和定位已核对；在线 `live_abstract` 结果不能作为页码级证据。

## 安装与启动

要求 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,map]"
python -m src.cli download-model
python -m src.cli doctor
python -m src.cli validate
python -m src.cli ui --run-id phase2-real
```

浏览器访问 `http://127.0.0.1:8787/?run=phase2-real`。在线 UI 可使用：

```powershell
python -m src.cli ui --run-id phase2-real --port 8787 --no-browser
```

`download-model` 会从 Hugging Face 下载 `allenai/specter2_base`、论文 proximity adapter `allenai/specter2` 和查询 adapter `allenai/specter2_adhoc_query`，之后地图与检索重排只读取本地缓存。默认地图模式严格要求真实 SPECTER2；在线候选和全文片段重排默认优先使用 SPECTER2，并在不可用时记录降级原因。测试或故障排查可显式设置 `LITAUDIT_MAP_EMBEDDER=hash`、`LITAUDIT_RERANK_EMBEDDER=hash`。

在线检索 run 还会生成 `output/citation_graph.json`，保存核心候选的一跳参考/施引关系、引用上下文与请求状态。证据审计会生成 `output/fulltext_index.json`，以 BM25 召回和 SPECTER2 重排全文片段，并保留论文 ID、PDF 页码和片段哈希。

## 命令行

```powershell
python -m src.cli run --offline --run-id phase2-real
python -m src.cli run --online --question "你的科研问题"
python -m src.cli ask --offline "PaperQA LitQA"
python -m src.cli replay --list
python -m src.cli replay <run_id>
python -m src.cli evaluate
python -m pytest -q
```

## DeepSeek 配置

```powershell
Copy-Item .env.example .env
```

```dotenv
LITAUDIT_LLM_API_KEY=你的密钥
LITAUDIT_LLM_BASE_URL=https://api.deepseek.com/v1
LITAUDIT_LLM_MODEL=deepseek-chat
SEMANTIC_SCHOLAR_API_KEY=你的密钥
OPENALEX_MAILTO=你的邮箱
```

真实 API key 只能放在本地 `.env`，不能写入源码、测试、run 产物或文档。`.env` 及其环境变体已加入 Git 忽略规则。没有配置 LLM 或 LLM 请求失败时，系统只报告 AI 服务状态，不生成固定选择题、固定总论或固定主题回答，也不会把失败伪装成成功结果。

## 目录结构

```text
data/                                  本地候选、Claim、Evidence、反证和缓存
runs/<run_id>/                         一次独立、可回放的检索运行
src/conversation.py                    DeepSeek 路由、回答和会话持久化
src/retrieve.py                        arXiv / OpenAlex / Semantic Scholar
src/live_ingest.py                     在线候选去重、编号和写入
src/screen_rules.py                    标题摘要筛选规则
src/schema.py                          Pydantic 数据契约和校验
src/map_builder.py                     研究地图关系构建
src/ui/server.py                       本地 HTTP 服务和 API
src/ui/static/                         前端页面、对话和审计模块
skills/conversational-research-routing/ 连续研究对话路由 Skill
docs/research_scope.md                 冻结的研究范围
```

## 已知边界

- 在线论文默认先做标题摘要级筛选；可按需获取 arXiv、OpenAlex 或 Semantic Scholar 声明的开放 PDF。扫描文档 OCR、付费全文获取和自动语义判决尚未实现。
- 系统不会自动生成跨论文确定性长综述。
- 研究地图是 SPECTER2 语义相似图，不是引用图谱；边表示 Title + Abstract 的向量相似，不代表证据支持。
- 在线筛选仍是规则与关键词辅助，不能替代人工判断或领域语义模型。
- API 来源可能限流或失败，失败状态必须保留并在结果中说明。
- 可追溯性评测关注证据定位和审计链路，不是模型准确率排行榜。

## 开发检查

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m pytest -q
node --test tests/ui_scope.test.cjs
git diff --check
```

涉及筛选、run 隔离、证据状态、对话持久化或在线来源的修改，应同时增加回归测试，并更新 `docs/agent_log.md` 和 `docs/current_delivery_report.md`。
