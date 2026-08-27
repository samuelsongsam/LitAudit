# LitAudit

可核验的文献调研智能体。输入一个科研问题或 idea，输出筛选漏斗、研究地图、论断-证据卡和反证据报告，而不是一篇无法回溯的长综述。

默认可在线调用 arXiv、OpenAlex 和 Semantic Scholar，在金标候选上扩检索、去重、按标题/摘要规则筛选，并写入新的 run。`--offline` 仍用于回放已落盘快照和 pytest。`verified` 只覆盖已核对的摘录，不能伪装成整篇论文读完。在线新论文不会自动变成页码级证据，也不会把 `claim-008` 改成 supported。

## 快速开始

Python ≥ 3.10。在仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline --run-id phase2-real
python -m src.cli evaluate
python -m src.cli replay --list
python -m src.cli ui --run-id phase2-real
```

浏览器打开终端打印的地址，默认 [http://127.0.0.1:8787/?run=phase2-real](http://127.0.0.1:8787/?run=phase2-real)。界面「在线检索」会请求公开学术 API 并生成新的 `live_...` run；「仅本地」只在当前候选里做关键词重叠；「重跑快照」离线重写 `phase2-real`。左侧 01–05 切换漏斗、地图、证据、证伪、评测。

在线扩候选（不写综述）：

```powershell
python -m src.cli run --online --question "检索增强大模型智能体是否提高科学文献问答的证据可追溯性？"
python -m src.cli ask --online "检索增强是否提高科学文献问答的证据可追溯性？"
python -m src.cli ask --offline "PaperQA LitQA"
```

无网络或只回放金标：

```powershell
python -m src.cli run --offline --run-id phase2-real
python -m src.cli run --fixture --run-id demo
```

Semantic Scholar 无密钥时经常返回 HTTP 429，界面和 `retrieval_runs.jsonl` 必须显示为 `rate_limited`，不能当成零结果成功。可选：复制 `.env.example` 为 `.env`，填写 `SEMANTIC_SCHOLAR_API_KEY` 和 `OPENALEX_MAILTO`。

测试：

```powershell
python -m pytest -q
```

## 目录

```text
data/                      真实候选、卡片、论断、证据、反证据
data/cache/                检索原始响应与本地 PDF
data/gold_standard/        小型可复核评测题
src/schema.py              字段校验
src/pipeline.py            离线快照或在线合并检索
src/retrieve.py            arXiv / OpenAlex / Semantic Scholar
src/screen_rules.py        标题摘要纳排规则
src/map_builder.py         主线 / 冲突边 / 矛盾对
src/ask.py                 当前候选上的关键词重叠
src/ui/                    勘验工作台（漏斗 / 地图 / 证据 / 证伪 / 评测）
runs/<run_id>/             一次可回放运行
docs/contest_technical_report.md  比赛技术文档底稿
docs/demo_script.md        演示脚本
docs/submission_checklist.md 提交清单
```

## 当前数据状态

- 主问题见 `docs/research_scope.md`
- 7 篇金标候选：2 include，5 exclude，0 pending
- 8 条 Claim、14 条页码级 Evidence、2 条 FalsificationHit
- `claim-008` 因正反证据冲突保持 pending
- 比赛材料入口：`docs/current_delivery_report.md`

## 已知限制

- 在线筛选是规则，不是全文审阅；拿不准标 pending
- 研究地图的边来自证据冲突和反证据，不是引用图谱
- `pdf_partial_verified` 不是全文逐页审阅完毕
- Semantic Scholar 批量请求曾返回 HTTP 429，必须显示为失败
