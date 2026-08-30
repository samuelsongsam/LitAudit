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
  -> 标题与摘要规则筛选
  -> 写入独立 live_<时间>_<随机标识> run
  -> DeepSeek 根据当前 run 生成总论
  -> 对话、论文、研究地图和审计模块按 run 展示
```

每次在线检索都会产生新的 `live_*` run，不覆盖本地基准数据。每个历史对话绑定一个 run；论文、检索记录、Claim、Evidence、反证、地图和评测都必须从当前 run 读取。

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

在线新论文目前只完成标题和摘要级筛选，不自动下载全文、不自动抽取页码证据，也不会把 Claim 自动标记为 `supported`。

筛选规则必须区分研究主题和输出形式。“综述”“深入分析”“性能对比”是输出要求，不能直接当作论文主题词。自定义主题筛选不能只因为论文包含 `literature review` 或 `systematic review` 就纳入；应同时检查领域锚点、对象、方法和任务等实质性词项。当前规则属于工程筛选，不等同于语义模型判断或人工全文审阅。

## 审计模块

对话回复包含论文筛选、研究地图、证据核验、反证检查和可追溯性评测入口。进入模块时地址携带当前对话的 `run_id`；模块只读取当前 run，显示所属对话和返回对话按钮。在线 run 会过滤继承的本地基准论文，避免 PaperQA、SciMON 等基准数据混入其他主题。

研究地图中的论文是节点，有向边只来自已落盘的证据冲突或反证关系。关键词重叠不能自动产生证据边，引用关系图算法尚未接入。节点支持拖动、画布平移和缩放。

证据规则：没有 Evidence 的 Claim 不能标记为 `supported`；正反证据冲突时必须保持 `pending`；`pdf_partial_verified` 只表示摘录和定位已核对；在线 `live_abstract` 结果不能作为页码级证据。

## 安装与启动

要求 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.cli doctor
python -m src.cli validate
python -m src.cli ui --run-id phase2-real
```

浏览器访问 `http://127.0.0.1:8787/?run=phase2-real`。在线 UI 可使用：

```powershell
python -m src.cli ui --run-id phase2-real --port 8787 --no-browser
```

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

- 在线论文只有标题摘要级筛选，没有自动全文页码核验。
- 系统不会自动生成跨论文确定性长综述。
- 研究地图不是引用图谱；同被引、文献耦合、PageRank、Node2Vec 尚未接入。
- 在线筛选仍是规则与关键词辅助，不能替代人工判断或领域语义模型。
- API 来源可能限流或失败，失败状态必须保留并在结果中说明。
- 可追溯性评测关注证据定位和审计链路，不是模型准确率排行榜。

## 开发检查

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m pytest -q
git diff --check
```

涉及筛选、run 隔离、证据状态、对话持久化或在线来源的修改，应同时增加回归测试，并更新 `docs/agent_log.md` 和 `docs/current_delivery_report.md`。
