# LitAudit

可核验的文献调研智能体。输入一个科研问题或 idea，输出筛选漏斗、研究地图、论断-证据卡和反证据报告，而不是一篇无法回溯的长综述。

当前仓库是可离线回放的部分全文核验快照：pipeline 读取 papers、paper_cards、claim_decisions 和 retrieval_runs；界面展示漏斗、主线/矛盾对、论断-证据卡、反证据和评测对照。在线 API 不由 pipeline 自动调用。`verified` 只覆盖已核对的摘录，不能伪装成整篇论文读完。

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

浏览器打开终端打印的地址，默认 [http://127.0.0.1:8787/?run=phase2-real](http://127.0.0.1:8787/?run=phase2-real)。左侧 01–05 切换漏斗、地图、证据、证伪、评测；数字键 1–5 同样可用。这是独立勘验工作台，不再使用 Streamlit。

本地提问（不写综述）：

```powershell
python -m src.cli ask "检索增强是否提高科学文献问答的证据可追溯性？"
```

离线 fixture（不混入真实论文统计）：

```powershell
python -m src.cli run --fixture --run-id demo
python -m src.cli replay demo
```

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
src/pipeline.py            离线读取 -> run_id -> JSON 落盘
src/map_builder.py         主线 / 冲突边 / 矛盾对
src/ask.py                 本地问题检索
src/ui/                    勘验工作台（漏斗 / 地图 / 证据 / 证伪 / 评测）
runs/<run_id>/             一次可回放运行
docs/contest_technical_report.md  比赛技术文档底稿
docs/demo_script.md        演示脚本
docs/submission_checklist.md 提交清单
```

## 当前数据状态

- 主问题见 `docs/research_scope.md`
- 7 篇候选：2 include，5 exclude，0 pending
- 8 条 Claim、14 条页码级 Evidence、2 条 FalsificationHit
- `claim-008` 因正反证据冲突保持 pending
- 比赛材料入口：`docs/current_delivery_report.md`

## 已知限制

- pipeline 只支持 `--offline` / `--fixture`
- 研究地图的边来自证据冲突和反证据，不是引用图谱
- `pdf_partial_verified` 不是全文逐页审阅完毕
- Semantic Scholar 批量请求曾返回 HTTP 429，必须显示为失败
