# LitAudit

可核验的文献调研智能体。输入一个科研问题或 idea，输出筛选漏斗、研究地图、论断-证据卡和反证据报告，而不是一篇无法回溯的长综述。

当前仓库处于 **B 第一轮工程骨架**：可以离线校验 A 的数据、生成 `run_id`、回放结果，并打开四屏 Demo。不会调用检索 API，也不会把 `pending` 伪装成已纳入结论。

## 快速开始

Python ≥ 3.10。在仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline
python -m src.cli replay --list
python -m src.cli ui
```

离线样例（不混入真实论文统计）：

```powershell
python -m src.cli run --fixture --run-id demo
python -m src.cli replay demo
python -m src.cli ui --run-id demo
```

测试：

```powershell
python -m pytest -q
```

## 角色边界

| 角色 | 负责 |
|---|---|
| A 研究与可信度 | 研究范围、检索/筛选、论断、证据、反证据规则、指标 |
| B 产品与工程 | 数据契约落地、流水线、缓存/回放、四屏 UI、README |

B 不改变 `decision` / `status` 语义，不填充 `null` 作者或摘要，不把缺失证据写成确定结论。

## 目录

```text
data/                 A 的真实候选与筛选日志
data/fixtures/        虚构 schema 样例，不计入真实统计
src/schema.py         字段校验
src/pipeline.py       离线读取 -> run_id -> JSON 落盘
src/replay.py         回放已有 run
src/ui/               漏斗 / 地图 / 证据卡 / 证伪报告
runs/<run_id>/        一次可回放运行
docs/                 范围、契约、交接
```

## 当前数据状态（A Phase 1）

- 主问题见 `docs/research_scope.md`
- 5 篇候选：3 pending，2 exclude，0 include
- 摘要和作者均为 `null`，界面会原样显示，不会填默认值
- 还没有真实 `claims.jsonl` / `evidence.jsonl` / `paper_cards.jsonl`

## 已知限制

- 只支持 `--offline` / `--fixture`。在线 arXiv 请求此前已失败，本轮不重试网络。
- 研究地图只有论文节点，没有主线和矛盾对，等待 A 的论文卡片。
- 证据卡和证伪报告在真实 run 中为空状态；fixture run 用于演示字段，不能当研究结果。
